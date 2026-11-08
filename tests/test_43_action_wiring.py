"""C2b: ZoneAction control-field wiring in run_hourly_loop (test_43).

Every remaining ZoneAction field (led_on, led_dim, hvac_m, deh_m,
erv_flow_m3h, co2_sp) plus the two config fields that land in the loop
(setpoints.T_heat, setpoints.RH_dark) is asserted DIRECTIONALLY: a run
with the field set differs from the same run without it in the
physically expected direction.  Two zero-drift invariants anchor the
legacy path: policy=None lands in the shared ACCEPTED sha256 oracle,
and an all-None policy hashes identically to policy=None.

Secondary consumption points -- DECIDED rulings, intentionally NOT
asserted here (engine.py / engine_report.py / devices stay frozen):
  (a) DEH/HVAC auto-size design points stay light-period setpoints
      (engine.py sizing loop unchanged by control overrides);
  (b) the rh_exceed report stays single-setpoint v1 (engine_report.py
      does not track a dark RH band);
  (c) shr_rh_guard stays the config threshold inside the devices
      (a policy RH_sp override does not move the guard).
"""

import hashlib
import json

import numpy as np
import pandas as pd

from vfed.design.control import ControlAction, ZoneAction
from vfed.design.engine import DesignEngine
from vfed.design.presets import preset_609

# Zero-drift oracle (shared with test_40 -- platform-dependent float
# ordering gives two accepted digests).
WIN = "1764f7e6ee6e185d41e8b438a2c3c81320f38e9d02468446dc5f249a25870192"
LINUX = "ede65ba07d51c5ed4aa52f353f93590925a80fda93edf70c7436b2db8fa0c336"
ACCEPTED = frozenset({WIN, LINUX})


def synthetic_weather(n=48, t0=10.0, t_amp=8.0):
    """test_40's weather series, parametrized on the temperature level."""
    idx = pd.date_range("2023-01-01", periods=n, freq="h")
    hour = np.arange(n)
    t_ext = t0 + t_amp * np.sin((hour - 9) / 24.0 * 2.0 * np.pi)
    rh_ext = 70.0 + 10.0 * np.sin((hour - 3) / 24.0 * 2.0 * np.pi)
    ghi = np.clip(600.0 * np.sin((hour - 6) / 12.0 * np.pi), 0.0, None)
    return pd.DataFrame(
        {
            "temperature_2m": t_ext,
            "relative_humidity_2m": rh_ext,
            "shortwave_radiation": ghi,
            "wind_speed_10m": np.full(n, 2.0),
            "direct_radiation": 0.7 * ghi,
            "diffuse_radiation": 0.3 * ghi,
            "surface_pressure": np.full(n, 1013.25),
        },
        index=idx,
    )


