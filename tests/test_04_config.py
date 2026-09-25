"""
Layer 4: Configuration validation — from_dict, parameter_ranges, objective.

Ensures YAML config parsing catches errors and validates ranges.
"""
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "vfed"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from vfed.design.project import DesignProject


# ---------------------------------------------------------------------------
# 4.1  from_dict — unknown keys
# ---------------------------------------------------------------------------
class TestFromDictErrors:
    def test_unknown_top_level_key_raises(self):
        """A typo in a top-level YAML key should raise ValueError."""
        with pytest.raises(ValueError, match="Unrecognised top-level"):
            DesignProject.from_dict({"bad_toplevel": 42})

    def test_unknown_section_key_raises(self):
        """A typo inside a section should raise ValueError."""
        with pytest.raises(ValueError, match="Unrecognised keys"):
            DesignProject.from_dict({
                "led": {"ppfd_target": 400, "not_a_real_field": 999}
            })

    def test_known_keys_pass(self):
        """from_dict with only known keys should succeed."""
        d = {
            "name": "test",
            "site": {"lat": 31.0, "lon": 121.0},
            "led": {"ppfd_target": 300},
        }
        p = DesignProject.from_dict(d)
        assert p.name == "test"
        assert p.site.lat == 31.0
        assert p.led.ppfd_target == 300.0

    def test_unknown_capital_key_raises(self):
        """A typo inside a nested 'capital' block should raise."""
        with pytest.raises(ValueError, match="Unrecognised keys in 'led.capital'"):
            DesignProject.from_dict({
                "led": {
                    "ppfd_target": 400,
                    "capital": {"mode": "direct", "not_a_key": 1.0}
                }
            })

    def test_round_trip_preserves_values(self):
        """to_dict -> from_dict must be lossless."""
        from vfed.design.presets import preset_609

        p1 = preset_609()
        p2 = DesignProject.from_dict(p1.to_dict())
        assert p2.site.lat == p1.site.lat
        assert p2.led.ppfd_target == p1.led.ppfd_target
        assert p2.hvac.P_rated_w == p1.hvac.P_rated_w

    # ── Carnot COP config ───────────────────────────────────────────

    def test_carnot_cop_params_round_trip(self):
        """Carnot COP fields survive YAML round-trip."""
        d = {
            "hvac": {
                "cop_mode": "carnot",
                "eta_II": 0.30,
                "delta_T_evap": 10.0,
                "delta_T_cond": 18.0,
            }
        }
        p = DesignProject.from_dict(d)
        assert p.hvac.cop_mode == "carnot"
        assert p.hvac.eta_II == pytest.approx(0.30)
        assert p.hvac.delta_T_evap == pytest.approx(10.0)
        assert p.hvac.delta_T_cond == pytest.approx(18.0)

    def test_carnot_defaults(self):
        """Carnot COP fields have sensible defaults."""
        p = DesignProject.from_dict({"hvac": {"cop_mode": "carnot"}})
        assert p.hvac.eta_II == pytest.approx(0.35)
        assert p.hvac.delta_T_evap == pytest.approx(8.0)
        assert p.hvac.delta_T_cond == pytest.approx(15.0)

    def test_t_coil_drop_round_trip(self):
        """Supply-air coil depression survives YAML round-trip."""
        d = {"hvac": {"t_coil_drop": 12.0}}
        p = DesignProject.from_dict(d)
        assert p.hvac.t_coil_drop == pytest.approx(12.0)
        p2 = DesignProject.from_dict(p.to_dict())
        assert p2.hvac.t_coil_drop == pytest.approx(12.0)

    def test_t_coil_drop_default(self):
        """t_coil_drop defaults to 9 degC (real AC supply-air drop)."""
        p = DesignProject.from_dict({"hvac": {}})
        assert p.hvac.t_coil_drop == pytest.approx(9.0)

    def test_auto_size_defaults(self):
        """HVAC and DEH auto_size defaults to False."""
        p = DesignProject.from_dict({"hvac": {}, "deh": {}})
        assert p.hvac.auto_size is False
        assert p.deh.auto_size is False

    def test_auto_size_round_trip(self):
        """auto_size survives YAML round-trip."""
        d = {"hvac": {"auto_size": True}, "deh": {"auto_size": True}}
        p = DesignProject.from_dict(d)
        p2 = DesignProject.from_dict(p.to_dict())
        assert p2.hvac.auto_size is True
        assert p2.deh.auto_size is True

    # ── DEH control mode (P1-1) ──────────────────────────────────────

    def test_deh_control_defaults_to_vfd(self):
        """DEH control defaults to 'vfd' — existing projects keep their
        baseline behaviour (bitwise-identical physics)."""
        p = DesignProject.from_dict({"deh": {}})
        assert p.deh.control == "vfd"

    def test_deh_control_on_off_accepted_and_round_trips(self):
        """'on_off' (full-speed cycling at rated SMER) loads and survives
        a YAML round-trip."""
        p = DesignProject.from_dict({"deh": {"control": "on_off"}})
        assert p.deh.control == "on_off"
        p2 = DesignProject.from_dict(p.to_dict())
        assert p2.deh.control == "on_off"

    def test_deh_control_invalid_rejected(self):
        """An unknown control mode fails fast at load time — it must never
        silently fall back to the VFD path."""
        with pytest.raises(ValueError, match="deh.control"):
            DesignProject.from_dict({"deh": {"control": "turbo"}})

    def test_old_style_cop_loads_with_defaults(self):
        """YAML without Carnot params (old constant-mode) still works."""
        d = {"hvac": {"cop_mode": "constant", "cop_value": 4.0}}
        p = DesignProject.from_dict(d)
        assert p.hvac.cop_mode == "constant"
        # Carnot fields get defaults
        assert p.hvac.eta_II == pytest.approx(0.35)

    # ── PV temperature-coefficient dimension guards ──────────────────

    def test_pv_alpha_sc_100x_error_rejected(self):
        """alpha_sc=0.045 (100x the physical 0.00045 /K) must fail at load."""
        with pytest.raises(ValueError, match="pv.alpha_sc"):
            DesignProject.from_dict({"pv": {"alpha_sc": 0.045}})

    def test_pv_beta_voc_absolute_value_rejected(self):
        """beta_voc=-0.25 is an absolute V/K value — the model expects a
        RELATIVE /K coefficient (~-0.0025), so -0.25 must fail at load."""
        with pytest.raises(ValueError, match="pv.beta_voc"):
            DesignProject.from_dict({"pv": {"beta_voc": -0.25}})

    def test_pv_valid_coefficients_pass(self):
        """Datasheet-consistent relative coefficients load cleanly."""
        p = DesignProject.from_dict(
            {"pv": {"alpha_sc": 0.00045, "beta_voc": -0.0025}})
        assert p.pv.alpha_sc == pytest.approx(0.00045)
        assert p.pv.beta_voc == pytest.approx(-0.0025)

    # ── HVAC COP / coil guards ───────────────────────────────────────

    def test_hvac_negative_cop_value_rejected(self):
        """A negative COP would flip the cooling cycle into a heater."""
        with pytest.raises(ValueError, match="hvac.cop_value"):
            DesignProject.from_dict({"hvac": {"cop_mode": "constant",
                                              "cop_value": -3.0}})

    def test_hvac_negative_cop_heat_rejected(self):
        with pytest.raises(ValueError, match="hvac.cop_heat"):
            DesignProject.from_dict({"hvac": {"cop_heat": -1.0}})

    def test_hvac_negative_cop_table_rejected(self):
        """Negative table entries propagate through the linear interpolation."""
        with pytest.raises(ValueError, match="hvac.cop_table"):
            DesignProject.from_dict(
                {"hvac": {"cop_mode": "table",
                          "cop_table": {10: 3.0, 30: -0.5}}})

    def test_hvac_unknown_cop_mode_rejected(self):
        """An unknown cop_mode silently fell back to `return self.value`."""
        with pytest.raises(ValueError, match="hvac.cop_mode"):
            DesignProject.from_dict({"hvac": {"cop_mode": "quantum"}})

    def test_hvac_shr_bf_one_rejected(self):
        """BF=1.0 divides by zero in the BF-ADP coil model (shr.py T_adp)."""
        with pytest.raises(ValueError, match="hvac.shr_BF"):
            DesignProject.from_dict({"hvac": {"shr_BF": 1.0}})

    def test_hvac_negative_eta_II_rejected(self):
        with pytest.raises(ValueError, match="hvac.eta_II"):
            DesignProject.from_dict({"hvac": {"eta_II": -0.1}})

    def test_hvac_valid_cop_guards_pass(self):
        """Healthy COP configuration loads cleanly."""
        p = DesignProject.from_dict(
            {"hvac": {"cop_mode": "table", "cop_value": 4.0,
                      "cop_table": {10: 3.0, 30: 2.0}, "shr_BF": 0.15}})
        assert p.hvac.cop_mode == "table"
        assert p.hvac.shr_BF == pytest.approx(0.15)

    # ── Transpiration config ────────────────────────────────────────

    def test_transpiration_daily_params_round_trip(self):
        d = {
            "transpiration": {
                "method": "daily",
                "daily_water_L": 60.0,
            }
        }
        p = DesignProject.from_dict(d)
        assert p.transpiration.method == "daily"
        assert p.transpiration.daily_water_L == pytest.approx(60.0)

    def test_transpiration_per_plant_params_round_trip(self):
        d = {
            "transpiration": {
                "method": "per_plant",
                "plant_count": 1000,
                "ml_per_plant_day": 50.0,
            }
        }
        p = DesignProject.from_dict(d)
        assert p.transpiration.method == "per_plant"
        assert p.transpiration.plant_count == 1000
        assert p.transpiration.ml_per_plant_day == pytest.approx(50.0)

    def test_transpiration_unknown_method_rejected(self):
        """Unknown method string must fail fast at config level (P5-5)."""
        d = {"transpiration": {"method": "some_unknown"}}
        with pytest.raises(ValueError, match="transpiration.method"):
            DesignProject.from_dict(d)


