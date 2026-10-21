"""CO2 supplement M1: mass conservation of the step_co2 integrator.

Contract under test (proposal §2.7, M1 rows):
  * sealed room (no ventilation exchange at solver level), constant
    injection source: delta(c_z * air_mass) == S_inj * dt closes per step
    and the concentration rises linearly at slope S/(V*rho);
  * constant photosynthesis sink: linear decline, no clamp while c_z
    stays above the floor;
  * the Gamma floor clamp engages exactly at c_floor and REPORTS the
    clipped mass via return_meta (clamp is never silent);
  * air_mass <= 0 fails fast.
"""

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "vfed"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from vfed.devices.co2 import ppm_to_mixing_ratio
from vfed.physics.ode import RoomODESolver

V_ROOM = 200.0
RHO = 1.2
AIR_MASS = V_ROOM * RHO
DT = 600.0
GAMMA = 5.2e-5 / RHO  # growth c_Gamma in mixing-ratio form (~4.3e-5 kg/kg)


def test_sealed_constant_injection_mass_closure():
    """delta(c_z*air_mass) == S*dt every step (float-exact to 1e-12)."""
    ode = RoomODESolver(C_z=80000.0, V_room=V_ROOM, rho_air=RHO)
    S = 200.0 / 3.6e6  # 200 g/h -> kg/s
    c = ppm_to_mixing_ratio(420.0)
    for _ in range(144):  # one day of 600 s steps
        c_new = ode.step_co2(c, S, DT)
        assert c_new * AIR_MASS - c * AIR_MASS == pytest.approx(S * DT, rel=1e-12, abs=1e-18)
        c = c_new


def test_sealed_constant_injection_linear_ramp():
    """Closed room, constant source: c(t) = c0 + S*t/(V*rho) exactly
    (no clamp engaged, explicit Euler is exact for a constant rate)."""
    ode = RoomODESolver(C_z=80000.0, V_room=V_ROOM, rho_air=RHO)
    S = 50.0 / 3.6e6
    c0 = ppm_to_mixing_ratio(420.0)
    n = 200
    c = c0
    for _ in range(n):
        c = ode.step_co2(c, S, DT)
    assert c == pytest.approx(c0 + S * n * DT / AIR_MASS, rel=1e-12)


def test_constant_sink_linear_decline_no_clamp():
    """Constant photosynthesis-like sink: linear decline; the floor is NOT
    engaged while c stays above it (meta reports zero clipping)."""
    ode = RoomODESolver(C_z=80000.0, V_room=V_ROOM, rho_air=RHO)
    S = -4.5 / 3.6e6  # 4.5 g/h uptake: ~103 ppm over the window
    c0 = ppm_to_mixing_ratio(800.0)
    c = c0
    n = 50
    for _ in range(n):
        c, meta = ode.step_co2(c, S, DT, c_floor=GAMMA, return_meta=True)
        assert meta["floor_clipped_kg"] == 0.0
    assert c == pytest.approx(c0 + S * n * DT / AIR_MASS, rel=1e-12)


def test_gamma_floor_clamps_and_reports():
    """A sink that would cross the compensation point: c_z clamps AT the
    floor and the removed CO2 mass is reported (not silent)."""
    ode = RoomODESolver(C_z=80000.0, V_room=V_ROOM, rho_air=RHO)
    # start barely above the floor; a sink that drains the whole store
    c0 = GAMMA + 1.0e-6
    S = -1.0e-4  # kg/s: would take c far below Gamma in one step
    c_new, meta = ode.step_co2(c0, S, DT, c_floor=GAMMA, return_meta=True)
    assert c_new == GAMMA
    # unclipped Euler target and the reported clip close the balance:
    c_raw = c0 + S * DT / AIR_MASS
    assert meta["floor_clipped_kg"] == pytest.approx((GAMMA - c_raw) * AIR_MASS, rel=1e-12)
    # no-meta call returns the same clamped state
    assert ode.step_co2(c0, S, DT, c_floor=GAMMA) == GAMMA


def test_default_floor_is_zero():
    """The step_humidity-mirror default floor is 0 kg/kg: a driving sink
    clamps AT zero and reports the phantom mass via meta (not silent)."""
    ode = RoomODESolver(C_z=80000.0, V_room=V_ROOM, rho_air=RHO)
    c_new, meta = ode.step_co2(1.0e-6, -1.0e-4, DT, return_meta=True)
    assert c_new == 0.0
    # clip = (0 - c_raw)*M with c_raw = c0 + S*dt/M  ->  S*dt - c0*M
    assert meta["floor_clipped_kg"] == pytest.approx(
        1.0e-4 * DT - 1.0e-6 * AIR_MASS, rel=1e-12
    )


def test_zero_air_mass_fails_fast():
    with pytest.raises(ValueError, match="V_room \\* rho_air"):
        RoomODESolver(C_z=80000.0, V_room=0.0, rho_air=RHO).step_co2(1e-3, 1e-6, DT)
    with pytest.raises(ValueError, match="V_room \\* rho_air"):
        RoomODESolver(C_z=80000.0, V_room=V_ROOM, rho_air=0.0).step_co2(1e-3, 1e-6, DT)


def test_ventilation_exchange_relaxation():
    """S_vent = m_dot*(c_out - c_z) at solver level: explicit Euler takes
    exactly the linear step c + m_dot*(c_out-c)*dt/M, and iterating drives
    c_z toward c_out (the infiltration channel the engine superposes)."""
    ode = RoomODESolver(C_z=80000.0, V_room=V_ROOM, rho_air=RHO)
    m_dot = 0.05 * V_ROOM * RHO / 3600.0  # 0.05 ACH
    c_out = ppm_to_mixing_ratio(420.0)
    c = ppm_to_mixing_ratio(900.0)
    c_new = ode.step_co2(c, m_dot * (c_out - c), DT)
    assert c_new == pytest.approx(c + m_dot * (c_out - c) * DT / AIR_MASS, rel=1e-15)
    for _ in range(2000):  # e-fold ~ 20 h at 0.05 ACH: pull all the way in
        c = ode.step_co2(c, m_dot * (c_out - c), DT)
    assert c == pytest.approx(c_out, rel=1e-6)
