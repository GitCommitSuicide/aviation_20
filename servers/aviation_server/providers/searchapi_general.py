"""
servers/aviation_server/providers/searchapi_general.py
======================================================
General SearchApi.io wrapper for Google Maps, Google Hotels, and Google Search.
"""

import requests
from servers.aviation_server.config import SEARCH_API_KEY, HAS_SEARCHAPI, REQUEST_TIMEOUT_SECONDS, get_logger

logger = get_logger(__name__)


def google_search(
    query: str,
    engine: str = "google",
    location: str | None = None,
    check_in: str | None = None,
    check_out: str | None = None,
) -> tuple[bool, object]:
    if not HAS_SEARCHAPI:
        return False, "NO_KEY"

    params = {
        "engine": engine,
        "q": query,
        "api_key": SEARCH_API_KEY,
    }

    if location and engine != "google_maps":
        params["location"] = location

    if engine == "google_maps":
        # Google Maps engine might use 'q' or 'll', but 'q' usually works for search.
        # If we have location, append it to query to ensure accuracy.
        if location:
            params["q"] = f"{query} near {location}"
    
    if engine == "google_hotels":
        if check_in:
            params["check_in"] = check_in
        if check_out:
            params["check_out"] = check_out

    try:
        resp = requests.get("https://www.searchapi.io/api/v1/search", params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        logger.info("GET searchapi.io engine=%s q=%s -> %s", engine, params["q"], resp.status_code)
        resp.raise_for_status()
        return True, resp.json()
    except requests.exceptions.HTTPError as e:
        return False, f"HTTP_ERROR:{e}"
    except requests.exceptions.Timeout:
        return False, "TIMEOUT"
    except Exception as e:
        return False, f"ERROR:{e}"
