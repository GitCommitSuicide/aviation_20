"""
servers/aviation_server/persistence.py
========================================
After the aviation MCP server fetches fresh data from an external API
(AeroDataBox / Aviationstack / SearchApi), it writes that data back into the
shared PostgreSQL cache so the database MCP server can serve it instantly
next time. This mirrors the original app's "DB-first" caching design.

The aviation server depends on `shared.db.*` (same package the database
server uses) purely for this write-through cache — it never exposes DB
*read* tools itself; that stays entirely on the database MCP server.
"""

import datetime

from shared.db.connection import get_connection_context
from shared.db.repositories.flight_repository import upsert_flight
from shared.db.repositories.stats_repository import record_flight_route, update_delay_stats
from shared.db.repositories.airport_repository import upsert_airport, get_airport_by_iata
from shared.db.repositories.route_repository import create_route_search, save_itineraries_to_db
from shared.time_utils import parse_utc
from servers.aviation_server.config import get_logger

logger = get_logger(__name__)


def _flight_record_to_db_row(record: dict, query_date: str) -> dict:
    """Map one common-shape flight record (see providers/normalize.py) to the
    flat dict expected by flight_repository.upsert_flight()."""
    now_utc = datetime.datetime.now(tz=datetime.timezone.utc)
    dep = record.get("departure", {})
    arr = record.get("arrival", {})
    airline = record.get("airline", {})
    aircraft = record.get("aircraft", {})

    return {
        "flight_number": record.get("flight_number"),
        "query_date": query_date,
        "status": record.get("status"),
        "fetch_at": now_utc,

        "departure_iata": dep.get("iata"),
        "departure_icao": dep.get("icao"),
        "departure_name": dep.get("name"),
        "departure_city": dep.get("city"),
        "departure_country": None,
        "departure_country_code": dep.get("country_code"),
        "departure_lat": dep.get("lat"),
        "departure_lon": dep.get("lon"),
        "departure_timezone": dep.get("timezone"),
        "departure_scheduled": parse_utc(dep.get("scheduled_utc")),
        "departure_actual": parse_utc(dep.get("actual_utc")),
        "departure_estimated": parse_utc(dep.get("estimated_utc")),
        "departure_terminal": dep.get("terminal"),
        "departure_gate": dep.get("gate"),

        "arrival_iata": arr.get("iata"),
        "arrival_icao": arr.get("icao"),
        "arrival_name": arr.get("name"),
        "arrival_city": arr.get("city"),
        "arrival_country": None,
        "arrival_country_code": arr.get("country_code"),
        "arrival_lat": arr.get("lat"),
        "arrival_lon": arr.get("lon"),
        "arrival_timezone": arr.get("timezone"),
        "arrival_scheduled": parse_utc(arr.get("scheduled_utc")),
        "arrival_actual": parse_utc(arr.get("actual_utc")),
        "arrival_estimated": parse_utc(arr.get("estimated_utc")),
        "arrival_terminal": arr.get("terminal"),
        "arrival_gate": arr.get("gate"),
        "arrival_baggage_belt": arr.get("baggage_belt"),

        "airline_iata": airline.get("iata"),
        "airline_icao": airline.get("icao"),
        "airline_name": airline.get("name"),
        "aircraft_registration": aircraft.get("reg"),
        "aircraft_model": aircraft.get("model"),
        "delay_minutes": None,
    }


def save_flights(records: list[dict], flight_number: str, query_date: str) -> None:
    """Persist a list of normalized flight records, and update the observed
    route + delay-stats tables. Never raises — caching failures shouldn't
    break the user-facing response."""
    try:
        with get_connection_context() as conn:
            for record in records:
                row = _flight_record_to_db_row(record, query_date)
                fid = upsert_flight(conn, row)
                if fid:
                    logger.info("Cached flight %s id=%s (source=%s)", flight_number, fid, record.get("source"))
                    dep_iata = row.get("departure_iata")
                    arr_iata = row.get("arrival_iata")
                    if dep_iata and arr_iata:
                        route_id = record_flight_route(conn, flight_number, dep_iata, arr_iata)
                        if route_id:
                            update_delay_stats(conn, flight_number, route_id)
    except Exception as exc:
        logger.error("save_flights failed: %s", exc)


def save_itineraries(dep_iata: str, arr_iata: str, travel_date: str, currency: str, itineraries_raw: list[dict]) -> None:
    """Persist a full set of SearchApi itineraries (with ordered legs and
    layovers) using the delete-and-replace strategy."""
    now_utc = datetime.datetime.now(tz=datetime.timezone.utc)
    try:
        with get_connection_context() as conn:
            dep_row = get_airport_by_iata(conn, dep_iata)
            if not dep_row:
                upsert_airport(conn, {"iata_code": dep_iata, "name": dep_iata, "fetch_at": now_utc})
                dep_row = get_airport_by_iata(conn, dep_iata)

            arr_row = get_airport_by_iata(conn, arr_iata)
            if not arr_row:
                upsert_airport(conn, {"iata_code": arr_iata, "name": arr_iata, "fetch_at": now_utc})
                arr_row = get_airport_by_iata(conn, arr_iata)

            if not dep_row or not arr_row:
                logger.warning("save_itineraries: could not resolve airports %s / %s", dep_iata, arr_iata)
                return

            search_id = create_route_search(conn, {
                "origin_airport_id": dep_row["airport_id"],
                "destination_airport_id": arr_row["airport_id"],
                "search_date": now_utc.strftime("%Y-%m-%d"),
                "travel_date": travel_date,
                "currency": currency,
                "trip_type": "one_way",
                "fetch_at": now_utc,
            })

            n = save_itineraries_to_db(
                conn,
                dep_airport_id=dep_row["airport_id"],
                arr_airport_id=arr_row["airport_id"],
                travel_date=travel_date,
                search_id=search_id,
                itineraries_raw=itineraries_raw,
                currency=currency,
                fetch_at=now_utc,
            )
            logger.info("save_itineraries: %s itineraries saved for %s->%s %s", n, dep_iata, arr_iata, travel_date)
    except Exception as exc:
        logger.error("save_itineraries failed: %s", exc)
