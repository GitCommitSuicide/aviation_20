"""
servers/database_server/server.py
====================================
MCP server exposing DATABASE (PostgreSQL cache) read tools ONLY. This
server never calls an external aviation API — it is purely a fast cache
front-end that the chat agent should always query first.

Run standalone (stdio transport):
    python -m servers.database_server.server

Run over HTTP:
    python -m servers.database_server.server --http
"""

import sys

from mcp.server.fastmcp import FastMCP

from servers.database_server.tools.search import search_database
from servers.database_server.tools.airports import get_airport_info
from servers.database_server.tools.airlines import get_airline_info
from servers.database_server.tools.flights import get_flight_status_cached, get_route_cached

mcp = FastMCP("database-server")

for fn in (
    search_database,
    get_airport_info,
    get_airline_info,
    get_flight_status_cached,
    get_route_cached,
):
    mcp.tool()(fn)


if __name__ == "__main__":
    transport = "streamable-http" if "--http" in sys.argv else "stdio"
    mcp.run(transport=transport)
