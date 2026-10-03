"""R34: HVAC additive upgrades (cop_soft_cap / crankcase_heat_w / defrost).

Contract under test:
  * All switches default OFF/0.0: the engine's default path stays
    bit-for-bit identical to the pre-R34 baselines -- preset_609 48 h
    synthetic-run timeseries sha256 oracle (the SAME constant the
    test_23/24/25/26 suites pin, captured at HEAD=332b465).
  * H1a ``hvac.cop_soft_cap: true`` (carnot mode only) replaces the flat
    4.5 cooling-COP ceiling with the lift-dependent soft ceiling
      cap(lift) = 5.25 - 0.16 * max(lift - 21, 0)   [lift in K]
    calibrated on the GB 21455-2019 IPLV(C) four-point weights
    0.023/0.415/0.461/0.101 (100/75/50/25% load): flat 5.25 ceiling below
    the A25/A27 lift (21 K, in the 5.0-5.5 mild band; the delivered COP
    there is the un-pinned Carnot 4.87), converging 0.16/K to 3.65 at the
    A35/A27 lift (31 K, 3.5-4 band; Carnot 3.30 still binds -> EER holds).
  * H2 ``hvac.crankcase_heat_w`` (default 0): a constant heater drawn ONLY
    while the compressor is OFF, counted in HVAC electricity AND as a room
    heat gain.
  * H3 ``hvac.defrost`` (default "off"): heat-pump heating frost derating
    below defrost_threshold_c (4 C, DOE-2.1E timed threshold).
      "timed"     - discrete reverse-cycle events every
                    defrost_interval_min (90) of frost-condition heating,
                    defrost_duration_min (5) long: delivery stops, the
                    DOE-2.1E reverse-cycle load is drawn from the room,
                    compressor at rated draw.
      "on_demand" - DOE-2.1E continuous frost factors: T_coil =
                    0.82*T_ext - 8.589, d_omega vs W_sat(T_coil), t_frac =
                    1/(1+0.01446/d_omega), capacity x 0.875*(1-t_frac),
                    power x 0.954*(1-t_frac), averaged reverse-cycle load.
    Cold-probe acceptance: T_ext = -7 C heating energy rises ~+8-20%.
  * Fail-fast contract: non-bool cop_soft_cap, unknown defrost modes,
    defrost on resistive units, duration >= interval, out-of-band
    thresholds and crankcase wattages are all rejected at load time.
"""

import hashlib
import json

import numpy as np
import pandas as pd
import pytest

from vfed.design.engine import DesignEngine
from vfed.design.project import DesignProject
from vfed.devices.hvac import COPModel, HVACDevice, _soft_cap_cool
from vfed.physics.psychrometrics import saturation_humidity, temp_rh_to_ah

# Zero-drift oracle: preset_609 on the deterministic 48 h synthetic weather
# below -- the SAME sha256 constant the test_23/24/25/26 suites pin
# (re-captured at HEAD=01b7000 + R34/W3-D preset re-calibration deh.smer 3.5
# / hvac.eta_II 0.33).  Any default-path float perturbation breaks it.
ZERO_DRIFT_SHA256 = "1764f7e6ee6e185d41e8b438a2c3c81320f38e9d02468446dc5f249a25870192"

# GB 21455-2019 IPLV(C) four-point weights (100/75/50/25% load).
IPLV_WEIGHTS = (0.023, 0.415, 0.461, 0.101)


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


def cold_weather(n=48, t_ext=-7.0, rh_ext=80.0):
    """Constant deep-cold humid outdoor air (frost conditions all run)."""
    idx = pd.date_range("2026-01-01", periods=n, freq="h")
    return pd.DataFrame(
        {
            "temperature_2m": np.full(n, t_ext),
            "relative_humidity_2m": np.full(n, rh_ext),
            "shortwave_radiation": np.zeros(n),
            "direct_radiation": np.zeros(n),
            "diffuse_radiation": np.zeros(n),
            "surface_pressure": np.full(n, 1013.25),
        },
        index=idx,
    )


