"""
Unit tests for transpiration model — all 5 methods, edge cases, and
consistency between equivalent configurations.
"""

import pytest
from vfed.plants.transpiration import TranspirationModel


# ── Helper ───────────────────────────────────────────────────────────

def _light(T_z=22.0, RH_z=65.0, is_light=True, dt=60.0, **kw):
    """Simulate one step with standard lettuce conditions."""
    return TranspirationModel(**kw).step(T_z, RH_z, is_light, dt, cycle_day=5.0)


def _dark(T_z=22.0, RH_z=65.0, dt=60.0, **kw):
    return TranspirationModel(**kw).step(T_z, RH_z, False, dt, cycle_day=5.0)


# ── Daily method ─────────────────────────────────────────────────────

def test_daily_total_correct():
    """40 L/day over 16h photoperiod → ~6.94e-4 kg/s during light."""
    model = TranspirationModel(method="daily", daily_water_L=40.0,
                               photoperiod_hours=16.0, area_m2=45.0)
    rate = model.step(T_z=22.0, RH_z=65.0, is_light=True, dt=60.0)

    # 40 L/day = 40 kg/day. Over 16h = 40/(16*3600) = 6.944e-4 kg/s
    expected = 40.0 / (16.0 * 3600.0)
    assert rate == pytest.approx(expected, rel=0.01)


def test_daily_dark_transpiration_fraction():
    """暗期透蒸 = 光期 × dark_transpiration_frac(0.15)（Caird 2007 夜间气孔不完全关闭）。"""
    model = TranspirationModel(method="daily", daily_water_L=40.0,
                               photoperiod_hours=16.0)
    rate = model.step(T_z=22.0, RH_z=65.0, is_light=False, dt=60.0)
    expected = 0.15 * 40.0 / (16.0 * 3600.0)
    assert rate == pytest.approx(expected, rel=0.01)


def test_daily_stage_factor():
    model = TranspirationModel(method="daily", daily_water_L=40.0,
                               photoperiod_hours=16.0, stage_factor=0.5)
    rate = model.step(T_z=22.0, RH_z=65.0, is_light=True, dt=60.0)
    expected = 20.0 / (16.0 * 3600.0)  # half rate
    assert rate == pytest.approx(expected, rel=0.01)


# ── Per-plant method ─────────────────────────────────────────────────

def test_per_plant_total_correct():
    """500 plants × 80 mL/plant/day = 40 L/day."""
    model = TranspirationModel(method="per_plant", plant_count=500,
                               ml_per_plant_day=80.0, photoperiod_hours=16.0)
    rate = model.step(T_z=22.0, RH_z=65.0, is_light=True, dt=60.0)

    # 500 × 80 = 40,000 mL = 40 L. Over 16h = 40/(16*3600) = 6.944e-4 kg/s
    expected = 40.0 / (16.0 * 3600.0)
    assert rate == pytest.approx(expected, rel=0.01)


def test_per_plant_zero_count():
    """0 plants → fail-fast ValueError (P3-5): a silent zero would collapse
    room humidity and leave the DEH never running."""
    model = TranspirationModel(method="per_plant", plant_count=0,
                               ml_per_plant_day=80.0)
    with pytest.raises(ValueError, match="plant_count"):
        model.step(T_z=22.0, RH_z=65.0, is_light=True, dt=60.0)


def test_per_plant_dark_transpiration_fraction():
    model = TranspirationModel(method="per_plant", plant_count=100,
                               ml_per_plant_day=80.0, photoperiod_hours=16.0)
    rate = model.step(T_z=22.0, RH_z=65.0, is_light=False, dt=60.0)
    day_rate = 100.0 * 80.0 / 1000.0 / (16.0 * 3600.0)
    assert rate == pytest.approx(0.15 * day_rate, rel=0.01)


# ── Equivalence: daily vs per_plant ──────────────────────────────────

def test_daily_per_plant_equivalent():
    """Same total L/day → same instantaneous rate."""
    model_d = TranspirationModel(method="daily", daily_water_L=40.0,
                                 photoperiod_hours=16.0)
    model_p = TranspirationModel(method="per_plant", plant_count=500,
                                 ml_per_plant_day=80.0, photoperiod_hours=16.0)
    rate_d = model_d.step(T_z=22.0, RH_z=65.0, is_light=True, dt=60.0)
    rate_p = model_p.step(T_z=22.0, RH_z=65.0, is_light=True, dt=60.0)
    assert rate_d == pytest.approx(rate_p, rel=1e-4)


# ── Van Henten method ────────────────────────────────────────────────

def test_van_henten_positive():
    model = TranspirationModel(method="van_henten", k_van_henten=1e-4, area_m2=45.0)
    rate = model.step(T_z=22.0, RH_z=65.0, is_light=True, dt=60.0, X_d=0.05)
    assert rate > 0


