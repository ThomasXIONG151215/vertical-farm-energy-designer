"""CO2 supplement M1: injector control logic + fail-fast config guards.

Contract under test (proposal §2.4/§2.7):
  * deadband hysteresis: ON at/below setpoint - band, stays on through the
    band, OFF at/above setpoint + band (on_off: mod = 1 exactly while ON);
  * inject_in_dark=False forces mod = 0 (and zero power) in the dark;
  * min_off_s anti-short-cycling holds the valve closed after a stop;
  * capacity cap: converged injection equals capacity_g_per_h (kg/s);
  * power P_elec = power_w * mod;
  * fail-fast: unknown control mode, non-positive capacity/band/tau,
    negative min_on/min_off/power -- both at the device and at
    DesignProject.from_dict (incl. the HARD_LIMITS bands).
"""

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "vfed"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from vfed.design.project import DesignProject
from vfed.devices.co2 import G_PER_H_TO_KG_PER_S, CO2Device


def _dev(**kw):
    return CO2Device(**kw)


class TestDeadband:
    def test_on_below_setpoint_minus_band(self):
        d = _dev(capacity_g_per_h=200.0, band_ppm=50.0, tau_s=1.0)
        # 700 < 800 - 50: demand 100 >= band -> ON at full modulation
        out = d.step(700.0, 600.0, 800.0, is_light=True)
        assert out["mod"] == 1.0
        assert out["is_on"] is True

    def test_stays_on_inside_band(self):
        d = _dev(capacity_g_per_h=200.0, band_ppm=50.0, tau_s=1.0)
        assert d.step(700.0, 600.0, 800.0)["mod"] == 1.0  # ON
        # inside (sp-band, sp+band): hysteresis keeps the valve open
        out = d.step(800.0, 600.0, 800.0, is_light=True)
        assert out["mod"] == 1.0

    def test_off_at_setpoint_plus_band(self):
        d = _dev(capacity_g_per_h=200.0, band_ppm=50.0, tau_s=1.0)
        d.step(700.0, 600.0, 800.0)  # ON
        # 860 >= 800 + 50 (demand -60 <= -band) -> OFF
        out = d.step(860.0, 600.0, 800.0, is_light=True)
        assert out["mod"] == 0.0
        assert out["is_on"] is False
        assert out["P_elec_W"] == 0.0

    def test_no_injection_when_initially_inside_band(self):
        """Cold start inside the deadband: OFF (no demand above band)."""
        d = _dev(capacity_g_per_h=200.0, band_ppm=50.0, tau_s=1.0)
        out = d.step(780.0, 600.0, 800.0, is_light=True)
        assert out["mod"] == 0.0


class TestDarkPeriod:
    def test_dark_forces_mod_zero_and_zero_power(self):
        d = _dev(capacity_g_per_h=200.0, band_ppm=50.0, tau_s=1.0)
        d.step(700.0, 600.0, 800.0)  # valve ON in light
        out = d.step(700.0, 600.0, 800.0, is_light=False)
        assert out["mod"] == 0.0
        assert out["is_on"] is False
        assert out["P_elec_W"] == 0.0
        # the line lag decays whatever was flowing; power stays 0
        for _ in range(3):
            out = d.step(700.0, 600.0, 800.0, is_light=False)
            assert out["P_elec_W"] == 0.0
        # light returns -> valve reopens immediately
        out = d.step(700.0, 600.0, 800.0, is_light=True)
        assert out["mod"] == 1.0

    def test_inject_in_dark_true_keeps_injecting(self):
        d = _dev(capacity_g_per_h=200.0, band_ppm=50.0, tau_s=1.0, inject_in_dark=True)
        out = d.step(700.0, 600.0, 800.0, is_light=False)
        assert out["mod"] == 1.0
        assert out["P_elec_W"] == 50.0


class TestAntiShortCycle:
    def test_min_off_holds_closed_after_stop(self):
        """min_off_s = 1200 s with dt = 600 s: the valve stays closed while
        less than 1200 s have elapsed since the last stop (including the
        cold start) and reopens once the hold expires."""
        d = _dev(band_ppm=50.0, tau_s=1.0, min_on_s=0.0, min_off_s=1200.0)
        # cold start: only 600 s in the OFF state despite full demand
        assert d.step(700.0, 600.0, 800.0)["mod"] == 0.0
        # 1200 s elapsed: opens
        assert d.step(700.0, 600.0, 800.0)["mod"] == 1.0
        # full demand again, 600 s after the stop: held closed
        assert d.step(860.0, 600.0, 800.0)["mod"] == 0.0  # OFF at sp+band
        assert d.step(700.0, 600.0, 800.0)["mod"] == 0.0
        # after >= 1200 s off: reopens
        assert d.step(700.0, 600.0, 800.0)["mod"] == 1.0


