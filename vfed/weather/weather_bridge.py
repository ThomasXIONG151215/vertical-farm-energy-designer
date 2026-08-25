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

import calendar
import warnings
from datetime import date, timedelta, timezone
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import pandas as pd

try:
    import requests

    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False

try:
    from pyodide.http import open_url as _py_open_url

    _HAS_PYODIDE = True
except ImportError:
    _HAS_PYODIDE = False

OPEN_METEO_URL = "https://archive-api.open-meteo.com/v1/archive"
OPEN_METEO_FCST = "https://api.open-meteo.com/v1/forecast"


class WeatherFetchError(Exception):
    """Raised when weather data cannot be acquired (error code E003).

    Covers missing 'requests', transport failures, and non-2xx API
    responses — anything that prevents a full year of weather from being
    produced.  The CLI maps this exception to ``[ERROR E003]``.
    """


__all__ = ["fetch_weather", "add_poa", "erbs_split", "WeatherFetchError"]


def _cache_path(
    cache_dir: Path,
    lat: float,
    lon: float,
    year: int,
    tilt: float = 20.0,
    azimuth: float = 180.0,
    tz_hours: float = 8.0,
) -> Path:
    """Tilt-aware cache key — POA depends on (tilt, azimuth, tz_hours)."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / (
        f"weather_{lat:.3f}_{lon:.3f}_{year}" f"_t{tilt:.3f}_a{azimuth:.3f}_z{tz_hours:.3f}.csv"
    )


def _legacy_cache_path(cache_dir: Path, lat: float, lon: float, year: int) -> Path:
    """Pre-P6-1 geometry-independent cache name (kept readable)."""
    return cache_dir / f"weather_{lat:.3f}_{lon:.3f}_{year}.csv"


def _find_city_csv(city: str, year: int) -> Optional[Path]:
    """Search for a pre-downloaded city weather CSV.

    Checks ``data/weather/{city}_{year}.csv`` relative to the project root
    (``vfed`` package parent).  Returns ``None`` if the file does not exist.
    """
    # Project root = directory containing vfed/
    root = Path(__file__).resolve().parent.parent.parent
    candidate = root / "data" / "weather" / f"{city}_{year}.csv"
    if candidate.exists():
        return candidate
    return None


def _solar_geometry(
    lat: float, lon: float, tz_hours: float, dt: pd.DatetimeIndex
) -> Tuple[np.ndarray, np.ndarray]:
    """Return solar zenith and azimuth (degrees) for each timestamp."""
    lat_r = np.deg2rad(lat)
    doy = dt.dayofyear.values
    # Local solar time = clock time + (standard meridian - local meridian)/15 h.
    # Standard meridian = 15 * tz_hours, so offset = tz_hours - lon/15.
    # (Simplified: no equation-of-time refinement.)
    lst = dt.hour.values + dt.minute.values / 60.0 + (tz_hours - lon / 15.0)
    decl = np.deg2rad(23.45 * np.sin(np.deg2rad(360.0 * (284.0 + doy) / 365.0)))
    hour_angle = np.deg2rad(15.0 * (lst - 12.0))
    sin_alt = np.sin(lat_r) * np.sin(decl) + np.cos(lat_r) * np.cos(decl) * np.cos(hour_angle)
    sin_alt = np.clip(sin_alt, -1.0, 1.0)
    altitude = np.arcsin(sin_alt)
    zenith = np.pi / 2 - altitude
    # Azimuth (from south, +/-)
    cos_az = (np.sin(decl) - np.sin(lat_r) * sin_alt) / np.maximum(
        np.cos(lat_r) * np.cos(altitude), 1e-6
    )
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
    df[m2] = (
        0.9511 - 0.1604 * kt[m2] + 4.388 * kt[m2] ** 2 - 16.638 * kt[m2] ** 3 + 12.336 * kt[m2] ** 4
    )
    m3 = kt > 0.80
    df[m3] = 0.165
    diffuse = df * ghi
    dni = np.where(cos_z > 1e-3, (ghi - diffuse) / cos_z, 0.0)
    dni = np.clip(dni, 0.0, None)
    return diffuse, dni


def add_poa(
    df: pd.DataFrame,
    tilt: float = 20.0,
    azimuth: float = 180.0,
    lat: float = 31.2,
    lon: float = 121.5,
    tz_hours: float = 8.0,
) -> pd.DataFrame:
    """Add ``poa_radiation`` (and overwrite direct/diffuse as POA components).

    Model = beam (``dni * cos(incidence)``) + isotropic diffuse
    (``(1 + cos(tilt))/2`` sky view factor) + isotropic ground reflection
    (``albedo * GHI * (1 - cos(tilt))/2``).  No horizon brightening or
    circumsolar (Hay) enhancement is applied (P6-8).
    """
    out = df.copy()
    if "poa_radiation" in out.columns:
        # P6-8: input is already POA-ised — direct/diffuse are plane-of-array
        # components, so ``direct/cos(zen)`` would treat a POA beam as
        # horizontal and over-scale DNI by up to 1/cos(zen).  Drop the derived
        # columns and recompute from GHI (Erbs split) instead.
        warnings.warn(
            "add_poa(): input already contains poa_radiation; dropping "
            "POA-ised direct/diffuse and recomputing from GHI (Erbs split).",
            stacklevel=2,
        )
        out = out.drop(columns=["poa_radiation", "direct_radiation", "diffuse_radiation"])
    ghi = out["shortwave_radiation"].values.astype(float)
    has_components = "direct_radiation" in out.columns and not np.allclose(
        out["direct_radiation"]
        if "direct_radiation" in out.columns
        else pd.Series(0.0, index=out.index),
        0,
    )
    if has_components:
        # Input carries horizontal beam/diffuse (Open-Meteo convention):
        # direct_radiation == horizontal beam (DNI * cos(zen)), so dividing by
        # cos(zen) recovers DNI.  Only valid for HORIZONTAL inputs — see the
        # poa_radiation guard above for POA-ised inputs.
        diffuse_h = out["diffuse_radiation"].values.astype(float)
        dni = out["direct_radiation"].values.astype(float) / np.maximum(
            np.cos(np.deg2rad(_solar_geometry(lat, lon, tz_hours, out.index)[0])), 1e-3
        )
    else:
        zen, _ = _solar_geometry(lat, lon, tz_hours, out.index)
        diffuse_h, dni = erbs_split(ghi, zen)
        out["diffuse_radiation"] = diffuse_h
    zen, sol_az = _solar_geometry(lat, lon, tz_hours, out.index)
    zen_r, sol_az_r = np.deg2rad(zen), np.deg2rad(sol_az)
    tilt_r, surf_az_r = np.deg2rad(tilt), np.deg2rad(azimuth)
    cos_inc = np.sin(zen_r) * np.cos(surf_az_r - sol_az_r) * np.sin(tilt_r) + np.cos(
        zen_r
    ) * np.cos(tilt_r)
    cos_inc = np.clip(cos_inc, 0.0, None)
    cos_z = np.clip(np.cos(zen_r), 1e-3, 1.0)
    # Beam (POA)
    beam_poa = dni * cos_inc
    # Diffuse: isotropic sky model only (no Hay/horizon-brightening term, P6-8)
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
    timeout: float = 120.0,
) -> pd.DataFrame:
    """Fetch (and cache) hourly weather for a calendar year.

    When ``city`` is provided and a pre-downloaded CSV exists in
    ``data/weather/{city}_{year}.csv`` (relative to project root), it is
    loaded directly without any API call.  Falls back to Open-Meteo if
    the local file is not found.
    """
    cache_dir = Path(cache_dir) if cache_dir else Path("weather_cache")
    cp = _cache_path(cache_dir, lat, lon, year, tilt, azimuth, tz_hours)
    lp = _legacy_cache_path(cache_dir, lat, lon, year)

    # ── City-based local CSV (no API) ──
    if city:
        local = _find_city_csv(city, year)
        if local is not None:
            # P6-10: pre-downloaded data/weather/{city}_{year}.csv carry a
            # "+00:00" suffix but the VALUES are local wall-clock time (GHI
            # peaks at local hour 12).  The engine consumes the index via
            # wall-clock fields (index.hour/month/day), so this is internally
            # consistent; the "+00:00" label is a misleading legacy of the
            # download step — treat the index as local wall time.
            df = pd.read_csv(local, parse_dates=["timestamp"])
            df = df.set_index("timestamp")
            if "poa_radiation" not in df.columns:
                df = add_poa(df, tilt, azimuth, lat, lon, tz_hours)
            # Also write to the standard cache so subsequent calls hit quickly
            if not cp.exists():
                cache_dir.mkdir(parents=True, exist_ok=True)
                df.to_csv(cp)
            return df

    # ── Standard lat/lon cache (tilt-aware key with legacy fallback, P6-1) ──
    if (cp.exists() or lp.exists()) and not force:
        legacy = not cp.exists()
        path = lp if legacy else cp
        df = pd.read_csv(path, parse_dates=["timestamp"])
        df = df.set_index("timestamp")
        # P4-16: stale-cache detection — caches written before the local-year
        # alignment fix are shifted by tz_hours (missing Jan 1 00-07h local,
        # carrying phantom hours of the next year).  If the window is not
        # aligned to the local calendar year, regenerate below.
        expected_n = (365 + int(calendar.isleap(year))) * 24
        aligned = (
            len(df) > 0
            and df.index[0] == pd.Timestamp(f"{year}-01-01 00:00:00")
            and len(df) == expected_n
        )
        if aligned:
            if "poa_radiation" not in df.columns:
                df = add_poa(df, tilt, azimuth, lat, lon, tz_hours)
            elif legacy:
                # P6-1: legacy cache is keyed on lat/lon/year only, so its POA
                # may have been computed for a different tilt/azimuth/tz.
                # Recompute from GHI (Erbs split) so the returned POA honours
                # the requested geometry; the API's original horizontal
                # direct/diffuse are not recoverable from a POA-ised cache.
                warnings.warn(
                    f"Legacy weather cache {path} does not encode tilt/azimuth/"
                    f"tz; recomputing poa_radiation for tilt={tilt}, "
                    f"azimuth={azimuth}, tz_hours={tz_hours} from GHI.",
                    stacklevel=2,
                )
                df = df.drop(columns=["poa_radiation", "direct_radiation", "diffuse_radiation"])
                df = add_poa(df, tilt, azimuth, lat, lon, tz_hours)
            return df
        # Pre-fix cache (window shifted by tz_hours): keep it as an offline
        # fallback and regenerate below when the network is available.
        fallback_df = df
        warnings.warn(
            f"Stale weather cache {path} is not aligned to the local calendar "
            f"year (pre-P4-16 format); re-fetching.",
            stacklevel=2,
        )

    if not _HAS_REQUESTS and not _HAS_PYODIDE:
        raise WeatherFetchError(
            "The 'requests' package is required to fetch weather from "
            "Open-Meteo. Install it or provide a cached CSV."
        )

    # One extra day on each side so the tz-shifted data still covers the full
    # local year [year-01-01 00:00, (year+1)-01-01 00:00) for any |tz_hours|<24
    # (P4-16).  Open-Meteo accepts dates beyond the requested archive window.
    start = date(year - 1, 12, 31).isoformat()
    end = date(year + 1, 1, 2).isoformat()
    url = OPEN_METEO_FCST if use_forecast else OPEN_METEO_URL
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start,
        "end_date": end,
        "hourly": (
            "temperature_2m,relative_humidity_2m,surface_pressure,"
            "shortwave_radiation,direct_radiation,diffuse_radiation"
        ),
        "timezone": "UTC",
        "wind_speed_unit": "ms",
    }

    # P7-6: long first-run fetches (up to ~2 min) print a progress line so the
    # user is not staring at a silent 120 s.
    print(
        f"Fetching weather for lat={lat:.3f}, lon={lon:.3f}, "
        f"year={year} from Open-Meteo (timeout={timeout:.0f}s)...",
        flush=True,
    )
    try:
        if _HAS_REQUESTS:
            resp = requests.get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()["hourly"]
        else:
            # Pyodide fallback: use browser-native HTTP via open_url.
            # open_url returns the body as a file-like object; non-2xx raises.
            import json as _json
            from urllib.parse import urlencode

            full_url = f"{url}?{urlencode(params)}"
            try:
                body = _py_open_url(full_url).read()
            except Exception as e:
                raise WeatherFetchError(f"Weather API request failed: {e}") from e
            data = _json.loads(body)["hourly"]
    except WeatherFetchError:
        # Already wrapped inside the pyodide block — re-raise unchanged.
        raise
    except Exception as e:
        # P4-16 offline fallback: if a pre-fix (shifted-window) cache exists and
        # the re-fetch fails (no network), reuse it with a warning rather than
        # aborting — the tz-shift only costs the first 8 hours of Jan 1.
        fb = locals().get("fallback_df")
        if fb is not None:
            warnings.warn(
                f"Weather re-fetch failed ({e}); reusing stale pre-P4-16 cache "
                f"{path} (local calendar offset by tz_hours={tz_hours}).",
                stacklevel=2,
            )
            if "poa_radiation" not in fb.columns:
                fb = add_poa(fb, tilt, azimuth, lat, lon, tz_hours)
            else:
                # P6-1: stale legacy POA geometry is unknown — recompute from
                # GHI so the offline fallback still honours the requested
                # tilt/azimuth (pure numpy, no network needed).
                fb = fb.drop(columns=["poa_radiation", "direct_radiation", "diffuse_radiation"])
                fb = add_poa(fb, tilt, azimuth, lat, lon, tz_hours)
            return fb
        raise WeatherFetchError(
            f"weather fetch failed: {e}. Check network connectivity or "
            f"provide a cached/offline weather CSV."
        ) from e
    df = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(data["time"], utc=True),
            "temperature_2m": data["temperature_2m"],
            "relative_humidity_2m": data["relative_humidity_2m"],
            "surface_pressure": data.get("surface_pressure", [101.325] * len(data["time"])),
            "shortwave_radiation": data.get("shortwave_radiation", [0] * len(data["time"])),
            "direct_radiation": data.get("direct_radiation", [0] * len(data["time"])),
            "diffuse_radiation": data.get("diffuse_radiation", [0] * len(data["time"])),
        }
    )
    # Convert to local time as a fixed-offset zone, then align to the local
    # calendar year (P4-16).  tz_convert(None) would keep the UTC wall clock;
    # only tz_localize(None) keeps the local wall clock for the naive cache.
    # P6-10: fixed offset tz_hours — no DST.  China (UTC+8) has no DST, so a
    # constant offset is exact for all project presets; for DST-observing
    # locales this simplified model is off by +/-1 h across DST transitions
    # (accepted limitation — do not apply pytz/zoneinfo DST rules here).
    tz = timezone(timedelta(hours=tz_hours))
    df["timestamp"] = df["timestamp"].dt.tz_convert(tz)
    df = df.set_index("timestamp")
    lo = pd.Timestamp(f"{year}-01-01 00:00:00", tz=tz)
    hi = pd.Timestamp(f"{year + 1}-01-01 00:00:00", tz=tz)
    df = df[(df.index >= lo) & (df.index < hi)]
    df.index = df.index.tz_localize(None)  # naive local wall time (cache format)
    df = add_poa(df, tilt, azimuth, lat, lon, tz_hours)
    df.to_csv(cp)
    return df
