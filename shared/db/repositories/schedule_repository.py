"""
database/repositories/schedule_repository.py
============================================
Data-access and inference functions for the `flight_schedules` table.

The schedule table stores the RECURRING WEEKLY PATTERN for a flight/route:
which days of the week it operates and the local clock time it departs.

Population strategy
-------------------
Schedules are NOT fetched from a timetable API (not available on free tier).
Instead, `infer_and_update_schedule()` is called as a side-effect every time a
new flight row lands in the `flights` table.  It looks back ~8 weeks of
observations for the same flight/route and, if a consistent pattern emerges,
writes/updates the schedule row.

Timezone convention
-------------------
`days_of_week` stores ISO weekday numbers (1=Mon .. 7=Sun) in the DEPARTURE
AIRPORT'S LOCAL TIMEZONE — matching how airlines publish timetables and how a
passenger understands "this flight operates on Mondays."
"""

import datetime
import logging
from collections import defaultdict
from typing import Optional

import psycopg
from psycopg.rows import dict_row

from shared.time_utils import get_airport_tz, to_local

logger = logging.getLogger(__name__)

# Minimum observations before we trust a weekday as part of the pattern
_MIN_TOTAL_OBSERVATIONS = 3
_MIN_WEEKDAY_OCCURRENCES = 2

# Weekday name map for user-facing output
_WEEKDAY_NAMES = {1: "Monday", 2: "Tuesday", 3: "Wednesday", 4: "Thursday",
                  5: "Friday", 6: "Saturday", 7: "Sunday"}


# ---------------------------------------------------------------------------
# Write operations
# ---------------------------------------------------------------------------

