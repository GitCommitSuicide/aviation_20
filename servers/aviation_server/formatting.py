"""
servers/aviation_server/formatting.py
=======================================
Turns one or more normalized flight records (see providers/normalize.py)
into the human-readable text blocks the chat agent shows to the user.
Kept separate from the tools so both flight_status.py and
flight_tracking.py can reuse the same rendering logic.
"""

from shared.time_utils import parse_utc, get_airport_tz, fmt_local, calc_delay, calc_duration


def _infer_status(raw_status: str, dep_actual, arr_actual) -> str:
    status = raw_status or "Unknown"
    if status.lower() not in ("arrived", "canceled", "cancelled", "diverted", "landed"):
        if arr_actual:
            return "Arrived"
        elif dep_actual:
            return "In Flight"
        elif status.lower() not in ("canceled", "cancelled"):
            return "Scheduled / Not Departed"
    return status


def format_flight_record(record: dict, route_label: str = "") -> str:
    """Render one normalized flight record as a text block."""
    dep = record.get("departure", {})
    arr = record.get("arrival", {})

    dep_tz = get_airport_tz(dep.get("iata"), dep.get("timezone"))
    arr_tz = get_airport_tz(arr.get("iata"), arr.get("timezone"))

    dep_sched = parse_utc(dep.get("scheduled_utc"))
    dep_actual = parse_utc(dep.get("actual_utc"))
    dep_est = parse_utc(dep.get("estimated_utc"))
    arr_sched = parse_utc(arr.get("scheduled_utc"))
    arr_actual = parse_utc(arr.get("actual_utc"))
    arr_est = parse_utc(arr.get("estimated_utc"))

    dep_delay = calc_delay(dep_sched, dep_actual or dep_est)
    arr_delay = calc_delay(arr_sched, arr_actual or arr_est)
    duration = calc_duration(dep_sched, arr_sched)

    status = _infer_status(record.get("status"), dep_actual, arr_actual)
    airline = record.get("airline", {}).get("name") or "Unknown"
    aircraft = record.get("aircraft", {}).get("model") or "Unknown"
    aircraft_reg = record.get("aircraft", {}).get("reg") or "Unknown"

    header = f"--- {route_label} ---\n" if route_label else ""
    source_note = f" (source: {record.get('source', 'unknown')})" if record.get("source") else ""

    body = (
        f"{header}"
        f"Flight: {record.get('flight_number')}{source_note}\n"
        f"Airline: {airline}\n"
        f"Status: {status}\n"
        f"Aircraft: {aircraft} ({aircraft_reg})\n"
        f"Duration: {duration}\n"
        f"Departure: {dep.get('name', 'Unknown')} ({dep.get('iata', '?')})\n"
        f"  - Scheduled: {fmt_local(dep_sched, dep_tz)}\n"
        f"  - Predicted: {fmt_local(dep_est, dep_tz) if dep_est else 'N/A'}\n"
        f"  - Actual:    {fmt_local(dep_actual, dep_tz) if dep_actual else 'N/A'}\n"
        f"  - Delay:     {dep_delay}\n"
        f"  - Terminal: {dep.get('terminal', 'N/A')} | Gate: {dep.get('gate', 'N/A')}\n"
        f"Arrival: {arr.get('name', 'Unknown')} ({arr.get('iata', '?')})\n"
        f"  - Scheduled: {fmt_local(arr_sched, arr_tz)}\n"
        f"  - Predicted: {fmt_local(arr_est, arr_tz) if arr_est else 'N/A'}\n"
        f"  - Actual:    {fmt_local(arr_actual, arr_tz) if arr_actual else 'N/A'}\n"
        f"  - Delay:     {arr_delay}\n"
        f"  - Terminal: {arr.get('terminal', 'N/A')} | Gate: {arr.get('gate', 'N/A')} | Baggage Belt: {arr.get('baggage_belt', 'N/A')}"
    )

    movement = record.get("movement")
    if movement:
        lat, lon = movement.get("lat"), movement.get("lon")
        alt_ft = round((movement.get("altitude_m") or 0) * 3.28084)
        speed = round(movement.get("speed_kmh") or 0)
        heading = round(movement.get("heading") or 0)
        body += (
            f"\n--- LIVE POSITION ---\n"
            f"Latitude:  {lat}\n"
            f"Longitude: {lon}\n"
            f"Altitude:  {alt_ft} ft\n"
            f"Speed:     {speed} km/h\n"
            f"Heading:   {heading}°\n"
        )

    return body


def format_flight_records(records: list[dict], flight_number: str, date: str | None = None) -> str:
    if len(records) == 1:
        return format_flight_record(records[0])

    parts = []
    for i, record in enumerate(records, 1):
        dep_iata = record.get("departure", {}).get("iata", "???")
        arr_iata = record.get("arrival", {}).get("iata", "???")
        parts.append(format_flight_record(record, route_label=f"Route {i}: {dep_iata} -> {arr_iata}"))

    suffix = f" on {date}" if date else ""
    return (
        f"Flight {flight_number} operates on {len(records)} routes{suffix}.\n\n"
        + "\n\n".join(parts)
    )
