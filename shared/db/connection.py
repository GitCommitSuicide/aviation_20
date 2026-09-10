"""
database/connection.py
======================
Reusable PostgreSQL connection module for the Aviation Chatbot.

Usage:
    from shared.db.connection import get_connection, get_connection_context

    # One-off connection (caller must close):
    conn = get_connection()
    ...
    conn.close()

    # Preferred — context-manager (auto-commits or rolls back, always closes):
    from shared.db.connection import get_connection_context
    with get_connection_context() as conn:
        conn.execute(...)

Environment variables (read from .env):
    DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD

Defaults fall back to local dev credentials so the app works without a .env.
"""

import logging
import os
from contextlib import contextmanager

import psycopg
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def get_db_config() -> dict:
    """
    Build the psycopg connection-keyword dict from environment variables.
    Falls back to local dev defaults so the project works out of the box
    without a .env file.

    To switch to environment variables in production, simply set these vars:
        DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
    """
    return {
        "host":     os.getenv("DB_HOST",     "localhost"),
        "port":     int(os.getenv("DB_PORT", "5444")),
        "dbname":   os.getenv("DB_NAME",     "aviation_chatbot"),
        "user":     os.getenv("DB_USER",     "postgres"),
        "password": os.getenv("DB_PASSWORD", "Anil123"),
    }


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------

def get_connection() -> psycopg.Connection:
    """
    Open and return a new psycopg connection.
    The caller is responsible for calling conn.close() (or using
    get_connection_context() which handles this automatically).
    """
    config = get_db_config()
    try:
        conn = psycopg.connect(**config)
        logger.debug(
            "DB connected: host=%s port=%s dbname=%s user=%s",
            config["host"], config["port"], config["dbname"], config["user"],
        )
        return conn
    except psycopg.OperationalError as exc:
        logger.error("PostgreSQL connection failed: %s", exc)
        raise


@contextmanager
def get_connection_context():
    """
    Context-manager that opens a connection, yields it, commits on clean exit,
    rolls back on exception, and always closes the connection.

    Example:
        with get_connection_context() as conn:
            conn.execute("SELECT 1")
    """
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
