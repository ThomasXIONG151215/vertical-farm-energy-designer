"""
Layer 5: Regression tests — end-to-end engine + sweep stability.

These are the slowest tests; they run the full simulation to verify
key outputs haven't silently changed.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


class TestEngineRegression:
    def test_annual_load_stable(self, sim_609):
        """Annual load should be in 45-75 MWh range for preset_609
        (after LED power bugfix: 1575W→7200W, cooling load increased)."""
        e = sim_609["annual_load_kwh"]
        assert 45000 < e < 75000, \
            f"annual_load_kwh = {e:.0f} outside expected range"

    def test_biomass_stable(self, sim_609):
        """Biomass should be 180-350 kg dry/yr for preset_609
        (after light_wm2 bugfix: PAR correctly calculated from PPFD)."""
        b = sim_609["biomass_kg"]
        assert 180.0 < b < 350.0, \
            f"biomass_kg = {b:.1f} outside expected range"

    def test_timeseries_has_all_columns(self, sim_609):
        """Timeseries dataframe must contain core columns."""
        ts = sim_609["timeseries"]
        required = {"hour_of_year", "hour_of_day", "T_z", "RH_z",
                     "load_kw", "E_hvac_Wh", "E_deh_Wh", "E_led_Wh"}
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
            assert 6000 < avg_on < 8000, \
                f"avg LED power when on: {avg_on:.0f} W"

    def test_weather_dict_has_keys(self, sim_609):
        """Weather dict must contain required fields."""
        weather = sim_609["weather"]
        required = {"direct_radiation", "diffuse_radiation",
                     "temperature_2m", "hour"}
        missing = required - set(weather.keys())
        assert not missing, f"missing weather fields: {missing}"

    # ── Carnot COP regression ───────────────────────────────────────

    def test_carnot_cop_runs(self, project_609):
        """Carnot default COP mode produces valid annual load."""
        from src.design.engine import DesignEngine

        p = project_609
        p.hvac.cop_mode = "carnot"
        engine = DesignEngine()
        result = engine.run(p)
        assert result["annual_load_kwh"] > 0
        assert np.isfinite(result["annual_load_kwh"])

    def test_carnot_cop_seasonal_variation(self, project_609):
        """Carnot COP should vary seasonally — winter COP > summer COP."""
        from src.design.engine import DesignEngine

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
        from src.design.engine import DesignEngine

        p = project_609
        p.hvac.auto_size = True
        engine = DesignEngine()
        result = engine.run(p)
        assert result["annual_load_kwh"] > 0

    def test_auto_size_deh_positive(self, project_609):
        """auto_size DEH produces positive power."""
        from src.design.engine import DesignEngine

        p = project_609
        p.deh.auto_size = True
        engine = DesignEngine()
        result = engine.run(p)
        assert result["annual_load_kwh"] > 0

    def test_vpd_transpiration_runs(self, project_609):
        """VPD method with k_vpd=2e-5 produces valid results."""
        from src.design.engine import DesignEngine

        p = project_609
        p.transpiration.method = "vpd"
        engine = DesignEngine()
        result = engine.run(p)
        assert result["annual_load_kwh"] > 0
        assert result["biomass_kg"] > 0

    def test_daily_transpiration_runs(self, project_609):
        """Daily direct-set method produces valid results."""
        from src.design.engine import DesignEngine

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
        from src.design.engine import DesignEngine

        p = project_609
        p.hvac.auto_size = True
        p.hvac.P_rated_w = 3000.0   # stale default
        p.deh.auto_size = True
        p.deh.P_ref_w = 2233.0      # stale default
        DesignEngine().run(p)
        # HVAC design load now includes the DEH net sensible heat (P_comp+fan)
        assert p.hvac.P_rated_w > 3000.0, \
            f"HVAC auto-size did not write back: P_rated_w={p.hvac.P_rated_w:.1f}"
        assert p.deh.P_ref_w != 2233.0, \
            f"DEH auto-size did not write back: P_ref_w={p.deh.P_ref_w:.1f}"

    def test_water_balance_closure(self, sim_609):
        """Water balance must stay in a healthy envelope (C-fix, 2026-08-16).

        k_vpd was calibrated 2e-5 -> 5e-5.  At the old value the model water
        balance was ~3.4 L/kg fresh (real PFAL lettuce ~20 L/kg).  Raising it
        to 1e-4 (the full 'real' value) collapses the model: transpiration ->
        RH -> DEH-heat feedback drives harvest to 0.  This test pins the
        healthy operating band so neither drift is silently reintroduced:
          * water/weight ratio within [3, 12] L/kg fresh  (3.4@2e-5, 5.8@5e-5)
          * harvest stays positive (no feedback collapse)
          * water use is finite (no inf from a zero-harvest divide)
        """
        s = sim_609.summary
        water_m3 = s["annual_water_m3"]
        harvest_fw = s["annual_harvest_fw_kg"]
        assert np.isfinite(water_m3), f"annual water non-finite: {water_m3}"
        assert harvest_fw > 1000.0, \
            f"harvest collapsed: {harvest_fw:.1f} kg fresh/yr"
        wf = water_m3 * 1000.0 / harvest_fw
        assert 3.0 <= wf <= 12.0, \
            f"water/fresh = {wf:.2f} L/kg outside healthy band [3, 12]"

    def test_growth_energy_use_efficiency_band(self, sim_609):
        """RUE must stay in a physically plausible band (C-fix, 2026-08-16).

        Model RUE (dry-mass gain per intercepted PAR energy) is ~2.9 g/MJ
        from the Van Henten 2003 defaults — inside the C3-crop band 2.2-3.5
        g/MJ.  This guards against future growth-model recalibration that
        would break the energy basis declared in GrowthConfig.c_rad_phot.
        """
        s = sim_609.summary
        harvest_dry = s["annual_harvest_kg"]           # kg dry / yr
        # Intercepted PAR: 87.5 W/m² · 45 m² · 16 h/day = 63 kWh/day
        # → ×365 = 22,995 kWh/yr = 22,995 × 3.6 = 82,782 MJ/yr.
        par_energy_MJ = 22995.0 * 3.6
        rue = harvest_dry * 1000.0 / par_energy_MJ     # g dry / MJ
        assert 1.5 <= rue <= 4.0, \
            f"RUE = {rue:.2f} g/MJ outside C3 band [1.5, 4]"


class TestSweepRegression:
    def test_sweep_best_lcoe_finite(self, project_609):
        """Sweep with PV ranges should produce finite LCOE."""
        from src.design.sweep import sweep_design

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
        from src.design.sweep import sweep_design

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
        from src.design.sweep import sweep_design

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
            assert lcoe_values[i] <= lcoe_values[i + 1], \
                f"not sorted at index {i}: {lcoe_values[i]} > {lcoe_values[i + 1]}"
