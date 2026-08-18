"""
Available cities for weather data lookup.

Provides a static list of city names with pre-downloaded 2025 weather
data.  No API call is needed at design time — selecting a city loads
the corresponding CSV from ``data/weather/`` (or equivalent cache dir).
"""

from typing import Dict, List, Optional

__all__ = ["AVAILABLE_CITIES", "lookup_city", "list_cities", "city_coords"]

AVAILABLE_CITIES: List[str] = [
    "Shanghai", "Nanjing", "Hangzhou", "Suzhou", "Ningbo", "Wuxi",
    "Hefei", "Fuzhou", "Xiamen", "Qingdao", "Jinan",
    "Beijing", "Tianjin", "Shijiazhuang", "Taiyuan", "Shenyang",
    "Dalian", "Harbin", "Changchun",
    "Guangzhou", "Shenzhen", "Dongguan", "Changsha", "Wuhan",
    "Zhengzhou", "Nanchang", "Nanning", "Haikou",
    "Chengdu", "Chongqing", "Kunming", "Guiyang", "Lhasa",
    "Xi'an", "Lanzhou", "Urumqi", "Yinchuan", "Xining",
    "Tokyo", "Osaka", "Seoul", "Singapore", "Bangkok",
    "Dubai", "Amsterdam", "London", "New York",
    "Los Angeles", "Chicago", "Melbourne", "Sydney",
]

# Internal coordinate table (kept private — used by the download script).
_COORDS: Dict[str, tuple] = {
    "Shanghai":     (31.23, 121.47, 8.0),
    "Nanjing":      (32.06, 118.80, 8.0),
    "Hangzhou":     (30.29, 120.16, 8.0),
    "Suzhou":       (31.30, 120.62, 8.0),
    "Ningbo":       (29.87, 121.55, 8.0),
    "Wuxi":         (31.57, 120.29, 8.0),
    "Hefei":        (31.82, 117.23, 8.0),
    "Fuzhou":       (26.07, 119.30, 8.0),
    "Xiamen":       (24.48, 118.09, 8.0),
    "Qingdao":      (36.07, 120.38, 8.0),
    "Jinan":        (36.65, 117.00, 8.0),
    "Beijing":      (39.91, 116.40, 8.0),
    "Tianjin":      (39.13, 117.20, 8.0),
    "Shijiazhuang": (38.04, 114.51, 8.0),
    "Taiyuan":      (37.87, 112.55, 8.0),
    "Shenyang":     (41.80, 123.43, 8.0),
    "Dalian":       (38.92, 121.63, 8.0),
    "Harbin":       (45.80, 126.53, 8.0),
    "Changchun":    (43.90, 125.20, 8.0),
    "Guangzhou":    (23.13, 113.26, 8.0),
    "Shenzhen":     (22.54, 114.06, 8.0),
    "Dongguan":     (23.04, 113.76, 8.0),
    "Changsha":     (28.20, 113.08, 8.0),
    "Wuhan":        (30.59, 114.30, 8.0),
    "Zhengzhou":    (34.75, 113.62, 8.0),
    "Nanchang":     (28.68, 115.86, 8.0),
    "Nanning":      (22.82, 108.37, 8.0),
    "Haikou":       (20.04, 110.34, 8.0),
    "Chengdu":      (30.57, 104.07, 8.0),
    "Chongqing":    (29.56, 106.55, 8.0),
    "Kunming":      (25.04, 102.68, 8.0),
    "Guiyang":      (26.65, 106.63, 8.0),
    "Lhasa":        (29.65, 91.10, 8.0),
    "Xi'an":        (34.26, 108.94, 8.0),
    "Lanzhou":      (36.06, 103.83, 8.0),
    "Urumqi":       (43.83, 87.62, 6.0),
    "Yinchuan":     (38.47, 106.27, 8.0),
    "Xining":       (36.62, 101.78, 8.0),
    "Tokyo":        (35.68, 139.76, 9.0),
    "Osaka":        (34.69, 135.50, 9.0),
    "Seoul":        (37.57, 126.98, 9.0),
    "Singapore":    (1.35, 103.82, 8.0),
    "Bangkok":      (13.76, 100.50, 7.0),
    "Dubai":        (25.20, 55.27, 4.0),
    "Amsterdam":    (52.37, 4.90, 1.0),
    "London":       (51.51, -0.13, 0.0),
    "New York":     (40.71, -74.01, -5.0),
    "Los Angeles":  (34.05, -118.24, -8.0),
    "Chicago":      (41.88, -87.63, -6.0),
    "Melbourne":    (-37.81, 144.96, 10.0),
    "Sydney":       (-33.87, 151.21, 10.0),
}


def lookup_city(name: str) -> Optional[str]:
    """Return the canonical city name if found, else ``None``."""
    if not name:
        return None
    key = name.strip()
    if key in AVAILABLE_CITIES:
        return key
    kl = key.lower()
    for c in AVAILABLE_CITIES:
        if c.lower() == kl:
            return c
    for c in AVAILABLE_CITIES:
        if c.lower().startswith(kl):
            return c
    return None


def list_cities() -> List[Dict[str, str]]:
    return [{"name": c} for c in AVAILABLE_CITIES]


def city_coords(name: str) -> Optional[tuple]:
    """Return ``(lat, lon, tz_hours)`` for a canonical city name, else ``None``.

    The coordinate table carries the correct UTC offset per city (e.g. Urumqi
    is UTC+6, Tokyo +9) — unlike a network geocode, which defaults to +8.
    """
    if not name:
        return None
    return _COORDS.get(name.strip())
