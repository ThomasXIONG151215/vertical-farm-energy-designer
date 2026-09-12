"""P1-3a: additive output-pipeline columns (monthly.csv / summary.csv).

Pins the zero-drift additive fix set:
  * monthly.csv gains grid_import_kwh / electricity_cost / water_m3 /
    harvest_fw_kg (all configs) and pv_generation_kwh / grid_export_kwh /
    battery_net_kwh (only when PV or battery is enabled);
  * summary.csv gains annual_led_kwh / annual_hvac_kwh, the energy_breakdown
    shares flattened (hvac_pct / deh_pct / led_pct / misc_pct) and
    harvest_final_standing_kg (year-end standing crop, in NO monthly bucket);
  * every summary.csv cell is ast.literal_eval-parseable (no np.float64 repr);
  * the sweep results.csv column set stays exactly the 32 P1-2 columns.
"""
import ast
import csv
import os

import numpy as np
import pytest

from vfed.design.engine import DesignEngine
from vfed.design.presets import preset_609
from vfed.design.result import SimulationResult, _ensure_json_safe

MONTHLY_BASE_COLS = {
    "month",
    "energy_kwh__total",
    "energy_kwh__hvac",
    "energy_kwh__deh",
    "energy_kwh__led",
    "energy_kwh__misc",
    "harvest_kg",
    "avg_T_z",
    "avg_RH_z",
}
MONTHLY_P13A_GRID_COLS = {"grid_import_kwh", "electricity_cost", "water_m3", "harvest_fw_kg"}
MONTHLY_P13A_PV_COLS = {"pv_generation_kwh", "grid_export_kwh", "battery_net_kwh"}


# ── grid-only (preset 609): new monthly flat keys + summary scalars ──────


def test_monthly_grid_only_new_columns_present(sim_609):
    got = set()
    for k, v in sim_609.monthly.items():
        if isinstance(v, dict):
            got |= {f"{k}__{sk}" for sk in v}
        else:
            got.add(k)
    assert MONTHLY_BASE_COLS <= got, f"pre-existing monthly columns lost: {MONTHLY_BASE_COLS - got}"
    assert MONTHLY_P13A_GRID_COLS <= got
    # PV-dispatch columns must NOT appear on a grid-only run
    assert not (MONTHLY_P13A_PV_COLS & got)
    for col in MONTHLY_P13A_GRID_COLS:
        assert len(sim_609.monthly[col]) == 12


def test_summary_new_scalars_present(sim_609):
    s = sim_609.summary
    for key in (
        "annual_led_kwh",
        "annual_hvac_kwh",
        "hvac_pct",
        "deh_pct",
        "led_pct",
        "misc_pct",
        "harvest_final_standing_kg",
    ):
        assert key in s, f"missing new summary scalar: {key}"
    # pct scalars mirror the energy_breakdown dict exactly
    for dev in ("hvac", "deh", "led", "misc"):
        assert s[f"{dev}_pct"] == sim_609.energy_breakdown[f"{dev}_pct"]


def test_summary_led_hvac_match_timeseries_sums(sim_609):
    ts = sim_609["timeseries"]
    assert sim_609.summary["annual_led_kwh"] == pytest.approx(
        float(ts["E_led_Wh"].sum()) / 1000.0, abs=0.01
    )
    assert sim_609.summary["annual_hvac_kwh"] == pytest.approx(
        float(ts["E_hvac_Wh"].sum()) / 1000.0, abs=0.01
    )


def test_grid_only_monthly_grid_import_equals_load(sim_609):
    m = sim_609.monthly
    assert m["grid_import_kwh"] == pytest.approx(m["energy_kwh"]["total"])


def test_grid_only_monthly_electricity_cost_closes_with_annual(sim_609):
    m = sim_609.monthly
    s = sim_609.summary
    assert len(m["electricity_cost"]) == 12
    assert sum(m["electricity_cost"]) == pytest.approx(s["annual_grid_cost_net"], abs=0.01)
    assert sum(m["electricity_cost"]) == pytest.approx(s["total_electricity_cost"], abs=0.01)


