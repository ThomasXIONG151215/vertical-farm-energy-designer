# -*- coding: utf-8 -*-
"""E-2 addendum: mechanism diagnostics for the report (water balance, HVAC
split, X_d carry-over, exact harvest). Re-runs the 3 arms (~6 s)."""
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

DEMAND_RATE = 40.0
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


out = {}
engine = DesignEngine(cache_dir=None)
for name, rh_dark in ARMS:
    r = engine.run(deepcopy(make_project(rh_dark)))
    ts = r.timeseries
    led = np.asarray(ts["E_led_Wh"], float)
    hvac = np.asarray(ts["E_hvac_Wh"], float)
    deh = np.asarray(ts["E_deh_Wh"], float)
    xd = np.asarray(ts["X_d"], float)
    dark = led <= 0.0
    s = r.summary
    out[name] = {
        "annual_water_m3": s.get("annual_water_m3"),
        "annual_hvac_kwh": s.get("annual_hvac_kwh"),
        "hvac_kwh_dark": round(float(hvac[dark].sum() / 1000.0), 2),
        "hvac_kwh_light": round(float(hvac[~dark].sum() / 1000.0), 2),
        "hvac_kwh_total": round(float(hvac.sum() / 1000.0), 2),
        "deh_water_kg_smer35_est": round(float(deh.sum() / 1000.0 * 3.5), 1),
        "xd_mean_dark": round(float(xd[dark].mean()), 6),
        "xd_mean_light": round(float(xd[~dark].mean()), 6),
        "xd_mean_last_dark_hour": round(float(xd[dark][-1]), 6),
        "xd_mean_first3h_light": round(float(xd[~dark][:3].mean()), 6),
        "annual_harvest_kg_exact": s.get("annual_harvest_kg"),
        "annual_harvest_fw_kg_exact": s.get("annual_harvest_fw_kg"),
        "moisture_clamp_stats": s.get("moisture_clamp_stats"),
        "dehumidifier_performance": s.get("dehumidifier_performance"),
        "deh_smer_effective": s.get("deh_smer"),
        "led_kwh": s.get("annual_led_kwh"),
        "rh_setpoint_pct": s.get("rh_setpoint_pct"),
    }

d = REPO / "docs" / "reports" / "e2-rh-dark"
with open(d / "e2_addendum.json", "w", encoding="utf-8") as f:
    json.dump(out, f, indent=1, ensure_ascii=False)
print(json.dumps(out, indent=1, ensure_ascii=False))
