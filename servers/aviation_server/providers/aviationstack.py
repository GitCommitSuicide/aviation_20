"""
servers/aviation_server/providers/aviationstack.py
====================================================
Wrapper around the Aviationstack API — used as a FALLBACK when AeroDataBox
is unavailable (missing key, rate-limited, or genuinely has no data for a
flight). This is a NEW addition versus the original single-provider design.

Free tier notes (aviationstack.com, checked at integration time):
  - 100 requests/month on the free plan, HTTP only (no HTTPS on free tier).
  - Real-time flight status by flight number via `flight_iata`.
  - Live lat/lon/altitude/speed ("live" object) is included for flights
    currently airborne, but is a paid-plan feature on some tiers — treat
    it as best-effort and fall back gracefully if missing.

Because of the low free-tier request budget, this provider is only called
when AeroDataBox fails or is unconfigured — never as a primary source.
"""

import requests

from servers.aviation_server.config import (
    AVIATIONSTACK_API_KEY,
    HAS_AVIATIONSTACK,
    REQUEST_TIMEOUT_SECONDS,
    get_logger,
)

logger = get_logger(__name__)

# Aviationstack's free tier only supports http:// (not https://).
BASE_URL = "http://api.aviationstack.com/v1"


def _get(endpoint: str, params: dict) -> tuple[bool, object]:
    if not HAS_AVIATIONSTACK:
        return False, "NO_KEY"

    query = {"access_key": AVIATIONSTACK_API_KEY, **params}
    url = f"{BASE_URL}/{endpoint}"
    try:
        resp = requests.get(url, params=query, timeout=REQUEST_TIMEOUT_SECONDS)
        logger.info("GET %s -> %s", url, resp.status_code)
        resp.raise_for_status()
        body = resp.json()
    except requests.exceptions.Timeout:
        return False, "TIMEOUT"
    except requests.exceptions.HTTPError as e:
        code = e.response.status_code if e.response is not None else "UNKNOWN"
        return False, f"HTTP_{code}"
    except Exception as exc:
        return False, f"ERROR:{exc}"

    if "error" in body:
        # Aviationstack returns 200 with an {"error": {...}} body on quota/
        # auth problems rather than a non-2xx status code.
        err = body["error"]
        return False, f"API_ERROR:{err.get('code', 'unknown')}:{err.get('message', '')}"

    data = body.get("data", [])
    if not data:
        return False, "NO_CONTENT"
    return True, data


def get_flight_by_number(flight_number: str, date: str | None = None) -> tuple[bool, object]:
    """
    Look up a flight by its IATA flight number, e.g. "AI101". Aviationstack
    doesn't support querying a specific historical date on the free tier —
    `date` is accepted for interface symmetry with AeroDataBox but ignored
    unless the account has a paid plan that supports `flight_date`.
    """
    params = {"flight_iata": flight_number}
    if date:
        params["flight_date"] = date
    return _get("flights", params)


def get_flights_by_route(dep_iata: str, arr_iata: str) -> tuple[bool, object]:
    """Look up scheduled/live flights between two airports today."""
    params = {"dep_iata": dep_iata, "arr_iata": arr_iata}
    return _get("flights", params)
