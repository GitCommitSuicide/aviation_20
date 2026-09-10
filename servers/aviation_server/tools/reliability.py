"""
servers/aviation_server/tools/reliability.py
==============================================
get_flight_reliability / get_flight_route_info — historical performance
tools. These read stats from the shared DB, and if there isn't enough
history yet, actively backfill by calling AeroDataBox for a window of
recent/near-term dates.
"""

import datetime

from shared.db.connection import get_connection_context
from shared.db.repositories.stats_repository import get_delay_stats, get_flight_routes
from servers.aviation_server.config import get_logger
from servers.aviation_server.providers import aerodatabox
from servers.aviation_server.providers.normalize import normalize_aerodatabox_flight
from servers.aviation_server.persistence import save_flights

logger = get_logger(__name__)

_HISTORY_WINDOW_DAYS = 3  # fetch [-3, +3] days around today


def _backfill_history(flight_number: str) -> None:
    """Fetch a small window of days from AeroDataBox to populate enough
    history for stats calculation. Best-effort — never raises."""
    today = datetime.date.today()
    dates = [today + datetime.timedelta(days=i) for i in range(-_HISTORY_WINDOW_DAYS, _HISTORY_WINDOW_DAYS + 1)]

    for d in dates:
        date_str = d.isoformat()
        ok, payload = aerodatabox.get_flight_by_number(flight_number, date_str)
        if ok and isinstance(payload, list):
            records = [normalize_aerodatabox_flight(item, flight_number) for item in payload]
            records = [r for r in records if r.get("departure", {}).get("iata") and r.get("arrival", {}).get("iata")]
            if records:
                save_flights(records, flight_number, date_str)


def get_flight_reliability(flight_number: str) -> str:
    """
    Answers questions about a flight's reliability, average delays, or how
    often it is on time. e.g. "How reliable is AI101?", "Does AI101 get
    delayed?".
    """
    logger.info("get_flight_reliability flight_number=%r", flight_number)
    flight_number = flight_number.replace(" ", "").strip().upper()

    with get_connection_context() as conn:
        stats = get_delay_stats(conn, flight_number)

    if not stats or any(s.get("total_observations", 0) < 3 for s in stats):
        logger.info("Not enough history for %s — backfilling", flight_number)
        _backfill_history(flight_number)
        with get_connection_context() as conn:
            stats = get_delay_stats(conn, flight_number)

    if not stats:
        return f"I don't have enough historical data to determine the reliability of flight {flight_number}."

    lines = [f"Reliability Statistics for Flight {flight_number}:"]
    for s in stats:
        lines.append(
            f"\nRoute: {s['origin_iata']} -> {s['destination_iata']}\n"
            f"  - Total flights observed: {s['total_observations']}\n"
            f"  - On-time performance:    {s['on_time_percentage']:.1f}%\n"
            f"  - Average delay:          {s['average_delay_mins']} minutes\n"
            f"  - Median delay:           {s['median_delay_mins']} minutes"
        )
    return "\n".join(lines)


def get_flight_route_info(flight_number: str) -> str:
    """
    Answers questions about where a flight normally flies (its route).
    e.g. "What is the usual route for AI101?", "Where does AI101 fly?".
    """
    logger.info("get_flight_route_info flight_number=%r", flight_number)
    flight_number = flight_number.replace(" ", "").strip().upper()

    with get_connection_context() as conn:
        routes = get_flight_routes(conn, flight_number)

    if not routes:
        _backfill_history(flight_number)
        with get_connection_context() as conn:
            routes = get_flight_routes(conn, flight_number)

    if not routes:
        return f"I don't have any route information for flight {flight_number}."

    lines = [f"Observed Routes for Flight {flight_number}:"]
    for r in routes:
        lines.append(f"  - {r['origin_iata']} -> {r['destination_iata']} (Observed {r['observation_count']} times)")
    return "\n".join(lines)
