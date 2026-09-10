"""
servers/database_server/tools/_common.py
==========================================
Small helpers shared by every database_server tool: JSON-safe serialization
of datetime/date values, and a uniform result envelope so the chat agent can
consistently decide "use this" vs "fall back to the aviation server".
"""

import datetime
from typing import Any


def serialise(obj: Any) -> Any:
    if isinstance(obj, (datetime.datetime, datetime.date)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: serialise(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [serialise(i) for i in obj]
    return obj


def make_result(found: bool, fresh: bool, data: Any, note: str = "") -> dict:
    return {
        "source": "database",
        "found": found,
        "fresh": fresh,
        "data": serialise(data),
        "note": note,
    }
