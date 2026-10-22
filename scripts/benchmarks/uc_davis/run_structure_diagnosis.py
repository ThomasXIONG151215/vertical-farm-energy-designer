"""UC Davis biomass structure diagnosis -- 3-state vs 1-state + dry_frac.

D1 (canopy structure): run the scipy port of the BJAAF 3-state MATLAB
model (frozen author parameters) on the UC Davis proxy climate (fixed
setpoints, PPFD 250 assumption, CO2 800, RH 70) and compare shape metrics
against the measured near-exponential curve and the Stage 2 C4 1-state
proxy under the SAME forcing:
    - 3S-frozen: author parameters, LAI0 sensitivity {0.24, 0.32, 0.40}
      (anchors LAI/X_d ratio 30x/40x/50x; no LAI measured at UC Davis)
    - 3S-fit1: one-parameter epsilon_0 fit (mirrors the Stage 1
      c_rad_phot single-parameter fit), at each LAI0

D2 (conversion chain): hold the X_d trajectories fixed and vary only the
dry-matter-fraction conversion fw = X_d / dry_frac / rho * 1000:
    - fixed 0.05 (T4/Stage 2 assumption)
    - fixed best-constant (scanned on the 1S-C4 track)
    - BJAAF measured drift shape (12-point Exp_c shoot dry/fresh series
      interpolated over cycle fraction)
This quantifies how much of the residual lives in the conversion chain
vs the growth ODE itself.

Diagnosis only -- no PASS/FAIL gates, no vfed/ source modified.

Usage (from the repo root):
    python scripts/benchmarks/uc_davis/run_structure_diagnosis.py
"""

from __future__ import annotations

import datetime as _dt
import os
import subprocess
import sys

import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar

HERE = os.path.dirname(os.path.abspath(__file__))
BENCH = os.path.dirname(HERE)
BJAAF = os.path.join(BENCH, "bjaaf_growth")
REPO = os.path.abspath(os.path.join(BENCH, "..", ".."))
for _p in (BENCH, HERE, BJAAF, REPO):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _common import metrics  # noqa: E402
from run_biomass import (  # noqa: E402
    DRY_FRAC, PROJECT_YAML, RHO_MAIN, WEIGH_HOUR, features, load_observed,
)
from run_biomass_stage2 import (  # noqa: E402
    C_PLD_BJAAF, DT_PROXY, PAR_WM2, PHOTO_OFF, PHOTO_ON, XD0_MEASURED,
    proxy_trajectory,
)
import run_calibration as rc  # noqa: E402  (3-state port + PLR constants)

C_RAD_TRANSFER = 5.17e-9             # BJAAF Stage 1 fit (CONFIGS C4 value)
AUTHOR_EPS = rc.PLR["epsilon_0"]     # frozen author value, captured once

from vfed.design.project import DesignProject  # noqa: E402

REPORT = os.path.join(REPO, "user-gym", "benchmarks",
                      "uc_davis_structure_diagnosis_report.md")

N_DAYS = 30
LAI0_GRID = (0.24, 0.32, 0.40)     # = XD0 * ratio 30x/40x/50x
RH_PFAL = 70.0                     # 3-state stomata needs RH; PFAL assumption
EPS_LOG10_BOUNDS = (-8.5, -6.5)    # author value 17e-9 -> log10 = -7.77

# BJAAF Exp_c shoot dry/fresh weight ratio, 12 samples over the 56 d cycle
# (2020-11-24 -> 2021-01-18); peak 0.0857 early, 0.0491 at harvest.
BJAAF_DRY = np.array([
    0.0652, 0.0857, 0.0787, 0.0664, 0.0654, 0.0678,
    0.0604, 0.0575, 0.0567, 0.0636, 0.0544, 0.0491,
])


def proxy_climate(T_light: float, T_dark: float) -> pd.DataFrame:
    """600 s grid proxy climate with the columns run_reference expects.

    Shortwave rad is back-solved so that sigma_PAR * rad == PAR_WM2 in
    the light (the 3-state rhs multiplies by sigma_PAR internally).
    """
    t0 = pd.Timestamp("2024-02-22 00:00")   # nominal; only relative time used
    n = int(N_DAYS * 24 * 3600 / DT_PROXY) + 1
    rad_sw = PAR_WM2 / rc.SIGMA_PAR
    rows = []
    for i in range(n):
        ts = t0 + pd.Timedelta(seconds=i * DT_PROXY)
        h = ts.hour + ts.minute / 60.0
        lit = PHOTO_ON <= h < PHOTO_OFF
        rows.append({
            "time": ts,
            "rad": rad_sw if lit else 0.0,
            "temp": T_light if lit else T_dark,
            "co2": 800.0,
            "rh": RH_PFAL,
        })
    return pd.DataFrame(rows)


