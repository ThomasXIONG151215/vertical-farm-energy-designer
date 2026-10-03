"""R34/W2-C (D1): DEH EnergyPlus Dehumidifier:DX (T, RH) maps (additive, default off).

Contract under test:
  * ``deh.smer_map: false`` (default) is behaviourally IDENTICAL to the
    pre-R34 path -- the engine's default run stays bit-for-bit equal to the
    shared zero-drift sha256 oracle (test_23/24/25/26/27 constant, captured
    at HEAD=332b465), and the step reports the additive keys
    ``wr_map_mod = ef_map_mod = 1.0`` exactly.
  * ``smer_map: true`` swaps the R33 humidity-only air-side factor for the
    EnergyPlus ``ZoneHVAC:Dehumidifier:DX`` model: TWO normalized
    biquadratics of the inlet air state (E+ v9.5.0 reference curves
    ZoneDehumidWaterRemoval / ZoneDehumidEnergyFactor, NREL fit to the DOE
    10 CFR 430 Appendix X1 test matrix; inputs clamped to the E+ curve
    domain [21, 32.22] C x [40, 80] % RH):
        M        = M_nom * m * WR(T_z, RH_z)      (capacity ALSO derated)
        SMER_eff = smer * smer_speed_mod(m) * EF(T_z, RH_z)
        P_comp   = M * 3.6e6 / SMER_eff
    Both maps are exactly 1.0 at the DOE rating point (26.7 C / 60 % RH),
    where the map-on machine is bit-identical to map-off.
  * Corner probes: 15 C / 40 % RH (clamped to the 21/40 corner) ->
    wr 0.349 / ef 0.617 (SMER_eff = 0.617 x rated, inside the R33/B10 fix
    band 0.4-0.7, AND capacity down to 35 %); 21 C / 68 % RH (layer-A
    condition) -> ef 1.124: wetter-than-rated air may beat the rating
    (anchor, not cap, per E+ -- unlike the R33 law's 1.0 ceiling).
  * Fail-fast: non-bool ``deh.smer_map`` rejected at load; ``smer_map`` +
    ``smer_curve`` are mutually exclusive (project AND device level).
"""

import hashlib
import json

import numpy as np
import pandas as pd
import pytest

from vfed.design.engine import DesignEngine
from vfed.design.project import DesignProject
from vfed.devices.dehumidifier import (
    DEHDevice,
    _EF_MAP_COEF,
    _EF_MAP_RATED,
    _W_NOM_DOE,
    _WR_MAP_COEF,
    _WR_MAP_RATED,
    _biquad_raw,
)
from vfed.physics.psychrometrics import temp_rh_to_ah

# Zero-drift oracle: the SAME constant the test_23/24/25/26/27 suites pin
# (preset_609 48 h synthetic weather, re-captured at HEAD=01b7000 +
# R34/W3-D preset re-calibration deh.smer 3.5 / hvac.eta_II 0.33).  Any
# default-path float perturbation breaks it.
ZERO_DRIFT_SHA256 = "1764f7e6ee6e185d41e8b438a2c3c81320f38e9d02468446dc5f249a25870192"

W_1540 = temp_rh_to_ah(15.0, 40.0)  # B10 dry-cold probe condition
W_2168 = temp_rh_to_ah(21.0, 68.0)  # layer-A measured-band probe condition

_SITE = {"lat": 31.23, "lon": 121.47}


def synthetic_weather(n=48):
    idx = pd.date_range("2023-01-01 00:00", periods=n, freq="h")
    hour = np.arange(n, dtype=float)
    t_ext = 10.0 + 8.0 * np.sin((hour - 9.0) / 24.0 * 2.0 * np.pi)
    rh_ext = 70.0 + 10.0 * np.sin((hour - 3.0) / 24.0 * 2.0 * np.pi)
    ghi = np.clip(600.0 * np.sin((hour - 6.0) / 12.0 * np.pi), 0.0, None)
    return pd.DataFrame(
        {
            "temperature_2m": t_ext,
            "relative_humidity_2m": rh_ext,
            "wind_speed_10m": np.full(n, 2.0),
            "shortwave_radiation": ghi,
            "direct_radiation": ghi * 0.7,
            "diffuse_radiation": ghi * 0.3,
            "surface_pressure": np.full(n, 1013.25),
        },
        index=idx,
    )


