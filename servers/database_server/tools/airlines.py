"""
servers/database_server/tools/airlines.py
============================================
get_airline_info — cached airline lookup by name/IATA code.
"""

from shared.db.connection import get_connection_context
from shared.db.repositories.airline_repository import search_airlines
from shared.cache import is_fresh, hours_to_minutes, AIRLINE_CACHE_HOURS
from servers.database_server.tools._common import make_result


def get_airline_info(query: str) -> dict:
    """
    Look up an airline in the local cache by name or IATA code.

    Args:
        query: Free-text search term, e.g. "IndiGo", "6E".
    """
    if not query:
        return make_result(False, False, [], "query parameter is required")

    with get_connection_context() as conn:
        rows = search_airlines(conn, query)

    if not rows:
        return make_result(False, False, [], f"No airline found for '{query}' in database")

    fresh = is_fresh(rows[0].get("fetch_at"), hours_to_minutes(AIRLINE_CACHE_HOURS))
    return make_result(True, fresh, rows, f"Found {len(rows)} airline(s). {'Fresh.' if fresh else 'Stale.'}")
