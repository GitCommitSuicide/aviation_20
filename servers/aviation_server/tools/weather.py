"""
servers/aviation_server/tools/weather.py
==========================================
get_airport_weather — current conditions at an airport via Open-Meteo
(free, no API key required).
"""

import requests

from shared.airport_data import get_airport_coords
from servers.aviation_server.config import REQUEST_TIMEOUT_SECONDS, get_logger

logger = get_logger(__name__)


from datetime import datetime, timedelta

def get_airport_weather(iata_code: str, date: str = None) -> str:
    """
    Get current or forecasted weather conditions at an airport — useful for anticipating
    weather-related delays.

    Args:
        iata_code: 3-letter IATA code, e.g. "SFO".
        date: Optional date in YYYY-MM-DD format for a future forecast (up to 14 days ahead).
              If omitted, returns current weather.
    """
    logger.info("get_airport_weather iata_code=%r date=%r", iata_code, date)
    iata_code = iata_code.strip().upper()
    coords = get_airport_coords(iata_code)
    if not coords:
        return f"Unknown airport code: {iata_code}"

    lat, lon = coords
    
    try:
        if date:
            # Parse date to ensure format and check limits
            try:
                target_date = datetime.strptime(date, "%Y-%m-%d").date()
            except ValueError:
                return "Invalid date format. Please use YYYY-MM-DD."
                
            today = datetime.utcnow().date()
            days_ahead = (target_date - today).days
            
            if days_ahead < 0:
                return "Cannot fetch weather for past dates."
            if days_ahead > 14:
                return "Cannot fetch weather forecast more than 14 days in advance."
                
            resp = requests.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "daily": "temperature_2m_max,temperature_2m_min,wind_speed_10m_max,weather_code",
                    "start_date": date,
                    "end_date": date,
                    "timezone": "auto"
                },
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            data = resp.json().get("daily", {})
            
            if not data or not data.get("time"):
                return f"Forecast not available for {date} at {iata_code}."
                
            temp_max = data.get("temperature_2m_max", ["N/A"])[0]
            temp_min = data.get("temperature_2m_min", ["N/A"])[0]
            wind_max = data.get("wind_speed_10m_max", ["N/A"])[0]
            
            return (
                f"Weather Forecast at {iata_code} for {date}:\n"
                f"  - High Temp:  {temp_max}°C\n"
                f"  - Low Temp:   {temp_min}°C\n"
                f"  - Max Wind:   {wind_max} km/h\n"
            )
        else:
            resp = requests.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "temperature_2m,wind_speed_10m,weather_code,visibility",
                },
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            data = resp.json().get("current", {})

            temp = data.get("temperature_2m", "N/A")
            wind = data.get("wind_speed_10m", "N/A")
            vis = data.get("visibility", "N/A")

            return (
                f"Current Weather at {iata_code}:\n"
                f"  - Temperature: {temp}°C\n"
                f"  - Wind Speed:  {wind} km/h\n"
                f"  - Visibility:  {vis} meters"
            )
    except Exception as e:
        logger.error("Weather API error for %s: %s", iata_code, e)
        return f"Failed to fetch weather for {iata_code}: {e}"
