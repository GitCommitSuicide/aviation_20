"""
servers/aviation_server/providers/searchapi_flights.py
========================================================
Wrapper around SearchApi.io's Google Flights engine — used for route/price
search (as opposed to AeroDataBox/Aviationstack, which handle single-flight
status lookups).
"""

import requests

from servers.aviation_server.config import SEARCH_API_KEY, HAS_SEARCHAPI, REQUEST_TIMEOUT_SECONDS, get_logger

logger = get_logger(__name__)


def search_flights(
    dep_iata: str, 
    arr_iata: str, 
    date: str, 
    currency: str = "INR",
    seat_class: str = "economy",
    flight_type: str = "one_way",
    return_date: str = None
) -> tuple[bool, object]:
    if not HAS_SEARCHAPI:
        return False, "NO_KEY"

    # Map seat class to Google Flights travel_class parameter
    # 1=Economy, 2=Premium Economy, 3=Business, 4=First
    class_map = {
        "economy": "1",
        "premium_economy": "2",
        "business": "3",
        "first": "4"
    }
    travel_class = class_map.get(seat_class.lower(), "1")

    # Map flight type to Google Flights type parameter
    # 1=Round trip, 2=One way
    is_return = flight_type.lower() in ["return", "round_trip", "roundtrip"]
    api_type = "1" if is_return else "2"

    params = {
        "engine": "google_flights",
        "departure_id": dep_iata,
        "arrival_id": arr_iata,
        "outbound_date": date,
        "type": api_type,
        "travel_class": travel_class,
        "currency": currency,
        "api_key": SEARCH_API_KEY,
    }
    
    # Include return_date if it's a round trip
    if is_return and return_date:
        params["return_date"] = return_date

    try:
        resp = requests.get("https://www.searchapi.io/api/v1/search", params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        logger.info(
            "GET searchapi.io departure_id=%s arrival_id=%s outbound_date=%s type=%s travel_class=%s -> %s", 
            dep_iata, arr_iata, date, api_type, travel_class, resp.status_code
        )
        resp.raise_for_status()
        return True, resp.json()
    except requests.exceptions.HTTPError as e:
        return False, f"HTTP_ERROR:{e}"
    except requests.exceptions.Timeout:
        return False, "TIMEOUT"
    except Exception as e:
        return False, f"ERROR:{e}"