class TestCapacityAndLag:
    def test_capacity_cap_converged(self):
        """tau << dt: the lag converges within a step, S_inj == capacity."""
        d = _dev(capacity_g_per_h=200.0, band_ppm=50.0, tau_s=1.0)
        out = d.step(700.0, 600.0, 800.0)
        assert out["S_inj_kgs"] == pytest.approx(200.0 * G_PER_H_TO_KG_PER_S, rel=1e-12)

    def test_lag_ramps_from_zero(self):
        """tau = dt: first step reaches 1 - exp(-1) of the target."""
        import math

        d = _dev(capacity_g_per_h=200.0, band_ppm=50.0, tau_s=600.0)
        out = d.step(700.0, 600.0, 800.0)
        target = 200.0 * G_PER_H_TO_KG_PER_S
        assert out["S_inj_kgs"] == pytest.approx(target * (1.0 - math.exp(-1.0)), rel=1e-12)

    def test_power_linear_in_mod(self):
        d = _dev(power_w=50.0, band_ppm=50.0, tau_s=1.0)
        assert d.step(700.0, 600.0, 800.0)["P_elec_W"] == 50.0
        assert d.step(860.0, 600.0, 800.0)["P_elec_W"] == 0.0

    def test_reset_restores_initial_state(self):
        d = _dev(band_ppm=50.0, tau_s=600.0)
        d.step(700.0, 600.0, 800.0)  # charges the lag + compressor state
        d.reset()
        fresh = _dev(band_ppm=50.0, tau_s=600.0)
        a = d.step(700.0, 600.0, 800.0)
        b = fresh.step(700.0, 600.0, 800.0)
        assert a == b


class TestDeviceFailFast:
    def test_unknown_control_mode(self):
        with pytest.raises(ValueError, match="control"):
            _dev(control="vfd")  # M2 deliverable: rejected in M1
        with pytest.raises(ValueError, match="control"):
            _dev(control="fuzzy")

    def test_non_positive_capacity(self):
        for bad in (0.0, -10.0):
            with pytest.raises(ValueError, match="capacity"):
                _dev(capacity_g_per_h=bad)

    def test_non_positive_band(self):
        for bad in (0.0, -5.0):
            with pytest.raises(ValueError, match="band"):
                _dev(band_ppm=bad)

    def test_non_positive_tau(self):
        for bad in (0.0, -1.0):
            with pytest.raises(ValueError, match="tau"):
                _dev(tau_s=bad)

    def test_negative_times_or_power(self):
        with pytest.raises(ValueError, match="min_on_s"):
            _dev(min_on_s=-1.0)
        with pytest.raises(ValueError, match="min_on_s"):
            _dev(min_off_s=-1.0)
        with pytest.raises(ValueError, match="power"):
            _dev(power_w=-50.0)


class TestConfigFailFast:
    def test_yaml_control_whitelist(self):
        with pytest.raises(ValueError, match="co2.control"):
            DesignProject.from_dict({"co2": {"enabled": True, "control": "vfd"}})

    def test_yaml_boolean_switches(self):
        with pytest.raises(ValueError, match="co2.enabled"):
            DesignProject.from_dict({"co2": {"enabled": "true"}})
        with pytest.raises(ValueError, match="co2.inject_in_dark"):
            DesignProject.from_dict({"co2": {"inject_in_dark": 1}})

    def test_yaml_positive_invariants(self):
        with pytest.raises(ValueError, match="co2.capacity_g_per_h"):
            DesignProject.from_dict({"co2": {"capacity_g_per_h": 0.0}})
        with pytest.raises(ValueError, match="co2.band_ppm"):
            DesignProject.from_dict({"co2": {"band_ppm": 0.0}})
        with pytest.raises(ValueError, match="co2.tau_s"):
            DesignProject.from_dict({"co2": {"tau_s": -30.0}})

    def test_yaml_hard_limit_bands(self):
        # hard limits: outdoor 350-800, band 10-300, capacity 0-10000
        with pytest.raises(ValueError, match="hard limit"):
            DesignProject.from_dict({"envelope": {"outdoor_co2_ppm": 900.0}})
        with pytest.raises(ValueError, match="hard limit"):
            DesignProject.from_dict({"co2": {"band_ppm": 5.0}})
        with pytest.raises(ValueError, match="hard limit"):
            DesignProject.from_dict({"co2": {"capacity_g_per_h": 20000.0}})

    def test_yaml_setpoint_band_and_inheritance(self):
        """setpoint_ppm / co2_initial_ppm share the setpoints.co2_ppm band;
        None inherits setpoints.co2_ppm (resolved by the engine)."""
        with pytest.raises(ValueError, match=r"co2.setpoint_ppm must be in"):
            DesignProject.from_dict({"co2": {"setpoint_ppm": 2500.0}})
        with pytest.raises(ValueError, match=r"co2.co2_initial_ppm must be in"):
            DesignProject.from_dict({"co2": {"co2_initial_ppm": 100.0}})
        p = DesignProject.from_dict(
            {
                "setpoints": {"co2_ppm": 1000.0},
                "co2": {"enabled": True},
            }
        )
        assert p.co2.enabled is True
        assert p.co2.setpoint_ppm is None  # engine resolves to 1000.0
        assert p.setpoints.co2_ppm == 1000.0
        assert p.envelope.outdoor_co2_ppm == 420.0  # documented default

    def test_yaml_unknown_keys_rejected(self):
        with pytest.raises(ValueError, match="Unrecognised keys in 'co2'"):
            DesignProject.from_dict({"co2": {"injection_heat": True}})
        with pytest.raises(ValueError, match="Unrecognised top-level"):
            DesignProject.from_dict({"CO2": {}})

    def test_disabled_defaults(self):
        p = DesignProject.from_dict({})
        assert p.co2.enabled is False
        assert p.co2.setpoint_ppm is None
        assert p.co2.band_ppm == 50.0
        assert p.co2.control == "on_off"
        assert p.co2.capacity_g_per_h == 200.0
        assert p.co2.inject_in_dark is False
        assert p.co2.min_on_s == 0.0
        assert p.co2.min_off_s == 300.0
        assert p.co2.power_w == 50.0
        assert p.co2.tau_s == 30.0
        assert p.co2.co2_initial_ppm is None
