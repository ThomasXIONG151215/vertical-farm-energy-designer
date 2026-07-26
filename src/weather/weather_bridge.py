"""
Weather bridge — fetches hourly meteorology from Open-Meteo for an arbitrary
site and prepares it for the building + PV simulations.

Outputs a tidy hourly DataFrame with the columns consumed downstream:

  timestamp, temperature_2m, relative_humidity_2m, wind_speed_10m,
  shortwave_radiation (GHI, W/m^2),
  direct_radiation, diffuse_radiation (POA components, W/m^2),
  poa_radiation (total plane-of-array, W/m^2)

The PV single-diode model uses ``direct_radiation + diffuse_radiation``; by
convention those two columns sum to the plane-of-array irradiance on the
configured tilt, while ``shortwave_radiation`` remains the horizontal GHI
(used for window solar gain).
"""

from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import pandas as pd

try:
    import requests
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False

OPEN_METEO_URL = "https://archive-api.open-meteo.com/v1/archive"
OPEN_METEO_FCST = "https://api.open-meteo.com/v1/forecast"

__all__ = ["fetch_weather", "add_poa", "erbs_split"]


def _cache_path(cache_dir: Path, lat: float, lon: float, year: int) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"weather_{lat:.3f}_{lon:.3f}_{year}.csv"


def _find_city_csv(city: str, year: int) -> Optional[Path]:
    """Search for a pre-downloaded city weather CSV.

    Checks ``data/weather/{city}_{year}.csv`` relative to the project root
    (``vfed`` package parent).  Returns ``None`` if the file does not exist.
    """
    # Project root = directory containing src/
    root = Path(__file__).resolve().parent.parent.parent
    candidate = root / "data" / "weather" / f"{city}_{year}.csv"
    if candidate.exists():
        return candidate
    return None


def _solar_geometry(lat: float, lon: float, tz_hours: float,
                    dt: pd.DatetimeIndex) -> Tuple[np.ndarray, np.ndarray]:
    """Return solar zenith and azimuth (degrees) for each timestamp."""
    lat_r = np.deg2rad(lat)
    doy = dt.dayofyear.values
    # Local solar time correction (simplified, no equation-of-time refinement).
    lst = dt.hour.values + dt.minute.values / 60.0 + (lon / 15.0 - tz_hours)
    decl = np.deg2rad(23.45 * np.sin(np.deg2rad(360.0 * (284.0 + doy) / 365.0)))
    hour_angle = np.deg2rad(15.0 * (lst - 12.0))
    sin_alt = (np.sin(lat_r) * np.sin(decl) +
               np.cos(lat_r) * np.cos(decl) * np.cos(hour_angle))
    sin_alt = np.clip(sin_alt, -1.0, 1.0)
    altitude = np.arcsin(sin_alt)
    zenith = np.pi / 2 - altitude
    # Azimuth (from south, +/-)
    cos_az = (np.sin(decl) - np.sin(lat_r) * sin_alt) / np.maximum(
        np.cos(lat_r) * np.cos(altitude), 1e-6)
    cos_az = np.clip(cos_az, -1.0, 1.0)
    az = np.arccos(cos_az)
    az = np.where(hour_angle > 0, 2 * np.pi - az, az)
    return np.rad2deg(zenith), np.rad2deg(az)


