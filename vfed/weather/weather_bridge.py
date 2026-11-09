"""
Weather bridge — fetches meteorology from Open-Meteo or NASA POWER for an
arbitrary site and prepares it for the building + PV simulations.

The exit contract is a UNIFORM TIMESTEP GRID: strictly increasing naive
local wall-clock timestamps with one constant integer-second step (3600 s
today; 900 s or 1800 s sub-hourly grids validate identically) that covers
the requested local calendar year.  ``to_hourly`` aggregates any such grid
to the hourly rows consumed by the report and PV layers, and hourly input
passes through bit-identically (dual view: native resolution for the
building loop, hourly aggregation for the annual reports).

Outputs a tidy DataFrame with the columns consumed downstream:

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
import io
import warnings
from datetime import date, timedelta, timezone
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlsplit

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

# Round 22: NASA POWER hourly point API (keyless, no quota).  The four
# parameters map 1:1 onto the weather contract columns; ALLSKY_SFC_SW_DWN
# is hourly Wh/m^2, numerically equal to the mean W/m^2 over the hour, and
# is used as shortwave_radiation WITHOUT any x3600 conversion.
NASA_POWER_URL = "https://power.larc.nasa.gov/api/temporal/hourly/point"
NASA_POWER_PARAMS = "T2M,RH2M,WS10M,ALLSKY_SFC_SW_DWN"

# Provider vocabulary (single source of truth for the fetcher, the config
# guard and the CLI override).
WEATHER_PROVIDERS = ("open-meteo", "nasa-power")

# T3 (wave-1): the minimum column set every exit path must deliver.  It is
# the intersection of what the two live providers return and what the
# pre-downloaded city files carry; direct/diffuse/poa are added downstream
# by add_poa and are therefore not part of this base contract.
REQUIRED_WEATHER_COLUMNS = ("temperature_2m", "relative_humidity_2m", "shortwave_radiation")

# Integer-nanosecond helpers for the grid contract (ns keep exact int64
# arithmetic on DatetimeIndex.asi8 without float rounding).
_NS_PER_SECOND = 1_000_000_000
_NS_PER_HOUR = 3_600_000_000_000


def _index_ns(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Normalize a DatetimeIndex to nanosecond resolution for asi8 math.

    pandas 3 changed the default datetime64 unit from nanoseconds to
    microseconds, so raw ``asi8`` integers no longer mean ns there and
    the ``_NS_PER_*`` comparisons below would see timesteps 1000x too
    small.  Converting us/s -> ns is lossless.  pandas 1.x has no
    ``.unit`` attribute but already defaults to ns, so the getattr
    fallback keeps this a no-op on the minimum supported version.
    """
    if getattr(index, "unit", "ns") != "ns":
        index = index.as_unit("ns")
    return index


# G2 (Wave 1): POA transposition-model vocabulary (single source of truth
# for add_poa, fetch_weather and the SiteConfig field).  "isotropic" is the
# legacy pre-G2 sky model; "hay_davies" adds the Hay & Davies (1980)
# anisotropic sky.
TRANSPOSITION_MODELS = ("isotropic", "hay_davies")

# G2: total solar irradiance reference value (W/m^2) used for the
# extraterrestrial normal irradiance in the Hay-Davies anisotropy index.
# Open data: Gueymard (2018), Sol. Energy 168, 2-23 (TSI ~1361 W/m^2);
# ISO 21348.  (erbs_split keeps its own 1367 W/m^2 clearness-index constant
# untouched -- the legacy bitstream depends on it.)
SOLAR_CONSTANT_WM2 = 1361.0


def _extraterrestrial_normal(doy: np.ndarray) -> np.ndarray:
    """Extraterrestrial NORMAL irradiance D_on (W/m^2) per day of year.

    Duffie & Beckman, "Solar Engineering of Thermal Processes", 4th ed.,
    eq. 1.4.1:  D_on = G_sc * (1 + 0.033 * cos(360*n/365)), n = day of
    year, G_sc = 1361 W/m^2 (see SOLAR_CONSTANT_WM2).
    """
    doy = np.asarray(doy, dtype=float)
    return SOLAR_CONSTANT_WM2 * (1.0 + 0.033 * np.cos(np.deg2rad(360.0 * doy / 365.0)))


def _validate_transposition_args(albedo: float, transposition: str) -> None:
    """G2 fail-fast guard shared by ``add_poa`` and ``fetch_weather``.

    Mirrors the SiteConfig contract (TRANSPOSITION_MODELS whitelist; the
    ``albedo`` HARD_LIMIT band [0, 1] in design/project.py) so an invalid
    model name or reflectance fails at the entry point instead of after a
    full-year network fetch (or silently producing a negative ground term).
    """
    if transposition not in TRANSPOSITION_MODELS:
        raise ValueError(
            "transposition must be one of isotropic|hay_davies, got " f"{transposition!r}."
        )
    if isinstance(albedo, bool) or not isinstance(albedo, (int, float)):
        raise ValueError(
            "albedo must be a number (ground reflectance in [0, 1]), got "
            f"{type(albedo).__name__}: {albedo!r}"
        )
    if not (0.0 <= float(albedo) <= 1.0):
        raise ValueError(f"albedo must be within [0, 1] (ground reflectance), got {albedo}.")


