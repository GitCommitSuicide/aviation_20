"""
servers/aviation_server/tools/flight_tracking.py
==================================================
track_flight_live — live position/status tracking.

Provider order:
  1. AeroDataBox (primary) — richest live data: lat/lon, altitude, speed,
     terminals, gates.
  2. AirLabs /flights (fallback) — real-time ADS-B radar covering all
     airborne flights globally. Returns position, altitude, speed, heading.

Live tracking requires the flight to be currently airborne.
"""

import datetime
import json
import os

from servers.aviation_server.config import HAS_AIRLABS, get_logger
from servers.aviation_server.providers import aerodatabox, airlabs
from servers.aviation_server.providers.normalize import (
    normalize_aerodatabox_flight,
    normalize_airlabs_flight,
    validate_flight_record,
)
from servers.aviation_server.formatting import format_flight_record
from servers.aviation_server.persistence import save_flights

logger = get_logger(__name__)


def _fmt_live(flight_iata: str, item: dict) -> str:
    """Format a single AirLabs /flights radar result into a readable string."""
    lat = item.get("lat", "N/A")
    lng = item.get("lng", "N/A")
    alt = item.get("alt", "N/A")
    speed = item.get("speed", "N/A")
    heading = item.get("dir", "N/A")
    status = (item.get("status") or "unknown").title()
    dep = item.get("dep_iata", "?")
    arr = item.get("arr_iata", "?")
    aircraft = item.get("aircraft_icao", "")
    reg = item.get("reg_number", "")
    updated = item.get("updated", "")

    lines = [
        f"**✈️ LIVE TRACKING — {flight_iata}** *(via AirLabs ADS-B)*\n",
        f"- **Route:** `{dep}` → `{arr}`",
        f"- **Status:** {status}",
        f"- **Position:** {lat}°N, {lng}°E",
        f"- **Altitude:** {alt} m",
        f"- **Speed:** {speed} km/h",
        f"- **Heading:** {heading}°",
    ]
    if aircraft:
        lines.append(f"- **Aircraft:** {aircraft}" + (f" ({reg})" if reg else ""))
    if updated:
        import datetime as _dt
        try:
            ts = _dt.datetime.fromtimestamp(int(updated)).strftime("%H:%M:%S")
            lines.append(f"- **Last Updated:** {ts}")
        except Exception:
            pass
    return "\n".join(lines)


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

    # ── 1. Try AeroDataBox ───────────────────────────────────────────────
    ok, payload = aerodatabox.get_flight_live(flight_number)

    # DEBUG: Save raw payload
    try:
        os.makedirs("debug_data", exist_ok=True)
        with open(f"debug_data/{flight_number}_tracking.json", "w") as f:
            json.dump(payload, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save debug data: {e}")

    if ok and isinstance(payload, list) and payload:
        records = [validate_flight_record(normalize_aerodatabox_flight(item, flight_number)) for item in payload]
        records = [
            r for r in records
            if r.get("departure", {}).get("iata") and r.get("arrival", {}).get("iata")
        ]
        if records:
            save_flights(records, flight_number, datetime.datetime.now().strftime("%Y-%m-%d"))
            live_records = [r for r in records if r.get("movement")]
            chosen = live_records or records
            blocks = [format_flight_record(r, route_label=f"Route {i}") for i, r in enumerate(chosen, 1)]
            return "LIVE_TRACKING_DATA:\n" + "\n\n====================\n\n".join(blocks)

    aerodatabox_error = payload if not ok else "NO_USABLE_DATA"
    logger.info("AeroDataBox live tracking unavailable (%s) — trying AirLabs for %s", aerodatabox_error, flight_number)

    # ── 2. Fall back to AirLabs /flights (ADS-B radar) ───────────────────
    if HAS_AIRLABS:
        ok2, payload2 = airlabs.get_live_flights(flight_iata=flight_number)
        if ok2:
            flights = payload2 if isinstance(payload2, list) else [payload2] if isinstance(payload2, dict) else []
            flights = [f for f in flights if f.get("lat") is not None]
            if flights:
                blocks = [_fmt_live(flight_number, f) for f in flights[:3]]
                return "LIVE_TRACKING_DATA:\n" + "\n\n====================\n\n".join(blocks)
            # Flight found but not airborne
            if isinstance(payload2, (list, dict)):
                # Normalize for schedule display
                items = payload2 if isinstance(payload2, list) else [payload2]
                if items:
                    record = validate_flight_record(normalize_airlabs_flight(items[0], flight_number))
                    if record.get("departure", {}).get("iata"):
                        return (
                            f"Flight {flight_number} is currently not airborne (status: "
                            f"{record.get('status', 'unknown')}). "
                            "Here is the latest schedule data:\n\n"
                            + format_flight_record(record)
                        )

    # ── 3. All tracking sources failed ───────────────────────────────────
    if aerodatabox_error == "NO_KEY" and not HAS_AIRLABS:
        return "Live tracking is unavailable (missing RAPID_API_KEY and AIRLABS_API)."
    if aerodatabox_error in ("NO_CONTENT", "NOT_FOUND"):
        return f"No live tracking details found for {flight_number} — it may not be airborne right now."
    if aerodatabox_error == "RATE_LIMITED":
        return "FLIGHT_DATA_UNAVAILABLE: The flight API is rate-limited right now. No real data was retrieved."
    return f"Error fetching live tracking for {flight_number}: {aerodatabox_error}"
