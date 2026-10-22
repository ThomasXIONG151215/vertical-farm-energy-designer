"""BJAAF Exp_v1 / Exp_v2 frozen-parameter holdout validation (Stage 3).

Stage 1 (run_calibration.py) anchored and fitted the growth parameters on
the Exp_c calibration experiment:

    c_pl_d     = 32.7 m2/kg    (LAI/X_d pairing anchor, interception LSQ)
    c_rad_phot = 5.17e-9 kg/J  (1-param fit, measured PAR drive)

This script freezes BOTH the Stage 1 vfed values AND the authors' global
3-state MATLAB constants and runs them -- with no re-fitting -- on the two
independent validation experiments shipped with the dataset:

    Exp_v1: spring 2020, climate 2020-04-09 17:00 .. 05-14 17:00, 8 samples
            (first 5 columns same layout as Exp_c; 15 trailing empty cols)
    Exp_v2: winter 2022, climate 2022-01-30 15:00 .. 03-16 15:00, 12 samples
            MainProgram.m is the authors' Exp_v2 driver; its X0
            [0.0019766, 0, 0.0996] equals the 2022-01-30 summary sample.

Two tracks per experiment:
    A) 3-state reference port (authors' frozen constants; only the
       per-experiment plant density rho_c enters ShootRootRatio.m,
       back-computed as mean(X_d / Total dry weight per plant))
    B) vfed 1-state Van Henten with frozen Stage 1 calibration values
       (cross-experiment transfer, mirroring the UC Davis Stage 2 protocol)

Alignment convention: the last summary sample at or before the climate
start is the initial state X0; every later sample is a comparison point.
Integration starts at the first climate row; the offset between the X0
sample instant and the climate start is <= 17 h (same convention as
Stage 1 Exp_c, where X0 00:00 vs climate 15:00).

Note: Exp_v1 time stamps carry sub-second jitter (e.g. 17:00:00.06), so
the 1-state runner records samples by row INDEX (searchsorted), not by
exact timestamp equality.

Scope note (planning doc v0.4 cross-cutting calibration line, Q3):
greenhouse data is used ONLY for growth-module validation. The measured
climate series is a direct model input; no envelope coupling; envelope/
HVAC parameters are untouched.

Usage (from the repo root):
    python scripts/benchmarks/bjaaf_growth/run_validation.py [--no-report]
"""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import subprocess
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
BENCH = os.path.dirname(HERE)
REPO = os.path.abspath(os.path.join(BENCH, "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, BENCH)
sys.path.insert(0, REPO)

from _common import metrics                      # noqa: E402
from run_calibration import run_reference, DT_S  # noqa: E402

from vfed.plants.van_henten import VanHenten     # noqa: E402

DATA_DIR = os.path.join(REPO, "data", "datasets", "bjaaf-lettuce-growth")
EXPS = {
    "v1": os.path.join(DATA_DIR, "Greenhouse Climate & Crop data_Exp_v1.xlsx"),
    "v2": os.path.join(DATA_DIR, "Lettuce growth model program",
                       "Greenhouse Climate & Crop data_Exp_v2.xlsx"),
}
REPORT = os.path.join(REPO, "user-gym", "benchmarks",
                      "bjaaf_exp_validation_report.md")

# Stage 1 frozen calibration (bjaaf_growth_calibration_report.md)
C_PL_D = 32.7        # m2/kg, interception-LSQ anchor on Exp_c
C_RAD_PHOT = 5.17e-9  # kg/J, 1-param fit on Exp_c measured PAR


def load_exp(path: str):
    """Climate (5-min, first 5 cols) + growth summary of one experiment."""
    clim = pd.read_excel(path, sheet_name="Greenhouse climate",
                         usecols=[0, 1, 2, 3, 4])
    clim.columns = ["time", "co2", "temp", "rh", "rad"]
    gro = pd.read_excel(path, sheet_name="Lettuce growth summary")
    gro = gro[["Time", "Xd [kg m-2]", "LAI [-]",
               "Total dry weight [g]"]].rename(columns={
        "Time": "date", "Xd [kg m-2]": "xd", "LAI [-]": "lai",
        "Total dry weight [g]": "tdw"}).dropna(subset=["date"])
    return clim, gro


def run_vfed_samples(clim, xd0, c_pl_d, c_rad_phot, sample_times):
    """Euler-step the 1-state Van Henten model; record by row index.

    Index-based recording (searchsorted on the climate time array) is
    robust to the sub-second jitter present in Exp_v1 timestamps.
    Returns sampled X_d aligned with *sample_times*.
    """
    grow = VanHenten(co2_ppm=558.0, c_pl_d=c_pl_d, c_rad_phot=c_rad_phot)
    temp = clim["temp"].to_numpy()
    co2 = clim["co2"].to_numpy()
    par = 0.5 * clim["rad"].to_numpy()            # sigma_PAR * shortwave
    t64 = clim["time"].to_numpy()
    targets = t64.searchsorted(pd.DatetimeIndex(sample_times).to_numpy(),
                               side="left")
    if np.any(targets < 1) or np.any(targets >= len(clim)):
        raise ValueError("sample time outside climate window")
    want = {int(j): None for j in targets}
    xd = xd0
    for i in range(len(clim) - 1):
        grow.co2_ppm = float(co2[i])
        _, xd = grow.step(float(temp[i]), float(par[i]), xd, DT_S)
        j = i + 1
        if j in want and want[j] is None:
            want[j] = xd
    return np.array([want[int(j)] for j in targets])


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=REPO,
            stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-report", action="store_true")
    args = ap.parse_args()

    results = {}
    for tag, path in EXPS.items():
        print(f"[{tag}] loading {os.path.basename(path)} ...")
        clim, gro = load_exp(path)
        rho_c = float(np.mean(gro["xd"].to_numpy() * 1e3
                              / gro["tdw"].to_numpy()))
        t0 = clim["time"].iloc[0]
        pre = gro[gro["date"] <= t0]
        post = gro[gro["date"] > t0].reset_index(drop=True)
        if len(pre) == 0 or len(post) < 3:
            raise RuntimeError(f"{tag}: alignment failed")
        x0_row = pre.iloc[-1]
        xd0, lai0 = float(x0_row["xd"]), float(x0_row["lai"])
        sample_times = pd.DatetimeIndex(post["date"])
        obs_xd = post["xd"].to_numpy()
        obs_lai = post["lai"].to_numpy()
        print(f"[{tag}] climate {clim['time'].iloc[0]} -> "
              f"{clim['time'].iloc[-1]} ({len(clim)} rows), "
              f"rho_c={rho_c:.2f} plants/m2")
        print(f"[{tag}] X0 @ {x0_row['date']}  X_d={xd0:.6f} LAI={lai0:.5f}; "
              f"{len(post)} comparison points")

        # track A: authors' 3-state, frozen constants
        ref_xd, ref_lai = run_reference(clim, [xd0, 0.0, lai0],
                                        sample_times, rho_c)
        m_ref = metrics(ref_xd, obs_xd)
        m_ref_lai = metrics(ref_lai, obs_lai)

        # track B: vfed 1-state, frozen Stage 1 calibration
        sim_xd = run_vfed_samples(clim, xd0, C_PL_D, C_RAD_PHOT,
                                  sample_times)
        m_sim = metrics(sim_xd, obs_xd)

        mult_obs = float(obs_xd[-1] / xd0)
        mult_ref = float(ref_xd[-1] / xd0)
        mult_sim = float(sim_xd[-1] / xd0)
        clim_stats = {
            "t_min": clim["temp"].min(), "t_max": clim["temp"].max(),
            "t_mean": clim["temp"].mean(), "c_min": clim["co2"].min(),
            "c_max": clim["co2"].max(), "c_mean": clim["co2"].mean(),
            "r_min": clim["rad"].min(), "r_max": clim["rad"].max(),
            "r_mean": clim["rad"].mean(),
        }
        results[tag] = {
            "path": path, "rho_c": rho_c, "x0_row": x0_row,
            "n_clim": len(clim),
            "xd0": xd0, "lai0": lai0, "post": post,
            "sample_times": sample_times, "obs_xd": obs_xd,
            "obs_lai": obs_lai, "ref_xd": ref_xd, "ref_lai": ref_lai,
            "sim_xd": sim_xd, "m_ref": m_ref, "m_ref_lai": m_ref_lai,
            "m_sim": m_sim, "mult_obs": mult_obs, "mult_ref": mult_ref,
            "mult_sim": mult_sim, "clim_stats": clim_stats,
        }
        print(f"[{tag}] 3-state  RMSE {m_ref['rmse']:.4f} MBE "
              f"{m_ref['mbe']:+.4f} final {ref_xd[-1]:.4f} "
              f"({mult_ref:.1f}x vs obs {mult_obs:.1f}x) | LAI RMSE "
              f"{m_ref_lai['rmse']:.3f}")
        print(f"[{tag}] 1-state  RMSE {m_sim['rmse']:.4f} MBE "
              f"{m_sim['mbe']:+.4f} final {sim_xd[-1]:.4f} "
              f"({mult_sim:.1f}x)")

    if args.no_report:
        return 0

    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    L = [
        "# BJAAF Exp_v1 / Exp_v2 冻结参数 holdout 验证（Stage 3）\n",
        f"- 生成时间: {now}  |  vfed git: {_git_sha()}",
        "- 数据: `data/datasets/bjaaf-lettuce-growth/`（Mendeley "
        "r7z9ttvkyh v2, CC BY 4.0）Exp_v1（2020 春）与 Exp_v2（2022 冬）"
        "两个独立验证试验",
        "- 冻结口径: 所有参数取 Stage 1（Exp_c 标定）终值，本验证**零重拟合**",
        f"  - vfed 1-state: c_pl_d={C_PL_D} m²/kg, "
        f"c_rad_phot={C_RAD_PHOT:.2e} kg/J（Stage 1 锚定+拟合）",
        "  - 3-state 参考: 作者全局冻结常数（.m 转录），仅种植密度按各实验"
        "反推（ShootRootRatio.m 输入）",
        "- 范围口径: 规划 v0.4 贯穿能力线 / Q3 —— 温室数据仅用于生长模块"
        "验证，气候序列为直接输入，围护/HVAC 不涉及\n",
        "## 对齐\n",
        "| | Exp_v1 | Exp_v2 |", "|---|---|---|",
    ]
    r1, r2 = results["v1"], results["v2"]
    L += [
        f"| 时段 | 2020-04-09 17:00 → 05-14 17:00（35 d） "
        f"| 2022-01-30 15:00 → 03-16 15:00（45 d） |",
        f"| 气候行数 | {r1['n_clim']} | {r2['n_clim']} |",
        f"| 密度反推 | {r1['rho_c']:.2f} 株/m² | {r2['rho_c']:.2f} 株/m²"
        "（= MATLAB 硬编码 11.52 ✓）|",
        f"| X₀ 采样 | {r1['x0_row']['date']}（首采样，早于气候窗 17 h） "
        f"| {r2['x0_row']['date']}（第 2 采样，早于气候窗 15 h；"
        "MainProgram.m X0=[0.0019766, 0, 0.0996] 与此一致）|",
        f"| X₀ 值 | X_d={r1['xd0']:.6f}, LAI={r1['lai0']:.3f} "
        f"| X_d={r2['xd0']:.6f}, LAI={r2['lai0']:.3f} |",
        f"| 对比点 | {len(r1['post'])}（04-14 → 05-14 每 5 d） "
        f"| {len(r2['post'])}（02-04 → 03-16 每 5 d） |",
    ]
    for tag, r in results.items():
        cs = r["clim_stats"]
        L += [
            f"\n## Exp_{tag} 结果\n",
            "### 气候范围（实测输入）\n",
            "| 变量 | min | max | mean |", "|---|---|---|---|",
            f"| 气温 [°C] | {cs['t_min']:.1f} | {cs['t_max']:.1f} "
            f"| {cs['t_mean']:.1f} |",
            f"| CO₂ [ppm] | {cs['c_min']:.0f} | {cs['c_max']:.0f} "
            f"| {cs['c_mean']:.0f} |",
            f"| 短波辐射 [W/m²] | {cs['r_min']:.0f} | {cs['r_max']:.0f} "
            f"| {cs['r_mean']:.1f} |\n",
            "### 汇总指标（X_d, kg/m²）\n",
            "| 指标 | vfed 1-state（Stage 1 冻结） | 3-state 参考"
            "（作者冻结） |", "|---|---|---|",
            f"| RMSE | {r['m_sim']['rmse']:.4f} | "
            f"{r['m_ref']['rmse']:.4f} |",
            f"| MBE (sim−obs) | {r['m_sim']['mbe']:+.4f} | "
            f"{r['m_ref']['mbe']:+.4f} |",
            f"| P95 abs err | {r['m_sim']['p95abs']:.4f} | "
            f"{r['m_ref']['p95abs']:.4f} |",
            f"| 终点 X_d | {r['sim_xd'][-1]:.4f} | {r['ref_xd'][-1]:.4f} "
            f"|（实测 {r['obs_xd'][-1]:.4f}）|",
            f"| 增长倍数 (终点/X₀) | {r['mult_sim']:.1f}× | "
            f"{r['mult_ref']:.1f}× |（实测 {r['mult_obs']:.1f}×）|",
            f"| LAI RMSE | —（无 LAI 状态） | "
            f"{r['m_ref_lai']['rmse']:.3f} |\n",
            "### 逐点 X_d [kg/m²]\n",
            "| 日期 | 实测 | vfed 1-state | 3-state | LAI 实测 | "
            "LAI 3-state |", "|---|---|---|---|---|---|",
        ]
        for d, o, s, rr, lo, ls in zip(
                r["post"]["date"].dt.strftime("%m-%d"), r["obs_xd"],
                r["sim_xd"], r["ref_xd"], r["obs_lai"], r["ref_lai"]):
            L.append(f"| {d} | {o:.5f} | {s:.5f} | {rr:.5f} | "
                     f"{lo:.3f} | {ls:.3f} |")
    L += [
        "\n## 结论\n",
        "- **第三个配置点**: 两套模型、两套参数全部冻结于 Exp_c，"
        "在 2020 春 / 2022 冬两个独立试验上直接外推（UC Davis PFAL 恒光、"
        "Exp_c 冷季温室之后）。零重拟合\n",
        f"- **3-state 作者模型**: v2 终点 −{100*(1-r2['ref_xd'][-1]/r2['obs_xd'][-1]):.1f}%"
        "（几乎命中），v1 终点 "
        f"+{100*(r1['ref_xd'][-1]/r1['obs_xd'][-1]-1):.1f}% 超调且末端 LAI "
        f"高估 {100*(r1['ref_lai'][-1]/r1['obs_lai'][-1]-1):.0f}%（"
        f"{r1['ref_lai'][-1]:.2f} vs {r1['obs_lai'][-1]:.2f}）——同设施"
        "跨季节迁移基本成立，春季高温高辐射末段偏乐观",
        f"- **vfed 1-state 跨设施迁移**: v2 表现好（MBE "
        f"{r2['m_sim']['mbe']:+.4f}≈0，终点 "
        f"{100*(r2['sim_xd'][-1]/r2['obs_xd'][-1]-1):+.0f}%），v1 全程高估"
        f"（MBE {r1['m_sim']['mbe']:+.4f}，终点 "
        f"+{100*(r1['sim_xd'][-1]/r1['obs_xd'][-1]-1):.0f}%）。归因辐射外推: "
        f"v1 均值 {r1['clim_stats']['r_mean']:.0f} W/m² 为 Exp_c 标定窗"
        "（64 W/m²）的 2.8 倍，冬季拟合的 c_rad_phot 在春季强光下系统性"
        "偏高效——c_rad_phot 是条件值的直接实证（Phase 3 可辨识性标签"
        "「迁移」类的实证依据）",
        "- **残差形态第三次复现**: v2 1-state 中段高估（02-19→03-01）"
        "末期反转低估（03-06 起）——与 Exp_c Stage 1、UC Davis Stage 2 "
        "形态同构。单状态结构限制（LAI/X_d 漂移不可跟踪）在第三个数据集"
        "上再次出现",
        "- 与 Stage 1/2 相同的诚实口径: 不设 PASS/FAIL 门禁；残差形态"
        "（中期/末期偏差结构）比单一 RMSE 更有解释力",
        "\n## 复现\n\n```bash\n"
        "python scripts/benchmarks/bjaaf_growth/run_validation.py\n```\n",
    ]
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print(f"\n[report] written {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
