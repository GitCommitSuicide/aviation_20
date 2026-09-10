"""
servers/aviation_server/tools/route_search.py
================================================
get_flights_by_route — search flights between two places on a date, with
real prices, via SearchApi.io's Google Flights engine.
"""

import datetime

from shared.airport_data import resolve_iata
from shared.time_utils import get_airport_tz, fmt_duration_mins
from servers.aviation_server.config import get_logger
from servers.aviation_server.providers.searchapi_flights import search_flights
from servers.aviation_server.persistence import save_itineraries

logger = get_logger(__name__)


def get_flights_by_route(
    origin: str, 
    destination: str, 
    date: str | None = None,
    seat_class: str = "economy",
    flight_type: str = "one_way",
    return_date: str | None = None
) -> str:
    """
    Use this when the user describes a ROUTE (two city names or airport
    codes) and wants to search flights between them on a specific date (or
    today/tomorrow), e.g. "flights from Mumbai to Pune". Queries Google
    Flights via SearchApi.io with real prices.

    Args:
        origin: Departure city name (e.g. "Mumbai") or IATA code (e.g. "BOM").
        destination: Arrival city name (e.g. "Pune") or IATA code (e.g. "PNQ").
        date: Optional YYYY-MM-DD. Default is today.
        seat_class: Optional seat class. Can be "economy", "premium_economy", "business", or "first". Default is "economy".
        flight_type: Optional flight type. Can be "one_way" or "return". Default is "one_way".
        return_date: Optional return date (YYYY-MM-DD), required if flight_type is "return".
    """
    logger.info("get_flights_by_route origin=%r destination=%r date=%r seat_class=%r flight_type=%r", origin, destination, date, seat_class, flight_type)

    if not date:
        date = datetime.datetime.now().strftime("%Y-%m-%d")

    dep_iata = resolve_iata(origin)
    arr_iata = resolve_iata(destination)
    if not dep_iata:
        return f"I don't know the airport code for '{origin}'. Please provide its 3-letter IATA code."
    if not arr_iata:
        return f"I don't know the airport code for '{destination}'. Please provide its 3-letter IATA code."

    ok, data = search_flights(
        dep_iata, 
        arr_iata, 
        date, 
        currency="INR", 
        seat_class=seat_class, 
        flight_type=flight_type, 
        return_date=return_date
    )
    if not ok:
        if data == "NO_KEY":
            return "Route search is unavailable (missing SEARCH_API key)."
        return f"Error querying flight search: {data}"

    best_flights = data.get("best_flights", [])
    other_flights = data.get("other_flights", [])
    all_itineraries = best_flights[:5]
    if len(all_itineraries) < 5:
        all_itineraries.extend(other_flights[:(5 - len(all_itineraries))])

    if not all_itineraries:
        return f"No flights found from {origin} ({dep_iata}) to {destination} ({arr_iata}) on {date}."

    results = []
    for i, it in enumerate(all_itineraries, 1):
        price = it.get("price")
        price_str = f"{price} INR" if price else "Price not available"
        segments = it.get("flights", [])
        seg_lines = []

        for j, seg in enumerate(segments):
            dep_ap = seg.get("departure_airport", {})
            arr_ap = seg.get("arrival_airport", {})
            seg_dep_iata = dep_ap.get("id", "?")
            seg_arr_iata = arr_ap.get("id", "?")
            dep_tz = get_airport_tz(seg_dep_iata)
            arr_tz = get_airport_tz(seg_arr_iata)

            dep_local_str = f"{dep_ap.get('date', '?')} {dep_ap.get('time', '?')}"
            arr_local_str = f"{arr_ap.get('date', '?')} {arr_ap.get('time', '?')}"

            try:
                dep_display = datetime.datetime.strptime(dep_local_str, "%Y-%m-%d %H:%M").strftime("%Y-%m-%d %I:%M %p")
            except Exception:
                dep_display = dep_local_str
            try:
                arr_display = datetime.datetime.strptime(arr_local_str, "%Y-%m-%d %H:%M").strftime("%Y-%m-%d %I:%M %p")
            except Exception:
                arr_display = arr_local_str

            dur_str = fmt_duration_mins(seg.get("duration", 0))

            seg_lines.append(
                f"  - Leg {j + 1}: {seg_dep_iata} -> {seg_arr_iata}"
                f" ({seg.get('airline', 'Unknown')} {seg.get('flight_number', 'N/A')})\n"
                f"    Departure: {dep_display} ({dep_tz or 'Local Time'})\n"
                f"    Arrival:   {arr_display} ({arr_tz or 'Local Time'})\n"
                f"    Duration:  {dur_str}\n"
                f"    Aircraft:  {seg.get('airplane', 'Unknown')}"
            )

        major_airline = segments[0].get("airline", "Unknown") if segments else "Unknown"
        results.append(f"**Option {i} — {major_airline}**\nPrice: {price_str}\nRoute Details:\n" + "\n".join(seg_lines))

    save_itineraries(dep_iata, arr_iata, date, "INR", all_itineraries)

    return (
        f"Flights from {origin} ({dep_iata}) to {destination} ({arr_iata}) on {date}:\n\n"
        + "\n\n---\n\n".join(results)
    )
