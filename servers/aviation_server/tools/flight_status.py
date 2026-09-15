"""
servers/aviation_server/tools/flight_status.py
================================================
get_flight_details — flight status/schedule lookup by flight number.

Provider order:
  1. AeroDataBox (primary)  — richest data: terminals, gates, live position.
  2. AirLabs /flight (fallback) — excellent all-in-one: status + schedule +
     estimated/actual times + live position + aircraft details.
  3. Aviationstack (last resort) — used only when both above are unconfigured
     or rate-limited.

NOTE ON CACHING: the caller (the chat agent) is expected to try the
database server's `search_database` tool FIRST. This tool is only meant
to be called on a cache miss/stale result — it always hits the live APIs.
"""

import datetime
import json
import os

from servers.aviation_server.config import HAS_AVIATIONSTACK, HAS_AIRLABS, get_logger
from servers.aviation_server.providers import aerodatabox, aviationstack, airlabs
from servers.aviation_server.providers.normalize import (
    normalize_aerodatabox_flight,
    normalize_aviationstack_flight,
    normalize_airlabs_flight,
    validate_flight_record,
)
from servers.aviation_server.formatting import format_flight_records
from servers.aviation_server.persistence import save_flights

logger = get_logger(__name__)


def _valid_route(record: dict) -> bool:
    return bool(record.get("departure", {}).get("iata")) and bool(record.get("arrival", {}).get("iata"))


def get_flight_details(flight_number: str, date: str | None = None) -> str:
    """
    Get flight status (schedule, terminals, gates, delays) for a KNOWN flight
    number. If the flight operates on multiple routes the same day, details
    for ALL of them are returned.

    Args:
        flight_number: IATA flight number, e.g. AA100, BA12, AI101.
        date: Optional YYYY-MM-DD. Only pass this if the user explicitly
              gave a date — otherwise leave it unset.
    """
    logger.info("get_flight_details flight_number=%r date=%r", flight_number, date)
    flight_number = flight_number.replace(" ", "").strip().upper()

    if not date:
        date = datetime.datetime.now().strftime("%Y-%m-%d")
    else:
        try:
            datetime.datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            return f"Invalid date format: {date}. Please use YYYY-MM-DD."

    # ── 1. Try AeroDataBox ───────────────────────────────────────────────
    ok, payload = aerodatabox.get_flight_by_number(flight_number, date)

    # DEBUG: Save raw payload
    try:
        os.makedirs("debug_data", exist_ok=True)
        with open(f"debug_data/{flight_number}_status.json", "w") as f:
            json.dump(payload, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save debug data: {e}")

    if ok and isinstance(payload, list):
        records = [validate_flight_record(normalize_aerodatabox_flight(item, flight_number)) for item in payload]
        records = [r for r in records if _valid_route(r)]
        if records:
            save_flights(records, flight_number, date)
            return format_flight_records(records, flight_number, date)

    aerodatabox_error = payload if not ok else "NO_USABLE_DATA"

    # ── 2. Fall back to AirLabs /flight ──────────────────────────────────
    if HAS_AIRLABS:
        logger.info("AeroDataBox unavailable (%s) — trying AirLabs for %s", aerodatabox_error, flight_number)
        ok2, payload2 = airlabs.get_flight_info(flight_number)
        if ok2 and isinstance(payload2, dict) and payload2:
            record = validate_flight_record(normalize_airlabs_flight(payload2, flight_number))
            if _valid_route(record):
                save_flights([record], flight_number, date)
                result = format_flight_records([record], flight_number, date)
                return (
                    "[Note: Primary data source was unavailable — "
                    "data below is from AirLabs instead.]\n\n" + result
                )

    # ── 3. Fall back to Aviationstack ────────────────────────────────────
    if HAS_AVIATIONSTACK:
        logger.info("AeroDataBox and AirLabs unavailable — falling back to Aviationstack for %s", flight_number)
        ok3, payload3 = aviationstack.get_flight_by_number(flight_number, date)
        if ok3 and isinstance(payload3, list):
            records = [validate_flight_record(normalize_aviationstack_flight(item)) for item in payload3]
            records = [r for r in records if _valid_route(r)]
            if records:
                save_flights(records, flight_number, date)
                result = format_flight_records(records, flight_number, date)
                return (
                    "[Note: Primary data sources were unavailable — "
                    "data below is from Aviationstack instead.]\n\n" + result
                )

    # ── 4. All providers failed ──────────────────────────────────────────
    if aerodatabox_error == "NO_KEY" and not HAS_AVIATIONSTACK and not HAS_AIRLABS:
        return "Flight lookup is unavailable: no RAPID_API_KEY, AIRLABS_API, or AVIATIONSTACK_API_KEY configured."
    if aerodatabox_error == "NOT_FOUND":
        return f"Flight {flight_number} was not found for {date}."
    if aerodatabox_error == "RATE_LIMITED":
        return (
            "FLIGHT_DATA_UNAVAILABLE: All flight data providers are currently rate-limited. "
            "Do not guess or estimate a schedule."
        )
    return f"No flight details found for {flight_number} on {date}."
