"""
database/repositories/airport_repository.py
============================================
Data-access functions for the `airports` table.

All functions accept an open psycopg connection and use parameterised queries
(never string-interpolated SQL) to prevent SQL injection.
"""

import logging
from typing import Optional

import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Write operations
# ---------------------------------------------------------------------------

def upsert_airport(conn: psycopg.Connection, data: dict) -> Optional[int]:
    """
    Insert or update an airport row.

    `data` keys (all optional except `name`):
        iata_code, icao_code, name, city, country, country_code,
        latitude, longitude, timezone, airport_type, fetch_at

    The UPSERT key is iata_code (preferred) or icao_code.
    Returns the airport_id of the inserted/updated row, or None on error.
    """
    # Normalise codes to uppercase
    iata = (data.get("iata_code") or "").strip().upper() or None
    icao = (data.get("icao_code") or "").strip().upper() or None

    if not iata and not icao:
        logger.warning("upsert_airport: no IATA or ICAO code provided, skipping.")
        return None

    name = (data.get("name") or "").strip()
    if not name:
        logger.warning("upsert_airport: 'name' is required, skipping.")
        return None

    try:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                INSERT INTO airports (
                    iata_code, icao_code, name, city, country, country_code,
                    latitude, longitude, timezone, airport_type, fetch_at,
                    created_at, updated_at
                )
                VALUES (
                    %(iata_code)s, %(icao_code)s, %(name)s, %(city)s,
                    %(country)s, %(country_code)s,
                    %(latitude)s, %(longitude)s,
                    %(timezone)s, %(airport_type)s, %(fetch_at)s,
                    NOW(), NOW()
                )
                ON CONFLICT (iata_code) DO UPDATE SET
                    icao_code    = COALESCE(EXCLUDED.icao_code,    airports.icao_code),
                    name         = EXCLUDED.name,
                    city         = COALESCE(EXCLUDED.city,         airports.city),
                    country      = COALESCE(EXCLUDED.country,      airports.country),
                    country_code = COALESCE(EXCLUDED.country_code, airports.country_code),
                    latitude     = COALESCE(EXCLUDED.latitude,     airports.latitude),
                    longitude    = COALESCE(EXCLUDED.longitude,    airports.longitude),
                    timezone     = COALESCE(EXCLUDED.timezone,     airports.timezone),
                    airport_type = COALESCE(EXCLUDED.airport_type, airports.airport_type),
                    fetch_at     = EXCLUDED.fetch_at,
                    updated_at   = NOW()
                RETURNING airport_id
                """,
                {
                    "iata_code":    iata,
                    "icao_code":    icao,
                    "name":         name,
                    "city":         data.get("city"),
                    "country":      data.get("country"),
                    "country_code": data.get("country_code"),
                    "latitude":     data.get("latitude"),
                    "longitude":    data.get("longitude"),
                    "timezone":     data.get("timezone"),
                    "airport_type": data.get("airport_type"),
                    "fetch_at":     data.get("fetch_at"),
                },
            )
            row = cur.fetchone()
            airport_id = row["airport_id"] if row else None
            logger.debug("upsert_airport: id=%s iata=%s", airport_id, iata)
            return airport_id
    except psycopg.errors.UniqueViolation:
        # Could happen on icao_code conflict if iata is NULL — try icao conflict path
        conn.rollback()
        logger.warning("upsert_airport: UniqueViolation on iata=%s icao=%s", iata, icao)
        return None
    except psycopg.Error as exc:
        conn.rollback()
        logger.error("upsert_airport error: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------

def get_airport_by_iata(conn: psycopg.Connection, iata: str) -> Optional[dict]:
    """Return a single airport dict by IATA code, or None."""
    iata = iata.strip().upper()
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT * FROM airports WHERE iata_code = %s LIMIT 1",
            (iata,),
        )
        return cur.fetchone()


def get_airport_by_icao(conn: psycopg.Connection, icao: str) -> Optional[dict]:
    """Return a single airport dict by ICAO code, or None."""
    icao = icao.strip().upper()
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT * FROM airports WHERE icao_code = %s LIMIT 1",
            (icao,),
        )
        return cur.fetchone()


def get_airport_by_id(conn: psycopg.Connection, airport_id: int) -> Optional[dict]:
    """Return a single airport dict by primary key, or None."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT * FROM airports WHERE airport_id = %s LIMIT 1",
            (airport_id,),
        )
        return cur.fetchone()


def search_airports(conn: psycopg.Connection, query: str, limit: int = 10) -> list[dict]:
    """
    Search airports by IATA code, ICAO code, name, city, or country.
    Returns up to `limit` matches ordered by relevance (exact IATA first).
    """
    q = query.strip().upper()
    q_lower = query.strip().lower()

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT *,
                CASE
                    WHEN iata_code = %(q)s             THEN 1
                    WHEN icao_code = %(q)s             THEN 2
                    WHEN LOWER(city)    = %(q_lower)s  THEN 3
                    WHEN LOWER(country) = %(q_lower)s  THEN 4
                    ELSE 5
                END AS rank
            FROM airports
            WHERE
                iata_code    =  %(q)s
                OR icao_code =  %(q)s
                OR LOWER(city)     LIKE %(like)s
                OR LOWER(country)  LIKE %(like)s
                OR LOWER(name)     LIKE %(like)s
            ORDER BY rank, name
            LIMIT %(limit)s
            """,
            {"q": q, "q_lower": q_lower, "like": f"%{q_lower}%", "limit": limit},
        )
        return cur.fetchall()
