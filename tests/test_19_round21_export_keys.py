"""Round 21 commit B (F3+F4): additive summary keys — zero-drift contract.

F3: ``summary["annual_capital"]`` (both engine economics branches — README
    promised the column but engine.py only ever folded the value into
    lcoe / specific_cost_per_kg) and ``summary["annual_ghi_kwh_m2"]``
    (annual GHI insolation, same number as ``climate.annual_ghi_kwh_m2``).
F4: battery bookkeeping keys ``battery_charge_kwh`` (terminal-side annual
    charge throughput, already contains the P4-18 year-end top-up) and
    ``battery_recon_grid_kwh`` (signed reconciliation energy) so the three
    user13 observations — annual-balance residual +17.58 kWh, apparent RTE
    0.8303 vs 0.8281, cycles -0.443% — close exactly from summary.csv.

Additive only: no existing key, physics loop or sweep column changes
(the 32-column sweep contract is pinned in test_09).
"""

import csv
import os
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[1] / "vfed"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from vfed.design.engine import DesignEngine
from vfed.design.presets import preset_609
from vfed.pvbes.battery import BatterySystem
from vfed.pvbes.energy_system import EnergySystem
from vfed.pvbes.pv import PVSystem


@pytest.fixture(scope="module")
def econ():
    """user13 econ sizing: preset 609 @ Shanghai 2025 + PV 100 m2 + 40 kWh
    battery (dispatch reproduces the audited u13_econ numbers: import
    31,187.45 / discharge 5,567.89 / recon 17.5824)."""
    p = preset_609()
    p.site.city = "Shanghai"
    p.site.year = 2025
    p.pv_area_m2 = 100.0
    p.battery_kwh = 40.0
    sim = DesignEngine(cache_dir="weather_cache").run(p)
    return sim, p


# ── F3: annual_capital ───────────────────────────────────────────────────


def test_annual_capital_grid_only_identity(sim_609, project_609):
    """preset 609 declares no capital blocks -> every component resolves to
    the zero legacy fallback, so the grid-only baseline must export
    annual_capital == 0.0 exactly (capital=0 -> CRF x 0 = 0)."""
    from vfed.design.sweep import _annualized_capital, _total_capital

    s = sim_609.summary
    assert "annual_capital" in s
    assert s["capital_total"] == 0.0
    assert s["annual_capital"] == 0.0
    # identity vs the same sweep helpers the engine calls
    expected = _annualized_capital(project_609, _total_capital(project_609, 0.0, 0.0))
    assert s["annual_capital"] == pytest.approx(expected, abs=1e-9)


def test_annual_capital_pv_branch_identity(econ):
    """With PV+battery the exported value equals capital_total CRF-annualised
    per component depreciation life, and lcoe is recomputable from the four
    summary scalars alone."""
    from vfed.design.sweep import _annualized_capital, _total_capital

    sim, p = econ
    s = sim.summary
    assert s["annual_capital"] > 0.0
    expected = _annualized_capital(p, _total_capital(p, p.pv_area_m2, p.battery_kwh))
    assert s["annual_capital"] == pytest.approx(expected, abs=0.01)
    # lcoe closure from summary keys only (lcoe is rounded to 4 dp)
    recomputed = (
        s["annual_capital"] + s["annual_om"] + s["annual_grid_cost_net"]
    ) / s["annual_energy_kwh"]
    assert recomputed == pytest.approx(s["lcoe"], rel=1e-3)


# ── F3: annual GHI insolation ────────────────────────────────────────────


def test_annual_ghi_matches_weather_df(sim_609):
    """Independent recomputation: preset 609 runs on the pre-downloaded city
    file (Shanghai_2025.csv) — sum its hourly shortwave_radiation directly
    and compare against both the new summary key and the climate block."""
    import pandas as pd

    city = Path(__file__).resolve().parents[1] / "data" / "weather" / "Shanghai_2025.csv"
    df = pd.read_csv(city)
    assert len(df) == 8760
    ghi_kwh_m2 = float(df["shortwave_radiation"].sum()) / 1000.0
    assert sim_609.summary["annual_ghi_kwh_m2"] == pytest.approx(ghi_kwh_m2, abs=0.01)
    # same number the climate block has always carried (unrounded there)
    assert sim_609.summary["annual_ghi_kwh_m2"] == pytest.approx(
        sim_609.climate["annual_ghi_kwh_m2"], abs=0.01
    )


def test_annual_ghi_pv_run_matches_raw_weather(econ):
    sim, _p = econ
    ghi = np.asarray(sim._raw["weather"]["shortwave_radiation"], dtype=float)
    assert sim.summary["annual_ghi_kwh_m2"] == pytest.approx(float(ghi.sum()) / 1000.0, abs=0.01)


# ── F4: battery bookkeeping keys ─────────────────────────────────────────


def test_grid_only_battery_keys_present_and_zero(sim_609):
    s = sim_609.summary
    for key in ("battery_charge_kwh", "battery_recon_grid_kwh"):
        assert key in s
        assert s[key] == 0.0
    assert s["battery_discharge_kwh"] == 0.0
    assert s["battery_cycles"] == 0.0


