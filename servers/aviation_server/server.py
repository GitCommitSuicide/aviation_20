"""
servers/aviation_server/server.py
===================================
MCP server exposing AVIATION tools — everything that talks to an external
API (AeroDataBox, AirLabs, Aviationstack, SearchApi, Open-Meteo, Tavily).
This server has NO direct read access for the chat agent into the local
cache; it only writes to it (see persistence.py) as a caching side-effect
after a live fetch. Cache *reads* live entirely on the database MCP server.

Run standalone (stdio transport, for use with Claude Desktop / any MCP
client config):
    python -m servers.aviation_server.server

Run over HTTP (useful for local dev / debugging with the MCP inspector):
    python -m servers.aviation_server.server --http
"""

import sys

from mcp.server.fastmcp import FastMCP

from servers.aviation_server.tools.flight_status import get_flight_details
from servers.aviation_server.tools.flight_tracking import track_flight_live
from servers.aviation_server.tools.route_search import get_flights_by_route
from servers.aviation_server.tools.weather import get_airport_weather
from servers.aviation_server.tools.news import search_aviation_news
from servers.aviation_server.tools.reliability import get_flight_reliability, get_flight_route_info
from servers.aviation_server.tools.trip_planner import plan_trip_itinerary
from servers.aviation_server.tools.airport_schedules import get_airport_schedules
from servers.aviation_server.tools.airport_info import get_airport_info, find_nearby_airports
from servers.aviation_server.tools.airline_info import get_airline_info, suggest_flight_search

from servers.aviation_server.tools.search_travel import google_search_travel

mcp = FastMCP("aviation-server")

for fn in (
    get_flight_details,
    track_flight_live,
    get_flights_by_route,
    get_airport_weather,
    search_aviation_news,
    get_flight_reliability,
    get_flight_route_info,
    plan_trip_itinerary,
    # ── AirLabs-powered tools ──────────────────────────
    get_airport_schedules,
    get_airport_info,
    find_nearby_airports,
    get_airline_info,
    suggest_flight_search,
    # ── SearchApi tools ──────────────────────────
    google_search_travel,
):
    mcp.tool()(fn)


if __name__ == "__main__":
    transport = "streamable-http" if "--http" in sys.argv else "stdio"
    mcp.run(transport=transport)
