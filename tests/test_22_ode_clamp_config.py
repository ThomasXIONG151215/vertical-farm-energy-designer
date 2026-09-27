"""ODE thermal clamp configurability (R27-C, ASHRAE 140 BESTEST prep).

The clamp bounds used to be constructor defaults only, so the engine path
(``_build_devices`` never passes T_min/T_max) was stuck at [-20, 60] degC.
Case 600FF free-float reference peaks reach 62.4-68.4 degC, so the BESTEST
harness needs to raise the ceiling WITHOUT touching engine.py.  Contract:
production default behaviour is bit-for-bit unchanged (60 stays 60).
"""

import pytest

from vfed.physics.ode import RoomODESolver


class TestClampDefaultsUnchanged:
    def test_default_bounds_are_minus20_60(self):
        s = RoomODESolver(C_z=1000.0)
        assert s.T_min == -20.0
        assert s.T_max == 60.0

    def test_default_step_still_clamps_at_60(self):
        s = RoomODESolver(C_z=1000.0)
        T_new, meta = s.step_temperature(
            59.9, Q_total_W=100.0, dt=600.0, return_meta=True
        )
        # 59.9 + 100*600/(1000*3600) = 59.9 + 0.01667 -> below clamp, no clip
        assert T_new == pytest.approx(59.9 + 100.0 * 600.0 / (1000.0 * 3600.0))
        assert meta["clipped_deg_c"] == 0.0

    def test_default_step_clips_above_60_with_meta(self):
        s = RoomODESolver(C_z=1000.0)
        # 60.0 + 100kW*600s/(1000Wh/K*3600) = 60 + 16.67 = 76.67 -> clipped
        # at 60, staying inside the +-100 divergence guard.
        T_new, meta = s.step_temperature(
            60.0, Q_total_W=100_000.0, dt=600.0, return_meta=True
        )
        assert T_new == 60.0
        assert meta["clipped_deg_c"] == pytest.approx(
            100_000.0 * 600.0 / (1000.0 * 3600.0), rel=1e-9
        )


class TestExplicitInjection:
    def test_constructor_t_max_respected(self):
        s = RoomODESolver(C_z=1000.0, T_max=90.0)
        assert s.T_max == 90.0
        # 89.0 + 4kW*600s/(1000*3600) = 89.667: above 60, below 90, no clip
        T_new, meta = s.step_temperature(
            89.0, Q_total_W=4_000.0, dt=600.0, return_meta=True
        )
        assert T_new == 89.0 + 4_000.0 * 600.0 / (1000.0 * 3600.0)
        assert meta["clipped_deg_c"] == 0.0

    def test_constructor_t_min_respected(self):
        s = RoomODESolver(C_z=1000.0, T_min=-40.0)
        assert s.T_min == -40.0

    def test_explicit_param_beats_module_override(self):
        import vfed.physics.ode as ode_mod

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(ode_mod, "_DEFAULT_T_MAX", 90.0)
            s = RoomODESolver(C_z=1000.0, T_max=60.0)
            assert s.T_max == 60.0


class TestModuleLevelOverride:
    """Harness injection path: override the module constant, build WITHOUT
    T_max (exactly what the engine's ``_build_devices`` does)."""

    def test_override_raises_ceiling_for_none_default(self):
        import vfed.physics.ode as ode_mod

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(ode_mod, "_DEFAULT_T_MAX", 90.0)
            s = ode_mod.RoomODESolver(C_z=1000.0)
            assert s.T_max == 90.0
            # 600FF-style: a 65 degC state is no longer clipped
            T_new, meta = s.step_temperature(65.0, 0.0, dt=600.0, return_meta=True)
            assert T_new == 65.0
            assert meta["clipped_deg_c"] == 0.0

    def test_override_restored_by_monkeypatch(self):
        # Sanity: the override is not sticky across tests (default path intact)
        s = RoomODESolver(C_z=1000.0)
        assert s.T_max == 60.0

    def test_divergence_guard_still_active_above_100(self):
        import vfed.physics.ode as ode_mod

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(ode_mod, "_DEFAULT_T_MAX", 90.0)
            s = ode_mod.RoomODESolver(C_z=1000.0)
            # Between T_max=90 and the +-100 divergence bound: clipped, no raise
            # (95.0 + 10kW*600s/(1000*3600) = 96.67 -> clipped at 90)
            T_new, meta = s.step_temperature(
                95.0, 10_000.0, dt=600.0, return_meta=True
            )
            assert T_new == 90.0
            assert meta["clipped_deg_c"] > 0.0
            # Beyond +-100: the guard still trips (Magnus validity bound)
            with pytest.raises(RuntimeError, match="diverged"):
                s.step_temperature(99.9, 10_000.0, dt=600.0)
