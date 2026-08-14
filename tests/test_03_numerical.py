"""
Layer 3: Numerical guardrails — DIV/0, CRF, transpiration fallback.

Tests that numerical edge cases produce errors (not silent wrong values).
"""
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from src.design.sweep import _crf


# ---------------------------------------------------------------------------
# 3.1  CRF — zero interest rate
# ---------------------------------------------------------------------------
class TestCRF:
    def test_zero_interest(self):
        """CRF(i=0, n) = 1/n."""
        assert _crf(0.0, 25.0) == pytest.approx(1.0 / 25, rel=0.01)

    def test_near_zero_interest(self):
        """CRF should not explode for tiny i."""
        crf = _crf(1e-10, 15.0)
        assert crf == pytest.approx(1.0 / 15, rel=1e-6)

    def test_normal_interest(self):
        """CRF(i=0.06, n=25) ≈ 0.0782."""
        crf = _crf(0.06, 25.0)
        assert crf == pytest.approx(0.0782, rel=1e-3)

    def test_one_year(self):
        """CRF for 1-year = 1 + i."""
        assert _crf(0.05, 1.0) == pytest.approx(1.05, rel=0.01)

    def test_negative_interest_returns_finite(self):
        """CRF with negative interest should still return a finite number."""
        crf = _crf(-0.01, 25.0)
        assert np.isfinite(crf)


# ---------------------------------------------------------------------------
# 3.2  kwh_per_kg — zero biomass guard
# ---------------------------------------------------------------------------
class TestKwhPerKg:
    def test_kwh_per_kg_finite(self, sim_609):
        """kwh_per_kg must be finite (not inf/nan)."""
        assert np.isfinite(sim_609["kwh_per_kg"]), \
            f"kwh_per_kg is {sim_609['kwh_per_kg']}"

    def test_kwh_per_kg_fresh_finite(self, sim_609):
        """kwh_per_kg_fresh must be finite."""
        assert np.isfinite(sim_609["kwh_per_kg_fresh"]), \
            f"kwh_per_kg_fresh is {sim_609['kwh_per_kg_fresh']}"

    def test_kwh_per_kg_ratio(self):
        """Dry / fresh should be roughly 20:1 (5% DM convention)."""
        from src.design.engine import DesignEngine
        from src.design.presets import preset_609

        p = preset_609()
        engine = DesignEngine()
        sim = engine.run(p)
        ratio = sim["kwh_per_kg"] / max(sim["kwh_per_kg_fresh"], 1e-9)
        assert ratio == pytest.approx(20.0, rel=0.05), \
            f"dry/fresh ratio = {ratio} (expected ~20)"


# ---------------------------------------------------------------------------
# 3.3  Transpiration — unknown method
# ---------------------------------------------------------------------------
def test_transpiration_unknown_method_returns_zero():
    """Unknown transpiration method should silently return 0.0 (current behaviour)."""
    from src.plants.transpiration import TranspirationModel

    tm = TranspirationModel(method="flute_serenade", area_m2=45.0)
    result = tm.step(T_z=22.0, RH_z=65.0, is_light=True, dt=600.0)
    assert result == 0.0


