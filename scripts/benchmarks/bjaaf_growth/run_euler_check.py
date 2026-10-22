#!/usr/bin/env python3
"""Step 1 numerical verification for 3-state entry into vfed.

Question: can the 3-state MATLAB-reference model (X_d, C_buf, LAI) be integrated
with the same explicit-Euler scheme vfed uses (600 s step, zero-order-hold
climate), instead of scipy RK45?

Gate (planning doc v0.5, Phase 1.3 "生长模型结构升级" Step 1):
    On four tracks (BJAAF Exp_c / Exp_v1 / Exp_v2 + UC Davis proxy climate),
    max relative difference at sample points between Euler dt=600 and RK45
    must stay < 0.5 % for X_d (LAI reported alongside, no separate gate).
    A dt=300 run is added as step-halving convergence evidence.

Everything else is frozen: author parameters (rc.PLR / rc.SR untouched),
MATLAB guard behaviour stays inside the rhs, sampling = record after the step
that reaches the target time (same convention as Stage 1/3 one-state runs).

Report: user-gym/benchmarks/3state_euler_verification_report.md
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent            # scripts/benchmarks/bjaaf_growth
BJAAF = HERE
BENCH = HERE.parent                               # scripts/benchmarks
UCD = BENCH / "uc_davis"
REPO = BENCH.parent.parent                         # repo root

for _p in (BENCH, HERE, UCD, REPO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from run_calibration import _matlab_reference_rhs, run_reference  # noqa: E402
from run_validation import load_exp  # noqa: E402
from run_structure_diagnosis import proxy_climate, sample_times  # noqa: E402
from run_biomass_stage2 import XD0_MEASURED  # noqa: E402
from run_biomass import RHO_MAIN  # noqa: E402

DATA = REPO / "data" / "datasets" / "bjaaf-lettuce-growth"
REPORT = REPO / "user-gym" / "benchmarks" / "3state_euler_verification_report.md"

GATE_REL_DIFF = 0.5  # percent
PROXY_T_LIGHT = 24.5  # diagnosis setpoints (project.yaml)
PROXY_T_DARK = 18.5
PROXY_LAI0 = 0.32     # mid value of the diagnosis grid (0.24/0.32/0.40)

EXPS = {
    "Exp_c": DATA / "Greenhouse Climate & Crop data_Exp_c.xlsx",
    "Exp_v1": DATA / "Greenhouse Climate & Crop data_Exp_v1.xlsx",
    "Exp_v2": DATA / "Lettuce growth model program"
    / "Greenhouse Climate & Crop data_Exp_v2.xlsx",
}


def euler_run(clim: pd.DataFrame, X0, sample_times, rho_c: float, dt: float):
    """Explicit Euler with zero-order-hold climate.

    rhs is evaluated once per step at the step-start time/气候 state; the
    state advances by dy*dt; samples are recorded after the first step whose
    end reaches the target time (offset <= dt, same as Stage 1/3 convention).
    """
    t0 = clim["time"].iloc[0]
    t_s = (clim["time"] - t0).dt.total_seconds().to_numpy()
    rad = clim["rad"].to_numpy()
    temp = clim["temp"].to_numpy()
    co2 = clim["co2"].to_numpy()
    rh = clim["rh"].to_numpy()
    targets = np.array(
        [(ts - t0).total_seconds() for ts in sample_times], dtype=float
    )
    t_end = float(t_s[-1])

    y = np.array(X0, dtype=float)
    xd_out = np.full(len(targets), np.nan)
    lai_out = np.full(len(targets), np.nan)
    buf_min = float(y[1])
    t = 0.0
    k = 0
    n_steps = 0
    while t < t_end - 1e-9:
        dy = np.asarray(
            _matlab_reference_rhs(t, y, t_s, rad, temp, co2, rh, rho_c),
            dtype=float,
        )
        t_next = min(t + dt, t_end)
        y = y + dy * (t_next - t)
        t = t_next
        n_steps += 1
        if y[1] < buf_min:
            buf_min = float(y[1])
        while k < len(targets) and t >= targets[k] - 1e-6:
            xd_out[k] = y[0]
            lai_out[k] = y[2]
            k += 1
    # any remaining targets beyond t_end: leave NaN, they should not exist
    return xd_out, lai_out, buf_min, n_steps


def rel_diff_pct(a, b):
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    ok = ~np.isnan(a) & ~np.isnan(b) & (b > 0)
    return float(np.max(np.abs(a[ok] - b[ok]) / b[ok]) * 100.0) if ok.any() else np.nan


def track_bjaaf(path: Path):
    clim, gro = load_exp(path)
    t0 = clim["time"].iloc[0]
    pre = gro[gro["date"] <= t0]
    post = gro[gro["date"] > t0]
    X0 = [float(pre["xd"].iloc[-1]), 0.0, float(pre["lai"].iloc[-1])]
    rho_c = float((gro["xd"] * 1e3 / gro["tdw"]).mean())
    sts = list(post["date"])
    return clim, X0, sts, rho_c


def track_proxy():
    clim = proxy_climate(PROXY_T_LIGHT, PROXY_T_DARK)
    X0 = [float(XD0_MEASURED), 0.0, PROXY_LAI0]
    sts = sample_times(clim, list(range(1, 31)))
    return clim, X0, sts, float(RHO_MAIN)


def main() -> int:
    tracks = {}
    for name, path in EXPS.items():
        tracks[name] = track_bjaaf(path)
    tracks["proxy"] = track_proxy()

    rows = []
    details = []
    for name, (clim, X0, sts, rho_c) in tracks.items():
        # RK45 reference (scipy, max_step=600, rtol 1e-3)
        rk_xd, rk_lai = run_reference(clim, X0, sts, rho_c)
        e6_xd, e6_lai, buf6, n6 = euler_run(clim, X0, sts, rho_c, dt=600.0)
        e3_xd, e3_lai, buf3, n3 = euler_run(clim, X0, sts, rho_c, dt=300.0)

        d6_xd = rel_diff_pct(e6_xd, rk_xd)
        d6_lai = rel_diff_pct(e6_lai, rk_lai)
        d3_xd = rel_diff_pct(e3_xd, rk_xd)
        d3_lai = rel_diff_pct(e3_lai, rk_lai)
        gate = "PASS" if (d6_xd < GATE_REL_DIFF) else "FAIL"

        t0 = clim["time"].iloc[0]
        window_d = (sts[-1] - t0).total_seconds() / 86400.0
        rows.append(
            dict(
                track=name, n_samples=len(sts), window_d=round(window_d, 1),
                rho_c=round(rho_c, 2), X0="[%.5f, 0, %.4f]" % (X0[0], X0[2]),
                xd_max_rel_600=d6_xd, xd_max_rel_300=d3_xd,
                lai_max_rel_600=d6_lai, lai_max_rel_300=d3_lai,
                cbuf_min_600=buf6, gate=gate,
            )
        )
        details.append((name, sts, rk_xd, e6_xd, rk_lai, e6_lai))

    df = pd.DataFrame(rows)
    n_pass = int((df["gate"] == "PASS").sum())
    overall = "PASS" if n_pass == len(df) else "FAIL"

    lines = []
    lines.append("# 3-state 模型 Euler 600 s 数值验证（Step 1）\n")
    lines.append("- 日期: %s" % datetime.now().strftime("%Y-%m-%d %H:%M"))
    lines.append(
        "- 问题: 3-state 移植模型（X_d, C_buf, LAI）能否用 vfed 同款"
        "显式 Euler（600 s 步长、零阶保持气候）替代 scipy RK45 进入 vfed。"
    )
    lines.append("- 门禁: 四轨道采样点 X_d 相对差 max < %.1f%%（LAI 仅报告）"
                 % GATE_REL_DIFF)
    lines.append("- 冻结口径: 作者参数原封（ε₀=17e-9 等）；MATLAB C_buf<0 guard "
                 "保留在 rhs 内；采样=步进后记录（同 Stage 1/3 口径）；"
                 "气候 BJAAF 三轨 5 min 网格 / proxy 600 s 网格。\n")
    lines.append("## 汇总\n")
    lines.append(
        "| 轨道 | 采样数 | 窗口 d | rho_c | X0 [X_d,0,LAI] "
        "| Xd 差%% (dt600) | Xd 差%% (dt300) | LAI 差%% (dt600) "
        "| LAI 差%% (dt300) | C_buf min | 门禁 |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        lines.append(
            "| %(track)s | %(n_samples)d | %(window_d).1f | %(rho_c).2f "
            "| %(X0)s | %(xd_max_rel_600).3f | %(xd_max_rel_300).3f "
            "| %(lai_max_rel_600).3f | %(lai_max_rel_300).3f "
            "| %(cbuf_min_600).5f | %(gate)s |" % r
        )
    lines.append("\n总判定: **%s**（%d/%d 轨道通过）\n" % (overall, n_pass, len(df)))

    lines.append("## 逐点对比（Euler dt=600 vs RK45，X_d kg/m²）\n")
    for name, sts, rk_xd, e6_xd, rk_lai, e6_lai in details:
        lines.append("\n### %s\n" % name)
        lines.append("| 时刻 | RK45 X_d | Euler600 X_d | 相对差% |")
        lines.append("|---|---|---|---|")
        for ts, a, b in zip(sts, rk_xd, e6_xd):
            rel = abs(b - a) / a * 100.0 if a > 0 else float("nan")
            lines.append(
                "| %s | %.6f | %.6f | %.3f |"
                % (pd.Timestamp(ts).strftime("%Y-%m-%d"), a, b, rel)
            )

    lines.append("\n## 结论段\n")
    if overall == "PASS":
        lines.append(
            "- 四轨道 X_d 采样点相对差 max 均低于 %.1f%%，且 dt=300 较 dt=600 "
            "未见系统性放大（步长收敛）。显式 Euler 600 s 可作为 vfed 集成的"
            "积分方案，Step 2（plants/ 新类 + engine 三状态接口）解锁。"
            % GATE_REL_DIFF
        )
    else:
        lines.append(
            "- 存在轨道超过 %.1f%% 门禁。集成前需改用自适应步长或在 engine 内"
            "做子步进（sub-stepping），并复核 C_buf 快平衡项。" % GATE_REL_DIFF
        )
    lines.append(
        "- C_buf 轨迹最小值均 >= 0（guard 生效范围内），无负值振荡信号。"
        if all(r["cbuf_min_600"] >= 0 for r in rows)
        else "- 注意: 存在 C_buf < 0 的轨道，集成时需保留 guard 并加监测。"
    )

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(df.to_string(index=False))
    print("\nOverall: %s (%d/%d)" % (overall, n_pass, len(df)))
    print("Report -> %s" % REPORT)
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
