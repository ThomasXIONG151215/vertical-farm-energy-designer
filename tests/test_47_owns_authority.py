"""Wave 6: control ownership (``owns``) authority contract (test_47).

Contract under test:
  * ``CONTROL_FIELDS`` registry integrity: the 11 ``ZoneAction`` fields
    are exactly ``BUILDING_CONTROL_NAMES``; the two dispatch-tier fields
    (``charge_w`` / ``discharge_w``) live only in ``CONTROL_FIELDS``;
    every ``voids_params`` entry is a real flattened config key
    (cross-checked against ``PARAM_PATH_MAP`` / ``PARAM_TOPLEVEL_MAP``).
  * ``validate_owns`` gates (via ``DesignEngine.run``): a policy without
    ``owns`` is rejected; an unknown field name is rejected naming the
    offender; ``owns = frozenset()`` is a legal pure observer.
  * Zero drift: an observer policy (``owns = frozenset()``, all-``None``
    actions) and an all-default ``setpoint_offset`` policy both land in
    the shared ACCEPTED sha256 oracle (same WIN/LINUX constants as
    test_23..29 / 38 / 40 / 43).
  * Per-tick seat enforcement in the hourly loop: an owned field left
    ``None`` at a control tick raises ``RuntimeError`` naming the field
    and ``t_s``; a field set without being declared in ``owns`` raises
    ``RuntimeError`` naming the field.
  * ``SetpointOffsetPolicy.owns`` derives from its effective params;
    ``t_offset_k=1.0`` claims ``{T_sp, T_heat_sp}`` and shifts the mean
    ``T_z`` UP directionally.
  * ``build_policy`` spec-key whitelist (``schedule_echo`` accepted).
  * Optimize conflict gate: a grid/candidate flat key whose config
    authority a declared policy spec voids raises ``ValueError`` naming
    the key; ``"schedule_echo": true`` on the spec is the escape hatch.
  * Hollowed-config warning: seating a policy that voids config keys
    emits a ``UserWarning`` listing them at startup.
  * Multizone: bad ``owns`` on a ``policies[zid]`` seat is reported
    before the loop runs.
"""

import hashlib
import json

import numpy as np
import pandas as pd
import pytest

from vfed.design.control import (
    BUILDING_CONTROL_NAMES,
    CONTROL_FIELDS,
    ControlAction,
    ZoneAction,
    build_policy,
    register_policy,
)
from vfed.design.engine import DesignEngine
from vfed.design.optimize import evaluate_candidate, optimize
from vfed.design.presets import preset_609
from vfed.design.project import (
    PARAM_PATH_MAP,
    PARAM_TOPLEVEL_MAP,
    DesignProject,
)

# Same per-OS constants the test_23..29 / 38 / 40 / 43 suites pin
# (duplicated per the repo's standalone-test convention).
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


def _run(policy=None, policies=None, project=None):
    p = project if project is not None else preset_609()
    return DesignEngine(cache_dir=None).run(
        p, weather=synthetic_weather(48), policy=policy, policies=policies
    )


class _ObserverPolicy:
    """Pure observer: seats the policy chair but never sets a field."""

    owns = frozenset()

    def reset(self, ctx):
        pass

    def plan_daily(self, obs):
        return None

    def step(self, obs):
        return ControlAction()


@register_policy("wave6_led_owner")
class Wave6LedOwnerPolicy:
    """Registered test policy owning ``led_on`` (LED forced off).

    Used by the optimize conflict-gate tests: owning ``led_on`` voids
    ``light_start_hour`` / ``photoperiod_hours``.
    """

    owns = frozenset({"led_on"})

    def __init__(self):
        self._zone_id = "main"

    def reset(self, ctx):
        self._zone_id = ctx.zone_id

    def plan_daily(self, obs):
        return None

    def step(self, obs):
        return ControlAction(
            zones={self._zone_id: ZoneAction(led_on=False)}
        )


# ---------------------------------------------------------------------------
# Registry integrity
# ---------------------------------------------------------------------------
class TestRegistry:
    def test_zoneaction_fields_match_building_control_names(self):
        assert set(ZoneAction.__dataclass_fields__) == set(BUILDING_CONTROL_NAMES)
        # Dispatch-tier fields live in CONTROL_FIELDS but are not
        # build-loop ownable seats.
        assert "charge_w" in CONTROL_FIELDS
        assert "discharge_w" in CONTROL_FIELDS
        assert "charge_w" not in BUILDING_CONTROL_NAMES
        assert "discharge_w" not in BUILDING_CONTROL_NAMES
        assert CONTROL_FIELDS["charge_w"].tier == 1
        assert CONTROL_FIELDS["led_on"].tier == 0

    def test_voids_params_are_real_config_keys(self):
        known = set(PARAM_PATH_MAP) | set(PARAM_TOPLEVEL_MAP)
        for fname, cf in CONTROL_FIELDS.items():
            unknown = set(cf.voids_params) - known
            assert not unknown, f"{fname} voids unknown config keys {sorted(unknown)}"


# ---------------------------------------------------------------------------
# validate_owns gates via DesignEngine.run
# ---------------------------------------------------------------------------
class TestValidateOwnsGates:
    def test_missing_owns_raises_in_engine_run(self):
        class NoOwns:
            def reset(self, ctx):
                pass

            def plan_daily(self, obs):
                return None

            def step(self, obs):
                return ControlAction()

        with pytest.raises(ValueError, match="owns"):
            _run(policy=NoOwns())

    def test_unknown_field_name_raises(self):
        class BadOwns:
            owns = frozenset({"warp_drive"})

            def reset(self, ctx):
                pass

            def plan_daily(self, obs):
                return None

            def step(self, obs):
                return ControlAction()

        with pytest.raises(ValueError, match="warp_drive"):
            _run(policy=BadOwns())


