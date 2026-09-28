"""
scripts/init_database.py
========================
One-time (idempotent) database initialisation script.

Usage:
    python scripts/init_database.py

What it does:
    1. Reads DB credentials from .env (or uses local dev defaults).
    2. Connects to PostgreSQL.
    3. Executes database/schema.sql (CREATE TABLE IF NOT EXISTS — safe to re-run).
    4. Verifies all expected tables exist.
    5. Prints a clear success/failure report.
"""

import os
import sys

# Allow running from the project root or from the scripts/ directory
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

from dotenv import load_dotenv
load_dotenv()

import psycopg
from shared.db.connection import get_connection, get_db_config

SCHEMA_PATH = os.path.join(project_root, "shared", "db", "schema.sql")

EXPECTED_TABLES = [
    "airports",
    "airlines",
    "aircraft",
    "flights",
    "route_searches",
    "itineraries",
    "itinerary_legs",
    "flight_schedules",
    "flight_routes",
    "flight_delay_stats",
    "semantic_cache",
]



def run_schema(conn: psycopg.Connection) -> None:
    """Read and execute schema.sql."""
    if not os.path.exists(SCHEMA_PATH):
        raise FileNotFoundError(f"Schema file not found: {SCHEMA_PATH}")

    with open(SCHEMA_PATH, encoding="utf-8") as f:
        sql = f.read()

    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()
    logger.info("schema.sql executed successfully.")


def verify_tables(conn: psycopg.Connection) -> dict[str, bool]:
    """Check that all expected tables exist in the public schema."""
    results: dict[str, bool] = {}
    with conn.cursor() as cur:
        for table in EXPECTED_TABLES:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public'
                      AND table_name   = %s
                )
                """,
                (table,),
            )
            row = cur.fetchone()
            results[table] = bool(row and row[0])
    return results


def main() -> None:
    cfg = get_db_config()
    print("\n" + "=" * 55)
    print("  Aviation Chatbot — Database Initialisation")
    print("=" * 55)
    print(f"  Host    : {cfg['host']}:{cfg['port']}")
    print(f"  Database: {cfg['dbname']}")
    print(f"  User    : {cfg['user']}")
    print("=" * 55 + "\n")

    # Step 1 — connect
    try:
        conn = get_connection()
        print("[OK]  Connected to PostgreSQL\n")
    except Exception as exc:
        print(f"[FAIL]  Cannot connect to PostgreSQL: {exc}")
        print("\nMake sure PostgreSQL is running and credentials in .env are correct.")
        sys.exit(1)

    # Step 2 — run schema
    try:
        run_schema(conn)
        print("[OK]  Schema applied (schema.sql)\n")
    except Exception as exc:
        print(f"[FAIL]  Failed to apply schema: {exc}")
        conn.close()
        sys.exit(1)

    # Step 3 — verify tables
    print("Verifying tables...")
    results = verify_tables(conn)
    all_ok = True
    for table, exists in results.items():
        status = "[OK]" if exists else "[FAIL]"
        print(f"  {status}  {table}")
        if not exists:
            all_ok = False

    conn.close()

    print()
    if all_ok:
        print("[OK]  All tables verified. Database is ready!\n")
    else:
        missing = [t for t, ok in results.items() if not ok]
        print(f"[FAIL]  Missing tables: {missing}")
        print("    Check schema.sql for errors and re-run this script.\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