class WeatherFetchError(Exception):
    """Raised when weather data cannot be acquired (error code E003).

    Covers missing 'requests', transport failures, and non-2xx API
    responses — anything that prevents a full year of weather from being
    produced.  The CLI maps this exception to ``[ERROR E003]``.
    """


__all__ = [
    "fetch_weather",
    "add_poa",
    "erbs_split",
    "to_hourly",
    "validate_weather_grid",
    "WeatherFetchError",
    "REQUIRED_WEATHER_COLUMNS",
    "TRANSPOSITION_MODELS",
]


# ---------------------------------------------------------------------------
# T3 (wave-1): unified timestep-grid contract.
#
# The pre-T3 bridge hard-required exactly 8760/8784 HOURLY rows at every
# exit.  The contract is now a UNIFORM timestep grid of any integer-second
# step (3600 s, 1800 s, 900 s, ...) that tiles the requested window; the
# hourly behaviour is unchanged (an hourly grid is the 3600 s special case
# and every hourly message stays byte-identical).  Two public entry points
# carry the contract:
#
#   validate_weather_grid(df, year, context) -- fail-fast validation with
#       the first offending row index in every diagnostic.
#   to_hourly(df) -- aggregate any sub-hourly grid to hourly rows (arithmetic
#       mean per column, timestamps at hour start); an hourly input returns
#       a bitwise-identical copy.
# ---------------------------------------------------------------------------


def _window_seconds(year: int) -> int:
    """Length of *year* in seconds (365 or 366 days, no leap seconds)."""
    days = 365 + int(calendar.isleap(year))
    return days * 86400


def _grid_step_seconds(index: pd.DatetimeIndex) -> Optional[int]:
    """Lenient step probe used only for cache-hit ROUTING decisions.

    Returns the constant integer-second step of *index* when the grid is
    uniform, otherwise ``None``.  A ``None`` result routes the caller down
    its existing misaligned-cache path (stale-cache warning + refetch), so
    this helper must never raise on malformed input.
    """
    if not isinstance(index, pd.DatetimeIndex) or len(index) < 2:
        return None
    index = _index_ns(index)
    deltas = np.diff(index.asi8)
    d0 = int(deltas[0])
    if d0 <= 0 or d0 % _NS_PER_SECOND != 0 or np.any(deltas != d0):
        return None
    return d0 // _NS_PER_SECOND


def _uniform_step_seconds(df: pd.DataFrame, context: str) -> int:
    """Return the constant integer-second step of the frame's DatetimeIndex.

    Raises ``WeatherFetchError`` with the FIRST offending row index for
    every violation class: not a DatetimeIndex, tz-aware stamps, an empty
    frame, fewer than two rows, non-increasing stamps, a non-constant
    step, and a step that is not a whole number of seconds.
    """
    index = _index_ns(df.index)
    if not isinstance(index, pd.DatetimeIndex):
        raise WeatherFetchError(
            f"{context}: weather data must be timestamp-indexed, got a "
            f"{type(index).__name__} index."
        )
    if index.tz is not None:
        raise WeatherFetchError(
            f"{context}: weather stamps carry a timezone ({index.tz}); the "
            "grid contract works on naive local wall time."
        )
    if len(index) == 0:
        raise WeatherFetchError(f"{context}: weather data contains 0 rows.")
    if len(index) == 1:
        raise WeatherFetchError(
            f"{context}: weather data contains 1 row; a timestep is " "undefined below two rows."
        )
    deltas = np.diff(index.asi8)
    bad = np.nonzero(deltas <= 0)[0]
    if len(bad):
        i = int(bad[0])
        raise WeatherFetchError(
            f"{context}: timestamps are not strictly increasing at row "
            f"{i + 1} ({index[i]} -> {index[i + 1]})."
        )
    d0 = int(deltas[0])
    if np.any(deltas != d0):
        bad = np.nonzero(deltas != d0)[0]
        i = int(bad[0])
        actual = int(deltas[i]) / _NS_PER_SECOND
        raise WeatherFetchError(
            f"{context}: timestep is not constant at row {i + 1} "
            f"(step {d0 / _NS_PER_SECOND:g} s so far, then "
            f"{actual:g} s to {index[i + 1]})."
        )
    if d0 % _NS_PER_SECOND != 0:
        raise WeatherFetchError(
            f"{context}: timestep {d0 / _NS_PER_SECOND:g} s is not a whole "
            "number of seconds; the grid contract needs integer-second steps."
        )
    return d0 // _NS_PER_SECOND


