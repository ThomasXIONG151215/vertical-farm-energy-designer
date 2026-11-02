"""G1 (Wave 2) multi-array PV: contract, engine equivalence, physics.

Layer 0/1 for pv_arrays:

* contract -- default is an empty tuple (legacy single-array sizing), to_dict
  omits it, from_dict validates tilt/azimuth/area/module per array and
  rejects pv_arrays + pv_area_m2 > 0 as mutually exclusive;
* sweep guard -- pv_arrays projects are evaluate-only until G7;
* engine equivalence -- a single array at the site orientation reproduces
  the legacy scalar summary bit-for-bit (the multi-array branch reuses the
  main POA DataFrame, so the injected series is the legacy series);
* superposition -- calculate_pv_output is linear in area (n_modules is a
  float ratio), so 60 + 40 m2 arrays equal one 100 m2 array bit-for-bit;
* multi-orientation -- a vertical east facade (tilt 90 / azimuth 90) runs
  through its own POA fetch and yields a different generation total;
* per-array module -- an array may pick another library preset (the _UNSET
  sentinel resolution fills its electrical fields).

The vertical-facade and mixed-module cases fetch a new orientation on
first run (weather_cache afterwards) -- same network dependency style as
test_06.
"""

import pytest

from vfed.design.engine import DesignEngine
from vfed.design.presets import preset_609
from vfed.design.project import DesignProject
from vfed.design.sweep import sweep_design


def _pv_project(**overrides):
    """preset_609 dict with pv_arrays set and the legacy scalar cleared."""
    d = preset_609().to_dict()
    d.pop("pv_area_m2", None)
    d["pv_arrays"] = overrides.pop("pv_arrays")
    d.update(overrides)
    return DesignProject.from_dict(d)


# ---------------------------------------------------------------------------
# Layer 0: contract
# ---------------------------------------------------------------------------


class TestPVArraysContract:
    def test_default_is_empty_tuple_and_to_dict_omits(self):
        p = preset_609()
        assert p.pv_arrays == ()
        assert "pv_arrays" not in p.to_dict()

    def test_from_dict_parses_arrays_with_defaults(self):
        d = preset_609().to_dict()
        d.pop("pv_area_m2", None)
        d["pv_arrays"] = [{"tilt": 25.0, "azimuth": 190.0, "area_m2": 40.0}]
        p = DesignProject.from_dict(d)
        assert len(p.pv_arrays) == 1
        a = p.pv_arrays[0]
        assert (a.tilt, a.azimuth, a.area_m2) == (25.0, 190.0, 40.0)
        assert a.name is None and a.module is None  # inherit project module

    def test_mutual_exclusion_with_legacy_scalar(self):
        d = preset_609().to_dict()
        d["pv_area_m2"] = 100.0
        d["pv_arrays"] = [{"tilt": 20.0, "azimuth": 180.0, "area_m2": 100.0}]
        with pytest.raises(ValueError, match="mutually exclusive"):
            DesignProject.from_dict(d)

    @pytest.mark.parametrize(
        "bad,match",
        [
            ({"tilt": 91.0, "azimuth": 180.0, "area_m2": 10.0}, "tilt"),
            ({"tilt": 20.0, "azimuth": 361.0, "area_m2": 10.0}, "azimuth"),
            ({"tilt": 20.0, "azimuth": 180.0, "area_m2": 0.0}, "area_m2"),
            ({"tilt": 20.0, "azimuth": 180.0, "area_m2": 1001.0}, "area_m2"),
            ({"tilt": 20.0, "azimuth": 180.0, "area_m2": 10.0, "bogus": 1}, "Unrecognised"),
            (
                {"tilt": 20.0, "azimuth": 180.0, "area_m2": 10.0, "module": "nope"},
                "unknown PV module",
            ),
        ],
    )
    def test_out_of_band_values_fail_fast(self, bad, match):
        d = preset_609().to_dict()
        d.pop("pv_area_m2", None)
        d["pv_arrays"] = [bad]
        with pytest.raises(ValueError, match=match):
            DesignProject.from_dict(d)

    def test_non_list_rejected(self):
        d = preset_609().to_dict()
        d.pop("pv_area_m2", None)
        d["pv_arrays"] = "roof"
        with pytest.raises(ValueError, match="list"):
            DesignProject.from_dict(d)

    def test_sweep_rejects_pv_arrays(self, tmp_path):
        p = _pv_project(pv_arrays=[{"tilt": 20.0, "azimuth": 180.0, "area_m2": 10.0}])
        with pytest.raises(NotImplementedError, match="evaluate-only"):
            sweep_design(p, cache_dir=str(tmp_path))


