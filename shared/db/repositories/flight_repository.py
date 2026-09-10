"""
database/repositories/flight_repository.py
===========================================
Data-access functions for the `flights` table.

Flights are the central entity — every read query JOINs airports and airlines
so callers get full human-readable data back without extra round trips.
"""

import logging
from typing import Optional
import datetime

import psycopg
from psycopg.rows import dict_row

from shared.db.repositories.airport_repository import upsert_airport, get_airport_by_iata
from shared.db.repositories.airline_repository import upsert_airline, get_airline_by_iata
from shared.db.repositories.aircraft_repository import upsert_aircraft

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared JOIN query
# ---------------------------------------------------------------------------

_FLIGHT_SELECT = """
    SELECT
        f.flight_id,
        f.flight_number,
        f.query_date,
        f.status,
        f.departure_scheduled,
        f.departure_actual,
        f.departure_estimated,
        f.departure_terminal,
        f.departure_gate,
        f.arrival_scheduled,
        f.arrival_actual,
        f.arrival_estimated,
        f.arrival_terminal,
        f.arrival_gate,
        f.arrival_baggage_belt,
        f.delay_minutes,
        f.fetch_at,

        -- Departure airport
        da.airport_id       AS dep_airport_id,
        da.iata_code        AS dep_iata,
        da.icao_code        AS dep_icao,
        da.name             AS dep_airport_name,
        da.city             AS dep_city,
        da.country          AS dep_country,

        -- Arrival airport
        aa.airport_id       AS arr_airport_id,
        aa.iata_code        AS arr_iata,
        aa.icao_code        AS arr_icao,
        aa.name             AS arr_airport_name,
        aa.city             AS arr_city,
        aa.country          AS arr_country,

        -- Airline
        al.airline_id,
        al.iata_code        AS airline_iata,
        al.name             AS airline_name,

        -- Aircraft
        ac.aircraft_id,
        ac.registration     AS aircraft_reg,
        ac.model            AS aircraft_model

    FROM flights f
    LEFT JOIN airports da ON f.departure_airport_id = da.airport_id
    LEFT JOIN airports aa ON f.arrival_airport_id   = aa.airport_id
    LEFT JOIN airlines al ON f.airline_id            = al.airline_id
    LEFT JOIN aircraft ac ON f.aircraft_id           = ac.aircraft_id
"""


# ---------------------------------------------------------------------------
# Write operations
# ---------------------------------------------------------------------------