def validate_weather_grid(
    df: pd.DataFrame, year: int, context: str, *, strict_window: bool = True
) -> int:
    """Validate the unified exit contract and return the step in seconds.

    Checks, in order: the three required columns are present, the stamp
    index is a strictly increasing uniform integer-second grid (via
    ``_uniform_step_seconds``), and — with ``strict_window=True`` — the
    grid exactly covers the local-year window
    ``[year-01-01 00:00, (year+1)-01-01 00:00)``.  Every violation raises
    ``WeatherFetchError`` naming the first offending row.

    ``strict_window=False`` keeps the city-file behaviour of tolerating a
    shifted or short window (the pinned warn-and-use-as-is path) while
    still raising on broken grids.
    """
    missing = [c for c in REQUIRED_WEATHER_COLUMNS if c not in df.columns]
    if missing:
        raise WeatherFetchError(
            f"{context}: weather data is missing required column(s) "
            f"{', '.join(missing)}; the contract needs all of "
            f"{', '.join(REQUIRED_WEATHER_COLUMNS)}."
        )
    step_s = _uniform_step_seconds(df, context)
    if not strict_window:
        return step_s
    start = pd.Timestamp(year=year, month=1, day=1)
    end = start + pd.Timedelta(seconds=_window_seconds(year))
    index = df.index
    if index[0] != start:
        raise WeatherFetchError(
            f"{context}: window starts at row 0 with {index[0]}, expected "
            f"{start} local wall time."
        )
    expected_n = _window_seconds(year) // step_s
    covered = index[-1] + pd.Timedelta(seconds=step_s)
    if covered != end:
        raise WeatherFetchError(
            f"{context}: window ends at row {len(index) - 1} "
            f"({len(index)} rows of {step_s} s, covering through "
            f"{covered}), expected {expected_n} rows covering through "
            f"{end}; refusing a partial year."
        )
    return step_s


