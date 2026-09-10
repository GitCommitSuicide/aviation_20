"""
database/repositories/stats_repository.py
=========================================
Operations for flight_routes and flight_delay_stats tables.
"""

import datetime
import logging
from typing import Optional

import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)

def record_flight_route(
    conn: psycopg.Connection,
    flight_number: str,
    origin_iata: str,
    destination_iata: str,
) -> Optional[int]:
    """
    Upserts a flight route into flight_routes. Increments observation_count
    and updates last_seen if it already exists.
    Returns the route_id.
    """
    flight_number = flight_number.strip().upper()
    origin_iata = origin_iata.strip().upper()
    destination_iata = destination_iata.strip().upper()

    try:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                INSERT INTO flight_routes (flight_number, origin_iata, destination_iata)
                VALUES (%s, %s, %s)
                ON CONFLICT (flight_number, origin_iata, destination_iata)
                DO UPDATE SET
                    last_seen = NOW(),
                    observation_count = flight_routes.observation_count + 1
                RETURNING route_id
                """,
                (flight_number, origin_iata, destination_iata),
            )
            row = cur.fetchone()
            return row["route_id"] if row else None
    except psycopg.Error as exc:
        conn.rollback()
        logger.error("record_flight_route error: %s", exc)
        return None


def get_flight_routes(
    conn: psycopg.Connection,
    flight_number: str,
) -> list[dict]:
    """Return all observed routes for a flight number."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT * FROM flight_routes
            WHERE flight_number = %s
            ORDER BY observation_count DESC
            """,
            (flight_number.strip().upper(),)
        )
        return cur.fetchall()


def update_delay_stats(
    conn: psycopg.Connection,
    flight_number: str,
    route_id: int,
) -> None:
    """
    Recalculates delay stats for a specific flight + route by reading from the
    flights table, and upserts into flight_delay_stats.
    """
    flight_number = flight_number.strip().upper()

    try:
        with conn.cursor(row_factory=dict_row) as cur:
            # First, fetch all flights for this number and route origin/dest
            # We need to know origin and dest for this route_id
            cur.execute("SELECT origin_iata, destination_iata FROM flight_routes WHERE route_id = %s", (route_id,))
            route = cur.fetchone()
            if not route:
                return

            cur.execute(
                """
                SELECT f.departure_scheduled, f.departure_actual, f.departure_estimated
                FROM flights f
                JOIN airports da ON f.departure_airport_id = da.airport_id
                JOIN airports aa ON f.arrival_airport_id = aa.airport_id
                WHERE f.flight_number = %s
                  AND da.iata_code = %s
                  AND aa.iata_code = %s
                  AND f.departure_scheduled IS NOT NULL
                  AND (f.departure_actual IS NOT NULL OR f.departure_estimated IS NOT NULL)
                """,
                (flight_number, route["origin_iata"], route["destination_iata"])
            )
            flights = cur.fetchall()

            if not flights:
                return

            delays = []
            on_time_count = 0
            for f in flights:
                sched = f["departure_scheduled"]
                # Use actual if available, else estimated
                actual = f["departure_actual"] or f["departure_estimated"]
                
                # Sched and actual should be tz-aware UTC
                if sched and actual:
                    delay_mins = max(0, int((actual - sched).total_seconds() / 60))
                    delays.append(delay_mins)
                    # We define "on time" as < 15 minutes delay
                    if delay_mins < 15:
                        on_time_count += 1
            
            if not delays:
                return

            total_obs = len(delays)
            avg_delay = sum(delays) // total_obs
            delays.sort()
            median_delay = delays[total_obs // 2]
            on_time_pct = (on_time_count / total_obs) * 100.0

            cur.execute(
                """
                INSERT INTO flight_delay_stats (
                    flight_number, route_id, total_observations, 
                    average_delay_mins, median_delay_mins, on_time_percentage
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (flight_number, route_id)
                DO UPDATE SET
                    total_observations = EXCLUDED.total_observations,
                    average_delay_mins = EXCLUDED.average_delay_mins,
                    median_delay_mins = EXCLUDED.median_delay_mins,
                    on_time_percentage = EXCLUDED.on_time_percentage,
                    last_calculated = NOW()
                """,
                (flight_number, route_id, total_obs, avg_delay, median_delay, on_time_pct)
            )
    except psycopg.Error as exc:
        conn.rollback()
        logger.error("update_delay_stats error: %s", exc)


def get_delay_stats(
    conn: psycopg.Connection,
    flight_number: str,
) -> list[dict]:
    """Returns delay stats joined with route details for a given flight number."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT s.*, r.origin_iata, r.destination_iata
            FROM flight_delay_stats s
            JOIN flight_routes r ON s.route_id = r.route_id
            WHERE s.flight_number = %s
            """,
            (flight_number.strip().upper(),)
        )
        return cur.fetchall()
