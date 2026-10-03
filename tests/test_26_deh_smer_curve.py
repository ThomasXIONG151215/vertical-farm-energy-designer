"""R33 (B10): DEH operating-condition SMER correction (additive, default off).

Contract under test:
  * ``deh.smer_curve: false`` (default) is behaviourally IDENTICAL to the
    pre-R33 constant-SMER path — the engine's default path stays bit-for-bit
    (preset_609 48 h synthetic run timeseries sha256 oracle, the SAME
    constant as test_23/24/25, captured at HEAD=332b465).
  * ``smer_curve: true`` applies, every step,
      SMER_eff = smer * clamp(0.25 + 0.75*(W_z/W_nom)^0.7, 0.25, 1.0)
    with W_nom anchored at the DOE 10 CFR 430 Appendix X1 dehumidifier test
    condition (26.7 C / 60 % RH) via vfed/physics/psychrometrics.py.
    Moisture CAPACITY is unchanged; the compressor power for the same
    condensate rises as 1/SMER_eff (P = M*3.6e6/SMER_eff) — the DOE-observed
    dry-air pessimism the constant-SMER assumption missed by 1.5-2x (B10).
  * Both control modes apply it: on_off full speed gets the air factor alone
    (speed mod = 1), vfd stacks it with the DOE part-load speed curve.
  * Fail-fast: non-bool ``deh.smer_curve`` values are rejected at load time.
"""

import hashlib
import json

import numpy as np
import pandas as pd
import pytest

from vfed.design.engine import DesignEngine
from vfed.design.project import DesignProject
from vfed.devices.dehumidifier import DEHDevice, _W_NOM_DOE
from vfed.physics.psychrometrics import temp_rh_to_ah

# Zero-drift oracle: preset_609 on the deterministic 48 h synthetic weather
# below — the SAME sha256 constant the test_23/24/25 suites pin (re-captured
# at HEAD=01b7000 + R34/W3-D preset re-calibration deh.smer 3.5 /
# hvac.eta_II 0.33).  Any default-path float perturbation breaks it.
ZERO_DRIFT_SHA256 = "1764f7e6ee6e185d41e8b438a2c3c81320f38e9d02468446dc5f249a25870192"

W_1540 = temp_rh_to_ah(15.0, 40.0)  # B10 dry-cold probe condition


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


