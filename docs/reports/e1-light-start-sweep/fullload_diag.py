"""E-1 full-load diagnostics: HVAC/DEH saturation at representative hours.

Runs DesignEngine once per light_start_hour (physics identical across
tariff/PV arms) and dumps summary["full_load_diagnostics"] plus the
hvac/deh energy shares. Hours: 0, 6 (baseline/worst), 14 (grid-cost best,
no PV), 16 (LCOE best, no PV), 22 (best with 80 m2 PV).
"""
import json
from pathlib import Path

from vfed.design.engine import DesignEngine, full_load_warnings
from vfed.design.presets import preset_609
from vfed.design.sweep import _override_project

OUT = Path(__file__).resolve().parent
HOURS = [0, 6, 14, 16, 22]

engine = DesignEngine(cache_dir=None)
report = {}
for h in HOURS:
    p = _override_project(preset_609(), {"light_start_hour": float(h)})
    sim = engine.run(p)
    s = sim.summary
    diag = s.get("full_load_diagnostics", {})
    report[str(h)] = {
        "full_load_diagnostics": diag,
        "warnings": full_load_warnings(s),
        "annual_load_kwh": s.get("annual_load_kwh"),
        "energy_share_pct": s.get("energy_share_pct"),
    }
    print(f"--- hour {h} ---")
    print(json.dumps(report[str(h)], indent=2, ensure_ascii=False, default=str))

with open(OUT / "e1_fullload_diagnostics.json", "w", encoding="utf-8") as f:
    json.dump(report, f, indent=2, ensure_ascii=False, default=str)
print("saved -> e1_fullload_diagnostics.json")
