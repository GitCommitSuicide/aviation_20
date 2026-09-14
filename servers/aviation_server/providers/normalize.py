"""
servers/aviation_server/providers/normalize.py
================================================
AeroDataBox and Aviationstack return very different JSON shapes. Rather than
have every tool branch on "which provider gave me this", both providers are
normalized here into ONE common flight-record dict. Tools, formatters, and
the DB-persistence layer only ever deal with this common shape.

After normalization, call validate_flight_record() to detect data
inconsistencies (e.g., arrival actual without departure actual, impossible
timelines). Warnings are attached to the record for display to the user.

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
        "scheduled_utc": str|None,   # ISO-ish UTC string
        "actual_utc": str|None,
        "estimated_utc": str|None,
        "scheduled_local": str|None, # ISO-ish local string from API
        "actual_local": str|None,
        "estimated_local": str|None,
        "terminal": str|None, "gate": str|None,
    },
    "arrival": {  # same keys as departure, plus:
        ..., "baggage_belt": str|None,
    },
    "movement": {"lat":.,"lon":.,"altitude_m":.,"speed_kmh":.,"heading":..} | None,
    "warnings": list[str],  # data integrity warnings (may be empty)
}
"""

from shared.time_utils import parse_utc


def validate_flight_record(record: dict) -> dict:
    """
    Run data integrity checks on a normalized flight record and attach
    a 'warnings' list. This should be called AFTER normalization, BEFORE
    formatting or persistence.

    Checks:
        1. Arrival actual exists but departure actual is missing
        2. Actual arrival time is before scheduled departure (impossible)
        3. Actual departure is after actual arrival (impossible)
        4. Scheduled arrival is before scheduled departure (impossible)
    """
    warnings = []
    dep = record.get("departure", {})
    arr = record.get("arrival", {})

    dep_sched = parse_utc(dep.get("scheduled_utc"))
    dep_actual = parse_utc(dep.get("actual_utc"))
    arr_sched = parse_utc(arr.get("scheduled_utc"))
    arr_actual = parse_utc(arr.get("actual_utc"))

    # 1. Arrival actual without departure actual
    if arr_actual and not dep_actual:
        warnings.append(
            "DATA INTEGRITY: Arrival actual time reported but departure actual is missing. "
            "The provider may not have received all operational events."
        )

    # 2. Actual arrival before scheduled departure (impossible flight)
    if dep_sched and arr_actual and arr_actual < dep_sched:
        warnings.append(
            "DATA INTEGRITY: Actual arrival time is BEFORE scheduled departure. "
            "This is physically impossible — the data may be from a different flight instance."
        )

    # 3. Departure actual after arrival actual (impossible)
    if dep_actual and arr_actual and dep_actual > arr_actual:
        warnings.append(
            "DATA INTEGRITY: Actual departure is AFTER actual arrival. "
            "This is physically impossible — data may be corrupted or mismatched."
        )

    # 4. Scheduled arrival before scheduled departure (likely cross-date but check)
    if dep_sched and arr_sched and arr_sched < dep_sched:
        warnings.append(
            "DATA INTEGRITY: Scheduled arrival is before scheduled departure. "
            "Possible timezone or date error in the source data."
        )

    record["warnings"] = warnings
    return record




def normalize_aerodatabox_flight(raw: dict, flight_number: str) -> dict:
    dep = raw.get("departure", {}) or {}
    arr = raw.get("arrival", {}) or {}
    dep_ap = dep.get("airport", {}) or {}
    arr_ap = arr.get("airport", {}) or {}
    airline = raw.get("airline", {}) or {}
    aircraft = raw.get("aircraft", {}) or {}

    def pick(section: dict, *keys, prefer: str = "utc") -> str | None:
        """Extract a time value from AeroDataBox nested time objects.
        
        AeroDataBox returns times as: {"scheduledTime": {"utc": "...", "local": "..."}}
        `prefer` controls which sub-key to grab: "utc" or "local".
        Also handles flat string values for backward compatibility.
        """
        for key in keys:
            val = section.get(key)
            if isinstance(val, dict):
                raw_val = val.get(prefer)
                if raw_val:
                    return raw_val
            elif val:
                # Flat string value (legacy or non-nested fields)
                return val
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
            # UTC times (for storage, delay calc, duration)
            "scheduled_utc": pick(dep, "scheduledTime", prefer="utc"),
            "actual_utc": pick(dep, "actualTime", "runwayTime", prefer="utc"),
            "estimated_utc": pick(dep, "predictedTime", "revisedTime", prefer="utc"),
            # Local times (for display — straight from the API)
            "scheduled_local": pick(dep, "scheduledTime", prefer="local"),
            "actual_local": pick(dep, "actualTime", "runwayTime", prefer="local"),
            "estimated_local": pick(dep, "predictedTime", "revisedTime", prefer="local"),
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
            # UTC times
            "scheduled_utc": pick(arr, "scheduledTime", prefer="utc"),
            "actual_utc": pick(arr, "actualTime", "runwayTime", prefer="utc"),
            "estimated_utc": pick(arr, "predictedTime", "revisedTime", prefer="utc"),
            # Local times
            "scheduled_local": pick(arr, "scheduledTime", prefer="local"),
            "actual_local": pick(arr, "actualTime", "runwayTime", prefer="local"),
            "estimated_local": pick(arr, "predictedTime", "revisedTime", prefer="local"),
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

    # Aviationstack gives ISO strings with offsets — these serve as both
    # the UTC value (after parsing) and the local value (the raw string
    # already contains the offset, so it IS the local representation).
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
            # Aviationstack returns offset-aware ISO strings — use them as local too
            "scheduled_local": dep.get("scheduled"),
            "actual_local": dep.get("actual") or dep.get("actual_runway"),
            "estimated_local": dep.get("estimated") or dep.get("estimated_runway"),
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
            # Aviationstack returns offset-aware ISO strings — use them as local too
            "scheduled_local": arr.get("scheduled"),
            "actual_local": arr.get("actual") or arr.get("actual_runway"),
            "estimated_local": arr.get("estimated") or arr.get("estimated_runway"),
            "terminal": arr.get("terminal"),
            "gate": arr.get("gate"),
            "baggage_belt": arr.get("baggage"),
        },
        "movement": movement,
    }