def test_battery_keys_match_user13_audit_pins(econ):
    """The audited u13_econ dispatch reproduced: discharge 5,567.89 kWh,
    reconciliation top-up 17.58 kWh (16.0 kWh stored / eta_ch), import
    31,187.45 kWh — the three numbers the round-20 white-box closed by
    hand are now exported directly."""
    sim, _p = econ
    s = sim.summary
    assert s["battery_charge_kwh"] > 0.0
    assert s["battery_discharge_kwh"] == pytest.approx(5567.89, abs=0.02)
    assert s["battery_recon_grid_kwh"] == pytest.approx(17.58, abs=0.01)
    assert s["grid_import_kwh"] == pytest.approx(31187.45, abs=0.02)


def test_charge_free_residual_equals_recon(econ):
    """user13's charge-free check import + discharge + self - load carries a
    residual of EXACTLY the reconciliation top-up (to the 2-dp rounding of
    the exported scalars); the charge-inclusive balance closes to zero."""
    sim, _p = econ
    s = sim.summary
    residual = (
        s["grid_import_kwh"]
        + s["battery_discharge_kwh"]
        + s["pv_self_consumed_kwh"]
        - s["annual_energy_kwh"]
    )
    assert residual == pytest.approx(s["battery_recon_grid_kwh"], abs=0.03)
    # full balance WITH the charge term closes (recon enters import and
    # charge together — never load)
    balance = (
        s["pv_generation_kwh"]
        + s["grid_import_kwh"]
        + s["battery_discharge_kwh"]
        - s["annual_energy_kwh"]
        - s["battery_charge_kwh"]
        - s["grid_export_kwh"]
    )
    assert balance == pytest.approx(0.0, abs=0.05)


def test_measured_rte_identity(econ):
    """discharge / charge == eta_ch * eta_dis exactly, because the exported
    charge already contains the reconciliation top-up (user13's 0.8303 came
    from a PV-only denominator missing the 17.58 kWh)."""
    sim, p = econ
    s = sim.summary
    eta2 = p.battery.eta_ch * p.battery.eta_dis
    assert s["battery_discharge_kwh"] / s["battery_charge_kwh"] == pytest.approx(eta2, rel=1e-4)
    # and the PV-only denominator + recon recovers the same denominator
    pv_only_charge = s["pv_generation_kwh"] - s["pv_self_consumed_kwh"] - s["grid_export_kwh"]
    assert s["battery_charge_kwh"] == pytest.approx(
        pv_only_charge + s["battery_recon_grid_kwh"], abs=0.03
    )


def test_battery_cycles_storage_side_definition(econ):
    """battery_cycles counts storage-side throughput; the terminal-side
    formula is higher by 1 - 2*eta/(1+eta^2) (~0.443% at eta=0.91)."""
    sim, p = econ
    s = sim.summary
    cap = p.battery_kwh
    eta_ch, eta_dis = p.battery.eta_ch, p.battery.eta_dis
    assert eta_ch == eta_dis  # preset default 0.91 (ratio formula below needs it)
    storage = (s["battery_charge_kwh"] * eta_ch + s["battery_discharge_kwh"] / eta_dis) / (2 * cap)
    assert s["battery_cycles"] == pytest.approx(storage, abs=0.02)
    terminal = (s["battery_charge_kwh"] + s["battery_discharge_kwh"]) / (2 * cap)
    assert s["battery_cycles"] / terminal == pytest.approx(
        2 * eta_ch / (1 + eta_ch * eta_dis), rel=1e-3
    )


def test_simulate_performance_exports_recon_scalar():
    """Unit level: EnergySystem.simulate_performance passes the P4-18
    reconciliation scalar through, the top-up lands in import AND charge
    (not load), and the SOC is restored to soc0."""
    n = 48
    load = np.full(n, 1.0)  # constant deficit: battery drains to soc_min
    weather = {
        "hour": np.arange(n) % 24,
        "direct_radiation": np.zeros(n),
        "diffuse_radiation": np.zeros(n),
        "temperature_2m": np.full(n, 20.0),
    }
    es = EnergySystem(pv=PVSystem())
    perf = es.simulate_performance([0.0, 2.0], weather, load)
    assert "battery_recon_grid_kwh" in perf
    recon = perf["battery_recon_grid_kwh"]
    assert recon > 0.0
    flows = BatterySystem().calculate_battery_flows(-load, load, 2.0)
    assert recon == pytest.approx(flows["recon_grid_kwh"], rel=1e-12)
    # no PV -> the only charging energy is the top-up itself
    assert perf["battery_charge"].sum() == pytest.approx(recon, rel=1e-12)
    # import = unmet load + recon (recon never serves load)
    assert perf["grid_import"].sum() == pytest.approx(
        load.sum() - perf["battery_discharge"].sum() + recon, rel=1e-12
    )
    assert perf["battery_soc"][-1] == pytest.approx(0.5, abs=1e-12)


# ── export layer: new keys reach summary.csv ─────────────────────────────


def test_summary_csv_contains_new_keys(sim_609, tmp_path):
    path = os.path.join(str(tmp_path), "summary.csv")
    sim_609.save_summary_csv(path)
    with open(path, newline="", encoding="utf-8") as f:
        header = next(csv.reader(f))
    for key in ("annual_capital", "annual_ghi_kwh_m2", "battery_charge_kwh",
                "battery_recon_grid_kwh"):
        assert key in header, key