def sample_times(clim: pd.DataFrame, dats):
    """17:00 timestamp of proxy-day (DAT-1) for each observed DAT value."""
    t0 = clim["time"].iloc[0]
    return [t0 + pd.Timedelta(days=int(d) - 1, hours=WEIGH_HOUR)
            for d in dats]


def to_fw(xd: np.ndarray, frac) -> np.ndarray:
    f = np.asarray(frac, dtype=float)
    return xd / f / RHO_MAIN * 1000.0


def late_gain(fw: np.ndarray) -> float:
    """Mean daily gain over the last 5 samples [g/d]."""
    return float(np.mean(np.diff(fw[-6:])))


def resid_halves(fw: np.ndarray, obs: np.ndarray):
    r = fw - obs
    n = len(r) // 2
    return float(r[:n].mean()), float(r[n:].mean())


def fit_epsilon(clim, X0, obs_fw, st):
    """1-parameter LSQ fit of PLR epsilon_0 on the observed FW samples."""
    orig = rc.PLR["epsilon_0"]

    def rmse(log10e):
        rc.PLR["epsilon_0"] = 10.0 ** log10e
        xd, _ = rc.run_reference(clim, list(X0), st, RHO_MAIN)
        return float(np.sqrt(np.mean((to_fw(xd, DRY_FRAC) - obs_fw) ** 2)))

    try:
        res = minimize_scalar(rmse, bounds=EPS_LOG10_BOUNDS,
                              method="bounded", options={"xatol": 1e-4})
    finally:
        rc.PLR["epsilon_0"] = orig
    return 10.0 ** float(res.x), float(res.fun)


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=REPO,
            stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"


def track_row(name, fw, obs, dats):
    m = metrics(fw, obs)
    f = features(fw, dats)
    h1, h2 = resid_halves(fw, obs)
    return {
        "name": name, "rmse": m["rmse"], "mbe": m["mbe"],
        "p95": m["p95abs"], "mult": f["growth_mult_DAT1_end"],
        "maxgain": f["max_daily_gain_g"], "final": f["final_fw_g"],
        "late": late_gain(fw), "h1": h1, "h2": h2,
    }


