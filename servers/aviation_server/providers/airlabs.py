"""
servers/aviation_server/providers/airlabs.py
=============================================
Thin wrapper around the AirLabs Data API (https://airlabs.co/api/v9/).

AirLabs is used as:
  - Fallback for flight status when AeroDataBox returns no data
  - Primary source for live ADS-B radar tracking
  - Sole source for airport schedules, airport info, airline info, nearby airports

Every public function returns a tuple (ok, payload):
    ok=True,  payload=<parsed JSON: dict or list[dict]>  -> success
    ok=False, payload=<error code string>                -> caller decides

Error codes returned when ok=False:
    "NO_KEY"       - AIRLABS_API is not configured
    "NOT_FOUND"    - upstream returned no results
    "RATE_LIMITED" - quota exceeded (minute/hour/month)
    "TIMEOUT"      - request timed out
    "HTTP_<code>"  - any other HTTP error
    "ERROR:<msg>"  - unexpected exception
"""

import requests

from servers.aviation_server.config import (
    AIRLABS_API_KEY,
    HAS_AIRLABS,
    REQUEST_TIMEOUT_SECONDS,
    get_logger,
)

logger = get_logger(__name__)

BASE_URL = "https://airlabs.co/api/v9"


def _get(endpoint: str, params: dict | None = None) -> tuple[bool, object]:
    """Internal helper -- adds api_key to all requests."""
    if not HAS_AIRLABS:
        return False, "NO_KEY"
    p = {"api_key": AIRLABS_API_KEY}
    if params:
        p.update(params)
    url = f"{BASE_URL}/{endpoint}"
    try:
        resp = requests.get(url, params=p, timeout=REQUEST_TIMEOUT_SECONDS)
        logger.info("GET %s -> %s", url, resp.status_code)
        resp.raise_for_status()
        data = resp.json()
        # AirLabs wraps errors in {"error": {"message": "...", "code": "..."}}
        if "error" in data:
            err = data["error"]
            code = err.get("code", "unknown")
            if code in ("minute_limit_exceeded", "hour_limit_exceeded", "month_limit_exceeded"):
                return False, "RATE_LIMITED"
            if code == "not_found":
                return False, "NOT_FOUND"
            return False, f"API_ERROR:{err.get('message', code)}"
        return True, data.get("response", data)
    except requests.exceptions.HTTPError as e:
        if e.response is not None:
            if e.response.status_code == 404:
                return False, "NOT_FOUND"
            if e.response.status_code == 429:
                return False, "RATE_LIMITED"
            return False, f"HTTP_{e.response.status_code}"
        return False, "HTTP_UNKNOWN"
    except requests.exceptions.Timeout:
        return False, "TIMEOUT"
    except Exception as exc:
        return False, f"ERROR:{exc}"


# -- Services ------------------------------------------------------------------

def get_flight_info(flight_iata: str) -> tuple[bool, object]:
    """
    /flight -- Detailed flight info: status, schedule times, estimated/actual
    times, live position, aircraft details. Best all-in-one flight endpoint.
    """
    return _get("flight", {"flight_iata": flight_iata.upper()})


def get_live_flights(
    flight_iata: str | None = None,
    dep_iata: str | None = None,
    arr_iata: str | None = None,
    airline_iata: str | None = None,
) -> tuple[bool, object]:
    """
    /flights -- Real-time ADS-B radar. Returns all currently airborne flights
    matching the filter. Live position (lat/lng), altitude, speed, heading.
    """
    params: dict = {}
    if flight_iata:
        params["flight_iata"] = flight_iata.upper()
    if dep_iata:
        params["dep_iata"] = dep_iata.upper()
    if arr_iata:
        params["arr_iata"] = arr_iata.upper()
    if airline_iata:
        params["airline_iata"] = airline_iata.upper()
    return _get("flights", params)


def get_airport_schedules(
    dep_iata: str | None = None,
    arr_iata: str | None = None,
    airline_iata: str | None = None,
    flight_iata: str | None = None,
    limit: int = 30,
) -> tuple[bool, object]:
    """
    /schedules -- Live airport departure/arrival board (up to 10h ahead).
    At least one of dep_iata or arr_iata is required.
    """
    params: dict = {"limit": limit}
    if dep_iata:
        params["dep_iata"] = dep_iata.upper()
    if arr_iata:
        params["arr_iata"] = arr_iata.upper()
    if airline_iata:
        params["airline_iata"] = airline_iata.upper()
    if flight_iata:
        params["flight_iata"] = flight_iata.upper()
    return _get("schedules", params)


def get_airports(search: str | None = None, iata: str | None = None) -> tuple[bool, object]:
    """
    /airports -- Search the global airports database.
    """
    params: dict = {}
    if search:
        params["search"] = search
    if iata:
        params["iata_code"] = iata.upper()
    return _get("airports", params)


def get_airlines(search: str | None = None, iata: str | None = None) -> tuple[bool, object]:
    """
    /airlines -- Search the global airlines database.
    """
    params: dict = {}
    if search:
        params["search"] = search
    if iata:
        params["iata_code"] = iata.upper()
    return _get("airlines", params)


def get_nearby_airports(lat: float, lng: float, dist_km: int = 100) -> tuple[bool, object]:
    """
    /nearby -- Find airports near a GPS coordinate.
    """
    return _get("nearby", {"lat": lat, "lng": lng, "distance": dist_km})


def suggest(query: str) -> tuple[bool, object]:
    """
    /suggest -- Auto-complete search for airports, airlines, and cities.
    """
    return _get("suggest", {"query": query})