# ---------------------------------------------------------------------------
# 3.4  Humidity ODE — clamps must never be silent (P0)
# ---------------------------------------------------------------------------
class TestHumidityODEClamps:
    """step_humidity [0, W_sat] clamps must (a) keep W >= 0, (b) report the
    clipped water mass so the engine can preserve the energy balance, and
    (c) keep the legacy float-return signature working."""

    AIR_MASS = 200.0 * 1.2  # default V_room x rho_air = 240 kg

    def _solver(self, V_room=200.0, rho_air=1.2, P_atm=101.325):
        from src.physics.ode import RoomODESolver
        return RoomODESolver(C_z=1000.0, V_room=V_room, rho_air=rho_air, P_atm=P_atm)

    def test_floor_clamp_reports_clipped_water(self):
        """Over-dehumidification must clamp W to 0 AND report the phantom
        water (0.004 kg/kg - 0.005 kg/kg step -> 0.24 kg) instead of silently
        destroying it."""
        s = self._solver()
        W_new, meta = s.step_humidity(
            0.004, -0.002, T_z=22.0, dt=600.0, return_meta=True)
        assert W_new == 0.0
        assert meta["floor_clipped_kg"] == pytest.approx(0.24, rel=1e-9)
        assert meta["sat_clipped_kg"] == 0.0

    def test_saturation_cap_reports_condensed_water(self):
        """W above W_sat(T) must be capped to W_sat AND report the condensed
        water instead of silently discarding it."""
        from src.physics.psychrometrics import saturation_vapor_pressure

        s = self._solver()
        W_sat = 0.622 * saturation_vapor_pressure(25.0) / (
            101.325 - saturation_vapor_pressure(25.0))
        W_new, meta = s.step_humidity(
            0.05, 0.0, T_z=25.0, dt=600.0, return_meta=True)
        assert W_new == pytest.approx(W_sat, rel=1e-9)
        assert meta["sat_clipped_kg"] == pytest.approx(
            (0.05 - W_sat) * self.AIR_MASS, rel=1e-9)
        assert meta["floor_clipped_kg"] == 0.0

    def test_mass_conservation_books_clip_as_water(self):
        """Bookkeeping identity: unclamped state == clamped state
        + (sat_clipped - floor_clipped)/air_mass.  This is the exact invariant
        the engine uses to recover the latent heat of the clipped water
        (q_corr = (sat_clipped - floor_clipped) * L_v)."""
        s = self._solver()
        W_z, M, T, dt = 0.004, -0.002, 22.0, 600.0
        unclamped = W_z + M * dt / self.AIR_MASS
        W_new, meta = s.step_humidity(
            W_z, M, T_z=T, dt=dt, return_meta=True)
        bookkeeping = W_new + (meta["sat_clipped_kg"]
                               - meta["floor_clipped_kg"]) / self.AIR_MASS
        assert bookkeeping == pytest.approx(unclamped, rel=1e-12)

    def test_never_negative_for_any_input(self):
        """Even a violent over-dehumidification must never yield a negative
        humidity state (regression guard for the reported bug)."""
        s = self._solver(V_room=50.0)  # tiny room -> very strong removal
        W_new, _ = s.step_humidity(
            0.001, -0.005, T_z=22.0, dt=600.0, return_meta=True)
        assert W_new >= 0.0

    def test_legacy_signature_still_returns_float(self):
        """Without return_meta the API keeps returning a plain float."""
        s = self._solver()
        out = s.step_humidity(0.004, -0.002, T_z=22.0, dt=600.0)
        assert isinstance(out, float)
        assert out == 0.0


# ---------------------------------------------------------------------------
# 3.5  Psychrometrics public-function guards (P1-1)
# ---------------------------------------------------------------------------
class TestPsychrometricsGuards:
    def test_saturation_vapor_pressure_rejects_extreme_temps(self):
        """Magnus formula is only valid in a bounded temperature range;
        out-of-range inputs must raise instead of dividing by zero / overflowing."""
        from src.physics.psychrometrics import saturation_vapor_pressure

        with pytest.raises(ValueError):
            saturation_vapor_pressure(-300.0)   # would ZeroDivisionError at -237.3
        with pytest.raises(ValueError):
            saturation_vapor_pressure(150.0)    # beyond validity / p_sat >= P_atm

    def test_ah_to_temp_rh_rejects_negative_ah(self):
        """Negative absolute humidity must raise, not silently emit a fake
        positive RH (p_vapor changes sign when ah < -0.622)."""
        from src.physics.psychrometrics import ah_to_temp_rh

        with pytest.raises(ValueError):
            ah_to_temp_rh(22.0, -0.001)

    def test_temp_rh_to_ah_clamps_out_of_range_rh(self):
        """Negative RH input would previously yield negative AH; it is now
        clamped to [0, 100] (defensive: engine always passes in-range RH)."""
        from src.physics.psychrometrics import temp_rh_to_ah

        assert temp_rh_to_ah(25.0, -10.0) == 0.0
        assert temp_rh_to_ah(25.0, 150.0) == pytest.approx(
            temp_rh_to_ah(25.0, 100.0), rel=1e-9)


