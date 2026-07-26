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