def map_project(smer_map=None, **overrides):
    """Compact humid-room project whose DEH actually runs (48 h is enough)."""
    d = {
        "name": "deh_map_test",
        "envelope": {
            "U_wall_A": 20.0,
            "A_window": 0.0,
            "eta_solar": 0.15,
            "ach": 0.001,
            "permeance": 0.0,
            "V_room": 80.0,
            "C_z": 50000.0,
        },
        "hvac": {
            "cop_mode": "constant",
            "cop_value": 3.0,
            "heat_mode": "resistive",
            "P_rated_w": 3000.0,
            "P_rated_heat_w": 6000.0,
            "shr_rh_guard": 100.0,
            "min_on_s": 0.0,
            "min_off_s": 0.0,
            "fan_power_w": 0.0,
        },
        "deh": {"P_ref_w": 3000.0, "fan_power_w": 0.0},
        "led": {
            "auto_deduce": False,
            "power_w": 0.0,
            "photoperiod_hours": 24.0,
            "light_start_hour": 0,
        },
        "transpiration": {"method": "daily", "daily_water_L": 80.0},
        "setpoints": {"T_light": 27.0, "T_dark": 20.0, "RH": 50.0},
        "equipment_power_w": 0.0,
        "pv_area_m2": 0.0,
        "battery_kwh": 0.0,
        "site": {"lat": 31.23, "lon": 121.47, "tz_hours": 8.0},
    }
    if smer_map is not None:
        d["deh"]["smer_map"] = smer_map
    for section, values in overrides.items():
        d.setdefault(section, {}).update(values)
    return DesignProject.from_dict(d)


def humid_weather(n=48):
    """Constant warm/humid outdoor air so the room sits above the RH setpoint."""
    idx = pd.date_range("2026-01-01", periods=n, freq="h")
    return pd.DataFrame(
        {
            "temperature_2m": np.full(n, 25.0),
            "relative_humidity_2m": np.full(n, 80.0),
            "shortwave_radiation": np.zeros(n),
            "direct_radiation": np.zeros(n),
            "diffuse_radiation": np.zeros(n),
            "surface_pressure": np.full(n, 1013.25),
        },
        index=idx,
    )


def settled_step(dev, T_z, RH_z, W_z, n=60, dt=60.0, deh_setpoint=30.0):
    """Step n times (>> tau_m) and return the last output dict (lag settled)."""
    out = None
    for _ in range(n):
        out = dev.step(T_z, RH_z, W_z, dt=dt, deh_setpoint=deh_setpoint)
    return out


def wr_mod(T, RH):
    return _biquad_raw(_WR_MAP_COEF, T, RH) / _WR_MAP_RATED


def ef_mod(T, RH):
    return _biquad_raw(_EF_MAP_COEF, T, RH) / _EF_MAP_RATED


# === 1. default off = zero drift ===