# ---------------------------------------------------------------------------
# Zero drift: observer + all-default setpoint_offset
# ---------------------------------------------------------------------------
class TestZeroDrift:
    def test_observer_policy_hashes_to_accepted(self):
        result = _run(policy=_ObserverPolicy())
        assert _ts_sha256(result) in ACCEPTED

    def test_all_default_setpoint_offset_hashes_to_accepted(self):
        pol = build_policy({"type": "setpoint_offset", "params": {}})
        assert pol.owns == frozenset()
        result = _run(policy=pol)
        assert _ts_sha256(result) in ACCEPTED


# ---------------------------------------------------------------------------
# Per-tick seat enforcement in the loop
# ---------------------------------------------------------------------------
class TestSeatEnforcement:
    def test_owned_field_left_none_raises_with_t_s(self):
        class TspOwnerMissingSeat:
            owns = frozenset({"T_sp"})

            def reset(self, ctx):
                pass

            def plan_daily(self, obs):
                return None

            def step(self, obs):
                return ControlAction()  # never supplies T_sp

        with pytest.raises(RuntimeError, match=r"T_sp.*t_s=\d+"):
            _run(policy=TspOwnerMissingSeat())

    def test_undeclared_field_set_raises(self):
        class LedDimOverreach:
            owns = frozenset()

            def reset(self, ctx):
                pass

            def plan_daily(self, obs):
                return None

            def step(self, obs):
                return ControlAction(
                    zones={"main": ZoneAction(led_dim=0.5)}
                )

        with pytest.raises(RuntimeError, match="led_dim"):
            _run(policy=LedDimOverreach())


# ---------------------------------------------------------------------------
# SetpointOffsetPolicy derives owns from effective params
# ---------------------------------------------------------------------------
class TestSetpointOffsetOwns:
    def test_t_offset_claims_tsp_pair_and_shifts_tz_up(self):
        pol = build_policy(
            {"type": "setpoint_offset", "params": {"t_offset_k": 1.0}}
        )
        assert pol.owns == frozenset({"T_sp", "T_heat_sp"})
        baseline = _run()
        treated = _run(policy=pol)
        assert float(np.mean(treated.timeseries["T_z"])) > float(
            np.mean(baseline.timeseries["T_z"])
        )


# ---------------------------------------------------------------------------
# build_policy spec-key whitelist
# ---------------------------------------------------------------------------
class TestBuildPolicyWhitelist:
    def test_unknown_spec_key_raises(self):
        with pytest.raises(ValueError, match="typo_key"):
            build_policy({"type": "setpoint_offset", "typo_key": 1})

    def test_schedule_echo_key_accepted(self):
        pol = build_policy(
            {
                "type": "setpoint_offset",
                "params": {},
                "schedule_echo": True,
            }
        )
        assert pol.owns == frozenset()


# ---------------------------------------------------------------------------
# Optimize conflict gate + escape hatch
# ---------------------------------------------------------------------------
class TestOptimizeConflictGate:
    def test_optimize_grid_conflict_raises(self):
        grid = {
            "light_start_hour": [6, 22],
            "policy": [{"type": "wave6_led_owner", "params": {}}],
        }
        with pytest.raises(ValueError, match="light_start_hour"):
            optimize(preset_609(), grid, weather=synthetic_weather(48))

    def test_optimize_schedule_echo_escape_allows(self):
        grid = {
            "light_start_hour": [6],
            "policy": [
                {
                    "type": "wave6_led_owner",
                    "params": {},
                    "schedule_echo": True,
                }
            ],
        }
        out = optimize(preset_609(), grid, weather=synthetic_weather(48))
        assert len(out["results"]) == 1
        assert out["best"] is not None
        assert out["best"]["light_start_hour"] == 6

    def test_evaluate_candidate_conflict_raises(self):
        candidate = {
            "schema": 1,
            "T_light": 24.0,
            "policy": {
                "type": "setpoint_offset",
                "params": {"t_offset_k": 1.0},
            },
        }
        with pytest.raises(ValueError, match="T_light"):
            evaluate_candidate(
                preset_609(), candidate, weather=synthetic_weather(48)
            )


# ---------------------------------------------------------------------------
# Hollowed-config warning at startup
# ---------------------------------------------------------------------------
class TestHollowedWarning:
    def test_voided_config_keys_warn_at_startup(self):
        pol = build_policy(
            {"type": "setpoint_offset", "params": {"t_offset_k": 1.0}}
        )
        with pytest.warns(UserWarning, match="T_light"):
            _run(policy=pol)  # smoke-runs to the warning point


# ---------------------------------------------------------------------------
# Multizone policies seat: bad owns reported before the run
# ---------------------------------------------------------------------------
class TestMultizoneOwns:
    def test_multizone_bad_owns_raises_before_run(self):
        d = preset_609().to_dict()
        d["zones"] = {
            "nursery": {"setpoints": {"T_light": 22}},
            "grow": {"setpoints": {"T_light": 25}},
        }
        p = DesignProject.from_dict(d)

        class StrOwns:
            owns = "RH_sp"  # str, not frozenset -> rejected

            def reset(self, ctx):
                pass

            def plan_daily(self, obs):
                return None

            def step(self, obs):
                return ControlAction()

        with pytest.raises(ValueError, match=r"policies\[nursery\]"):
            _run(
                policies={"nursery": StrOwns(), "grow": _ObserverPolicy()},
                project=p,
            )