# ---------------------------------------------------------------------------
# 4.1b  S8 fail-fast numeric / timestep guards (P8-5 / P8-12)
# ---------------------------------------------------------------------------
class TestFromDictGuards:
    def test_timestep_700_rejected_at_load(self):
        """Non-divisor of 3600 must be rejected at load time (P8-12)."""
        with pytest.raises(ValueError, match="timestep_s"):
            DesignProject.from_dict({"space": {"timestep_s": 700.0}})

    def test_timestep_zero_rejected(self):
        with pytest.raises(ValueError, match="timestep_s"):
            DesignProject.from_dict({"space": {"timestep_s": 0.0}})

    def test_timestep_600_ok(self):
        p = DesignProject.from_dict({"space": {"timestep_s": 600.0}})
        assert p.space.timestep_s == 600.0

    def test_ppfd_target_string_rejected(self):
        with pytest.raises(ValueError, match="ppfd_target"):
            DesignProject.from_dict({"led": {"ppfd_target": "six"}})

    def test_parameter_ranges_string_triple_rejected(self):
        with pytest.raises(ValueError, match="parameter_ranges"):
            DesignProject.from_dict(
                {"space": {"parameter_ranges": {"ppfd_target": ["a", "b", "c"]}}})

    def test_site_lat_string_rejected(self):
        with pytest.raises(ValueError, match="site.lat"):
            DesignProject.from_dict({"site": {"lat": "31.0"}})

    def test_setpoints_T_light_string_rejected(self):
        with pytest.raises(ValueError, match="setpoints.T_light"):
            DesignProject.from_dict({"setpoints": {"T_light": "22"}})

    def test_tariff_hourly_price_string_rejected(self):
        hp = [0.1] * 24
        hp[23] = "six"
        with pytest.raises(ValueError, match="hourly_prices"):
            DesignProject.from_dict({"tariff": {"hourly_prices": hp}})


