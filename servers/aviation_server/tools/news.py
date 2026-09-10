"""
servers/aviation_server/tools/news.py
=======================================
search_aviation_news — web search for real-world aviation events via Tavily.
"""

import requests

from servers.aviation_server.config import TAVILY_API_KEY, HAS_TAVILY, REQUEST_TIMEOUT_SECONDS, get_logger

logger = get_logger(__name__)


def search_aviation_news(query: str) -> str:
    """
    Search the web for the LATEST aviation news, incidents, accidents,
    delays, airspace closures, or any real-world events related to a
    flight, aircraft, airline, or airport.

    Args:
        query: A specific, focused search query, e.g.
               "Air India flight AI101 accident news 2024" or
               "IndiGo 6E214 incident today"
    """
    logger.info("search_aviation_news query=%r", query)
    if not HAS_TAVILY:
        return "News search unavailable: TAVILY_API_KEY is not set."

    payload = {
        "api_key": TAVILY_API_KEY,
        "query": query,
        "search_depth": "basic",
        "include_answer": True,
        "max_results": 3,
        "include_domains": [],
        "exclude_domains": [],
    }

    try:
        resp = requests.post("https://api.tavily.com/search", json=payload, timeout=REQUEST_TIMEOUT_SECONDS)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.Timeout:
        return "News search timed out. Please try again shortly."
    except requests.exceptions.HTTPError as e:
        return f"News search API error {e.response.status_code if e.response else ''}: {str(e)}"
    except Exception as e:
        return f"News search failed: {str(e)}"

    parts: list[str] = []
    answer = data.get("answer")
    if answer:
        parts.append(f"Summary: {answer}")

    results = data.get("results", [])
    if not results:
        return parts[0] if parts else "No news results found for that query."

    parts.append(f"Found {len(results)} result(s) for: '{query}'")
    for i, r in enumerate(results, 1):
        snippet = r.get("content", "").strip()
        if len(snippet) > 300:
            snippet = snippet[:297] + "..."
        parts.append(f"\n[{i}] {r.get('title', 'No title')}\n    URL: {r.get('url', '')}\n    {snippet}")

    return "\n".join(parts)
