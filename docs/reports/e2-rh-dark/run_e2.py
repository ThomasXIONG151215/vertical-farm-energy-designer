# -*- coding: utf-8 -*-
"""E-2: dark-period low-humidity setpoint (setpoints.RH_dark) A/B experiment.

Arms (609 preset, Shanghai 2025 offline weather, grid-only):
  B0      : baseline, RH_dark=None (sentinel determinism re-run)
  A0_none : baseline, RH_dark=None (the baseline row of the 3-arm table)
  A55     : RH_dark=55 (% RH during dark hours)
  A60     : RH_dark=60 (% RH during dark hours)

Tariff (applied IDENTICALLY to every arm, incl. B0):
  Shanghai TOU from vfed/pvbes/tariff_db.lookup_tariff("Shanghai")
  (valley 0.30 CNY/kWh h22-06, flat 0.60, peak 1.00 h08-11 & h18-21)
  + monthly demand charge 40 CNY/kW-month on the monthly max hourly
    grid import power (rate assumed: Shanghai two-part general industry;
    the task specifies the mechanism but not the rate).

Outputs (this directory): e2_results.csv, report.md
"""
import csv
import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path

import numpy as np

REPO = Path(r"G:\VFLab\VFLAB\vertical-farm-energy-designer")
sys.path.insert(0, str(REPO))

from vfed.design.engine import DesignEngine
from vfed.design.presets import preset_609
from vfed.design.project import TariffConfig
from vfed.pvbes.tariff_db import lookup_tariff

DEMAND_RATE = 40.0  # CNY/kW-month (documented assumption)
ARMS = [("A0_none", None), ("A55", 55.0), ("A60", 60.0)]


def make_project(rh_dark):
    p = preset_609()
    rec = lookup_tariff("Shanghai")
    p.tariff = TariffConfig(
        hourly_prices=list(rec["hourly_prices"]),
        export_price=rec["export_price"],
        demand_charge_per_kw=DEMAND_RATE,
    )
    p.currency = "CNY"
    if rh_dark is not None:
        p.setpoints.RH_dark = rh_dark
    return p


def ts_hash(result):
    payload = json.dumps(
        result.timeseries, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def arm_metrics(name, rh_dark, result):
    ts = result.timeseries
    led = np.asarray(ts["E_led_Wh"], dtype=float)
    deh = np.asarray(ts["E_deh_Wh"], dtype=float)
    rh = np.asarray(ts["RH_z"], dtype=float)
    load = np.asarray(ts["load_kw"], dtype=float)
    price = np.asarray(ts["price"], dtype=float)
    month = np.asarray(ts["month"], dtype=int)

    dark = led <= 0.0
    n_dark, n_light = int(dark.sum()), int((~dark).sum())

    deh_total_kwh = deh.sum() / 1000.0
    deh_dark_kwh = deh[dark].sum() / 1000.0
    deh_light_kwh = deh[~dark].sum() / 1000.0
    duty_dark = float(np.count_nonzero(deh[dark] > 0)) / n_dark
    duty_light = float(np.count_nonzero(deh[~dark] > 0)) / n_light

    rh_dark_h = rh[dark]
    energy_cost = float(np.sum(load * price))  # grid-only: import == load
    peaks = [float(load[month == m].max()) for m in range(1, 13)]
    demand_cost = DEMAND_RATE * sum(peaks)

    s = result.summary
    return {
        "arm": name,
        "rh_dark": "None" if rh_dark is None else f"{rh_dark:.0f}",
        "annual_energy_kwh": round(s["annual_energy_kwh"], 2),
        "annual_harvest_kg": round(s["annual_harvest_kg"], 3),
        "deh_kwh_total": round(deh_total_kwh, 2),
        "deh_kwh_dark": round(deh_dark_kwh, 2),
        "deh_kwh_light": round(deh_light_kwh, 2),
        "deh_duty_dark": round(duty_dark, 4),
        "deh_duty_light": round(duty_light, 4),
        "dark_h": n_dark,
        "light_h": n_light,
        "dark_rh_mean": round(float(rh_dark_h.mean()), 2),
        "dark_rh_p5": round(float(np.percentile(rh_dark_h, 5)), 2),
        "dark_rh_p50": round(float(np.percentile(rh_dark_h, 50)), 2),
        "dark_rh_p95": round(float(np.percentile(rh_dark_h, 95)), 2),
        "rh_exceed_hours_v1": int(s["rh_exceed_hours"]),
        "rh_p95_year": s.get("rh_p95_pct"),
        "energy_cost_cny": round(energy_cost, 2),
        "demand_cost_cny": round(demand_cost, 2),
        "total_cost_cny_engine": round(s["total_electricity_cost"], 2),
        "total_cost_cny_check": round(energy_cost + demand_cost, 2),
        "annual_peak_kw_max": round(max(peaks), 3),
    }


def main():
    out_dir = REPO / "docs" / "reports" / "e2-rh-dark"
    out_dir.mkdir(parents=True, exist_ok=True)
    engine = DesignEngine(cache_dir=None)

    rows = []
    hashes = {}

    # sentinel arm B0 first
    r_b0 = engine.run(deepcopy(make_project(None)))
    hashes["B0"] = ts_hash(r_b0)

    for name, rh_dark in ARMS:
        r = engine.run(deepcopy(make_project(rh_dark)))
        hashes[name] = ts_hash(r)
        rows.append(arm_metrics(name, rh_dark, r))

    print("hashes:", json.dumps(hashes, indent=1))
    if hashes["B0"] != hashes["A0_none"]:
        print("FATAL: B0 / A0_none timeseries hashes differ - aborting.")
        sys.exit(2)

    with open(out_dir / "e2_results.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("wrote", out_dir / "e2_results.csv")

    # persist raw hashes + rows for the report step
    with open(out_dir / "e2_raw.json", "w", encoding="utf-8") as f:
        json.dump({"hashes": hashes, "rows": rows,
                   "demand_rate_cny_per_kw_month": DEMAND_RATE}, f, indent=1)
    print("wrote", out_dir / "e2_raw.json")


if __name__ == "__main__":
    main()
