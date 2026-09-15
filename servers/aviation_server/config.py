"""
servers/aviation_server/config.py
==================================
Centralised environment/config loading for the aviation MCP server.
"""

import os
import logging

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s]: %(message)s")


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


# ── External API keys ────────────────────────────────────────────────────────
RAPID_API_KEY         = os.getenv("RAPID_API_KEY")          # AeroDataBox (via RapidAPI) — primary
AVIATIONSTACK_API_KEY = os.getenv("AVIATIONSTACK_API_KEY")  # Aviationstack — fallback for flight status
SEARCH_API_KEY        = os.getenv("SEARCH_API")             # SearchApi.io (Google Flights) — route/price search
TAVILY_API_KEY        = os.getenv("TAVILY_API_KEY")         # Tavily — news + trip planning search
AIRLABS_API_KEY       = os.getenv("AIRLABS_API")            # AirLabs — live radar, schedules, airport/airline DB

# Feature flags derived from key presence — tools use these to decide whether
# to attempt a provider at all, rather than failing on every call.
HAS_AERODATABOX   = bool(RAPID_API_KEY)
HAS_AVIATIONSTACK = bool(AVIATIONSTACK_API_KEY)
HAS_SEARCHAPI     = bool(SEARCH_API_KEY)
HAS_TAVILY        = bool(TAVILY_API_KEY)
HAS_AIRLABS       = bool(AIRLABS_API_KEY)

REQUEST_TIMEOUT_SECONDS = 15
