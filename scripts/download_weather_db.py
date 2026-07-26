"""
One-shot script: download 2025 hourly weather for every city in the city DB.

Run once and commit the resulting CSV files to ``data/weather/``.
The files are then consumed by ``fetch_weather(city=...)`` without any
API call at design time.

Usage::

    python scripts/download_weather_db.py [--force]
"""

import sys
import time
from pathlib import Path

# Append project root to sys.path so we can import src.*
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests
import pandas as pd

from src.weather.city_db import AVAILABLE_CITIES, _COORDS

OPEN_METEO_URL = "https://archive-api.open-meteo.com/v1/archive"
YEAR = 2025
OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "weather"
WEB_DIR = Path(__file__).resolve().parent.parent / "vfed-web" / "data" / "weather"


def download_city(city: str, force: bool = False) -> bool:
    out_path = OUT_DIR / f"{city}_{YEAR}.csv"
    if out_path.exists() and not force:
        print(f"  [skip] {city} — already exists")
        return True

    coords = _COORDS.get(city)
    if coords is None:
        print(f"  [FAIL] {city} — no coordinates in _COORDS")
        return False

    lat, lon, tz = coords
    print(f"  downloading {city} (lat={lat:.2f}, lon={lon:.2f})...", end=" ", flush=True)
    try:
        params = {
            "latitude": lat,
            "longitude": lon,
            "start_date": f"{YEAR}-01-01",
            "end_date": f"{YEAR}-12-31",
            "hourly": ("temperature_2m,relative_humidity_2m,wind_speed_10m,"
                       "shortwave_radiation,direct_radiation,diffuse_radiation"),
            "timezone": "UTC",
            "wind_speed_unit": "ms",
        }
        resp = requests.get(OPEN_METEO_URL, params=params, timeout=120)
        resp.raise_for_status()
        data = resp.json()["hourly"]

        df = pd.DataFrame({
            "timestamp": pd.to_datetime(data["time"], utc=True),
            "temperature_2m": data["temperature_2m"],
            "relative_humidity_2m": data["relative_humidity_2m"],
            "wind_speed_10m": data["wind_speed_10m"],
            "shortwave_radiation": data.get("shortwave_radiation", 0),
            "direct_radiation": data.get("direct_radiation", 0),
            "diffuse_radiation": data.get("diffuse_radiation", 0),
        })

        # Convert UTC → local time
        offset_h = int(round(tz))
        df["timestamp"] = df["timestamp"] + pd.Timedelta(hours=offset_h)
        df = df.set_index("timestamp")

        # Drop Feb 29 if it exists (non-leap year, but API may include it)
        feb29 = f"{YEAR}-02-29"
        df = df[~df.index.strftime("%Y-%m-%d").str.match(feb29)]

        # Fill missing with 0
        df = df.fillna(0.0)

        OUT_DIR.mkdir(parents=True, exist_ok=True)
        WEB_DIR.mkdir(parents=True, exist_ok=True)

        df.to_csv(out_path)
        df.to_csv(WEB_DIR / f"{city}_{YEAR}.csv")

        print(f"OK ({len(df)} rows)")
        return True
    except Exception as exc:
        print(f"FAIL: {exc}")
        return False


def main():
    force = "--force" in sys.argv
    print(f"Downloading {YEAR} weather for {len(AVAILABLE_CITIES)} cities...")
    ok = fail = 0
    for city in AVAILABLE_CITIES:
        if download_city(city, force=force):
            ok += 1
        else:
            fail += 1
        time.sleep(0.5)  # rate limit courtesy
    print(f"\nDone. {ok} success, {fail} failed.")


if __name__ == "__main__":
    main()
