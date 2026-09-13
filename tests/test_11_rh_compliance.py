"""P1-4: RH compliance / disease-risk KPIs (additive output aggregation).

Pins:
  * summary gains 6 RH-compliance scalars (rh_setpoint_pct / rh_exceed_hours
    / rh_exceed_pct / rh_p95_pct / rh_max_pct / rh_disease_risk_hours) —
    pure post-processing on the RH_z hourly array, no physics touched
    (baseline energy/harvest/cost pins unchanged);
  * every pre-existing summary key survives (additive contract);
  * recomputing the KPIs from the exported timeseries.csv RH_z column
    reproduces the summary values (same-array self-consistency);
  * setpoints.rh_disease_risk_threshold is yaml-configurable with
    (0, 100] load-time validation; a risk-band crossing emits a pure-ASCII
    WARNING;
  * monthly gains rh_exceed_hours whose 12 buckets close against the
    annual scalar.
"""
import csv
import os
import sys
from pathlib import Path

import numpy as np
import pytest
import yaml

SRC = Path(__file__).resolve().parents[1] / "vfed"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from vfed.design.engine import DesignEngine  # noqa: E402
from vfed.design.presets import preset_609  # noqa: E402
from vfed.design.project import DesignProject  # noqa: E402

RH_KPIS = (
    "rh_setpoint_pct",
    "rh_exceed_hours",
    "rh_exceed_pct",
    "rh_p95_pct",
    "rh_max_pct",
    "rh_disease_risk_hours",
)

# Frozen pre-P1-4 summary key set (grid-only 609 path): base scalars +
# deh_smer / full_load_diagnostics + the P0-2 economics block.  P1-4 is
# strictly additive — this set must survive untouched, and the P1-4 keys
# must be the ONLY additions.
OLD_SUMMARY_KEYS = {
    "annual_energy_kwh",
    "annual_grid_cost_net",
    "annual_harvest_fw_kg",
    "annual_harvest_kg",
    "annual_hvac_kwh",
    "annual_led_kwh",
    "annual_om",
    "annual_water_m3",
    "battery_cycles",
    "battery_discharge_kwh",
    "capital_total",
    "deh_pct",
    "deh_smer",
    "dehumidifier_performance",
    "dry_matter_fraction",
    "free_energy_kwh",
    "full_load_diagnostics",
    "grid_export_kwh",
    "grid_import_kwh",
    "grid_independence_pct",
    "harvest_final_standing_kg",
    "harvest_per_month_avg_kg",
    "hvac_pct",
    "lcoe",
    "led_pct",
    "misc_pct",
    "moisture_clamp_stats",
    "pv_generation_kwh",
    "pv_self_consumed_kwh",
    "pv_self_consumption_rate",
    "specific_cost_per_kg",
    "specific_energy_kwh_per_kg",
    "temperature_clamp_stats",
    "total_electricity_cost",
}


@pytest.fixture(scope="module")
def sim_shanghai_2025():
    """preset 609 @ pre-downloaded Shanghai 2025 city file (offline)."""
    p = preset_609()
    p.site.city = "Shanghai"
    p.site.year = 2025
    return DesignEngine(cache_dir="weather_cache").run(p)


# ── additive contract ──────────────────────────────────────────────────────


def test_summary_additive_keys(sim_shanghai_2025):
    s = sim_shanghai_2025.summary
    assert OLD_SUMMARY_KEYS <= set(s), f"pre-existing summary keys lost: {OLD_SUMMARY_KEYS - set(s)}"
    assert set(s) == OLD_SUMMARY_KEYS | set(RH_KPIS)


# ── 609@Shanghai2025 aligned-window KPI pins (self-test measured) ──────────


def test_shanghai_2025_rh_kpi_pins(sim_shanghai_2025):
    s = sim_shanghai_2025.summary
    assert s["rh_setpoint_pct"] == 65.0
    assert s["rh_exceed_hours"] == 7095
    assert s["rh_exceed_pct"] == 0.8099
    assert s["rh_p95_pct"] == 69.1
    assert s["rh_max_pct"] == 69.49
    assert s["rh_disease_risk_hours"] == 0  # max 69.49 % < 85 % default band


