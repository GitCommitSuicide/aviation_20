"""
scripts/test_stats_operations.py
================================
Integration tests for flight_routes and flight_delay_stats tables.
"""

import os
import sys
import datetime

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from shared.db.connection import get_connection_context
from shared.db.repositories.airport_repository import upsert_airport
from shared.db.repositories.flight_repository import upsert_flight
from shared.db.repositories.stats_repository import record_flight_route, get_flight_routes, update_delay_stats, get_delay_stats

NOW = datetime.datetime.now(tz=datetime.timezone.utc)
TODAY = datetime.date.today()

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

with get_connection_context() as conn:
    # 1. Setup Airports
    upsert_airport(conn, {"iata_code": "DEL", "name": "Delhi", "fetch_at": NOW})
    upsert_airport(conn, {"iata_code": "BOM", "name": "Mumbai", "fetch_at": NOW})

    # 2. Test record_flight_route
    print("\n[ test record_flight_route ]")
    r1 = record_flight_route(conn, "TEST1", "DEL", "BOM")
    check("route returned ID", r1 is not None)
    
    r1_dup = record_flight_route(conn, "TEST1", "DEL", "BOM")
    check("route ID matches on dup", r1 == r1_dup)

    routes = get_flight_routes(conn, "TEST1")
    check("route count = 1", len(routes) == 1)
    check("obs_count = 2", routes[0]["observation_count"] == 2)
    check("origin = DEL", routes[0]["origin_iata"] == "DEL")
    check("dest = BOM", routes[0]["destination_iata"] == "BOM")

    # 3. Insert Flights & Test update_delay_stats
    print("\n[ test update_delay_stats ]")
    # Flight 1: 0 mins delay (on time)
    f1_sched = NOW - datetime.timedelta(days=1)
    upsert_flight(conn, {
        "flight_number": "TEST1", "query_date": f1_sched.date().isoformat(),
        "departure_iata": "DEL", "arrival_iata": "BOM",
        "departure_scheduled": f1_sched, "departure_actual": f1_sched,
        "fetch_at": NOW, "status": "Landed"
    })

    # Flight 2: 30 mins delay
    f2_sched = NOW - datetime.timedelta(days=2)
    f2_actual = f2_sched + datetime.timedelta(minutes=30)
    upsert_flight(conn, {
        "flight_number": "TEST1", "query_date": f2_sched.date().isoformat(),
        "departure_iata": "DEL", "arrival_iata": "BOM",
        "departure_scheduled": f2_sched, "departure_actual": f2_actual,
        "fetch_at": NOW, "status": "Landed"
    })

    update_delay_stats(conn, "TEST1", r1)

    stats = get_delay_stats(conn, "TEST1")
    check("stats exists", len(stats) == 1)
    if stats:
        s = stats[0]
        check("total_obs = 2", s["total_observations"] == 2)
        check("avg_delay = 15", s["average_delay_mins"] == 15)
        check("on_time_percentage = 50.00", float(s["on_time_percentage"]) == 50.00)

print(f"\nResults: {_pass} passed, {_fail} failed")
if _fail > 0:
    sys.exit(1)
