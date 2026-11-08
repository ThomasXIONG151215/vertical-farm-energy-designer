"""C1: building-loop control protocol (policy seat, merge, zero drift).

Contract under test:
  * ``merge`` priority: step action > daily plan entry for the hour >
    None, per field, for all 10 ``ZoneAction`` fields.
  * ``vfed/design/control.py`` is a pure leaf (stdlib + numpy only, no
    vfed imports, no relative imports) — enforced by an AST gate.
  * A present-but-all-None policy is bit-identical to ``policy=None``
    on the 609 preset 48 h synthetic-weather zero-drift sha256 oracle
    (same WIN/LINUX per-OS constants as test_23..29 / 38).
  * A policy that sets ``RH_sp=60`` (below the preset's 65) shifts the
    ``RH_z`` hourly-mean DOWN (direction assertion only).
  * ``control.period_s=1800`` at dt=600 makes ``policy.step`` fire
    exactly 96 times per 48 h (288 substeps / 3), with ``plan_daily``
    at each day boundary (2 calls) and tick times that are multiples
    of 1800 s.
"""

import ast
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from vfed.design.control import (
    ControlAction,
    DailyPlan,
    Observation,
    PolicyContext,
    ZoneAction,
    merge,
)
from vfed.design.engine import DesignEngine

# Same per-OS constants the test_23..29 / 38 suites pin (duplicated per
# the repo's standalone-test convention; see test_23_wall_rc.py:30-42).
WIN = "1764f7e6ee6e185d41e8b438a2c3c81320f38e9d02468446dc5f249a25870192"
LINUX = "ede65ba07d51c5ed4aa52f353f93590925a80fda93edf70c7436b2db8fa0c336"
ACCEPTED = frozenset({WIN, LINUX})

# One sentinel value per ZoneAction field, honouring each field's type.
FIELD_VALUES = {
    "led_on": True,
    "led_dim": 0.5,
    "T_sp": 22.5,
    "T_heat_sp": 19.5,
    "RH_sp": 60.0,
    "hvac_m": 0.7,
    "deh_m": 0.6,
    "econ_override": True,
    "erv_flow_m3h": 300.0,
    "co2_sp": 900.0,
}
ALTERNATE_VALUES = {
    "led_on": False,
    "led_dim": 0.25,
    "T_sp": 21.5,
    "T_heat_sp": 18.5,
    "RH_sp": 62.0,
    "hvac_m": 0.3,
    "deh_m": 0.2,
    "econ_override": False,
    "erv_flow_m3h": 150.0,
    "co2_sp": 700.0,
}


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


class _NullPolicy:
    """Attaches the policy seat but never overrides anything."""

    owns = frozenset()  # Wave 6: pure observer declares no authority.

    def reset(self, ctx):
        pass

    def plan_daily(self, obs):
        return None

    def step(self, obs):
        return ControlAction(zones={"main": ZoneAction()})


class TestMergePriority:
    @pytest.mark.parametrize("field_name", sorted(FIELD_VALUES))
    def test_action_only(self, field_name):
        value = FIELD_VALUES[field_name]
        action = ZoneAction(**{field_name: value})
        for daily in (None, {}, {5: ZoneAction()}):
            merged = merge(action, daily, 5)
            assert getattr(merged, field_name) == value

    @pytest.mark.parametrize("field_name", sorted(FIELD_VALUES))
    def test_daily_only(self, field_name):
        value = FIELD_VALUES[field_name]
        daily = {5: ZoneAction(**{field_name: value})}
        for action in (None, ZoneAction()):
            merged = merge(action, daily, 5)
            assert getattr(merged, field_name) == value

    @pytest.mark.parametrize("field_name", sorted(FIELD_VALUES))
    def test_both_action_wins(self, field_name):
        action = ZoneAction(**{field_name: FIELD_VALUES[field_name]})
        daily = {5: ZoneAction(**{field_name: ALTERNATE_VALUES[field_name]})}
        merged = merge(action, daily, 5)
        assert getattr(merged, field_name) == FIELD_VALUES[field_name]

    @pytest.mark.parametrize("field_name", sorted(FIELD_VALUES))
    def test_neither_is_none(self, field_name):
        for daily in (None, {}, {5: ZoneAction()}):
            merged = merge(None, daily, 5)
            assert getattr(merged, field_name) is None

    def test_all_none_action_merge_is_all_none(self):
        merged = merge(ZoneAction(), {5: ZoneAction()}, 5)
        assert all(getattr(merged, f) is None for f in FIELD_VALUES)

    def test_daily_other_hour_does_not_leak(self):
        daily = {6: ZoneAction(T_sp=25.0)}
        assert merge(None, daily, 5).T_sp is None
        assert merge(None, daily, 6).T_sp == 25.0


