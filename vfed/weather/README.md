# Weather Module

Meteorological data acquisition — Open-Meteo API (NASA-POWER fallback), Erbs GHI splitting, plane-of-array irradiance, and geocoding.

## Files

| File | Purpose |
|------|---------|
| `weather_bridge.py` | Fetches hourly weather from Open-Meteo (NASA-POWER fallback), performs Erbs 1982 GHI split, computes POA irradiance, caches as CSV; accepts any validated gapless hourly grid (zero-order-hold time-indexed lookup) |
| `geocode.py` | Open-Meteo geocoding — converts city name to (lat, lon) via API call |

## Usage

```python
from vfed.weather.weather_bridge import fetch_weather
from vfed.weather.geocode import geocode_city

lat, lon = geocode_city("Shanghai")
df = fetch_weather(lat, lon, year=2023, cache_dir="weather_cache")
```
