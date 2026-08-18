"""
Unit tests for HVAC (COPModel, size_hvac) and DEH (size_deh) device models.
"""

import pytest
from vfed.devices.hvac import COPModel, size_hvac


# ── COPModel: Carnot mode ────────────────────────────────────────────

def test_carnot_cop_room_temp():
    """COP drops as outdoor temperature rises (Carnot baseline)."""
    cop = COPModel(mode="carnot", eta_II=0.35, delta_T_evap=8.0, delta_T_cond=15.0)
    # T_room=22°C, T_out=35°C → COP ≈ 2.79
    cop_hot = cop(T_ext=35.0, T_indoor=22.0)
    assert 2.5 < cop_hot < 3.5

    # T_room=22°C, T_out=15°C → higher COP
    cop_cold = cop(T_ext=15.0, T_indoor=22.0)
    assert cop_cold > cop_hot  # cooler outdoor = higher COP


def test_carnot_cop_default_indoor():
    """If T_indoor not given, fallback to 22°C."""
    cop = COPModel(mode="carnot")
    val = cop(T_ext=30.0)
    assert val > 0.5


def test_carnot_cop_zero_delta():
    """When outdoor approaches indoor temp, floor at COP ≥ 0.5."""
    cop = COPModel(mode="carnot", eta_II=0.35, delta_T_evap=0.0, delta_T_cond=0.0)
    val = cop(T_ext=22.0, T_indoor=22.0)
    assert val >= 0.5


def test_carnot_cop_negative_outdoor():
    """Negative outdoor temperatures (winter) — still physically positive COP."""
    cop = COPModel(mode="carnot")
    val = cop(T_ext=-10.0, T_indoor=22.0)
    assert val > 0.5


def test_carnot_cop_high_indoor():
    """High room temp improves Carnot COP (warmer evaporator)."""
    cop = COPModel(mode="carnot")
    cop_low = cop(T_ext=35.0, T_indoor=20.0)
    cop_high = cop(T_ext=35.0, T_indoor=28.0)
    assert cop_high > cop_low


# ── COPModel: Non-Carnot modes ───────────────────────────────────────

def test_constant_cop_ignores_indoor():
    cop = COPModel(mode="constant", value=4.0)
    v1 = cop(T_ext=30.0, T_indoor=22.0)
    v2 = cop(T_ext=30.0, T_indoor=18.0)
    assert v1 == v2 == 4.0


def test_linear_cop_decreases_with_temp():
    cop = COPModel(mode="linear", value=4.0, k=0.02, T_ref=25.0)
    # T_ext = 25: COP = 4.0 * (1 - 0.02*(25-25)) = 4.0
    # T_ext = 35: COP = 4.0 * (1 - 0.02*(35-25)) = 3.2
    assert cop(25.0) == pytest.approx(4.0)
    assert cop(35.0) == pytest.approx(3.2)
    assert cop(40.0) < cop(25.0)


def test_linear_cop_floor():
    cop = COPModel(mode="linear", value=4.0, k=0.1, T_ref=25.0)
    # T_ext = 100: COP = 4.0 * (1 - 0.1*(75)) = -26.0 → floor 1.0
    assert cop(100.0) >= 1.0


def test_table_cop():
    cop = COPModel(mode="table", table={10.0: 5.0, 30.0: 3.0, 40.0: 2.0})
    assert cop(10.0) == pytest.approx(5.0)
    # T=20: linear interp between (10,5) and (30,3) → 4.0
    assert cop(20.0) == pytest.approx(4.0)
    assert cop(30.0) == pytest.approx(3.0)
    assert cop(35.0) == pytest.approx(2.5)  # interp (30,3)→(40,2)
    assert cop(40.0) == pytest.approx(2.0)
    assert cop(50.0) == pytest.approx(2.0)   # above last edge


def test_table_cop_empty():
    cop = COPModel(mode="table", value=4.0, table={})
    assert cop(25.0) == pytest.approx(4.0)


# ── COPModel: runtime floors (defense-in-depth vs negative config) ──

def test_constant_cop_negative_floor():
    """A negative constant COP (bad config/programmatic build) must be
    floored at 0.5 so the cooling cycle never flips into a heater."""
    cop = COPModel(mode="constant", value=-3.0)
    assert cop(35.0) == pytest.approx(0.5)


def test_table_cop_negative_floor():
    """Negative table entries are floored at 0.5 (including interpolation)."""
    cop = COPModel(mode="table", table={10.0: 3.0, 30.0: -1.0})
    assert cop(10.0) == pytest.approx(3.0)   # positive entry untouched
    assert cop(30.0) == pytest.approx(0.5)   # negative endpoint floored
    assert cop(20.0) == pytest.approx(1.0)   # interp (3.0 → -1.0) = 1.0 (still positive)


def test_unknown_mode_negative_floor():
    """Unknown mode falls back to `value` — floored at 0.5."""
    cop = COPModel(mode="quantum", value=-2.0)
    assert cop(30.0) == pytest.approx(0.5)


