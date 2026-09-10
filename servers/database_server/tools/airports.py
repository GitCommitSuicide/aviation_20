"""
servers/database_server/tools/airports.py
============================================
get_airport_info — cached airport lookup by name/city/IATA code.
"""

from shared.db.connection import get_connection_context
from shared.db.repositories.airport_repository import search_airports
from shared.cache import is_fresh, hours_to_minutes, AIRPORT_CACHE_HOURS
from servers.database_server.tools._common import make_result


def get_airport_info(query: str) -> dict:
    """
    Look up an airport in the local cache by name, city, or IATA code.

    Args:
        query: Free-text search term, e.g. "Delhi", "DEL", "Heathrow".

    Returns a dict: {source, found, fresh, data, note}. If found=False, the
    aviation server has no equivalent airport-only lookup tool — treat a
    miss here as "unknown airport" rather than something to retry elsewhere.
    """
    if not query:
        return make_result(False, False, [], "query parameter is required")

    with get_connection_context() as conn:
        rows = search_airports(conn, query)

    if not rows:
        return make_result(False, False, [], f"No airport found for '{query}' in database")

    fresh = is_fresh(rows[0].get("fetch_at"), hours_to_minutes(AIRPORT_CACHE_HOURS))
    return make_result(True, fresh, rows, f"Found {len(rows)} airport(s). {'Data is fresh.' if fresh else 'Data may be stale.'}")
