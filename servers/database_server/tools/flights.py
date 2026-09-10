"""
servers/database_server/tools/flights.py
===========================================
get_flight_status_cached — cached flight-status lookup by flight number.
get_route_cached         — cached route/itinerary-search lookup.

Both mirror what the aviation server's live tools return, but read
EXCLUSIVELY from the local PostgreSQL cache — no external API calls happen
here. The chat agent should always try these first.
"""

from shared.db.connection import get_connection_context
from shared.db.repositories.flight_repository import get_flight, search_flights_by_route
from shared.db.repositories.route_repository import get_latest_route_search
from shared.db.repositories.airport_repository import get_airport_by_iata
from shared.cache import is_fresh, FLIGHT_CACHE_MINUTES, ROUTE_CACHE_MINUTES
from servers.database_server.tools._common import make_result


def get_flight_status_cached(flight_number: str, date: str = "") -> dict:
    """
    Look up a flight's cached status by flight number (and optional date).

    Args:
        flight_number: IATA flight number, e.g. "AI101".
        date: Optional YYYY-MM-DD date filter.
    """
    if not flight_number:
        return make_result(False, False, [], "flight_number is required")

    with get_connection_context() as conn:
        rows = get_flight(conn, flight_number, date or None)

    if not rows:
        return make_result(False, False, [], f"Flight {flight_number} not found in database" + (f" for {date}" if date else ""))

    fetch_times = [r.get("fetch_at") for r in rows if r.get("fetch_at")]
    latest_fetch = max(fetch_times) if fetch_times else None
    fresh = is_fresh(latest_fetch, FLIGHT_CACHE_MINUTES)

    return make_result(
        True, fresh, rows,
        f"Found {len(rows)} flight record(s) for {flight_number}."
        + (" Data is fresh." if fresh else " Data is stale — a live lookup is recommended."),
    )


def get_route_cached(origin: str, destination: str, date: str = "", currency: str = "INR") -> dict:
    """
    Look up cached flights/itineraries for a route (origin -> destination).

    Args:
        origin: Departure IATA code, e.g. "DEL".
        destination: Arrival IATA code, e.g. "BOM".
        date: Optional YYYY-MM-DD travel date filter.
        currency: Currency code used for cached price data, e.g. "INR".
    """
    if not origin or not destination:
        return make_result(False, False, [], "origin and destination IATA codes are required")

    with get_connection_context() as conn:
        origin_row = get_airport_by_iata(conn, origin)
        dest_row = get_airport_by_iata(conn, destination)

        if not origin_row or not dest_row:
            return make_result(False, False, [], f"Airport {'origin' if not origin_row else 'destination'} not in database")

        route_rec = get_latest_route_search(
            conn, origin_row["airport_id"], dest_row["airport_id"],
            travel_date=date or None, currency=currency or None,
        )
        if not route_rec:
            return make_result(False, False, [], f"No route search cached for {origin}->{destination}")

        fresh = is_fresh(route_rec.get("fetch_at"), ROUTE_CACHE_MINUTES)
        flight_rows = search_flights_by_route(conn, origin, destination, date or None)

    return make_result(
        found=True, fresh=fresh, data=flight_rows,
        note=f"Route {origin}->{destination} cached. " + ("Fresh — using DB data." if fresh else "Stale — a live lookup is recommended."),
    )