def test_monthly_water_m3_closes_with_annual(sim_609):
    m = sim_609.monthly
    assert sum(m["water_m3"]) == pytest.approx(sim_609.summary["annual_water_m3"], abs=0.01)


def test_monthly_harvest_is_pure_events_standing_excluded(sim_609):
    """P1-3a T3: monthly.harvest_kg sums to annual − standing; the standing
    crop lives only in summary.harvest_final_standing_kg."""
    m = sim_609.monthly
    s = sim_609.summary
    standing = s["harvest_final_standing_kg"]
    assert standing >= 0.0
    assert sum(m["harvest_kg"]) == pytest.approx(s["annual_harvest_kg"] - standing, abs=0.01)
    # fw column is the dry column converted with dry_matter_fraction
    dry = s["dry_matter_fraction"]
    assert m["harvest_fw_kg"] == pytest.approx([h / dry for h in m["harvest_kg"]], rel=1e-9)
    assert sum(m["harvest_fw_kg"]) == pytest.approx(sum(m["harvest_kg"]) / dry, rel=1e-9)
    # vs the ROUNDED annual/standing scalars the closure holds to the
    # rounding error of annual_harvest_kg (2 dp, amplified by /dry_fraction)
    assert sum(m["harvest_fw_kg"]) == pytest.approx(
        (s["annual_harvest_kg"] - standing) / dry, abs=0.1
    )


# ── Shanghai 2025 authoritative baseline pin ─────────────────────────────
# P1-3b: numbers migrated from the rotating-window set (62,452.72 / m1
# 8.2964) after data/weather/Shanghai_2025.csv was regenerated on the
# aligned local calendar year.  See tests/test_10_time_axis.py for the
# full alignment contract.


@pytest.fixture(scope="module")
def sim_shanghai_2025():
    """preset 609 @ pre-downloaded Shanghai 2025 city file (offline)."""
    p = preset_609()
    p.site.city = "Shanghai"
    p.site.year = 2025
    return DesignEngine(cache_dir="weather_cache").run(p)


def test_shanghai_2025_harvest_attribution(sim_shanghai_2025):
    """m1 = harvest event 1 only; the year-end standing crop is a separate
    scalar, not folded into any month."""
    m = sim_shanghai_2025.monthly
    s = sim_shanghai_2025.summary
    assert m["harvest_kg"][0] == pytest.approx(8.3285, abs=5e-4)
    assert s["harvest_final_standing_kg"] == pytest.approx(1.4617, abs=5e-4)
    assert s["annual_harvest_kg"] == pytest.approx(100.55, abs=5e-3)
    assert sum(m["harvest_kg"]) == pytest.approx(
        s["annual_harvest_kg"] - s["harvest_final_standing_kg"], abs=0.01
    )


def test_shanghai_2025_zero_drift_and_cost_closure(sim_shanghai_2025):
    s = sim_shanghai_2025.summary
    assert s["annual_energy_kwh"] == pytest.approx(62444.50, abs=5e-3)
    assert s["specific_energy_kwh_per_kg"] == pytest.approx(31.0499, abs=5e-4)
    assert s["annual_led_kwh"] == pytest.approx(42048.0, abs=0.01)
    assert s["annual_hvac_kwh"] == pytest.approx(10163.59, abs=0.01)
    assert s["lcoe"] == pytest.approx(0.6608, abs=5e-5)
    assert s["annual_grid_cost_net"] == pytest.approx(6244.45, abs=0.01)
    m = sim_shanghai_2025.monthly
    assert sum(m["electricity_cost"]) == pytest.approx(6244.45, abs=0.01)
    assert sum(m["grid_import_kwh"]) == pytest.approx(62444.50, abs=0.01)


# ── PV/battery enabled: dispatch columns appear and close ────────────────


@pytest.fixture(scope="module")
def sim_pv():
    p = preset_609()
    p.pv_area_m2 = 50.0
    p.battery_kwh = 40.0
    return DesignEngine(cache_dir="weather_cache").run(p)