def test_unknown_mode_default_value():
    """Unknown mode with a sane value still returns that value."""
    cop = COPModel(mode="quantum", value=3.5)
    assert cop(30.0) == pytest.approx(3.5)


# ── size_hvac() ──────────────────────────────────────────────────────

def test_size_hvac_positive():
    """Reasonable building parameters return positive P_rated."""
    p = size_hvac(
        U_wall_A=0.35, A_window=10.0, eta_solar=0.7,
        ach=0.5, V_room=5000, rho_air=1.2, cp_air=1005,
        led_heat_w=3000, equipment_power_w=2000,
        cop=3.0, T_setpoint=24.0,
        T_design_ext=35.0, GHI_design=800.0,
        safety_factor=1.2,
    )
    assert p > 0


def test_size_hvac_no_window():
    """Zero window area reduces load but still positive."""
    p = size_hvac(
        U_wall_A=0.3, A_window=0.0, eta_solar=0.7,
        ach=0.3, V_room=3000, rho_air=1.2, cp_air=1005,
        led_heat_w=2000, equipment_power_w=1000,
        cop=3.0, T_setpoint=22.0,
        T_design_ext=35.0, GHI_design=800.0,
        safety_factor=1.2,
    )
    assert p > 0


def test_size_hvac_cold_outdoor():
    """When outdoor ≤ indoor, load floor is 0 → P_rated = 0."""
    p = size_hvac(
        U_wall_A=0.35, A_window=10.0, eta_solar=0.7,
        ach=0.5, V_room=5000, rho_air=1.2, cp_air=1005,
        led_heat_w=0, equipment_power_w=0,
        cop=3.0, T_setpoint=24.0,
        T_design_ext=10.0, GHI_design=0.0,
        safety_factor=1.2,
    )
    # Outdoor cooler than setpoint + no internal loads → no cooling needed
    assert p == 0.0


def test_size_hvac_low_cop_increases_p_rated():
    """Lower COP → higher electrical rating for same cooling load."""
    args = dict(
        U_wall_A=0.35, A_window=10.0, eta_solar=0.7,
        ach=0.5, V_room=5000, rho_air=1.2, cp_air=1005,
        led_heat_w=3000, equipment_power_w=2000,
        T_setpoint=24.0, T_design_ext=35.0, GHI_design=800.0,
        safety_factor=1.2,
    )
    p_high_cop = size_hvac(cop=4.0, **args)
    p_low_cop = size_hvac(cop=2.0, **args)
    assert p_low_cop > p_high_cop


def test_size_hvac_deh_net_heat_increases_p_rated():
    """DEH net sensible heat (P_comp+fan) at the design point must be
    included in the HVAC design load — otherwise auto-sizing understates
    the nameplate."""
    args = dict(
        U_wall_A=0.35, A_window=10.0, eta_solar=0.7,
        ach=0.5, V_room=5000, rho_air=1.2, cp_air=1005,
        led_heat_w=3000, equipment_power_w=2000,
        cop=3.0, T_setpoint=24.0, T_design_ext=35.0, GHI_design=800.0,
        safety_factor=1.2,
    )
    p_no_deh = size_hvac(**args)
    p_with_deh = size_hvac(deh_net_heat_w=2270.0, **args)
    assert p_with_deh > p_no_deh
    # sensible ratio check: +2270 W sensible → +2270/shr_design/COP*SF electrical
    assert p_with_deh - p_no_deh == pytest.approx(
        2270.0 / 0.80 / 3.0 * 1.2, rel=1e-6)


def test_size_hvac_cold_outdoor_with_deh_heat_still_zero():
    """Even with DEH heat, no cooling needed when design is cold and there
    are no internal loads — the net-load floor still applies."""
    p = size_hvac(
        U_wall_A=0.35, A_window=10.0, eta_solar=0.7,
        ach=0.5, V_room=5000, rho_air=1.2, cp_air=1005,
        led_heat_w=0, equipment_power_w=0,
        cop=3.0, T_setpoint=24.0,
        T_design_ext=10.0, GHI_design=0.0,
        safety_factor=1.2,
        deh_net_heat_w=2270.0,
    )
    assert p == 0.0


# ── size_deh() ───────────────────────────────────────────────────────

from vfed.devices.dehumidifier import size_deh


def test_size_deh_positive():
    p = size_deh(moisture_load_kgs=0.001, smer=2.0, safety_factor=1.2)
    assert p > 0


def test_size_deh_linear():
    """Double moisture load → double P_ref."""
    p1 = size_deh(0.001, smer=2.0, safety_factor=1.0)
    p2 = size_deh(0.002, smer=2.0, safety_factor=1.0)
    assert p2 == pytest.approx(p1 * 2.0)


def test_size_deh_low_smer():
    """Poor SMER → higher electrical rating."""
    p_good = size_deh(0.001, smer=3.0, safety_factor=1.0)
    p_bad = size_deh(0.001, smer=1.0, safety_factor=1.0)
    assert p_bad > p_good


def test_size_deh_zero_load():
    p = size_deh(0.0, smer=2.0, safety_factor=1.2)
    assert p == 0.0
