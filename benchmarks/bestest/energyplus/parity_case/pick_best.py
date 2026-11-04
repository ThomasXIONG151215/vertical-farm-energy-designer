#!/usr/bin/env python
"""List all scan rows per case sorted by the parity score (freeze helper)."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CASES = ["600", "900", "600FF", "900FF"]

for case in (sys.argv[1:] or CASES):
    path = HERE / f"parity_scan_{case}.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    print(f"=== {case} ({len(rows)} candidates)")
    ranked = sorted(rows, key=lambda r: r["score"])
    for r in ranked:
        ch = r["rows"]
        t = ch.get("t_z", {})
        line = (f"  {r['tag']:22s} score {r['score']:6.3f} | t_z RMSE "
                f"{t.get('rmse', float('nan')):.3f} MBE {t.get('mbe', 0):+.3f}")
        for k in ("heat_kwh", "cool_kwh"):
            if k in ch:
                line += f" | {k[:4]} {ch[k]['diff_pct']:+6.2f}% (rmse {ch[k]['rmse']:.3f})"
        print(line)
