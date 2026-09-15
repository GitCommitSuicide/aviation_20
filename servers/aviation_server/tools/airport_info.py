# -*- coding: utf-8 -*-
"""
servers/aviation_server/tools/airport_info.py
===============================================
get_airport_info     -- Look up any airport by name, city, or IATA code.
find_nearby_airports -- Find airports within a radius of a GPS point.

Uses AirLabs /airports and /nearby endpoints.
"""

from servers.aviation_server.config import HAS_AIRLABS, get_logger
from servers.aviation_server.providers import airlabs

logger = get_logger(__name__)


def get_airport_info(search_term: str) -> str:
    """
    Look up airport details by name, city, country, or IATA code.
    Returns IATA/ICAO codes, city, country, timezone, and GPS coordinates.

    Args:
        search_term: Airport name, city, IATA code (e.g. "Chennai", "MAA",
                     "Indira Gandhi", "Mumbai").
    """
    logger.info("get_airport_info search=%r", search_term)

    if not HAS_AIRLABS:
        return "Airport info is unavailable (missing AIRLABS_API key)."

    term = search_term.strip()
    if len(term) == 3 and term.isalpha():
        ok, payload = airlabs.get_airports(iata=term)
    else:
        ok, payload = airlabs.get_airports(search=term)

    if not ok:
        if payload == "NOT_FOUND":
            return "No airport found matching '{}'.".format(search_term)
        if payload == "RATE_LIMITED":
            return "Airport lookup is temporarily unavailable (rate limit reached)."
        return "Could not look up airport '{}': {}".format(search_term, payload)

    airports = payload if isinstance(payload, list) else [payload] if isinstance(payload, dict) else []
    if not airports:
        return "No airport found matching '{}'.".format(search_term)

    airports = airports[:5]
    lines = ["**Airport Information** -- {} result(s) for '{}'" .format(len(airports), search_term), ""]

    for ap in airports:
        iata = ap.get("iata_code", "N/A")
        icao = ap.get("icao_code", "N/A")
        name = ap.get("name", "Unknown Airport")
        city = ap.get("city", "")
        country = ap.get("country_code", "")
        tz = ap.get("timezone", "")
        lat = ap.get("lat", "")
        lng = ap.get("lng", "")
        phone = ap.get("phone", "")
        website = ap.get("website", "")
        email = ap.get("email", "")

        lines.append("### {}".format(name))
        lines.append("- **IATA:** `{}` | **ICAO:** `{}`".format(iata, icao))
        if city or country:
            loc = city
            if country:
                loc += (", " + country) if loc else country
            lines.append("- **Location:** {}".format(loc))
        if tz:
            lines.append("- **Timezone:** {}".format(tz))
        if lat and lng:
            lines.append("- **Coordinates:** {}, {}".format(lat, lng))
        if phone:
            lines.append("- **Phone:** {}".format(phone))
        if website:
            lines.append("- **Website:** {}".format(website))
        if email:
            lines.append("- **Email:** {}".format(email))
        lines.append("")

    return "\n".join(lines)


def find_nearby_airports(lat: float, lng: float, radius_km: int = 100) -> str:
    """
    Find airports near a geographic location.

    Args:
        lat: Latitude of the point of interest.
        lng: Longitude of the point of interest.
        radius_km: Search radius in kilometres (default 100 km).
    """
    logger.info("find_nearby_airports lat=%s lng=%s radius=%s", lat, lng, radius_km)

    if not HAS_AIRLABS:
        return "Nearby airport search is unavailable (missing AIRLABS_API key)."

    ok, payload = airlabs.get_nearby_airports(lat=lat, lng=lng, dist_km=radius_km)
    if not ok:
        if payload == "NOT_FOUND":
            return "No airports found within {} km of ({}, {}).".format(radius_km, lat, lng)
        return "Could not search nearby airports: {}".format(payload)

    airports = payload if isinstance(payload, list) else []
    if not airports:
        return "No airports found within {} km of ({}, {}).".format(radius_km, lat, lng)

    airports = airports[:10]
    lines = [
        "**Airports within {} km of ({}, {})** -- {} found".format(radius_km, lat, lng, len(airports)),
        "",
        "| IATA | Name | City | Country | Distance |",
        "|------|------|------|---------|----------|",
    ]
    for ap in airports:
        iata = ap.get("iata_code", "N/A")
        name = ap.get("name", "Unknown")
        city = ap.get("city", "")
        country = ap.get("country_code", "")
        dist = ap.get("distance", "")
        dist_str = "{:.0f} km".format(dist) if isinstance(dist, (int, float)) else str(dist)
        lines.append("| {} | {} | {} | {} | {} |".format(iata, name, city, country, dist_str))

    return "\n".join(lines)
