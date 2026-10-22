"""Tests for the 3-state Van Henten growth model (van_henten_3state).

Covers: lazy state initialisation, reset semantics, read-only fluxes(),
synthetic non-negativity stress, the growth.model config selector, and a
frozen regression of the 30-day PFAL proxy orbit (values computed with this
exact class, cross-checked against the RK45 reference in
scripts/benchmarks/bjaaf_growth/run_euler_check.py; agreement < 0.5%).
"""

import math

import pytest

from vfed.design.project import VanHenten3Config, VanHentenConfig
from vfed.plants.van_henten import VanHenten
from vfed.plants.van_henten_3state import VanHenten3State

# ── frozen proxy orbit anchors (author params, dt=600, 30 d) ──────────────
_PAR = 54.7          # canopy PAR W/m2 during the light period
_DT = 600.0
_N = 30 * 24 * 6     # 4320 steps
_XD0 = 0.008
_LAI0 = 0.32
_RHO_C = 20.0
_FROZEN_DAY15_XD = 0.1116788167
_FROZEN_DAY15_LAI = 5.29732346
_FROZEN_END_XD = 0.2906760367
_FROZEN_END_LAI = 14.99543397
_FROZEN_END_CBUF = 0.0001289633


def _proxy_run(grow):
    """Drive the standard 30-day PFAL proxy orbit; returns final X_d."""
    grow.rh_pct = 70.0
    xd = _XD0
    for s in range(_N):
        hour = (s * _DT / 3600.0) % 24.0
        lit = 8.0 <= hour < 22.0
        t_z = 24.5 if lit else 18.5
        _, xd = grow.step(t_z, _PAR if lit else 0.0, xd, _DT)
    return xd


# ── state lifecycle ────────────────────────────────────────────────────────


def test_lazy_init_and_default_lai():
    g = VanHenten3State(co2_ppm=800.0, rho_c=_RHO_C)
    assert g.C_buf is None and g.LAI is None  # lazy until first use
    g.rh_pct = 70.0
    g.fluxes(24.5, _PAR, _XD0)  # read-only call triggers lazy init only
    assert g.C_buf == 0.0
    assert g.LAI == pytest.approx(_XD0 * 40.0)  # default LAI0 = X_d0 x 40


def test_reset_restores_seedling_state():
    g = VanHenten3State(co2_ppm=800.0, rho_c=_RHO_C, initial_lai=_LAI0)
    g.rh_pct = 70.0
    xd = _XD0
    for _ in range(200):  # ~1.4 d of growth
        _, xd = g.step(24.5, _PAR, xd, _DT)
    assert g.LAI > _LAI0 and g.C_buf != 0.0
    g.reset(_XD0)
    assert g.C_buf == 0.0
    assert g.LAI == pytest.approx(_LAI0)  # explicit initial_lai honoured


def test_unknown_override_raises():
    with pytest.raises(ValueError, match="not_a_param"):
        VanHenten3State(co2_ppm=800.0, not_a_param=1.0)


# ── fluxes contract ────────────────────────────────────────────────────────


def test_fluxes_read_only():
    g = VanHenten3State(co2_ppm=800.0, rho_c=_RHO_C, initial_lai=_LAI0)
    g.rh_pct = 70.0
    g.step(24.5, _PAR, _XD0, _DT)
    c_buf_before, lai_before = g.C_buf, g.LAI
    phi_1, resp_1 = g.fluxes(24.5, _PAR, _XD0)
    phi_2, resp_2 = g.fluxes(24.5, _PAR, _XD0)
    # deterministic, and does not advance internal state
    assert phi_1 == phi_2 and resp_1 == resp_2
    assert g.C_buf == c_buf_before and g.LAI == lai_before
    # phi is the CO2-currency photosynthesis rate (M1 uses it directly),
    # resp the DM-currency maintenance respiration — both finite/positive
    # in the light at 24.5 C.
    assert math.isfinite(phi_1) and phi_1 > 0.0
    assert math.isfinite(resp_1) and resp_1 > 0.0


