"""R28: 2R2C wall thermal-mass network (additive, default off).

Contract under test:
  * ``envelope.wall_rc_nodes: 0`` (default) is behaviourally IDENTICAL to the
    pre-R28 single-node envelope -- the engine's default path stays
    bit-for-bit (609 preset 48 h synthetic run timeseries sha256 oracle,
    captured at HEAD=332b465 before any change).
  * ``wall_rc_nodes: 2`` activates the T_z + T_m two-state network with
    explicit conductances g_im (mass->air) / g_em (mass->outdoor) and
    capacity C_mass (Wh/K).  ode.py is untouched: T_m is stepped by the
    envelope itself (staggered Euler from substep-start states).
  * Fail-fast: invalid switch values, non-positive capacities/conductances
    and forward-Euler instability (closed-form |lambda|max guard, 0.8x
    dt_max) are rejected at load / device-build time.
"""

import hashlib
import json

import numpy as np
import pandas as pd
import pytest

from vfed.design.engine import DesignEngine, _build_devices
from vfed.design.project import DesignProject
from vfed.devices.hvac import size_hvac
from vfed.physics.envelope import Envelope
from vfed.physics.ode import RoomODESolver

# Zero-drift oracle: preset_609 on the deterministic 48 h synthetic weather
# below, timeseries JSON sha256 -- captured at HEAD=332b465 BEFORE the R28
# diff (R27 T2 protocol).  Any default-path float perturbation breaks it.
ZERO_DRIFT_SHA256 = "18735078ad6055df5cc1df28fdd0fc218837c090cd4e69d435ed114b0015c5b8"


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


def rc_project(**overrides):
    """BESTEST-like 2R2C project (design report section 3.4, 600 family)."""
    d = {
        "name": "rc_test",
        "envelope": {
            "U_wall_A": 52.1,
            "A_window": 12.0,
            "eta_solar": 0.72,
            "ach": 0.346,
            "permeance": 0.0,
            "V_room": 129.6,
            "rho_air": 1.2,
            "cp_air": 1005.0,
            "C_z": 150.0,
            "wall_rc_nodes": 2,
            "C_mass": 535.0,
            "g_im": 900.0,
            "g_em": 35.8,
        },
        "hvac": {
            "cop_mode": "constant",
            "cop_value": 3.0,
            "heat_mode": "resistive",
            "deadband_c": 0.5,
            "comp_mod_band_c": 1.0,
            "min_on_s": 0.0,
            "min_off_s": 0.0,
            "fan_power_w": 0.0,
            "shr_rh_guard": 100.0,
            "auto_size": False,
            "P_rated_w": 4000.0,
            "P_rated_heat_w": 6000.0,
        },
        "deh": {"P_ref_w": 0.0, "fan_power_w": 0.0, "auto_size": False},
        "led": {
            "auto_deduce": False,
            "power_w": 0.0,
            "photoperiod_hours": 24.0,
            "light_start_hour": 0,
        },
        "transpiration": {"method": "daily", "daily_water_L": 0.0},
        "setpoints": {"T_light": 27.0, "T_dark": 20.0, "RH": 50.0},
        "equipment_power_w": 200.0,
        "pv_area_m2": 0.0,
        "battery_kwh": 0.0,
        "site": {"lat": 39.83, "lon": -104.65, "tz_hours": -7.0, "year": 1990},
        "space": {"timestep_s": 60},
    }
    for section, values in overrides.items():
        d.setdefault(section, {}).update(values)
    return DesignProject.from_dict(d)