def upsert_flight_schedule(conn: psycopg.Connection, data: dict) -> Optional[int]:
    """
    Insert or update a flight schedule pattern row.

    Expected `data` keys:
        flight_number                   str   required
        departure_airport_id            int   required
        arrival_airport_id              int   required
        days_of_week                    list[int]  e.g. [1, 3, 5]
        scheduled_departure_local_time  datetime.time  required
        scheduled_arrival_local_time    datetime.time  required
        airline_id                      int   optional
        valid_from                      date  optional
        valid_to                        date  optional
        confidence                      str   'inferred' | 'confirmed'
        observed_count                  int
        fetch_at                        datetime (tz-aware UTC)

    Returns schedule_id or None on error.
    """
    flight_number = (data.get("flight_number") or "").strip().upper()
    dep_id = data.get("departure_airport_id")
    arr_id = data.get("arrival_airport_id")
    days   = sorted(set(data.get("days_of_week") or []))
    dep_time = data.get("scheduled_departure_local_time")
    arr_time = data.get("scheduled_arrival_local_time")

    if not flight_number or not dep_id or not arr_id or not days or not dep_time:
        logger.warning("upsert_flight_schedule: missing required fields, skipping.")
        return None

    now_utc  = datetime.datetime.now(tz=datetime.timezone.utc)
    fetch_at = data.get("fetch_at") or now_utc

    try:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                INSERT INTO flight_schedules (
                    flight_number, airline_id,
                    departure_airport_id, arrival_airport_id,
                    days_of_week,
                    scheduled_departure_local_time,
                    scheduled_arrival_local_time,
                    valid_from, valid_to,
                    confidence, observed_count,
                    fetch_at, created_at, updated_at
                )
                VALUES (
                    %(flight_number)s, %(airline_id)s,
                    %(dep_id)s, %(arr_id)s,
                    %(days)s,
                    %(dep_time)s,
                    %(arr_time)s,
                    %(valid_from)s, %(valid_to)s,
                    %(confidence)s, %(observed_count)s,
                    %(fetch_at)s, NOW(), NOW()
                )
                ON CONFLICT (flight_number, departure_airport_id, arrival_airport_id, days_of_week)
                DO UPDATE SET
                    scheduled_departure_local_time = EXCLUDED.scheduled_departure_local_time,
                    scheduled_arrival_local_time   = EXCLUDED.scheduled_arrival_local_time,
                    airline_id      = COALESCE(EXCLUDED.airline_id,    flight_schedules.airline_id),
                    confidence      = CASE
                                        WHEN EXCLUDED.confidence = 'confirmed' THEN 'confirmed'
                                        ELSE flight_schedules.confidence
                                      END,
                    observed_count  = GREATEST(EXCLUDED.observed_count, flight_schedules.observed_count),
                    fetch_at        = EXCLUDED.fetch_at,
                    updated_at      = NOW()
                RETURNING schedule_id
                """,
                {
                    "flight_number":  flight_number,
                    "airline_id":     data.get("airline_id"),
                    "dep_id":         dep_id,
                    "arr_id":         arr_id,
                    "days":           days,
                    "dep_time":       dep_time,
                    "arr_time":       arr_time,
                    "valid_from":     data.get("valid_from"),
                    "valid_to":       data.get("valid_to"),
                    "confidence":     data.get("confidence", "inferred"),
                    "observed_count": data.get("observed_count", 1),
                    "fetch_at":       fetch_at,
                },
            )
            row = cur.fetchone()
            sid = row["schedule_id"] if row else None
            logger.debug("upsert_flight_schedule: id=%s flight=%s days=%s", sid, flight_number, days)
            return sid
    except psycopg.Error as exc:
        conn.rollback()
        logger.error("upsert_flight_schedule error: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------

def get_schedule(
    conn: psycopg.Connection,
    flight_number: str,
    dep_airport_id: Optional[int] = None,
    arr_airport_id: Optional[int] = None,
) -> list[dict]:
    """
    Return schedule rows for a given flight number, optionally filtered by route.
    Returns all matching rows ordered by observed_count DESC (most confident first).
    """
    flight_number = flight_number.strip().upper()

    with conn.cursor(row_factory=dict_row) as cur:
        if dep_airport_id and arr_airport_id:
            cur.execute(
                """
                SELECT fs.*,
                       da.iata_code AS dep_iata, da.name AS dep_airport_name,
                       da.timezone  AS dep_timezone,
                       aa.iata_code AS arr_iata, aa.name AS arr_airport_name,
                       aa.timezone  AS arr_timezone,
                       al.name      AS airline_name
                FROM flight_schedules fs
                LEFT JOIN airports da ON fs.departure_airport_id = da.airport_id
                LEFT JOIN airports aa ON fs.arrival_airport_id   = aa.airport_id
                LEFT JOIN airlines al ON fs.airline_id           = al.airline_id
                WHERE fs.flight_number        = %s
                  AND fs.departure_airport_id = %s
                  AND fs.arrival_airport_id   = %s
                ORDER BY fs.observed_count DESC, fs.updated_at DESC
                """,
                (flight_number, dep_airport_id, arr_airport_id),
            )
        else:
            cur.execute(
                """
                SELECT fs.*,
                       da.iata_code AS dep_iata, da.name AS dep_airport_name,
                       da.timezone  AS dep_timezone,
                       aa.iata_code AS arr_iata, aa.name AS arr_airport_name,
                       aa.timezone  AS arr_timezone,
                       al.name      AS airline_name
                FROM flight_schedules fs
                LEFT JOIN airports da ON fs.departure_airport_id = da.airport_id
                LEFT JOIN airports aa ON fs.arrival_airport_id   = aa.airport_id
                LEFT JOIN airlines al ON fs.airline_id           = al.airline_id
                WHERE fs.flight_number = %s
                ORDER BY fs.observed_count DESC, fs.updated_at DESC
                """,
                (flight_number,),
            )
        return cur.fetchall()


# ---------------------------------------------------------------------------
# Next-occurrence helper (pure Python — no DB needed)
# ---------------------------------------------------------------------------

def get_next_occurrence(days_of_week: list[int], from_date: datetime.date) -> datetime.date:
    """
    Return the next calendar date (>= from_date) on which the flight operates.

    Args:
        days_of_week: list of ISO weekday numbers (1=Mon .. 7=Sun)
        from_date:    start date (inclusive)

    Returns the date itself if from_date is already an operating day,
    otherwise the nearest future date that matches.
    """
    if not days_of_week:
        return from_date

    days_set = set(days_of_week)
    for offset in range(8):   # at most 7 days ahead + today
        candidate = from_date + datetime.timedelta(days=offset)
        if candidate.isoweekday() in days_set:
            return candidate
    return from_date   # fallback — shouldn't happen


def format_schedule_for_user(schedule: dict) -> str:
    """
    Return a human-readable description of a schedule row.
    Example: "AI101 operates Mon / Wed / Fri, departing DEL at 02:20 PM IST,
              arriving BOM at 04:30 PM IST."
    """
    days = schedule.get("days_of_week") or []
    day_names = " / ".join(_WEEKDAY_NAMES.get(d, str(d)) for d in sorted(days))

    dep_iata  = schedule.get("dep_iata", "?")
    arr_iata  = schedule.get("arr_iata", "?")
    dep_tz    = schedule.get("dep_timezone") or get_airport_tz(dep_iata)
    arr_tz    = schedule.get("arr_timezone") or get_airport_tz(arr_iata)

    dep_time_obj = schedule.get("scheduled_departure_local_time")
    arr_time_obj = schedule.get("scheduled_arrival_local_time")

    def _fmt_time(t, tz_name):
        if t is None:
            return "Unknown"
        t_str = t.strftime("%I:%M %p") if hasattr(t, "strftime") else str(t)[:5]
        # Append the timezone abbreviation from a dummy date conversion
        try:
            from zoneinfo import ZoneInfo
            dummy = datetime.datetime.combine(datetime.date.today(), t, tzinfo=ZoneInfo(tz_name))
            return f"{dummy.strftime('%I:%M %p')} {dummy.strftime('%Z')}"
        except Exception:
            return t_str

    dep_time_str = _fmt_time(dep_time_obj, dep_tz) if dep_tz else (
        dep_time_obj.strftime("%H:%M") if dep_time_obj else "Unknown"
    )
    arr_time_str = _fmt_time(arr_time_obj, arr_tz) if arr_tz else (
        arr_time_obj.strftime("%H:%M") if arr_time_obj else "Unknown"
    )

    airline = schedule.get("airline_name", "")
    airline_str = f" ({airline})" if airline else ""

    dep_name = schedule.get("dep_airport_name", dep_iata)
    arr_name = schedule.get("arr_airport_name", arr_iata)

    confidence = schedule.get("confidence", "inferred")
    obs = schedule.get("observed_count", 1)
    note = (
        f" [pattern inferred from {obs} observation(s)]"
        if confidence == "inferred"
        else " [confirmed schedule]"
    )

    return (
        f"Flight {schedule['flight_number']}{airline_str} operates on: {day_names}\n"
        f"  Departure: {dep_name} ({dep_iata}) at {dep_time_str}\n"
        f"  Arrival:   {arr_name} ({arr_iata}) at {arr_time_str}\n"
        f"  {note}"
    )


# ---------------------------------------------------------------------------
# Inference engine
# ---------------------------------------------------------------------------

def infer_and_update_schedule(
    conn: psycopg.Connection,
    flight_number: str,
    dep_airport_id: int,
    arr_airport_id: int,
    dep_iata: Optional[str] = None,
    airline_id: Optional[int] = None,
) -> None:
    """
    Look at the last ~8 weeks of observed flight rows for this flight/route
    and, if a consistent weekly pattern emerges, upsert a flight_schedules row.

    Called automatically as a side-effect of every successful upsert_flight().

    Algorithm:
    1. Pull the last 8 weeks of distinct (query_date, departure_scheduled) rows.
    2. Convert each departure_scheduled (UTC TIMESTAMPTZ) to the departure
       airport's LOCAL time — so weekday means "Monday at the gate."
    3. A weekday is included if it has >= _MIN_WEEKDAY_OCCURRENCES observations.
    4. If >= _MIN_TOTAL_OBSERVATIONS rows total, write the schedule.
    """
    from shared.db.repositories.flight_repository import get_flight_history

    rows = get_flight_history(conn, flight_number, dep_airport_id, arr_airport_id, weeks=8)
    if len(rows) < _MIN_TOTAL_OBSERVATIONS:
        logger.debug(
            "infer_and_update_schedule: only %d observations for %s — skipping",
            len(rows), flight_number,
        )
        return

    # Resolve departure airport timezone for weekday calculation
    dep_tz_name = get_airport_tz(dep_iata)

    by_weekday: dict[int, list[datetime.time]] = defaultdict(list)
    arr_times_raw: list[datetime.time] = []

    for r in rows:
        dep_utc = r.get("departure_scheduled")
        arr_utc = r.get("arrival_scheduled")
        if not dep_utc:
            continue

        # Ensure tz-aware
        if dep_utc.tzinfo is None:
            dep_utc = dep_utc.replace(tzinfo=datetime.timezone.utc)

        # Convert to local for weekday + clock-time
        dep_local = to_local(dep_utc, dep_tz_name) or dep_utc
        weekday = dep_local.isoweekday()       # 1=Mon..7=Sun at local time
        dep_time_local = dep_local.time().replace(second=0, microsecond=0)
        by_weekday[weekday].append(dep_time_local)

        if arr_utc:
            if arr_utc.tzinfo is None:
                arr_utc = arr_utc.replace(tzinfo=datetime.timezone.utc)
            arr_times_raw.append(arr_utc.time().replace(second=0, microsecond=0))

    # Keep only weekdays with enough evidence
    confirmed_days = [d for d, times in by_weekday.items() if len(times) >= _MIN_WEEKDAY_OCCURRENCES]
    if not confirmed_days:
        return

    # Representative departure time: median of observed times for confirmed days
    all_dep_times = [t for d in confirmed_days for t in by_weekday[d]]
    all_dep_times_sorted = sorted(all_dep_times)
    rep_dep_time = all_dep_times_sorted[len(all_dep_times_sorted) // 2]

    # Representative arrival time: median of all observed arrivals
    if arr_times_raw:
        arr_sorted = sorted(arr_times_raw)
        rep_arr_time = arr_sorted[len(arr_sorted) // 2]
    else:
        rep_arr_time = rep_dep_time   # fallback

    upsert_flight_schedule(conn, {
        "flight_number":                   flight_number,
        "airline_id":                      airline_id,
        "departure_airport_id":            dep_airport_id,
        "arrival_airport_id":              arr_airport_id,
        "days_of_week":                    confirmed_days,
        "scheduled_departure_local_time":  rep_dep_time,
        "scheduled_arrival_local_time":    rep_arr_time,
        "confidence":                      "inferred",
        "observed_count":                  len(rows),
        "fetch_at":                        datetime.datetime.now(tz=datetime.timezone.utc),
    })
    logger.info(
        "infer_and_update_schedule: %s dep=%s arr=%s days=%s obs=%d",
        flight_number, dep_airport_id, arr_airport_id, confirmed_days, len(rows),
    )
