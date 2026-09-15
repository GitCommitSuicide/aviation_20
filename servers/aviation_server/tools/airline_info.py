# -*- coding: utf-8 -*-
"""
servers/aviation_server/tools/airline_info.py
==============================================
get_airline_info      -- Look up any airline by IATA/ICAO code.
suggest_flight_search -- Auto-complete search for airports, airlines, cities.

Uses AirLabs /airlines and /suggest endpoints.
"""

from servers.aviation_server.config import HAS_AIRLABS, get_logger
from servers.aviation_server.providers import airlabs
from servers.aviation_server.providers.airlabs import _get as _airlabs_get

logger = get_logger(__name__)


def get_airline_info(search_term: str) -> str:
    """
    Look up airline details by IATA code, ICAO code, or name.
    Returns IATA/ICAO codes, country, type, hub airport, and contact info.

    Args:
        search_term: Airline IATA code (e.g. "6E", "AI", "BA"),
                     ICAO code (e.g. "IGO", "AIC"), or airline name
                     (e.g. "IndiGo", "Air India").
    """
    logger.info("get_airline_info search=%r", search_term)

    if not HAS_AIRLABS:
        return "Airline info is unavailable (missing AIRLABS_API key)."

    term = search_term.strip().upper()
    ok = False
    payload = None

    # 2-char IATA code (can be alphanumeric, e.g. 6E, 2W)
    if len(term) == 2:
        ok, payload = airlabs.get_airlines(iata=term)

    # 3-letter ICAO code (all alphabetic)
    if (not ok or not payload) and len(term) == 3 and term.isalpha():
        ok, payload = _airlabs_get("airlines", {"icao_code": term})

    # Fall back: use /suggest to find the best match, then do IATA lookup
    if not ok or not payload:
        ok_s, sug = airlabs.suggest(query=search_term.strip())
        if ok_s and isinstance(sug, dict):
            al_sug = sug.get("airlines", [])
            if al_sug:
                best_iata = al_sug[0].get("iata_code", "")
                if best_iata:
                    ok, payload = airlabs.get_airlines(iata=best_iata)

    if not ok or not payload:
        return "No airline found matching '{}'. Try the IATA code (e.g. 6E, AI, BA).".format(search_term)

    airlines = payload if isinstance(payload, list) else [payload] if isinstance(payload, dict) else []
    if not airlines:
        return "No airline found matching '{}'. Try the IATA code (e.g. 6E, AI, BA).".format(search_term)

    airlines = airlines[:5]
    lines = ["**Airline Information** -- {} result(s) for '{}'".format(len(airlines), search_term), ""]

    for al in airlines:
        iata = al.get("iata_code") or "N/A"
        icao = al.get("icao_code") or "N/A"
        name = al.get("name", "Unknown Airline")
        country = al.get("country_code", "")
        callsign = al.get("callsign", "")
        hub = al.get("hub_code", "")
        is_lcc = al.get("is_lcc", None)
        status = al.get("status", "")
        website = al.get("website", "")
        phone = al.get("phone", "")
        facebook = al.get("facebook", "")
        twitter = al.get("twitter", "")

        lines.append("### {}".format(name))
        lines.append("- **IATA:** `{}` | **ICAO:** `{}`".format(iata, icao))
        if country:
            lines.append("- **Country:** {}".format(country))
        if callsign:
            lines.append("- **Callsign:** {}".format(callsign))
        if hub:
            lines.append("- **Hub Airport:** `{}`".format(hub))
        if is_lcc is not None:
            lcc_str = "Low-Cost Carrier (LCC)" if is_lcc else "Full-Service Airline"
            lines.append("- **Type:** {}".format(lcc_str))
        if status:
            lines.append("- **Status:** {}".format(status.title()))
        if website:
            lines.append("- **Website:** {}".format(website))
        if phone:
            lines.append("- **Phone:** {}".format(phone))
        if facebook:
            lines.append("- **Facebook:** {}".format(facebook))
        if twitter:
            lines.append("- **Twitter:** {}".format(twitter))
        lines.append("")

    return "\n".join(lines)


def suggest_flight_search(query: str) -> str:
    """
    Auto-complete / name suggestion for airports, airlines, and cities.
    Useful when the user provides a partial or ambiguous name.

    Args:
        query: Partial name to search (e.g. "Chenn", "Indi", "Air").
    """
    logger.info("suggest_flight_search query=%r", query)

    if not HAS_AIRLABS:
        return "Search suggestions are unavailable (missing AIRLABS_API key)."

    ok, payload = airlabs.suggest(query=query.strip())
    if not ok:
        return "Could not get suggestions for '{}': {}".format(query, payload)

    if not isinstance(payload, dict):
        return "No suggestions found for '{}'.".format(query)

    lines = ["**Search Suggestions for '{}'**".format(query), ""]
    found_anything = False

    airports = payload.get("airports", [])
    if airports:
        found_anything = True
        lines.append("**Airports:**")
        for ap in airports[:5]:
            iata = ap.get("iata_code", "")
            name = ap.get("name", "")
            city = ap.get("city", "")
            lines.append("  - `{}` -- {} ({})".format(iata, name, city))
        lines.append("")

    al_list = payload.get("airlines", [])
    if al_list:
        found_anything = True
        lines.append("**Airlines:**")
        for al in al_list[:5]:
            iata = al.get("iata_code", "")
            name = al.get("name", "")
            country = al.get("country_code", "")
            lines.append("  - `{}` -- {} ({})".format(iata, name, country))
        lines.append("")

    cities = payload.get("cities", [])
    if cities:
        found_anything = True
        lines.append("**Cities:**")
        for c in cities[:5]:
            name = c.get("name", "")
            country = c.get("country_code", "")
            lines.append("  - {} ({})".format(name, country))
        lines.append("")

    if not found_anything:
        return "No suggestions found for '{}'.".format(query)

    return "\n".join(lines)
