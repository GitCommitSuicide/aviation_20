"""
servers/aviation_server/tools/trip_planner.py
================================================
plan_trip_itinerary — web-search-based trip/itinerary suggestions via Tavily.
"""

from tavily import TavilyClient

from servers.aviation_server.config import TAVILY_API_KEY, HAS_TAVILY, get_logger

logger = get_logger(__name__)

_client = TavilyClient(api_key=TAVILY_API_KEY) if HAS_TAVILY else None


def plan_trip_itinerary(destination: str, days: int, preferences: str = "") -> str:
    """
    Use this when a user asks for a trip itinerary or connection planning to
    a destination. Searches the web for top spots, activities, and required
    time for each, based on the user's preferences.

    Args:
        destination: The destination city/place.
        days: Number of days for the trip.
        preferences: Optional free-text preferences, e.g. "food, history".
    """
    logger.info("plan_trip_itinerary destination=%r days=%s preferences=%r", destination, days, preferences)

    if not _client:
        return "Tavily API key is missing. Please add TAVILY_API_KEY to enable trip planning search."

    query = f"Top tourist spots and a {days}-day itinerary in {destination}"
    if preferences:
        query += f" focusing on {preferences}"

    try:
        response = _client.search(query=query, search_depth="advanced", max_results=2, include_answer=True)
        answer = response.get("answer", "")
        results = response.get("results", [])

        output = f"### Trip Plan for {destination} ({days} days)\n"
        if answer:
            output += f"{answer}\n\n"
        if results:
            output += "**Top Recommendations:**\n"
            for res in results[:3]:
                output += f"- [{res.get('title', 'Link')}]({res.get('url', '#')}): {res.get('content', '')[:150]}...\n"
        output += "\n*Ask the user if they want to adjust this plan or if they would like you to look up flights for these destinations!*"
        return output
    except Exception as e:
        logger.error("Tavily search failed: %s", e)
        return f"Sorry, I couldn't generate a trip plan for {destination} right now due to a search error: {e}"
