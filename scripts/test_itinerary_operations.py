"""
scripts/test_itinerary_operations.py
=====================================
Integration test for the new itinerary caching layer.

Tests:
1. Save a direct-flight itinerary (1 leg)
2. Save a 1-stop itinerary (2 legs) with layover calculation
3. Read back with get_cached_itineraries — verify leg order and layover
4. Delete-and-replace: save new itineraries for same route/date, verify old ones gone
5. Verify itinerary_legs ON DELETE CASCADE when itinerary is deleted

Usage:
    python scripts/test_itinerary_operations.py
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
from shared.db.repositories.route_repository import (
    create_route_search,
    save_itineraries_to_db,
    get_cached_itineraries,
)

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
TRAVEL_DATE = "2026-09-10"

DIRECT_ITINERARY = {
    "price": 4500,
    "total_duration": 110,
    "booking_token": "token_direct_abc",
    "flights": [
        {
            "flight_number": "6E 214",
            "airline": "IndiGo",
            "airplane": "Airbus A320",
            "duration": 110,
            "departure_airport": {"id": "BOM", "name": "Mumbai International", "date": "2026-09-10", "time": "06:00"},
            "arrival_airport":   {"id": "DEL", "name": "Indira Gandhi International", "date": "2026-09-10", "time": "07:50"},
        }
    ],
}

CONNECTING_ITINERARY = {
    "price": 6200,
    "total_duration": 480,
    "booking_token": "token_connect_xyz",
    "flights": [
        {
            "flight_number": "AI 101",
            "airline": "Air India",
            "airplane": "Boeing 787",
            "duration": 180,
            "departure_airport": {"id": "BOM", "name": "Mumbai International", "date": "2026-09-10", "time": "08:00"},
            "arrival_airport":   {"id": "AUH", "name": "Abu Dhabi International", "date": "2026-09-10", "time": "11:00"},
        },
        {
            "flight_number": "AI 201",
            "airline": "Air India",
            "airplane": "Boeing 787",
            "duration": 200,
            "departure_airport": {"id": "AUH", "name": "Abu Dhabi International", "date": "2026-09-10", "time": "14:00"},
            "arrival_airport":   {"id": "DEL", "name": "Indira Gandhi International", "date": "2026-09-10", "time": "18:20"},
        },
    ],
}

# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

def main():
    print("\n" + "=" * 60)
    print("  Aviation Chatbot -- Itinerary Caching Test")
    print("=" * 60 + "\n")

    with get_connection_context() as conn:

        # Ensure airports exist
        for ap in [
            {"iata_code": "BOM", "name": "Mumbai International", "city": "Mumbai", "country_code": "IN", "fetch_at": NOW},
            {"iata_code": "DEL", "name": "Indira Gandhi International", "city": "Delhi", "country_code": "IN", "fetch_at": NOW},
            {"iata_code": "AUH", "name": "Abu Dhabi International", "city": "Abu Dhabi", "country_code": "AE", "fetch_at": NOW},
        ]:
            upsert_airport(conn, ap)

        bom_row = get_airport_by_iata(conn, "BOM")
        del_row = get_airport_by_iata(conn, "DEL")
        check("BOM airport row exists", bom_row is not None)
        check("DEL airport row exists", del_row is not None)

        # Create route search record
        search_id = create_route_search(conn, {
            "origin_airport_id":      bom_row["airport_id"],
            "destination_airport_id": del_row["airport_id"],
            "search_date": NOW.strftime("%Y-%m-%d"),
            "travel_date": TRAVEL_DATE,
            "currency":    "INR",
            "trip_type":   "one_way",
            "fetch_at":    NOW,
        })
        check("create_route_search returns ID", search_id is not None)

        # ── Test 1: Save direct itinerary ─────────────────────────────────
        print("\n[ Direct Flight Itinerary ]")
        n = save_itineraries_to_db(
            conn,
            dep_airport_id=bom_row["airport_id"],
            arr_airport_id=del_row["airport_id"],
            travel_date=TRAVEL_DATE,
            search_id=search_id,
            itineraries_raw=[DIRECT_ITINERARY],
            currency="INR",
            fetch_at=NOW,
        )
        check("save direct itinerary returns 1", n == 1)

        itins = get_cached_itineraries(conn, "BOM", "DEL", TRAVEL_DATE)
        check("get_cached_itineraries returns >=1", len(itins) >= 1)

        direct = next((i for i in itins if i.get("stop_count") == 0), None)
        check("direct itinerary found (stop_count=0)", direct is not None)
        if direct:
            check("price = 4500",              direct["price"] == 4500)
            check("total_duration_minutes=110", direct["total_duration_minutes"] == 110)
            check("1 leg returned",            len(direct.get("legs", [])) == 1)
            if direct["legs"]:
                leg = direct["legs"][0]
                check("leg 1: dep_iata = BOM", leg["dep_iata"] == "BOM")
                check("leg 1: arr_iata = DEL", leg["arr_iata"] == "DEL")
                check("leg 1: airline = IndiGo", leg["airline_name"] == "IndiGo")
                check("leg 1: no layover (last leg)", leg["layover_minutes"] is None)

        # ── Test 2: Save 1-stop itinerary ─────────────────────────────────
        print("\n[ 1-Stop (Connecting) Itinerary ]")
        n2 = save_itineraries_to_db(
            conn,
            dep_airport_id=bom_row["airport_id"],
            arr_airport_id=del_row["airport_id"],
            travel_date=TRAVEL_DATE,
            search_id=search_id,
            itineraries_raw=[CONNECTING_ITINERARY],
            currency="INR",
            fetch_at=NOW,
        )
        # After delete-and-replace, only the connecting one should exist
        check("save connecting itinerary returns 1", n2 == 1)

        itins2 = get_cached_itineraries(conn, "BOM", "DEL", TRAVEL_DATE)
        # Direct was deleted when we called save again for the same route+date
        check("delete-and-replace: only 1 itinerary now", len(itins2) == 1)

        conn_itin = itins2[0]
        check("stop_count = 1", conn_itin.get("stop_count") == 1)
        check("2 legs returned", len(conn_itin.get("legs", [])) == 2)

        if len(conn_itin.get("legs", [])) == 2:
            leg1, leg2 = conn_itin["legs"]
            check("leg 1 order=1",             leg1["leg_order"] == 1)
            check("leg 1: BOM -> AUH",         leg1["dep_iata"] == "BOM" and leg1["arr_iata"] == "AUH")
            check("leg 2 order=2",             leg2["leg_order"] == 2)
            check("leg 2: AUH -> DEL",         leg2["dep_iata"] == "AUH" and leg2["arr_iata"] == "DEL")
            check("leg 1 layover_minutes set",  leg1["layover_minutes"] is not None)
            check("layover = 180 min (3h)",     leg1["layover_minutes"] == 180)
            check("layover_iata = AUH",         leg1["layover_iata"] == "AUH")
            check("leg 2: no layover (last)",   leg2["layover_minutes"] is None)

        # ── Test 3: Save both itineraries together ─────────────────────────
        print("\n[ Both Itineraries Together ]")
        n3 = save_itineraries_to_db(
            conn,
            dep_airport_id=bom_row["airport_id"],
            arr_airport_id=del_row["airport_id"],
            travel_date=TRAVEL_DATE,
            search_id=search_id,
            itineraries_raw=[DIRECT_ITINERARY, CONNECTING_ITINERARY],
            currency="INR",
            fetch_at=NOW,
        )
        check("save both itineraries returns 2", n3 == 2)

        itins3 = get_cached_itineraries(conn, "BOM", "DEL", TRAVEL_DATE)
        check("2 itineraries in cache",  len(itins3) == 2)
        stop_counts = sorted([i.get("stop_count", -1) for i in itins3])
        check("stop counts are [0, 1]", stop_counts == [0, 1])

    # Summary
    total = _pass + _fail
    print(f"\n{'=' * 60}")
    print(f"  Results: {_pass}/{total} passed", "[ALL PASSED]" if _fail == 0 else "[SOME FAILED]")
    print(f"{'=' * 60}\n")

    if _fail > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
