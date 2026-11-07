"""C2 device-plane runtime overrides: contract tests (zero-drift proof).

Four devices gained optional runtime override inputs (all default None, the
legacy bit-for-bit path):

* ``LEDDevice.step(hour, dim=None)`` — dimming fraction, clamped to [0, 1].
* ``HVACDevice.step(..., m_override=None)`` — replaces the CompressorState
  modulation output m (clamped to [0, 1]); the hysteresis / min_on / min_off
  state machine still runs first.
* ``DEHDevice.step(..., m_override=None)`` — same semantics on the stock
  (vfd / on_off) paths where ``S_DH = m``.
* ``Envelope.mechanical_ventilation(..., flow_override_m3h=None)`` — fresh-air
  flow, clamped to [0, design flow]; a disabled ERV still returns zeros.

Plus two lazy SetpointConfig contract fields (``T_heat`` / ``RH_dark``),
whose engine_loop wiring lands in C2b.  Every override is asserted three
ways: effective value, clamping, and None == legacy call (exact equality).
"""

import pytest

from vfed.design.project import HARD_LIMITS, PARAM_PATH_MAP, DesignProject
from vfed.devices.dehumidifier import DEHDevice
from vfed.devices.hvac import HVACDevice
from vfed.devices.led import LEDDevice
from vfed.physics.envelope import Envelope


# ── LED dimming override ──────────────────────────────────────────────


def led() -> LEDDevice:
    return LEDDevice(power_w=480.0, auto_deduce=False, heat_fraction=0.8)


def test_led_dim_override_scales_outputs():
    dev = led()
    q, p = dev.step(10, dim=0.5)  # hour 10 sits inside the 6-22 photoperiod
    assert q == pytest.approx(0.8 * 480.0 * 0.5)
    assert p == pytest.approx(480.0 * 0.5)


def test_led_dim_override_clamped():
    dev = led()
    assert dev.step(10, dim=1.7) == dev.step(10, dim=1.0)
    assert dev.step(10, dim=-0.3) == (0.0, 0.0)
    assert dev.step(10, dim=0.0) == (0.0, 0.0)


def test_led_dim_none_equals_legacy_call():
    legacy, with_none = led(), led()
    assert with_none.step(10, dim=None) == legacy.step(10)


def test_led_dark_hour_override_stays_zero():
    dev = led()
    assert dev.step(3, dim=1.0) == (0.0, 0.0)  # hour 3 is outside 6-22


# ── HVAC modulation override ──────────────────────────────────────────


def hvac() -> HVACDevice:
    return HVACDevice()


def test_hvac_m_override_replaces_mod():
    base_dev, half_dev = hvac(), hvac()
    for d in (base_dev, half_dev):
        # Warm the state machine ON: at dt=60 s two lead-in steps clear the
        # min_off timer before the modulation output goes positive.
        d.step(30.0, 65.0, 35.0, T_setpoint=22.0)
        d.step(30.0, 65.0, 35.0, T_setpoint=22.0)
    base = base_dev.step(30.0, 65.0, 35.0, T_setpoint=22.0)
    assert base["mode"] == "cool" and base["mod"] > 0.0  # baseline sanity
    half = half_dev.step(30.0, 65.0, 35.0, T_setpoint=22.0, m_override=0.5)
    assert half["mod"] == 0.5
    assert half["is_on"] is True
    assert half["P_elec_W"] < base["P_elec_W"]  # part load draws less power


def test_hvac_m_override_clamped():
    hi = hvac().step(30.0, 65.0, 35.0, T_setpoint=22.0, m_override=1.9)
    assert hi["mod"] == 1.0
    lo = hvac().step(30.0, 65.0, 35.0, T_setpoint=22.0, m_override=-0.4)
    assert lo["mod"] == 0.0
    assert lo["is_on"] is False
    assert lo["P_elec_W"] == 0.0


def test_hvac_m_override_none_equals_legacy_call():
    legacy = hvac().step(30.0, 65.0, 35.0, T_setpoint=22.0)
    with_none = hvac().step(30.0, 65.0, 35.0, T_setpoint=22.0, m_override=None)
    assert with_none == legacy


# ── DEH modulation override (stock path) ──────────────────────────────


def deh() -> DEHDevice:
    return DEHDevice(control="on_off", P_ref_w=2000.0, smer=2.0)


def test_deh_m_override_replaces_mod():
    half_dev, full_dev = deh(), deh()
    for d in (half_dev, full_dev):
        # Two lead-in steps clear the min_off timer (same as the HVAC test).
        d.step(25.0, 80.0, 0.012, deh_setpoint=60.0)
        d.step(25.0, 80.0, 0.012, deh_setpoint=60.0)
    half = half_dev.step(25.0, 80.0, 0.012, deh_setpoint=60.0, m_override=0.5)
    assert half["mod"] == 0.5
    assert half["S_DH"] == 0.5  # stock path: S_DH follows the override
    full = full_dev.step(25.0, 80.0, 0.012, deh_setpoint=60.0)
    assert full["mod"] == 1.0  # on_off control: saturated baseline
    assert half["P_elec_W"] < full["P_elec_W"]