def test_monthly_pv_columns_present_and_close(sim_pv):
    m = sim_pv.monthly
    s = sim_pv.summary
    for col in MONTHLY_P13A_PV_COLS | MONTHLY_P13A_GRID_COLS:
        assert col in m, f"missing PV-run monthly column: {col}"
        assert len(m[col]) == 12
    assert sum(m["pv_generation_kwh"]) == pytest.approx(s["pv_generation_kwh"], abs=0.01)
    assert sum(m["grid_import_kwh"]) == pytest.approx(s["grid_import_kwh"], abs=0.01)
    assert sum(m["grid_export_kwh"]) == pytest.approx(s["grid_export_kwh"], abs=0.01)
    # electricity_cost is the hourly NET bill (import x price - export x
    # feed-in), so it closes with the annual net grid cost here too.
    assert sum(m["electricity_cost"]) == pytest.approx(s["annual_grid_cost_net"], abs=0.01)


# ── summary.csv: literal_eval-parseable, no numpy reprs ─────────────────


def test_summary_csv_all_cells_literal_eval_safe(sim_609, tmp_path):
    path = os.path.join(str(tmp_path), "summary.csv")
    sim_609.save_summary_csv(path)
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    header, values = rows[0], rows[1]
    assert "np.float64" not in " ".join(values)
    assert "np." not in " ".join(values)
    for col, cell in zip(header, values):
        parsed = ast.literal_eval(cell)  # must not raise
        if col in ("deh_smer", "dehumidifier_performance", "full_load_diagnostics",
                   "moisture_clamp_stats", "temperature_clamp_stats"):
            assert isinstance(parsed, dict)


def test_ensure_json_safe_removes_np_repr_from_summary(tmp_path):
    """Regression for D-5 root cause: a summary carrying np.float64 scalars
    inside dict values exports clean CSV cells."""
    r = SimulationResult(project_name="np_repr")
    r.summary = {
        "deh_smer": {
            "effective_smer_kg_per_kwh": np.float64(1.32),
            "deh_comp_energy_kwh": round(np.float64(9884.61), 2),
        },
        "plain": np.float64(0.5),
    }
    path = os.path.join(str(tmp_path), "summary.csv")
    r.save_summary_csv(path)
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    cells = dict(zip(rows[0], rows[1]))
    assert "np.float64" not in ",".join(rows[1])
    assert ast.literal_eval(cells["deh_smer"]) == {
        "effective_smer_kg_per_kwh": 1.32,
        "deh_comp_energy_kwh": 9884.61,
    }
    assert ast.literal_eval(cells["plain"]) == 0.5
    assert _ensure_json_safe(np.float64(2.0)) == 2.0


# ── sweep results.csv column set stays exactly 32 ────────────────────────


def test_sweep_column_set_unchanged(project_609):
    from vfed.design.sweep import sweep_design

    p = preset_609()
    p.space.parameter_ranges = {
        "ppfd_target": [200, 300, 100],
        "pv_area": [0, 100, 100],
        "battery": [0, 100, 100],
    }
    df = sweep_design(p)["results"]
    expected = {
        "ppfd_target", "currency", "pv_area", "battery_kwh", "lcoe",
        "cost_per_kg_fresh", "kwh_per_kg_fresh", "capital_total", "capital_led",
        "capital_hvac", "capital_deh", "capital_pv", "capital_battery",
        "capital_equipment", "capital_envelope", "annual_capital", "annual_om",
        "annual_grid_cost", "annual_load_kwh", "biomass_kg",
        "annual_pv_generation", "annual_grid_import", "annual_grid_export",
        "battery_cycles", "grid_independence_pct", "pv_self_consumption_rate",
        "annual_savings", "payback_period", "delta_capital",
        "delta_annual_savings", "npv_25yr", "irr_pct",
    }
    assert len(df.columns) == 32
    assert set(df.columns) == expected
    # no P1-3a summary scalars may leak into the sweep table
    for leaked in ("annual_led_kwh", "annual_hvac_kwh", "hvac_pct", "harvest_final_standing_kg"):
        assert leaked not in df.columns
