"""
servers/aviation_server/providers/normalize.py
================================================
AeroDataBox and Aviationstack return very different JSON shapes. Rather than
have every tool branch on "which provider gave me this", both providers are
normalized here into ONE common flight-record dict. Tools, formatters, and
the DB-persistence layer only ever deal with this common shape.

Common flight-record shape:
{
    "source": "aerodatabox" | "aviationstack",
    "flight_number": str,
    "status": str,
    "airline": {"name": str|None, "iata": str|None, "icao": str|None},
    "aircraft": {"model": str|None, "reg": str|None},
    "departure": {
        "iata": str|None, "icao": str|None, "name": str|None,
        "city": str|None, "country_code": str|None,
        "lat": float|None, "lon": float|None, "timezone": str|None,
        "scheduled_utc": str|None,   # ISO-ish string, parsed later via parse_utc
        "actual_utc": str|None,
        "estimated_utc": str|None,
        "terminal": str|None, "gate": str|None,
    },
    "arrival": {  # same keys as departure, plus:
        ..., "baggage_belt": str|None,
    },
    "movement": {"lat":..,"lon":..,"altitude_m":..,"speed_kmh":..,"heading":..} | None,
}
"""


def normalize_aerodatabox_flight(raw: dict, flight_number: str) -> dict:
    dep = raw.get("departure", {}) or {}
    arr = raw.get("arrival", {}) or {}
    dep_ap = dep.get("airport", {}) or {}
    arr_ap = arr.get("airport", {}) or {}
    airline = raw.get("airline", {}) or {}
    aircraft = raw.get("aircraft", {}) or {}

    def pick(section: dict, *keys) -> str | None:
        for key in keys:
            val = section.get(key)
            if isinstance(val, dict):
                raw_val = val.get("utc")
            else:
                raw_val = val
            if raw_val:
                return raw_val
        return None

    movement = None
    mv = raw.get("movement")
    if mv:
        loc = mv.get("location", {}) or {}
        movement = {
            "lat": loc.get("lat"),
            "lon": loc.get("lon"),
            "altitude_m": mv.get("altitude"),
            "speed_kmh": mv.get("speed"),
            "heading": mv.get("track"),
        }

    return {
        "source": "aerodatabox",
        "flight_number": flight_number,
        "status": raw.get("status", "Unknown"),
        "airline": {
            "name": airline.get("name"),
            "iata": airline.get("iata"),
            "icao": airline.get("icao"),
        },
        "aircraft": {
            "model": aircraft.get("model"),
            "reg": aircraft.get("reg"),
        },
        "departure": {
            "iata": dep_ap.get("iata"),
            "icao": dep_ap.get("icao"),
            "name": dep_ap.get("name"),
            "city": dep_ap.get("municipalityName") or dep_ap.get("shortName"),
            "country_code": dep_ap.get("countryCode"),
            "lat": (dep_ap.get("location") or {}).get("lat"),
            "lon": (dep_ap.get("location") or {}).get("lon"),
            "timezone": dep_ap.get("timeZone"),
            "scheduled_utc": pick(dep, "scheduledTime"),
            "actual_utc": pick(dep, "actualTime", "runwayTime"),
            "estimated_utc": pick(dep, "predictedTime", "revisedTime"),
            "terminal": dep.get("terminal"),
            "gate": dep.get("gate"),
        },
        "arrival": {
            "iata": arr_ap.get("iata"),
            "icao": arr_ap.get("icao"),
            "name": arr_ap.get("name"),
            "city": arr_ap.get("municipalityName") or arr_ap.get("shortName"),
            "country_code": arr_ap.get("countryCode"),
            "lat": (arr_ap.get("location") or {}).get("lat"),
            "lon": (arr_ap.get("location") or {}).get("lon"),
            "timezone": arr_ap.get("timeZone"),
            "scheduled_utc": pick(arr, "scheduledTime"),
            "actual_utc": pick(arr, "actualTime", "runwayTime"),
            "estimated_utc": pick(arr, "predictedTime", "revisedTime"),
            "terminal": arr.get("terminal"),
            "gate": arr.get("gate"),
            "baggage_belt": arr.get("baggageBelt"),
        },
        "movement": movement,
    }


def normalize_aviationstack_flight(raw: dict) -> dict:
    dep = raw.get("departure", {}) or {}
    arr = raw.get("arrival", {}) or {}
    airline = raw.get("airline", {}) or {}
    aircraft = raw.get("aircraft", {}) or {}
    flight = raw.get("flight", {}) or {}
    live = raw.get("live") or {}

    movement = None
    if live and live.get("latitude") is not None:
        movement = {
            "lat": live.get("latitude"),
            "lon": live.get("longitude"),
            "altitude_m": live.get("altitude"),
            "speed_kmh": live.get("speed_horizontal"),
            "heading": live.get("direction"),
        }

    return {
        "source": "aviationstack",
        "flight_number": flight.get("iata") or flight.get("icao") or "UNKNOWN",
        "status": raw.get("flight_status", "unknown"),
        "airline": {
            "name": airline.get("name"),
            "iata": airline.get("iata"),
            "icao": airline.get("icao"),
        },
        "aircraft": {
            # Aviationstack rarely gives a human model name on the free tier,
            # only ICAO/IATA aircraft type codes — surface what's available.
            "model": aircraft.get("icao") or aircraft.get("iata"),
            "reg": aircraft.get("registration"),
        },
        "departure": {
            "iata": dep.get("iata"),
            "icao": dep.get("icao"),
            "name": dep.get("airport"),
            "city": None,
            "country_code": None,
            "lat": None,
            "lon": None,
            "timezone": dep.get("timezone"),
            "scheduled_utc": dep.get("scheduled"),
            "actual_utc": dep.get("actual") or dep.get("actual_runway"),
            "estimated_utc": dep.get("estimated") or dep.get("estimated_runway"),
            "terminal": dep.get("terminal"),
            "gate": dep.get("gate"),
        },
        "arrival": {
            "iata": arr.get("iata"),
            "icao": arr.get("icao"),
            "name": arr.get("airport"),
            "city": None,
            "country_code": None,
            "lat": None,
            "lon": None,
            "timezone": arr.get("timezone"),
            "scheduled_utc": arr.get("scheduled"),
            "actual_utc": arr.get("actual") or arr.get("actual_runway"),
            "estimated_utc": arr.get("estimated") or arr.get("estimated_runway"),
            "terminal": arr.get("terminal"),
            "gate": arr.get("gate"),
            "baggage_belt": arr.get("baggage"),
        },
        "movement": movement,
    }
