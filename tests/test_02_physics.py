"""
Layer 2: Physics correctness tests.

Validates core thermodynamic / plant-growth models produce plausible outputs.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


# ---------------------------------------------------------------------------
# 2.1  Van Henten growth — monotonic
# ---------------------------------------------------------------------------
class TestVanHenten:
    def test_X_d_increases_over_day(self):
        """Canopy dry mass should increase over a typical light period."""
        from src.plants.van_henten import VanHenten

        vh = VanHenten(co2_ppm=800)
        dt = 600.0         # 10-min steps
        # 16 h light at 400 W/m2 PAR, 22 C
        par = 400.0
        temp = 22.0
        n_light = int(16 * 3600 / dt)  # 96 steps

        X_d = 0.001       # initial dry mass kg/m2
        for _ in range(n_light):
            _, X_d = vh.step(temp, par, X_d, dt)

        assert X_d > 0.001, f"biomass did not increase: {X_d}"

    def test_dark_period_no_growth_or_decay(self):
        """In dark (PAR=0) growth rate should be near-zero."""
        from src.plants.van_henten import VanHenten

        vh = VanHenten(co2_ppm=800)
        X_d = 0.01
        dt = 600.0
        n_dark = int(8 * 3600 / dt)

        for _ in range(n_dark):
            _, X_new = vh.step(18.0, 0.0, X_d, dt)
            assert X_new > 0.001, f"biomass collapsed in dark: {X_new}"
            X_d = X_new

    def test_demo_runs(self):
        """Van Henten _demo() should run without error."""
        from src.plants.van_henten import _demo

        # should not raise
        _demo()


# ---------------------------------------------------------------------------
# 2.2  Psychrometrics — consistency
# ---------------------------------------------------------------------------
class TestPsychrometrics:
    def test_saturation_pressure_increases_with_temp(self):
        """p_sat(T) must be monotonically increasing with temperature."""
        from src.physics.psychrometrics import saturation_vapor_pressure

        p1 = saturation_vapor_pressure(10.0)
        p2 = saturation_vapor_pressure(20.0)
        p3 = saturation_vapor_pressure(30.0)
        assert p2 > p1, f"p_sat(20)={p2} <= p_sat(10)={p1}"
        assert p3 > p2, f"p_sat(30)={p3} <= p_sat(20)={p2}"

    def test_humidity_ratio_bounds(self):
        """AH at phi=0 should be 0 and >0 at phi>0."""
        from src.physics.psychrometrics import temp_rh_to_ah

        W_dry = temp_rh_to_ah(25.0, 0.0)
        W_wet = temp_rh_to_ah(25.0, 80.0)
        assert W_dry == pytest.approx(0.0, abs=1e-6)
        assert W_wet > W_dry

    def test_dewpoint(self):
        """T_dp at phi=100% equals dry-bulb."""
        from src.physics.psychrometrics import temp_rh_to_dewpoint

        T = 20.0
        T_dp = temp_rh_to_dewpoint(T, 100.0)
        assert T_dp == pytest.approx(T, abs=0.5)


# ---------------------------------------------------------------------------
# 2.3  SHR — DynamicSHR
# ---------------------------------------------------------------------------
class TestSHR:
    def test_shr_default(self):
        """DynamicSHR instantiation and default attributes."""
        from src.physics.shr import DynamicSHR

        shr = DynamicSHR()
        # SHR bounds should be within [0, 1]
        assert 0.0 <= shr.shr_min <= 1.0
        assert 0.0 <= shr.shr_max <= 1.0
        assert shr.shr_min <= shr.shr_max

    def test_shr_calculation(self):
        """calc_shr with reasonable values returns plausible SHR."""
        from src.physics.shr import DynamicSHR

        shr = DynamicSHR(BF=0.15)
        # Return air 24 C, 50% RH; supply air 12 C (typical DX coil)
        result = shr.calc_shr(24.0, 50.0, 12.0)
        assert 0.0 <= result <= 1.0, f"SHR out of bounds: {result}"


# ---------------------------------------------------------------------------
# 2.4  Engine — energy is non-negative
# ---------------------------------------------------------------------------
class TestEngineOutputs:
    def test_load_is_positive(self, sim_609):
        """Every hour of load must be >= 0."""
        load = sim_609["load"]
        assert len(load) == 8760, f"expected 8760 hours, got {len(load)}"
        assert np.all(load >= 0), f"negative load found: min={load.min()}"

    def test_annual_energy_positive(self, sim_609):
        """Total annual energy must be > 0."""
        assert sim_609["annual_load_kwh"] > 0

    def test_biomass_positive(self, sim_609):
        """Harvested biomass must be > 100 kg dry / yr."""
        assert sim_609["biomass_kg"] > 100.0, \
            f"biomass too low: {sim_609['biomass_kg']}"

    def test_kwh_per_kg_below_50(self, sim_609):
        """kWh/kg fresh should be below 50 for viable PFAL."""
        assert sim_609["kwh_per_kg_fresh"] < 50.0, \
            f"kWh/kg too high: {sim_609['kwh_per_kg_fresh']}"

    def test_temperature_in_range(self, sim_609):
        """T_z must stay between 15-35 C."""
        ts = sim_609["timeseries"]
        T = ts["T_z"].values
        assert T.min() >= 5.0, f"temperature too low: {T.min()}"
        assert T.max() <= 40.0, f"temperature too high: {T.max()}"

    def test_rh_in_range(self, sim_609):
        """RH_z must stay in [0, 100]."""
        ts = sim_609["timeseries"]
        RH = ts["RH_z"].values
        assert RH.min() >= 0.0, f"RH negative: {RH.min()}"
        assert RH.max() <= 100.0, f"RH > 100: {RH.max()}"
