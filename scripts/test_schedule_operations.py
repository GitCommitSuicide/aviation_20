"""
scripts/test_schedule_operations.py
=====================================
Integration tests for the flight_schedules table and inference engine.

Tests:
1. upsert_flight_schedule — insert + upsert (observed_count update)
2. get_schedule — by flight number only, and filtered by route
3. get_next_occurrence — correct next weekday from a known start date
4. is_past_date — correctly identifies past vs. today vs. future dates
5. infer_and_update_schedule — inject synthetic flight history, verify pattern
6. format_schedule_for_user — smoke test (no crash, contains weekday name)

Usage:
    python scripts/test_schedule_operations.py
"""

import os
import sys
import datetime

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv()

from shared.db.connection import get_connection_context
from shared.db.repositories.airport_repository import upsert_airport, get_airport_by_iata
from shared.db.repositories.airline_repository import upsert_airline
from shared.db.repositories.flight_repository import upsert_flight
from shared.db.repositories.schedule_repository import (
    upsert_flight_schedule,
    get_schedule,
    get_next_occurrence,
    format_schedule_for_user,
    infer_and_update_schedule,
)
from shared.cache import is_past_date

_pass = 0
_fail = 0

def check(label: str, condition: bool) -> None:
    global _pass, _fail
    if condition:
        _pass += 1
        print(f"  [PASS]  {label}")
    else:
        _fail += 1
        print(f"  [FAIL]  {label}")


NOW = datetime.datetime.now(tz=datetime.timezone.utc)
TODAY = datetime.date.today()

# ── 1. is_past_date ──────────────────────────────────────────────────────────
print("\n[ is_past_date ]")
check("yesterday is past",   is_past_date(TODAY - datetime.timedelta(days=1)))
check("today is NOT past",   not is_past_date(TODAY))
check("tomorrow is NOT past",not is_past_date(TODAY + datetime.timedelta(days=1)))
check("string past date",    is_past_date("2020-01-01"))
check("string future date",  not is_past_date("2099-01-01"))
check("None is NOT past",    not is_past_date(None))


# ── 2. get_next_occurrence ────────────────────────────────────────────────────
print("\n[ get_next_occurrence ]")

# Use a known Monday (2026-09-07 — confirmed Monday via isoweekday=1)
KNOWN_MONDAY = datetime.date(2026, 9, 7)
assert KNOWN_MONDAY.isoweekday() == 1, "KNOWN_MONDAY is not a Monday"

next_mon = get_next_occurrence([1], from_date=KNOWN_MONDAY)
check("from Monday, next Mon = same day", next_mon == KNOWN_MONDAY)

next_fri = get_next_occurrence([5], from_date=KNOWN_MONDAY)
check("from Monday, next Fri = +4 days", next_fri == KNOWN_MONDAY + datetime.timedelta(days=4))

next_mwf = get_next_occurrence([1, 3, 5], from_date=KNOWN_MONDAY)
check("from Monday, next Mon/Wed/Fri = same Monday", next_mwf == KNOWN_MONDAY)

next_sun = get_next_occurrence([7], from_date=KNOWN_MONDAY)
check("from Monday, next Sun = +6 days", next_sun == KNOWN_MONDAY + datetime.timedelta(days=6))

KNOWN_SUNDAY = KNOWN_MONDAY + datetime.timedelta(days=6)
next_from_sun = get_next_occurrence([1, 3], from_date=KNOWN_SUNDAY)
check("from Sunday, next Mon/Wed = Monday (+1)", next_from_sun == KNOWN_SUNDAY + datetime.timedelta(days=1))


# ── 3. upsert_flight_schedule + get_schedule ─────────────────────────────────
print("\n[ upsert_flight_schedule + get_schedule ]")

with get_connection_context() as conn:
    # Ensure airports
    for ap in [
        {"iata_code": "DEL", "name": "Indira Gandhi International", "city": "Delhi",   "country_code": "IN", "timezone": "Asia/Kolkata", "fetch_at": NOW},
        {"iata_code": "BOM", "name": "Mumbai International",        "city": "Mumbai",  "country_code": "IN", "timezone": "Asia/Kolkata", "fetch_at": NOW},
    ]:
        upsert_airport(conn, ap)

    del_row = get_airport_by_iata(conn, "DEL")
    bom_row = get_airport_by_iata(conn, "BOM")
    check("DEL airport exists", del_row is not None)
    check("BOM airport exists", bom_row is not None)

    # Insert first schedule row
    sid1 = upsert_flight_schedule(conn, {
        "flight_number":                  "AI101",
        "departure_airport_id":           del_row["airport_id"],
        "arrival_airport_id":             bom_row["airport_id"],
        "days_of_week":                   [1, 3, 5],
        "scheduled_departure_local_time": datetime.time(14, 20),
        "scheduled_arrival_local_time":   datetime.time(16, 30),
        "confidence":                     "inferred",
        "observed_count":                 3,
        "fetch_at":                       NOW,
    })
    check("upsert_flight_schedule returns ID", sid1 is not None)

    # Upsert again with higher observed_count — should increment
    sid2 = upsert_flight_schedule(conn, {
        "flight_number":                  "AI101",
        "departure_airport_id":           del_row["airport_id"],
        "arrival_airport_id":             bom_row["airport_id"],
        "days_of_week":                   [1, 3, 5],
        "scheduled_departure_local_time": datetime.time(14, 20),
        "scheduled_arrival_local_time":   datetime.time(16, 30),
        "confidence":                     "inferred",
        "observed_count":                 7,   # higher
        "fetch_at":                       NOW,
    })
    check("re-upsert returns same or new ID", sid2 is not None)

    # get_schedule by flight only
    schedules = get_schedule(conn, "AI101")
    check("get_schedule returns >=1 row", len(schedules) >= 1)

    sched = schedules[0]
    check("flight_number = AI101",   sched["flight_number"] == "AI101")
    check("days_of_week = [1,3,5]",  sorted(sched["days_of_week"]) == [1, 3, 5])
    check("observed_count = 7",      sched["observed_count"] == 7)
    check("dep_iata = DEL",          sched.get("dep_iata") == "DEL")
    check("arr_iata = BOM",          sched.get("arr_iata") == "BOM")

    # get_schedule filtered by route
    filtered = get_schedule(conn, "AI101", del_row["airport_id"], bom_row["airport_id"])
    check("filtered get_schedule returns row", len(filtered) >= 1)

    wrong = get_schedule(conn, "AI101", bom_row["airport_id"], del_row["airport_id"])
    check("wrong route returns 0 rows",  len(wrong) == 0)