# ---------------------------------------------------------------------------
# 3.6  Config validation — negative humidity coefficients rejected (P1-2)
# ---------------------------------------------------------------------------
class TestConfigValidation:
    def test_negative_stage_factor_rejected(self):
        """A negative stage_factor silently flips transpiration into a moisture
        sink; from_dict must reject it."""
        from src.design.project import DesignProject

        with pytest.raises(ValueError, match="transpiration.stage_factor"):
            DesignProject.from_dict({"transpiration": {"stage_factor": -1.0}})

    def test_negative_smer_rejected(self):
        """A negative SMER would make the dehumidifier 'inject' water."""
        from src.design.project import DesignProject

        with pytest.raises(ValueError, match="deh.smer"):
            DesignProject.from_dict({"deh": {"smer": -2.0}})

    def test_rh_out_of_range_rejected(self):
        from src.design.project import DesignProject

        with pytest.raises(ValueError, match="setpoints.RH"):
            DesignProject.from_dict({"setpoints": {"RH": 120.0}})

    def test_empty_dict_uses_sane_defaults(self):
        from src.design.project import DesignProject

        p = DesignProject.from_dict({})
        assert p.transpiration.stage_factor == 1.0
        assert p.deh.smer == 2.0
        assert p.setpoints.RH == 65.0


# ---------------------------------------------------------------------------
# 3.7  Engine-level regression — no negative RH, clamps reported (P0)
# ---------------------------------------------------------------------------
def test_engine_over_dehumidification_never_negative_rh():
    """Small room + low RH setpoint + aggressive latent removal is the exact
    configuration that previously drove the humidity intermediate state
    negative. The engine must (a) never output RH < 0 and (b) report the
    floor-clamp events in the summary instead of hiding them."""
    import pandas as pd

    from src.design.engine import DesignEngine
    from src.design.presets import preset_609

    p = preset_609()
    p.envelope.V_room = 80.0
    p.envelope.C_z = 50000.0
    p.setpoints.RH = 40.0
    p.deh.P_ref_w = 3000.0
    p.hvac.P_rated_w = 3000.0

    # Deterministic synthetic weather: hot & dry outdoor all year.
    idx = pd.date_range("2026-01-01", periods=8760, freq="h", tz="UTC")
    weather = pd.DataFrame({
        "temperature_2m": 30.0,
        "relative_humidity_2m": 30.0,
        "shortwave_radiation": 0.0,
        "direct_radiation": 0.0,
        "diffuse_radiation": 0.0,
        "surface_pressure": 1013.25,
    }, index=idx)

    sim = DesignEngine().run(p, weather=weather)
    ts = sim.timeseries

    assert float(np.min(ts["RH_z"])) >= 0.0
    stats = sim.summary["moisture_clamp_stats"]
    assert set(stats.keys()) == {
        "floor_clip_events", "floor_clip_water_kg",
        "sat_clip_events", "sat_clip_water_kg",
    }
    # With inventory-capped removal the ODE floor clamp no longer fires from
    # device over-dehumidification (the flow itself is capped first).  The
    # limitation is now reported through the dehumidifier performance stats.
    assert stats["floor_clip_events"] >= 0
    assert stats["floor_clip_water_kg"] >= 0.0
    assert stats["sat_clip_water_kg"] >= 0.0
    perf = sim.summary["dehumidifier_performance"]
    assert perf["removal_limited_events"] > 0
    assert perf["removal_limited_water_kg"] > 0.0