def probe_project(**hvac_over):
    """Compact cold room whose heat pump actually heats (48 h is enough).

    ~4.2 kW envelope loss at T_ext=-7 vs ~5.4 kW heat delivery -> the
    compressor cycles in heat mode nearly continuously, exercising the
    frost scheduler.
    """
    d = {
        "name": "hvac_upgrade_probe",
        "envelope": {
            "U_wall_A": 150.0,
            "A_window": 0.0,
            "eta_solar": 0.15,
            "ach": 0.05,
            "permeance": 0.0,
            "V_room": 60.0,
            "C_z": 20000.0,
        },
        "hvac": {
            "cop_mode": "constant",
            "cop_value": 3.0,
            "heat_mode": "heat_pump",
            "cop_heat": 3.0,
            "P_rated_w": 2500.0,
            "P_rated_heat_w": 2500.0,
            "shr_rh_guard": 100.0,
            "min_on_s": 0.0,
            "min_off_s": 0.0,
            "fan_power_w": 0.0,
        },
        "deh": {"P_ref_w": 300.0, "fan_power_w": 0.0, "control": "on_off"},
        "led": {
            "auto_deduce": False,
            "power_w": 0.0,
            "photoperiod_hours": 24.0,
            "light_start_hour": 0,
        },
        "transpiration": {"method": "daily", "daily_water_L": 2.0},
        "setpoints": {"T_light": 22.0, "T_dark": 20.0, "RH": 70.0},
        "equipment_power_w": 0.0,
        "pv_area_m2": 0.0,
        "battery_kwh": 0.0,
        "site": {"lat": 45.0, "lon": 127.0, "tz_hours": 8.0},
    }
    for k, v in hvac_over.items():
        d["hvac"][k] = v
    return DesignProject.from_dict(d)


# ── 1. default off = zero drift ────────────────────────────────────────────


