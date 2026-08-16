"""
Layer 4: Configuration validation — from_dict, parameter_ranges, objective.

Ensures YAML config parsing catches errors and validates ranges.
"""
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from src.design.project import DesignProject


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
        with pytest.raises(ValueError, match="Unrecognised keys in 'capital'"):
            DesignProject.from_dict({
                "led": {
                    "ppfd_target": 400,
                    "capital": {"mode": "direct", "not_a_key": 1.0}
                }
            })

    def test_round_trip_preserves_values(self):
        """to_dict -> from_dict must be lossless."""
        from src.design.presets import preset_609

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
                "photoperiod_hours": 14.0,
            }
        }
        p = DesignProject.from_dict(d)
        assert p.transpiration.method == "daily"
        assert p.transpiration.daily_water_L == pytest.approx(60.0)
        assert p.transpiration.photoperiod_hours == pytest.approx(14.0)

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

    def test_transpiration_unknown_method_accepted(self):
        """Unknown method string is accepted at config level (engine handles it)."""
        d = {"transpiration": {"method": "some_unknown"}}
        p = DesignProject.from_dict(d)
        assert p.transpiration.method == "some_unknown"


# ---------------------------------------------------------------------------
# 4.2  parameter_ranges validation
# ---------------------------------------------------------------------------
class TestParameterRanges:
    def test_unknown_parameter_raises(self):
        """Sweeping a non-existent parameter should raise."""
        from src.design.sweep import _validate_ranges

        with pytest.raises(ValueError, match="Unknown parameter"):
            _validate_ranges({"super_duper_ppfd": [100, 300, 50]})

    def test_out_of_bounds_raises(self):
        """A range exceeding HARD_LIMITS should raise."""
        from src.design.sweep import _validate_ranges

        with pytest.raises(ValueError, match="exceeds hard limits"):
            _validate_ranges({"ppfd_target": [0, 600, 50]})

    def test_inverted_range_raises(self):
        """min > max should raise."""
        from src.design.sweep import _validate_ranges

        with pytest.raises(ValueError, match="Invalid range"):
            _validate_ranges({"ppfd_target": [400, 200, 50]})

    def test_valid_range_passes(self):
        """Valid range should not raise."""
        from src.design.sweep import _validate_ranges

        # Should not raise
        _validate_ranges({"ppfd_target": [200, 400, 50]})


# ---------------------------------------------------------------------------
# 4.3  Objective validation
# ---------------------------------------------------------------------------
def test_unknown_objective_raises(project_609):
    """Sweeping with invalid objective should raise."""
    from src.design.sweep import sweep_design

    p = project_609
    p.space.parameter_ranges = {"ppfd_target": [400, 500, 100]}
    p.space.objective = "maximize_happiness"
    with pytest.raises(ValueError, match="Unknown objective"):
        sweep_design(p)
