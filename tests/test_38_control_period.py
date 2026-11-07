"""Tests for the T2 control-cadence contract (control.period_s).

Three layers: (1) the config contract round-trips — default omitted,
explicit kept, null sentinel re-derives, unknown keys rejected; (2)
``_resolve_control_steps`` does the integer-k fail-fast arithmetic
(None -> 1, integer multiples pass, non-integer / sub-dt periods raise);
(3) the field is INERT for the simulation — preset_609 with
control.period_s=1800 on the 48 h synthetic weather reproduces the
shared zero-drift sha256 exactly (the tick hook lands with the control
protocol in C1, so until then the cadence must not perturb a float).
"""

import hashlib
import json

import numpy as np
import pandas as pd
import pytest

from vfed.design.engine import DesignEngine, _resolve_control_steps
from vfed.design.project import DesignProject

# Same per-OS constants the test_23..29 / co2 suites pin (duplicated per
# the repo's standalone-test convention; see test_23_wall_rc.py:30-42).
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


class TestConfigContract:
    def test_default_omitted_from_to_dict(self):
        assert "control" not in DesignProject().to_dict()

    def test_explicit_period_roundtrips(self):
        p = DesignProject.from_dict({"control": {"period_s": 1800}})
        assert p.control.period_s == 1800
        assert DesignProject.from_dict(p.to_dict()).control.period_s == 1800

    def test_null_sentinel_roundtrips_to_none(self):
        p = DesignProject.from_dict({"control": {"period_s": None}})
        assert p.control.period_s is None
        assert "control" not in p.to_dict()

    def test_unknown_key_rejected(self):
        with pytest.raises(ValueError, match="Unrecognised keys in 'control'"):
            DesignProject.from_dict({"control": {"cadence_s": 60}})


class TestResolveControlSteps:
    def test_none_is_physics_timestep(self):
        assert _resolve_control_steps(600.0, None) == 1

    def test_integer_multiples_pass(self):
        assert _resolve_control_steps(600.0, 600.0) == 1
        assert _resolve_control_steps(600.0, 1800.0) == 3
        assert _resolve_control_steps(900.0, 3600.0) == 4

    def test_non_integer_multiple_raises(self):
        with pytest.raises(ValueError, match="integer multiple"):
            _resolve_control_steps(600.0, 333.0)

    def test_sub_dt_period_raises(self):
        with pytest.raises(ValueError, match="integer multiple"):
            _resolve_control_steps(600.0, 300.0)


class TestFieldIsInertUntilProtocol:
    def test_period_1800_zero_drift(self):
        """A valid cadence must not perturb the simulation before C1."""
        from vfed.design.presets import preset_609

        p = preset_609()
        p.control.period_s = 1800.0
        result = DesignEngine(cache_dir=None).run(p, weather=synthetic_weather(48))
        ts_json = json.dumps(result.timeseries, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(ts_json.encode("utf-8")).hexdigest()
        assert digest in ACCEPTED

    def test_bad_period_fails_fast_at_engine(self):
        from vfed.design.presets import preset_609

        p = preset_609()
        p.control.period_s = 333.0
        with pytest.raises(ValueError, match="integer multiple"):
            DesignEngine(cache_dir=None).run(p, weather=synthetic_weather(48))