class TestRcOffIsLegacy:
    def test_default_and_zero_modes_bitwise(self):
        """Q_wall with the switch off is the historical single-node float op."""
        for env in (Envelope(U_wall_A=75.0), Envelope(U_wall_A=75.0, wall_rc_nodes=0)):
            assert env.rc_enabled is False
            assert env.T_m is None
            assert env.Q_wall(4.3, 21.7) == 75.0 * (4.3 - 21.7)
            assert env.Q_wall(4.3, 21.7, None) == 75.0 * (4.3 - 21.7)

    def test_engine_zero_drift_sha256(self):
        from vfed.design.presets import preset_609

        engine = DesignEngine(cache_dir=None)
        result = engine.run(preset_609(), weather=synthetic_weather(48))
        ts_json = json.dumps(result.timeseries, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(ts_json.encode("utf-8")).hexdigest()
        assert digest == ZERO_DRIFT_SHA256
        # additive columns must not leak into the default path
        assert "T_m" not in result.timeseries
        assert "wall_rc" not in result.summary


class TestConfigFailFast:
    def test_invalid_switch_value(self):
        # direct dataclass path (1 is not a legal switch; 3 became legal in
        # R28 step 3 as the 2R3C mode)
        with pytest.raises(ValueError, match="wall_rc_nodes"):
            Envelope(U_wall_A=50.0, wall_rc_nodes=1)
        # YAML-facing path
        with pytest.raises(ValueError, match="wall_rc_nodes"):
            DesignProject.from_dict(
                {"name": "bad", "envelope": {"wall_rc_nodes": 1}}
            )

    def test_rc2_requires_positive_capacity_and_conductance(self):
        for field, value in (("C_mass", 0.0), ("C_mass", -1.0), ("g_im", 0.0), ("g_im", -5.0)):
            bad = {
                "name": "bad",
                "envelope": {
                    "wall_rc_nodes": 2,
                    "C_mass": 535.0,
                    "g_im": 900.0,
                    "g_em": 35.8,
                    field: value,
                },
            }
            with pytest.raises(ValueError, match=field):
                DesignProject.from_dict(bad)
        with pytest.raises(ValueError, match="g_em"):
            DesignProject.from_dict(
                {
                    "name": "bad",
                    "envelope": {
                        "wall_rc_nodes": 2,
                        "C_mass": 535.0,
                        "g_im": 900.0,
                        "g_em": -0.1,
                    },
                }
            )

    def test_pure_internal_mass_g_em_zero_is_valid(self):
        p = DesignProject.from_dict(
            {
                "name": "pure_internal",
                "envelope": {
                    "wall_rc_nodes": 2,
                    "C_mass": 535.0,
                    "g_im": 900.0,
                    "g_em": 0.0,
                },
            }
        )
        assert p.envelope.g_em == 0.0


class TestStabilityGuard:
    def test_lambda_max_guard_fails_fast(self):
        """C_z=20 / g_im=1000 at dt=600 s: dt_max ~115 s -> 0.8x = 92 s < 600 s."""
        p = DesignProject.from_dict(
            {
                "name": "unstable",
                "envelope": {
                    "U_wall_A": 52.1,
                    "ach": 0.346,
                    "V_room": 129.6,
                    "C_z": 20.0,
                    "wall_rc_nodes": 2,
                    "C_mass": 100.0,
                    "g_im": 1000.0,
                    "g_em": 30.0,
                },
                "space": {"timestep_s": 600},
            }
        )
        with pytest.raises(RuntimeError, match="dt_max"):
            _build_devices(p, P_atm=101.325)

    def test_recommended_params_pass_the_guard(self):
        env, *_ = _build_devices(rc_project(), P_atm=101.325)
        assert env.rc_enabled is True


class TestMassNodeStep:
    def test_hand_computed_euler_step_and_units(self):
        """1 K air-mass gap, g_em=0: dT_m = g_im*dt*1K/(C_mass*3600) exactly."""
        env = Envelope(
            U_wall_A=52.1, wall_rc_nodes=2, C_mass=100.0, g_im=80.0, g_em=0.0
        )
        env.reset(20.0)
        # T_z=21: flux = 80 W -> dT = 80*600/(100*3600) = 0.13333... K
        t_m = env.step_mass(10.0, 21.0, dt=600.0)
        assert t_m == pytest.approx(20.0 + 80.0 * 600.0 / (100.0 * 3600.0), rel=1e-12)
        assert env.T_m == pytest.approx(t_m)

    def test_outdoor_leg_pulls_toward_t_ext(self):
        env = Envelope(
            U_wall_A=52.1, wall_rc_nodes=2, C_mass=100.0, g_im=80.0, g_em=20.0
        )
        env.reset(20.0)
        t_m = env.step_mass(0.0, 20.0, dt=600.0)  # g_im leg is 0 (T_z == T_m)
        # q = 20*(0-20) = -400 W -> dT = -400*600/(100*3600) = -0.66667 K
        assert t_m == pytest.approx(20.0 - 400.0 * 600.0 / (100.0 * 3600.0), rel=1e-12)


class TestPhysicsClosure:
    def test_relaxation_to_outdoor_temperature(self):
        """No sources, constant T_ext: both states relax to T_ext."""
        env = Envelope(
            U_wall_A=52.1,
            ach=0.0,
            wall_rc_nodes=2,
            C_mass=535.0,
            g_im=900.0,
            g_em=35.8,
        )
        ode = RoomODESolver(C_z=150.0)
        env.reset(27.0)
        t_z, dt = 27.0, 600.0
        for _ in range(800):  # 133 h >> the ~7 h slow eigenmode
            t_m = env.step_mass(10.0, t_z, dt)
            t_z = ode.step_temperature(t_z, env.Q_wall(10.0, t_z, t_m), dt)
        assert t_z == pytest.approx(10.0, abs=1e-7)
        assert env.T_m == pytest.approx(10.0, abs=1e-7)

    def test_energy_closure_boundary_flux_two_node_state(self):
        """free-float square-wave gain: int(boundary fluxes) + stagger term
        == dU_z + dU_m.

        The g_im leg is internal between the nodes but the engine steps the
        mass node FIRST (staggered Euler), so the internal flux enters the
        air balance as g_im*(T_m_new - T_z) and leaves the mass balance as
        g_im*(T_z - T_m_start): the two cancel only up to the O(dt) stagger
        term g_im*(T_m_new - T_m_start)*dt, which is asserted bounded small
        (documented ordering consistency, same order as the air integrator).
        """
        c_z, c_m, g_im, g_em, u_a, dt = 150.0, 535.0, 900.0, 35.8, 52.1, 600.0
        env = Envelope(
            U_wall_A=u_a, ach=0.0, A_window=0.0,
            wall_rc_nodes=2, C_mass=c_m, g_im=g_im, g_em=g_em,
        )
        ode = RoomODESolver(C_z=c_z)
        env.reset(20.0)
        t_z = 20.0
        t_ext = 10.0
        e_boundary_wh = 0.0
        stagger_wh = 0.0
        g_im_throughput_wh = 0.0
        for step in range(144):  # 24 h
            q_in = 2000.0 if (step % 48) < 24 else 0.0  # square-wave gain, W
            t_m_start = env.T_m
            t_m = env.step_mass(t_ext, t_z, dt)
            q_wall = env.Q_wall(t_ext, t_z, t_m)  # direct channel + g_im(T_m-T_z)
            assert q_wall == pytest.approx(
                u_a * (t_ext - t_z) + g_im * (t_m - t_z), rel=1e-12
            )
            t_z_new = ode.step_temperature(t_z, q_in + q_wall, dt)
            # boundary energies over this step (Wh); outdoor legs at the
            # state values the fluxes were actually evaluated at
            e_boundary_wh += (
                q_in + u_a * (t_ext - t_z) + g_em * (t_ext - t_m_start)
            ) * dt / 3600.0
            stagger_wh += g_im * (t_m - t_m_start) * dt / 3600.0
            g_im_throughput_wh += abs(g_im * (t_m - t_z)) * dt / 3600.0
            t_z = t_z_new
        du_z_wh = c_z * (t_z - 20.0)
        du_m_wh = c_m * (env.T_m - 20.0)
        assert (du_z_wh + du_m_wh) == pytest.approx(
            e_boundary_wh + stagger_wh, rel=1e-9
        )
        # the stagger term is an O(dt) ordering artefact of the internal
        # g_im flux, not a leak: small relative to that flux's throughput
        assert abs(stagger_wh) < 0.05 * g_im_throughput_wh

    def test_buffer_cuts_air_swing_vs_light_single_node(self):
        """R28 acceptance physics: the mass node buffers the light air node.

        Against a single node with the SAME air capacity and DC conductance,
        the 2R2C network roughly halves the air-node daily swing under a
        square-wave gain, and the mass returns heat to the air at night
        (regenerative g_im flux) for a majority of the off hours.
        """
        dt = 600.0
        t_ext = 10.0

        def run(envelope, c_z, days=6):
            ode = RoomODESolver(C_z=c_z)
            if envelope.rc_enabled:
                envelope.reset(20.0)
            t_z, t_zs, regen = 20.0, [], 0
            for step in range(days * 144):
                q_in = 2000.0 if (step % 48) < 24 else 0.0
                if envelope.rc_enabled:
                    t_m = envelope.step_mass(t_ext, t_z, dt)
                    if t_m - t_z > 0.2 and step > 144:
                        regen += 1
                    q_wall = envelope.Q_wall(t_ext, t_z, t_m)
                else:
                    q_wall = envelope.Q_wall(t_ext, t_z)
                t_z = ode.step_temperature(t_z, q_in + q_wall, dt)
                t_zs.append(t_z)
            day = np.array(t_zs[3 * 144: 4 * 144])  # periodic steady state
            return day.max() - day.min(), regen

        rc = Envelope(
            U_wall_A=52.1, ach=0.0, wall_rc_nodes=2,
            C_mass=535.0, g_im=900.0, g_em=35.8,
        )
        u_dc = 52.1 + 35.8 * 900.0 / (35.8 + 900.0)
        light = Envelope(U_wall_A=u_dc, ach=0.0)  # same C_z=150, same DC
        swing_rc, regen = run(rc, 150.0)
        swing_light, _ = run(light, 150.0)
        assert swing_rc < 0.6 * swing_light
        assert regen > 0.3 * 3 * 144  # >30% of day-4+ hours return heat


class TestDcAperture:
    def test_size_hvac_uses_ua_dc_when_rc(self):
        kw = dict(
            A_window=12.0,
            eta_solar=0.72,
            ach=0.346,
            V_room=129.6,
            rho_air=1.2,
            cp_air=1005.0,
            led_heat_w=0.0,
            equipment_power_w=200.0,
            cop=3.0,
            T_setpoint=27.0,
        )
        p_on = rc_project(hvac={"auto_size": True})
        _build_devices(p_on, P_atm=101.325)
        ua_dc = 52.1 + 35.8 * 900.0 / (35.8 + 900.0)
        expected_on = size_hvac(U_wall_A=ua_dc, **kw)
        assert p_on.hvac.P_rated_w == pytest.approx(expected_on, rel=1e-9)
        assert p_on.hvac.P_rated_w > size_hvac(U_wall_A=52.1, **kw)

        p_off = rc_project(envelope={"wall_rc_nodes": 0}, hvac={"auto_size": True})
        _build_devices(p_off, P_atm=101.325)
        assert p_off.hvac.P_rated_w == pytest.approx(
            size_hvac(U_wall_A=52.1, **kw), rel=1e-9
        )


class TestEngineRcSmoke:
    def test_rc_engine_run_t_m_column_and_conservation_guards(self):
        wx = synthetic_weather(48)
        engine = DesignEngine(cache_dir=None)
        result = engine.run(rc_project(), weather=wx)
        assert "T_m" in result.timeseries
        t_m = np.asarray(result.timeseries["T_m"], dtype=float)
        t_z = np.asarray(result.timeseries["T_z"], dtype=float)
        t_ext = wx["temperature_2m"].values.astype(float)
        assert len(t_m) == 48
        assert np.isfinite(t_m).all() and np.isfinite(t_z).all()
        assert result.summary["wall_rc"]["T_m_final_c"] == pytest.approx(t_m[-1], abs=0.3)
        # mass node is a slow state: bounded excursion, smooth trajectory
        assert t_m.min() > t_ext.min() - 5.0
        assert t_m.max() < t_z.max() + 5.0
        assert np.abs(np.diff(t_m)).max() < 6.0
        assert result.summary["temperature_clamp_stats"]["clip_events"] == 0
        rh = np.asarray(result.timeseries["RH_z"], dtype=float)
        assert (rh > 0).all() and (rh <= 100).all()