class TestControlModuleIsPureLeaf:
    def test_imports_stdlib_and_numpy_only(self):
        source = Path("vfed/design/control.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        allowed = set(getattr(sys, "stdlib_module_names", ())) or {
            # py3.8 fallback: the modules control.py can legitimately use.
            "abc", "argparse", "ast", "collections", "copy", "dataclasses",
            "datetime", "enum", "functools", "hashlib", "itertools", "json",
            "math", "os", "re", "statistics", "sys", "time", "types",
            "typing", "unittest",
        }
        allowed.add("numpy")
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    assert root in allowed, f"import {alias.name} not allowed"
            elif isinstance(node, ast.ImportFrom):
                assert node.level == 0, (
                    f"relative import (level={node.level}) in control.py"
                )
                root = node.module.split(".")[0] if node.module else ""
                assert root in allowed, f"from {node.module} import not allowed"


class TestZeroDriftIntegration:
    def test_policy_none_matches_oracle(self):
        from vfed.design.presets import preset_609

        result = DesignEngine(cache_dir=None).run(
            preset_609(), weather=synthetic_weather(48)
        )
        assert _ts_sha256(result) in ACCEPTED

    def test_all_none_policy_same_hash(self):
        """A seated but silent policy must not perturb one float."""
        from vfed.design.presets import preset_609

        result = DesignEngine(cache_dir=None).run(
            preset_609(), weather=synthetic_weather(48), policy=_NullPolicy()
        )
        assert _ts_sha256(result) in ACCEPTED

    def test_rh60_policy_lowers_rh_z_mean(self):
        from vfed.design.presets import preset_609

        class RH60Policy:
            owns = frozenset({"RH_sp"})  # Wave 6: claims RH_sp.

            def reset(self, ctx):
                pass

            def plan_daily(self, obs):
                return None

            def step(self, obs):
                return ControlAction(zones={"main": ZoneAction(RH_sp=60.0)})

        baseline = DesignEngine(cache_dir=None).run(
            preset_609(), weather=synthetic_weather(48)
        )
        treated = DesignEngine(cache_dir=None).run(
            preset_609(), weather=synthetic_weather(48), policy=RH60Policy()
        )
        base_mean = float(np.mean(baseline.timeseries["RH_z"]))
        treated_mean = float(np.mean(treated.timeseries["RH_z"]))
        assert treated_mean < base_mean


class TestTickCadence:
    def test_period_1800_gives_96_ticks_per_48h(self):
        from vfed.design.presets import preset_609

        class CountingPolicy:
            owns = frozenset()  # Wave 6: counts ticks, sets nothing.

            def __init__(self):
                self.ctx = None
                self.step_count = 0
                self.plan_count = 0
                self.tick_times_s = []

            def reset(self, ctx):
                self.ctx = ctx

            def plan_daily(self, obs):
                self.plan_count += 1
                return None

            def step(self, obs):
                self.step_count += 1
                self.tick_times_s.append(obs.t_s)
                return ControlAction()

        p = preset_609()
        p.control.period_s = 1800.0
        pol = CountingPolicy()
        DesignEngine(cache_dir=None).run(
            p, weather=synthetic_weather(48), policy=pol
        )
        # dt=600 s, sub=6, so 48 h is 288 substeps; period 1800 s is
        # every 3rd substep -> 96 ticks, one plan per day boundary -> 2.
        assert pol.step_count == 96
        assert pol.plan_count == 2
        assert all(t % 1800 == 0 for t in pol.tick_times_s)
        assert pol.ctx is not None
        assert pol.ctx.control_period_s == 1800.0
        assert pol.ctx.dt == 600.0
        assert len(pol.ctx.hourly_prices) == 24

    def test_default_period_ticks_every_substep(self):
        from vfed.design.presets import preset_609

        class CountingPolicy:
            owns = frozenset()  # Wave 6: counts ticks, sets nothing.

            def __init__(self):
                self.step_count = 0

            def reset(self, ctx):
                pass

            def plan_daily(self, obs):
                return None

            def step(self, obs):
                self.step_count += 1
                return ControlAction()

        pol = CountingPolicy()
        DesignEngine(cache_dir=None).run(
            preset_609(), weather=synthetic_weather(48), policy=pol
        )
        # period_s None -> every substep: 48 h x 6 substeps = 288.
        assert pol.step_count == 288
