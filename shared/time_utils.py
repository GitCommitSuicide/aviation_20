"""
tools/time_utils.py
====================
All time / timezone utilities for the Aviation Chatbot.

Design principles
-----------------
* UTC is always used for storage, arithmetic (duration, delay).
* Local time is always used for user-facing display, using the airport's IANA
  timezone (e.g. "Asia/Kolkata").
* If the timezone is unknown we fall back gracefully: show the UTC value with
  a "(UTC)" label so the user always sees something meaningful.
"""

import datetime
import logging
import re
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import airportsdata

logger = logging.getLogger(__name__)

# ── Pre-load airport library once ──────────────────────────────────────────
_AIRPORTS_BY_IATA = airportsdata.load("IATA")

# ── AeroDataBox UTC string patterns ────────────────────────────────────────
# Examples: "2026-08-24 07:10Z", "2026-08-24T07:10:00Z", "2026-08-24 07:10+00:00"
_UTC_PATTERNS = [
    "%Y-%m-%d %H:%MZ",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%MZ",
    "%Y-%m-%d %H:%M",        # naive fallback (assumed UTC)
    "%Y-%m-%dT%H:%M:%S",     # naive fallback
]


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_utc(raw: Optional[str]) -> Optional[datetime.datetime]:
    """
    Parse any UTC timestamp string from AeroDataBox / SearchAPI into a
    timezone-aware UTC datetime.

    Accepts:
        "2026-08-24 07:10Z"
        "2026-08-24T07:10:00Z"
        "2026-08-24 07:10+05:30"   ← offset-aware; converted to UTC
        "2026-08-24 07:10"         ← naive; assumed UTC

    Returns None if parsing fails or raw is empty.
    """
    if not raw:
        return None

    raw = raw.strip()

    # fromisoformat handles offsets natively in Python 3.7+
    normalized = raw.replace(" ", "T").replace("Z", "+00:00")
    try:
        dt = datetime.datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        else:
            dt = dt.astimezone(datetime.timezone.utc)
        return dt
    except ValueError:
        pass

    # Fallback: try manual strptime patterns
    cleaned = raw.replace("Z", "").strip()
    for fmt in _UTC_PATTERNS:
        try:
            dt = datetime.datetime.strptime(cleaned, fmt)
            return dt.replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            continue

    logger.debug("parse_utc: could not parse %r", raw)
    return None


# ---------------------------------------------------------------------------
# Timezone resolution
# ---------------------------------------------------------------------------

def get_airport_tz(iata_code: Optional[str], db_tz: Optional[str] = None) -> Optional[str]:
    """
    Return the IANA timezone string for an airport.

    Priority:
        1. db_tz   — value already in airports.timezone column (most authoritative)
        2. airportsdata library
        3. None    — caller should default to UTC display

    Args:
        iata_code: 3-letter IATA code, e.g. "BOM"
        db_tz:     timezone string already retrieved from the DB (may be None)
    """
    if db_tz and db_tz.strip():
        return db_tz.strip()

    if iata_code:
        info = _AIRPORTS_BY_IATA.get(iata_code.strip().upper(), {})
        tz = info.get("tz") or info.get("timezone")
        if tz:
            return tz

    return None


def _get_zoneinfo(tz_name: Optional[str]) -> Optional[ZoneInfo]:
    if not tz_name:
        return None
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, KeyError):
        logger.debug("_get_zoneinfo: unknown timezone %r", tz_name)
        return None


# ---------------------------------------------------------------------------
# Conversion & formatting
# ---------------------------------------------------------------------------

def to_local(utc_dt: Optional[datetime.datetime], tz_name: Optional[str]) -> Optional[datetime.datetime]:
    """
    Convert a UTC datetime to the given IANA timezone.
    Returns the UTC datetime unchanged if tz_name is unknown.
    """
    if utc_dt is None:
        return None
    zi = _get_zoneinfo(tz_name)
    if zi is None:
        return utc_dt
    return utc_dt.astimezone(zi)


