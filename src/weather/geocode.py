"""
Open-Meteo Geocoding — city name to coordinates.

Single function with a single API call.  Used by ``vfed design new --city`` to
avoid requiring users to manually look up lat/lon.
"""

__all__ = ["geocode_city"]


def geocode_city(name: str) -> tuple[float, float]:
    """Return ``(lat, lon)`` for a city name.

    Raises ``ValueError`` when the name is not found.
    """
    import requests

    url = "https://geocoding-api.open-meteo.com/v1/search"
    resp = requests.get(
        url,
        params={"name": name, "count": 1, "language": "en", "format": "json"},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    results = data.get("results")
    if not results:
        raise ValueError(f"City not found: {name}")
    r = results[0]
    return float(r["latitude"]), float(r["longitude"])
