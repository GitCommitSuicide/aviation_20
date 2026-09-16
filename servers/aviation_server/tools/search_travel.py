"""
servers/aviation_server/tools/search_travel.py
==============================================
google_search_travel - Tool for airport navigation, hotels, and general travel queries.
"""

import json
from servers.aviation_server.config import get_logger
from servers.aviation_server.providers import searchapi_general

logger = get_logger(__name__)

def google_search_travel(
    query: str,
    engine: str,
    location: str,
    check_in: str | None = None,
    check_out: str | None = None,
) -> str:
    """
    Use this tool for airport navigation and travel queries.
    
    Engine selection rules:
    - Use engine="maps" when the user asks for directions, distance, walking time, or how to get from one gate/terminal/location to another (e.g. "gate 1 to gate 2", "how do I get to baggage claim", "shortest way to terminal 3").
    - Use engine="hotels" when the user asks about hotels, places to stay, or accommodation near the airport.
    - Use engine="search" for anything else travel-related that isn't a direction or hotel query (restaurants, lounges, parking, shops).
    
    Rules:
    1. Always extract the airport code or terminal/gate info into the "location" field if mentioned or inferable from context.
    2. Call the tool immediately once engine type is clear — do not ask the user to confirm which engine to use.
    3. If the query is ambiguous between maps and search (e.g. "where can I eat near gate 5"), prefer engine="search" with location set to the gate.
    4. Only ask a clarifying question if the location/airport is completely missing and cannot be inferred from prior conversation.
    5. Do not show reasoning or explain your tool choice — just call the tool.
    6. After getting results, answer in 2-4 sentences maximum — give the direct answer (route, hotel names/prices, or place names), not a full dump of raw results.
    """
    logger.info("google_search_travel engine=%r query=%r location=%r", engine, query, location)

    engine_map = {
        "maps": "google_maps",
        "hotels": "google_hotels",
        "search": "google"
    }
    
    api_engine = engine_map.get(engine.lower(), "google")

    ok, payload = searchapi_general.google_search(
        query=query,
        engine=api_engine,
        location=location,
        check_in=check_in,
        check_out=check_out
    )

    if not ok:
        if payload == "NO_KEY":
            return "Search is unavailable (missing SEARCH_API_KEY)."
        return f"Could not perform search: {payload}"

    # Extract relevant fields to save token space
    result_summary = {}
    
    if isinstance(payload, dict):
        if api_engine == "google_maps":
            directions = payload.get("directions", [])
            places = payload.get("places", [])
            local_results = payload.get("local_results", [])
            if directions:
                result_summary["directions"] = directions
            if places:
                result_summary["places"] = places[:3]
            if local_results:
                result_summary["local_results"] = local_results[:3]
                
        elif api_engine == "google_hotels":
            hotels = payload.get("properties", [])
            if hotels:
                # Keep only top 4 hotels with names, prices, and ratings to save tokens
                condensed = []
                for h in hotels[:4]:
                    condensed.append({
                        "name": h.get("name"),
                        "price": h.get("rate_per_night", {}).get("lowest"),
                        "rating": h.get("overall_rating"),
                        "amenities": h.get("amenities", [])[:3]
                    })
                result_summary["hotels"] = condensed
        else:
            # General google search
            organic = payload.get("organic_results", [])
            local_results = payload.get("local_results", [])
            knowledge_graph = payload.get("knowledge_graph", {})
            
            if local_results:
                condensed = []
                for l in local_results[:3]:
                    condensed.append({
                        "title": l.get("title"),
                        "address": l.get("address"),
                        "rating": l.get("rating")
                    })
                result_summary["local_results"] = condensed
                
            if knowledge_graph:
                result_summary["knowledge_graph"] = {
                    "title": knowledge_graph.get("title"),
                    "description": knowledge_graph.get("description")
                }
                
            if organic:
                condensed = []
                for o in organic[:3]:
                    condensed.append({
                        "title": o.get("title"),
                        "snippet": o.get("snippet")
                    })
                result_summary["web_results"] = condensed

    return "Search Results:\n```json\n" + json.dumps(result_summary, indent=2) + "\n```"
