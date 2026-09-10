"""
shared/airport_data.py
=======================
Airport/city name -> IATA code resolution, coordinate lookup, and great-circle
distance helpers. Used by both MCP servers (aviation_server for resolving user
input, database_server for nothing currently, but kept shared in case a future
tool needs it).

Moved out of the old tools/aviation_tools.py so it has no dependency on
LangChain, requests, or any single server — it's pure data/lookup logic.
"""

import math

import airportsdata

# ── Airport reference data (loaded once per process) ────────────────────────
AIRPORTS_BY_IATA = airportsdata.load("IATA")

_CITY_TO_IATA: dict[str, list[str]] = {}
for _code, _info in AIRPORTS_BY_IATA.items():
    _city = _info.get("city", "").strip().lower()
    if _city:
        _CITY_TO_IATA.setdefault(_city, []).append(_code)

# Common city / colloquial names that don't map cleanly via airportsdata's
# `city` field (old names, metro-area names, etc.)
ALTERNATE_NAMES: dict[str, str] = {
    "thiruvananthapuram": "TRV",
    "bengaluru": "BLR",
    "bombay": "BOM",
    "madras": "MAA",
    "calcutta": "CCU",
    "cochin": "COK",
    "vizag": "VTZ",
    "pondicherry": "PNY",
    "varanasi": "VNS",
    "banaras": "VNS",
    "new york": "JFK",
    "london": "LHR",
    "paris": "CDG",
    "singapore": "SIN",
    "dubai": "DXB",
    "hong kong": "HKG",
    "bangkok": "BKK",
    "toronto": "YYZ",
    "sydney": "SYD",
    "san francisco": "SFO",
    "los angeles": "LAX",
}


def resolve_iata(place: str) -> str | None:
    """Resolve a city name or IATA code to a valid 3-letter IATA code."""
    place = place.strip()
    if len(place) == 3 and place.isalpha():
        code = place.upper()
        return code if code in AIRPORTS_BY_IATA else None

    key = place.lower()
    if key in ALTERNATE_NAMES:
        return ALTERNATE_NAMES[key]

    matches = _CITY_TO_IATA.get(key, [])
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        for code in matches:
            if "international" in AIRPORTS_BY_IATA[code].get("name", "").lower():
                return code
        return matches[0]

    for code, info in AIRPORTS_BY_IATA.items():
        if key in info.get("name", "").lower():
            return code

    return None


def get_airport_coords(iata_code: str) -> tuple[float, float] | None:
    """Return (lat, lon) for an IATA airport code, or None."""
    info = AIRPORTS_BY_IATA.get(iata_code)
    if info:
        return (info["lat"], info["lon"])
    return None


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km between two points."""
    R = 6371.0
    rlat1, rlon1 = math.radians(lat1), math.radians(lon1)
    rlat2, rlon2 = math.radians(lat2), math.radians(lon2)
    dlat = rlat2 - rlat1
    dlon = rlon2 - rlon1
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