# ── same-array self-consistency: recompute from exported timeseries.csv ────


def test_rh_kpis_recomputable_from_ts_csv(sim_shanghai_2025, tmp_path):
    sim = sim_shanghai_2025
    path = os.path.join(str(tmp_path), "timeseries.csv")
    sim.save_timeseries_csv(path)
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    col = rows[0].index("RH_z")
    rh = np.array([float(r[col]) for r in rows[1:]])
    assert len(rh) == 8760
    s = sim.summary
    rh_set = s["rh_setpoint_pct"]
    thr = preset_609().setpoints.rh_disease_risk_threshold
    assert int(np.count_nonzero(rh > rh_set)) == s["rh_exceed_hours"]
    assert round(int(np.count_nonzero(rh > rh_set)) / len(rh), 4) == s["rh_exceed_pct"]
    assert round(float(np.percentile(rh, 95)), 2) == s["rh_p95_pct"]
    assert round(float(np.max(rh)), 2) == s["rh_max_pct"]
    assert int(np.count_nonzero(rh >= thr)) == s["rh_disease_risk_hours"]


# ── threshold is configurable; crossing the band warns (pure ASCII) ────────


def test_low_threshold_triggers_risk_hours_and_warning(tmp_path):
    p = preset_609()
    p.site.city = "Shanghai"
    p.site.year = 2025
    d = p.to_dict()
    d["setpoints"]["rh_disease_risk_threshold"] = 50.0
    yml = tmp_path / "thr50.yaml"
    yml.write_text(yaml.safe_dump(d, sort_keys=False, allow_unicode=True), encoding="utf-8")
    proj = DesignProject.load(str(yml))
    assert proj.setpoints.rh_disease_risk_threshold == 50.0

    with pytest.warns(UserWarning, match="RH disease risk") as rec:
        sim = DesignEngine(cache_dir="weather_cache").run(proj)
    s = sim.summary
    assert s["rh_disease_risk_hours"] > 0
    # WARNING text: pure ASCII, carries risk hours + threshold + setpoint
    msgs = [str(w.message) for w in rec if "RH disease risk" in str(w.message)]
    assert len(msgs) == 1
    msg = msgs[0]
    assert msg == msg.encode("ascii").decode("ascii")
    assert "50.0" in msg and "65.0" in msg and str(s["rh_disease_risk_hours"]) in msg


# ── config validation: (0, 100] fail-fast ──────────────────────────────────


@pytest.mark.parametrize("bad", [0.0, 150.0])
def test_threshold_validation_fails_fast(bad):
    with pytest.raises(ValueError, match="rh_disease_risk_threshold"):
        DesignProject.from_dict(
            {"name": "x", "setpoints": {"rh_disease_risk_threshold": bad}}
        )


# ── physics zero-drift pins (reporting layer only) ─────────────────────────


def test_physics_zero_drift_pins(sim_shanghai_2025):
    s = sim_shanghai_2025.summary
    assert s["annual_energy_kwh"] == pytest.approx(62444.50, abs=5e-3)
    assert s["specific_energy_kwh_per_kg"] == pytest.approx(31.0499, abs=5e-4)
    assert s["annual_harvest_kg"] == pytest.approx(100.55, abs=5e-3)
    assert s["annual_grid_cost_net"] == pytest.approx(6244.45, abs=0.01)
    assert s["lcoe"] == pytest.approx(0.6608, abs=5e-5)


# ── monthly rh_exceed_hours closes against the annual scalar ───────────────


def test_monthly_rh_exceed_hours_closes_annual(sim_shanghai_2025):
    m = sim_shanghai_2025.monthly
    s = sim_shanghai_2025.summary
    assert "rh_exceed_hours" in m
    assert len(m["rh_exceed_hours"]) == 12
    assert sum(m["rh_exceed_hours"]) == s["rh_exceed_hours"]