def curve_project(smer_curve=None, **overrides):
    """Compact humid-room project whose DEH actually runs (48 h is enough)."""
    d = {
        "name": "deh_curve_test",
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
    if smer_curve is not None:
        d["deh"]["smer_curve"] = smer_curve
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


# ── 1. default off = zero drift ────────────────────────────────────────────


class TestCurveOffZeroDrift:
    def test_device_default_off_matches_explicit_false_bitwise(self):
        """Class default and explicit False produce the identical float ops,
        and the air factor reports exactly 1.0 (dry 15/40 air included)."""
        a = DEHDevice(control="on_off", P_ref_w=2000.0, smer=2.0)
        b = DEHDevice(control="on_off", P_ref_w=2000.0, smer=2.0, smer_curve=False)
        assert a.smer_curve is False and b.smer_curve is False
        oa = settled_step(a, T_z=15.0, RH_z=40.0, W_z=W_1540)
        ob = settled_step(b, T_z=15.0, RH_z=40.0, W_z=W_1540)
        assert oa["P_elec_W"] == ob["P_elec_W"]
        assert oa["M_deh_kgs"] == ob["M_deh_kgs"]
        assert oa["Q_DH_W"] == ob["Q_DH_W"]
        assert oa["smer_air_mod"] == 1.0 and ob["smer_air_mod"] == 1.0
        # curve OFF in dry air: still the RATED extraction per kWh (the B10
        # optimism this round fixes when the switch is flipped on).
        p_comp = oa["P_elec_W"] - a.fan_power_w
        assert oa["M_deh_kgs"] * 3.6e6 / p_comp == pytest.approx(2.0, rel=1e-9)

    def test_engine_default_path_sha256_unchanged(self):
        """preset_609 48 h default run: the shared test_23/24/25 oracle holds
        (R33 is invisible on the default path) and the summary flags it."""
        from vfed.design.presets import preset_609

        engine = DesignEngine(cache_dir=None)
        result = engine.run(preset_609(), weather=synthetic_weather(48))
        ts_json = json.dumps(result.timeseries, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(ts_json.encode("utf-8")).hexdigest()
        assert digest == ZERO_DRIFT_SHA256
        assert result.summary["deh_smer"]["smer_curve"] is False

    def test_engine_explicit_false_bitwise_matches_default(self):
        """An explicitly-set smer_curve: false project is bitwise-identical
        to the implicit default (no hidden coupling through the switch)."""
        engine = DesignEngine(cache_dir=None)
        wx = humid_weather()
        r_default = engine.run(curve_project(), weather=wx)
        r_false = engine.run(curve_project(smer_curve=False), weather=wx)
        assert r_default.summary == r_false.summary
        for key in ("load_kw", "E_deh_Wh", "T_z", "RH_z"):
            assert r_default.timeseries[key] == r_false.timeseries[key]


# ── 2. the air-side correction formula ─────────────────────────────────────


class TestAirCurveFormula:
    def test_w_nom_anchor_is_doe_rating_point(self):
        """W_nom is the DOE 10 CFR 430 Appendix X1 test point (26.7 C / 60 %
        RH) computed with the bundled psychrometrics — ~0.0132 kg/kg."""
        assert _W_NOM_DOE == pytest.approx(temp_rh_to_ah(26.7, 60.0), rel=1e-15)
        assert _W_NOM_DOE == pytest.approx(0.013175, abs=1e-5)
        assert 0.012 < _W_NOM_DOE < 0.014

    def test_modifier_unity_at_rated_condition(self):
        """At the rating point the correction is exactly 1 (no penalty);
        wetter-than-rated air cannot beat the rating (clamp at 1.0)."""
        dev = DEHDevice(smer_curve=True)
        assert dev._smer_air_mod(_W_NOM_DOE) == pytest.approx(1.0, abs=1e-12)
        assert dev._smer_air_mod(1.02 * _W_NOM_DOE) == 1.0
        assert dev._smer_air_mod(2.0 * _W_NOM_DOE) == 1.0
        # slightly drier air already degrades (continuous at the anchor)
        assert dev._smer_air_mod(0.99 * _W_NOM_DOE) < 1.0

    def test_modifier_dry_cold_15_40_in_band(self):
        """B10 re-verification band: W(15,40)/W_nom ~ 0.32 -> modifier
        0.25 + 0.75*0.32^0.7 ~ 0.588, inside the accepted 0.4-0.7 band and
        monotonically ordered against milder conditions."""
        dev = DEHDevice(smer_curve=True)
        mod = dev._smer_air_mod(W_1540)
        assert mod == pytest.approx(0.25 + 0.75 * (W_1540 / _W_NOM_DOE) ** 0.7, rel=1e-15)
        assert 0.4 < mod < 0.7
        assert mod == pytest.approx(0.5878, abs=2e-3)
        # monotone in W_z
        assert mod < dev._smer_air_mod(temp_rh_to_ah(20.0, 60.0)) < 1.0

    def test_modifier_clamps_at_floor_and_ceiling(self):
        """W_z = 0 pins the floor 0.25 exactly; mid ratios follow the power
        law; oversaturated ratios clamp to 1.0."""
        dev = DEHDevice(smer_curve=True)
        assert dev._smer_air_mod(0.0) == 0.25
        assert dev._smer_air_mod(-0.001) == 0.25  # negative W guarded
        assert dev._smer_air_mod(0.5 * _W_NOM_DOE) == pytest.approx(
            0.25 + 0.75 * 0.5 ** 0.7, rel=1e-15
        )
        assert dev._smer_air_mod(10.0 * _W_NOM_DOE) == 1.0


# ── 3. curve-on device behaviour (capacity holds, power rises) ─────────────


class TestCurveOnDevice:
    def test_rated_point_bitwise_same_as_curve_off(self):
        """At W_z = W_nom the factor is exactly 1.0, so the curve-on machine
        is bit-identical to curve-off (rated SMER, full speed, on_off)."""
        on = DEHDevice(control="on_off", P_ref_w=2000.0, smer=2.0, smer_curve=True)
        off = DEHDevice(control="on_off", P_ref_w=2000.0, smer=2.0)
        oo = settled_step(on, T_z=26.7, RH_z=60.0, W_z=_W_NOM_DOE,
                          deh_setpoint=50.0)
        of = settled_step(off, T_z=26.7, RH_z=60.0, W_z=_W_NOM_DOE,
                          deh_setpoint=50.0)
        assert oo["is_on"] and oo["mod"] == pytest.approx(1.0)
        assert oo["P_elec_W"] == of["P_elec_W"]
        assert oo["M_deh_kgs"] == of["M_deh_kgs"]
        assert oo["smer_air_mod"] == 1.0
        p_comp = oo["P_elec_W"] - on.fan_power_w
        assert oo["M_deh_kgs"] * 3.6e6 / p_comp == pytest.approx(2.0, rel=1e-9)

    def test_dry_cold_15_40_capacity_holds_power_rises(self):
        """B10 probe, device level: same condensate, P_comp up by 1/modifier,
        effective SMER = rated * modifier (ratio < 1, inside 0.4-0.7)."""
        on = DEHDevice(control="on_off", P_ref_w=2000.0, smer=2.0, smer_curve=True)
        off = DEHDevice(control="on_off", P_ref_w=2000.0, smer=2.0)
        oo = settled_step(on, T_z=15.0, RH_z=40.0, W_z=W_1540)
        of = settled_step(off, T_z=15.0, RH_z=40.0, W_z=W_1540)
        assert oo["is_on"] and of["is_on"]
        mod = on._smer_air_mod(W_1540)
        assert oo["smer_air_mod"] == mod
        # capacity (moisture removal) is unchanged by the correction
        assert oo["M_deh_kgs"] == pytest.approx(of["M_deh_kgs"], rel=1e-12)
        # power for the same condensate rises exactly as 1/modifier
        p_on = oo["P_elec_W"] - on.fan_power_w
        p_off = of["P_elec_W"] - off.fan_power_w
        assert p_on == pytest.approx(p_off / mod, rel=1e-9)
        # effective SMER = rated * speed_mod(1) * air modifier
        eff = oo["M_deh_kgs"] * 3.6e6 / p_on
        assert eff == pytest.approx(
            2.0 * on._smer_speed_mod(1.0) * mod, rel=1e-9
        )
        assert 0.4 < eff / 2.0 < 0.7  # the B10 acceptance band
        assert eff == pytest.approx(1.1756, abs=2e-3)

    def test_vfd_part_load_stacks_with_air_factor(self):
        """vfd mid-band (m = 0.5): the two DOE factors MULTIPLY —
        SMER_eff = smer * smer_speed_mod(m) * smer_air(W_z)."""
        on = DEHDevice(P_ref_w=2000.0, smer=2.0, smer_curve=True)  # vfd default
        off = DEHDevice(P_ref_w=2000.0, smer=2.0)
        kw = dict(T_z=22.0, RH_z=62.0, W_z=temp_rh_to_ah(22.0, 62.0))
        oo = settled_step(on, deh_setpoint=60.0, **kw)
        of = settled_step(off, deh_setpoint=60.0, **kw)
        assert 0.0 < oo["mod"] < 1.0  # genuinely inside the proportional band
        m = oo["mod"]
        assert m == pytest.approx(of["mod"])  # control path untouched
        mod_air = on._smer_air_mod(kw["W_z"])
        p_on = oo["P_elec_W"] - on.fan_power_w
        p_off = of["P_elec_W"] - off.fan_power_w
        assert p_on == pytest.approx(p_off / mod_air, rel=1e-9)
        eff = oo["M_deh_kgs"] * 3.6e6 / p_on
        assert eff == pytest.approx(
            2.0 * on._smer_speed_mod(m) * mod_air, rel=1e-9
        )
        assert eff < 2.0 * mod_air  # part-load speed penalty stacked on top

    def test_output_key_smer_air_mod_reflects_state(self):
        """The additive step key: 1.0 when the curve is off (any air state,
        machine on or off) and the live factor when on — including while the
        machine is idle (P=0), so probes can read the correction anytime."""
        off = DEHDevice(control="on_off", P_ref_w=2000.0, smer=2.0)
        idle_off = off.step(T_z=15.0, RH_z=20.0, W_z=W_1540, dt=600.0, deh_setpoint=60.0)
        assert idle_off["smer_air_mod"] == 1.0 and idle_off["P_elec_W"] == 0.0
        on = DEHDevice(control="on_off", P_ref_w=2000.0, smer=2.0, smer_curve=True)
        idle_on = on.step(T_z=15.0, RH_z=20.0, W_z=W_1540, dt=600.0, deh_setpoint=60.0)
        assert idle_on["smer_air_mod"] == on._smer_air_mod(W_1540)
        assert idle_on["P_elec_W"] == 0.0  # correction never wakes an idle unit


# ── 4. contract fail-fast ──────────────────────────────────────────────────


class TestContractFailFast:
    @pytest.mark.parametrize("bad", ["true", "false", 1, 0, 1.0, [True]])
    def test_non_bool_rejected(self, bad):
        with pytest.raises(ValueError, match="deh.smer_curve"):
            DesignProject.from_dict(
                {"name": "bad", "site": {"lat": 31.23, "lon": 121.47},
                 "deh": {"smer_curve": bad}}
            )

    def test_bool_accepted_and_default_false(self):
        _site = {"lat": 31.23, "lon": 121.47}
        assert DesignProject.from_dict({"name": "p", "site": _site}).deh.smer_curve is False
        assert DesignProject.from_dict(
            {"name": "p", "site": _site, "deh": {"smer_curve": True}}
        ).deh.smer_curve is True
        assert DesignProject.from_dict(
            {"name": "p", "site": _site, "deh": {"smer_curve": False}}
        ).deh.smer_curve is False


# ── 5. engine integration (48 h humid room, DEH actually runs) ────────────


class TestEngineIntegration:
    def test_engine_curve_on_deh_energy_rises_eff_smer_falls(self):
        """Whole-engine direction: with the curve on the DEH draws MORE
        electricity for a similar condensate load, so the reported effective
        SMER falls below both the curve-off run and the nameplate."""
        engine = DesignEngine(cache_dir=None)
        wx = humid_weather()
        r_off = engine.run(curve_project(smer_curve=False), weather=wx)
        r_on = engine.run(curve_project(smer_curve=True), weather=wx)
        sm_off, sm_on = r_off.summary["deh_smer"], r_on.summary["deh_smer"]
        assert sm_off["smer_curve"] is False and sm_on["smer_curve"] is True
        assert sm_on["deh_comp_energy_kwh"] > 0.0
        assert sm_on["deh_comp_energy_kwh"] > sm_off["deh_comp_energy_kwh"]
        # capacity essentially unchanged (same moisture, costlier power)
        perf_off = r_off.summary["dehumidifier_performance"]
        perf_on = r_on.summary["dehumidifier_performance"]
        assert perf_on["deh_nominal_dehum_kg"] == pytest.approx(
            perf_off["deh_nominal_dehum_kg"], rel=0.05
        )
        assert sm_on["effective_smer_kg_per_kwh"] < sm_off[
            "effective_smer_kg_per_kwh"
        ]
        assert sm_on["effective_smer_kg_per_kwh"] < sm_on["rated_smer_kg_per_kwh"]
        # delivered never exceeds effective on either basis
        assert sm_on["delivered_smer_kg_per_kwh"] <= sm_on[
            "effective_smer_kg_per_kwh"
        ]
        e_deh_on = float(np.sum(r_on.timeseries["E_deh_Wh"]))
        e_deh_off = float(np.sum(r_off.timeseries["E_deh_Wh"]))
        assert e_deh_on > e_deh_off

    def test_engine_curve_on_run_is_physically_healthy(self):
        """48 h curve-on run stays finite and inside physical RH bounds."""
        engine = DesignEngine(cache_dir=None)
        r = engine.run(curve_project(smer_curve=True), weather=humid_weather())
        rh = np.asarray(r.timeseries["RH_z"], dtype=float)
        assert np.isfinite(rh).all()
        assert (rh > 0.0).all() and (rh <= 100.0).all()
        assert np.isfinite(r.summary["annual_energy_kwh"])
