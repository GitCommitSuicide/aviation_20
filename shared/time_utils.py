"""
shared/time_utils.py
====================
All time / timezone utilities for the Aviation Chatbot.

Design principles
-----------------
* UTC is always used for storage, arithmetic (duration, delay).
* Local time (from the API) is always preferred for user-facing display.
* If the API provides a local time string, we use it directly — no conversion.
* If only UTC is available, we convert to local using the airport's IANA timezone.
* If the timezone is unknown we fall back gracefully: show the UTC value with
  a "(UTC)" label so the user always sees something meaningful.
* Delay calculations are ALWAYS done in UTC to avoid timezone arithmetic bugs.
* Pre-departure flights never show "early" predictions — those are unreliable.
"""

import datetime
import logging
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import airportsdata

logger = logging.getLogger(__name__)

# ── Pre-load airport library once ──────────────────────────────────────────
_AIRPORTS_BY_IATA = airportsdata.load("IATA")


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_utc(raw: Optional[str]) -> Optional[datetime.datetime]:
    """
    Parse any timestamp string into a timezone-aware UTC datetime.

    Accepts:
        "2026-08-24 07:10Z"            ← explicit Z
        "2026-08-24T07:10:00Z"         ← ISO with Z
        "2026-08-24 07:10+05:30"       ← offset-aware; converted to UTC
        "2026-08-24 07:10"             ← naive; assumed UTC

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
    _PATTERNS = [
        "%Y-%m-%d %H:%MZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%MZ",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
    ]
    cleaned = raw.replace("Z", "").strip()
    for fmt in _PATTERNS:
        try:
            dt = datetime.datetime.strptime(cleaned, fmt)
            return dt.replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            continue

    logger.debug("parse_utc: could not parse %r", raw)
    return None


def parse_local(raw: Optional[str]) -> Optional[datetime.datetime]:
    """
    Parse a LOCAL time string from the API, preserving its original offset.

    Unlike parse_utc(), this does NOT convert to UTC — it keeps the offset
    as-is so we can format it directly for display.

    Accepts:
        "2026-09-14 21:30+01:00"       ← offset-aware local time
        "2026-09-14T21:30:00+05:30"    ← ISO with offset
        "2026-09-14 21:30"             ← naive (no offset info — still usable)

    Returns None if parsing fails or raw is empty.
    """
    if not raw:
        return None

    raw = raw.strip()

    # If it ends with Z, this is actually UTC, not local — still parse it
    normalized = raw.replace(" ", "T")
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"

    try:
        dt = datetime.datetime.fromisoformat(normalized)
        # Keep the original offset — do NOT convert to UTC
        return dt
    except ValueError:
        pass

    # Fallback: try without offset (naive datetime)
    _PATTERNS = [
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
    ]
    cleaned = raw.replace("Z", "").strip()
    for fmt in _PATTERNS:
        try:
            return datetime.datetime.strptime(cleaned, fmt)
        except ValueError:
            continue

    logger.debug("parse_local: could not parse %r", raw)
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


def _tz_abbr(dt: datetime.datetime) -> str:
    """Get a human-readable timezone abbreviation from a datetime."""
    abbr = dt.strftime("%Z")
    if abbr:
        return abbr
    # If strftime gives empty string, build from offset
    if dt.tzinfo is not None:
        offset = dt.utcoffset()
        if offset is not None:
            total_seconds = int(offset.total_seconds())
            sign = "+" if total_seconds >= 0 else "-"
            total_seconds = abs(total_seconds)
            hours, remainder = divmod(total_seconds, 3600)
            minutes = remainder // 60
            if minutes:
                return f"UTC{sign}{hours}:{minutes:02d}"
            return f"UTC{sign}{hours}"
    return "UTC"


def fmt_local_time(
    local_dt: Optional[datetime.datetime],
    utc_dt: Optional[datetime.datetime],
    tz_name: Optional[str],
    *,
    fmt: str = "%Y-%m-%d %I:%M %p",
    unknown_label: str = "Unknown",
) -> str:
    """
    Smart formatter that produces the best possible local time display.

    Priority:
        1. If local_dt is available (from API), format it directly.
           If tz_name is also available, re-interpret through the IANA zone
           to get a proper abbreviation (e.g. "BST" instead of "UTC+1").
        2. Else if utc_dt + tz_name available, convert UTC → local
        3. Else if utc_dt available, show as UTC
        4. Return unknown_label

    This is the PRIMARY display function. It prefers the API's own local
    time to avoid any timezone conversion bugs.
    """
    if local_dt is not None:
        # If we have an IANA timezone, convert through it for a proper abbreviation
        # (e.g., "BST" instead of "UTC+1", "IST" instead of "UTC+5:30")
        zi = _get_zoneinfo(tz_name) if tz_name else None
        if zi is not None:
            # Re-interpret the local_dt through the IANA zone
            # This gives us the named abbreviation (BST, IST, etc.)
            display_dt = local_dt.astimezone(zi)
        else:
            display_dt = local_dt
        abbr = _tz_abbr(display_dt)
        return f"{display_dt.strftime(fmt)} {abbr}".strip()

    if utc_dt is not None:
        if utc_dt.tzinfo is None:
            utc_dt = utc_dt.replace(tzinfo=datetime.timezone.utc)
        local = to_local(utc_dt, tz_name) or utc_dt
        abbr = _tz_abbr(local)
        return f"{local.strftime(fmt)} {abbr}".strip()

    return unknown_label


def fmt_local(
    utc_dt: Optional[datetime.datetime],
    tz_name: Optional[str],
    *,
    fmt: str = "%Y-%m-%d %I:%M %p",
    unknown_label: str = "Unknown",
) -> str:
    """
    Format a UTC datetime as a LOCAL time string with the timezone abbreviation.
    Legacy function — kept for backward compatibility with other callers.

    Example outputs:
        "2026-08-24 12:40 PM IST"        ← Asia/Kolkata
        "2026-08-24 07:10 AM UTC"        ← fallback when tz unknown
        "Unknown"                         ← when utc_dt is None
    """
    if utc_dt is None:
        return unknown_label

    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=datetime.timezone.utc)

    local_dt = to_local(utc_dt, tz_name) or utc_dt
    abbr = _tz_abbr(local_dt)
    return f"{local_dt.strftime(fmt)} {abbr}".strip()


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


def calc_delay_safe(
    sched_utc: Optional[datetime.datetime],
    compare_utc: Optional[datetime.datetime],
    has_departed: bool,
    is_arrival: bool = False,
) -> str:
    """
    Delay calculation with sanity checks for pre-departure flights.

    Rules:
        - If the flight hasn't departed yet:
            * Ignore arrival predictions entirely (they're unreliable)
            * For departure: only show delay if predicted is LATER than scheduled
              (i.e., an actual delay). Ignore "early" predictions for non-departed flights.
        - If the flight has departed: use standard calc_delay()

    Args:
        sched_utc:    Scheduled time in UTC
        compare_utc:  Actual or predicted time in UTC
        has_departed: Whether the flight has actually departed
        is_arrival:   Whether this is for the arrival leg
    """
    if sched_utc is None or compare_utc is None:
        return "No delay info"

    if not has_departed:
        if is_arrival:
            # Pre-departure: arrival predictions are unreliable — don't show
            return "No delay info"

        # Pre-departure: only trust departure delays (later than scheduled),
        # not "early" predictions
        if sched_utc.tzinfo is None:
            sched_utc = sched_utc.replace(tzinfo=datetime.timezone.utc)
        if compare_utc.tzinfo is None:
            compare_utc = compare_utc.replace(tzinfo=datetime.timezone.utc)

        diff_mins = int((compare_utc - sched_utc).total_seconds() / 60)
        if diff_mins > 0:
            return f"{diff_mins} min delay"
        else:
            return "On time"

    # Flight has departed — use standard delay calculation
    return calc_delay(sched_utc, compare_utc)


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
