"""
One-shot script: download 2025 hourly weather for every city in the city DB.

Run once and commit the resulting CSV files to ``data/weather/``.
The files are then consumed by ``fetch_weather(city=...)`` without any
API call at design time.

Providers (round 23):

* ``open-meteo`` (default) — ERA5 reanalysis, ``{City}_{year}.csv``.
  Behaviour is bit-identical to the pre-round-23 script.
* ``nasa-power`` — NASA POWER hourly point API (MERRA-2 meteorology +
  CERES radiation), ``{City}_{year}_power.csv``.  Downloads always go
  through ``vfed.weather.weather_bridge.fetch_weather(provider=...)``
  so the on-disk format and the -999 fill-value rejection stay in one
  place (no second HTTP implementation to drift).

Usage::

    python scripts/download_weather_db.py [--force]
    python scripts/download_weather_db.py --provider nasa-power [--force]
    python scripts/download_weather_db.py --manifest   # only (re)build MANIFEST.md
"""

import argparse
import calendar
import subprocess
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

# Append project root to sys.path so we can import vfed.*
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests
import pandas as pd

from vfed.weather.city_db import AVAILABLE_CITIES, _COORDS

OPEN_METEO_URL = "https://archive-api.open-meteo.com/v1/archive"
YEAR = 2025
OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "weather"
MANIFEST_PATH = OUT_DIR / "MANIFEST.md"

# City-file contract: exactly the columns of the pre-existing ERA5 city
# files (data/weather/{City}_{year}.csv).  POWER provides hourly GHI only,
# so direct/diffuse are written as 0.0 placeholders — at load time
# ``add_poa`` sees an all-zero beam column and re-derives direct/diffuse/
# POA from GHI (Erbs split) with the design's tilt/azimuth, keeping the
# city file geometry-neutral.
CITY_FILE_COLUMNS = (
    "temperature_2m",
    "relative_humidity_2m",
    "wind_speed_10m",
    "shortwave_radiation",
    "direct_radiation",
    "diffuse_radiation",
)


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

        df.to_csv(out_path)

        print(f"OK ({len(df)} rows)")
        return True
    except Exception as exc:
        print(f"FAIL: {exc}")
        return False


def _validate_city_df(df: pd.DataFrame, city: str) -> None:
    """Fail-fast checks for a freshly fetched POWER city frame.

    The engine's city loader rejects (or warns on) misaligned files, and a
    partial year would poison the 8760-hour ODE integration — refuse to
    write anything but a fully aligned, gap-free file.
    """
    expected_n = (365 + int(calendar.isleap(YEAR))) * 24
    if len(df) != expected_n:
        raise ValueError(f"{city}: {len(df)} rows, expected {expected_n}")
    first = df.index[0]
    if first != pd.Timestamp(f"{YEAR}-01-01 00:00:00"):
        raise ValueError(f"{city}: first row {first}, expected {YEAR}-01-01 00:00:00")
    if not (df.index.is_monotonic_increasing and df.index.is_unique):
        raise ValueError(f"{city}: timestamp index not strictly monotonic/unique")
    ghi = df["shortwave_radiation"]
    # -999 must already have been rejected per-row inside fetch_weather
    # (NASA POWER fill value); NaN in ANY column would poison the ODE.
    if ghi.isna().any() or (ghi == -999).any():
        raise ValueError(f"{city}: GHI column contains -999/NaN")
    for col in CITY_FILE_COLUMNS:
        if df[col].isna().any():
            raise ValueError(f"{city}: column {col} contains NaN")