def test_dark_step_no_nan_and_floor():
    """Cold dark hours (T below the 1-state guard range) must stay finite."""
    g = VanHenten3State(co2_ppm=800.0, rho_c=_RHO_C, initial_lai=_LAI0)
    g.rh_pct = 90.0
    xd = _XD0
    for t_z in (1.0, 5.0, 30.0, 40.0):
        _, xd_new = g.step(t_z, 0.0, xd, _DT)
        assert math.isfinite(xd_new)
        assert xd_new >= 0.0
        assert math.isfinite(g.C_buf) and math.isfinite(g.LAI)


# ── non-negativity stress over a synthetic climate ─────────────────────────


def test_nonnegative_stress_synthetic_climate():
    g = VanHenten3State(co2_ppm=800.0, rho_c=_RHO_C, initial_lai=_LAI0)
    xd = _XD0
    for day in range(10):
        for hour in range(24):
            lit = 8 <= hour < 22
            t_z = 25.0 if lit else 15.0 + 5.0 * math.sin(day)
            g.rh_pct = 60.0 + 10.0 * math.sin(0.3 * (day * 24 + hour))
            _, xd = g.step(t_z, _PAR if lit else 0.0, xd, _DT)
            assert math.isfinite(xd) and xd > 0.0
            assert math.isfinite(g.LAI) and g.LAI > 0.0


# ── config selector (growth.model) ─────────────────────────────────────────


def test_config_default_is_one_state():
    cfg = VanHentenConfig()
    assert cfg.model == "van_henten"
    assert isinstance(cfg.three_state, VanHenten3Config)
    assert cfg.three_state.epsilon_0 == pytest.approx(17e-9)
    assert cfg.three_state.SLA_rf == pytest.approx(47.93)


def test_config_model_whitelist():
    with pytest.raises(ValueError, match="model"):
        VanHentenConfig(model="kozai")


def test_config_three_state_dict_coercion():
    cfg = VanHentenConfig(model="van_henten_3state",
                          three_state={"epsilon_0": 7.3e-9, "rho_c": 11.5})
    assert isinstance(cfg.three_state, VanHenten3Config)
    assert cfg.three_state.epsilon_0 == pytest.approx(7.3e-9)
    assert cfg.three_state.rho_c == pytest.approx(11.5)
    # untouched fields keep defaults
    assert cfg.three_state.c_beta == pytest.approx(0.8)


def test_config_three_state_unknown_key_rejected():
    with pytest.raises(ValueError, match="no_such_field"):
        VanHentenConfig(three_state={"no_such_field": 1.0})


def test_config_three_state_bad_type_rejected():
    with pytest.raises(ValueError):
        VanHentenConfig(three_state=42)


# ── frozen proxy regression ────────────────────────────────────────────────


def test_frozen_proxy_orbit():
    g = VanHenten3State(co2_ppm=800.0, rho_c=_RHO_C, initial_lai=_LAI0)
    g.rh_pct = 70.0
    xd = _XD0
    for s in range(_N):
        hour = (s * _DT / 3600.0) % 24.0
        lit = 8.0 <= hour < 22.0
        _, xd = g.step(24.5 if lit else 18.5, _PAR if lit else 0.0, xd, _DT)
        if s == 2159:  # mid-orbit anchor (day 15)
            assert xd == pytest.approx(_FROZEN_DAY15_XD, rel=1e-8)
            assert g.LAI == pytest.approx(_FROZEN_DAY15_LAI, rel=1e-8)
    assert xd == pytest.approx(_FROZEN_END_XD, rel=1e-8)
    assert g.LAI == pytest.approx(_FROZEN_END_LAI, rel=1e-8)
    assert g.C_buf == pytest.approx(_FROZEN_END_CBUF, rel=1e-6)


def test_one_state_reset_is_noop():
    g = VanHenten()
    g.reset(0.02)  # must not raise; 1-state has no internal states
    _, xd = g.step(25.0, 100.0, 0.02, 600.0)
    assert xd > 0.0
