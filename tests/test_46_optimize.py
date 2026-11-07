"""O5: design+control co-optimization infrastructure.

Contract under test:
  * ``evaluate_candidate`` schema gate (version != 1 raises), unknown
    candidate keys raise WITH the key name, flat overrides are
    bit-equivalent to a manual to_dict -> modify -> from_dict -> run.
  * ``zones`` candidate delta deep-merges onto the base zones and
    re-validates through ``from_dict``; an untouched sibling zone's
    ``zone_timeseries`` is bitwise unchanged (no cross-talk).
  * Declarative ``policy`` / ``policies`` specs instantiate through
    ``build_policy``; the registered ``setpoint_offset`` policy shifts
    the RH mean down at ``rh_offset_pp=-5`` and is bit-identical to
    ``policy=None`` with all-default params (zero-drift sha256 oracle).
  * ``period_s`` is registered in PARAM_PATH_MAP / HARD_LIMITS, out-of-
    band values fail fast, and the override path lands in
    ``control.period_s`` (cadence-effective: 1200 s -> 144 ticks / 48 h).
  * ``optimize`` enumerates the outer grid in declared key order with
    ONE ``DesignEngine.run`` per combo (monkeypatched counter), re-
    dispatches PV x battery through ``EnergySystem.calculate_metrics``
    (2 outer x 2 x 2 inner = 8 rows), sorts ascending, best = min,
    is deterministic across calls, and n_workers=2 == n_workers=1
    bit-exactly.
  * Illegal objectives raise in both entry points.
"""

import hashlib
import json

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from vfed.design.control import ControlAction
from vfed.design.engine import DesignEngine
from vfed.design.optimize import evaluate_candidate, optimize
from vfed.design.presets import preset_609
from vfed.design.project import HARD_LIMITS, PARAM_PATH_MAP, DesignProject

# Same per-OS constants the test_23..29 / 38 / 40 suites pin.
WIN = "1764f7e6ee6e185d41e8b438a2c3c81320f38e9d02468446dc5f249a25870192"
LINUX = "ede65ba07d51c5ed4aa52f353f93590925a80fda93edf70c7436b2db8fa0c336"
ACCEPTED = frozenset({WIN, LINUX})


def synthetic_weather(n=48):
    idx = pd.date_range("2023-01-01 00:00", periods=n, freq="h")
    hour = np.arange(n, dtype=float)
    t_ext = 10.0 + 8.0 * np.sin((hour - 9.0) / 24.0 * 2.0 * np.pi)
    rh_ext = 70.0 + 10.0 * np.sin((hour - 3.0) / 24.0 * 2.0 * np.pi)
    ghi = np.clip(600.0 * np.sin((hour - 6.0) / 12.0 * np.pi), 0.0, None)
    return pd.DataFrame(
        {
            "temperature_2m": t_ext,
            "relative_humidity_2m": rh_ext,
            "wind_speed_10m": np.full(n, 2.0),
            "shortwave_radiation": ghi,
            "direct_radiation": ghi * 0.7,
            "diffuse_radiation": ghi * 0.3,
            "surface_pressure": np.full(n, 1013.25),
        },
        index=idx,
    )