def upsert_flight(conn: psycopg.Connection, data: dict) -> Optional[int]:
    """
    Full transactional upsert of a flight and all related entities.

    Expected `data` keys (mirroring AeroDataBox response parsed structure):
        flight_number       str   required
        query_date          str   "YYYY-MM-DD"
        status              str
        fetch_at            datetime (timezone-aware)

        departure_iata      str
        departure_icao      str
        departure_name      str
        departure_city      str
        departure_country   str
        departure_country_code str
        departure_lat       float
        departure_lon       float
        departure_timezone  str
        departure_scheduled str   ISO-8601
        departure_actual    str
        departure_estimated str
        departure_terminal  str
        departure_gate      str

        arrival_*           (same shape as departure_*)
        arrival_baggage_belt str

        airline_iata        str
        airline_icao        str
        airline_name        str

        aircraft_registration str
        aircraft_model      str

        delay_minutes       int

    Returns flight_id or None on error.
    """
    now_utc = datetime.datetime.now(tz=datetime.timezone.utc)
    fetch_at = data.get("fetch_at") or now_utc

    def parse_ts(val):
        if not val:
            return None
        if isinstance(val, datetime.datetime):
            return val
        try:
            return datetime.datetime.fromisoformat(val.replace("Z", "+00:00"))
        except Exception:
            return None

    try:
        # ── 1. Upsert departure airport ──────────────────────────────────
        dep_airport_id = None
        if data.get("departure_iata") or data.get("departure_name"):
            dep_airport_id = upsert_airport(conn, {
                "iata_code":    data.get("departure_iata"),
                "icao_code":    data.get("departure_icao"),
                "name":         data.get("departure_name") or data.get("departure_iata", "Unknown"),
                "city":         data.get("departure_city"),
                "country":      data.get("departure_country"),
                "country_code": data.get("departure_country_code"),
                "latitude":     data.get("departure_lat"),
                "longitude":    data.get("departure_lon"),
                "timezone":     data.get("departure_timezone"),
                "fetch_at":     fetch_at,
            })

        # ── 2. Upsert arrival airport ────────────────────────────────────
        arr_airport_id = None
        if data.get("arrival_iata") or data.get("arrival_name"):
            arr_airport_id = upsert_airport(conn, {
                "iata_code":    data.get("arrival_iata"),
                "icao_code":    data.get("arrival_icao"),
                "name":         data.get("arrival_name") or data.get("arrival_iata", "Unknown"),
                "city":         data.get("arrival_city"),
                "country":      data.get("arrival_country"),
                "country_code": data.get("arrival_country_code"),
                "latitude":     data.get("arrival_lat"),
                "longitude":    data.get("arrival_lon"),
                "timezone":     data.get("arrival_timezone"),
                "fetch_at":     fetch_at,
            })

        if not dep_airport_id or not arr_airport_id:
            logger.warning(
                "upsert_flight: missing dep(%s) or arr(%s) airport, skipping flight %s",
                dep_airport_id, arr_airport_id, data.get("flight_number"),
            )
            return None

        # ── 3. Upsert airline ────────────────────────────────────────────
        airline_id = None
        if data.get("airline_name") or data.get("airline_iata"):
            airline_id = upsert_airline(conn, {
                "iata_code": data.get("airline_iata"),
                "icao_code": data.get("airline_icao"),
                "name":      data.get("airline_name") or data.get("airline_iata", "Unknown"),
                "fetch_at":  fetch_at,
            })

        # ── 4. Upsert aircraft ───────────────────────────────────────────
        aircraft_id = None
        if data.get("aircraft_registration") or data.get("aircraft_model"):
            aircraft_id = upsert_aircraft(conn, {
                "registration": data.get("aircraft_registration"),
                "model":        data.get("aircraft_model"),
                "fetch_at":     fetch_at,
            })

        # ── 5. Upsert flight row ─────────────────────────────────────────
        query_date = data.get("query_date")
        if query_date and isinstance(query_date, str):
            try:
                query_date = datetime.date.fromisoformat(query_date)
            except ValueError:
                query_date = None

        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                INSERT INTO flights (
                    flight_number, query_date,
                    airline_id, aircraft_id,
                    departure_airport_id, arrival_airport_id,
                    status,
                    departure_scheduled, departure_actual, departure_estimated,
                    departure_terminal, departure_gate,
                    arrival_scheduled, arrival_actual, arrival_estimated,
                    arrival_terminal, arrival_gate, arrival_baggage_belt,
                    delay_minutes, fetch_at, created_at, updated_at
                )
                VALUES (
                    %(flight_number)s, %(query_date)s,
                    %(airline_id)s, %(aircraft_id)s,
                    %(dep_airport_id)s, %(arr_airport_id)s,
                    %(status)s,
                    %(dep_sched)s, %(dep_actual)s, %(dep_est)s,
                    %(dep_terminal)s, %(dep_gate)s,
                    %(arr_sched)s, %(arr_actual)s, %(arr_est)s,
                    %(arr_terminal)s, %(arr_gate)s, %(arr_baggage)s,
                    %(delay_minutes)s, %(fetch_at)s, NOW(), NOW()
                )
                ON CONFLICT (flight_number, query_date, departure_airport_id, arrival_airport_id)
                DO UPDATE SET
                    airline_id          = COALESCE(EXCLUDED.airline_id,         flights.airline_id),
                    aircraft_id         = COALESCE(EXCLUDED.aircraft_id,        flights.aircraft_id),
                    status              = EXCLUDED.status,
                    departure_scheduled = COALESCE(EXCLUDED.departure_scheduled, flights.departure_scheduled),
                    departure_actual    = COALESCE(EXCLUDED.departure_actual,    flights.departure_actual),
                    departure_estimated = COALESCE(EXCLUDED.departure_estimated, flights.departure_estimated),
                    departure_terminal  = COALESCE(EXCLUDED.departure_terminal,  flights.departure_terminal),
                    departure_gate      = COALESCE(EXCLUDED.departure_gate,      flights.departure_gate),
                    arrival_scheduled   = COALESCE(EXCLUDED.arrival_scheduled,   flights.arrival_scheduled),
                    arrival_actual      = COALESCE(EXCLUDED.arrival_actual,      flights.arrival_actual),
                    arrival_estimated   = COALESCE(EXCLUDED.arrival_estimated,   flights.arrival_estimated),
                    arrival_terminal    = COALESCE(EXCLUDED.arrival_terminal,    flights.arrival_terminal),
                    arrival_gate        = COALESCE(EXCLUDED.arrival_gate,        flights.arrival_gate),
                    arrival_baggage_belt= COALESCE(EXCLUDED.arrival_baggage_belt,flights.arrival_baggage_belt),
                    delay_minutes       = EXCLUDED.delay_minutes,
                    fetch_at            = EXCLUDED.fetch_at,
                    updated_at          = NOW()
                RETURNING flight_id
                """,
                {
                    "flight_number":  data.get("flight_number", "").strip().upper(),
                    "query_date":     query_date,
                    "airline_id":     airline_id,
                    "aircraft_id":    aircraft_id,
                    "dep_airport_id": dep_airport_id,
                    "arr_airport_id": arr_airport_id,
                    "status":         data.get("status"),
                    "dep_sched":      parse_ts(data.get("departure_scheduled")),
                    "dep_actual":     parse_ts(data.get("departure_actual")),
                    "dep_est":        parse_ts(data.get("departure_estimated")),
                    "dep_terminal":   data.get("departure_terminal"),
                    "dep_gate":       data.get("departure_gate"),
                    "arr_sched":      parse_ts(data.get("arrival_scheduled")),
                    "arr_actual":     parse_ts(data.get("arrival_actual")),
                    "arr_est":        parse_ts(data.get("arrival_estimated")),
                    "arr_terminal":   data.get("arrival_terminal"),
                    "arr_gate":       data.get("arrival_gate"),
                    "arr_baggage":    data.get("arrival_baggage_belt"),
                    "delay_minutes":  data.get("delay_minutes"),
                    "fetch_at":       fetch_at,
                },
            )
            row = cur.fetchone()
            flight_id = row["flight_id"] if row else None
            logger.debug(
                "upsert_flight: id=%s flight=%s date=%s",
                flight_id, data.get("flight_number"), query_date,
            )
            return flight_id

    except psycopg.Error as exc:
        conn.rollback()
        logger.error("upsert_flight error: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------

def get_flight(
    conn: psycopg.Connection,
    flight_number: str,
    query_date: Optional[str] = None,
) -> list[dict]:
    """
    Return all matching flight rows (with JOINed airport/airline data)
    for a given flight number, optionally filtered by date.
    """
    flight_number = flight_number.strip().upper()

    with conn.cursor(row_factory=dict_row) as cur:
        if query_date:
            try:
                date_val = datetime.date.fromisoformat(query_date)
            except ValueError:
                date_val = None
        else:
            date_val = None

        if date_val:
            cur.execute(
                _FLIGHT_SELECT
                + " WHERE f.flight_number = %s AND f.query_date = %s ORDER BY f.departure_scheduled",
                (flight_number, date_val),
            )
        else:
            cur.execute(
                _FLIGHT_SELECT
                + " WHERE f.flight_number = %s ORDER BY f.query_date DESC, f.departure_scheduled",
                (flight_number,),
            )
        return cur.fetchall()


def search_flights_by_route(
    conn: psycopg.Connection,
    dep_iata: str,
    arr_iata: str,
    query_date: Optional[str] = None,
) -> list[dict]:
    """
    Search flights by departure+arrival IATA codes, optionally on a specific date.
    Returns rows with full airport/airline JOIN data.
    """
    dep_iata = dep_iata.strip().upper()
    arr_iata = arr_iata.strip().upper()

    with conn.cursor(row_factory=dict_row) as cur:
        if query_date:
            try:
                date_val = datetime.date.fromisoformat(query_date)
            except ValueError:
                date_val = None
        else:
            date_val = None

        if date_val:
            cur.execute(
                _FLIGHT_SELECT
                + """
                WHERE da.iata_code = %s
                  AND aa.iata_code = %s
                  AND f.query_date = %s
                ORDER BY f.departure_scheduled
                """,
                (dep_iata, arr_iata, date_val),
            )
        else:
            cur.execute(
                _FLIGHT_SELECT
                + """
                WHERE da.iata_code = %s
                  AND aa.iata_code = %s
                ORDER BY f.query_date DESC, f.departure_scheduled
                LIMIT 20
                """,
                (dep_iata, arr_iata),
            )
        return cur.fetchall()


def get_flight_history(
    conn: psycopg.Connection,
    flight_number: str,
    dep_airport_id: int,
    arr_airport_id: int,
    weeks: int = 8,
) -> list[dict]:
    """
    Return the last `weeks` weeks of observed flight rows for a specific
    flight number + departure/arrival airport pair.

    Used by schedule_repository.infer_and_update_schedule() to build
    weekly operating patterns from real observations.

    Returns rows with: query_date, departure_scheduled, arrival_scheduled,
    dep_iata, dep_timezone, arr_iata, arr_timezone, airline_id.
    Only rows with a non-null departure_scheduled are returned.
    """
    flight_number = flight_number.strip().upper()
    cutoff = datetime.date.today() - datetime.timedelta(weeks=weeks)

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT
                f.query_date,
                f.departure_scheduled,
                f.arrival_scheduled,
                f.airline_id,
                da.iata_code  AS dep_iata,
                da.timezone   AS dep_timezone,
                aa.iata_code  AS arr_iata,
                aa.timezone   AS arr_timezone
            FROM flights f
            LEFT JOIN airports da ON f.departure_airport_id = da.airport_id
            LEFT JOIN airports aa ON f.arrival_airport_id   = aa.airport_id
            WHERE f.flight_number        = %s
              AND f.departure_airport_id = %s
              AND f.arrival_airport_id   = %s
              AND f.query_date           >= %s
              AND f.departure_scheduled  IS NOT NULL
            ORDER BY f.query_date DESC
            LIMIT 60
            """,
            (flight_number, dep_airport_id, arr_airport_id, cutoff),
        )
        return cur.fetchall()