def test_van_henten_dark_transpiration_fraction():
    """暗期透蒸 = 0.15 × 光期（气孔夜间不完全关闭，VPD 驱动仍有效）。"""
    model = TranspirationModel(method="van_henten", k_van_henten=1e-4)
    day = model.step(T_z=22.0, RH_z=65.0, is_light=True, dt=60.0, X_d=0.05)
    night = model.step(T_z=22.0, RH_z=65.0, is_light=False, dt=60.0, X_d=0.05)
    assert night == pytest.approx(0.15 * day, rel=0.01)


def test_van_henten_biomass_coupling():
    """More biomass → more transpiration."""
    model = TranspirationModel(method="van_henten", k_van_henten=1e-4, area_m2=45.0)
    rate_small = model.step(T_z=22.0, RH_z=65.0, is_light=True, dt=60.0, X_d=0.01)
    rate_large = model.step(T_z=22.0, RH_z=65.0, is_light=True, dt=60.0, X_d=0.05)
    assert rate_large > rate_small


# ── daily_per_period method ──────────────────────────────────────────

def test_daily_per_period_stage_selection():
    """period_days=[10,10,10], daily_water_L_period=[30,45,60] →
    day 5 → 30 L/day, day 15 → 45 L/day, day 25 → 60 L/day."""
    model = TranspirationModel(method="daily_per_period", photoperiod_hours=16.0,
                               period_days=[10.0, 10.0, 10.0],
                               daily_water_L_period=[30.0, 45.0, 60.0])
    r5 = model.step(22.0, 65.0, True, 60.0, cycle_day=5.0)
    r15 = model.step(22.0, 65.0, True, 60.0, cycle_day=15.0)
    r25 = model.step(22.0, 65.0, True, 60.0, cycle_day=25.0)
    assert r5 == pytest.approx(30.0 / (16.0 * 3600.0), rel=1e-4)
    assert r15 == pytest.approx(45.0 / (16.0 * 3600.0), rel=1e-4)
    assert r25 == pytest.approx(60.0 / (16.0 * 3600.0), rel=1e-4)


def test_daily_per_period_stage_boundaries():
    """Left-closed right-open: day<10 → stage0, 10≤day<20 → stage1, ≥20 → stage2.
    cycle_day beyond sum(period_days) clamps to the last stage."""
    model = TranspirationModel(method="daily_per_period", photoperiod_hours=16.0,
                               period_days=[10.0, 10.0, 10.0],
                               daily_water_L_period=[30.0, 45.0, 60.0])
    r0 = model.step(22.0, 65.0, True, 60.0, cycle_day=0.0)
    r10 = model.step(22.0, 65.0, True, 60.0, cycle_day=10.0)
    r20 = model.step(22.0, 65.0, True, 60.0, cycle_day=20.0)
    r35 = model.step(22.0, 65.0, True, 60.0, cycle_day=35.0)
    assert r0 == pytest.approx(30.0 / (16.0 * 3600.0), rel=1e-4)
    assert r10 == pytest.approx(45.0 / (16.0 * 3600.0), rel=1e-4)
    assert r20 == pytest.approx(60.0 / (16.0 * 3600.0), rel=1e-4)
    assert r35 == pytest.approx(60.0 / (16.0 * 3600.0), rel=1e-4)


def test_daily_per_period_dark_transpiration_fraction():
    model = TranspirationModel(method="daily_per_period", photoperiod_hours=16.0,
                               daily_water_L_period=[30.0, 45.0, 60.0])
    rate = model.step(T_z=22.0, RH_z=65.0, is_light=False, dt=60.0, cycle_day=5.0)
    day_rate = 30.0 / (16.0 * 3600.0)  # stage 0
    assert rate == pytest.approx(0.15 * day_rate, rel=0.01)


def test_period_method_requires_cycle_day():
    """Period methods must receive cycle_day — a missing clock would silently
    mis-select stages. Fail fast instead."""
    model = TranspirationModel(method="daily_per_period")
    with pytest.raises(ValueError, match="cycle_day"):
        model.step(T_z=22.0, RH_z=65.0, is_light=True, dt=60.0)


# ── per_plant_per_period method ──────────────────────────────────────

def test_per_plant_per_period_stage_selection():
    """1000 plants × ml_per_plant_day_period=[10,30,50] mL → 10/30/50 L/day."""
    model = TranspirationModel(method="per_plant_per_period", plant_count=1000,
                               photoperiod_hours=16.0,
                               period_days=[10.0, 10.0, 10.0],
                               ml_per_plant_day_period=[10.0, 30.0, 50.0])
    r5 = model.step(22.0, 65.0, True, 60.0, cycle_day=5.0)
    r15 = model.step(22.0, 65.0, True, 60.0, cycle_day=15.0)
    r25 = model.step(22.0, 65.0, True, 60.0, cycle_day=25.0)
    assert r5 == pytest.approx(10.0 / (16.0 * 3600.0), rel=1e-4)
    assert r15 == pytest.approx(30.0 / (16.0 * 3600.0), rel=1e-4)
    assert r25 == pytest.approx(50.0 / (16.0 * 3600.0), rel=1e-4)