class TestMapOffZeroDrift:
    def test_device_default_off_matches_explicit_false_bitwise(self):
        """Class default and explicit False produce the identical float ops,
        and both additive keys report exactly 1.0 (dry 15/40 air included)."""
        a = DEHDevice(control="on_off", P_ref_w=2000.0, smer=2.0)
        b = DEHDevice(control="on_off", P_ref_w=2000.0, smer=2.0, smer_map=False)
        assert a.smer_map is False and b.smer_map is False
        oa = settled_step(a, T_z=15.0, RH_z=40.0, W_z=W_1540)
        ob = settled_step(b, T_z=15.0, RH_z=40.0, W_z=W_1540)
        assert oa["P_elec_W"] == ob["P_elec_W"]
        assert oa["M_deh_kgs"] == ob["M_deh_kgs"]
        assert oa["Q_DH_W"] == ob["Q_DH_W"]
        assert oa["smer_air_mod"] == 1.0  # R33 switch also untouched
        assert oa["wr_map_mod"] == 1.0 and ob["wr_map_mod"] == 1.0
        assert oa["ef_map_mod"] == 1.0 and ob["ef_map_mod"] == 1.0
        # map OFF in dry air: still the RATED extraction per kWh
        p_comp = oa["P_elec_W"] - a.fan_power_w
        assert oa["M_deh_kgs"] * 3.6e6 / p_comp == pytest.approx(2.0, rel=1e-9)

    def test_engine_default_path_sha256_unchanged(self):
        """preset_609 48 h default run: the shared test_23/24/25/26/27 oracle
        holds (R34 is invisible on the default path) and the summary flags
        both switches off."""
        from vfed.design.presets import preset_609

        engine = DesignEngine(cache_dir=None)
        result = engine.run(preset_609(), weather=synthetic_weather(48))
        ts_json = json.dumps(result.timeseries, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(ts_json.encode("utf-8")).hexdigest()
        assert digest == ZERO_DRIFT_SHA256
        assert result.summary["deh_smer"]["smer_map"] is False
        assert result.summary["deh_smer"]["smer_curve"] is False

    def test_engine_explicit_false_bitwise_matches_default(self):
        """An explicitly-set smer_map: false project is bitwise-identical to
        the implicit default (no hidden coupling through the switch)."""
        engine = DesignEngine(cache_dir=None)
        wx = humid_weather()
        r_default = engine.run(map_project(), weather=wx)
        r_false = engine.run(map_project(smer_map=False), weather=wx)
        assert r_default.summary == r_false.summary
        for key in ("load_kw", "E_deh_Wh", "T_z", "RH_z"):
            assert r_default.timeseries[key] == r_false.timeseries[key]


# === 2. the E+ reference curves themselves ===


class TestMapCoefficients:
    def test_coefficients_are_the_eplus_reference_curves(self):
        """Pinned verbatim from EnergyPlus v9.5.0
        testfiles/SingleFamilyHouse_HP_Slab_Dehumidification.idf (objects
        ZoneDehumidWaterRemoval / ZoneDehumidEnergyFactor)."""
        assert _WR_MAP_COEF == (
            -2.724878664080, 0.100711983591, -0.000990538285,
            0.050053043874, -0.000203629282, -0.000341750531,
        )
        assert _EF_MAP_COEF == (
            -2.388319068955, 0.093047739452, -0.001369700327,
            0.066533716758, -0.000343198063, -0.000562490295,
        )
        # the published E+ curves are NOT exactly 1.0 at the rating point
        # (~0.981 / ~0.975), which is WHY the runtime modifiers normalize
        # by the rating-point raw value (exact x/x = 1.0 in IEEE-754).
        assert _WR_MAP_RATED == pytest.approx(0.980619, abs=5e-7)
        assert _EF_MAP_RATED == pytest.approx(0.975010, abs=5e-7)

    def test_maps_unity_at_doe_rating_point(self):
        """Both modifiers are EXACTLY 1.0 at 26.7 C / 60 % RH, so the map-on
        machine reduces to the rated machine there (bitwise, see class 3)."""
        dev = DEHDevice(smer_map=True)
        assert dev._wr_map_mod(26.7, 60.0) == 1.0
        assert dev._ef_map_mod(26.7, 60.0) == 1.0
        # marginally off-rating air already moves the factors (continuity)
        assert dev._wr_map_mod(26.7, 59.9) < 1.0
        assert dev._ef_map_mod(26.7, 59.9) < 1.0

    def test_doe_matrix_points_in_band(self):
        """DOE 10 CFR 430 Appendix X1 matrix structure (26.7/60 rated,
        26.7/{50..80} humidity sweep, ~18-32/60 temperature sweep): both
        normalized maps stay in [0.3, 1.35], water removal rises with RH,
        EF degrades in dry air and plateaus in wet air."""
        dev = DEHDevice(smer_map=True)
        # humidity sweep at the rated temperature
        assert dev._wr_map_mod(26.7, 50.0) == pytest.approx(0.811047, abs=2e-6)
        assert dev._ef_map_mod(26.7, 50.0) == pytest.approx(0.858838, abs=2e-6)
        assert dev._wr_map_mod(26.7, 70.0) == pytest.approx(1.147422, abs=2e-6)
        assert dev._ef_map_mod(26.7, 70.0) == pytest.approx(1.070763, abs=2e-6)
        assert dev._wr_map_mod(26.7, 80.0) == pytest.approx(1.253313, abs=2e-6)
        # temperature sweep at the rated humidity (18.3 C clamps to 21 C)
        assert dev._wr_map_mod(18.3, 60.0) == dev._wr_map_mod(21.0, 60.0)
        assert dev._ef_map_mod(18.3, 60.0) == dev._ef_map_mod(21.0, 60.0)
        assert dev._wr_map_mod(21.0, 60.0) == pytest.approx(0.808425, abs=2e-6)
        assert dev._ef_map_mod(21.0, 60.0) == pytest.approx(1.035289, abs=2e-6)
        assert dev._wr_map_mod(32.2, 60.0) == pytest.approx(1.122630, abs=2e-6)
        assert dev._ef_map_mod(32.2, 60.0) == pytest.approx(0.879413, abs=2e-6)
        for T in (18.3, 21.0, 26.7, 32.2):
            for RH in (50.0, 60.0, 70.0, 80.0):
                assert 0.3 < dev._wr_map_mod(T, RH) < 1.35
                assert 0.3 < dev._ef_map_mod(T, RH) < 1.35
        # WR monotone in RH at the rated temperature; EF degrades in dry
        # air and plateaus near the wet end (E+ fit: peak around 75 % RH).
        assert dev._wr_map_mod(26.7, 50.0) < dev._wr_map_mod(26.7, 60.0)
        assert dev._wr_map_mod(26.7, 60.0) < dev._wr_map_mod(26.7, 70.0)
        assert dev._wr_map_mod(26.7, 70.0) < dev._wr_map_mod(26.7, 80.0)
        assert dev._ef_map_mod(26.7, 50.0) < dev._ef_map_mod(26.7, 60.0)
        assert dev._ef_map_mod(26.7, 60.0) < dev._ef_map_mod(26.7, 70.0)
        assert dev._ef_map_mod(26.7, 80.0) == pytest.approx(
            dev._ef_map_mod(26.7, 70.0), abs=5e-3
        )

    def test_input_clamping_at_domain_boundaries(self):
        """15 C / 40 % RH pins to the (21, 40) corner; 40 C / 90 % RH pins
        to the (32.22, 80) corner -- the E+ curve domain is the whole story
        outside the tested envelope."""
        dev = DEHDevice(smer_map=True)
        assert dev._wr_map_mod(15.0, 40.0) == dev._wr_map_mod(21.0, 40.0)
        assert dev._ef_map_mod(15.0, 40.0) == dev._ef_map_mod(21.0, 40.0)
        assert dev._wr_map_mod(5.0, 20.0) == dev._wr_map_mod(21.0, 40.0)
        assert dev._wr_map_mod(40.0, 90.0) == dev._wr_map_mod(32.22, 80.0)
        assert dev._ef_map_mod(40.0, 90.0) == dev._ef_map_mod(32.22, 80.0)
        assert dev._wr_map_mod(32.22, 80.0) == pytest.approx(1.337803, abs=2e-6)
        assert dev._ef_map_mod(32.22, 80.0) == pytest.approx(0.886256, abs=2e-6)

    def test_probe_conditions_layer_a_21_68_and_b10_15_40(self):
        """The two acceptance probes of the upgrade brief:
        * 15/40 (B10 dry-cold): ef 0.6168 inside the R33 fix band 0.4-0.7,
          wr 0.349 -- the E+ map ALSO derates capacity, unlike the R33 law.
        * 21/68 (layer-A band condition): ef 1.124 EXCEEDS the rating (the
          rating point is an anchor, not a cap, per E+; the 0.3-0.8 kg/kWh
          layer-A level is a preset-smer calibration matter, wave 3)."""
        dev = DEHDevice(smer_map=True)
        wr_dry, ef_dry = dev._wr_map_mod(15.0, 40.0), dev._ef_map_mod(15.0, 40.0)
        assert wr_dry == pytest.approx(0.349259, abs=2e-6)
        assert ef_dry == pytest.approx(0.616799, abs=2e-6)
        assert 0.4 < ef_dry < 0.7  # B10 fix band holds on the SMER factor
        wr_a, ef_a = dev._wr_map_mod(21.0, 68.0), dev._ef_map_mod(21.0, 68.0)
        assert wr_a == pytest.approx(0.945577, abs=2e-6)
        assert ef_a == pytest.approx(1.123839, abs=2e-6)
        assert ef_a > 1.0  # wetter-than-rated air beats the rating


# === 3. map-on device behaviour (capacity AND power follow the maps) ===


class TestMapOnDevice:
    def test_rated_point_bitwise_same_as_map_off(self):
        """At the DOE rating point both factors are exactly 1.0, so the
        map-on machine is bit-identical to map-off (rated SMER, on_off)."""
        on = DEHDevice(control="on_off", P_ref_w=2000.0, smer=2.0, smer_map=True)
        off = DEHDevice(control="on_off", P_ref_w=2000.0, smer=2.0)
        oo = settled_step(on, T_z=26.7, RH_z=60.0, W_z=_W_NOM_DOE,
                          deh_setpoint=50.0)
        of = settled_step(off, T_z=26.7, RH_z=60.0, W_z=_W_NOM_DOE,
                          deh_setpoint=50.0)
        assert oo["is_on"] and oo["mod"] == pytest.approx(1.0)
        assert oo["P_elec_W"] == of["P_elec_W"]
        assert oo["M_deh_kgs"] == of["M_deh_kgs"]
        assert oo["wr_map_mod"] == 1.0 and oo["ef_map_mod"] == 1.0
        p_comp = oo["P_elec_W"] - on.fan_power_w
        assert oo["M_deh_kgs"] * 3.6e6 / p_comp == pytest.approx(2.0, rel=1e-9)

    def test_dry_cold_15_40_capacity_drops_power_follows_maps(self):
        """B10 probe, device level: moisture removal scales by wr (0.349 --
        capacity is NOT held, unlike the R33 law), compressor power scales
        by wr/ef = 0.566, and the effective SMER is smer * ef = 1.234."""
        on = DEHDevice(control="on_off", P_ref_w=2000.0, smer=2.0, smer_map=True)
        off = DEHDevice(control="on_off", P_ref_w=2000.0, smer=2.0)
        oo = settled_step(on, T_z=15.0, RH_z=40.0, W_z=W_1540)
        of = settled_step(off, T_z=15.0, RH_z=40.0, W_z=W_1540)
        assert oo["is_on"] and of["is_on"]
        wr, ef = on._wr_map_mod(15.0, 40.0), on._ef_map_mod(15.0, 40.0)
        assert oo["wr_map_mod"] == wr and oo["ef_map_mod"] == ef
        assert oo["smer_air_mod"] == 1.0  # R33 path dormant (exclusive)
        # capacity scales exactly by the water-removal map
        assert oo["M_deh_kgs"] == pytest.approx(of["M_deh_kgs"] * wr, rel=1e-9)
        # power for the (smaller) condensate follows P = M*3.6e6/SMER_eff
        p_on = oo["P_elec_W"] - on.fan_power_w
        p_off = of["P_elec_W"] - off.fan_power_w
        assert p_on == pytest.approx(p_off * wr / ef, rel=1e-9)
        # effective SMER = rated * speed_mod(1) * ef; 1.234 kg/kWh
        eff = oo["M_deh_kgs"] * 3.6e6 / p_on
        assert eff == pytest.approx(2.0 * on._smer_speed_mod(1.0) * ef, rel=1e-9)
        assert eff == pytest.approx(1.2336, abs=2e-3)

    def test_layer_a_21_68_effective_smer_beats_rating(self):
        """21 C / 68 % RH: SMER_eff = 2.0 * 1.124 = 2.25 kg/kWh > nameplate
        (E+ anchor-not-cap semantics); capacity still slightly derated."""
        on = DEHDevice(control="on_off", P_ref_w=2000.0, smer=2.0, smer_map=True)
        off = DEHDevice(control="on_off", P_ref_w=2000.0, smer=2.0)
        oo = settled_step(on, T_z=21.0, RH_z=68.0, W_z=W_2168)
        of = settled_step(off, T_z=21.0, RH_z=68.0, W_z=W_2168)
        wr, ef = on._wr_map_mod(21.0, 68.0), on._ef_map_mod(21.0, 68.0)
        assert oo["M_deh_kgs"] == pytest.approx(of["M_deh_kgs"] * wr, rel=1e-9)
        p_on = oo["P_elec_W"] - on.fan_power_w
        eff = oo["M_deh_kgs"] * 3.6e6 / p_on
        assert eff == pytest.approx(2.0 * ef, rel=1e-9)
        assert eff > 2.0  # beats the nameplate in wetter-than-rated air
        assert eff == pytest.approx(2.2477, abs=2e-3)

    def test_vfd_part_load_stacks_with_ef_map(self):
        """vfd mid-band (m = 0.5): speed penalty and EF map MULTIPLY --
        SMER_eff = smer * smer_speed_mod(m) * ef(T, RH); capacity carries
        both m and wr."""
        on = DEHDevice(P_ref_w=2000.0, smer=2.0, smer_map=True)  # vfd default
        off = DEHDevice(P_ref_w=2000.0, smer=2.0)
        kw = dict(T_z=22.0, RH_z=62.0, W_z=temp_rh_to_ah(22.0, 62.0))
        oo = settled_step(on, deh_setpoint=60.0, **kw)
        of = settled_step(off, deh_setpoint=60.0, **kw)
        assert 0.0 < oo["mod"] < 1.0  # genuinely inside the proportional band
        m = oo["mod"]
        assert m == pytest.approx(of["mod"])  # control path untouched
        wr, ef = on._wr_map_mod(22.0, 62.0), on._ef_map_mod(22.0, 62.0)
        assert oo["M_deh_kgs"] == pytest.approx(
            of["M_deh_kgs"] * wr, rel=1e-9
        )  # speed m identical on both, cancels in the ratio
        p_on = oo["P_elec_W"] - on.fan_power_w
        eff = oo["M_deh_kgs"] * 3.6e6 / p_on
        assert eff == pytest.approx(2.0 * on._smer_speed_mod(m) * ef, rel=1e-9)
        assert eff < 2.0 * ef  # part-load speed penalty stacked on top

    def test_idle_output_keys_reflect_state(self):
        """The additive step keys read 1.0 when the map is off (machine on or
        off) and the live factors when on -- including while idle (P = 0),
        so probes can read the correction anytime."""
        off = DEHDevice(control="on_off", P_ref_w=2000.0, smer=2.0)
        idle_off = off.step(T_z=15.0, RH_z=20.0, W_z=W_1540, dt=600.0, deh_setpoint=60.0)
        assert idle_off["wr_map_mod"] == 1.0 and idle_off["ef_map_mod"] == 1.0
        assert idle_off["P_elec_W"] == 0.0
        on = DEHDevice(control="on_off", P_ref_w=2000.0, smer=2.0, smer_map=True)
        idle_on = on.step(T_z=15.0, RH_z=20.0, W_z=W_1540, dt=600.0, deh_setpoint=60.0)
        assert idle_on["wr_map_mod"] == on._wr_map_mod(15.0, 20.0)
        assert idle_on["ef_map_mod"] == on._ef_map_mod(15.0, 20.0)
        assert idle_on["P_elec_W"] == 0.0  # correction never wakes an idle unit


# === 4. contract fail-fast ===


class TestContractFailFast:
    @pytest.mark.parametrize("bad", ["true", "false", 1, 0, 1.0, [False]])
    def test_non_bool_rejected(self, bad):
        with pytest.raises(ValueError, match="deh.smer_map"):
            DesignProject.from_dict(
                {"name": "bad", "site": _SITE, "deh": {"smer_map": bad}}
            )

    def test_bool_accepted_and_default_false(self):
        assert DesignProject.from_dict({"name": "p", "site": _SITE}).deh.smer_map is False
        assert DesignProject.from_dict(
            {"name": "p", "site": _SITE, "deh": {"smer_map": True}}
        ).deh.smer_map is True
        assert DesignProject.from_dict(
            {"name": "p", "site": _SITE, "deh": {"smer_map": False}}
        ).deh.smer_map is False

    def test_mutually_exclusive_with_smer_curve_project_level(self):
        with pytest.raises(ValueError, match="mutually exclusive"):
            DesignProject.from_dict(
                {"name": "bad", "site": _SITE,
                 "deh": {"smer_curve": True, "smer_map": True}}
            )

    def test_mutually_exclusive_device_level(self):
        with pytest.raises(ValueError, match="mutually exclusive"):
            DEHDevice(smer_curve=True, smer_map=True)


# === 5. engine integration (48 h humid room, DEH actually runs) ===


class TestEngineIntegration:
    def test_engine_map_on_deh_energy_rises_delivered_smer_falls(self):
        """Whole-engine direction (48 h warm-humid room, DEH cycling around
        the 50 % RH setpoint): the (T, RH) maps derate capacity near the
        setpoint (wr < 1) and SMER (ef < 1 there), so the machine draws
        MORE compressor electricity for the SAME delivered condensate --
        delivered kg is a room-load invariant, the price moves."""
        engine = DesignEngine(cache_dir=None)
        wx = humid_weather()
        r_off = engine.run(map_project(smer_map=False), weather=wx)
        r_on = engine.run(map_project(smer_map=True), weather=wx)
        sm_off, sm_on = r_off.summary["deh_smer"], r_on.summary["deh_smer"]
        assert sm_off["smer_map"] is False and sm_on["smer_map"] is True
        assert sm_on["deh_comp_energy_kwh"] > 0.0
        assert sm_on["deh_comp_energy_kwh"] > sm_off["deh_comp_energy_kwh"]
        # same room, same moisture load: delivered condensate is invariant
        perf_off = r_off.summary["dehumidifier_performance"]
        perf_on = r_on.summary["dehumidifier_performance"]
        assert perf_on["deh_actual_dehum_kg"] == pytest.approx(
            perf_off["deh_actual_dehum_kg"], rel=1e-6
        )
        # ...but every delivered kg costs more electricity
        assert sm_on["delivered_smer_kg_per_kwh"] < sm_off[
            "delivered_smer_kg_per_kwh"
        ]
        assert sm_on["delivered_smer_kg_per_kwh"] < sm_on[
            "rated_smer_kg_per_kwh"
        ]
        e_deh_on = float(np.sum(r_on.timeseries["E_deh_Wh"]))
        e_deh_off = float(np.sum(r_off.timeseries["E_deh_Wh"]))
        assert e_deh_on > e_deh_off

    def test_engine_map_on_run_is_physically_healthy(self):
        """48 h map-on run stays finite and inside physical RH bounds."""
        engine = DesignEngine(cache_dir=None)
        r = engine.run(map_project(smer_map=True), weather=humid_weather())
        rh = np.asarray(r.timeseries["RH_z"], dtype=float)
        assert np.isfinite(rh).all()
        assert (rh > 0.0).all() and (rh <= 100.0).all()
        assert np.isfinite(r.summary["annual_energy_kwh"])


# === 6. source hygiene: pure-ASCII additions (GBK-console safe) ===


class TestSourceHygiene:
    def test_touched_sources_stay_ascii(self):
        """This test file is pure ASCII and the R34 mutex message renders
        clean on a GBK console (test_14 walks every vfed/ runtime emitter;
        dehumidifier.py itself keeps PRE-EXISTING em-dashes in comments --
        only the emitter strings must be ASCII)."""
        import pathlib

        repo = pathlib.Path(__file__).resolve().parent.parent
        raw = (repo / "tests" / "test_28_deh_smer_map.py").read_bytes()
        assert all(b < 128 for b in raw), "non-ASCII byte in test_28"
        with pytest.raises(ValueError) as exc:
            DEHDevice(smer_curve=True, smer_map=True)
        assert str(exc.value).isascii()
