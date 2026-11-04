#!/usr/bin/env python
"""Quantify the perceived one-step lag: vfed vs E+ hourly phase analysis.

Answers "vfed 慢一拍?" with measurements:
  1. whole-year cross-correlation at offsets -3..+3 h per channel
  2. April-window daily peak/onset hour agreement per channel
  3. RMSE by hour-of-day (are errors concentrated at transition hours?)
  4. an hour-by-hour excerpt of the day with the largest onset shift
"""
import numpy as np
from pathlib import Path

HERE = Path(__file__).resolve().parent
W = slice(105 * 24, 112 * 24)  # Apr 15-21


def r_off(v, e, off):
    """Pearson r between v[i] and e[i+off] over the valid overlap."""
    if off >= 0:
        a, b = v[off:], e[: len(e) - off]
    else:
        a, b = v[: off], e[-off:]
    if a.std() < 1e-9 or b.std() < 1e-9:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def onset_hour(series, day0_hour, thr):
    """First hour index in the window where series exceeds thr."""
    idx = np.where(series > thr)[0]
    return int(idx[0]) + day0_hour if len(idx) else None


for case in ("600", "900"):
    z = np.load(HERE / f"series_{case}.npz")
    print(f"===== case {case}")
    for key, label in (("t_z", "温度"), ("rh_z", "湿度"),
                       ("heat", "供热"), ("cool", "供冷")):
        v = np.asarray(z[f"{key}_v"], float)
        e = np.asarray(z[f"{key}_e"], float)
        rs = {off: r_off(v, e, off) for off in (-2, -1, 0, 1, 2)}
        best = max(rs, key=lambda k: (rs[k] if np.isfinite(rs[k]) else -9))
        print(f"  {label}: 全年互相关 r(-2..+2) = "
              + " ".join(f"{rs[o]:.4f}" for o in (-2, -1, 0, 1, 2))
              + f"  最优偏移 {best:+d} h")
        # window: daily peak-hour agreement (use local maxima of daily sums)
        vw, ew = v[W], e[W]
        days = vw.reshape(-1, 24)
        days_e = ew.reshape(-1, 24)
        same = neigh = diff = 0
        for d in range(days.shape[0]):
            hv, he = int(np.argmax(days[d])), int(np.argmax(days_e[d]))
            if hv == he:
                same += 1
            elif abs(hv - he) == 1:
                neigh += 1
            else:
                diff += 1
        print(f"    窗口逐日峰值小时: 同桶 {same}/7, 差 1 h {neigh}, "
              f"差 >=2 h {diff}")
    # RMSE by hour-of-day for temperature (transition-hour concentration)
    v = np.asarray(z["t_z_v"], float)
    e = np.asarray(z["t_z_e"], float)
    err2 = (v - e) ** 2
    hod = np.arange(8760) % 24
    tr = err2[(hod >= 5) & (hod <= 9)].sum() + err2[(hod >= 17) & (hod <= 21)].sum()
    print(f"  温度 RMSE 中过渡时段(05-09/17-21)占比: "
          f"{tr / err2.sum() * 100:.1f}%  (时段覆盖 10/24 h)")
    # biggest daily cooling-onset shift day in the window
    cv = np.asarray(z["cool_v"], float)[W]
    ce = np.asarray(z["cool_e"], float)[W]
    worst_day, worst_gap = -1, -1
    for d in range(7):
        iv = np.where(cv[d * 24:(d + 1) * 24] > 0.05)[0]
        ie = np.where(ce[d * 24:(d + 1) * 24] > 0.05)[0]
        if len(iv) and len(ie):
            gap = abs(int(iv[0]) - int(ie[0]))
            if gap > worst_gap:
                worst_day, worst_gap = d, gap
    print(f"  供冷起始时刻差最大的一天: 4 月 {15 + worst_day} 日, "
          f"起始相差 {worst_gap} h")
    d = worst_day
    print(f"  --- 4 月 {15 + d} 日逐时 (供冷 kWh | 室温 °C):")
    print("  hour | " + " | ".join(f"{h:2d}" for h in range(24)))
    print("  vfed cool | " + " | ".join(
        f"{cv[d*24+h]:5.2f}" for h in range(24)))
    print("  E+   cool | " + " | ".join(
        f"{ce[d*24+h]:5.2f}" for h in range(24)))
    tv = np.asarray(z["t_z_v"], float)[W][d * 24:(d + 1) * 24]
    te = np.asarray(z["t_z_e"], float)[W][d * 24:(d + 1) * 24]
    print("  vfed T_z  | " + " | ".join(f"{x:5.1f}" for x in tv))
    print("  E+   T_z  | " + " | ".join(f"{x:5.1f}" for x in te))
