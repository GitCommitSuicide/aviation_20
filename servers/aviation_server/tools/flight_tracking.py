"""
servers/aviation_server/tools/flight_tracking.py
==================================================
track_flight_live — live position/status tracking via AeroDataBox.

Live position (lat/lon/altitude/speed) is an AeroDataBox-only feature in
this build; Aviationstack's `live` object is included as a bonus in
formatting.py/normalize.py if it ever comes back populated, but there's no
dedicated fallback call here since live tracking is a paid-tier feature on
most free aviation APIs. See the project README for a free live-tracking
alternative (OpenSky Network).
"""

import datetime
import json
import os

from servers.aviation_server.config import get_logger
from servers.aviation_server.providers import aerodatabox
from servers.aviation_server.providers.normalize import (
    normalize_aerodatabox_flight,
    validate_flight_record,
)
from servers.aviation_server.formatting import format_flight_record
from servers.aviation_server.persistence import save_flights

logger = get_logger(__name__)


def track_flight_live(flight_number: str) -> str:
    """
    Track a flight's LIVE position, status, terminals, gates, and delays.
    Use this when the user asks to TRACK or see the LIVE POSITION of a
    flight.

    Args:
        flight_number: IATA flight number, e.g. AI101, 6E123.
    """
    logger.info("track_flight_live flight_number=%r", flight_number)
    flight_number = flight_number.replace(" ", "").strip().upper()

    ok, payload = aerodatabox.get_flight_live(flight_number)

    # DEBUG: Save raw payload
    try:
        os.makedirs("debug_data", exist_ok=True)
        with open(f"debug_data/{flight_number}_tracking.json", "w") as f:
            json.dump(payload, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save debug data: {e}")

    if not ok:
        if payload == "NO_KEY":
            return "Live tracking is unavailable (missing RAPID_API_KEY)."
        if payload == "NO_CONTENT":
            return f"No live tracking details found for {flight_number}."
        if payload == "NOT_FOUND":
            return f"Flight {flight_number} was not found."
        if payload == "RATE_LIMITED":
            return "FLIGHT_DATA_UNAVAILABLE: The flight API is rate-limited right now. No real data was retrieved."
        return f"Error fetching live tracking for {flight_number}: {payload}"

    if not isinstance(payload, list) or not payload:
        return f"No flight details found for {flight_number}."

    records = [validate_flight_record(normalize_aerodatabox_flight(item, flight_number)) for item in payload]
    records = [
        r for r in records
        if r.get("departure", {}).get("iata") and r.get("arrival", {}).get("iata")
    ]
    if not records:
        return f"No flight details with known origin and destination found for {flight_number}."

    save_flights(records, flight_number, datetime.datetime.now().strftime("%Y-%m-%d"))

    live_records = [r for r in records if r.get("movement")]
    chosen = live_records or records

    blocks = [format_flight_record(r, route_label=f"Route {i}") for i, r in enumerate(chosen, 1)]
    return "LIVE_TRACKING_DATA:\n" + "\n\n====================\n\n".join(blocks)