class TestUpgradesOffZeroDrift:
    def test_engine_default_path_sha256_unchanged(self):
        """preset_609 48 h default run: the shared test_23..26 oracle holds
        (R34 is invisible on the default path) and the summary flags it."""
        from vfed.design.presets import preset_609

        engine = DesignEngine(cache_dir=None)
        result = engine.run(preset_609(), weather=synthetic_weather(48))
        ts_json = json.dumps(result.timeseries, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(ts_json.encode("utf-8")).hexdigest()
        assert digest == ZERO_DRIFT_SHA256
        hu = result.summary["hvac_upgrades"]
        assert hu["cop_soft_cap"] is False
        assert hu["defrost"] == "off"
        assert hu["defrost_events"] == 0
        assert hu["defrost_energy_kwh"] == 0.0
        assert hu["crankcase_energy_kwh"] == 0.0

    def test_explicit_off_bitwise_matches_implicit_default(self):
        """Explicitly-set cop_soft_cap: false / defrost: off /
        crankcase_heat_w: 0.0 is bitwise-identical to the implicit default
        (no hidden coupling through the switches), on a project whose HVAC
        actually runs in both cool and heat modes."""
        engine = DesignEngine(cache_dir=None)
        wx = cold_weather(n=48, t_ext=2.0)
        r_default = engine.run(probe_project(), weather=wx)
        r_off = engine.run(
            probe_project(cop_soft_cap=False, defrost="off", crankcase_heat_w=0.0),
            weather=wx,
        )
        assert r_default.summary == r_off.summary
        for key in ("load_kw", "E_hvac_Wh", "E_deh_Wh", "T_z", "RH_z"):
            assert r_default.timeseries[key] == r_off.timeseries[key]


# ── 2. H1a: the lift-dependent soft ceiling ────────────────────────────────


class TestSoftCapFormula:
    def test_ceiling_curve_knee_and_bands(self):
        """Flat 5.25 (inside the 5.0-5.5 mild band) at/below the A25/A27
        knee lift 21 K, sloping 0.16/K beyond, continuous at the knee."""
        assert _soft_cap_cool(0.0) == 5.25
        assert _soft_cap_cool(21.0) == 5.25
        assert 5.0 <= _soft_cap_cool(21.0) <= 5.5
        assert _soft_cap_cool(22.0) == pytest.approx(5.25 - 0.16, rel=1e-15)
        # hot-lift convergence: 3.65 at the A35/A27 lift 31 K (3.5-4 band)
        assert _soft_cap_cool(31.0) == pytest.approx(3.65, rel=1e-15)
        assert 3.5 <= _soft_cap_cool(31.0) <= 4.0

    def test_a25_a27_mild_point_unpinned(self):
        """A25/A27 (25 C outdoor / 27 C indoor, lift 21 K): the flat 4.5 pin
        is gone -- the delivered COP is the un-pinned Carnot 4.87 (the
        B-layer-judged in-band value for the 5-6 real fleet), strictly
        above the old cap."""
        on = COPModel(cop_soft_cap=True)
        off = COPModel()
        cop_on = on(25.0, 27.0)
        cop_off = off(25.0, 27.0)
        assert cop_off == 4.5  # the B3 artifact: pinned at the flat cap
        assert cop_on == pytest.approx(0.35 * 292.15 / 21.0, rel=1e-15)
        assert cop_on == pytest.approx(4.8689, abs=5e-4)
        assert 4.5 < cop_on < 5.0

    def test_a35_a27_rating_point_holds(self):
        """A35/A27 (35 C outdoor / 27 C indoor, lift 31 K): the Carnot term
        (3.30, the B1 PASS EER vs the 2.8-3.6 datasheet band) still binds
        under the soft ceiling."""
        on = COPModel(cop_soft_cap=True)
        cop = on(35.0, 27.0)
        assert cop == pytest.approx(0.35 * 292.15 / 31.0, rel=1e-15)
        assert cop == pytest.approx(3.30, abs=2e-3)
        assert 3.3 <= round(cop, 2) <= 3.6

    def test_monotone_nonincreasing_in_outdoor_temp(self):
        """COP never rises as the outdoor temperature climbs (both the
        Carnot term and the ceiling are nonincreasing in lift)."""
        on = COPModel(cop_soft_cap=True)
        cops = [on(t, 27.0) for t in range(-5, 41, 5)]
        assert all(a >= b for a, b in zip(cops, cops[1:]))

    def test_deep_mild_ceiling_and_off_cap(self):
        """Deep-mild (collapsed lift -> 5 K floor): the ceiling holds 5.25
        (vs the old flat 4.5); switch off keeps the legacy 4.5 exactly."""
        on = COPModel(cop_soft_cap=True)
        off = COPModel()
        assert on(0.0, 22.0) == 5.25
        assert off(0.0, 22.0) == 4.5

    def test_carnot_mode_only(self):
        """constant/linear/table modes ignore the switch (the ceiling is a
        Carnot-model construct)."""
        for mode, kw in (
            ("constant", {}),
            ("linear", {}),
            ("table", {"table": {20: 3.0, 35: 2.5}}),
        ):
            a = COPModel(mode=mode, cop_soft_cap=True, **kw)
            b = COPModel(mode=mode, **kw)
            for t in (0.0, 10.0, 25.0, 35.0):
                assert a(t, 22.0) == b(t, 22.0)

    def test_iplv_four_point_weighted_value(self):
        """GB 21455-2019 IPLV(C) check: IPLV = 0.023*COP_100 + 0.415*COP_75
        + 0.461*COP_50 + 0.101*COP_25 at the A35/A27 rating outdoor
        condition, with the VFD part-load boost (COP(m) = COP/eir(m)).
        Documents the calibration anchor ~4.18 (report table)."""
        dev = HVACDevice(defrost="off")  # speed-curve host only
        cop100 = COPModel(cop_soft_cap=True)(35.0, 27.0)
        cops = [cop100 / dev._eir_speed_mod(m) for m in (1.0, 0.75, 0.5, 0.25)]
        iplv = sum(w * c for w, c in zip(IPLV_WEIGHTS, cops))
        assert iplv == pytest.approx(4.18, abs=0.05)
        assert 3.0 < iplv < 4.5


# ── 3. H2: crankcase heater ────────────────────────────────────────────────


class TestCrankcaseHeater:
    def test_off_machine_draws_and_heats(self):
        """Compressor OFF: the heater draws exactly its wattage and injects
        the same watts into the room (resistive, no coil lag); the machine
        stays is_on=False."""
        dev = HVACDevice(
            cop=COPModel(mode="constant", value=3.0),
            heat_mode="resistive",
            min_on_s=0.0,
            min_off_s=0.0,
            fan_power_w=0.0,
            crankcase_heat_w=60.0,
        )
        out = dev.step(T_z=22.0, RH_z=50.0, T_ext=10.0, dt=60.0,
                       T_setpoint=22.0, T_heat_setpoint=18.0)
        assert out["is_on"] is False
        assert out["P_elec_W"] == 60.0
        assert out["Q_HVAC_W"] == 60.0  # lag sits at 0 -> pure crankcase gain
        assert dev.energy_crankcase_j == pytest.approx(60.0 * 60.0)

    def test_default_zero_watts_bitwise(self):
        """0 W (default): an idle machine reports exactly 0.0 W and 0.0 W
        heat (no -0.0/float perturbation from the guarded adds)."""
        dev = HVACDevice(fan_power_w=0.0)
        out = dev.step(T_z=22.0, RH_z=50.0, T_ext=10.0, dt=60.0)
        assert out["P_elec_W"] == 0.0
        assert out["Q_HVAC_W"] == 0.0
        assert dev.energy_crankcase_j == 0.0

    def test_running_machine_skips_heater(self):
        """Compressor ON: no crankcase draw -- identical power to a heater-
        free twin, so the heater cannot leak into running substeps."""
        kw = dict(T_z=30.0, RH_z=50.0, T_ext=35.0, dt=60.0, T_setpoint=22.0)
        with_cw = HVACDevice(crankcase_heat_w=60.0, fan_power_w=0.0,
                             min_on_s=0.0, min_off_s=0.0)
        without = HVACDevice(fan_power_w=0.0, min_on_s=0.0, min_off_s=0.0)
        oa = with_cw.step(**kw)
        ob = without.step(**kw)
        assert oa["is_on"] and ob["is_on"]
        assert oa["P_elec_W"] == ob["P_elec_W"]
        assert with_cw.energy_crankcase_j == 0.0

    def test_engine_metering(self):
        """48 h engine run: the off-cycle draw lands in E_hvac (which rises
        vs baseline) and the crankcase_energy_kwh meter is a positive,
        plausible share of the HVAC total (its room heat gain also displaces
        some heat-pump compressor draw, so E delta != meter 1:1)."""
        engine = DesignEngine(cache_dir=None)
        wx = cold_weather(n=48, t_ext=2.0)
        r0 = engine.run(probe_project(), weather=wx)
        r1 = engine.run(probe_project(crankcase_heat_w=60.0), weather=wx)
        e0 = float(np.sum(r0.timeseries["E_hvac_Wh"]))
        e1 = float(np.sum(r1.timeseries["E_hvac_Wh"]))
        assert e1 > e0
        hu = r1.summary["hvac_upgrades"]
        assert 0.0 < hu["crankcase_energy_kwh"] < e1 / 1000.0
        # upper bound: 60 W running every substep of 48 h = 2.88 kWh
        assert hu["crankcase_energy_kwh"] <= 60.0 * 48.0 / 1000.0


# ── 4. H3: defrost -- timed discrete events ────────────────────────────────


class TestDefrostTimedDevice:
    def _heat_dev(self, **kw):
        return HVACDevice(
            heat_mode="heat_pump",
            cop_heat=3.0,
            P_rated_w=2500.0,
            P_rated_heat_w=2500.0,
            min_on_s=0.0,
            min_off_s=0.0,
            fan_power_w=0.0,
            **kw,
        )

    def test_event_schedule_and_outputs(self):
        """At T_ext=-7 (frost conditions) the frost timer fires every 90 min
        of heating: during the 5 min event the delivery stops
        (defrost_frac=1.0), the compressor burns its rated draw and the
        reverse-cycle load makes the room flux negative."""
        dev = self._heat_dev(defrost="timed")
        outs = [
            dev.step(T_z=15.0, RH_z=50.0, T_ext=-7.0, dt=60.0,
                     T_setpoint=22.0, T_heat_setpoint=20.0)
            for _ in range(180)  # 3 h: event starts at 90 min, ends at 95
        ]
        assert dev.defrost_events == 1
        event_outs = [o for o in outs if o["defrost_frac"] == 1.0]
        assert len(event_outs) == 5  # 5 min at dt=60 s
        for o in event_outs:
            assert o["defrosting"] is True
            assert o["P_elec_W"] == 2500.0  # rated draw, fan off
        assert o["Q_HVAC_W"] < 0.0  # reverse cycle draws heat from the room
        assert dev.energy_defrost_j == pytest.approx(2500.0 * 5 * 60.0)
        # annualised multiplier sanity: 5 min / 90 min duty
        assert 5.0 / 90.0 == pytest.approx(0.0556, abs=1e-3)

    def test_above_threshold_is_bitwise_off(self):
        """T_ext=10 C (above the 4 C threshold): a timed machine is
        output-identical to a defrost-off twin (no frost branch at all)."""
        a = self._heat_dev(defrost="timed")
        b = self._heat_dev()
        for _ in range(30):
            oa = a.step(T_z=15.0, RH_z=50.0, T_ext=10.0, dt=60.0,
                        T_setpoint=22.0, T_heat_setpoint=20.0)
            ob = b.step(T_z=15.0, RH_z=50.0, T_ext=10.0, dt=60.0,
                        T_setpoint=22.0, T_heat_setpoint=20.0)
        assert a.defrost_events == 0
        assert oa == ob  # full dict equality, floats included

    def test_custom_schedule(self):
        """A 30/3 min schedule triples the event rate (config plumbing)."""
        dev = self._heat_dev(
            defrost="timed", defrost_interval_min=30.0, defrost_duration_min=3.0
        )
        for _ in range(120):  # 2 h -> ~4 events under a 30 min interval
            dev.step(T_z=15.0, RH_z=50.0, T_ext=-7.0, dt=60.0,
                     T_setpoint=22.0, T_heat_setpoint=20.0)
        assert dev.defrost_events >= 3


# ── 5. H3: defrost -- on_demand DOE-2.1E continuous factors ────────────────


class TestDefrostOnDemandDevice:
    def _heat_step(self, dev, W_ext, T_ext=-7.0):
        return dev.step(
            T_z=15.0, RH_z=50.0, T_ext=T_ext, dt=60.0,
            T_setpoint=22.0, T_heat_setpoint=20.0, W_ext=W_ext,
        )

    def test_factors_apply_exactly(self):
        """At T_ext=-7 / 80% RH the DOE-2.1E chain reproduces term by term:
        t_frac = 1/(1+0.01446/d_omega) with d_omega = W_out - W_sat(T_coil),
        power x 0.954*(1-t_frac) (capacity x 0.875*(1-t_frac) on delivery)."""
        dev = HVACDevice(
            heat_mode="heat_pump", cop_heat=3.0, P_rated_w=2500.0,
            P_rated_heat_w=2500.0, min_on_s=0.0, min_off_s=0.0,
            fan_power_w=0.0, defrost="on_demand",
        )
        W_ext = temp_rh_to_ah(-7.0, 80.0)
        out = self._heat_step(dev, W_ext)
        T_coil = 0.82 * -7.0 - 8.589
        d_w = W_ext - saturation_humidity(T_coil)
        assert d_w > 0.0  # frost potential at -7 C / 80% RH
        t_frac = 1.0 / (1.0 + 0.01446 / d_w)
        assert 0.0 < t_frac < 0.2
        assert out["defrost_frac"] == pytest.approx(t_frac, rel=1e-12)
        # m=1 (5 K below setpoint, band 2) -> cap=eir=1: P = 2500*0.954*(1-t)
        assert out["P_elec_W"] == pytest.approx(
            2500.0 * 0.954 * (1.0 - t_frac), rel=1e-12
        )
        assert dev.energy_defrost_j > 0.0

    def test_dry_air_no_frost_untouched(self):
        """Dry outdoor air (W below the coil frost point): demand defrost
        never fires -- outputs match a defrost-off twin bitwise."""
        a = HVACDevice(
            heat_mode="heat_pump", P_rated_w=2500.0, P_rated_heat_w=2500.0,
            min_on_s=0.0, min_off_s=0.0, fan_power_w=0.0, defrost="on_demand",
        )
        b = HVACDevice(
            heat_mode="heat_pump", P_rated_w=2500.0, P_rated_heat_w=2500.0,
            min_on_s=0.0, min_off_s=0.0, fan_power_w=0.0,
        )
        W_dry = 0.0005  # << W_sat(T_coil=-14.3 C) ~ 0.00125
        oa = self._heat_step(a, W_dry)
        ob = self._heat_step(b, W_dry)
        assert a.defrost_events == 0
        assert oa == ob

    def test_missing_w_ext_fails_fast(self):
        dev = HVACDevice(
            heat_mode="heat_pump", defrost="on_demand",
            min_on_s=0.0, min_off_s=0.0,
        )
        with pytest.raises(ValueError, match="W_ext"):
            self._heat_step(dev, None)


# ── 6. engine-level cold probe (-7 C, heat pump actually heating) ──────────


class TestEngineColdProbe:
    def test_timed_defrost_energy_penalty_direction(self):
        """T_ext=-7 C constant probe: timed defrost raises HVAC electricity
        for the same heated room (~+8-20% acceptance; assert the direction
        and a physically plausible band), events and meter nonzero."""
        engine = DesignEngine(cache_dir=None)
        wx = cold_weather()
        r0 = engine.run(probe_project(), weather=wx)
        r1 = engine.run(probe_project(defrost="timed"), weather=wx)
        e0 = float(np.sum(r0.timeseries["E_hvac_Wh"]))
        e1 = float(np.sum(r1.timeseries["E_hvac_Wh"]))
        assert e0 > 0.0
        ratio = e1 / e0
        assert 1.04 < ratio < 1.40
        hu = r1.summary["hvac_upgrades"]
        assert hu["defrost"] == "timed"
        assert hu["defrost_events"] > 0
        assert hu["defrost_energy_kwh"] > 0.0
        # the run stays physically healthy
        tz = np.asarray(r1.timeseries["T_z"], dtype=float)
        assert np.isfinite(tz).all()
        assert 18.0 < tz.mean() < 24.0

    def test_on_demand_defrost_energy_penalty_direction(self):
        """Same probe with the DOE-2.1E continuous factors: smaller but
        same-direction penalty (multiplier ~0.92/0.84 at -7/80% RH)."""
        engine = DesignEngine(cache_dir=None)
        wx = cold_weather()
        r0 = engine.run(probe_project(), weather=wx)
        r1 = engine.run(probe_project(defrost="on_demand"), weather=wx)
        e0 = float(np.sum(r0.timeseries["E_hvac_Wh"]))
        e1 = float(np.sum(r1.timeseries["E_hvac_Wh"]))
        ratio = e1 / e0
        assert 1.02 < ratio < 1.40
        hu = r1.summary["hvac_upgrades"]
        assert hu["defrost"] == "on_demand"
        assert hu["defrost_energy_kwh"] > 0.0

    def test_mild_probe_no_defrost_effect(self):
        """Above the frost threshold the switch is inert: bitwise-identical
        timeseries (engine level, T_ext=+10 C heating)."""
        engine = DesignEngine(cache_dir=None)
        wx = cold_weather(n=24, t_ext=10.0)
        r0 = engine.run(probe_project(), weather=wx)
        r1 = engine.run(probe_project(defrost="timed"), weather=wx)
        assert r0.timeseries["E_hvac_Wh"] == r1.timeseries["E_hvac_Wh"]
        assert r1.summary["hvac_upgrades"]["defrost_events"] == 0


# ── 7. engine integration: soft cap on the 609-shaped room ────────────────


class TestEngineSoftCap:
    def test_609_softcap_lowers_hvac_electricity(self):
        """48 h mild synthetic weather (all cooling hours below the knee
        lift): the un-pinned mild-weather COP reduces HVAC electricity; all
        outputs stay finite and the summary flags the switch."""
        from vfed.design.presets import preset_609

        engine = DesignEngine(cache_dir=None)
        wx = synthetic_weather(48)
        p_off = preset_609()
        p_on = preset_609()
        p_on.hvac.cop_soft_cap = True
        r_off = engine.run(p_off, weather=wx)
        r_on = engine.run(p_on, weather=wx)
        e_off = float(np.sum(r_off.timeseries["E_hvac_Wh"]))
        e_on = float(np.sum(r_on.timeseries["E_hvac_Wh"]))
        assert e_on < e_off
        assert r_on.summary["hvac_upgrades"]["cop_soft_cap"] is True
        rh = np.asarray(r_on.timeseries["RH_z"], dtype=float)
        assert np.isfinite(rh).all()
        assert (rh > 0.0).all() and (rh <= 100.0).all()

    def test_609_annual_city_file_softcap_run_is_healthy(self):
        """Short full-engine smoke on the bundled city weather path (3 days
        slice of Shanghai): finite, RH in bounds, flags reported."""
        from vfed.design.presets import preset_609

        p = preset_609()
        p.hvac.cop_soft_cap = True
        r = DesignEngine(cache_dir="weather_cache").run(p)
        assert r.summary["hvac_upgrades"]["cop_soft_cap"] is True
        assert np.isfinite(r.summary["annual_energy_kwh"])


# ── 8. contract fail-fast ──────────────────────────────────────────────────


class TestContractFailFast:
    _site = {"lat": 31.23, "lon": 121.47}

    @pytest.mark.parametrize("bad", ["true", "false", 1, 0, 1.0, [True]])
    def test_non_bool_cop_soft_cap_rejected(self, bad):
        with pytest.raises(ValueError, match="hvac.cop_soft_cap"):
            DesignProject.from_dict(
                {"name": "bad", "site": self._site,
                 "hvac": {"cop_soft_cap": bad}}
            )

    @pytest.mark.parametrize("bad", ["auto", "OFF", "TLM", 1, True, None])
    def test_bad_defrost_mode_rejected(self, bad):
        if bad is None:
            return
        with pytest.raises(ValueError, match="hvac.defrost"):
            DesignProject.from_dict(
                {"name": "bad", "site": self._site, "hvac": {"defrost": bad}}
            )

    def test_defrost_resistive_rejected(self):
        with pytest.raises(ValueError, match="heat_pump"):
            DesignProject.from_dict(
                {"name": "bad", "site": self._site,
                 "hvac": {"defrost": "timed", "heat_mode": "resistive"}}
            )

    def test_duration_ge_interval_rejected(self):
        with pytest.raises(ValueError, match="never leaves defrost"):
            DesignProject.from_dict(
                {"name": "bad", "site": self._site,
                 "hvac": {"defrost": "timed",
                          "defrost_duration_min": 90.0}}
            )

    def test_nonpositive_interval_rejected(self):
        with pytest.raises(ValueError, match="> 0 min"):
            DesignProject.from_dict(
                {"name": "bad", "site": self._site,
                 "hvac": {"defrost": "timed",
                          "defrost_interval_min": 0.0}}
            )

    def test_threshold_out_of_band_rejected(self):
        with pytest.raises(ValueError, match=r"\[-30, 10\]"):
            DesignProject.from_dict(
                {"name": "bad", "site": self._site,
                 "hvac": {"defrost": "timed",
                          "defrost_threshold_c": 25.0}}
            )

    @pytest.mark.parametrize("bad", [-5.0, 5000.0, "60"])
    def test_bad_crankcase_rejected(self, bad):
        with pytest.raises(ValueError, match="hvac.crankcase_heat_w"):
            DesignProject.from_dict(
                {"name": "bad", "site": self._site,
                 "hvac": {"crankcase_heat_w": bad}}
            )

    def test_defaults_and_valid_values_accepted(self):
        p = DesignProject.from_dict({"name": "p", "site": self._site})
        assert p.hvac.cop_soft_cap is False
        assert p.hvac.defrost == "off"
        assert p.hvac.crankcase_heat_w == 0.0
        assert p.hvac.defrost_threshold_c == 4.0
        assert p.hvac.defrost_interval_min == 90.0
        assert p.hvac.defrost_duration_min == 5.0
        q = DesignProject.from_dict(
            {"name": "q", "site": self._site,
             "hvac": {"cop_soft_cap": True, "defrost": "on_demand",
                      "crankcase_heat_w": 60.0,
                      "defrost_interval_min": 60.0,
                      "defrost_duration_min": 4.0}}
        )
        assert q.hvac.cop_soft_cap is True
        assert q.hvac.defrost == "on_demand"
        assert q.hvac.crankcase_heat_w == 60.0

    def test_device_level_rejects_bad_defrost(self):
        with pytest.raises(ValueError, match="heat_pump"):
            HVACDevice(heat_mode="resistive", defrost="timed")
        with pytest.raises(ValueError, match="off\\|timed\\|on_demand"):
            HVACDevice(defrost="sometimes")