# ---------------------------------------------------------------------------
# 4.2  parameter_ranges validation
# ---------------------------------------------------------------------------
class TestParameterRanges:
    def test_unknown_parameter_raises(self):
        """Sweeping a non-existent parameter should raise."""
        from vfed.design.sweep import _validate_ranges

        with pytest.raises(ValueError, match="Unknown parameter"):
            _validate_ranges({"super_duper_ppfd": [100, 300, 50]})

    def test_out_of_bounds_raises(self):
        """A range exceeding HARD_LIMITS should raise."""
        from vfed.design.sweep import _validate_ranges

        with pytest.raises(ValueError, match="exceeds hard limits"):
            _validate_ranges({"ppfd_target": [0, 600, 50]})

    def test_inverted_range_raises(self):
        """min > max should raise."""
        from vfed.design.sweep import _validate_ranges

        with pytest.raises(ValueError, match="Invalid range"):
            _validate_ranges({"ppfd_target": [400, 200, 50]})

    def test_valid_range_passes(self):
        """Valid range should not raise."""
        from vfed.design.sweep import _validate_ranges

        # Should not raise
        _validate_ranges({"ppfd_target": [200, 400, 50]})


# ---------------------------------------------------------------------------
# 4.3  Objective validation
# ---------------------------------------------------------------------------
def test_unknown_objective_raises(project_609):
    """Sweeping with invalid objective should raise."""
    import copy

    from vfed.design.sweep import sweep_design

    # Work on a copy: ``project_609`` is session-scoped and other tests
    # (test_06 edge cases) depend on the pristine 609 state.  Mutating it
    # in place leaked objective="maximize_happiness" into later sweeps.
    p = copy.deepcopy(project_609)
    p.space.parameter_ranges = {"ppfd_target": [400, 500, 100]}
    p.space.objective = "maximize_happiness"
    with pytest.raises(ValueError, match="Unknown objective"):
        sweep_design(p)


