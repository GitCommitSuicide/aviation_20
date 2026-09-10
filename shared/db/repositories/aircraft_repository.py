"""
database/repositories/aircraft_repository.py
=============================================
Data-access functions for the `aircraft` table.
""" 

import logging
from typing import Optional

import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Write operations
# ---------------------------------------------------------------------------

def upsert_aircraft(conn: psycopg.Connection, data: dict) -> Optional[int]:
    """
    Insert or update an aircraft row.

    `data` keys:
        registration (unique key), model, manufacturer, aircraft_type,
        iata_type_code, icao_type_code, serial_number, fetch_at

    If `registration` is None/empty, we insert a model-only row without
    a unique constraint (can't upsert reliably), so we simply insert.
    Returns aircraft_id or None.
    """
    registration = (data.get("registration") or "").strip().upper() or None
    model = (data.get("model") or "").strip() or None

    if not registration and not model:
        logger.warning("upsert_aircraft: neither registration nor model provided, skipping.")
        return None

    try:
        with conn.cursor(row_factory=dict_row) as cur:
            if registration:
                cur.execute(
                    """
                    INSERT INTO aircraft (
                        registration, model, manufacturer, aircraft_type,
                        iata_type_code, icao_type_code, serial_number,
                        fetch_at, created_at, updated_at
                    )
                    VALUES (
                        %(registration)s, %(model)s, %(manufacturer)s, %(aircraft_type)s,
                        %(iata_type_code)s, %(icao_type_code)s, %(serial_number)s,
                        %(fetch_at)s, NOW(), NOW()
                    )
                    ON CONFLICT (registration) DO UPDATE SET
                        model          = COALESCE(EXCLUDED.model,          aircraft.model),
                        manufacturer   = COALESCE(EXCLUDED.manufacturer,   aircraft.manufacturer),
                        aircraft_type  = COALESCE(EXCLUDED.aircraft_type,  aircraft.aircraft_type),
                        iata_type_code = COALESCE(EXCLUDED.iata_type_code, aircraft.iata_type_code),
                        icao_type_code = COALESCE(EXCLUDED.icao_type_code, aircraft.icao_type_code),
                        serial_number  = COALESCE(EXCLUDED.serial_number,  aircraft.serial_number),
                        fetch_at       = EXCLUDED.fetch_at,
                        updated_at     = NOW()
                    RETURNING aircraft_id
                    """,
                    {
                        "registration":  registration,
                        "model":         model,
                        "manufacturer":  data.get("manufacturer"),
                        "aircraft_type": data.get("aircraft_type"),
                        "iata_type_code": data.get("iata_type_code"),
                        "icao_type_code": data.get("icao_type_code"),
                        "serial_number": data.get("serial_number"),
                        "fetch_at":      data.get("fetch_at"),
                    },
                )
            else:
                # Model-only (AeroDataBox sometimes omits registration)
                # Check for existing identical model row first
                cur.execute(
                    "SELECT aircraft_id FROM aircraft WHERE model = %s AND registration IS NULL LIMIT 1",
                    (model,),
                )
                existing = cur.fetchone()
                if existing:
                    return existing["aircraft_id"]

                cur.execute(
                    """
                    INSERT INTO aircraft (
                        registration, model, manufacturer, aircraft_type,
                        iata_type_code, icao_type_code, serial_number,
                        fetch_at, created_at, updated_at
                    )
                    VALUES (
                        NULL, %(model)s, %(manufacturer)s, %(aircraft_type)s,
                        %(iata_type_code)s, %(icao_type_code)s, %(serial_number)s,
                        %(fetch_at)s, NOW(), NOW()
                    )
                    RETURNING aircraft_id
                    """,
                    {
                        "model":         model,
                        "manufacturer":  data.get("manufacturer"),
                        "aircraft_type": data.get("aircraft_type"),
                        "iata_type_code": data.get("iata_type_code"),
                        "icao_type_code": data.get("icao_type_code"),
                        "serial_number": data.get("serial_number"),
                        "fetch_at":      data.get("fetch_at"),
                    },
                )

            row = cur.fetchone()
            aircraft_id = row["aircraft_id"] if row else None
            logger.debug("upsert_aircraft: id=%s reg=%s", aircraft_id, registration)
            return aircraft_id
    except psycopg.Error as exc:
        conn.rollback()
        logger.error("upsert_aircraft error: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------

def get_aircraft_by_registration(conn: psycopg.Connection, reg: str) -> Optional[dict]:
    """Return aircraft by tail/registration number, or None."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT * FROM aircraft WHERE registration = %s LIMIT 1",
            (reg.strip().upper(),),
        )
        return cur.fetchone()


def get_aircraft_by_id(conn: psycopg.Connection, aircraft_id: int) -> Optional[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT * FROM aircraft WHERE aircraft_id = %s LIMIT 1",
            (aircraft_id,),
        )
        return cur.fetchone()
