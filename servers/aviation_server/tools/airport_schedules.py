# -*- coding: utf-8 -*-
"""
servers/aviation_server/tools/airport_schedules.py
====================================================
get_airport_schedules -- Live departure/arrival board for any airport.

Uses AirLabs /schedules endpoint which shows real-time flight boards
(like the screens in airport lounges) up to 10 hours ahead.
"""

from servers.aviation_server.config import HAS_AIRLABS, get_logger
from servers.aviation_server.providers import airlabs

logger = get_logger(__name__)

_STATUS_LABEL = {
    "scheduled": "[Scheduled]",
    "en-route": "[En-Route]",
    "landed": "[Landed]",
    "cancelled": "[Cancelled]",
    "delayed": "[Delayed]",
    "diverted": "[Diverted]",
    "unknown": "[Unknown]",
}


def _fmt_time(t):
    if not t:
        return "N/A"
    return t.split(" ")[-1] if " " in t else t


def _fmt_delay(minutes):
    if not minutes or minutes <= 0:
        return ""
    return " (+{}m delay)".format(minutes)


def get_airport_schedules(
    airport_iata: str,
    direction: str = "departures",
    airline_iata: str | None = None,
    limit: int = 20,
) -> str:
    """
    Show the live departure or arrival board for an airport.

    Args:
        airport_iata: IATA airport code, e.g. MAA, DEL, BOM.
        direction: 'departures' to show flights leaving, 'arrivals' to show
                   flights arriving. Defaults to 'departures'.
        airline_iata: Optional airline IATA code to filter (e.g. '6E' for IndiGo).
        limit: Maximum number of flights to show (default 20, max 50).
    """
    logger.info("get_airport_schedules airport=%r direction=%r airline=%r", airport_iata, direction, airline_iata)
    airport_iata = airport_iata.strip().upper()

    if not HAS_AIRLABS:
        return "Airport schedules are unavailable (missing AIRLABS_API key)."

    is_arrival = direction.lower().startswith("arr")
    dep_iata = None if is_arrival else airport_iata
    arr_iata = airport_iata if is_arrival else None

    ok, payload = airlabs.get_airport_schedules(
        dep_iata=dep_iata,
        arr_iata=arr_iata,
        airline_iata=airline_iata,
        limit=min(limit, 50),
    )

    if not ok:
        if payload == "RATE_LIMITED":
            return "Airport schedules are temporarily unavailable (rate limit reached)."
        if payload == "NOT_FOUND":
            return "No schedule data found for airport {}.".format(airport_iata)
        return "Could not fetch schedules for {}: {}".format(airport_iata, payload)

    flights = payload if isinstance(payload, list) else []
    flights = flights[:limit]  # Enforce limit locally since AirLabs might ignore it

    if not flights:
        dir_label = "arrivals" if is_arrival else "departures"
        return "No {} found for {} in the next 10 hours.".format(dir_label, airport_iata)

    board_type = "ARRIVALS" if is_arrival else "DEPARTURES"
    airline_filter = " ({})".format(airline_iata) if airline_iata else ""
    from_or_to = "From" if is_arrival else "To"
    
    lines = []

    for f in flights:
        flight_num = f.get("flight_iata") or f.get("flight_icao") or "N/A"
        airline = f.get("airline_iata", "")
        if is_arrival:
            other_airport = f.get("dep_iata", "N/A")
            sched_time = _fmt_time(f.get("dep_time"))
        else:
            other_airport = f.get("arr_iata", "N/A")
            sched_time = _fmt_time(f.get("dep_time"))

        status_raw = (f.get("status") or "unknown").lower()
        delay = f.get("delayed") or f.get("dep_delayed") or 0
        status_badge = _STATUS_LABEL.get(status_raw, "[?]")
        status_str = "{}{}{}".format(status_badge, " " + status_raw.title() if status_badge != status_raw else "", _fmt_delay(delay))

        # concise summary string
        lines.append(f"{flight_num} {airline} {from_or_to} {other_airport} at {sched_time} ({status_str})")

    import json
    # Provide 1 highly condensed JSON example to save tokens
    example = {}
    if flights:
        raw = flights[0]
        keys_to_keep = ["flight_iata", "airline_iata", "dep_iata", "arr_iata", "dep_time", "status", "dep_terminal", "dep_gate"]
        example = {k: raw.get(k) for k in keys_to_keep if k in raw}
        
    examples_str = json.dumps([example], indent=2)

    return f"**Airport {airport_iata} {board_type}** -- next {len(flights)} flights\n\nRaw Data Example:\n```json\n{examples_str}\n```\n\nAll Flights Summary:\n" + "\n".join(lines)