# ---------------------------------------------------------------------------
# Layer 1: engine equivalence / superposition (cached weather, no new fetch)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def engine():
    return DesignEngine(cache_dir="weather_cache")


@pytest.fixture(scope="module")
def legacy_100_50(engine):
    d = preset_609().to_dict()
    d["pv_area_m2"] = 100.0
    d["battery_kwh"] = 50.0
    return engine.run(DesignProject.from_dict(d))


def test_single_array_at_site_orientation_is_bit_equal(engine, legacy_100_50):
    r = engine.run(
        _pv_project(
            pv_arrays=[{"name": "roof", "tilt": 20.0, "azimuth": 180.0, "area_m2": 100.0}],
            battery_kwh=50.0,
        )
    )
    for k, v in legacy_100_50.summary.items():
        assert r.summary.get(k) == v, f"summary[{k}] diverged: {v} -> {r.summary.get(k)}"
    # the only additive key is the per-array breakdown
    br = r.summary["pv_arrays"]
    assert len(br) == 1
    assert br[0]["module"] == "jinko_jkm580n"
    assert br[0]["annual_kwh"] == r.summary["pv_generation_kwh"]


def test_superposition_same_orientation_bit_equal(engine, legacy_100_50):
    r = engine.run(
        _pv_project(
            pv_arrays=[
                {"name": "a", "tilt": 20.0, "azimuth": 180.0, "area_m2": 60.0},
                {"name": "b", "tilt": 20.0, "azimuth": 180.0, "area_m2": 40.0},
            ],
            battery_kwh=50.0,
        )
    )
    for k, v in legacy_100_50.summary.items():
        assert r.summary.get(k) == v, f"summary[{k}] diverged: {v} -> {r.summary.get(k)}"
    parts = sorted(a["annual_kwh"] for a in r.summary["pv_arrays"])
    assert parts[0] + parts[1] == pytest.approx(r.summary["pv_generation_kwh"], abs=0.01)


# ---------------------------------------------------------------------------
# Layer 1: new orientation + per-array module (first run fetches online)
# ---------------------------------------------------------------------------


def test_vertical_east_facade_runs_and_differs(engine, legacy_100_50):
    r = engine.run(
        _pv_project(
            pv_arrays=[{"name": "east", "tilt": 90.0, "azimuth": 90.0, "area_m2": 100.0}],
            battery_kwh=50.0,
        )
    )
    gen = r.summary["pv_generation_kwh"]
    assert gen > 0.0
    assert gen != legacy_100_50.summary["pv_generation_kwh"]
    assert 0.0 < r.summary["battery_cycles"]  # dispatch ran with the battery
    for k in ("lcoe", "capital_total", "annual_grid_cost_net"):
        val = r.summary[k]
        assert val == val and abs(val) != float("inf")  # finite


def test_per_array_module_uses_library_preset(engine):
    r = engine.run(
        _pv_project(
            pv_arrays=[
                {
                    "name": "hjt_wall",
                    "tilt": 20.0,
                    "azimuth": 180.0,
                    "area_m2": 100.0,
                    "module": "huasun_himalaya",
                }
            ],
            battery_kwh=50.0,
        )
    )
    assert r.summary["pv_generation_kwh"] > 0.0
    assert r.summary["pv_arrays"][0]["module"] == "huasun_himalaya"