# ── 4. format_schedule_for_user ───────────────────────────────────────────────
print("\n[ format_schedule_for_user ]")
with get_connection_context() as conn:
    sched_list = get_schedule(conn, "AI101")
formatted = format_schedule_for_user(sched_list[0])
check("formatted contains Monday",   "Monday" in formatted)
check("formatted contains Wednesday","Wednesday" in formatted)
check("formatted contains AI101",    "AI101" in formatted)
check("formatted contains DEL",      "DEL" in formatted)
check("formatted contains BOM",      "BOM" in formatted)
print(f"  Sample output:\n{formatted}")


# ── 5. infer_and_update_schedule ──────────────────────────────────────────────
print("\n[ infer_and_update_schedule ]")

# Inject synthetic flight history for a new flight "6E214" DEL->BOM
# operating on Mon (isoweekday=1) and Wed (3) consistently
# We'll insert at least 3 total rows with 2+ on Mon and 2+ on Wed

# Find the most recent past Monday and Wednesday
def most_recent_weekday(wd: int) -> datetime.date:
    """Return the most recent past date that was weekday wd (1=Mon..7=Sun)."""
    d = TODAY
    while d.isoweekday() != wd:
        d -= datetime.timedelta(days=1)
    return d

dates_mon = [most_recent_weekday(1) - datetime.timedelta(weeks=i) for i in range(3)]
dates_wed = [most_recent_weekday(3) - datetime.timedelta(weeks=i) for i in range(3)]
all_dates = dates_mon + dates_wed

with get_connection_context() as conn:
    # Ensure airline
    al_id = upsert_airline(conn, {"iata_code": "6E", "name": "IndiGo", "fetch_at": NOW})

    del_row = get_airport_by_iata(conn, "DEL")
    bom_row = get_airport_by_iata(conn, "BOM")

    for d in all_dates:
        # Build a UTC departure time (14:20 IST = 08:50 UTC)
        dep_utc = datetime.datetime.combine(
            d, datetime.time(8, 50), tzinfo=datetime.timezone.utc
        )
        arr_utc = dep_utc + datetime.timedelta(hours=2, minutes=10)

        upsert_flight(conn, {
            "flight_number":      "6E214",
            "query_date":         d.isoformat(),
            "status":             "Landed",
            "fetch_at":           NOW,
            "departure_iata":     "DEL",
            "departure_name":     "Indira Gandhi International",
            "departure_timezone": "Asia/Kolkata",
            "departure_scheduled": dep_utc,
            "arrival_iata":       "BOM",
            "arrival_name":       "Mumbai International",
            "arrival_timezone":   "Asia/Kolkata",
            "arrival_scheduled":  arr_utc,
            "airline_iata":       "6E",
            "airline_name":       "IndiGo",
        })

    # Now run inference
    infer_and_update_schedule(
        conn,
        flight_number="6E214",
        dep_airport_id=del_row["airport_id"],
        arr_airport_id=bom_row["airport_id"],
        dep_iata="DEL",
        airline_id=al_id,
    )

    result = get_schedule(conn, "6E214", del_row["airport_id"], bom_row["airport_id"])
    check("inference created schedule row", len(result) >= 1)
    if result:
        inf = result[0]
        days = sorted(inf["days_of_week"])
        check("inferred days contain Monday (1)",    1 in days)
        check("inferred days contain Wednesday (3)", 3 in days)
        check("observed_count >= 6",                 inf["observed_count"] >= 6)
        check("confidence = inferred",               inf["confidence"] == "inferred")
        check("departure local time set",            inf["scheduled_departure_local_time"] is not None)
        print(f"  Inferred pattern: days={days}, dep_time={inf['scheduled_departure_local_time']}")


# ── Summary ───────────────────────────────────────────────────────────────────
total = _pass + _fail
print(f"\n{'=' * 60}")
print(f"  Results: {_pass}/{total} passed", "[ALL PASSED]" if _fail == 0 else "[SOME FAILED]")
print(f"{'=' * 60}\n")

if _fail > 0:
    sys.exit(1)
