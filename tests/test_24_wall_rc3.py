"""R28 step 3: 2R3C wall network (wall_rc_nodes=3) + solar split.

Contract under test:
  * ``envelope.wall_rc_nodes: 3`` activates the T_z + T_s + T_m three-state
    network: surface node (C_surface Wh/K) between the mass node and the air
    node, coupled by g_sa (surface->air film) and g_sm (surface->mass);
    ode.py stays untouched (staggered explicit Euler inside the envelope).
  * ``envelope.solar_mass_fraction`` routes that fraction of the window
    solar gain into the RC network as a source (surface node for 2R3C, mass
    node for 2R2C); 0.0 (default) skips the split branch entirely so the
    rc path stays bit-for-bit the pre-step-3 behaviour.
  * Fail-fast: invalid switch values, missing/incomplete rc3 parameter
    groups, out-of-range fractions and forward-Euler instability of the
    3x3 system (closed-form |lambda|max cubic guard, 0.8x dt_max) are all
    rejected at config / device-build time.
  * Energy conservation: boundary fluxes + the documented O(dt) stagger of
    the internal g_sa leg close against dU_z + dU_s + dU_m (rel 1e-9).
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

from test_23_wall_rc import synthetic_weather


def rc3_envelope(**overrides):
    kw = dict(
        U_wall_A=52.1,
        ach=0.0,
        wall_rc_nodes=3,
        C_mass=1000.0,
        g_em=35.8,
        C_surface=260.0,
        g_sa=384.0,
        g_sm=60.0,
    )
    kw.update(overrides)
    return Envelope(**kw)


def rc3_project(**overrides):
    """BESTEST-like 2R3C project (600-family seeds)."""
    d = {
        "name": "rc3_test",
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
            "wall_rc_nodes": 3,
            "C_mass": 1000.0,
            "g_em": 35.8,
            "C_surface": 260.0,
            "g_sa": 384.0,
            "g_sm": 60.0,
            "solar_mass_fraction": 1.0,
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
            "P_rated_w": 8000.0,
            "P_rated_heat_w": 8000.0,
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


class TestConfigFailFast:
    def test_rc3_requires_full_parameter_group(self):
        for field, value in (
            ("C_surface", 0.0),
            ("C_surface", -1.0),
            ("g_sa", 0.0),
            ("g_sm", 0.0),
            ("C_mass", 0.0),
            ("g_em", -0.1),
        ):
            bad = {
                "name": "bad",
                "envelope": {
                    "wall_rc_nodes": 3,
                    "C_mass": 1000.0,
                    "g_em": 35.8,
                    "C_surface": 260.0,
                    "g_sa": 384.0,
                    "g_sm": 60.0,
                    field: value,
                },
            }
            with pytest.raises(ValueError, match=field):
                DesignProject.from_dict(bad)
            with pytest.raises(ValueError, match=field):
                rc3_envelope(**{field: value})

    def test_rc3_does_not_require_g_im(self):
        p = rc3_project()
        assert p.envelope.g_im == 0.0  # unused in 2R3C
        env, *_ = _build_devices(p, P_atm=101.325)
        assert env.rc_enabled and env.rc3_enabled

    def test_solar_mass_fraction_range(self):
        for bad in (-0.01, 1.01, -1.0, 2.0):
            with pytest.raises(ValueError, match="solar_mass_fraction"):
                rc3_envelope(solar_mass_fraction=bad)
            with pytest.raises(ValueError, match="solar_mass_fraction"):
                DesignProject.from_dict(
                    {
                        "name": "bad",
                        "envelope": {
                            "wall_rc_nodes": 3,
                            "C_mass": 1000.0,
                            "g_em": 35.8,
                            "C_surface": 260.0,
                            "g_sa": 384.0,
                            "g_sm": 60.0,
                            "solar_mass_fraction": bad,
                        },
                    }
                )

    def test_solar_mass_fraction_requires_rc(self):
        with pytest.raises(ValueError, match="solar_mass_fraction"):
            Envelope(U_wall_A=50.0, solar_mass_fraction=0.5)
        with pytest.raises(ValueError, match="solar_mass_fraction"):
            DesignProject.from_dict(
                {
                    "name": "bad",
                    "envelope": {"solar_mass_fraction": 0.5},
                }
            )

    def test_solar_mass_fraction_zero_valid_everywhere(self):
        # f = 0 must be accepted on every path (default no-drift semantics)
        Envelope(U_wall_A=50.0, solar_mass_fraction=0.0)
        rc3_envelope(solar_mass_fraction=0.0)
        DesignProject.from_dict(
            {"name": "ok", "envelope": {"solar_mass_fraction": 0.0}}
        )


class TestRc3Step:
    def test_hand_computed_euler_step_and_units(self):
        """Decoupled T_s/T_m hand calc: film flux and outdoor leg exact."""
        env = rc3_envelope()
        env.reset(20.0)
        t_s = env.step_mass(10.0, 21.0, dt=600.0)
        # q_s = g_sa*(21-20) + g_sm*(20-20) = 384 W
        #   -> dT_s = 384*600/(260*3600)
        assert t_s == pytest.approx(20.0 + 384.0 * 600.0 / (260.0 * 3600.0), rel=1e-12)
        # q_m = g_sm*(20-20) + g_em*(10-20) = -358 W
        #   -> dT_m = -358*600/(1000*3600)
        assert env.T_m == pytest.approx(20.0 - 358.0 * 600.0 / (1000.0 * 3600.0), rel=1e-12)
        assert env.T_s == pytest.approx(t_s)

    def test_q_source_lands_on_surface_node(self):
        env = rc3_envelope()
        env.reset(20.0)
        t_s = env.step_mass(10.0, 21.0, dt=600.0, Q_source_w=1000.0)
        # q_s = 384 + 1000 = 1384 W
        assert t_s == pytest.approx(20.0 + 1384.0 * 600.0 / (260.0 * 3600.0), rel=1e-12)
        # mass node sees NO source: same outdoor leg as the unpatched case
        assert env.T_m == pytest.approx(20.0 - 358.0 * 600.0 / (1000.0 * 3600.0), rel=1e-12)

    def test_reset_aligns_both_states(self):
        env = rc3_envelope()
        env.reset(21.5)
        assert env.T_m == 21.5 and env.T_s == 21.5

    def test_relaxation_to_outdoor_temperature(self):
        """No sources, constant T_ext: all three states relax to T_ext."""
        env = rc3_envelope()
        ode = RoomODESolver(C_z=150.0)
        env.reset(27.0)
        t_z, dt = 27.0, 600.0
        for _ in range(3000):  # >> the slowest eigenmode
            t_rc = env.step_mass(10.0, t_z, dt)
            t_z = ode.step_temperature(t_z, env.Q_wall(10.0, t_z, t_rc), dt)
        assert t_z == pytest.approx(10.0, abs=1e-7)
        assert env.T_s == pytest.approx(10.0, abs=1e-7)
        assert env.T_m == pytest.approx(10.0, abs=1e-7)


class TestEnergyClosure:
    def test_boundary_flux_closes_three_node_state(self):
        """Free-float square-wave source on the surface node: int(boundary)
        + stagger == dU_z + dU_s + dU_m (rel 1e-9).

        The engine steps (T_s, T_m) FIRST from substep-start states; the
        internal g_sm leg then cancels exactly (both node balances evaluate
        it at start states).  The air-coupling g_sa leg enters the air
        balance as g_sa*(T_s_new - T_z) but leaves the surface as
        g_sa*(T_z - T_s_start): the residual is the documented O(dt)
        stagger term g_sa*(T_s_new - T_s_start)*dt, asserted bounded small.
        """
        c_z, c_s, c_m = 150.0, 260.0, 1000.0
        g_sa, g_sm, g_em, u_a, dt = 384.0, 60.0, 35.8, 52.1, 600.0
        env = rc3_envelope(
            C_mass=c_m, C_surface=c_s, g_sa=g_sa, g_sm=g_sm, g_em=g_em,
            U_wall_A=u_a,
        )
        ode = RoomODESolver(C_z=c_z)
        env.reset(20.0)
        t_z, t_ext = 20.0, 10.0
        e_boundary_wh = 0.0
        stagger_wh = 0.0
        g_sa_throughput_wh = 0.0
        for step in range(144):  # 24 h
            q_src = 2000.0 if (step % 48) < 24 else 0.0  # square wave, W
            t_s_start = env.T_s
            t_m_start = env.T_m
            t_rc = env.step_mass(t_ext, t_z, dt, Q_source_w=q_src)
            q_wall = env.Q_wall(t_ext, t_z, t_rc)
            assert q_wall == pytest.approx(
                u_a * (t_ext - t_z) + g_sa * (t_rc - t_z), rel=1e-12
            )
            t_z_new = ode.step_temperature(t_z, q_wall, dt)
            # boundary energies over this step (Wh), at the state values the
            # fluxes were evaluated at (substep start)
            e_boundary_wh += (
                q_src + u_a * (t_ext - t_z) + g_em * (t_ext - t_m_start)
            ) * dt / 3600.0
            stagger_wh += g_sa * (t_rc - t_s_start) * dt / 3600.0
            g_sa_throughput_wh += abs(g_sa * (t_rc - t_z)) * dt / 3600.0
            t_z = t_z_new
        du_z_wh = c_z * (t_z - 20.0)
        du_s_wh = c_s * (env.T_s - 20.0)
        du_m_wh = c_m * (env.T_m - 20.0)
        assert (du_z_wh + du_s_wh + du_m_wh) == pytest.approx(
            e_boundary_wh + stagger_wh, rel=1e-9
        )
        assert abs(stagger_wh) < 0.05 * g_sa_throughput_wh


class TestSolarSplitZeroDrift:
    @staticmethod
    def _digest(project):
        engine = DesignEngine(cache_dir=None)
        result = engine.run(project, weather=synthetic_weather(48))
        ts_json = json.dumps(
            result.timeseries, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(ts_json.encode("utf-8")).hexdigest(), result

    def test_rc2_explicit_zero_equals_omitted(self):
        """f_split = 0.0 must reproduce the pre-step-3 rc2 path exactly:
        the split branch is skipped, step_mass gets its default source."""
        base = rc3_project(
            envelope={
                "wall_rc_nodes": 2,
                "C_mass": 535.0,
                "g_em": 35.8,
                "g_im": 900.0,
            }
        )
        base.envelope.solar_mass_fraction = 0.0
        with_field = rc3_project(
            envelope={
                "wall_rc_nodes": 2,
                "C_mass": 535.0,
                "g_em": 35.8,
                "g_im": 900.0,
                "solar_mass_fraction": 0.0,
            }
        )
        d1, r1 = self._digest(base)
        d2, r2 = self._digest(with_field)
        assert d1 == d2
        assert "T_s" not in r1.timeseries  # rc2 never emits the surface col
        assert "T_s_final_c" not in r1.summary.get("wall_rc", {})

    def test_rc3_explicit_zero_equals_omitted(self):
        no_field = rc3_project()
        no_field.envelope.solar_mass_fraction = 0.0
        with_field = rc3_project(envelope={"solar_mass_fraction": 0.0})
        d1, _ = self._digest(no_field)
        d2, _ = self._digest(with_field)
        assert d1 == d2

    def test_split_changes_the_trajectory(self):
        """f = 1.0 vs f = 0.0 must differ (solar is actually rerouted)."""
        d0, _ = self._digest(rc3_project(envelope={"solar_mass_fraction": 0.0}))
        d1, _ = self._digest(rc3_project(envelope={"solar_mass_fraction": 1.0}))
        assert d0 != d1


class TestStabilityGuard:
    def test_lambda_max_guard_fails_fast(self):
        """Thin surface node + strong film at dt=600 s: dt_max ~O(100 s)."""
        p = rc3_project(
            envelope={"C_z": 20.0, "C_surface": 5.0, "g_sa": 1500.0, "g_sm": 900.0},
            space={"timestep_s": 600},
        )
        with pytest.raises(RuntimeError, match="2R3C wall network unstable"):
            _build_devices(p, P_atm=101.325)

    def test_recommended_params_pass_the_guard(self):
        env, *_ = _build_devices(rc3_project(), P_atm=101.325)
        assert env.rc3_enabled is True

    def test_guard_closed_form_matches_numpy_reference(self):
        """The cubic closed form must agree with numpy eigvalsh of the
        symmetrised 3x3 system on a grid of physical parameter points."""
        import math
        from types import SimpleNamespace

        from vfed.design.engine import _wall_rc3_stability_guard
        from vfed.design.project import EnvelopeConfig

        # probe (cz, cs, cm, g_sa, g_sm, g_em, ua, ach) points
        grid = [
            (150.0, 260.0, 1000.0, 384.0, 60.0, 35.8, 52.1, 0.346),
            (150.0, 260.0, 4000.0, 500.0, 200.0, 12.0, 45.1, 0.346),
            (100.0, 2000.0, 3966.0, 585.0, 700.0, 36.6, 52.1, 0.346),
            (150.0, 800.0, 535.0, 1300.0, 30.0, 20.0, 52.1, 0.0),
        ]
        for cz, cs, cm, gsa, gsm, gem, ua, ach in grid:
            e = EnvelopeConfig(
                C_z=cz, C_surface=cs, C_mass=cm,
                g_sa=gsa, g_sm=gsm, g_em=gem,
                U_wall_A=ua, ach=ach,
                wall_rc_nodes=3,
            )
            c_z_j, c_s_j, c_m_j = cz * 3600.0, cs * 3600.0, cm * 3600.0
            g_z_ext = ua + ach * e.V_room * e.rho_air / 3600.0 * e.cp_air
            # symmetric similar matrix D^-1/2 L D^-1/2
            sym = np.array(
                [
                    [-(g_z_ext + gsa) / c_z_j, gsa / math.sqrt(c_z_j * c_s_j), 0.0],
                    [gsa / math.sqrt(c_z_j * c_s_j), -(gsa + gsm) / c_s_j,
                     gsm / math.sqrt(c_s_j * c_m_j)],
                    [0.0, gsm / math.sqrt(c_s_j * c_m_j), -(gem + gsm) / c_m_j],
                ]
            )
            lam_ref = float(np.abs(np.linalg.eigvalsh(sym)).max())
            dt_ref = 2.0 / lam_ref

            def fails(dt: float) -> bool:
                try:
                    _wall_rc3_stability_guard(
                        SimpleNamespace(envelope=e, space=SimpleNamespace(timestep_s=dt))
                    )
                    return False
                except RuntimeError:
                    return True

            # bisect the guard threshold: fails(dt) flips at dt = 0.8*dt_max
            lo, hi = 0.0, 2.0 * dt_ref  # hi > 0.8*dt_max necessarily
            for _ in range(100):
                mid = 0.5 * (lo + hi)
                if fails(mid):
                    hi = mid
                else:
                    lo = mid
            assert 0.8 * dt_ref == pytest.approx(lo, rel=1e-6)


class TestEngineRc3Smoke:
    def test_rc3_engine_run_columns_and_summary(self):
        wx = synthetic_weather(48)
        engine = DesignEngine(cache_dir=None)
        result = engine.run(rc3_project(), weather=wx)
        assert "T_m" in result.timeseries and "T_s" in result.timeseries
        t_s = np.asarray(result.timeseries["T_s"], dtype=float)
        t_m = np.asarray(result.timeseries["T_m"], dtype=float)
        t_z = np.asarray(result.timeseries["T_z"], dtype=float)
        t_ext = wx["temperature_2m"].values.astype(float)
        assert len(t_s) == 48 and len(t_m) == 48
        assert np.isfinite(t_s).all() and np.isfinite(t_m).all()
        assert result.summary["wall_rc"]["T_s_final_c"] == pytest.approx(
            t_s[-1], abs=0.3
        )
        assert result.summary["wall_rc"]["T_m_final_c"] == pytest.approx(
            t_m[-1], abs=0.3
        )
        # slow states: bounded excursion, smooth trajectories
        assert t_s.min() > t_ext.min() - 8.0
        # solar lands ON the surface node: it may run hotter than the air
        assert t_s.max() < t_z.max() + 15.0
        assert np.abs(np.diff(t_s)).max() < 10.0
        assert np.abs(np.diff(t_m)).max() < 6.0
        assert result.summary["temperature_clamp_stats"]["clip_events"] == 0
        rh = np.asarray(result.timeseries["RH_z"], dtype=float)
        assert (rh > 0).all() and (rh <= 100).all()

    def test_size_hvac_uses_series_ua_dc_when_rc3(self):
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
        p_on = rc3_project(hvac={"auto_size": True})
        _build_devices(p_on, P_atm=101.325)
        ua_dc = 52.1 + 1.0 / (1.0 / 384.0 + 1.0 / 60.0 + 1.0 / 35.8)
        assert p_on.hvac.P_rated_w == pytest.approx(
            size_hvac(U_wall_A=ua_dc, **kw), rel=1e-9
        )
        assert p_on.hvac.P_rated_w > size_hvac(U_wall_A=52.1, **kw)
