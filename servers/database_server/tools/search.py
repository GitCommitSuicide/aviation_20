"""
servers/database_server/tools/search.py
==========================================
search_database — single unified entry point over the local cache,
dispatching by `query_type`. Kept for compatibility with the original
single-tool design and because some agents/prompts find one flexible tool
easier to steer than four narrow ones. Internally it just calls the same
granular functions exposed as their own tools (airports.py, airlines.py,
flights.py) — no logic is duplicated.
"""

from servers.database_server.tools._common import make_result
from servers.database_server.tools.airports import get_airport_info
from servers.database_server.tools.airlines import get_airline_info
from servers.database_server.tools.flights import get_flight_status_cached, get_route_cached


def search_database(
    query_type: str,
    query: str = "",
    flight_number: str = "",
    date: str = "",
    origin: str = "",
    destination: str = "",
    currency: str = "INR",
) -> dict:
    """
    Query the local PostgreSQL aviation cache BEFORE calling any external
    (aviation-server) tool. Always call this first. If it returns
    found=True AND fresh=True, use the data directly — don't call
    get_flight_details / get_flights_by_route on the aviation server.

    Args:
        query_type: One of: "airport", "airline", "flight", "route"
        query: Free-text search term (airport/airline lookups)
        flight_number: IATA flight number, e.g. "AI101" (flight lookup)
        date: YYYY-MM-DD (flight/route lookup)
        origin: Departure IATA code, e.g. "DEL" (route lookup)
        destination: Arrival IATA code, e.g. "BOM" (route lookup)
        currency: Currency code, e.g. "INR" (route lookup)

    Returns a dict: {source, found, fresh, data, note}.
    """
    qt = (query_type or "").strip().lower()

    try:
        if qt == "airport":
            return get_airport_info(query)
        elif qt == "airline":
            return get_airline_info(query)
        elif qt == "flight":
            return get_flight_status_cached(flight_number, date)
        elif qt == "route":
            return get_route_cached(origin, destination, date, currency)
        else:
            return make_result(False, False, [], f"Unknown query_type '{query_type}'. Use: airport, airline, flight, route")
    except Exception as exc:
        return make_result(False, False, [], f"Database search failed: {str(exc)}. Try the aviation server instead.")
