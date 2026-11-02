"""Wave 0 golden drift gate: PVBES summary must stay bit-identical (G1-G13).

Gate 1 of the two-gate validation system.  ``tests/golden/pvbes_golden.json``
freezes the full ``r.summary`` of preset_609 with PV 100 m2 + battery 50 kWh
on the cached Fengxian 2023 weather, captured BEFORE any G1-G13 code change
(2026-11-01).  Every merged wave must keep this summary IDENTICAL while the
new contract fields (site.albedo/transposition, pv.module,
battery.power_kw/chemistry, tariff.export_limit_kw/demand_charge_per_kw)
sit at their defaults.

A deliberate bitstream change requires regenerating the golden file AND
recording why in this docstring.  A failure here means a wave leaked
behavior into the closed-switch path -- fix it before merging.

Regenerate::

    python tests/_capture_pvbes_golden.py tests/golden/pvbes_golden.json

(run from the repo root; requires the weather_cache directory).
"""

import json
from pathlib import Path

import pytest

from vfed.design.engine import DesignEngine
from vfed.design.presets import preset_609

GOLDEN_PATH = Path(__file__).parent / "golden" / "pvbes_golden.json"
CAPTURE_SCRIPT = Path(__file__).parent / "_capture_pvbes_golden.py"


@pytest.fixture(scope="session")
def pvbes_summary_609():
    """One engine run per test session: preset_609 + PV 100 m2 + 50 kWh."""
    p = preset_609()
    p.pv_area_m2 = 100.0
    p.battery_kwh = 50.0
    r = DesignEngine(cache_dir="weather_cache").run(p)
    return r.summary


def _diffs(golden, current, prefix=""):
    """Collect every differing path between the two summary dicts."""
    out = []
    for k in sorted(set(golden) | set(current)):
        path = f"{prefix}{k}"
        if k not in golden:
            out.append(f"{path}: new key = {current[k]!r}")
        elif k not in current:
            out.append(f"{path}: key vanished (golden {golden[k]!r})")
        elif isinstance(golden[k], dict) and isinstance(current[k], dict):
            out.extend(_diffs(golden[k], current[k], prefix=f"{path}."))
        elif golden[k] != current[k]:
            out.append(f"{path}: golden {golden[k]!r} != current {current[k]!r}")
    return out


def test_golden_files_exist():
    assert GOLDEN_PATH.is_file(), (
        f"golden baseline missing: {GOLDEN_PATH}. Regenerate with "
        f"`python tests/_capture_pvbes_golden.py tests/golden/pvbes_golden.json` "
        f"from the repo root."
    )
    assert CAPTURE_SCRIPT.is_file(), (
        f"capture script missing: {CAPTURE_SCRIPT} -- it is the documented "
        f"way to (re)generate the golden baseline."
    )


def test_pvbes_summary_bit_exact(pvbes_summary_609):
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    assert golden, "golden baseline is empty -- regenerate it"
    drift = _diffs(golden, pvbes_summary_609)
    assert not drift, (
        "PVBES golden drift detected (gate 1 violation): the summary "
        "changed while all new G1-G13 fields are at their defaults.\n  "
        + "\n  ".join(drift)
        + "\nIf the change is INTENTIONAL and approved, regenerate the "
        "golden baseline and record why in this test's docstring."
    )