def to_hourly(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate a uniform sub-hourly grid to hourly rows; hourly in = identical out.

    Each column becomes the arithmetic mean of the rows inside its hour
    and the hourly stamps sit at hour starts.  A frame that is already
    hourly is returned as a bitwise-identical copy (values, dtypes and
    ``attrs`` preserved) — downstream hourly consumers see zero change.
    """
    step_s = _uniform_step_seconds(df, "to_hourly")
    if 3600 % step_s != 0:
        raise WeatherFetchError(
            f"to_hourly: timestep {step_s} s does not divide one hour; "
            "rows cannot be aggregated to whole hours."
        )
    index = _index_ns(df.index)
    if int(index.asi8[0]) % _NS_PER_HOUR != 0:
        raise WeatherFetchError(
            f"to_hourly: first stamp {index[0]} is not anchored on the "
            "hour; hourly aggregation needs hour-aligned windows."
        )
    n_sub = 3600 // step_s
    if len(index) % n_sub != 0:
        raise WeatherFetchError(
            f"to_hourly: {len(index)} rows of {step_s} s do not tile whole "
            f"hours ({len(index)} % {n_sub} = {len(index) % n_sub} rows "
            "left over)."
        )
    if n_sub == 1:
        return df.copy()
    out = df.iloc[::n_sub].copy()
    for name in df.columns:
        out[name] = df[name].to_numpy().reshape(-1, n_sub).mean(axis=1)
    out.attrs = dict(df.attrs)
    return out


# ---------------------------------------------------------------------------
# user12 T5: legacy-cache POA-recompute notice -- issued at most ONCE per
# process.  A 100-row sweep previously repeated the same UserWarning for
# every enumerated configuration, each line attributed to the engine's
# fetch call site (a filesystem path like "G:\\...\\engine.py:521").
# warn_explicit keeps the attribution trailer free of any caller source
# path; the message names the cache file and the exact refetch action.
# ---------------------------------------------------------------------------
_LEGACY_CACHE_NOTICE_KEY = "legacy-weather-cache-poa"
_LEGACY_CACHE_NOTICE_SENT: set = set()


def _notify_legacy_cache_once(path, tilt: float, azimuth: float, tz_hours: float) -> None:
    """Warn once per process that *path* is a pre-P6-1 legacy cache whose
    POA components are being recomputed for the requested geometry."""
    if _LEGACY_CACHE_NOTICE_KEY in _LEGACY_CACHE_NOTICE_SENT:
        return
    _LEGACY_CACHE_NOTICE_SENT.add(_LEGACY_CACHE_NOTICE_KEY)
    warnings.warn_explicit(
        f"Legacy weather cache '{Path(path).name}' does not encode tilt/"
        f"azimuth/tz; recomputing poa_radiation for tilt={tilt}, "
        f"azimuth={azimuth}, tz_hours={tz_hours} from GHI. Shown once per "
        f"run. Delete the file to refetch a geometry-aware cache.",
        UserWarning,
        "vfed.weather_bridge",
        0,
    )


def _cache_path(
    cache_dir: Path,
    lat: float,
    lon: float,
    year: int,
    tilt: float = 20.0,
    azimuth: float = 180.0,
    tz_hours: float = 8.0,
    provider: str = "open-meteo",
    albedo: float = 0.2,
    transposition: str = "isotropic",
) -> Path:
    """Tilt-aware cache key — POA depends on (tilt, azimuth, tz_hours).

    Round 22: non-default providers append a source tag (``_power``) so the
    same coordinates never mix ERA5 and POWER data in one file — the two
    reanalyses differ by a few W/m^2/W/K everywhere, and a silent cross-hit
    would be invisible in every downstream KPI.

    G2 (Wave 1) backward compatibility: non-default transposition parameters
    (``albedo != 0.2`` or ``transposition != "isotropic"``) append an
    ``_r{albedo:.3f}_m{model}`` tag, so a POA field computed with a
    different ground reflectance / sky model never cross-hits a
    default-parameter cache.  With the defaults the filename is
    byte-identical to the pre-G2 name — every existing cache file keeps
    hitting (no refetch, no network).
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    suffix = "" if provider == "open-meteo" else "_power"
    if albedo != 0.2 or transposition != "isotropic":
        suffix += f"_r{albedo:.3f}_m{transposition}"
    return cache_dir / (
        f"weather_{lat:.3f}_{lon:.3f}_{year}"
        f"_t{tilt:.3f}_a{azimuth:.3f}_z{tz_hours:.3f}{suffix}.csv"
    )


def _legacy_cache_path(cache_dir: Path, lat: float, lon: float, year: int) -> Path:
    """Pre-P6-1 geometry-independent cache name (kept readable)."""
    return cache_dir / f"weather_{lat:.3f}_{lon:.3f}_{year}.csv"


def _find_city_csv(
    city: str,
    year: int,
    provider: str = "open-meteo",
    root: Optional[Path] = None,
) -> Optional[Path]:
    """Search for a pre-downloaded city weather CSV.

    Checks ``data/weather/{city}_{year}.csv`` relative to the project root
    (``vfed`` package parent).  Returns ``None`` if the file does not exist.

    Round 22: ``provider="nasa-power"`` looks for ``{city}_{year}_power.csv``
    instead — city files are source-specific, exactly like the lat/lon cache
    key.  *root* is injectable for tests.
    """
    # Project root = directory containing vfed/
    base = Path(root) if root is not None else Path(__file__).resolve().parent.parent.parent
    suffix = "" if provider == "open-meteo" else "_power"
    candidate = base / "data" / "weather" / f"{city}_{year}{suffix}.csv"
    if candidate.exists():
        return candidate
    return None


def _solar_geometry(
    lat: float, lon: float, tz_hours: float, dt: pd.DatetimeIndex
) -> Tuple[np.ndarray, np.ndarray]:
    """Return solar zenith and azimuth (degrees) for each timestamp."""
    lat_r = np.deg2rad(lat)
    doy = dt.day_of_year.values
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
    albedo: float = 0.2,
    transposition: str = "isotropic",
) -> pd.DataFrame:
    """Add ``poa_radiation`` (and overwrite direct/diffuse as POA components).

    ``transposition="isotropic"`` (default, legacy): beam
    (``dni * cos(incidence)``) + isotropic diffuse (``(1 + cos(tilt))/2``
    sky view factor) + isotropic ground reflection
    (``albedo * GHI * (1 - cos(tilt))/2``).  With the default arguments
    the output is bit-identical to the pre-G2 implementation, whose
    hard-coded ground reflectance was 0.2.  No horizon brightening is
    applied (P6-8).

    ``transposition="hay_davies"`` (G2, Wave 1): Hay & Davies (1980)
    anisotropic sky (Duffie & Beckman, "Solar Engineering of Thermal
    Processes", 4th ed., eq. 2.16.7).  The sky diffuse becomes
    ``DHI * [(1 - AI) * (1 + cos(tilt))/2 + AI * Rb]`` where
    ``AI = DNI/D_on`` is the anisotropy index (the circumsolar fraction of
    the diffuse; ``D_on`` = extraterrestrial normal irradiance, eq. 1.4.1,
    solar constant 1361 W/m^2) and ``Rb = cos(incidence)/cos(zenith)`` is
    the beam projection ratio (both cosines clipped exactly like the beam
    term, so circumsolar radiation behind the plane is zero).  Overcast
    hours (``DNI -> 0`` hence ``AI -> 0``) reduce the model to the
    isotropic formulation.  Solar constant per the TSI reference value
    (Gueymard 2018, Sol. Energy 168; ISO 21348, open data).

    ``albedo`` is the ground reflectance in [0, 1] (the same band as the
    ``albedo`` HARD_LIMIT in design/project.py); ``albedo=0`` makes the
    ground-reflected term exactly zero.
    """
    _validate_transposition_args(albedo, transposition)
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
    # Diffuse sky on the plane.  The isotropic branch keeps the legacy
    # expression and operand order verbatim, so the default-parameter
    # bitstream is unchanged (golden test 31).
    iso_view = (1 + np.cos(tilt_r)) / 2.0
    if transposition == "hay_davies":
        # Hay & Davies 1980 (Duffie & Beckman 4th ed., eq. 2.16.7): the
        # circumsolar share AI of the diffuse arrives from the sun's
        # direction (projection ratio Rb), the isotropic share (1 - AI)
        # from the sky dome.  AI is clipped to [0, 1]: DNI > D_on can only
        # happen from Erbs-split edge cases near the horizon.
        d_on = _extraterrestrial_normal(out.index.day_of_year.values)
        ai = np.clip(dni / d_on, 0.0, 1.0)
        rb = cos_inc / cos_z
        diffuse_poa = diffuse_h * ((1.0 - ai) * iso_view + ai * rb)
    else:
        diffuse_poa = diffuse_h * iso_view
    # Ground reflected
    ground = albedo * ghi * (1 - np.cos(tilt_r)) / 2.0
    poa = np.clip(beam_poa + diffuse_poa + ground, 0.0, None)
    out["poa_radiation"] = poa
    # Re-express direct/diffuse as POA components (their sum = POA).
    out["direct_radiation"] = beam_poa
    out["diffuse_radiation"] = diffuse_poa + ground
    return out


