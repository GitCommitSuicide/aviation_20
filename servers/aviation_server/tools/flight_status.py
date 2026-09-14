"""
servers/aviation_server/tools/flight_status.py
================================================
get_flight_details — flight status/schedule lookup by flight number.

Provider order:
  1. AeroDataBox (primary)  — richest data: terminals, gates, live position.
  2. Aviationstack (fallback) — used ONLY when AeroDataBox is unconfigured,
     rate-limited, or returns no usable data. This is the NEW addition:
     the original single-provider app had no fallback, so a RapidAPI
     rate-limit meant a dead end for the user.

NOTE ON CACHING: the caller (the chat agent) is expected to try the
database server's `search_database` tool FIRST. This tool is only meant
to be called on a cache miss/stale result — it always hits the live APIs.
"""

import datetime
import json
import os

from servers.aviation_server.config import HAS_AVIATIONSTACK, get_logger
from servers.aviation_server.providers import aerodatabox, aviationstack
from servers.aviation_server.providers.normalize import (
    normalize_aerodatabox_flight,
    normalize_aviationstack_flight,
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

    # ── 2. Fall back to Aviationstack ────────────────────────────────────
    if HAS_AVIATIONSTACK:
        logger.info("AeroDataBox unavailable (%s) — falling back to Aviationstack for %s", aerodatabox_error, flight_number)
        ok2, payload2 = aviationstack.get_flight_by_number(flight_number, date)
        if ok2 and isinstance(payload2, list):
            records = [validate_flight_record(normalize_aviationstack_flight(item)) for item in payload2]
            records = [r for r in records if _valid_route(r)]
            if records:
                save_flights(records, flight_number, date)
                result = format_flight_records(records, flight_number, date)
                return (
                    "[Note: AeroDataBox was unavailable for this request — "
                    "data below is from Aviationstack instead.]\n\n" + result
                )

    # ── 3. Both providers failed ─────────────────────────────────────────
    if aerodatabox_error == "NO_KEY" and not HAS_AVIATIONSTACK:
        return "Flight lookup is unavailable: no RAPID_API_KEY or AVIATIONSTACK_API_KEY configured."
    if aerodatabox_error == "NOT_FOUND":
        return f"Flight {flight_number} was not found for {date}."
    if aerodatabox_error == "RATE_LIMITED":
        return (
            "FLIGHT_DATA_UNAVAILABLE: AeroDataBox is rate-limited and no fallback "
            "provider returned data. Do not guess or estimate a schedule."
        )
    return f"No flight details found for {flight_number} on {date}."