def download_city_nasa_power(city: str, force: bool = False) -> bool:
    out_path = OUT_DIR / f"{city}_{YEAR}_power.csv"
    if out_path.exists() and not force:
        print(f"  [skip] {city} — already exists")
        return True

    coords = _COORDS.get(city)
    if coords is None:
        print(f"  [FAIL] {city} — no coordinates in _COORDS")
        return False

    lat, lon, tz = coords
    print(f"  downloading {city} [nasa-power] (lat={lat:.2f}, lon={lon:.2f})...",
          end=" ", flush=True)
    try:
        # Round 23: reuse the production fetcher — one HTTP implementation,
        # one -999 policy, one tz/local-year alignment.  The lat/lon cache
        # side effect goes to a throwaway directory (city files, not the
        # geometry-aware cache, are the deliverable here).
        from vfed.weather.weather_bridge import fetch_weather

        with tempfile.TemporaryDirectory(prefix="vfed_power_city_") as tmp:
            df = fetch_weather(
                lat, lon, YEAR,
                tz_hours=tz,
                tilt=20.0, azimuth=180.0,  # POA columns are discarded below
                cache_dir=Path(tmp),
                force=True,
                provider="nasa-power",
            )

        out = df[list(CITY_FILE_COLUMNS[:4])].copy()
        out["direct_radiation"] = 0.0
        out["diffuse_radiation"] = 0.0
        out.index.name = "timestamp"

        _validate_city_df(out, city)

        OUT_DIR.mkdir(parents=True, exist_ok=True)
        out.to_csv(out_path)

        # Round-trip readback: what we validate is what lands on disk.
        rb = pd.read_csv(out_path, parse_dates=["timestamp"])
        if len(rb) != len(out) or rb["timestamp"].iloc[0] != pd.Timestamp(f"{YEAR}-01-01 00:00:00"):
            raise ValueError(f"{city}: readback mismatch after write")

        ghi_kwh = float(out["shortwave_radiation"].sum()) / 1000.0
        print(f"OK ({len(out)} rows, GHI {ghi_kwh:.1f} kWh/m2)")
        return True
    except Exception as exc:
        print(f"FAIL: {exc}")
        return False


def _git_date(rel_path: Path) -> str:
    """Last commit date (YYYY-MM-DD) that touched *rel_path*, else ''."""
    try:
        res = subprocess.run(
            ["git", "log", "-1", "--format=%as", "--", rel_path.name],
            capture_output=True, text=True, cwd=str(OUT_DIR), timeout=30,
        )
        return res.stdout.strip()
    except Exception:
        return ""