# Round 22: radiation columns scaled together by ghi_scale.  Scaling the
# whole radiation field (GHI + beam/diffuse/POA components) proportionally
# keeps the sky partition fixed and makes POA / PV / annual GHI downstream
# scale by exactly the same factor.
_RADIATION_COLS = ("shortwave_radiation", "direct_radiation", "diffuse_radiation", "poa_radiation")


def _apply_ghi_scale(df: pd.DataFrame, ghi_scale: float) -> pd.DataFrame:
    """Apply the GHI bias-correction multiplier at the weather-df exit.

    Thinnest possible layer (round 22): called at EVERY return point of
    ``fetch_weather``, after the cache write — the on-disk cache always
    stores UNSCALED provider values, so changing ghi_scale never
    invalidates or poisons a cache entry.  ``ghi_scale == 1.0`` (the
    default) multiplies nothing — the default path is bitwise unchanged.
    The effective value is always recorded in ``attrs["ghi_scale"]``
    (self-evidence, incl. the 1.0 no-op).
    """
    if ghi_scale != 1.0:
        for col in _RADIATION_COLS:
            if col in df.columns:
                df[col] = df[col] * ghi_scale
    df.attrs["ghi_scale"] = ghi_scale
    return df


def _parse_power_csv(text: str) -> pd.DataFrame:
    """Parse a NASA POWER hourly point CSV response.

    Format: a ``-BEGIN HEADER-`` .. ``-END HEADER-`` prologue (13 lines in
    practice, but located by marker — never by count), then a
    ``YEAR,MO,DY,HR,<params>`` UTC grid.  Returns a UTC-indexed DataFrame
    with the weather-contract column names:

        T2M -> temperature_2m (deg C)
        RH2M -> relative_humidity_2m (%)
        WS10M -> wind_speed_10m (m/s)
        ALLSKY_SFC_SW_DWN -> shortwave_radiation (Wh/m^2 per hour ==
                             mean W/m^2 over the hour, used as-is)

    Fail-fast: any ``-999`` fill value or missing entry in ANY variable of
    ANY row raises ``WeatherFetchError`` — a partially filled year would
    silently poison the 8760-hour ODE integration (no-hardcoded-science /
    no silent gap-filling).
    """
    lines = text.splitlines()
    try:
        end_hdr = next(i for i, ln in enumerate(lines) if ln.strip() == "-END HEADER-")
    except StopIteration:
        raise WeatherFetchError(
            "NASA POWER response has no '-END HEADER-' marker (unexpected "
            "format or an error page); refusing to guess the data block."
        ) from None
    data_start = end_hdr + 1
    raw = pd.read_csv(io.StringIO("\n".join(lines[data_start:])))
    required = ["YEAR", "MO", "DY", "HR", "T2M", "RH2M", "WS10M", "ALLSKY_SFC_SW_DWN"]
    missing = [c for c in required if c not in raw.columns]
    if missing:
        raise WeatherFetchError(
            f"NASA POWER response is missing columns {missing} "
            f"(got {list(raw.columns)}); check the parameters/ URL."
        )
    ts = pd.to_datetime(
        dict(year=raw["YEAR"], month=raw["MO"], day=raw["DY"], hour=raw["HR"]), utc=True
    )
    vals = raw[["T2M", "RH2M", "WS10M", "ALLSKY_SFC_SW_DWN"]].apply(pd.to_numeric, errors="coerce")
    bad = (vals == -999) | vals.isna()
    if bad.to_numpy().any():
        rows = np.nonzero(bad.any(axis=1).to_numpy())[0]
        first = ts.iloc[int(rows[0])].strftime("%Y-%m-%dT%H:%MZ")
        raise WeatherFetchError(
            f"NASA POWER returned {len(rows)} row(s) with the -999 fill value "
            f"or missing data (first at {first}); refusing a partially "
            f"filled year. Narrow the year window or retry later."
        )
    return pd.DataFrame(
        {
            "timestamp": ts,
            "temperature_2m": vals["T2M"].to_numpy(dtype=float),
            "relative_humidity_2m": vals["RH2M"].to_numpy(dtype=float),
            "wind_speed_10m": vals["WS10M"].to_numpy(dtype=float),
            "shortwave_radiation": vals["ALLSKY_SFC_SW_DWN"].to_numpy(dtype=float),
        }
    )