def _ts_sha256(result):
    return hashlib.sha256(
        json.dumps(result.timeseries, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class ConstantPolicy:
    """BuildingPolicy returning one fixed ZoneAction at every tick."""

    def __init__(self, **fields):
        self._action = ZoneAction(**fields)
        self.owns = frozenset(fields)  # Wave 6: claims exactly what it sets.

    def reset(self, ctx):
        pass

    def plan_daily(self, obs):
        return None

    def step(self, obs):
        return ControlAction(zones={"main": self._action})


def _run(project, weather, policy=None):
    return DesignEngine(cache_dir=None).run(project, weather=weather, policy=policy)


def _proj_light_diag():
    """preset_609 with the spatial light model on (adds PPFD_mean/Q_led_W
    timeseries columns so PAR-level assertions are possible)."""
    p = preset_609()
    p.led.ppfd_layers = [200.0, 220.0, 240.0, 260.0]
    return p


def _dark_mask(ts):
    h = np.asarray(ts["hour_of_day"])
    return (h >= 22) | (h < 6)


# ── zero drift ─────────────────────────────────────────────────────


def test_zero_drift_policy_none_in_accepted_oracle():
    result = _run(preset_609(), synthetic_weather(48))
    assert _ts_sha256(result) in ACCEPTED


def test_zero_drift_all_none_policy_identical_hash():
    weather = synthetic_weather(48)
    base = _run(preset_609(), weather)
    null = _run(preset_609(), weather, policy=ConstantPolicy())
    assert _ts_sha256(base) == _ts_sha256(null)
    assert _ts_sha256(null) in ACCEPTED


# ── led_dim ────────────────────────────────────────────────────────


def test_led_dim_halves_power_par_and_shifts_humidity():
    proj = _proj_light_diag()
    weather = synthetic_weather(48)
    base = _run(proj, weather)
    dimmed = _run(proj, weather, policy=ConstantPolicy(led_dim=0.5))

    dark = _dark_mask(base.timeseries)
    light = ~dark

    # Electrical LED energy in clock-light hours: exactly half.
    e_base = np.asarray(base.timeseries["E_led_Wh"])[light]
    e_dim = np.asarray(dimmed.timeseries["E_led_Wh"])[light]
    np.testing.assert_allclose(e_dim / e_base, 0.5, rtol=1e-12)

    # PAR scales by the same ratio (loop-owned dim consistency).
    p_base = np.asarray(base.timeseries["PPFD_mean"])[light]
    p_dim = np.asarray(dimmed.timeseries["PPFD_mean"])[light]
    np.testing.assert_allclose(p_dim / p_base, 0.5, rtol=1e-12)

    # Halved PAR feeds transpiration -> the humidity trajectory moves.
    assert abs(
        np.mean(dimmed.timeseries["RH_z"]) - np.mean(base.timeseries["RH_z"])
    ) > 1e-6


# ── led_on ─────────────────────────────────────────────────────────


def test_led_on_tristate_forces_light_and_dark():
    proj = _proj_light_diag()
    weather = synthetic_weather(48)
    base = _run(proj, weather)
    forced_on = _run(proj, weather, policy=ConstantPolicy(led_on=True))
    forced_off = _run(proj, weather, policy=ConstantPolicy(led_on=False))

    dark = _dark_mask(base.timeseries)
    light = ~dark

    # Baseline sanity: dark hours are electrically dark.
    assert np.all(np.asarray(base.timeseries["E_led_Wh"])[dark] == 0.0)

    # led_on=True lights the fixture through the clock-dark hours.
    assert np.all(np.asarray(forced_on.timeseries["E_led_Wh"])[dark] > 0.0)
    assert np.all(np.asarray(forced_on.timeseries["PPFD_mean"])[dark] > 0.0)

    # led_on=False cuts the fixture through the clock-light hours.
    assert np.all(np.asarray(forced_off.timeseries["E_led_Wh"])[light] == 0.0)
    assert np.all(np.asarray(forced_off.timeseries["PPFD_mean"])[light] == 0.0)

    # Forced light also drives the room state (LED heat enters at night).
    assert abs(
        np.mean(forced_on.timeseries["T_z"]) - np.mean(base.timeseries["T_z"])
    ) > 1e-6


# ── hvac_m ─────────────────────────────────────────────────────────


def test_hvac_m_override_scales_hvac_energy():
    weather = synthetic_weather(48)
    hi = _run(preset_609(), weather, policy=ConstantPolicy(hvac_m=1.0))
    lo = _run(preset_609(), weather, policy=ConstantPolicy(hvac_m=0.5))
    e_hi = float(np.sum(hi.timeseries["E_hvac_Wh"]))
    e_lo = float(np.sum(lo.timeseries["E_hvac_Wh"]))
    assert e_hi > 0.0  # HVAC actually runs over the window
    assert e_lo < e_hi  # halved modulation halves delivered energy


# ── deh_m ──────────────────────────────────────────────────────────


def test_deh_m_override_scales_deh_energy():
    weather = synthetic_weather(48)
    hi = _run(preset_609(), weather, policy=ConstantPolicy(deh_m=1.0))
    lo = _run(preset_609(), weather, policy=ConstantPolicy(deh_m=0.5))
    e_hi = float(np.sum(hi.timeseries["E_deh_Wh"]))
    e_lo = float(np.sum(lo.timeseries["E_deh_Wh"]))
    assert e_hi > 0.0  # DEH actually runs (transpiration loads the room)
    assert e_lo < e_hi


# ── erv_flow_m3h ───────────────────────────────────────────────────


def test_erv_flow_override_scales_ventilation_and_fan():
    proj = preset_609()
    proj.envelope.erv_enabled = True
    proj.envelope.erv_flow_m3h = 500.0
    proj.envelope.erv_fan_power_w = 200.0
    weather = synthetic_weather(48)

    base = _run(proj, weather)
    half = _run(proj, weather, policy=ConstantPolicy(erv_flow_m3h=250.0))

    # Fan energy is exactly proportional (P = 200 W * 250/500); the
    # summary reports joules folded into kWh (engine_report P3-9).
    base_fan = base.summary["erv"]["annual_fan_kwh"]
    half_fan = half.summary["erv"]["annual_fan_kwh"]
    np.testing.assert_allclose(half_fan / base_fan, 0.5, rtol=1e-9)
    assert base_fan > 0.0

    # Recovered sensible heat halves too -- all five ventilation terms
    # are linear in flow at fixed zone state (test_42 device contract);
    # the small residual is zone-state feedback between the two runs.
    base_rec = base.summary["erv"]["annual_recovered_sensible_kwh"]
    half_rec = half.summary["erv"]["annual_recovered_sensible_kwh"]
    np.testing.assert_allclose(half_rec / base_rec, 0.5, rtol=5e-3)

    # Halved airflow shifts the zone thermal balance.
    assert abs(
        np.mean(half.timeseries["T_z"]) - np.mean(base.timeseries["T_z"])
    ) > 1e-9


# ── setpoints.T_heat ───────────────────────────────────────────────


def test_t_heat_config_raises_heating_trigger():
    # T_ext in [-18, -2] C: real heating duty.  The default (None)
    # inherits T_dark=21; the 609 room barely dips below that, so the
    # override is probed from ABOVE: T_heat=25 makes heating trigger at
    # 25 C instead of T_dark=21 C (verified: a lower value is a no-op
    # because the zone never falls below the inherited band).
    cold = synthetic_weather(48, t0=-10.0, t_amp=8.0)
    base = _run(preset_609(), cold)
    proj = preset_609()
    proj.setpoints.T_heat = 25.0
    warm = _run(proj, cold)

    dark = _dark_mask(base.timeseries)
    assert float(np.sum(base.timeseries["E_hvac_Wh"])) > 0.0  # heating runs
    # Heating now triggers at 25 C, not T_dark=21 C: far more heat, warmer
    # dark-period zone.
    assert float(np.sum(warm.timeseries["E_hvac_Wh"])) > float(
        np.sum(base.timeseries["E_hvac_Wh"])
    )
    assert np.mean(np.asarray(warm.timeseries["T_z"])[dark]) > np.mean(
        np.asarray(base.timeseries["T_z"])[dark]
    )


# ── setpoints.RH_dark ──────────────────────────────────────────────


def test_rh_dark_lowers_dark_period_humidity():
    weather = synthetic_weather(48)
    base = _run(preset_609(), weather)
    proj = preset_609()
    proj.setpoints.RH_dark = 50.0  # default: None -> inherit RH=65
    tight = _run(proj, weather)

    dark = _dark_mask(base.timeseries)
    assert np.mean(np.asarray(tight.timeseries["RH_z"])[dark]) < np.mean(
        np.asarray(base.timeseries["RH_z"])[dark]
    )
    # Total E_deh direction is deliberately NOT asserted: aggressive dark
    # drying warms the zone (DEH sensible heat), which changes HVAC coil
    # condensation and can flip the net DEH duty (measured: 41.5 vs
    # 44.1 kWh).  The setpoint's own channel -- dark RH_z -- is the
    # contract.


# ── co2_sp ─────────────────────────────────────────────────────────


def test_co2_sp_override_raises_concentration_band():
    proj = preset_609()
    proj.co2.enabled = True  # config setpoint: setpoints.co2_ppm = 800
    weather = synthetic_weather(48)
    base = _run(proj, weather)
    rich = _run(proj, weather, policy=ConstantPolicy(co2_sp=1200.0))

    assert np.mean(rich.timeseries["CO2_z"]) > np.mean(base.timeseries["CO2_z"])
    assert (
        rich.summary["annual_co2_injected_kg"]
        > base.summary["annual_co2_injected_kg"]
    )
