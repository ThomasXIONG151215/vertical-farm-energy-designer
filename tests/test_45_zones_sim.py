"""Wave 4 (Z-loop + Z-report): end-to-end multi-zone simulation tests.

Covers:
- single-zone zero drift (no ``zones`` key -> bitwise-identical timeseries,
  same sha256 oracle as tests/test_23_wall_rc.py);
- two-zone simulation, per-zone prefixed timeseries columns and
  ``zone_timeseries`` payload;
- aggregate ``load_kw`` == elementwise sum of zone columns;
- zone override effectiveness without cross-talk (a zone whose view equals
  the global config reproduces the single-zone baseline bitwise);
- per-zone ``policies`` mapping (call counts + zone_id plumbing);
- fail-fast validation (policy key mismatch, ambiguous single ``policy``,
  ``policies`` without zones, ``interzone`` stub);
- auto-size writeback isolation on the shared project (B8);
- facility annual energy == sum of per-zone annuals.

Per-zone monthly tables and inter-zone exchange are deferred to later
waves (see build_report docstring).
"""

import hashlib
import json
import math

import numpy as np
import pandas as pd
import pytest

from vfed.design.control import ControlAction, ZoneAction
from vfed.design.engine import DesignEngine
from vfed.design.presets import preset_609
from vfed.design.project import DesignProject

# Same dual-platform oracle set as tests/test_23_wall_rc.py (bitwise
# zero-drift gate; see there for provenance).
ZERO_DRIFT_SHA256 = "1764f7e6ee6e185d41e8b438a2c3c81320f38e9d02468446dc5f249a25870192"
ZERO_DRIFT_SHA256_LINUX = "ede65ba07d51c5ed4aa52f353f93590925a80fda93edf70c7436b2db8fa0c336"
ACCEPTED = {ZERO_DRIFT_SHA256, ZERO_DRIFT_SHA256_LINUX}


def synthetic_weather(n=48):
    """Deterministic hourly weather frame (copy of test_23 fixture)."""
    idx = pd.date_range("2023-01-01", periods=n, freq="h")
    hour = np.arange(n)
    t_ext = 10 + 8 * np.sin((hour - 9) / 24 * 2 * math.pi)
    rh_ext = 70 + 10 * np.sin((hour - 3) / 24 * 2 * math.pi)
    ghi = np.clip(600 * np.sin((hour - 6) / 12 * math.pi), 0, None)
    return pd.DataFrame(
        {
            "temperature_2m": t_ext,
            "relative_humidity_2m": rh_ext,
            "shortwave_radiation": ghi,
            "wind_speed_10m": 2.0,
            "direct_radiation": 0.7 * ghi,
            "diffuse_radiation": 0.3 * ghi,
            "surface_pressure": 1013.25,
        },
        index=idx,
    )


def two_zone_project():
    """nursery (LED + setpoint overrides) + grow (setpoint-only) project."""
    d = preset_609().to_dict()
    d["zones"] = {
        "nursery": {"led": {"ppfd_target": 200}, "setpoints": {"T_light": 22}},
        "grow": {"setpoints": {"T_light": 25}},
    }
    return DesignProject.from_dict(d)