def fmt_local(
    utc_dt: Optional[datetime.datetime],
    tz_name: Optional[str],
    *,
    fmt: str = "%Y-%m-%d %I:%M %p",
    unknown_label: str = "Unknown",
) -> str:
    """
    Format a UTC datetime as a LOCAL time string with the timezone abbreviation.

    Example outputs:
        "2026-08-24 12:40 PM IST"        ← Asia/Kolkata
        "2026-08-24 07:10 AM UTC"        ← fallback when tz unknown
        "Unknown"                         ← when utc_dt is None

    Args:
        utc_dt:        timezone-aware UTC datetime (from parse_utc or DB)
        tz_name:       IANA timezone string (e.g. "Asia/Kolkata")
        fmt:           strftime format for date+time part
        unknown_label: returned when utc_dt is None
    """
    if utc_dt is None:
        return unknown_label

    # Ensure UTC-awareness
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=datetime.timezone.utc)

    local_dt = to_local(utc_dt, tz_name) or utc_dt

    # Get timezone abbreviation
    tz_abbr = local_dt.strftime("%Z") or ("UTC" if local_dt.tzinfo == datetime.timezone.utc else "")

    return f"{local_dt.strftime(fmt)} {tz_abbr}".strip()


def fmt_utc(
    utc_dt: Optional[datetime.datetime],
    *,
    fmt: str = "%Y-%m-%d %H:%M UTC",
    unknown_label: str = "Unknown",
) -> str:
    """Format a UTC datetime as a plain UTC string (for debug / delay info)."""
    if utc_dt is None:
        return unknown_label
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=datetime.timezone.utc)
    return utc_dt.strftime(fmt)


# ---------------------------------------------------------------------------
# Arithmetic (always UTC — never use local datetimes here)
# ---------------------------------------------------------------------------

def calc_delay(
    sched_utc: Optional[datetime.datetime],
    actual_utc: Optional[datetime.datetime],
) -> str:
    """
    Return a human-readable delay string computed purely in UTC.

    Returns one of:
        "18 min delay"
        "5 min early"
        "On time"
        "No delay info"
    """
    if sched_utc is None or actual_utc is None:
        return "No delay info"

    # Ensure both are UTC-aware
    if sched_utc.tzinfo is None:
        sched_utc = sched_utc.replace(tzinfo=datetime.timezone.utc)
    if actual_utc.tzinfo is None:
        actual_utc = actual_utc.replace(tzinfo=datetime.timezone.utc)

    diff_mins = int((actual_utc - sched_utc).total_seconds() / 60)

    if diff_mins > 0:
        return f"{diff_mins} min delay"
    elif diff_mins < 0:
        return f"{abs(diff_mins)} min early"
    else:
        return "On time"


def calc_duration(
    dep_utc: Optional[datetime.datetime],
    arr_utc: Optional[datetime.datetime],
) -> str:
    """
    Return a human-readable flight duration computed purely in UTC.

    Returns e.g. "2h 35m" or "Unknown".
    """
    if dep_utc is None or arr_utc is None:
        return "Unknown"

    if dep_utc.tzinfo is None:
        dep_utc = dep_utc.replace(tzinfo=datetime.timezone.utc)
    if arr_utc.tzinfo is None:
        arr_utc = arr_utc.replace(tzinfo=datetime.timezone.utc)

    total_mins = int((arr_utc - dep_utc).total_seconds() / 60)
    if total_mins < 0:
        return "Unknown"

    hours, mins = divmod(total_mins, 60)
    if hours > 0:
        return f"{hours}h {mins}m"
    return f"{mins}m"


def fmt_duration_mins(total_minutes: Optional[int]) -> str:
    """Format an integer number of minutes as '2h 35m'."""
    if total_minutes is None:
        return "Unknown"
    hours, mins = divmod(int(total_minutes), 60)
    if hours > 0:
        return f"{hours}h {mins}m"
    return f"{mins}m"