# ---------------------------------------------------------------------------
# 4.4  Capital pricing-basis modes (P0-1: rate_per_watt unit trap)
# ---------------------------------------------------------------------------
class TestCapitalUnitModes:
    """P0-1: the capital mode names the pricing basis -- per_watt x rated W
    (LED/HVAC/DEH), per_kwp x rated kWp (PV), per_kwh x rated kWh (battery).
    The legacy pv/battery 'per_watt' spelling silently multiplied kWp/kWh
    (1000x / unit class off the field name: 46.5 kWp at "3.5/W" priced as
    162 instead of 162,000) and must fail fast with migration hints."""

    def test_pv_per_watt_rejected_with_migration_hint(self):
        with pytest.raises(ValueError, match="not valid for PV"):
            DesignProject.from_dict(
                {"pv": {"capital": {"mode": "per_watt", "rate_per_watt": 3.5}}}
            )

    def test_pv_per_watt_error_teaches_the_conversion(self):
        with pytest.raises(ValueError, match="rate_per_kwp: 3500"):
            DesignProject.from_dict(
                {"pv": {"capital": {"mode": "per_watt", "rate_per_watt": 3.5}}}
            )

    def test_battery_per_watt_rejected_with_migration_hint(self):
        with pytest.raises(ValueError, match="not valid for battery"):
            DesignProject.from_dict(
                {"battery": {"capital": {"mode": "per_watt", "rate_per_watt": 500}}}
            )

    def test_battery_migration_keeps_same_number(self):
        """Battery was priced per kWh all along, so the migration keeps the
        number: rate_per_watt 500 -> rate_per_kwh 500."""
        with pytest.raises(ValueError, match="rate_per_kwh: 500"):
            DesignProject.from_dict(
                {"battery": {"capital": {"mode": "per_watt", "rate_per_watt": 500}}}
            )

    def test_pv_per_kwp_without_rate_rejected(self):
        with pytest.raises(ValueError, match="requires rate_per_kwp"):
            DesignProject.from_dict({"pv": {"capital": {"mode": "per_kwp"}}})

    def test_battery_per_kwh_without_rate_rejected(self):
        with pytest.raises(ValueError, match="requires rate_per_kwh"):
            DesignProject.from_dict({"battery": {"capital": {"mode": "per_kwh"}}})

    def test_led_per_kwp_rejected(self):
        with pytest.raises(ValueError, match="not valid for 'led'"):
            DesignProject.from_dict(
                {"led": {"capital": {"mode": "per_kwp", "rate_per_kwp": 3500}}}
            )

    def test_equipment_capital_per_kwh_rejected(self):
        with pytest.raises(ValueError, match="not valid for 'equipment'"):
            DesignProject.from_dict(
                {"equipment_capital": {"mode": "per_kwh", "rate_per_kwh": 500}}
            )

    def test_runtime_guard_catches_programmatic_per_watt_pv(self):
        """Defense in depth: a programmatically built project (bypassing
        from_dict) with the stale pv per_watt spelling fails at pricing
        time, never silently."""
        from vfed.design.project import CapitalCostConfig
        from vfed.design.sweep import _resolve_capital

        with pytest.raises(ValueError, match="not valid for PV"):
            _resolve_capital(
                CapitalCostConfig(mode="per_watt", rate_per_watt=3.5), 46.5, component="pv"
            )