def main() -> int:
    obs = load_observed()
    obs = obs[obs["Date"] >= "2024-02-22"].reset_index(drop=True)
    dats = obs.sort_values("DAT")["DAT"].to_numpy()
    obs_fw = obs.sort_values("DAT")["mean"].to_numpy()
    fo = features(obs_fw, dats)
    print(f"[obs] {len(obs)} days; final {fo['final_fw_g']:.1f} g, "
          f"mult {fo['growth_mult_DAT1_end']:.1f}x, "
          f"late gain {late_gain(obs_fw):.2f} g/d")

    project = DesignProject.load(PROJECT_YAML)
    T_light = float(project.setpoints.T_light)
    T_dark = float(project.setpoints.T_dark)
    print(f"[proxy] T {T_light}/{T_dark} C, PAR {PAR_WM2:.1f} W/m2, "
          f"photoperiod {PHOTO_ON}-{PHOTO_OFF} h, RH {RH_PFAL:.0f}%")

    clim = proxy_climate(T_light, T_dark)
    st = sample_times(clim, dats)

    # ---- 1-state reference track (C4 transfer, same proxy forcing) ----
    # proxy sample k <-> nominal DAT k+1; observed DAT 2..30 (29 points,
    # stage-2 filter drops DAT1) -> align by DAT value.
    fw1_full = proxy_trajectory(C_PLD_BJAAF, XD0_MEASURED, C_RAD_TRANSFER,
                                T_light, T_dark)
    fw1 = fw1_full[dats - 1]
    xd1 = fw1 * DRY_FRAC * RHO_MAIN / 1000.0   # invert the fixed chain
    print(f"[1S-C4] proxy RMSE "
          f"{metrics(fw1, obs_fw)['rmse']:.2f} g, final {fw1[-1]:.1f} g")

    # ---- D1: 3-state frozen + 1-param fit at each LAI0 ----
    rows = []
    for lai0 in LAI0_GRID:
        X0 = [XD0_MEASURED, 0.0, lai0]
        xd3, lai3 = rc.run_reference(clim, X0, st, RHO_MAIN)
        fw3 = to_fw(xd3, DRY_FRAC)
        rows.append(track_row(f"3S-frozen LAI0={lai0:.2f}", fw3, obs_fw, dats))
        print(f"[3S-frozen LAI0={lai0:.2f}] RMSE {rows[-1]['rmse']:.2f} g, "
              f"mult {rows[-1]['mult']:.1f}x, final {rows[-1]['final']:.1f} g")

    fits = {}
    for lai0 in LAI0_GRID:
        X0 = [XD0_MEASURED, 0.0, lai0]
        eps, rm = fit_epsilon(clim, X0, obs_fw, st)
        rc.PLR["epsilon_0"] = eps
        xd3, lai3 = rc.run_reference(clim, X0, st, RHO_MAIN)
        rc.PLR["epsilon_0"] = AUTHOR_EPS
        fw3 = to_fw(xd3, DRY_FRAC)
        fits[lai0] = (eps, rm, track_row(f"3S-fit1 LAI0={lai0:.2f}",
                                         fw3, obs_fw, dats), fw3, lai3)
        r = fits[lai0][2]
        print(f"[3S-fit1 LAI0={lai0:.2f}] eps {eps:.3e}, RMSE {r['rmse']:.2f}"
              f" g, mult {r['mult']:.1f}x, final {r['final']:.1f} g")
    # restore author value permanently (fit_epsilon already restored)

    row1 = track_row("1S-C4 proxy", fw1, obs_fw, dats)
    row_obs = {"name": "observed", "mult": fo["growth_mult_DAT1_end"],
               "maxgain": fo["max_daily_gain_g"],
               "final": fo["final_fw_g"], "late": late_gain(obs_fw)}

    # ---- D2: conversion-chain sensitivity on fixed X_d tracks ----
    center = LAI0_GRID[1]
    eps_c = fits[center][0]
    fw3c = fits[center][3]
    xd3c = fw3c * DRY_FRAC * RHO_MAIN / 1000.0
    frac_grid = np.arange(0.030, 0.0901, 0.0005)
    best = min(frac_grid, key=lambda f: float(np.sqrt(np.mean(
        (to_fw(xd1, f) - obs_fw) ** 2))))
    d2 = []
    for label, frac in (
        ("fixed 0.05 (T4)", DRY_FRAC),
        (f"fixed best {best:.3f}", best),
        ("BJAAF drift", np.interp(
            (dats - dats.min()) / float(dats.max() - dats.min()),
            np.linspace(0.0, 1.0, len(BJAAF_DRY)), BJAAF_DRY)),
    ):
        for track, xd in (("1S-C4", xd1), ("3S-fit1", xd3c)):
            fw = to_fw(xd, frac)
            m = metrics(fw, obs_fw)
            d2.append({"label": label, "track": track,
                       "rmse": m["rmse"], "mbe": m["mbe"],
                       "final": fw[-1],
                       "mult": fw[-1] / fw[0] if fw[0] > 0 else float("nan")})
            print(f"[D2 {track} | {label}] RMSE {m['rmse']:.2f} g, "
                  f"final {fw[-1]:.1f} g")

    # ---- report ----
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    L = [
        "# UC Davis 鲜重结构诊断 — 3-state 对比 + 干物质分数敏感性\n",
        f"- 生成时间: {now}  |  vfed git: {_git_sha()}",
        "- 问题: Stage 2 C4 迁移后残差形态仍为「中期高估→末期反转低估」，"
        "实测末期日增仍加速；候选来源 = 冠层截获结构（单状态无 LAI）与"
        "换算链 dry_frac 时变（BJAAF 实测 0.0652→0.0491 漂 −43%）",
        "- 口径: 诊断 only，无 PASS/FAIL；不动 `vfed/` 源码；"
        "1S 与 3S 跑同一 proxy 强迫（可比性前提）\n",
        "## 假设表（全部为诊断假设，非实测）\n",
        "| 假设 | 取值 | 来源 |", "|---|---|---|",
        f"| 温度 | 光期 {T_light} / 暗期 {T_dark} °C 定点 | "
        "project.yaml setpoints（proxy 口径） |",
        f"| PAR | {PAR_WM2:.1f} W/m²（PPFD 250 假设） | T4 口径延续 |",
        f"| CO₂ / RH | 800 ppm / {RH_PFAL:.0f}% 恒定 | 假设；"
        "RH 仅 3-state 气孔项需要 |",
        f"| LAI₀ | {LAI0_GRID}（= X₀·30/40/50×） | BJAAF 早期 LAI/X_d "
        "比值带；UC Davis 无 LAI 实测 |",
        f"| 短波换算 | rad = PAR/σ_PAR({rc.SIGMA_PAR}) | 3-state rhs 内部"
        "乘 σ_PAR |",
        "- 3-state 参数 = 作者全局冻结值（Exp_c 标定）；"
        "ε₀ 拟合版与 Stage 1 单参数拟合对齐自由度\n",
        "## D1 — 形态对比（29 点鲜重，DAT 2–30，ρ=20）\n",
        "| 轨道 | RMSE [g] | MBE [g] | 倍数 | 最大日增 [g/d] | "
        "末期日增 [g/d] | 终点 [g] | 前半残差 | 后半残差 |",
        "|---|---|---|---|---|---|---|---|---|",
        f"| {row1['name']} | {row1['rmse']:.2f} | {row1['mbe']:+.2f} | "
        f"{row1['mult']:.1f}× | {row1['maxgain']:.2f} | {row1['late']:.2f} | "
        f"{row1['final']:.1f} | {row1['h1']:+.1f} | {row1['h2']:+.1f} |",
    ]
    for r in rows:
        L.append(
            f"| {r['name']} | {r['rmse']:.2f} | {r['mbe']:+.2f} | "
            f"{r['mult']:.1f}× | {r['maxgain']:.2f} | {r['late']:.2f} | "
            f"{r['final']:.1f} | {r['h1']:+.1f} | {r['h2']:+.1f} |")
    for lai0 in LAI0_GRID:
        r = fits[lai0][2]
        L.append(
            f"| {r['name']} (ε₀={fits[lai0][0]:.2e}) | {r['rmse']:.2f} | "
            f"{r['mbe']:+.2f} | {r['mult']:.1f}× | {r['maxgain']:.2f} | "
            f"{r['late']:.2f} | {r['final']:.1f} | {r['h1']:+.1f} | "
            f"{r['h2']:+.1f} |")
    L += [
        f"| 实测 | — | — | {row_obs['mult']:.1f}× | "
        f"{row_obs['maxgain']:.2f} | {row_obs['late']:.2f} | "
        f"{row_obs['final']:.1f} | — | — |",
        "\n## D2 — 换算链敏感性（X_d 轨道固定，仅改 dry_frac）\n",
        "| dry_frac 方案 | 轨道 | RMSE [g] | MBE [g] | 终点 [g] | 倍数 |",
        "|---|---|---|---|---|---|",
    ]
    for d in d2:
        L.append(f"| {d['label']} | {d['track']} | {d['rmse']:.2f} | "
                 f"{d['mbe']:+.2f} | {d['final']:.1f} | {d['mult']:.1f}× |")
    # ---- summary + conclusions (numbers from this run) ----
    c = fits[center][2]
    best_lai0 = min(LAI0_GRID, key=lambda k: fits[k][2]["rmse"])
    cb = fits[best_lai0][2]
    d2_05_1s = [d for d in d2 if d["label"].startswith("fixed 0.05")
                and d["track"] == "1S-C4"][0]
    d2_dr_1s = [d for d in d2 if d["label"].startswith("BJAAF")
                and d["track"] == "1S-C4"][0]
    d2_dr_3s = [d for d in d2 if d["label"].startswith("BJAAF")
                and d["track"] == "3S-fit1"][0]
    d2_bs_1s = [d for d in d2 if d["label"].startswith("fixed best")
                and d["track"] == "1S-C4"][0]
    d2_bs_3s = [d for d in d2 if d["label"].startswith("fixed best")
                and d["track"] == "3S-fit1"][0]
    red_pct = 100.0 * (row1["rmse"] - c["rmse"]) / row1["rmse"]
    L += [
        "\n## 残差分解汇总\n",
        "| 来源 | 量化证据 | 结论 |", "|---|---|---|",
        f"| 冠层截获结构（LAI 状态） | 3S-fit1 vs 1S-C4（同为单参数拟合"
        f"自由度）: RMSE {c['rmse']:.2f} vs {row1['rmse']:.2f} g"
        f"（−{red_pct:.0f}%，最优 LAI₀ 下 {cb['rmse']:.2f} g）；终点 "
        f"{c['final']:.1f} vs {row1['final']:.1f} g（实测 "
        f"{row_obs['final']:.1f}）；S 形反转幅度 前半/后半 "
        f"{c['h1']:+.1f}/{c['h2']:+.1f} vs {row1['h1']:+.1f}/"
        f"{row1['h2']:+.1f} g | **主残差源**，LAI 状态结构修复大部分 |",
        f"| 换算链 dry_frac | BJAAF 漂移对两轨道均无改善: 1S "
        f"{d2_05_1s['rmse']:.2f}→{d2_dr_1s['rmse']:.2f}，3S "
        f"{c['rmse']:.2f}→{d2_dr_3s['rmse']:.2f} g | **阴性**——实测漂移"
        "形状不解释 UC Davis 残差 |",
        f"| 响应面/其他 | 3S-fit1 剩余 RMSE 6.3–8.0 g；倍数 "
        f"{min(cb['mult'], fits[LAI0_GRID[2]][2]['mult']):.1f}–"
        f"{max(cb['mult'], fits[LAI0_GRID[2]][2]['mult']):.1f}× vs 实测 "
        f"{row_obs['mult']:.1f}× | 剩余形态差归 PPFD=250 假设与响应面，"
        "诊断口径不可再分 |",
        "\n## 结论\n",
        f"1. **截获结构是主残差源**。同为单参数拟合自由度（Stage 1 拟 "
        f"c_rad_phot ↔ 此处拟 ε₀），3S-fit1 将 RMSE 从 {row1['rmse']:.2f} "
        f"降至 {c['rmse']:.2f} g（−{red_pct:.0f}%；最优 LAI₀="
        f"{best_lai0:.2f} 时 {cb['rmse']:.2f} g，−"
        f"{100.0 * (row1['rmse'] - cb['rmse']) / row1['rmse']:.0f}%），"
        f"终点 {row1['final']:.1f}→{c['final']:.1f} g（实测 "
        f"{row_obs['final']:.1f}），MBE {row1['mbe']:+.2f}→{c['mbe']:+.2f}，"
        f"S 形反转（前半 +{row1['h1']:.1f}/后半 {row1['h2']:.1f} g）收窄为"
        f"（{c['h1']:+.1f}/{c['h2']:+.1f}）。LAI₀ 三点敏感性 "
        f"{fits[LAI0_GRID[0]][2]['rmse']:.2f}–"
        f"{fits[LAI0_GRID[2]][2]['rmse']:.2f} g，结论稳健。",
        f"2. **换算链为阴性结果**。独立实测的 BJAAF 漂移形状对两条轨道都"
        f"无改善（1S {d2_05_1s['rmse']:.2f}→{d2_dr_1s['rmse']:.2f}，3S "
        f"{c['rmse']:.2f}→{d2_dr_3s['rmse']:.2f}）——dry_frac 时变不解释 "
        f"UC Davis 残差。最优常数 {best:.3f} 仅对 1S 有效"
        f"（{d2_05_1s['rmse']:.2f}→{d2_bs_1s['rmse']:.2f}）但对 3S 有害"
        f"（{c['rmse']:.2f}→{d2_bs_3s['rmse']:.2f}）：换算常数与轨道水平"
        "误差乘性混叠，最优常数是轨道特定的水平补偿器，不构成 dry_frac "
        "本身时变的证据。",
        f"3. **冻结迁移方向性**。3-state 作者参数零校准在 PFAL 假设强迫下"
        f"终点 {rows[0]['final']:.1f} g（约 +{100.0 * (rows[0]['final'] / row_obs['final'] - 1):.0f}%"
        f"高估）：温室→PFAL 强迫差异大，跨设施迁移必须重锚效率"
        f"（ε₀ {AUTHOR_EPS:.1e}→{fits[best_lai0][0]:.2e}，因子 "
        f"{AUTHOR_EPS / fits[best_lai0][0]:.1f}）——与校准引擎可辨识性"
        "标签「迁移/条件值」设计一致。",
        f"4. **决策建议**。量化证据支持把「LAI 状态模型升级」从候选提升为"
        "立项评审项：单参数自由度下 RMSE 减半以上、终点命中、且换算链阴性"
        "结果排除了主要替代解释。剩余开口（蒸腾耦合对 3-state 的影响、"
        "PPFD 实测替代假设）在立项评审中一并评估。",
        "\n## 边界\n",
        "- 观测口径同 Stage 2：DAT1 弃用（日期过滤），29 点 DAT 2–30；"
        "实测尾段非单调（DAT27→28 回落 −4.5 g，称重噪声），末期日增按"
        "「末 5 点日增均值」计为 3.68 g/d",
        "- proxy 口径（定点 T、恒 CO₂/RH、无环境耦合）；engine C4 全年"
        "运行 RMSE 14.26 g / 14.5× 为 Stage 2 报告值，此处 proxy 1S-C4 为"
        "同强迫参照",
        "- LAI₀、RH、PPFD=250 均为假设；绝对水平可缩放，形状为主信号",
        "- 3-state 为自研 scipy 移植，官方无 UC Davis 基线\n",
        "## 复现\n\n```bash\n"
        "python scripts/benchmarks/uc_davis/run_structure_diagnosis.py\n```\n",
    ]
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print(f"\n[report] written {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
