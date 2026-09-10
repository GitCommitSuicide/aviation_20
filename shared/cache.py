"""
tools/cache.py
==============
Centralised cache-freshness configuration and utility for the Aviation Chatbot.

Every table that caches API data stores a `fetch_at TIMESTAMPTZ` column.
Call `is_fresh(fetch_at, max_age_minutes)` to decide whether the cached row
is still usable or whether the external API must be called again.
"""

import datetime
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configurable freshness periods
# ---------------------------------------------------------------------------
# Real-time flight status changes frequently → short TTL.
# Static reference data (airports, airlines, aircraft) → long TTL (1 week).

FLIGHT_CACHE_MINUTES:   int = 10
ROUTE_CACHE_MINUTES:    int = 60    # route search results
AIRPORT_CACHE_HOURS:    int = 168   
AIRLINE_CACHE_HOURS:    int = 168
AIRCRAFT_CACHE_HOURS:   int = 168
SCHEDULE_CACHE_DAYS:    int = 30    # re-derive weekly pattern at most once a month


# ---------------------------------------------------------------------------
# Helper — convert hours to minutes for a uniform interface
# ---------------------------------------------------------------------------

def hours_to_minutes(hours: int) -> int:
    return hours * 60


# ---------------------------------------------------------------------------
# Core freshness check
# ---------------------------------------------------------------------------

def is_fresh(fetch_at, max_age_minutes: int) -> bool:
    """
    Return True if `fetch_at` is within `max_age_minutes` of now.

    Args:
        fetch_at: A timezone-aware datetime object (as returned by psycopg
                  from a TIMESTAMPTZ column), or None.
        max_age_minutes: Maximum acceptable age in minutes.

    Returns:
        False if fetch_at is None (treat missing timestamp as stale).
        True  if the record is still within the freshness window.
        False if the record is older than max_age_minutes.
    """
    if fetch_at is None:
        logger.debug("is_fresh: fetch_at is None -> stale")
        return False

    # Ensure we compare timezone-aware datetimes
    now = datetime.datetime.now(tz=datetime.timezone.utc)

    # psycopg returns TIMESTAMPTZ as aware datetime; handle naive just in case
    if fetch_at.tzinfo is None:
        fetch_at = fetch_at.replace(tzinfo=datetime.timezone.utc)

    age_minutes = (now - fetch_at).total_seconds() / 60
    fresh = age_minutes <= max_age_minutes

    logger.debug(
        "is_fresh: age=%.1f min, max=%d min -> %s",
        age_minutes, max_age_minutes, "FRESH" if fresh else "STALE",
    )
    return fresh


def is_past_date(query_date) -> bool:
    """
    Return True if query_date is strictly before today (UTC date).

    A completed flight is a historical fact — its data will never change,
    so the 10-minute FLIGHT_CACHE_MINUTES TTL is irrelevant for past dates.
    We treat them as permanently fresh and never re-fetch.

    Args:
        query_date: datetime.date, or a string in 'YYYY-MM-DD' format, or None.

    Returns:
        True  if the date is in the past (before today).
        False if the date is today, in the future, or None.
    """
    if query_date is None:
        return False

    today = datetime.date.today()

    if isinstance(query_date, datetime.datetime):
        query_date = query_date.date()

    if isinstance(query_date, str):
        try:
            query_date = datetime.date.fromisoformat(query_date)
        except ValueError:
            return False

    return query_date < today
