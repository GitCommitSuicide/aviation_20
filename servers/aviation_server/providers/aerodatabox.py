"""
servers/aviation_server/providers/aerodatabox.py
==================================================
Thin wrapper around the AeroDataBox API (via RapidAPI). This is the PRIMARY
source for flight status, schedule, and live-position data.

Every function returns a tuple (ok, payload):
    ok=True,  payload=<parsed JSON: list[dict] or dict>   -> success
    ok=False, payload=<error code string>                 -> caller decides
                                                              how to react

Error codes returned when ok=False:
    "NO_KEY"        - RAPID_API_KEY is not configured
    "NOT_FOUND"     - upstream 404
    "RATE_LIMITED"  - upstream 429 (caller may fall back to Aviationstack)
    "NO_CONTENT"    - upstream 204 / empty body
    "TIMEOUT"       - request timed out
    "HTTP_<code>"   - any other HTTP error
    "ERROR:<msg>"   - unexpected exception
"""

import requests

from servers.aviation_server.config import (
    RAPID_API_KEY,
    HAS_AERODATABOX,
    REQUEST_TIMEOUT_SECONDS,
    get_logger,
)

logger = get_logger(__name__)

BASE_URL = "https://aerodatabox.p.rapidapi.com"


def _headers() -> dict:
    return {
        "x-rapidapi-key": RAPID_API_KEY,
        "x-rapidapi-host": "aerodatabox.p.rapidapi.com",
    }


def _get(url: str, params: dict | None = None) -> tuple[bool, object]:
    if not HAS_AERODATABOX:
        return False, "NO_KEY"
    try:
        resp = requests.get(url, headers=_headers(), params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        logger.info("GET %s -> %s", url, resp.status_code)
        if resp.status_code == 204:
            return False, "NO_CONTENT"
        resp.raise_for_status()
        return True, resp.json()
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


def get_flight_by_number(flight_number: str, date: str | None = None) -> tuple[bool, object]:
    """
    Fetch flight status by flight number, optionally scoped to a date
    (YYYY-MM-DD). Without a date, AeroDataBox returns near-term occurrences.
    """
    if date:
        url = f"{BASE_URL}/flights/number/{flight_number}/{date}"
    else:
        url = f"{BASE_URL}/flights/number/{flight_number}"
    return _get(url)


def get_flight_live(flight_number: str) -> tuple[bool, object]:
    """Fetch flight status WITH live position/movement data."""
    url = f"{BASE_URL}/flights/number/{flight_number}"
    return _get(url, params={"withLocation": "true", "withAircraftImage": "false"})