# ---------------------------------------------------------------------------
# 4.4b  Capital cost None sentinel (F2, round 21)
# ---------------------------------------------------------------------------
class TestCapitalCostSentinel:
    """F2 (round 21): ``cost=None`` is the "unspecified" sentinel — legacy
    fallback pricing applies only when the capital block (or its ``cost``
    key) is absent. Before round 21 the default was ``cost=0.0`` with a
    ``cost <= 0 -> fallback`` condition, so an explicit ``cost: 0.0`` was
    indistinguishable from "no block" and silently re-priced PV/battery at
    the legacy hidden unit prices (user13: 11,627.91 inserted into a
    zero-cost PV config, ~3% LCOE distortion)."""

    def test_block_missing_is_none_and_falls_back(self):
        from vfed.design.sweep import _total_capital

        p = DesignProject()  # all defaults
        assert p.pv.capital.cost is None
        assert p.battery.capital.cost is None
        cap = _total_capital(p, 43.0, 40.0)  # 43 m2 / 4.3 = 10 kWp
        assert cap["PV"] == pytest.approx(500.0 * 10.0)
        assert cap["Battery"] == pytest.approx(220.0 * 40.0)

    def test_cost_key_missing_inside_block_falls_back(self):
        from vfed.design.sweep import _total_capital

        p = DesignProject.from_dict({"pv": {"capital": {"mode": "direct"}}})
        assert p.pv.capital.cost is None
        assert _total_capital(p, 43.0, 0.0)["PV"] == pytest.approx(5000.0)

    def test_explicit_zero_cost_is_literal_zero(self):
        from vfed.design.sweep import _total_capital

        p = DesignProject.from_dict(
            {
                "pv": {"capital": {"mode": "direct", "cost": 0.0}},
                "battery": {"capital": {"mode": "direct", "cost": 0.0}},
            }
        )
        cap = _total_capital(p, 100.0, 40.0)
        # user13 pv100 repro: was 500 x 100/4.3 = 11,627.91 via fallback
        assert cap["PV"] == 0.0
        assert cap["Battery"] == 0.0

    def test_explicit_positive_direct_cost_used_as_is(self):
        from vfed.design.sweep import _total_capital

        p = DesignProject.from_dict({"pv": {"capital": {"mode": "direct", "cost": 1234.0}}})
        # direct mode: absolute cost, independent of the rated value
        assert _total_capital(p, 100.0, 0.0)["PV"] == 1234.0

    def test_negative_cost_rejected_at_load(self):
        with pytest.raises(ValueError, match="cost must be >= 0"):
            DesignProject.from_dict({"pv": {"capital": {"mode": "direct", "cost": -5.0}}})

    def test_to_dict_omits_none_cost_and_roundtrips(self):
        p = DesignProject.from_dict(
            {"pv": {"capital": {"mode": "per_kwp", "rate_per_kwp": 3500}}}
        )
        d = p.to_dict()
        assert "cost" not in d["pv"]["capital"]  # None omitted, not `cost: null`
        assert "cost" not in d["battery"]["capital"]
        assert "cost" not in d["equipment_capital"]
        p2 = DesignProject.from_dict(d)
        assert p2.pv.capital.cost is None
        assert p2.pv.capital.rate_per_kwp == 3500.0

    def test_to_dict_keeps_explicit_zero_cost(self):
        p = DesignProject.from_dict({"pv": {"capital": {"mode": "direct", "cost": 0.0}}})
        d = p.to_dict()
        assert d["pv"]["capital"]["cost"] == 0.0
        assert DesignProject.from_dict(d).pv.capital.cost == 0.0