# ---------------------------------------------------------------------------
# 3.8  Actual-dehumidification accounting — devices capped to vapour inventory
# ---------------------------------------------------------------------------
def test_limit_removal_by_inventory():
    """Nominal DEH/HVAC removal is capped to the room vapour inventory; the
    same scale factor applies to both devices so their ratio is preserved."""
    from src.design.engine import _limit_removal_by_inventory

    air_mass = 240.0  # V=200 × rho=1.2

    # Unconstrained: removal below inventory → unchanged.
    d, h, s = _limit_removal_by_inventory(0.001, 0.001, 0.01, air_mass, 600.0)
    assert (d, h, s) == (0.001, 0.001, 1.0)

    # Constrained: available = W_z*air_mass/dt = 0.004*240/600 = 1.6e-3 kg/s.
    d, h, s = _limit_removal_by_inventory(0.002, 0.001, 0.004, air_mass, 600.0)
    assert abs(s - 1.6e-3 / 3.0e-3) < 1e-12
    assert abs(d - 0.002 * s) < 1e-12
    assert abs(h - 0.001 * s) < 1e-12

    # Zero inventory → full clamp to zero removal.
    d, h, s = _limit_removal_by_inventory(0.002, 0.001, 0.0, air_mass, 600.0)
    assert (d, h, s) == (0.0, 0.0, 0.0)

    # No removal requested / invalid dt → scale stays 1.
    assert _limit_removal_by_inventory(0.0, 0.0, 0.01, air_mass, 600.0) == (0.0, 0.0, 1.0)
    assert _limit_removal_by_inventory(0.001, 0.001, 0.01, air_mass, 0.0)[2] == 1.0


def test_engine_reports_actual_dehumidification():
    """summary['dehumidifier_performance'] must expose nominal vs actual
    moisture removal and a utilization ratio, with actual <= nominal always."""
    import pandas as pd

    from src.design.engine import DesignEngine
    from src.design.presets import preset_609

    p = preset_609()
    p.envelope.V_room = 80.0
    p.envelope.C_z = 50000.0
    p.setpoints.RH = 40.0
    p.deh.P_ref_w = 3000.0
    p.hvac.P_rated_w = 3000.0

    idx = pd.date_range("2026-01-01", periods=8760, freq="h", tz="UTC")
    weather = pd.DataFrame({
        "temperature_2m": 30.0,
        "relative_humidity_2m": 30.0,
        "shortwave_radiation": 0.0,
        "direct_radiation": 0.0,
        "diffuse_radiation": 0.0,
        "surface_pressure": 1013.25,
    }, index=idx)

    sim = DesignEngine().run(p, weather=weather)
    perf = sim.summary["dehumidifier_performance"]

    assert set(perf.keys()) == {
        "deh_nominal_dehum_kg", "deh_actual_dehum_kg",
        "hvac_nominal_dehum_kg", "hvac_actual_dehum_kg",
        "removal_limited_events", "removal_limited_water_kg",
        "deh_utilization",
    }
    assert 0.0 <= perf["deh_actual_dehum_kg"] <= perf["deh_nominal_dehum_kg"]
    assert 0.0 <= perf["hvac_actual_dehum_kg"] <= perf["hvac_nominal_dehum_kg"]
    assert 0.0 <= perf["deh_utilization"] <= 1.0
    assert perf["removal_limited_events"] > 0
    assert perf["removal_limited_water_kg"] > 0.0
    assert perf["removal_limited_water_kg"] <= (
        perf["deh_nominal_dehum_kg"] + perf["hvac_nominal_dehum_kg"])


