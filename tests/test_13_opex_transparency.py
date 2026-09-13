"""
Layer 13: OPEX transparency + currency-magnitude guardrails (P1-7).

* summary gains ``opex_labor_per_year`` / ``opex_misc_per_year`` /
  ``annual_om_pct_of_cost`` in BOTH economics branches (PV enabled and
  grid-only).
* default-opex dominance WARNING: fires when the YAML omitted the opex
  section (``opex_was_defaulted``) AND OPEX > 50% of the annual cost
  total; suppressed when the opex section is explicit (same values ->
  identical numbers).  Fires at most once per process (sweep safety).
* ``opex_was_defaulted`` internal flag: load-time detection, to_dict /
  from_dict roundtrip fidelity, user-key rejection, template opex section.
"""

import sys
import warnings
from pathlib import Path

import pytest
import yaml

SRC = Path(__file__).resolve().parents[1] / "vfed"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from vfed.cli import main
from vfed.design import engine as engine_mod
from vfed.design.engine import DesignEngine, _warn_opex_dominance
from vfed.design.presets import preset_609
from vfed.design.project import DesignProject
from vfed.design.sweep import _annualized_capital, _total_capital


def _defaulted_opex_project():
    """preset 609 with the opex section stripped -> flag True (defaults)."""
    d = preset_609().to_dict()
    d.pop("opex", None)
    return DesignProject.from_dict(d)


def _explicit_opex_project():
    """preset 609 as-is: explicit opex section with the same default values."""
    return DesignProject.from_dict(preset_609().to_dict())


# ---------------------------------------------------------------------------
# 13.1  flag semantics (no simulation needed)
# ---------------------------------------------------------------------------
def test_direct_construction_flag_false():
    """Direct dataclass construction (presets) is not a yaml default case."""
    assert preset_609().opex_was_defaulted is False


def test_missing_opex_section_sets_flag():
    p = _defaulted_opex_project()
    assert p.opex_was_defaulted is True
    assert p.opex.labor_cost_per_year == 30000.0
    assert p.opex.misc_opex_per_year == 5000.0


def test_explicit_opex_section_clears_flag():
    d = preset_609().to_dict()
    d["opex"] = {"labor_cost_per_year": 12345.0}
    p = DesignProject.from_dict(d)
    assert p.opex_was_defaulted is False
    assert p.opex.labor_cost_per_year == 12345.0


def test_flag_roundtrip_defaulted():
    """to_dict -> from_dict preserves flag=True (opex section stays absent)."""
    p1 = _defaulted_opex_project()
    d1 = p1.to_dict()
    assert "opex_was_defaulted" not in d1  # internal key never serialized
    assert "opex" not in d1  # so from_dict re-derives the flag
    p2 = DesignProject.from_dict(d1)
    assert p2.opex_was_defaulted is True
    assert p2.opex.labor_cost_per_year == 30000.0
    assert p2.opex.misc_opex_per_year == 5000.0


def test_flag_roundtrip_explicit():
    """to_dict -> from_dict preserves flag=False and the user's values."""
    d = preset_609().to_dict()
    d["opex"] = {"labor_cost_per_year": 12345.0, "misc_opex_per_year": 678.0}
    p1 = DesignProject.from_dict(d)
    d1 = p1.to_dict()
    assert "opex_was_defaulted" not in d1
    assert "opex" in d1
    p2 = DesignProject.from_dict(d1)
    assert p2.opex_was_defaulted is False
    assert p2.opex.labor_cost_per_year == 12345.0
    assert p2.opex.misc_opex_per_year == 678.0


def test_user_cannot_write_internal_flag():
    """E001-style fail-fast: the flag is internal, not a user config key."""
    with pytest.raises(ValueError, match="internal VFED field"):
        DesignProject.from_dict({"opex_was_defaulted": True})
    with pytest.raises(ValueError, match="internal VFED field"):
        DesignProject.from_dict({"opex_was_defaulted": False})


# ---------------------------------------------------------------------------
# 13.2  warning helper: thresholds, suppression, once-per-process
# ---------------------------------------------------------------------------
def test_warn_helper_threshold_and_suppression(monkeypatch):
    monkeypatch.setattr(engine_mod, "_OPEX_DEFAULT_WARNED", False)
    defaulted = _defaulted_opex_project()
    explicit = _explicit_opex_project()

    # pct <= 0.5: silent even when defaulted
    with warnings.catch_warnings(record=True) as rec:
        warnings.simplefilter("always")
        _warn_opex_dominance(defaulted, 1000.0, 0.5)
    assert len(rec) == 0

    # pct > 0.5 + defaulted: fires, pure ASCII, required guidance text
    with pytest.warns(UserWarning, match="default OPEX in effect") as rec:
        _warn_opex_dominance(defaulted, 35020.75, 0.8488)
    msg = str(rec[0].message)
    assert msg.isascii()
    assert "35020.75" in msg
    assert "USD" in msg
    assert "84.9%" in msg
    assert "add an explicit opex section to your YAML" in msg

    # explicit opex section (same values): silent even at 90%
    with warnings.catch_warnings(record=True) as rec:
        warnings.simplefilter("always")
        _warn_opex_dominance(explicit, 35020.75, 0.9)
    assert len(rec) == 0


