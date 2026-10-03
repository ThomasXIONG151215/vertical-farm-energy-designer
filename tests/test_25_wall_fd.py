"""R28 step 6: 1-D finite-difference wall (additive, default off).

Contract under test:
  * ``envelope.wall_fd_nodes: 0`` (default) is behaviourally IDENTICAL to the
    pre-R28 envelope -- the engine's default path stays bit-for-bit (609
    preset 48 h synthetic run timeseries sha256 oracle, same constant as
    test_23/test_24).
  * ``wall_fd_nodes >= 10`` activates the cell-centered implicit FD wall
    continuum built from physical ``wall_layers`` (thickness, k, rho, c),
    an exterior sol-air film (``h_ext_wm2`` + ``wall_solar_abs``) and an
    interior convective film (``h_int_c_wm2``) feeding Q_wall, plus a pure
    internal mass node coupled through ``g_sm``.
  * The FD ladder closes EXACTLY onto the continuum DC resistance
    R = 1/(h_o*A) + sum(d_i/k_i)/A + 1/(h_i*A) -- asserted against the
    analytic steady-state flux.
  * Fail-fast: fd/rc mutual exclusion, node range [10, 100], positive layer
    properties, positive films/areas, C_mass/g_sm > 0, rc-only conductances
    must stay 0, and FD-only keys are rejected when the switch is off.
"""

import hashlib
import json

import numpy as np
import pandas as pd
import pytest

from vfed.design.engine import DesignEngine, _build_devices
from vfed.design.project import DesignProject
from vfed.physics.envelope import Envelope, distribute_nodes_fd
from vfed.physics.ode import RoomODESolver

# Zero-drift oracle: identical to test_23/test_24 (re-captured at HEAD=01b7000
# + R34/W3-D preset re-calibration deh.smer 3.5 / hvac.eta_II 0.33).
ZERO_DRIFT_SHA256 = "1764f7e6ee6e185d41e8b438a2c3c81320f38e9d02468446dc5f249a25870192"

# Single light layer, BESTEST-like: d=0.1 m, k=0.5, rho=500, c=1000, A=63.6.
LAYER_1 = (0.1, 0.5, 500.0, 1000.0)
AREA_1 = 63.6
H_EXT = 25.0
H_INT = 3.0


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


def fd_envelope(**overrides):
    kw = dict(
        U_wall_A=52.1,
        ach=0.346,
        A_window=12.0,
        wall_fd_nodes=18,
        wall_layers=[LAYER_1],
        wall_area_m2=AREA_1,
        h_ext_wm2=H_EXT,
        h_int_c_wm2=H_INT,
        g_sm=246.0,
        C_mass=260.0,
    )
    kw.update(overrides)
    return Envelope(**kw)