def erbs_split(ghi: np.ndarray, zenith_deg: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Erbs model: split GHI into diffuse and direct-normal irradiance.

    Returns (diffuse_horizontal, dni).
    """
    ghi = np.asarray(ghi, dtype=float)
    zen = np.deg2rad(np.asarray(zenith_deg, dtype=float))
    cos_z = np.cos(zen)
    cos_z = np.clip(cos_z, 1e-3, 1.0)
    # Clearness index kt
    extraterrestrial = 1367.0 * cos_z
    kt = np.where(extraterrestrial > 0, ghi / extraterrestrial, 0.0)
    kt = np.clip(kt, 0.0, 1.0)
    # Diffuse fraction (Erbs et al. 1982)
    df = np.empty_like(kt)
    m1 = kt <= 0.22
    df[m1] = 1.0 - 0.09 * kt[m1]
    m2 = (kt > 0.22) & (kt <= 0.80)
    df[m2] = 0.9511 - 0.1604 * kt[m2] + 4.388 * kt[m2] ** 2 - \
             16.638 * kt[m2] ** 3 + 12.336 * kt[m2] ** 4
    m3 = kt > 0.80
    df[m3] = 0.165
    diffuse = df * ghi
    dni = np.where(cos_z > 1e-3, (ghi - diffuse) / cos_z, 0.0)
    dni = np.clip(dni, 0.0, None)
    return diffuse, dni


def add_poa(df: pd.DataFrame, tilt: float = 20.0, azimuth: float = 180.0,
           lat: float = 31.2, lon: float = 121.5, tz_hours: float = 8.0) -> pd.DataFrame:
    """Add ``poa_radiation`` (and overwrite direct/diffuse as POA components).

    Uses beam (Hay/Iska) + isotropic diffuse + ground-reflected components.
    """
    out = df.copy()
    ghi = out["shortwave_radiation"].values.astype(float)
    has_components = ("direct_radiation" in out.columns and
                      not np.allclose(
                          out["direct_radiation"] if "direct_radiation" in out.columns
                          else pd.Series(0.0, index=out.index),
                          0))
    if has_components:
        diffuse_h = out["diffuse_radiation"].values.astype(float)
        dni = out["direct_radiation"].values.astype(float) / np.maximum(
            np.cos(np.deg2rad(_solar_geometry(lat, lon, tz_hours, out.index)[0])), 1e-3)
    else:
        zen, _ = _solar_geometry(lat, lon, tz_hours, out.index)
        diffuse_h, dni = erbs_split(ghi, zen)
        out["diffuse_radiation"] = diffuse_h
    zen, sol_az = _solar_geometry(lat, lon, tz_hours, out.index)
    zen_r, sol_az_r = np.deg2rad(zen), np.deg2rad(sol_az)
    tilt_r, surf_az_r = np.deg2rad(tilt), np.deg2rad(azimuth)
    cos_inc = (np.sin(zen_r) * np.cos(surf_az_r - sol_az_r) * np.sin(tilt_r) +
               np.cos(zen_r) * np.cos(tilt_r))
    cos_inc = np.clip(cos_inc, 0.0, None)
    cos_z = np.clip(np.cos(zen_r), 1e-3, 1.0)
    # Beam (POA)
    beam_poa = dni * cos_inc
    # Diffuse: isotropic + horizon brightening (simplified Hay)
    diffuse_poa = diffuse_h * (1 + np.cos(tilt_r)) / 2.0
    # Ground reflected
    alb = 0.2
    ground = alb * ghi * (1 - np.cos(tilt_r)) / 2.0
    poa = np.clip(beam_poa + diffuse_poa + ground, 0.0, None)
    out["poa_radiation"] = poa
    # Re-express direct/diffuse as POA components (their sum = POA).
    out["direct_radiation"] = beam_poa
    out["diffuse_radiation"] = diffuse_poa + ground
    return out


def fetch_weather(
    lat: float,
    lon: float,
    year: int,
    tz_hours: float = 8.0,
    tilt: float = 20.0,
    azimuth: float = 180.0,
    cache_dir: Optional[Path] = None,
    force: bool = False,
    use_forecast: bool = False,
    city: Optional[str] = None,
) -> pd.DataFrame:
    """Fetch (and cache) hourly weather for a calendar year.

    When ``city`` is provided and a pre-downloaded CSV exists in
    ``data/weather/{city}_{year}.csv`` (relative to project root), it is
    loaded directly without any API call.  Falls back to Open-Meteo if
    the local file is not found.
    """
    cache_dir = Path(cache_dir) if cache_dir else Path("weather_cache")
    cp = _cache_path(cache_dir, lat, lon, year)

    # ── City-based local CSV (no API) ──
    if city:
        local = _find_city_csv(city, year)
        if local is not None:
            df = pd.read_csv(local, parse_dates=["timestamp"])
            df = df.set_index("timestamp")
            if "poa_radiation" not in df.columns:
                df = add_poa(df, tilt, azimuth, lat, lon, tz_hours)
            # Also write to the standard cache so subsequent calls hit quickly
            if not cp.exists():
                cache_dir.mkdir(parents=True, exist_ok=True)
                df.to_csv(cp)
            return df

    # ── Standard lat/lon cache ──
    if cp.exists() and not force:
        df = pd.read_csv(cp, parse_dates=["timestamp"])
        df = df.set_index("timestamp")
        if "poa_radiation" not in df.columns:
            df = add_poa(df, tilt, azimuth, lat, lon, tz_hours)
        return df

    if not _HAS_REQUESTS:
        raise ImportError("The 'requests' package is required to fetch weather "
                          "from Open-Meteo. Install it or provide a cached CSV.")

    start = f"{year}-01-01"
    end = f"{year}-12-31"
    url = OPEN_METEO_FCST if use_forecast else OPEN_METEO_URL
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start,
        "end_date": end,
        "hourly": ("temperature_2m,relative_humidity_2m,surface_pressure,"
                   "shortwave_radiation,direct_radiation,diffuse_radiation"),
        "timezone": "UTC",
        "wind_speed_unit": "ms",
    }
    resp = requests.get(url, params=params, timeout=120)
    resp.raise_for_status()
    data = resp.json()["hourly"]
    df = pd.DataFrame({
        "timestamp": pd.to_datetime(data["time"], utc=True),
        "temperature_2m": data["temperature_2m"],
        "relative_humidity_2m": data["relative_humidity_2m"],
        "surface_pressure": data.get("surface_pressure", [101.325] * len(data["time"])),
        "shortwave_radiation": data.get("shortwave_radiation", [0] * len(data["time"])),
        "direct_radiation": data.get("direct_radiation", [0] * len(data["time"])),
        "diffuse_radiation": data.get("diffuse_radiation", [0] * len(data["time"])),
    })
    # Convert to local time for convenience.
    df["timestamp"] = df["timestamp"].dt.tz_convert(None) + pd.Timedelta(hours=tz_hours)
    df = df.set_index("timestamp")
    df = add_poa(df, tilt, azimuth, lat, lon, tz_hours)
    df.to_csv(cp)
    return df