def test_warn_helper_fires_at_most_once_per_process(monkeypatch):
    monkeypatch.setattr(engine_mod, "_OPEX_DEFAULT_WARNED", False)
    defaulted = _defaulted_opex_project()
    with pytest.warns(UserWarning, match="default OPEX in effect"):
        _warn_opex_dominance(defaulted, 1000.0, 0.9)
    # second identical condition: the once-per-process guard keeps it silent
    with warnings.catch_warnings(record=True) as rec:
        warnings.simplefilter("always")
        _warn_opex_dominance(defaulted, 1000.0, 0.9)
    assert len(rec) == 0


# ---------------------------------------------------------------------------
# 13.3  engine summary scalars + warning (grid-only branch, preset 609)
# ---------------------------------------------------------------------------
def test_grid_only_scalars_warning_and_suppression(monkeypatch):
    defaulted = _defaulted_opex_project()
    explicit = _explicit_opex_project()

    monkeypatch.setattr(engine_mod, "_OPEX_DEFAULT_WARNED", False)
    with pytest.warns(UserWarning, match="default OPEX in effect") as rec:
        r_def = DesignEngine(cache_dir="weather_cache").run(defaulted)
    assert str(rec[0].message).isascii()

    with warnings.catch_warnings(record=True) as rec:
        warnings.simplefilter("always")
        r_exp = DesignEngine(cache_dir="weather_cache").run(explicit)
    assert not any("default OPEX in effect" in str(w.message) for w in rec)

    s_def, s_exp = r_def.summary, r_exp.summary
    for s in (s_def, s_exp):
        assert s["opex_labor_per_year"] == 30000.0
        assert s["opex_misc_per_year"] == 5000.0
        assert 0.0 < s["annual_om_pct_of_cost"] <= 1.0
    # transparency only: identical numbers regardless of the flag
    for k in ("annual_om", "lcoe", "annual_om_pct_of_cost"):
        assert s_exp[k] == s_def[k]

    # exact share: annual_om / (annual_cap + annual_om + net_grid_cost)
    cap = _total_capital(defaulted, 0.0, 0.0)
    annual_cap = _annualized_capital(defaulted, cap)
    om = s_def["annual_om"]
    grid = s_def["annual_grid_cost_net"]
    expected = round(om / (annual_cap + om + grid), 4)
    assert s_def["annual_om_pct_of_cost"] == expected
    assert s_def["annual_om_pct_of_cost"] > 0.5  # the warned regime


# ---------------------------------------------------------------------------
# 13.4  engine summary scalars (PV-enabled branch)
# ---------------------------------------------------------------------------
def test_pv_branch_scalars_and_warning(monkeypatch):
    d = preset_609().to_dict()
    d["pv_area_m2"] = 60.0
    d.pop("opex", None)
    p = DesignProject.from_dict(d)
    assert p.opex_was_defaulted is True

    monkeypatch.setattr(engine_mod, "_OPEX_DEFAULT_WARNED", False)
    with pytest.warns(UserWarning, match="default OPEX in effect"):
        res = DesignEngine(cache_dir="weather_cache").run(p)

    s = res.summary
    assert s["opex_labor_per_year"] == 30000.0
    assert s["opex_misc_per_year"] == 5000.0
    assert 0.0 < s["annual_om_pct_of_cost"] <= 1.0


# ---------------------------------------------------------------------------
# 13.5  design new template: opex section spelled out
# ---------------------------------------------------------------------------
def test_design_new_template_has_explicit_opex(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["design", "new", "t", "--preset", "609"]) == 0
    text = (tmp_path / "t.yaml").read_text(encoding="utf-8")
    assert "defaults apply silently if this section is omitted" in text
    raw = yaml.safe_load(text)
    assert "opex_was_defaulted" not in raw  # internal key never in templates
    assert raw["opex"]["labor_cost_per_year"] == 30000.0
    assert raw["opex"]["misc_opex_per_year"] == 5000.0
    p = DesignProject.load(tmp_path / "t.yaml")
    assert p.opex_was_defaulted is False  # explicit section -> flag off