def _stale_cache_fallback(
    fb: pd.DataFrame,
    path: Path,
    err: Exception,
    tilt: float,
    azimuth: float,
    lat: float,
    lon: float,
    tz_hours: float,
    albedo: float = 0.2,
    transposition: str = "isotropic",
) -> pd.DataFrame:
    """P4-16 offline fallback: reuse a pre-fix (shifted-window) cache when
    the re-fetch fails (no network) rather than aborting — the tz-shift
    only costs the first tz_hours hours of Jan 1.  Shared by the
    Open-Meteo and NASA POWER fetch branches (identical semantics).
    G2: ``albedo``/``transposition`` pass through to add_poa (the stale
    cache's POA columns are dropped and recomputed from GHI anyway)."""
    warnings.warn(
        f"Weather re-fetch failed ({err}); reusing stale pre-P4-16 cache "
        f"{path} (local calendar offset by tz_hours={tz_hours}).",
        stacklevel=3,
    )
    if "poa_radiation" not in fb.columns:
        fb = add_poa(fb, tilt, azimuth, lat, lon, tz_hours, albedo, transposition)
    else:
        # P6-1: stale legacy POA geometry is unknown — recompute from
        # GHI so the offline fallback still honours the requested
        # tilt/azimuth (pure numpy, no network needed).
        fb = fb.drop(columns=["poa_radiation", "direct_radiation", "diffuse_radiation"])
        fb = add_poa(fb, tilt, azimuth, lat, lon, tz_hours, albedo, transposition)
    # P2-2: provenance metadata (offline stale-cache fallback).
    fb.attrs["weather_source"] = "cache"
    fb.attrs["weather_source_detail"] = f"{path.name} (stale pre-P4-16)"
    return fb


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
    provider: str = "open-meteo",
    ghi_scale: float = 1.0,
    albedo: float = 0.2,
    transposition: str = "isotropic",
) -> pd.DataFrame:
    """Fetch (and cache) hourly weather for a calendar year.

    When ``city`` is provided and a pre-downloaded CSV exists in
    ``data/weather/{city}_{year}.csv`` (relative to project root), it is
    loaded directly without any API call.  Falls back to the provider's
    live API if the local file is not found.

    Round 22: ``provider`` selects the source — ``"open-meteo"`` (default;
    ERA5 archive, unchanged behaviour) or ``"nasa-power"`` (NASA POWER
    hourly, MERRA-2/CERES).  The provider namespaces BOTH the lat/lon cache
    file (``..._z8.000_power.csv``) and the city file
    (``{City}_{year}_power.csv``) so the two reanalyses never mix.
    ``ghi_scale`` (default 1.0) multiplies the radiation field at the df
    exit — see ``_apply_ghi_scale``; the cache itself always stores
    unscaled provider values.

    G2 (Wave 1): ``albedo`` (ground reflectance, default 0.2) and
    ``transposition`` (``"isotropic"`` | ``"hay_davies"``, default
    ``"isotropic"``) pass through to ``add_poa`` — see its docstring.
    Defaults keep every output bit-identical to the pre-G2 fetch and keep
    hitting the existing (untagged) cache keys; non-default values append
    an ``_r{albedo}_m{model}`` tag to the cache filename (see
    ``_cache_path``), so the two parameterisations never cross-hit.
    """
    if provider not in WEATHER_PROVIDERS:
        raise WeatherFetchError(f"provider must be one of {WEATHER_PROVIDERS}, got {provider!r}.")
    # G2: fail fast BEFORE any network fetch or cache bookkeeping (an
    # invalid model name found only inside add_poa would waste a
    # full-year API call first).
    _validate_transposition_args(albedo, transposition)
    cache_dir = Path(cache_dir) if cache_dir else Path("weather_cache")

    # ── City-based local CSV (no API) ──
    # user12 P2-5: resolved BEFORE any lat/lon cache bookkeeping and returned
    # immediately -- a city hit must not write a lat/lon cache entry behind
    # the user's back.  The pre-downloaded city file IS the offline source;
    # its provenance is allowed to diverge from the lat/lon cache (P1-3b),
    # and silently materialising one would blur the two.
    if city:
        local = _find_city_csv(city, year, provider=provider)
        if local is not None:
            df = pd.read_csv(local, parse_dates=["timestamp"])
            df = df.set_index("timestamp")
            # P1-3b: pre-downloaded city files carry a legacy "+00:00" suffix
            # (P6-10) but the VALUES are local wall-clock time (GHI peaks at
            # local hour 12).  Strip the misleading UTC label so the index is
            # naive local wall time — the same convention as the P4-16 fetch
            # pipeline cache format.  Never re-zones or shifts the values.
            if len(df) > 0 and isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None:
                df.index = df.index.tz_localize(None)
            # T3: unified grid validation — a broken grid (gaps, disorder,
            # non-constant or non-integer-second step, missing columns)
            # raises with the first offending row; the window ALIGNMENT
            # (P1-3b) stays a warn-and-use-as-is decision below.
            step_s = validate_weather_grid(
                df, year, f"City weather file {local.name}", strict_window=False
            )
            # P1-3b: alignment guard (P4-16 parity for the city path).  A
            # rotated window (first row not at local Jan 1 00:00) is missing
            # the first tz_hours hours of the local year and wraps the tail
            # into the next year — warn loudly and use the file as-is (no
            # interpolation / no synthesized rows, no-hardcoded-science).
            expected_n = _window_seconds(year) // step_s
            first_ts = df.index[0]
            aligned = len(df) == expected_n and first_ts == pd.Timestamp(f"{year}-01-01 00:00:00")
            if not aligned:
                warnings.warn(
                    f"City weather file {local.name} is not aligned to the "
                    f"local calendar year {year} (first row {first_ts}, "
                    f"{len(df)} rows, expected {expected_n} rows starting "
                    f"{year}-01-01 00:00:00); "
                    "using it as-is without interpolation. Regenerate the "
                    "file from Open-Meteo for an aligned window.",
                    stacklevel=2,
                )
            if "poa_radiation" not in df.columns:
                df = add_poa(df, tilt, azimuth, lat, lon, tz_hours, albedo, transposition)
            elif albedo != 0.2 or transposition != "isotropic":
                # G2: the city file's POA was computed with the legacy
                # defaults (albedo=0.2, isotropic sky).  A non-default
                # request must not silently return those columns — drop
                # and recompute from GHI (same convention as the legacy
                # geometry-mismatch recompute below; pure numpy, no
                # network).
                df = df.drop(columns=["poa_radiation", "direct_radiation", "diffuse_radiation"])
                df = add_poa(df, tilt, azimuth, lat, lon, tz_hours, albedo, transposition)
            # P2-2: provenance metadata (in-process only; attrs never enter
            # to_csv round-trips or the JSON result schema).
            df.attrs["weather_source"] = "pre-downloaded city file"
            df.attrs["weather_source_detail"] = local.name
            return _apply_ghi_scale(df, ghi_scale)

    # ── Standard lat/lon cache (tilt-aware key with legacy fallback, P6-1) ──
    cp = _cache_path(
        cache_dir,
        lat,
        lon,
        year,
        tilt,
        azimuth,
        tz_hours,
        provider=provider,
        albedo=albedo,
        transposition=transposition,
    )
    # Round 22: the legacy (pre-P6-1) name is an Open-Meteo-era artefact —
    # a NASA POWER run must never adopt it (its POA came from ERA5 GHI).
    lp = _legacy_cache_path(cache_dir, lat, lon, year) if provider == "open-meteo" else None
    has_cp = cp.exists()
    has_lp = lp is not None and lp.exists()
    if (has_cp or has_lp) and not force:
        legacy = not has_cp
        path = lp if legacy else cp
        df = pd.read_csv(path, parse_dates=["timestamp"])
        df = df.set_index("timestamp")
        # P4-16: stale-cache detection — caches written before the local-year
        # alignment fix are shifted by tz_hours (missing Jan 1 00-07h local,
        # carrying phantom hours of the next year).  If the window is not
        # aligned to the local calendar year, regenerate below.
        # T3: the expected row count is resolution-aware (window seconds
        # over the grid step) so a future sub-hourly cache is not spuriously
        # treated as stale; today's hourly caches keep the same numbers.
        step_s = _grid_step_seconds(df.index)
        expected_n = (
            _window_seconds(year) // step_s if step_s else (365 + int(calendar.isleap(year))) * 24
        )
        aligned = (
            len(df) > 0
            and df.index[0] == pd.Timestamp(f"{year}-01-01 00:00:00")
            and len(df) == expected_n
        )
        if aligned:
            if "poa_radiation" not in df.columns:
                df = add_poa(df, tilt, azimuth, lat, lon, tz_hours, albedo, transposition)
            elif legacy:
                # P6-1: legacy cache is keyed on lat/lon/year only, so its POA
                # may have been computed for a different tilt/azimuth/tz.
                # Recompute from GHI (Erbs split) so the returned POA honours
                # the requested geometry; the API's original horizontal
                # direct/diffuse are not recoverable from a POA-ised cache.
                # user12 T5: once-per-process notice (see _notify_legacy_cache_once).
                _notify_legacy_cache_once(path, tilt, azimuth, tz_hours)
                df = df.drop(columns=["poa_radiation", "direct_radiation", "diffuse_radiation"])
                df = add_poa(df, tilt, azimuth, lat, lon, tz_hours, albedo, transposition)
            # P2-2: provenance metadata (cache hit, legacy or geometry-aware).
            df.attrs["weather_source"] = "cache"
            df.attrs["weather_source_detail"] = path.name
            return _apply_ghi_scale(df, ghi_scale)
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

    # ── NASA POWER live fetch (round 22) ──
    if provider == "nasa-power":
        # Same padded request window as the Open-Meteo branch below (one
        # extra day on each side): the P4-16 local-year slice must yield a
        # complete uniform grid covering the local year — validate_weather_grid
        # rejects any gap or shortfall before the data is cached, and the
        # cache-hit alignment guard keys on the exact window coverage, so
        # the UTC request has to over-cover |tz_hours| hours on both flanks.
        p_start = date(year - 1, 12, 31).strftime("%Y%m%d")
        p_end = date(year + 1, 1, 2).strftime("%Y%m%d")
        power_url = (
            f"{NASA_POWER_URL}?parameters={NASA_POWER_PARAMS}&community=RE"
            f"&latitude={lat}&longitude={lon}"
            f"&start={p_start}&end={p_end}&format=CSV&time-standard=UTC"
        )
        print(
            f"Fetching weather for lat={lat:.3f}, lon={lon:.3f}, "
            f"year={year} from NASA POWER (timeout={timeout:.0f}s)...",
            flush=True,
        )
        try:
            if _HAS_REQUESTS:
                resp = requests.get(power_url, timeout=timeout)
                resp.raise_for_status()
                text = resp.text
            else:
                # Pyodide fallback: browser-native HTTP via open_url (same
                # convention as the Open-Meteo branch).
                body = _py_open_url(power_url).read()
                text = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else body
        except Exception as e:
            fb = locals().get("fallback_df")
            if fb is not None:
                return _apply_ghi_scale(
                    _stale_cache_fallback(
                        fb, path, e, tilt, azimuth, lat, lon, tz_hours, albedo, transposition
                    ),
                    ghi_scale,
                )
            raise WeatherFetchError(
                f"weather fetch failed: {e}. Check network connectivity or "
                f"provide a cached/offline weather CSV."
            ) from e
        df = _parse_power_csv(text)
        # UTC -> local wall clock with the SAME fixed-offset conversion and
        # local-year slice as the Open-Meteo branch (P4-16; no DST rules —
        # see the comment there).
        tz = timezone(timedelta(hours=tz_hours))
        df["timestamp"] = df["timestamp"].dt.tz_convert(tz)
        df = df.set_index("timestamp")
        lo = pd.Timestamp(f"{year}-01-01 00:00:00", tz=tz)
        hi = pd.Timestamp(f"{year + 1}-01-01 00:00:00", tz=tz)
        df = df[(df.index >= lo) & (df.index < hi)]
        df.index = df.index.tz_localize(None)  # naive local wall time (cache format)
        # T3: unified grid validation replaces the hardcoded hourly row
        # count — the slice must still cover the full local year, and any
        # gap, disorder or non-uniform step fails fast with the offending
        # row before the result is cached.
        validate_weather_grid(df, year, "NASA POWER")
        df = add_poa(df, tilt, azimuth, lat, lon, tz_hours, albedo, transposition)
        df.to_csv(cp)
        # P2-2: provenance metadata (live NASA POWER).  Detail carries the
        # API host only — no query string (key-safe by construction).
        df.attrs["weather_source"] = "NASA POWER hourly (MERRA-2/CERES)"
        df.attrs["weather_source_detail"] = urlsplit(NASA_POWER_URL).netloc
        return _apply_ghi_scale(df, ghi_scale)

    # ── Open-Meteo live fetch (default provider) ──
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
        # P4-16 offline fallback: if a pre-fix (shifted-window) cache exists
        # and the re-fetch fails (no network), reuse it with a warning
        # rather than aborting (shared with the POWER branch).
        fb = locals().get("fallback_df")
        if fb is not None:
            return _apply_ghi_scale(
                _stale_cache_fallback(fb, path, e, tilt, azimuth, lat, lon, tz_hours),
                ghi_scale,
            )
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
    # T3: unified grid validation before add_poa and the cache write — a
    # partial or broken year fails fast here instead of being cached as a
    # silent landmine for every later run.
    validate_weather_grid(df, year, "Open-Meteo")
    df = add_poa(df, tilt, azimuth, lat, lon, tz_hours, albedo, transposition)
    df.to_csv(cp)
    # P2-2: provenance metadata (live Open-Meteo).  Detail carries the API
    # host only -- no query string, no credentials (Open-Meteo is keyless,
    # but keep the convention key-safe by construction).
    df.attrs["weather_source"] = "live fetch"
    df.attrs["weather_source_detail"] = urlsplit(url).netloc
    return _apply_ghi_scale(df, ghi_scale)