def _ts_sha256(timeseries):
    payload = json.dumps(timeseries, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


@pytest.fixture(scope="module")
def single_zone_result():
    return DesignEngine(cache_dir=None).run(
        preset_609(), weather=synthetic_weather(48)
    )


@pytest.fixture(scope="module")
def two_zone_result():
    return DesignEngine(cache_dir=None).run(
        two_zone_project(), weather=synthetic_weather(48)
    )


class TestSingleZoneZeroDrift:
    def test_timeseries_sha256_in_accepted_set(self, single_zone_result):
        assert _ts_sha256(single_zone_result.timeseries) in ACCEPTED

    def test_no_zone_payload_leaks(self, single_zone_result):
        assert single_zone_result.zone_ids == []
        assert single_zone_result.zone_timeseries == {}
        assert "zones" not in single_zone_result.summary


class TestTwoZoneRun:
    def test_zone_ids_declared_order(self, two_zone_result):
        assert two_zone_result.zone_ids == ["nursery", "grow"]

    def test_zone_timeseries_has_both_zones(self, two_zone_result):
        assert sorted(two_zone_result.zone_timeseries) == ["grow", "nursery"]
        for zid in ("nursery", "grow"):
            assert len(two_zone_result.zone_timeseries[zid]["T_z"]) == 48

    def test_prefix_columns_present(self, two_zone_result):
        ts = two_zone_result.timeseries
        for zid in ("nursery", "grow"):
            for col in (
                "T_z",
                "RH_z",
                "load_kw",
                "E_hvac_Wh",
                "E_deh_Wh",
                "E_led_Wh",
                "E_misc_Wh",
                "X_d",
            ):
                assert f"{zid}.{col}" in ts
                assert len(ts[f"{zid}.{col}"]) == 48

    def test_aggregate_load_equals_zone_sum(self, two_zone_result):
        ts = two_zone_result.timeseries
        for i in range(48):
            zsum = ts[f"nursery.load_kw"][i] + ts[f"grow.load_kw"][i]
            assert ts["load_kw"][i] == pytest.approx(zsum, abs=1e-9)

    def test_summary_zones_and_annual_total(self, two_zone_result):
        zones = two_zone_result.summary["zones"]
        assert sorted(zones) == ["grow", "nursery"]
        for zid, zm in zones.items():
            for key in (
                "annual_load_kwh",
                "annual_harvest_kg",
                "annual_harvest_fw_kg",
                "annual_water_m3",
                "T_z_mean_c",
                "rh_exceed_hours",
                "deh_utilization",
                "full_load_diagnostics",
                "hvac_P_rated_w",
                "deh_P_ref_w",
            ):
                assert key in zm, f"{zid}.{key} missing"
        zone_total = zones["nursery"]["annual_load_kwh"] + zones["grow"]["annual_load_kwh"]
        assert two_zone_result.summary["annual_energy_kwh"] == pytest.approx(
            zone_total, abs=0.05
        )


class TestZoneOverrideNoCrossTalk:
    def test_zone_mean_temperatures_differ(self, two_zone_result):
        zts = two_zone_result.zone_timeseries
        assert np.mean(zts["nursery"]["T_z"]) != pytest.approx(
            np.mean(zts["grow"]["T_z"]), abs=1e-6
        )

    def test_default_zone_matches_single_zone_baseline(self):
        # grow's zone view equals the global config with T_light=25; with
        # no inter-zone coupling its hourly columns must reproduce a
        # single-zone run of that exact config bitwise.
        d = preset_609().to_dict()
        d["setpoints"]["T_light"] = 25
        baseline = DesignEngine(cache_dir=None).run(
            DesignProject.from_dict(d), weather=synthetic_weather(48)
        )
        multi = DesignEngine(cache_dir=None).run(
            two_zone_project(), weather=synthetic_weather(48)
        )
        grow = multi.zone_timeseries["grow"]
        for col in ("T_z", "RH_z", "load_kw", "X_d"):
            assert grow[col] == baseline.timeseries[col], f"grow.{col} drifted"


class _CountingPolicy:
    """Records call counts and the zone_id seen via PolicyContext.reset."""

    owns = frozenset()  # Wave 6: pure observer declares no authority.

    def __init__(self):
        self.reset_calls = 0
        self.step_calls = 0
        self.zone_id = None
        self._key = "main"

    def reset(self, ctx):
        self.reset_calls += 1
        self.zone_id = ctx.zone_id
        self._key = ctx.zone_id

    def plan_daily(self, obs):
        return None

    def step(self, obs):
        self.step_calls += 1
        return ControlAction(zones={self._key: ZoneAction()})


class TestPerZonePolicies:
    def test_each_zone_policy_called_expected_count(self):
        p_nursery, p_grow = _CountingPolicy(), _CountingPolicy()
        eng = DesignEngine(cache_dir=None)
        p = two_zone_project()
        sub = max(1, int(round(3600.0 / p.space.timestep_s)))  # preset: 6
        eng.run(
            p,
            weather=synthetic_weather(48),
            policies={"nursery": p_nursery, "grow": p_grow},
        )
        # default control period -> one policy step per substep: 48 h * 6
        expected = 48 * sub
        assert p_nursery.step_calls == expected
        assert p_grow.step_calls == expected
        assert p_nursery.zone_id == "nursery"
        assert p_grow.zone_id == "grow"


class TestFailFastValidation:
    def test_policy_key_mismatch_raises(self):
        eng = DesignEngine(cache_dir=None)
        with pytest.raises(ValueError, match="nursery"):
            eng.run(
                two_zone_project(),
                weather=synthetic_weather(48),
                policies={"nursery": _CountingPolicy()},  # 'grow' missing
            )

    def test_single_policy_with_zones_ambiguous(self):
        eng = DesignEngine(cache_dir=None)
        with pytest.raises(ValueError, match="ambiguous|policies"):
            eng.run(
                two_zone_project(),
                weather=synthetic_weather(48),
                policy=_CountingPolicy(),
            )

    def test_policies_without_zones_raises(self):
        eng = DesignEngine(cache_dir=None)
        with pytest.raises(ValueError, match="policies"):
            eng.run(
                preset_609(),
                weather=synthetic_weather(48),
                policies={"main": _CountingPolicy()},
            )

    def test_interzone_stub_not_implemented(self):
        eng = DesignEngine(cache_dir=None)
        with pytest.raises(NotImplementedError):
            eng.run(two_zone_project(), weather=synthetic_weather(48), interzone=object())


class TestAutoSizeIsolation:
    def test_shared_project_not_written_back(self):
        p = two_zone_project()
        hvac_before = p.hvac.P_rated_w
        deh_before = p.deh.P_ref_w
        DesignEngine(cache_dir=None).run(p, weather=synthetic_weather(48))
        assert p.hvac.P_rated_w == hvac_before
        assert p.deh.P_ref_w == deh_before

    def test_zone_sizes_reported(self, two_zone_result):
        zones = two_zone_result.summary["zones"]
        for zid in ("nursery", "grow"):
            assert zones[zid]["hvac_P_rated_w"] > 0
            assert zones[zid]["deh_P_ref_w"] > 0


class TestFacilityAggregate:
    def test_annual_energy_equals_zone_sum_from_timeseries(self, two_zone_result):
        zts = two_zone_result.zone_timeseries
        zone_total = sum(
            zts[z]["load_kw"][i] for z in ("nursery", "grow") for i in range(48)
        )
        assert two_zone_result.summary["annual_energy_kwh"] == pytest.approx(
            round(zone_total, 2), abs=0.05
        )