def test_deh_m_override_clamped():
    hi = deh().step(25.0, 80.0, 0.012, deh_setpoint=60.0, m_override=2.5)
    assert hi["mod"] == 1.0
    lo = deh().step(25.0, 80.0, 0.012, deh_setpoint=60.0, m_override=-1.0)
    assert lo["mod"] == 0.0
    assert lo["is_on"] is False
    assert lo["P_elec_W"] == 0.0


def test_deh_m_override_none_equals_legacy_call():
    legacy = deh().step(25.0, 80.0, 0.012, deh_setpoint=60.0)
    with_none = deh().step(25.0, 80.0, 0.012, deh_setpoint=60.0, m_override=None)
    assert with_none == legacy


# ── Envelope ERV flow override ────────────────────────────────────────


def erv_env() -> Envelope:
    return Envelope(
        erv_enabled=True,
        erv_flow_m3h=500.0,
        erv_sensible_eff=0.7,
        erv_latent_eff=0.0,
    )


def test_erv_flow_override_scales_terms():
    env = erv_env()
    base = env.mechanical_ventilation(-7.0, 22.0, 0.002, 0.010)
    half = env.mechanical_ventilation(-7.0, 22.0, 0.002, 0.010, flow_override_m3h=250.0)
    for b, h in zip(base, half):
        assert h == pytest.approx(b * 0.5)


def test_erv_flow_override_clamped():
    env = erv_env()
    design = env.mechanical_ventilation(-7.0, 22.0, 0.002, 0.010)
    above = env.mechanical_ventilation(-7.0, 22.0, 0.002, 0.010, flow_override_m3h=9999.0)
    assert above == design  # cannot exceed the design flow
    closed = env.mechanical_ventilation(-7.0, 22.0, 0.002, 0.010, flow_override_m3h=-5.0)
    assert closed == (0.0, 0.0, 0.0, 0.0, 0.0)  # dampers fully closed


def test_erv_flow_override_none_equals_legacy_call():
    env = erv_env()
    legacy = env.mechanical_ventilation(-7.0, 22.0, 0.002, 0.010)
    with_none = env.mechanical_ventilation(-7.0, 22.0, 0.002, 0.010, flow_override_m3h=None)
    assert with_none == legacy


def test_erv_disabled_stays_zero_despite_override():
    off = Envelope()  # default: ERV hardware disabled
    r = off.mechanical_ventilation(35.0, 22.0, 0.02, 0.012, flow_override_m3h=300.0)
    assert r == (0.0, 0.0, 0.0, 0.0, 0.0)


# ── SetpointConfig lazy contract fields (T_heat / RH_dark) ────────────


def test_T_heat_RH_dark_roundtrip_emitted_when_set():
    p = DesignProject.from_dict({"setpoints": {"T_heat": 18.0, "RH_dark": 60.0}})
    assert p.setpoints.T_heat == 18.0
    assert p.setpoints.RH_dark == 60.0
    d = p.to_dict()
    assert d["setpoints"]["T_heat"] == 18.0
    assert d["setpoints"]["RH_dark"] == 60.0
    p2 = DesignProject.from_dict(d)
    assert p2.setpoints.T_heat == 18.0
    assert p2.setpoints.RH_dark == 60.0


def test_T_heat_RH_dark_default_none_and_omitted():
    p = DesignProject.from_dict({})
    assert p.setpoints.T_heat is None
    assert p.setpoints.RH_dark is None
    d = p.to_dict()
    assert "T_heat" not in d["setpoints"]
    assert "RH_dark" not in d["setpoints"]
    p2 = DesignProject.from_dict(d)  # lossless without the sentinels
    assert p2.setpoints.T_heat is None
    assert p2.setpoints.RH_dark is None


def test_T_heat_RH_dark_null_sentinel_means_inherit():
    p = DesignProject.from_dict({"setpoints": {"T_heat": None, "RH_dark": None}})
    assert p.setpoints.T_heat is None
    assert p.setpoints.RH_dark is None


@pytest.mark.parametrize("field,bad", [("T_heat", 35.0), ("T_heat", 5.0), ("RH_dark", 95.0), ("RH_dark", 20.0)])
def test_T_heat_RH_dark_hard_limits_reject_out_of_band(field, bad):
    with pytest.raises(ValueError) as ei:
        DesignProject.from_dict({"setpoints": {field: bad}})
    assert f"setpoints.{field}" in str(ei.value)
    assert "hard limit" in str(ei.value)


def test_T_heat_RH_dark_band_edges_accepted():
    lo_t, hi_t = HARD_LIMITS["T_heat"]
    lo_r, hi_r = HARD_LIMITS["RH_dark"]
    for v in (lo_t, hi_t):
        assert DesignProject.from_dict({"setpoints": {"T_heat": v}}).setpoints.T_heat == v
    for v in (lo_r, hi_r):
        assert DesignProject.from_dict({"setpoints": {"RH_dark": v}}).setpoints.RH_dark == v


def test_T_heat_RH_dark_registered_in_tables():
    # Sweep coverage requires both the band and the YAML path mapping.
    assert PARAM_PATH_MAP["T_heat"] == ("setpoints", "T_heat")
    assert PARAM_PATH_MAP["RH_dark"] == ("setpoints", "RH_dark")
    assert set(PARAM_PATH_MAP) | {"pv_area", "battery"} >= {"T_heat", "RH_dark"}
    assert set(HARD_LIMITS) >= {"T_heat", "RH_dark"}
