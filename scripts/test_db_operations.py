"""
scripts/test_db_operations.py
==============================
Integration test that verifies the full database layer end-to-end:

1. Inserts one test airport  (DEL — Indira Gandhi International)
2. Inserts one test airline  (Air India, AI)
3. Inserts one test aircraft (Airbus A320 NEO, no registration)
4. Inserts one test flight   (AI101, DEL → FCO)
5. Queries the flight with JOINs and verifies key fields
6. Inserts a route search record
7. Tests freshness logic (is_fresh)
8. Prints pass/fail for each assertion

Safe to run multiple times — upsert logic prevents duplicates.

Usage:
    python scripts/test_db_operations.py
"""

import os
import sys
import datetime

# Force UTF-8 output on Windows terminals (avoids cp1252 charmap errors)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from dotenv import load_dotenv
load_dotenv()

from shared.db.connection import get_connection_context
from shared.db.repositories.airport_repository import upsert_airport, get_airport_by_iata
from shared.db.repositories.airline_repository import upsert_airline, get_airline_by_iata
from shared.db.repositories.aircraft_repository import upsert_aircraft, get_aircraft_by_registration
from shared.db.repositories.flight_repository import upsert_flight, get_flight, search_flights_by_route
from shared.db.repositories.route_repository import create_route_search, get_latest_route_search
from shared.cache import is_fresh, FLIGHT_CACHE_MINUTES, hours_to_minutes, AIRPORT_CACHE_HOURS


# ---------------------------------------------------------------------------
# Tiny assertion helper
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

NOW = datetime.datetime.now(tz=datetime.timezone.utc)

TEST_AIRPORT_DEL = {
    "iata_code":    "DEL",
    "icao_code":    "VIDP",
    "name":         "Indira Gandhi International",
    "city":         "Delhi",
    "country":      "India",
    "country_code": "IN",
    "latitude":     28.5665,
    "longitude":    77.1031,
    "timezone":     "Asia/Kolkata",
    "airport_type": "large_airport",
    "fetch_at":     NOW,
}

TEST_AIRPORT_FCO = {
    "iata_code":    "FCO",
    "icao_code":    "LIRF",
    "name":         "Leonardo Da Vinci (Fiumicino)",
    "city":         "Rome",
    "country":      "Italy",
    "country_code": "IT",
    "latitude":     41.8003,
    "longitude":    12.2389,
    "timezone":     "Europe/Rome",
    "airport_type": "large_airport",
    "fetch_at":     NOW,
}

TEST_AIRLINE_AI = {
    "iata_code": "AI",
    "icao_code": "AIC",
    "name":      "Air India",
    "country":   "India",
    "fetch_at":  NOW,
}

TEST_AIRCRAFT = {
    "registration": "VT-ANR",
    "model":        "Boeing 787-8 Dreamliner",
    "manufacturer": "Boeing",
    "fetch_at":     NOW,
}

TEST_FLIGHT_AI101 = {
    "flight_number":    "AI101",
    "query_date":       NOW.strftime("%Y-%m-%d"),
    "status":           "active",
    "fetch_at":         NOW,

    "departure_iata":      "DEL",
    "departure_icao":      "VIDP",
    "departure_name":      "Indira Gandhi International",
    "departure_city":      "Delhi",
    "departure_country":   "India",
    "departure_country_code": "IN",
    "departure_lat":       28.5665,
    "departure_lon":       77.1031,
    "departure_timezone":  "Asia/Kolkata",
    "departure_scheduled": "2026-08-23T22:50:00+00:00",
    "departure_actual":    "2026-08-23T23:20:00+00:00",
    "departure_terminal":  "3",
    "departure_gate":      "24",

    "arrival_iata":      "FCO",
    "arrival_icao":      "LIRF",
    "arrival_name":      "Leonardo Da Vinci (Fiumicino)",
    "arrival_city":      "Rome",
    "arrival_country":   "Italy",
    "arrival_country_code": "IT",
    "arrival_lat":       41.8003,
    "arrival_lon":       12.2389,
    "arrival_scheduled": "2026-08-24T04:40:00+00:00",
    "arrival_actual":    "2026-08-24T03:59:00+00:00",
    "arrival_terminal":  "3",
    "arrival_gate":      None,
    "arrival_baggage_belt": None,

    "airline_iata": "AI",
    "airline_icao": "AIC",
    "airline_name": "Air India",

    "aircraft_registration": "VT-ANR",
    "aircraft_model":        "Boeing 787-8 Dreamliner",

    "delay_minutes": 30,
}


# ---------------------------------------------------------------------------
# Main test runner
# ---------------------------------------------------------------------------