# ---------------------------------------------------------------------------
# 3.9  A-level fixes: Penman–Monteith units, Van Henten high-T singularity,
#      psychrometrics station-pressure parameterisation
# ---------------------------------------------------------------------------
def test_stomatal_pm_unit_invariance():
    """Penman–Monteith is invariant to the *consistent* pressure unit: the
    all-kPa (Δ, γ, VPD all in kPa) and all-Pa representations give identical
    λE.  Guards against a future regression that mixes VPD(Pa) with Δ, γ in
    kPa, which would overstate the aerodynamic term by 1000×."""
    from src.plants.transpiration import TranspirationModel
    from src.physics.psychrometrics import (
        saturation_vapor_pressure, compute_vpd)

    T, RH = 25.0, 50.0
    model = TranspirationModel(method="stomatal", area_m2=45.0)
    E_model = model.step(T, RH, True, 600.0)          # all terms in kPa

    e_sat = saturation_vapor_pressure(T)              # kPa
    delta = 4098.0 * e_sat / (T + 237.3) ** 2         # kPa/K
    gamma = 0.0655                                    # kPa/K
    vpd = compute_vpd(T, RH)                          # kPa
    r_a = max(1.0, model.r_a)
    r_s = 1.0 / max(1e-9, model.g_stomata)
    rho_cp = model.rho_cp()
    R_n = model.r_n_canopy * 1.0                      # light on

    numerator = delta * R_n + rho_cp * max(0.0, vpd) / r_a
    denominator = delta + gamma * (1.0 + r_s / r_a)
    E_hand = (numerator / denominator) / model.h_fg * model.area_m2

    assert E_model == pytest.approx(E_hand, rel=1e-9)

    # All-Pa recomputation (every pressure term ×1000) → identical λE.
    num_pa = (delta * 1000.0) * R_n + rho_cp * (vpd * 1000.0) / r_a
    den_pa = (delta * 1000.0) + (gamma * 1000.0) * (1.0 + r_s / r_a)
    assert (num_pa / den_pa) == pytest.approx(numerator / denominator, rel=1e-12)

    # The *wrong* mixed-unit version (VPD in Pa only) must be clearly
    # distinguishable from the correct result — the regression signature.
    num_mixed = delta * R_n + rho_cp * (vpd * 1000.0) / r_a
    assert abs(num_mixed / denominator - numerator / denominator) > 1.0


def test_van_henten_high_temp_no_singularity():
    """Above ~42 °C the CO₂-response quadratic turns negative and the
    photosynthesis denominator crosses zero (~44.5 °C).  Net photosynthesis
    must stop cleanly (return 0) instead of flipping sign / blowing up and
    collapsing the biomass state."""
    from src.plants.van_henten import VanHenten

    grow = VanHenten(co2_ppm=800)

    # T=50 °C: co2_term < 0 → photosynthesis returns 0, growth = -respiration.
    assert grow._phi_phot_c(X_d=0.05, T_z=50.0, light=87.5) == 0.0

    dX_d, X_d_new = grow.step(T_z=50.0, light=87.5, X_d=0.05, dt=600.0)
    assert np.isfinite(dX_d) and np.isfinite(X_d_new)
    assert dX_d < 0.0                     # respiration only — no collapse
    assert X_d_new == pytest.approx(0.05 + dX_d * 600.0, rel=1e-9)
    assert X_d_new > 0.0

    # Around the former singularity nothing blows up or NaNs.
    for T in (42.0, 43.0, 44.0, 44.5, 45.0, 46.0):
        dd, xnew = grow.step(T_z=T, light=87.5, X_d=0.05, dt=600.0)
        assert np.isfinite(dd) and np.isfinite(xnew)
        assert xnew >= 0.0
        assert dd <= 1e-6                 # no spurious growth burst

    # Positive control: normal growing temperature still photosynthesis.
    dX_good, _ = grow.step(T_z=22.0, light=87.5, X_d=0.05, dt=600.0)
    assert dX_good > 0.0


def test_psychrometrics_pressure_parameterization():
    """temp_rh_to_ah / ah_to_temp_rh accept an explicit station pressure;
    lower pressure (higher altitude) raises AH for the same RH."""
    from src.physics.psychrometrics import (
        temp_rh_to_ah, ah_to_temp_rh, saturation_vapor_pressure)

    pv = saturation_vapor_pressure(25.0) * 0.5
    w_sea = 0.622 * pv / (101.325 - pv)
    w_alt = 0.622 * pv / (95.0 - pv)

    assert temp_rh_to_ah(25.0, 50.0) == pytest.approx(w_sea, rel=1e-12)
    assert temp_rh_to_ah(25.0, 50.0, pressure_kpa=95.0) == pytest.approx(w_alt, rel=1e-12)
    assert w_alt > w_sea

    # Default argument keeps the legacy behaviour.
    assert temp_rh_to_ah(25.0, 50.0, pressure_kpa=101.325) == pytest.approx(w_sea, rel=1e-12)

    # Round-trip inverse at altitude.
    assert ah_to_temp_rh(25.0, w_alt, pressure_kpa=95.0) == pytest.approx(50.0, abs=1e-9)


