"""
Layer 12: plant-parameter configuration (P1-6).

Covers the transpiration plants_per_m2 density field (T3), the unified
reference-scenario direct-set defaults (T4: mature lettuce ~1.5 L/m2/day at
25 plants/m2), and the guarantee that the van_henten model-coupled path is
untouched by the direct-set default change.
"""
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "vfed"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from vfed.design.project import DesignProject, TranspirationConfig
from vfed.design.presets import preset_609
from vfed.plants.transpiration import TranspirationModel


# ---------------------------------------------------------------------------
# T3: plants_per_m2 -> plant_count derivation
# ---------------------------------------------------------------------------
def test_plants_per_m2_round_trip():
    """plants_per_m2 loads into the config; plant_count stays untouched
    (derivation happens at engine build time, not in the config)."""
    p = DesignProject.from_dict(
        {"transpiration": {"method": "per_plant", "plants_per_m2": 25.0}}
    )
    assert p.transpiration.plants_per_m2 == pytest.approx(25.0)
    assert p.transpiration.plant_count == 0  # config-level: not materialised


def test_plants_per_m2_derives_plant_count_in_engine():
    """per_plant + plant_count=0 + plants_per_m2=25 -> engine derives
    round(25 x 45 m2 default canopy) = 1125 plants."""
    from vfed.design.engine import _build_devices

    p = DesignProject.from_dict(
        {"transpiration": {"method": "per_plant", "plants_per_m2": 25.0}}
    )
    _, _, _, _, transp, _ = _build_devices(p)
    assert transp.plant_count == 1125


def test_plants_per_m2_derivation_tracks_covered_area():
    """Density x configured canopy area, rounded: 25 x 80 m2 = 2000."""
    from vfed.design.engine import _build_devices

    p = DesignProject.from_dict(
        {
            "led": {"covered_area": 80.0},
            "transpiration": {"method": "per_plant", "plants_per_m2": 25.0},
        }
    )
    _, _, _, _, transp, _ = _build_devices(p)
    assert transp.plant_count == 2000


def test_per_plant_per_period_derivation_and_runtime():
    """per_plant_per_period derives the count too and the model runs."""
    from vfed.design.engine import _build_devices

    p = DesignProject.from_dict(
        {
            "transpiration": {
                "method": "per_plant_per_period",
                "plants_per_m2": 25.0,
            }
        }
    )
    _, _, _, _, transp, _ = _build_devices(p)
    assert transp.plant_count == 1125
    rate = transp.step(T_z=22.0, RH_z=65.0, is_light=True, dt=60.0, cycle_day=5.0)
    assert rate > 0.0


def test_explicit_plant_count_wins_over_density():
    """When both are given, plant_count is used as-is (no silent override)."""
    from vfed.design.engine import _build_devices

    p = DesignProject.from_dict(
        {
            "transpiration": {
                "method": "per_plant",
                "plant_count": 100,
                "plants_per_m2": 25.0,
            }
        }
    )
    _, _, _, _, transp, _ = _build_devices(p)
    assert transp.plant_count == 100


def test_per_plant_without_count_and_density_fails_fast():
    """Existing behaviour kept: neither source usable -> E-level ValueError
    that now also mentions plants_per_m2 (P1-6 message upgrade)."""
    for method in ("per_plant", "per_plant_per_period"):
        with pytest.raises(ValueError, match="plants_per_m2"):
            DesignProject.from_dict({"transpiration": {"method": method}})


@pytest.mark.parametrize("bad", [0, -1, 201, 1e4, "25", True])
def test_plants_per_m2_invalid_values_fail_fast(bad):
    """Density must be a number in (0, 200] plants/m2 -- anything else is a
    unit mistake and fails fast at load."""
    with pytest.raises(ValueError, match="plants_per_m2"):
        DesignProject.from_dict(
            {"transpiration": {"method": "per_plant", "plants_per_m2": bad}}
        )


# ---------------------------------------------------------------------------
# T4: unified reference-scenario defaults
# ---------------------------------------------------------------------------
def test_unified_default_water_values():
    """All four direct-set defaults anchor to one scenario: mature lettuce
    ~1.5 L/m2/day @ 25 plants/m2 on the 45 m2 default canopy."""
    t = TranspirationConfig()
    assert t.daily_water_L == pytest.approx(67.5)  # 1.5 x 45
    assert t.ml_per_plant_day == pytest.approx(60.0)  # 1500 / 25
    assert t.daily_water_L_period == pytest.approx([22.5, 45.0, 90.0])  # 0.5/1.0/2.0 x 45
    assert t.ml_per_plant_day_period == pytest.approx([20.0, 40.0, 80.0])  # ladder x 1000/25


def test_default_scenario_self_consistency():
    """per-plant defaults reproduce the canopy totals at the reference
    density (25 plants/m2) and canopy (45 m2): same L/day per stage."""
    t = TranspirationConfig()
    density, area = 25.0, 45.0
    assert density * area * t.ml_per_plant_day / 1000.0 == pytest.approx(t.daily_water_L)
    staged_L = [density * area * ml / 1000.0 for ml in t.ml_per_plant_day_period]
    assert staged_L == pytest.approx(t.daily_water_L_period)


def test_model_defaults_match_config_defaults():
    """The runtime TranspirationModel carries the same unified defaults."""
    t, m = TranspirationConfig(), TranspirationModel()
    assert m.daily_water_L == pytest.approx(t.daily_water_L)
    assert m.ml_per_plant_day == pytest.approx(t.ml_per_plant_day)
    assert m.daily_water_L_period == pytest.approx(t.daily_water_L_period)
    assert m.ml_per_plant_day_period == pytest.approx(t.ml_per_plant_day_period)


# ---------------------------------------------------------------------------
# T4 non-regression: the van_henten path ignores direct-set fields
# ---------------------------------------------------------------------------
def test_van_henten_sizing_independent_of_direct_set_defaults():
    """609 (van_henten) device sizing must be bit-identical under the old
    (40/80/[30,45,60]/[10,30,50]) and new (67.5/60/...) direct-set defaults
    -- the model-coupled path never reads them, so the P1-3b baseline cannot
    drift from T4."""
    from vfed.design.engine import _build_devices

    p_new = preset_609()
    env_a, hvac_a, deh_a, led_a, transp_a, _ = _build_devices(p_new)

    p_old = preset_609()
    p_old.transpiration.daily_water_L = 40.0
    p_old.transpiration.ml_per_plant_day = 80.0
    p_old.transpiration.daily_water_L_period = [30.0, 45.0, 60.0]
    p_old.transpiration.ml_per_plant_day_period = [10.0, 30.0, 50.0]
    env_b, hvac_b, deh_b, led_b, transp_b, _ = _build_devices(p_old)

    assert hvac_a.P_rated == pytest.approx(hvac_b.P_rated)
    assert deh_a.P_ref == pytest.approx(deh_b.P_ref)
    # and the runtime model rate does not depend on the direct-set fields
    ra = transp_a.step(T_z=22.0, RH_z=65.0, is_light=True, dt=60.0, X_d=0.3)
    rb = transp_b.step(T_z=22.0, RH_z=65.0, is_light=True, dt=60.0, X_d=0.3)
    assert ra == pytest.approx(rb)


def test_van_henten_is_still_the_default_method():
    """Guard the default family choice itself."""
    assert TranspirationConfig().method == "van_henten"
    assert TranspirationModel().method == "van_henten"
    assert preset_609().transpiration.method == "van_henten"
