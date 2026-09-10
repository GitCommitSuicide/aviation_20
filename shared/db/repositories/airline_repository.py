"""
database/repositories/airline_repository.py
============================================
Data-access functions for the `airlines` table.
"""

import logging
from typing import Optional

import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Write operations
# ---------------------------------------------------------------------------

def upsert_airline(conn: psycopg.Connection, data: dict) -> Optional[int]:
    """
    Insert or update an airline row.

    `data` keys:
        iata_code, icao_code, name (required), country, country_code,
        basic_facilities (dict/JSON), rating, fleet_size, website, fetch_at

    Returns airline_id or None on error.
    """
    import json

    iata = (data.get("iata_code") or "").strip().upper() or None
    icao = (data.get("icao_code") or "").strip().upper() or None
    name = (data.get("name") or "").strip()

    if not name:
        logger.warning("upsert_airline: 'name' is required, skipping.")
        return None

    # Serialise facilities dict to JSON string for psycopg
    facilities = data.get("basic_facilities")
    facilities_json = json.dumps(facilities) if isinstance(facilities, dict) else facilities

    try:
        with conn.cursor(row_factory=dict_row) as cur:
            if iata:
                # Prefer IATA as conflict target
                cur.execute(
                    """
                    INSERT INTO airlines (
                        iata_code, icao_code, name, country, country_code,
                        basic_facilities, rating, fleet_size, website,
                        fetch_at, created_at, updated_at
                    )
                    VALUES (
                        %(iata_code)s, %(icao_code)s, %(name)s, %(country)s, %(country_code)s,
                        %(basic_facilities)s::jsonb, %(rating)s, %(fleet_size)s, %(website)s,
                        %(fetch_at)s, NOW(), NOW()
                    )
                    ON CONFLICT (iata_code) DO UPDATE SET
                        icao_code        = COALESCE(EXCLUDED.icao_code,        airlines.icao_code),
                        name             = EXCLUDED.name,
                        country          = COALESCE(EXCLUDED.country,          airlines.country),
                        country_code     = COALESCE(EXCLUDED.country_code,     airlines.country_code),
                        basic_facilities = COALESCE(EXCLUDED.basic_facilities, airlines.basic_facilities),
                        rating           = COALESCE(EXCLUDED.rating,           airlines.rating),
                        fleet_size       = COALESCE(EXCLUDED.fleet_size,       airlines.fleet_size),
                        website          = COALESCE(EXCLUDED.website,          airlines.website),
                        fetch_at         = EXCLUDED.fetch_at,
                        updated_at       = NOW()
                    RETURNING airline_id
                    """,
                    {
                        "iata_code":        iata,
                        "icao_code":        icao,
                        "name":             name,
                        "country":          data.get("country"),
                        "country_code":     data.get("country_code"),
                        "basic_facilities": facilities_json,
                        "rating":           data.get("rating"),
                        "fleet_size":       data.get("fleet_size"),
                        "website":          data.get("website"),
                        "fetch_at":         data.get("fetch_at"),
                    },
                )
            else:
                # No IATA — insert by name only (SearchAPI case)
                # Check if an airline with this name already exists
                cur.execute(
                    "SELECT airline_id FROM airlines WHERE LOWER(name) = LOWER(%s) LIMIT 1",
                    (name,),
                )
                existing = cur.fetchone()
                if existing:
                    return existing["airline_id"]

                cur.execute(
                    """
                    INSERT INTO airlines (
                        iata_code, icao_code, name, country, country_code,
                        basic_facilities, rating, fleet_size, website,
                        fetch_at, created_at, updated_at
                    )
                    VALUES (
                        NULL, %(icao_code)s, %(name)s, %(country)s, %(country_code)s,
                        %(basic_facilities)s::jsonb, %(rating)s, %(fleet_size)s, %(website)s,
                        %(fetch_at)s, NOW(), NOW()
                    )
                    RETURNING airline_id
                    """,
                    {
                        "icao_code":        icao,
                        "name":             name,
                        "country":          data.get("country"),
                        "country_code":     data.get("country_code"),
                        "basic_facilities": facilities_json,
                        "rating":           data.get("rating"),
                        "fleet_size":       data.get("fleet_size"),
                        "website":          data.get("website"),
                        "fetch_at":         data.get("fetch_at"),
                    },
                )

            row = cur.fetchone()
            airline_id = row["airline_id"] if row else None
            logger.debug("upsert_airline: id=%s name=%s", airline_id, name)
            return airline_id
    except psycopg.Error as exc:
        conn.rollback()
        logger.error("upsert_airline error: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------

def get_airline_by_iata(conn: psycopg.Connection, iata: str) -> Optional[dict]:
    """Return a single airline dict by IATA code, or None."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT * FROM airlines WHERE iata_code = %s LIMIT 1",
            (iata.strip().upper(),),
        )
        return cur.fetchone()


def get_airline_by_id(conn: psycopg.Connection, airline_id: int) -> Optional[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT * FROM airlines WHERE airline_id = %s LIMIT 1",
            (airline_id,),
        )
        return cur.fetchone()


def search_airlines(conn: psycopg.Connection, query: str, limit: int = 10) -> list[dict]:
    """Search airlines by IATA code, name, or country."""
    q = query.strip().upper()
    q_lower = query.strip().lower()

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT *,
                CASE
                    WHEN iata_code = %(q)s            THEN 1
                    WHEN icao_code = %(q)s            THEN 2
                    WHEN LOWER(name) = %(q_lower)s   THEN 3
                    ELSE 4
                END AS rank
            FROM airlines
            WHERE
                iata_code = %(q)s
                OR icao_code = %(q)s
                OR LOWER(name)    LIKE %(like)s
                OR LOWER(country) LIKE %(like)s
            ORDER BY rank, name
            LIMIT %(limit)s
            """,
            {"q": q, "q_lower": q_lower, "like": f"%{q_lower}%", "limit": limit},
        )
        return cur.fetchall()
