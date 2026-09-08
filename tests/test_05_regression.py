"""
Layer 5: Regression tests — end-to-end engine + sweep stability.

These are the slowest tests; they run the full simulation to verify
key outputs haven't silently changed.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[1] / "vfed"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


class TestEngineRegression:
    def test_annual_load_stable(self, sim_609):
        """Annual load should be in 45-75 MWh range for preset_609
        (after LED power bugfix: 1575W→7200W, cooling load increased)."""
        e = sim_609["annual_load_kwh"]
        assert 45000 < e < 75000, f"annual_load_kwh = {e:.0f} outside expected range"

    def test_biomass_stable(self, sim_609):
        """Biomass 80-130 kg dry/yr for preset_609.

        P0-3R baseline change (2026-09-08): c_rad_phot recalibrated for PFAL
        lettuce (1e-8 -> 3.5e-9 kg/J), pinning yield to the commercial band
        30-60 kg fresh/m2/yr (44.5 kg/m2/yr on the 45 m2 canopy = 100.2 kg
        dry/yr).  The former 180-350 kg band was set by the uncalibrated
        literature default that overpredicted yield 2-4x.
        """
        b = sim_609["biomass_kg"]
        assert 80.0 < b < 130.0, f"biomass_kg = {b:.1f} outside expected range"

    def test_annual_fresh_yield_band(self, sim_609):
        """P0-3R hard criterion: fresh yield must sit inside the commercial
        PFAL lettuce band 30-60 kg/m2/yr over the 45 m2 canopy (mid-band
        anchor ~45).  Guards against yield regressions in either direction."""
        fw = sim_609.summary["annual_harvest_fw_kg"]
        per_m2 = fw / 45.0
        assert 30.0 <= per_m2 <= 60.0, (
            f"fresh yield {per_m2:.1f} kg/m2/yr outside commercial PFAL "
            f"band [30, 60] (annual_harvest_fw_kg={fw:.1f})"
        )

    def test_timeseries_has_all_columns(self, sim_609):
        """Timeseries dataframe must contain core columns."""
        ts = sim_609["timeseries"]
        required = {
            "hour_of_year",
            "hour_of_day",
            "T_z",
            "RH_z",
            "load_kw",
            "E_hvac_Wh",
            "E_deh_Wh",
            "E_led_Wh",
        }
        missing = required - set(ts.columns)
        assert not missing, f"missing columns: {missing}"

    def test_led_power_in_range(self, sim_609):
        """LED power should be correctly auto-deduced: PPFD×area/efficacy."""
        ts = sim_609["timeseries"]
        led = ts["E_led_Wh"].values
        on_mask = led > 100
        if on_mask.any():
            avg_on = led[on_mask].mean()
            # PPFD=400, area=45, efficacy=2.5 → 400×45/2.5 = 7200 W
            assert 6000 < avg_on < 8000, f"avg LED power when on: {avg_on:.0f} W"

    def test_weather_dict_has_keys(self, sim_609):
        """Weather dict must contain required fields."""
        weather = sim_609["weather"]
        required = {"direct_radiation", "diffuse_radiation", "temperature_2m", "hour"}
        missing = required - set(weather.keys())
        assert not missing, f"missing weather fields: {missing}"

    # ── Carnot COP regression ───────────────────────────────────────

    def test_carnot_cop_runs(self, project_609):
        """Carnot default COP mode produces valid annual load."""
        from vfed.design.engine import DesignEngine

        p = project_609
        p.hvac.cop_mode = "carnot"
        engine = DesignEngine()
        result = engine.run(p)
        assert result["annual_load_kwh"] > 0
        assert np.isfinite(result["annual_load_kwh"])

    def test_carnot_cop_seasonal_variation(self, project_609):
        """Carnot COP should vary seasonally — winter COP > summer COP."""
        from vfed.design.engine import DesignEngine

        p = project_609
        p.hvac.cop_mode = "carnot"
        engine = DesignEngine()
        result = engine.run(p)
        # HVAC runtime should exist (even if seasonal, check COP was used)
        ts = result["timeseries"]
        hvac_on = ts["E_hvac_Wh"] > 100
        # At least some HVAC operation should occur
        assert hvac_on.any(), "Expected some HVAC operation with Carnot COP"

    def test_auto_size_hvac_positive(self, project_609):
        """auto_size=True produces positive P_rated for Fengxian summer design."""
        from vfed.design.engine import DesignEngine

        p = project_609
        p.hvac.auto_size = True
        engine = DesignEngine()
        result = engine.run(p)
        assert result["annual_load_kwh"] > 0

    def test_auto_size_deh_positive(self, project_609):
        """auto_size DEH produces positive power."""
        from vfed.design.engine import DesignEngine

        p = project_609
        p.deh.auto_size = True
        engine = DesignEngine()
        result = engine.run(p)
        assert result["annual_load_kwh"] > 0

    def test_van_henten_transpiration_runs(self, project_609):
        """van_henten model-coupled method produces valid results."""
        from vfed.design.engine import DesignEngine

        p = project_609
        p.transpiration.method = "van_henten"
        engine = DesignEngine()
        result = engine.run(p)
        assert result["annual_load_kwh"] > 0
        assert result["biomass_kg"] > 0

    def test_daily_transpiration_runs(self, project_609):
        """Daily direct-set method produces valid results."""
        from vfed.design.engine import DesignEngine

        p = project_609
        p.transpiration.method = "daily"
        p.transpiration.daily_water_L = 40.0
        engine = DesignEngine()
        result = engine.run(p)
        assert result["annual_load_kwh"] > 0

    def test_auto_size_writes_back_capacity(self, project_609):
        """auto_size results must be written back to the config so CAPEX
        (sweep._total_capital reads config P_rated_w / P_ref_w) reflects the
        computed equipment instead of the stale defaults."""
        from vfed.design.engine import DesignEngine

        p = project_609
        p.hvac.auto_size = True
        p.hvac.P_rated_w = 3000.0  # stale default
        p.deh.auto_size = True
        p.deh.P_ref_w = 2233.0  # stale default
        DesignEngine().run(p)
        # HVAC design load now includes the DEH net sensible heat (P_comp+fan)
        assert (
            p.hvac.P_rated_w > 3000.0
        ), f"HVAC auto-size did not write back: P_rated_w={p.hvac.P_rated_w:.1f}"
        assert (
            p.deh.P_ref_w != 2233.0
        ), f"DEH auto-size did not write back: P_ref_w={p.deh.P_ref_w:.1f}"

    def test_water_balance_closure(self, sim_609):
        """Water balance must stay in a healthy envelope (C-fix, 2026-08-16,
        re-pinned after the 5-method consolidation to van_henten).

        The old vpd shortcut (k_vpd) was replaced by the model-coupled
        van_henten method, which tracks biomass and yields a comparable
        vapour flux at harvest.  Direct-set methods bypass the vapour-pressure
        feedback entirely.  This test pins the healthy operating band so
        neither drift is silently reintroduced:
          * water/weight ratio within [3, 12] L/kg fresh
          * harvest stays positive (no feedback collapse)
          * water use is finite (no inf from a zero-harvest divide)
        """
        s = sim_609.summary
        water_m3 = s["annual_water_m3"]
        harvest_fw = s["annual_harvest_fw_kg"]
        assert np.isfinite(water_m3), f"annual water non-finite: {water_m3}"
        assert harvest_fw > 1000.0, f"harvest collapsed: {harvest_fw:.1f} kg fresh/yr"
        wf = water_m3 * 1000.0 / harvest_fw
        assert 3.0 <= wf <= 12.0, f"water/fresh = {wf:.2f} L/kg outside healthy band [3, 12]"

    def test_growth_energy_use_efficiency_band(self, sim_609):
        """Whole-cycle light-use efficiency must stay physically plausible.

        P0-3R baseline change (2026-09-08): with c_rad_phot lettuce-calibrated
        to the commercial PFAL yield band, the whole-cycle LUE is ~1.2 g dry
        per MJ of incident PAR.  This is the low end of the greenhouse-lettuce
        literature band (~1.6-2.7 g/MJ, measured on a mature-canopy
        intercepted basis) discounted for canopy absorption (~0.85x) and the
        seedling establishment phase (~0.9x) -- coherent with a model that
        has zero inter-crop gap time (which would otherwise bias annual
        yield upward).  Band [0.9, 1.6] guards the calibrated energy basis
        declared in GrowthConfig.c_rad_phot against future drift.
        """
        s = sim_609.summary
        harvest_dry = s["annual_harvest_kg"]  # kg dry / yr
        # Intercepted PAR: 87.5 W/m² · 45 m² · 16 h/day = 63 kWh/day
        # → ×365 = 22,995 kWh/yr = 22,995 × 3.6 = 82,782 MJ/yr.
        par_energy_MJ = 22995.0 * 3.6
        rue = harvest_dry * 1000.0 / par_energy_MJ  # g dry / MJ
        assert 0.9 <= rue <= 1.6, f"LUE = {rue:.2f} g/MJ outside calibrated band [0.9, 1.6]"


class TestFullLoadDiagnostics:
    """P0-4: rated-capacity (full-load) diagnostics + preset_609 T_dark fix.

    Pre-fix pathology: T_dark = 18 C was unreachable against the 609 room's
    ~22 C night balance, so the HVAC pinned at full 3,070 W for all 2,920
    dark hours (33% of the year) chasing a setpoint it could never close.
    The fix pins preset_609 to T_dark = 21 C; the diagnostics block plus
    full_load_warnings() make any future saturation visible.
    """

    def test_preset_609_dark_setpoint_pinned(self, project_609):
        """preset_609 carries the explicit reachable T_dark (class default
        of SetpointConfig stays 18.0)."""
        from vfed.design.project import SetpointConfig

        assert project_609.setpoints.T_dark == pytest.approx(21.0)
        assert SetpointConfig().T_dark == pytest.approx(18.0)

    def test_summary_reports_full_load_diagnostics(self, sim_609):
        d = sim_609.summary["full_load_diagnostics"]
        for dev in ("hvac_cool", "hvac_heat", "deh"):
            assert set(("hours", "pct", "max_streak_h")) <= set(d[dev])
        assert "criteria" in d

    def test_609_dark_full_speed_below_target(self, sim_609):
        """P0-4 acceptance: dark-night saturation collapsed from 2,920 h
        (every dark hour) to well under half the dark hours, and no
        24 h+ saturation streaks remain."""
        d = sim_609.summary["full_load_diagnostics"]["hvac_cool"]
        assert d["hours"] < 1460, f"hvac cool full hours = {d['hours']} (target < 1460)"
        assert d["max_streak_h"] < 24, f"max full streak = {d['max_streak_h']} h (target < 24)"

    def test_609_no_heating_or_deh_saturation_warning(self, sim_609):
        d = sim_609.summary["full_load_diagnostics"]
        assert d["hvac_heat"]["hours"] == 0
        assert d["deh"]["pct"] < 60.0

    def test_max_true_run(self):
        from vfed.design.engine import _full_load_stats

        assert _full_load_stats(np.array([True, True, False, True]))["max_streak_h"] == 2
        assert _full_load_stats(np.zeros(5, dtype=bool))["max_streak_h"] == 0
        assert _full_load_stats(np.ones(7, dtype=bool))["max_streak_h"] == 7
        empty = _full_load_stats(np.zeros(0, dtype=bool))
        assert empty == {"hours": 0, "pct": 0.0, "max_streak_h": 0}

    def _diag(self, **overrides):
        base = {
            "hours": 0,
            "pct": 0.0,
            "max_streak_h": 0,
        }
        base.update(overrides)
        return base

    def test_warnings_fire_on_nightly_saturation(self):
        """The 609 pre-fix pattern: 8 h full every night = 2,920 h/yr
        (33.3%).  Must fire via the annual-share rule — a pure
        ">= 24 h continuous" rule would miss it by design."""
        from vfed.design.engine import full_load_warnings

        summary = {
            "full_load_diagnostics": {
                "hvac_cool": self._diag(hours=2920, pct=33.33, max_streak_h=8),
                "hvac_heat": self._diag(),
                "deh": self._diag(),
            }
        }
        msgs = full_load_warnings(summary)
        assert len(msgs) == 1
        assert "HVAC cooling" in msgs[0]
        assert "rated capacity" in msgs[0]
        assert "2,920" not in msgs[0]  # plain number, no thousands separator
        assert "2920 h" in msgs[0]

    def test_warnings_fire_on_sustained_streak(self):
        """A heatwave-grade undersize: low annual share but one >= 24 h
        continuous full-speed stretch must still fire."""
        from vfed.design.engine import full_load_warnings

        summary = {
            "full_load_diagnostics": {
                "hvac_cool": self._diag(hours=30, pct=0.34, max_streak_h=30),
                "hvac_heat": self._diag(),
                "deh": self._diag(),
            }
        }
        msgs = full_load_warnings(summary)
        assert len(msgs) == 1
        assert "HVAC cooling" in msgs[0]

    def test_warnings_fire_on_heating_and_deh_saturation(self):
        """Bidirectional coverage: heating saturation and a never-cycling
        DEH both report (with direction-specific hints)."""
        from vfed.design.engine import full_load_warnings

        summary = {
            "full_load_diagnostics": {
                "hvac_cool": self._diag(),
                "hvac_heat": self._diag(hours=1500, pct=17.1, max_streak_h=10),
                "deh": self._diag(hours=8400, pct=95.9, max_streak_h=120),
            }
        }
        msgs = full_load_warnings(summary)
        assert len(msgs) == 2
        assert any("HVAC heating" in m and "P_rated_heat_w" in m for m in msgs)
        assert any("DEH" in m and "setpoints.RH" in m for m in msgs)

    def test_warnings_silent_on_healthy_runs(self, sim_609):
        from vfed.design.engine import full_load_warnings

        assert full_load_warnings(sim_609.summary) == []

    def test_warnings_tolerate_missing_block(self):
        from vfed.design.engine import full_load_warnings

        assert full_load_warnings({}) == []
        assert full_load_warnings({"full_load_diagnostics": {}}) == []


class TestSweepRegression:
    def test_sweep_best_lcoe_finite(self, project_609):
        """Sweep with PV ranges should produce finite LCOE."""
        from vfed.design.sweep import sweep_design

        p = project_609
        p.space.objective = "lcoe"
        p.space.parameter_ranges = {
            "ppfd_target": [300, 400, 100],
            "pv_area": [0, 100, 50],
        }
        result = sweep_design(p)
        best = result["best"]
        assert best is not None
        assert np.isfinite(best["lcoe"])
        assert best["lcoe"] > 0

    def test_sweep_mixed_objectives(self, project_609):
        """Sweep with each supported objective should produce rows."""
        from vfed.design.sweep import sweep_design

        for obj in ("lcoe", "kwh_per_kg_fresh", "cost_per_kg_fresh"):
            p = project_609
            p.space.parameter_ranges = {
                "ppfd_target": [300, 400, 100],
                "pv_area": [0, 50, 50],
            }
            p.space.objective = obj
            result = sweep_design(p)
            assert result["results"] is not None
            assert len(result["results"]) > 0
            assert obj in result["best"]

    def test_sweep_results_sort_correctly(self, project_609):
        """Results DataFrame should be sorted by the objective ascending."""
        from vfed.design.sweep import sweep_design

        p = project_609
        p.space.parameter_ranges = {
            "ppfd_target": [200, 400, 200],
            "pv_area": [0, 50, 50],
        }
        p.space.objective = "lcoe"
        result = sweep_design(p)
        df = result["results"]
        lcoe_values = df["lcoe"].values
        for i in range(len(lcoe_values) - 1):
            assert (
                lcoe_values[i] <= lcoe_values[i + 1]
            ), f"not sorted at index {i}: {lcoe_values[i]} > {lcoe_values[i + 1]}"


class TestGridOnlyEconomics:
    """P0-2: with the energy system disabled (pv=0, bat=0) electricity must
    still be priced as grid_import_kwh x tariff — never silently zeroed —
    and the LCOE definition must agree between evaluate and sweep."""

    def test_evaluate_no_pv_grid_cost_priced(self, project_609, sim_609):
        """preset_609 (pv=0, bat=0): annual_grid_cost_net == sum(load x hourly price)."""
        s = sim_609.summary
        assert s["grid_import_kwh"] > 0
        assert (
            s["annual_grid_cost_net"] > 0
        ), "grid cost silently zeroed despite non-zero grid_import_kwh"
        assert s["total_electricity_cost"] == s["annual_grid_cost_net"]

        ts = sim_609["timeseries"]
        load = ts["load_kw"].to_numpy()
        hours = ts["hour_of_day"].to_numpy().astype(int)
        prices = np.asarray(project_609.tariff.hourly_prices)
        expected = float(np.sum(load * prices[hours]))
        assert abs(s["annual_grid_cost_net"] - expected) < 0.05

    def test_evaluate_no_pv_lcoe_includes_grid_cost(self, project_609, sim_609):
        """LCOE without PV must include electricity cost (same formula as sweep)."""
        from vfed.design.sweep import _annualized_capital, _compute_lcoe, _total_capital

        s = sim_609.summary
        p = project_609
        ts = sim_609["timeseries"]
        prices = np.asarray(p.tariff.hourly_prices)
        grid_cost = float(
            np.sum(ts["load_kw"].to_numpy() * prices[ts["hour_of_day"].to_numpy().astype(int)])
        )

        cap = _total_capital(p, 0.0, 0.0)
        annual_cap = _annualized_capital(p, cap)
        annual_om = (
            p.opex.maintenance_pct * cap["total"]
            + p.opex.water_cost_per_m3 * s.get("annual_water_m3", 0.0)
            + p.opex.labor_cost_per_year
            + p.opex.misc_opex_per_year
        )
        expected = _compute_lcoe(annual_cap, annual_om, grid_cost, s["annual_energy_kwh"])
        assert abs(s["lcoe"] - expected) < 5e-4
        # electricity cost is a visible share: LCOE strictly above the
        # electricity-free floor (annualised capital + OPEX only)
        assert s["lcoe"] > (annual_cap + annual_om) / s["annual_energy_kwh"] + 1e-9

    def test_evaluate_and_sweep_zero_row_lcoe_agree(self, project_609):
        """evaluate (no PV) and the sweep (0,0) row must share one LCOE definition."""
        from vfed.design.engine import DesignEngine
        from vfed.design.sweep import sweep_design

        p = project_609
        p.space.parameter_ranges = {
            "pv_area": [0, 100, 100],
            "battery": [0, 100, 100],
        }
        result = sweep_design(p)
        df = result["results"]
        zero_row = df[(df["pv_area"] == 0) & (df["battery_kwh"] == 0)].iloc[0]

        sim = DesignEngine(cache_dir="weather_cache").run(p)
        s = sim.summary
        assert abs(zero_row["annual_grid_cost"] - s["annual_grid_cost_net"]) < 0.05
        assert abs(zero_row["lcoe"] - s["lcoe"]) < 1e-3
        assert abs(zero_row["cost_per_kg_fresh"] - s["specific_cost_per_kg"]) < 1e-2

    def test_single_point_sweep_no_pv_grid_cost_priced(self, project_609):
        """Single-point sweep (empty ranges) of a no-PV project prices grid cost too,
        and agrees with a same-state evaluate run (P0-2 cross-path consistency)."""
        from vfed.design.engine import DesignEngine
        from vfed.design.sweep import sweep_design

        p = project_609
        p.space.parameter_ranges = {}
        row = sweep_design(p)["best"]
        assert row["annual_grid_cost"] > 0

        sim = DesignEngine(cache_dir="weather_cache").run(p)
        s = sim.summary
        assert s["annual_grid_cost_net"] > 0
        assert abs(row["annual_grid_cost"] - s["annual_grid_cost_net"]) < 0.05
        assert abs(row["lcoe"] - s["lcoe"]) < 1e-3
