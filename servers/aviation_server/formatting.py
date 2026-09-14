"""
servers/aviation_server/formatting.py
=======================================
Turns one or more normalized flight records (see providers/normalize.py)
into the human-readable text blocks the chat agent shows to the user.
Kept separate from the tools so both flight_status.py and
flight_tracking.py can reuse the same rendering logic.

Time display strategy:
  - Uses the API's own LOCAL times for display (via parse_local + fmt_local_time)
  - Falls back to UTC -> local conversion when API local times aren't available
  - Calculates delays using UTC times only (via calc_delay_safe)
  - Pre-departure flights never show misleading "early" predictions

Data provenance:
  - Every formatted output includes a provenance footer showing the data source,
    query date, and fetch timestamp so the user knows where the data came from.
  - Validation warnings (from normalize.validate_flight_record) are displayed
    to flag data inconsistencies.
"""

import datetime

from shared.time_utils import (
    parse_utc,
    parse_local,
    get_airport_tz,
    fmt_local_time,
    calc_delay_safe,
    calc_duration,
)


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


def format_flight_record(record: dict, route_label: str = "", query_date: str = "") -> str:
    """Render one normalized flight record as a text block with provenance."""
    dep = record.get("departure", {})
    arr = record.get("arrival", {})

    dep_tz = get_airport_tz(dep.get("iata"), dep.get("timezone"))
    arr_tz = get_airport_tz(arr.get("iata"), arr.get("timezone"))

    # -- Parse UTC times (for delay calc and duration) ---------------------
    dep_sched_utc = parse_utc(dep.get("scheduled_utc"))
    dep_actual_utc = parse_utc(dep.get("actual_utc"))
    dep_est_utc = parse_utc(dep.get("estimated_utc"))
    arr_sched_utc = parse_utc(arr.get("scheduled_utc"))
    arr_actual_utc = parse_utc(arr.get("actual_utc"))
    arr_est_utc = parse_utc(arr.get("estimated_utc"))

    # -- Parse LOCAL times (for display -- straight from API) --------------
    dep_sched_local = parse_local(dep.get("scheduled_local"))
    dep_actual_local = parse_local(dep.get("actual_local"))
    dep_est_local = parse_local(dep.get("estimated_local"))
    arr_sched_local = parse_local(arr.get("scheduled_local"))
    arr_actual_local = parse_local(arr.get("actual_local"))
    arr_est_local = parse_local(arr.get("estimated_local"))

    # -- Determine flight status -------------------------------------------
    status = _infer_status(record.get("status"), dep_actual_utc, arr_actual_utc)
    has_departed = dep_actual_utc is not None

    # -- Delay calculations (always in UTC, with sanity checks) ------------
    dep_delay = calc_delay_safe(
        dep_sched_utc,
        dep_actual_utc or dep_est_utc,
        has_departed=has_departed,
        is_arrival=False,
    )
    arr_delay = calc_delay_safe(
        arr_sched_utc,
        arr_actual_utc or arr_est_utc,
        has_departed=has_departed,
        is_arrival=True,
    )

    # -- Duration (always from UTC scheduled times) ------------------------
    duration = calc_duration(dep_sched_utc, arr_sched_utc)

    # -- Display formatting (prefer API local times) -----------------------
    airline = record.get("airline", {}).get("name") or "Unknown"
    aircraft = record.get("aircraft", {}).get("model") or "Unknown"
    aircraft_reg = record.get("aircraft", {}).get("reg") or "Unknown"

    header = f"--- {route_label} ---\n" if route_label else ""

    body = (
        f"{header}"
        f"Flight: {record.get('flight_number')}\n"
        f"Airline: {airline}\n"
        f"Status: {status}\n"
        f"Aircraft: {aircraft} ({aircraft_reg})\n"
        f"Duration: {duration}\n"
        f"Departure: {dep.get('name', 'Unknown')} ({dep.get('iata', '?')})\n"
        f"  - Scheduled: {fmt_local_time(dep_sched_local, dep_sched_utc, dep_tz)}\n"
        f"  - Predicted: {fmt_local_time(dep_est_local, dep_est_utc, dep_tz) if (dep_est_local or dep_est_utc) else 'N/A'}\n"
        f"  - Actual:    {fmt_local_time(dep_actual_local, dep_actual_utc, dep_tz) if (dep_actual_local or dep_actual_utc) else 'N/A'}\n"
        f"  - Delay:     {dep_delay}\n"
        f"  - Terminal: {dep.get('terminal', 'N/A')} | Gate: {dep.get('gate', 'N/A')}\n"
        f"Arrival: {arr.get('name', 'Unknown')} ({arr.get('iata', '?')})\n"
        f"  - Scheduled: {fmt_local_time(arr_sched_local, arr_sched_utc, arr_tz)}\n"
        f"  - Predicted: {fmt_local_time(arr_est_local, arr_est_utc, arr_tz) if (arr_est_local or arr_est_utc) else 'N/A'}\n"
        f"  - Actual:    {fmt_local_time(arr_actual_local, arr_actual_utc, arr_tz) if (arr_actual_local or arr_actual_utc) else 'N/A'}\n"
        f"  - Delay:     {arr_delay}\n"
        f"  - Terminal: {arr.get('terminal', 'N/A')} | Gate: {arr.get('gate', 'N/A')} | Baggage Belt: {arr.get('baggage_belt', 'N/A')}"
    )

    # -- Live position block -----------------------------------------------
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
            f"Heading:   {heading} deg\n"
        )

    # -- Data provenance footer --------------------------------------------
    source = record.get("source", "unknown")
    now_str = datetime.datetime.now(tz=datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    provenance_parts = [
        f"\n--- DATA PROVENANCE ---",
        f"Source: {source} (live lookup)",
        f"Data retrieved: {now_str}",
    ]
    if query_date:
        provenance_parts.insert(2, f"Query date: {query_date}")
    body += "\n".join(provenance_parts)

    # -- Data integrity warnings -------------------------------------------
    warnings = record.get("warnings", [])
    if warnings:
        body += "\n--- DATA WARNINGS ---"
        for w in warnings:
            body += f"\n>> {w}"

    return body


def format_flight_records(records: list[dict], flight_number: str, date: str | None = None) -> str:
    if len(records) == 1:
        return format_flight_record(records[0], query_date=date or "")

    parts = []
    for i, record in enumerate(records, 1):
        dep_iata = record.get("departure", {}).get("iata", "???")
        arr_iata = record.get("arrival", {}).get("iata", "???")
        parts.append(format_flight_record(
            record,
            route_label=f"Route {i}: {dep_iata} -> {arr_iata}",
            query_date=date or "",
        ))

    suffix = f" on {date}" if date else ""
    return (
        f"Flight {flight_number} operates on {len(records)} routes{suffix}.\n\n"
        + "\n\n".join(parts)
    )