def fd_project(**overrides):
    """BESTEST-like engine project with the FD wall switched on."""
    d = {
        "name": "fd_test",
        "envelope": {
            "U_wall_A": 52.1,
            "A_window": 12.0,
            "eta_solar": 0.72,
            "ach": 0.346,
            "permeance": 0.0,
            "V_room": 129.6,
            "rho_air": 1.2,
            "cp_air": 1005.0,
            "C_z": 60.0,
            "wall_fd_nodes": 18,
            "wall_layers": [LAYER_1],
            "wall_area_m2": AREA_1,
            "h_ext_wm2": H_EXT,
            "h_int_c_wm2": H_INT,
            "g_sm": 246.0,
            "C_mass": 260.0,
            "wall_solar_abs": 0.6,
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


class TestFdOffIsLegacy:
    def test_default_and_zero_modes(self):
        for env in (Envelope(U_wall_A=75.0), Envelope(U_wall_A=75.0, wall_fd_nodes=0)):
            assert env.fd_enabled is False
            assert env.T_m is None
            assert env.Q_wall(4.3, 21.7) == 75.0 * (4.3 - 21.7)

    def test_engine_zero_drift_sha256(self):
        from vfed.design.presets import preset_609

        engine = DesignEngine(cache_dir=None)
        result = engine.run(preset_609(), weather=synthetic_weather(48))
        ts_json = json.dumps(result.timeseries, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(ts_json.encode("utf-8")).hexdigest()
        assert digest == ZERO_DRIFT_SHA256
        # FD-only artefacts must not leak into the default path
        assert "wall_fd" not in result.summary
        assert "T_m" not in result.timeseries


class TestConfigFailFast:
    def test_fd_rc_mutual_exclusion(self):
        with pytest.raises(ValueError, match="mutually exclusive"):
            Envelope(U_wall_A=50.0, wall_fd_nodes=18, wall_layers=[LAYER_1],
                     wall_area_m2=AREA_1, h_ext_wm2=H_EXT, h_int_c_wm2=H_INT,
                     g_sm=246.0, C_mass=260.0, wall_rc_nodes=2)
        # project layer: from_dict validates the rc branch first, so hand it
        # a fully-legal rc2 parameter set plus FD keys to reach the
        # mutual-exclusion / FD-rejects-rc-conductances checks.
        with pytest.raises(ValueError):
            DesignProject.from_dict(
                {"name": "bad", "envelope": {
                    "wall_fd_nodes": 18, "wall_layers": [LAYER_1],
                    "wall_area_m2": AREA_1, "h_ext_wm2": H_EXT,
                    "h_int_c_wm2": H_INT, "g_sm": 246.0, "C_mass": 535.0,
                    "wall_rc_nodes": 2, "g_im": 900.0, "g_em": 35.8}}
            )

    @pytest.mark.parametrize("nodes", [9, 101, 0.5 if False else 18.5])
    def test_invalid_node_count(self, nodes):
        with pytest.raises(ValueError, match="wall_fd_nodes"):
            fd_envelope(wall_fd_nodes=nodes)

    def test_layers_required_and_validated(self):
        with pytest.raises(ValueError, match="wall_layers"):
            fd_envelope(wall_layers=[])
        with pytest.raises(ValueError, match="wall_layers"):
            fd_envelope(wall_layers=[(0.1, 0.5, 500.0)])  # arity
        with pytest.raises(ValueError, match="thickness_m"):
            fd_envelope(wall_layers=[(0.0, 0.5, 500.0, 1000.0)])

    @pytest.mark.parametrize(
        "field,value",
        [
            ("wall_area_m2", 0.0),
            ("h_ext_wm2", 0.0),
            ("h_int_c_wm2", 0.0),
            ("C_mass", 0.0),
            ("g_sm", 0.0),
        ],
    )
    def test_positive_requirements(self, field, value):
        with pytest.raises(ValueError, match=field.replace("_", "_")):
            fd_envelope(**{field: value})

    def test_solar_abs_band(self):
        with pytest.raises(ValueError, match="wall_solar_abs"):
            fd_envelope(wall_solar_abs=1.5)

    @pytest.mark.parametrize("field", ["g_em", "g_im", "C_surface", "g_sa"])
    def test_rc_only_conductances_must_be_zero(self, field):
        with pytest.raises(ValueError, match=field):
            fd_envelope(**{field: 10.0})

    def test_project_rejects_fd_keys_without_switch(self):
        with pytest.raises(ValueError, match="wall_fd_nodes > 0"):
            DesignProject.from_dict(
                {"name": "bad", "envelope": {"wall_layers": [LAYER_1],
                                             "wall_area_m2": AREA_1}}
            )


class TestDistributeNodes:
    def test_total_exact_and_every_layer_ge_one(self):
        layers = [(0.03, 0.14, 430.0, 1000.0), (0.1, 0.51, 1400.0, 1000.0)]
        counts = distribute_nodes_fd(layers, 18)
        assert sum(counts) == 18
        assert all(c >= 1 for c in counts)
        assert len(counts) == 2

    def test_heavier_layer_gets_more_nodes(self):
        light = (0.03, 0.14, 430.0, 1000.0)
        heavy = (0.1, 0.51, 1400.0, 1000.0)
        counts = distribute_nodes_fd([light, heavy], 18)
        # sqrt(R*C) scaling: the heavy layer has ~10x the areal capacity
        assert counts[1] > counts[0]


class TestSteadyStateAnalytic:
    def test_dc_flux_closes_onto_continuum_u_value(self):
        """Steady FD-wall flux == U_analytic * dT (the U_wall_A direct leg
        is subtracted: in fd mode Q_wall = U_wall_A*dT + g_c*(T_in - T_z),
        and only the second term is the FD ladder)."""
        env = fd_envelope(ach=0.0, A_window=0.0)
        env.reset(20.0)
        t_ext, t_z, dt = 10.0, 20.0, 600.0
        for _ in range(500):  # ~83 h >> the ~8 h wall time constant
            env.step_mass(t_ext, t_z, dt)
        u_analytic = 1.0 / (
            1.0 / (H_EXT * AREA_1)
            + 0.1 / (0.5 * AREA_1)
            + 1.0 / (H_INT * AREA_1)
        )
        q_fd = env.Q_wall(t_ext, t_z, env.T_m)
        q_wall_only = q_fd - 52.1 * (t_ext - t_z)
        assert q_wall_only == pytest.approx(u_analytic * (t_ext - t_z), rel=5e-3)

    def test_two_layer_stack_same_dc(self):
        """Split the same wall into two layers: identical steady flux."""
        env = fd_envelope(
            ach=0.0, A_window=0.0,
            wall_layers=[(0.05, 0.5, 500.0, 1000.0), (0.05, 0.5, 500.0, 1000.0)],
        )
        env.reset(20.0)
        for _ in range(500):
            env.step_mass(10.0, 20.0, 600.0)
        u_analytic = 1.0 / (
            1.0 / (H_EXT * AREA_1) + 0.1 / (0.5 * AREA_1) + 1.0 / (H_INT * AREA_1)
        )
        q_wall_only = env.Q_wall(10.0, 20.0, env.T_m) - 52.1 * (10.0 - 20.0)
        assert q_wall_only == pytest.approx(u_analytic * (10.0 - 20.0), rel=5e-3)

    def test_sol_air_boundary_raises_interior_temperature(self):
        env0 = fd_envelope(ach=0.0, A_window=0.0)
        env1 = fd_envelope(ach=0.0, A_window=0.0, wall_solar_abs=0.6)
        for env in (env0, env1):
            env.reset(20.0)
        for _ in range(500):
            env0.step_mass(10.0, 20.0, 600.0)
            env1.step_mass(10.0, 20.0, 600.0, I_ext_wm2=500.0)
        assert env1.T_sol_air == pytest.approx(10.0 + 0.6 * 500.0 / H_EXT)
        assert env1.Q_wall(10.0, 20.0, env1.T_m) > env0.Q_wall(10.0, 20.0, env0.T_m)


class TestImplicitStability:
    def test_large_dt_stays_bounded(self):
        """Backward Euler is unconditionally stable: dt=3600 s on a light wall."""
        env = fd_envelope(ach=0.0, A_window=0.0)
        env.reset(20.0)
        for _ in range(50):
            env.step_mass(-10.0, 20.0, 3600.0)
        assert np.isfinite(env.T_m)
        assert -15.0 < env.T_m < 25.0


class TestRelaxation:
    def test_free_float_relaxes_to_outdoor(self):
        """No sources, no infiltration: every state relaxes to T_ext."""
        env = fd_envelope(ach=0.0, A_window=0.0, g_sm=246.0, C_mass=50.0)
        ode = RoomODESolver(C_z=60.0)
        env.reset(27.0)
        t_z = 27.0
        for _ in range(900):  # ~150 h >> tau
            t_m = env.step_mass(10.0, t_z, 600.0)
            t_z = ode.step_temperature(t_z, env.Q_wall(10.0, t_z, t_m), 600.0)
        assert t_z == pytest.approx(10.0, abs=1e-6)
        assert env.T_m == pytest.approx(10.0, abs=1e-6)


class TestEngineFdSmoke:
    def test_fd_engine_run_summary_and_column(self):
        wx = synthetic_weather(48)
        engine = DesignEngine(cache_dir=None)
        result = engine.run(fd_project(), weather=wx)
        assert "T_m" in result.timeseries
        t_m = np.asarray(result.timeseries["T_m"], dtype=float)
        assert len(t_m) == 48 and np.isfinite(t_m).all()
        wf = result.summary["wall_fd"]
        assert wf["n_nodes"] == 18
        # the timeseries column is the hourly mean over substeps while the
        # summary is the last-substep value: same state, different snapshot
        assert wf["T_wall_in_final_c"] == pytest.approx(t_m[-1], abs=3.0)
        assert result.summary["temperature_clamp_stats"]["clip_events"] == 0
        rh = np.asarray(result.timeseries["RH_z"], dtype=float)
        assert (rh > 0).all() and (rh <= 100).all()