def test_engine_altitude_pressure_consistent():
    """A low surface-pressure run (950 hPa ≈ 0.6 km altitude) must convert
    AH↔RH with the actual P_atm everywhere and never emit negative RH."""
    import pandas as pd

    from src.design.engine import DesignEngine
    from src.design.presets import preset_609

    p = preset_609()
    p.envelope.V_room = 80.0
    p.envelope.C_z = 50000.0

    idx = pd.date_range("2026-01-01", periods=8760, freq="h", tz="UTC")
    weather = pd.DataFrame({
        "temperature_2m": 20.0,
        "relative_humidity_2m": 60.0,
        "shortwave_radiation": 0.0,
        "direct_radiation": 0.0,
        "diffuse_radiation": 0.0,
        "surface_pressure": 950.0,
    }, index=idx)

    sim = DesignEngine().run(p, weather=weather)
    ts = sim.timeseries
    assert float(np.min(ts["RH_z"])) >= 0.0
    assert float(np.max(ts["RH_z"])) <= 100.0
    assert np.all(np.isfinite(ts["RH_z"]))


# ---------------------------------------------------------------------------
# 3.11  B-level fixes: sample-YAML k_vpd parity, auto-size delegation to the
#       configured transpiration method, stomatal response to LED PAR
# ---------------------------------------------------------------------------
def test_sample_yaml_k_vpd_matches_code_default():
    """B1 fix: example YAMLs must agree with the code default k_vpd=2e-5
    (they previously used 1e-4 — a 5× discrepancy that under-sized the
    default DEH against YAML-driven projects)."""
    import yaml

    root = Path(__file__).resolve().parents[1]
    for fname in ("test_project.yaml", "example_lcoe_full.yaml",
                  "example_sweep.yaml"):
        with open(root / fname, encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh)
        assert cfg["transpiration"]["k_vpd"] == pytest.approx(2.0e-5), fname


def test_auto_size_delegates_to_transpiration_model():
    """B2 fix: DEH auto-size must estimate the design moisture load with the
    SAME configured transpiration method used at runtime.  stomatal and
    van_henten previously fell back to the k_vpd shortcut, sizing the DEH
    with the wrong method."""
    from src.design.engine import _build_devices
    from src.design.presets import preset_609

    for method in ("vpd", "stomatal", "van_henten", "constant", "daily"):
        p = preset_609()
        p.transpiration.method = method
        p.deh.auto_size = True
        _, _, deh, _, _, _ = _build_devices(p)
        assert deh.P_ref > 0.0, f"method={method}"

    # per_plant needs a non-zero plant count for a positive design load.
    p = preset_609()
    p.transpiration.method = "per_plant"
    p.transpiration.plant_count = 100
    p.deh.auto_size = True
    _, _, deh, _, _, _ = _build_devices(p)
    assert deh.P_ref > 0.0


def test_stomatal_transpiration_follows_light():
    """B3 fix: stomatal transpiration must respond to the actual LED PAR
    (light_wm2) instead of a fixed r_n_canopy; without light_wm2 the legacy
    behaviour is preserved."""
    from src.plants.transpiration import TranspirationModel

    model = TranspirationModel(method="stomatal", area_m2=45.0)
    T, RH = 25.0, 50.0

    e_legacy = model.step(T, RH, True, 600.0)               # r_n_canopy=250
    e_low = model.step(T, RH, True, 600.0, light_wm2=87.5)  # default PAR
    e_high = model.step(T, RH, True, 600.0, light_wm2=200.0)

    assert e_legacy > e_low              # 87.5 < 250 W/m² → less radiation
    assert e_high > e_low                # stronger light → more transpiration
    assert e_high < e_legacy
    assert model.step(T, RH, False, 600.0, light_wm2=87.5) == 0.0
