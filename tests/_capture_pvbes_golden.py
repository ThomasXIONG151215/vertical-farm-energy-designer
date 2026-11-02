"""Wave 0 golden capture: freeze the current PVBES-path summary numbers.

Runs preset_609 with PV=100 m2 + battery=50 kWh on the cached Fengxian
2023 weather and dumps the full summary dict to JSON.  This file is the
bit-drift reference for the G1-G13 program: every merged change must keep
these numbers identical while new fields are at their defaults.

Run from the repo root:  python tests/_capture_pvbes_golden.py out.json
"""

import json
import sys

from vfed.design.engine import DesignEngine
from vfed.design.presets import preset_609


def main(out_path: str) -> None:
    p = preset_609()
    p.pv_area_m2 = 100.0
    p.battery_kwh = 50.0
    r = DesignEngine(cache_dir="weather_cache").run(p)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(r.summary, f, indent=2, sort_keys=True)
    print(f"golden summary written: {out_path}")


if __name__ == "__main__":
    main(sys.argv[1])