def write_manifest() -> None:
    """Rebuild ``data/weather/MANIFEST.md`` from the files actually on disk.

    Every number (rows, GHI annual total) is computed by re-reading the
    CSVs — nothing is carried over from the download log.
    """
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    rows = []
    summary = {}
    for provider, suffix in (("open-meteo (ERA5)", ""), ("nasa-power (MERRA-2/CERES)", "_power")):
        ghi_vals = {}
        for city in AVAILABLE_CITIES:
            path = OUT_DIR / f"{city}_{YEAR}{suffix}.csv"
            if not path.exists():
                rows.append((path.name, provider, city, "—", "—", "—", "—", "MISSING", "—"))
                continue
            df = pd.read_csv(path, parse_dates=["timestamp"])
            ghi_kwh = float(df["shortwave_radiation"].sum()) / 1000.0
            lat, lon, _tz = _COORDS[city]
            generated = today if suffix else (_git_date(path) or today)
            rows.append((
                path.name, provider, city, f"{lat:.2f}", f"{lon:.2f}",
                YEAR, len(df), f"{ghi_kwh:.2f}", generated,
            ))
            ghi_vals[city] = ghi_kwh
        if ghi_vals:
            lo = min(ghi_vals, key=ghi_vals.get)
            hi = max(ghi_vals, key=ghi_vals.get)
            summary[provider] = (lo, ghi_vals[lo], hi, ghi_vals[hi])

    lines = [
        "# Weather Data Manifest — `data/weather/`",
        "",
        f"Generated by `scripts/download_weather_db.py` on {today}. "
        "Row counts and GHI totals are computed from the files on disk.",
        "",
        "## Data sources 数据源",
        "",
        "| provider | file pattern | upstream source |",
        "|---|---|---|",
        "| `open-meteo` | `{City}_{year}.csv` | ERA5 reanalysis (Copernicus/ECMWF), "
        "hourly, via the Open-Meteo archive API |",
        "| `nasa-power` | `{City}_{year}_power.csv` | NASA POWER hourly point API: "
        "meteorology from MERRA-2 reanalysis, radiation (ALLSKY_SFC_SW_DWN) from "
        "CERES SYN1deg satellite retrieval (~1° grid, interpolated to the request "
        "point by the service) |",
        "",
        "The two sources are whole-file alternatives — never mixed per column. "
        "In the `_power` files `direct_radiation`/`diffuse_radiation` are 0 "
        "placeholders (POWER provides hourly GHI only); the engine re-derives "
        "direct/diffuse/POA from GHI (Erbs split) with the design's "
        "tilt/azimuth at load time.",
        "",
        "## NASA POWER citation requirement 引用要求",
        "",
        "Any publication or report using the `_power` files must cite the NASA "
        "POWER service and its upstream datasets, per",
        "<https://power.larc.nasa.gov/docs/methodology/citations/>:",
        "",
        "- **NASA POWER** (Prediction Of Worldwide Energy Resources), NASA "
        "Langley Research Center (LaRC) — <https://power.larc.nasa.gov/>.",
        "- Meteorology: **MERRA-2** — Gelaro et al. (2017), *J. Climate*, "
        "doi:10.1175/JCLI-D-16-0758.1.",
        "- Radiation: **CERES SYN1deg** — Wielicki et al. (1996), *Bull. Amer. "
        "Meteor. Soc.*, doi:10.1175/1520-0477(1996)077<0853:CERESA>2.0.CO;2, "
        "and Rutan et al. (2015), *J. Atmos. Oceanic Technol.*, "
        "doi:10.1175/JTECH-D-14-00065.1.",
        "",
        "## City files 城市文件清单",
        "",
        "| File | Provider | City | Lat | Lon | Year | Rows | GHI (kWh/m²/yr) | Generated |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append("| " + " | ".join(str(c) for c in r) + " |")
    lines += ["", "## GHI range (per provider) GHI 年累计范围", ""]
    for provider, (lo_city, lo_val, hi_city, hi_val) in summary.items():
        lines.append(
            f"- `{provider}`: min **{lo_val:.2f} kWh/m²** ({lo_city}) — "
            f"max **{hi_val:.2f} kWh/m²** ({hi_city})"
        )
    lines.append("")

    MANIFEST_PATH.write_text("\n".join(lines), encoding="utf-8")
    n_missing = sum(1 for r in rows if r[7] == "MISSING")
    print(f"Manifest written: {MANIFEST_PATH.name} ({len(rows)} entries, {n_missing} missing)")


def main():
    parser = argparse.ArgumentParser(description="Download 2025 hourly weather for all DB cities.")
    parser.add_argument("--force", action="store_true", help="re-download even if the file exists")
    parser.add_argument(
        "--provider", choices=("open-meteo", "nasa-power"), default="open-meteo",
        help="weather source (default: open-meteo — ERA5, behaviour unchanged)",
    )
    parser.add_argument(
        "--manifest", action="store_true",
        help="only (re)generate data/weather/MANIFEST.md from the files on disk",
    )
    args = parser.parse_args()

    if args.manifest:
        write_manifest()
        return

    suffix = "" if args.provider == "open-meteo" else "_power"
    print(f"Downloading {YEAR} weather for {len(AVAILABLE_CITIES)} cities [{args.provider}]...")
    ok = fail = 0
    for city in AVAILABLE_CITIES:
        if args.provider == "open-meteo":
            good = download_city(city, force=args.force)
        else:
            good = download_city_nasa_power(city, force=args.force)
            if not good:
                print(f"  [retry] {city} — retrying once...")
                time.sleep(2.0)
                good = download_city_nasa_power(city, force=True)
        if good:
            ok += 1
        else:
            fail += 1
            print(f"  [FAIL-FINAL] {city}_{YEAR}{suffix}.csv not generated")
        time.sleep(0.5)  # rate limit courtesy

    if args.provider == "nasa-power":
        write_manifest()
    print(f"\nDone. {ok} success, {fail} failed.")


if __name__ == "__main__":
    main()