# ---------------------------------------------------------------------------
# 4.5  Capital pricing arithmetic (P0-1)
# ---------------------------------------------------------------------------
class TestCapitalUnitArithmetic:
    def test_pv_per_kwp_prices_kwp(self):
        from vfed.design.sweep import _total_capital

        p = DesignProject.from_dict({"pv": {"capital": {"mode": "per_kwp", "rate_per_kwp": 3500}}})
        cap = _total_capital(p, 200.0, 0.0)  # 200 m2 / 4.3 m2-per-kWp = 46.5 kWp
        assert cap["PV"] == pytest.approx(3500.0 * 200.0 / 4.3)

    def test_battery_per_kwh_prices_kwh(self):
        from vfed.design.sweep import _total_capital

        p = DesignProject.from_dict(
            {"battery": {"capital": {"mode": "per_kwh", "rate_per_kwh": 500}}}
        )
        cap = _total_capital(p, 0.0, 40.0)
        assert cap["Battery"] == pytest.approx(500.0 * 40.0)

    def test_led_per_watt_unchanged(self):
        """per_watt keeps its original x-rated-W semantics for LED."""
        from vfed.design.sweep import _derived_led_power, _total_capital

        p = DesignProject.from_dict(
            {
                "led": {
                    "auto_deduce": True,
                    "ppfd_target": 400.0,
                    "covered_area": 45.0,
                    "efficacy": 2.5,
                    "capital": {"mode": "per_watt", "rate_per_watt": 2.0},
                }
            }
        )
        led_w = _derived_led_power(p)  # 400 * 45 / 2.5 = 7200 W
        cap = _total_capital(p, 0.0, 0.0)
        assert cap["LED"] == pytest.approx(2.0 * led_w)
        assert cap["LED"] == pytest.approx(14400.0)

    def test_legacy_pv_fallback_uses_market_c_pv(self):
        """No pv.capital block -> C_pv x kWp with the market-anchored default
        (500 currency/kWp; the pre-P0-1 default of 110 was 4-8x below
        market)."""
        from vfed.design.sweep import _total_capital

        p = DesignProject()  # all defaults
        assert p.pv.C_pv == pytest.approx(500.0)
        cap = _total_capital(p, 43.0, 0.0)  # 43 m2 / 4.3 = 10 kWp
        assert cap["PV"] == pytest.approx(500.0 * 10.0)

    def test_example_lcoe_full_capital_blocks_use_explicit_units(self):
        """The official example must price PV per kWp (3500 RMB/kWp = 3.5
        RMB/W, China C&I 2025) and battery per kWh (500 RMB/kWh)."""
        import yaml

        root = Path(__file__).resolve().parents[1]
        with open(root / "example_lcoe_full.yaml", encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh)
        assert cfg["pv"]["capital"]["mode"] == "per_kwp"
        assert cfg["pv"]["capital"]["rate_per_kwp"] == pytest.approx(3500.0)
        assert cfg["battery"]["capital"]["mode"] == "per_kwh"
        assert cfg["battery"]["capital"]["rate_per_kwh"] == pytest.approx(500.0)