def main():
    print("\n" + "=" * 55)
    print("  Aviation Chatbot — DB Operations Test")
    print("=" * 55 + "\n")

    with get_connection_context() as conn:

        # ── Airports ──────────────────────────────────────────────────────
        print("[ Airports ]")
        del_id = upsert_airport(conn, TEST_AIRPORT_DEL)
        fco_id = upsert_airport(conn, TEST_AIRPORT_FCO)
        check("upsert DEL returns an ID", del_id is not None)
        check("upsert FCO returns an ID", fco_id is not None)

        row = get_airport_by_iata(conn, "DEL")
        check("get_airport_by_iata('DEL') found", row is not None)
        check("DEL city = Delhi",  row and row["city"] == "Delhi")
        check("DEL icao = VIDP",   row and row["icao_code"] == "VIDP")

        # ── Airlines ──────────────────────────────────────────────────────
        print("\n[ Airlines ]")
        ai_id = upsert_airline(conn, TEST_AIRLINE_AI)
        check("upsert Air India returns an ID", ai_id is not None)

        row = get_airline_by_iata(conn, "AI")
        check("get_airline_by_iata('AI') found",     row is not None)
        check("Airline name = 'Air India'",           row and row["name"] == "Air India")

        # ── Aircraft ──────────────────────────────────────────────────────
        print("\n[ Aircraft ]")
        ac_id = upsert_aircraft(conn, TEST_AIRCRAFT)
        check("upsert aircraft returns an ID", ac_id is not None)

        row = get_aircraft_by_registration(conn, "VT-ANR")
        check("get_aircraft_by_registration('VT-ANR') found", row is not None)
        check("aircraft model correct", row and "787" in row["model"])

        # ── Flight ────────────────────────────────────────────────────────
        print("\n[ Flights ]")
        fl_id = upsert_flight(conn, TEST_FLIGHT_AI101)
        check("upsert flight AI101 returns an ID", fl_id is not None)

        # Idempotency check — second upsert should return same ID
        fl_id2 = upsert_flight(conn, TEST_FLIGHT_AI101)
        check("second upsert returns same flight_id (idempotent)", fl_id == fl_id2)

        rows = get_flight(conn, "AI101", NOW.strftime("%Y-%m-%d"))
        check("get_flight AI101 returns >=1 row", len(rows) >= 1)

        if rows:
            r = rows[0]
            check("flight has dep_iata = DEL",      r.get("dep_iata") == "DEL")
            check("flight has arr_iata = FCO",      r.get("arr_iata") == "FCO")
            check("flight airline_name = Air India", r.get("airline_name") == "Air India")
            check("flight aircraft_reg = VT-ANR",   r.get("aircraft_reg") == "VT-ANR")

        # Route search by IATA
        route_rows = search_flights_by_route(conn, "DEL", "FCO", NOW.strftime("%Y-%m-%d"))
        check("search_flights_by_route DEL->FCO returns >=1 row", len(route_rows) >= 1)

        # ── Route searches ────────────────────────────────────────────────
        print("\n[ Route Searches ]")
        rs_id = create_route_search(conn, {
            "origin_airport_id":      del_id,
            "destination_airport_id": fco_id,
            "search_date":   NOW.strftime("%Y-%m-%d"),
            "travel_date":   NOW.strftime("%Y-%m-%d"),
            "currency":      "INR",
            "trip_type":     "one_way",
            "fetch_at":      NOW,
        })
        check("create_route_search returns an ID", rs_id is not None)

        rs_row = get_latest_route_search(conn, del_id, fco_id, NOW.strftime("%Y-%m-%d"), "INR")
        check("get_latest_route_search found",     rs_row is not None)
        check("route search currency = INR",       rs_row and rs_row["currency"] == "INR")

        # ── Freshness logic ───────────────────────────────────────────────
        print("\n[ Freshness / Cache ]")
        check("NOW is fresh (flight 10 min)",
              is_fresh(NOW, FLIGHT_CACHE_MINUTES))
        check("1 hour ago is stale for flight cache",
              not is_fresh(NOW - datetime.timedelta(hours=1), FLIGHT_CACHE_MINUTES))
        check("1 day ago is fresh for airports (7-day cache)",
              is_fresh(NOW - datetime.timedelta(days=1), hours_to_minutes(AIRPORT_CACHE_HOURS)))
        check("8 days ago is stale for airports",
              not is_fresh(NOW - datetime.timedelta(days=8), hours_to_minutes(AIRPORT_CACHE_HOURS)))
        check("None fetch_at is stale",
              not is_fresh(None, FLIGHT_CACHE_MINUTES))

    # ── Summary ───────────────────────────────────────────────────────────
    total = _pass + _fail
    print(f"{'=' * 55}")
    print(f"  Results: {_pass}/{total} passed", "[ALL PASSED]" if _fail == 0 else "[SOME FAILED]")
    print(f"{'=' * 55}\n")

    if _fail > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