def test_per_plant_per_period_zero_count():
    model = TranspirationModel(method="per_plant_per_period", plant_count=0,
                               ml_per_plant_day_period=[10.0, 30.0, 50.0])
    with pytest.raises(ValueError, match="plant_count"):
        model.step(22.0, 65.0, True, 60.0, cycle_day=5.0)


def test_per_plant_per_period_dark_transpiration_fraction():
    model = TranspirationModel(method="per_plant_per_period", plant_count=100,
                               photoperiod_hours=16.0,
                               ml_per_plant_day_period=[10.0, 30.0, 50.0])
    rate = model.step(T_z=22.0, RH_z=65.0, is_light=False, dt=60.0, cycle_day=5.0)
    day_rate = 100.0 * 10.0 / 1000.0 / (16.0 * 3600.0)  # stage 0
    assert rate == pytest.approx(0.15 * day_rate, rel=0.01)


# ── design_rate_kgs (DEH sizing) ─────────────────────────────────────

def test_design_rate_peak_stage():
    """Sizing rate = peak stage instantaneous rate (P3-4 peak logic)."""
    m = TranspirationModel(method="daily", daily_water_L=40.0, photoperiod_hours=16.0)
    assert m.design_rate_kgs() == pytest.approx(40.0 / (16.0 * 3600.0))

    m = TranspirationModel(method="per_plant", plant_count=1000,
                           ml_per_plant_day=80.0, photoperiod_hours=16.0)
    assert m.design_rate_kgs() == pytest.approx(80.0 / (16.0 * 3600.0))

    m = TranspirationModel(method="daily_per_period", photoperiod_hours=16.0,
                           daily_water_L_period=[30.0, 45.0, 60.0])
    assert m.design_rate_kgs() == pytest.approx(60.0 / (16.0 * 3600.0))

    m = TranspirationModel(method="per_plant_per_period", plant_count=1000,
                           photoperiod_hours=16.0,
                           ml_per_plant_day_period=[10.0, 30.0, 50.0])
    assert m.design_rate_kgs() == pytest.approx(50.0 / (16.0 * 3600.0))


def test_design_rate_stage_factor_multiplies():
    m = TranspirationModel(method="daily", daily_water_L=40.0,
                           photoperiod_hours=16.0, stage_factor=1.2)
    assert m.design_rate_kgs() == pytest.approx(1.2 * 40.0 / (16.0 * 3600.0))


def test_design_rate_van_henten_guarded():
    """van_henten sizing goes through the engine growth pre-run, not here."""
    m = TranspirationModel(method="van_henten")
    with pytest.raises(ValueError):
        m.design_rate_kgs()


# ── Legacy / unknown methods ─────────────────────────────────────────

@pytest.mark.parametrize("legacy,hint", [
    ("vpd", "van_henten"),
    ("stomatal", "van_henten"),
    ("constant", "daily"),
])
def test_legacy_method_fails_fast_with_hint(legacy, hint):
    """Removed methods raise ValueError with a migration hint."""
    model = TranspirationModel(method=legacy)
    with pytest.raises(ValueError, match=hint):
        model.step(T_z=22.0, RH_z=65.0, is_light=True, dt=60.0)


def test_unknown_method_fails_fast():
    """Unknown method raises ValueError (legacy silent-zero removed)."""
    model = TranspirationModel(method="nonexistent")
    with pytest.raises(ValueError, match="method"):
        model.step(T_z=22.0, RH_z=65.0, is_light=True, dt=60.0)


# ── Light factor: all methods 0.15× in dark ─────────────────────────

@pytest.mark.parametrize("method", ["van_henten", "daily", "per_plant",
                                    "daily_per_period", "per_plant_per_period"])
def test_method_dark_transpiration_fraction(method):
    """所有方法暗期透蒸 = 光期 × dark_transpiration_frac(0.15)
    （Caird et al. 2007：E_night/E_day 5-15%，PFAL 夜间 VPD 不降取上限）。"""
    model = TranspirationModel(method=method, plant_count=100,
                               daily_water_L_period=[30.0, 45.0, 60.0],
                               ml_per_plant_day_period=[10.0, 30.0, 50.0])
    day = model.step(T_z=22.0, RH_z=65.0, is_light=True, dt=60.0, cycle_day=5.0)
    night = model.step(T_z=22.0, RH_z=65.0, is_light=False, dt=60.0, cycle_day=5.0)
    assert night == pytest.approx(0.15 * day, rel=0.01)