def _ts_sha256(result):
    ts_json = json.dumps(result.timeseries, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(ts_json.encode("utf-8")).hexdigest()


def two_zone_project():
    d = preset_609().to_dict()
    d["zones"] = {
        "nursery": {"led": {"ppfd_target": 200}, "setpoints": {"T_light": 22}},
        "grow": {"setpoints": {"T_light": 25}},
    }
    return DesignProject.from_dict(d)


class _CountingPolicy:
    def __init__(self):
        self.step_count = 0
        self.plan_count = 0

    def reset(self, ctx):
        pass

    def plan_daily(self, obs):
        self.plan_count += 1
        return None

    def step(self, obs):
        self.step_count += 1
        return ControlAction()


@pytest.fixture()
def w48():
    return synthetic_weather(48)


# ---------------------------------------------------------------------------
# evaluate_candidate: contract gates + flat-override equivalence
# ---------------------------------------------------------------------------
class TestEvaluateCandidateContract:
    def test_schema_version_must_be_1(self, w48):
        with pytest.raises(ValueError, match="schema"):
            evaluate_candidate(preset_609(), {"schema": 2}, weather=w48)

    def test_unknown_key_raises_with_key_name(self, w48):
        with pytest.raises(ValueError, match="bogus_key"):
            evaluate_candidate(preset_609(), {"bogus_key": 1}, weather=w48)

    def test_illegal_objective_raises(self, w48):
        with pytest.raises(ValueError, match="objective"):
            evaluate_candidate(
                preset_609(), {}, weather=w48, objective="profit_per_m2"
            )

    def test_return_shape(self, w48):
        out = evaluate_candidate(preset_609(), {"ppfd_target": 250.0}, weather=w48)
        assert isinstance(out["objective"], float)
        for key in (
            "lcoe",
            "cost_per_kg_fresh",
            "kwh_per_kg_fresh",
            "annual_load_kwh",
            "biomass_kg",
            "annual_grid_cost",
        ):
            assert key in out["metrics"]
        assert out["result"].project_name  # a real SimulationResult came back

    def test_flat_override_bit_equivalent(self, w48):
        base = preset_609()
        got = evaluate_candidate(base, {"ppfd_target": 250.0}, weather=w48)

        d = base.to_dict()
        d["led"]["ppfd_target"] = 250.0
        manual_project = DesignProject.from_dict(d)
        manual = evaluate_candidate(manual_project, {}, weather=w48)

        assert got["objective"] == manual["objective"]  # bit-equal float
        assert got["metrics"] == manual["metrics"]
        assert got["result"].timeseries == manual["result"].timeseries

    def test_base_project_not_mutated(self, w48):
        base = preset_609()
        before = base.to_dict()
        evaluate_candidate(base, {"ppfd_target": 250.0}, weather=w48)
        assert base.to_dict() == before


# ---------------------------------------------------------------------------
# zones delta: deep-merge, re-validation, sibling no-cross-talk
# ---------------------------------------------------------------------------
class TestZonesDelta:
    def test_sibling_zone_bitwise_unchanged(self, w48):
        base = two_zone_project()
        baseline = evaluate_candidate(base, {}, weather=w48)
        treated = evaluate_candidate(
            base,
            {"zones": {"nursery": {"setpoints": {"T_light": 24.0}}}},
            weather=w48,
        )
        assert (
            treated["result"].zone_timeseries["grow"]
            == baseline["result"].zone_timeseries["grow"]
        )
        # the overridden zone actually moved
        assert (
            treated["result"].zone_timeseries["nursery"]
            != baseline["result"].zone_timeseries["nursery"]
        )

    def test_zones_delta_revalidated_by_from_dict(self, w48):
        base = two_zone_project()
        with pytest.raises(ValueError) as exc:
            evaluate_candidate(
                base, {"zones": {"nursery": {"led": {"no_such_field": 1}}}}, weather=w48
            )
        assert "nursery" in str(exc.value)


# ---------------------------------------------------------------------------
# declarative policies via build_policy / POLICY_REGISTRY
# ---------------------------------------------------------------------------
class TestPolicySpecs:
    def test_unknown_policy_type_raises_with_name(self, w48):
        with pytest.raises(ValueError, match="no_such_policy"):
            evaluate_candidate(
                preset_609(),
                {"policy": {"type": "no_such_policy", "params": {}}},
                weather=w48,
            )

    def test_zero_param_policy_hits_zero_drift_oracle(self, w48):
        out = evaluate_candidate(
            preset_609(),
            {"policy": {"type": "setpoint_offset", "params": {}}},
            weather=w48,
        )
        assert _ts_sha256(out["result"]) in ACCEPTED

    def test_rh_offset_minus_5_lowers_rh_mean(self, w48):
        base = preset_609()
        baseline = evaluate_candidate(base, {}, weather=w48)
        treated = evaluate_candidate(
            base,
            {"policy": {"type": "setpoint_offset", "params": {"rh_offset_pp": -5.0}}},
            weather=w48,
        )
        base_mean = float(np.mean(baseline["result"].timeseries["RH_z"]))
        treated_mean = float(np.mean(treated["result"].timeseries["RH_z"]))
        assert treated_mean < base_mean

    def test_multi_zone_per_zone_spec(self, w48):
        base = two_zone_project()
        baseline = evaluate_candidate(base, {}, weather=w48)
        treated = evaluate_candidate(
            base,
            {
                "policies": {
                    "nursery": {
                        "type": "setpoint_offset",
                        "params": {"rh_offset_pp": -5.0},
                    },
                    "grow": {"type": "setpoint_offset", "params": {}},
                }
            },
            weather=w48,
        )
        # offset zone moves down
        nb = float(np.mean(baseline["result"].zone_timeseries["nursery"]["RH_z"]))
        nt = float(np.mean(treated["result"].zone_timeseries["nursery"]["RH_z"]))
        assert nt < nb
        # zero-param sibling policy is bit-identical (zero drift per zone)
        assert (
            treated["result"].zone_timeseries["grow"]
            == baseline["result"].zone_timeseries["grow"]
        )

    def test_policies_and_policy_are_mutually_exclusive(self, w48):
        spec = {"type": "setpoint_offset", "params": {}}
        with pytest.raises(ValueError, match="policies"):
            evaluate_candidate(
                preset_609(), {"policy": spec, "policies": {"x": spec}}, weather=w48
            )


# ---------------------------------------------------------------------------
# period_s registry + effectiveness
# ---------------------------------------------------------------------------
class TestPeriodS:
    def test_registry_entries(self):
        assert PARAM_PATH_MAP["period_s"] == ("control", "period_s")
        assert HARD_LIMITS["period_s"] == (60, 3600)

    def test_out_of_band_period_fails_fast(self, w48):
        with pytest.raises(ValueError) as exc:
            evaluate_candidate(preset_609(), {"period_s": 30.0}, weather=w48)
        assert "period_s" in str(exc.value)

    def test_override_lands_in_control_period_s(self, w48):
        base = preset_609()
        out = evaluate_candidate(base, {"period_s": 1200.0}, weather=w48)
        assert out["result"] is not None  # override path runs a full sim

        # equivalence: same override applied manually through from_dict
        d = base.to_dict()
        d["control"] = {"period_s": 1200.0}
        manual = DesignProject.from_dict(d)
        assert manual.control.period_s == 1200.0
        manual_out = evaluate_candidate(manual, {}, weather=w48)
        assert out["objective"] == manual_out["objective"]

    def test_cadence_effective_1200s(self, w48):
        d = preset_609().to_dict()
        d["control"] = {"period_s": 1200.0}
        p = DesignProject.from_dict(d)
        pol = _CountingPolicy()
        DesignEngine(cache_dir=None).run(p, weather=w48, policy=pol)
        # dt=600 s -> 6 substeps/h; 48 h = 288 substeps; 1200 s tick = every
        # 2nd substep -> 144 step ticks, 2 day boundaries.
        assert pol.step_count == 144
        assert pol.plan_count == 2


# ---------------------------------------------------------------------------
# optimize: enumeration, one-run-per-combo, ordering, determinism, workers
# ---------------------------------------------------------------------------
class TestOptimize:
    GRID = {"ppfd_target": [200.0, 250.0]}

    def test_shape_rows_columns_order(self, w48):
        out = optimize(
            preset_609(),
            self.GRID,
            weather=w48,
            pv_grid=[0.0, 5.0],
            battery_grid=[0.0, 1.0],
        )
        df = out["results"]
        assert out["objective"] == "lcoe"
        assert len(df) == 8  # 2 outer x 2 pv x 2 battery
        for col in (
            "ppfd_target",
            "pv_area",
            "battery_kwh",
            "lcoe",
            "annual_load_kwh",
            "biomass_kg",
            "annual_grid_cost",
            "cost_per_kg_fresh",
            "kwh_per_kg_fresh",
        ):
            assert col in df.columns
        obj = df["lcoe"].tolist()
        assert obj == sorted(obj)  # ascending
        assert out["best"] == df.iloc[0].to_dict()  # best = min row
        # full inner-grid coverage per outer combo
        pairs = set(zip(df["pv_area"], df["battery_kwh"]))
        assert pairs == {(0.0, 0.0), (0.0, 1.0), (5.0, 0.0), (5.0, 1.0)}
        assert set(df["ppfd_target"]) == {200.0, 250.0}

    def test_one_engine_run_per_combo(self, w48, monkeypatch):
        calls = {"n": 0}
        original = DesignEngine.run

        def counted(self, *args, **kwargs):
            calls["n"] += 1
            return original(self, *args, **kwargs)

        monkeypatch.setattr(DesignEngine, "run", counted)
        optimize(preset_609(), self.GRID, weather=w48)
        assert calls["n"] == 2  # inner loop must NOT re-run the engine

    def test_deterministic_row_order(self, w48):
        a = optimize(preset_609(), self.GRID, weather=w48)
        b = optimize(preset_609(), self.GRID, weather=w48)
        assert_frame_equal(a["results"], b["results"], check_exact=True)
        assert a["best"] == b["best"]

    def test_n_workers_2_matches_sequential_bitwise(self, w48):
        seq = optimize(preset_609(), self.GRID, weather=w48, n_workers=1)
        par = optimize(preset_609(), self.GRID, weather=w48, n_workers=2)
        assert_frame_equal(seq["results"], par["results"], check_exact=True)
        assert seq["best"] == par["best"]

    def test_illegal_objective_raises(self, w48):
        with pytest.raises(ValueError, match="objective"):
            optimize(preset_609(), self.GRID, weather=w48, objective="nope")

    def test_grid_values_must_be_lists(self, w48):
        with pytest.raises(ValueError, match="ppfd_target"):
            optimize(preset_609(), {"ppfd_target": 250.0}, weather=w48)

    def test_empty_grid_runs_base_once(self, w48):
        out = optimize(preset_609(), {}, weather=w48, pv_grid=[0.0], battery_grid=[0.0])
        assert len(out["results"]) == 1
        assert out["best"]["ppfd_target"] if "ppfd_target" in out["best"] else True

    def test_zones_dim_cartesian_product(self, w48):
        base = two_zone_project()
        zones_a = {"nursery": {"setpoints": {"T_light": 24.0}}}
        zones_b = {"nursery": {"setpoints": {"T_light": 26.0}}}
        out = optimize(
            base,
            {"zones": [zones_a, zones_b]},
            weather=w48,
            pv_grid=[0.0],
            battery_grid=[0.0],
        )
        df = out["results"]
        assert len(df) == 2
        assert df.iloc[0]["zones"] in (zones_a, zones_b)
        assert df.iloc[1]["zones"] in (zones_a, zones_b)
        assert df.iloc[0]["zones"] != df.iloc[1]["zones"]
