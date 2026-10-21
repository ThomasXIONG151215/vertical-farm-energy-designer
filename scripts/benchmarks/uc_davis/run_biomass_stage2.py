"""UC Davis biomass benchmark, Stage 2 -- BJAAF-anchored c_pl_d transfer.

Tests whether the light-extinction anchor c_pl_d = 32.7 m2/kg (calibrated
on the BJAAF Exp_c greenhouse LAI/X_d pairing, see
scripts/benchmarks/bjaaf_growth/run_calibration.py) improves the UC Davis
PFAL fresh-weight fit reported by run_biomass.py (T4: RMSE 21.49 g/plant,
5.4x near-linear growth vs measured 19.1x near-exponential).

Factorial design (2 x 2 full-engine runs, everything else = T4 baseline):
    c_pl_d   in {53.0 (vfed default), 32.7 (BJAAF anchor)}
    X_d(0)   in {0.02 (vfed default), 0.008 (T4 measured DAT2:
              8 g FW/plant * 20 plants/m2 * 0.05 DM = 0.008 kg/m2)}

Plus an efficiency diagnostic: a fast direct-stepping proxy of the
engine's growth pre-run (fixed T_light/T_dark, PAR 250 umol/m2/s
/ 4.57 umol/J, 14 h photoperiod, CO2 800 ppm -- per T4 assumptions)
scans c_rad_phot to show the remaining shape gap attributable to
efficiency vs structure.

Usage (from the repo root):
    python scripts/benchmarks/uc_davis/run_biomass_stage2.py [--cache DIR]
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
sys.path.insert(0, BENCH)
sys.path.insert(0, HERE)
sys.path.insert(0, REPO)

from _common import metrics  # noqa: E402
from run_biomass import (  # noqa: E402
    CYCLE_DAYS, DRY_FRAC, PROJECT_YAML, RHO_MAIN, WEIGH_HOUR, features,
    load_observed,
)

from vfed.design.engine import DesignEngine  # noqa: E402
from vfed.design.project import DesignProject  # noqa: E402
from vfed.plants.van_henten import VanHenten  # noqa: E402

REPORT = os.path.join(REPO, "user-gym", "benchmarks",
                      "uc_davis_biomass_stage2_report.md")

C_PLD_DEFAULT = 53.0    # vfed default
C_PLD_BJAAF = 32.7      # BJAAF Exp_c interception-LSQ anchor
XD0_DEFAULT = 0.02      # vfed default initial dry weight
XD0_MEASURED = 0.008    # T4: measured DAT2 8 g FW/plant @ rho 20, DM 0.05
PAR_WM2 = 250.0 / 4.57  # PPFD assumption / white-LED efficacy [W/m2]
PHOTO_ON, PHOTO_OFF = 8.0, 22.0   # T4 assumed photoperiod [h]
DT_PROXY = 600.0        # engine pre-run growth timestep [s]

CONFIGS = [
    ("C0-default", C_PLD_DEFAULT, XD0_DEFAULT, None),
    ("C1-xd0fix", C_PLD_DEFAULT, XD0_MEASURED, None),
    ("C2-anchor", C_PLD_BJAAF, XD0_DEFAULT, None),
    ("C3-anchor+xd0fix", C_PLD_BJAAF, XD0_MEASURED, None),
    ("C4-full-transfer", C_PLD_BJAAF, XD0_MEASURED, 5.17e-9),
    ("C5-eff-only", C_PLD_DEFAULT, XD0_DEFAULT, 5.17e-9),
]


def run_sim(cache_dir: str, c_pl_d: float, xd0: float,
            c_rad_phot: float = None) -> pd.DataFrame:
    """Full-year engine run with growth overrides -> daily 17:00 X_d rows."""
    project = DesignProject.load(PROJECT_YAML)
    project.setpoints.crop_cycle_days = float(CYCLE_DAYS)
    project.growth.c_pl_d = float(c_pl_d)
    project.growth.initial_dry_weight = float(xd0)
    if c_rad_phot is not None:
        project.growth.c_rad_phot = float(c_rad_phot)
    sim = DesignEngine(cache_dir).run(project)
    ts = pd.DataFrame({"X_d": np.asarray(sim.timeseries["X_d"], dtype=float)})
    ts.index = pd.DatetimeIndex(sim.timeseries["timestamp"])
    win = ts.loc["2024-02-21":"2024-03-24", "X_d"]
    start = win.index[(win < 0.05).argmax() if (win < 0.05).any() else 0]
    daily = []
    for date in pd.date_range(start.normalize(), "2024-03-23", freq="D"):
        stamp = date + pd.Timedelta(hours=WEIGH_HOUR)
        if stamp in ts.index:
            daily.append({"Date": date, "X_d": ts.at[stamp, "X_d"]})
    out = pd.DataFrame(daily)
    out["DAT"] = (out["Date"] - pd.Timestamp("2024-02-21")).dt.days
    return out


def proxy_trajectory(c_pl_d: float, xd0: float, c_rad_phot: float,
                     T_light: float, T_dark: float) -> np.ndarray:
    """Fast proxy of the engine growth pre-run (fixed setpoint T, no env
    coupling). 30-day FW trajectory [g/plant] at rho=20, sampled 17:00."""
    grow = VanHenten(co2_ppm=800.0, c_pl_d=c_pl_d, c_rad_phot=c_rad_phot)
    xd = xd0
    fw = []
    for day in range(30):
        for k in range(144):                     # 600 s steps
            hour = (day * 24.0) + k * DT_PROXY / 3600.0
            lit = (hour % 24.0) >= PHOTO_ON and (hour % 24.0) < PHOTO_OFF
            T = T_light if lit else T_dark
            _, xd = grow.step(T, PAR_WM2 if lit else 0.0, xd, DT_PROXY)
            if abs((hour % 24.0) - (WEIGH_HOUR - DT_PROXY / 3600.0)) \
                    < DT_PROXY / 7200.0:
                fw.append(xd / DRY_FRAC / RHO_MAIN * 1000.0)
    return np.array(fw[:30])


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=REPO,
            stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cache", default=os.path.join(REPO, "weather_cache"))
    ap.add_argument("--no-report", action="store_true")
    args = ap.parse_args()

    obs = load_observed()
    obs = obs[obs["Date"] >= "2024-02-22"].reset_index(drop=True)
    dats = obs.sort_values("DAT")
    obs_fw = dats["mean"].to_numpy()
    fo = features(obs_fw, dats["DAT"].to_numpy())
    print(f"[obs] {len(obs)} days; final {fo['final_fw_g']:.1f} g, "
          f"mult {fo['growth_mult_DAT1_end']:.1f}x, "
          f"max gain {fo['max_daily_gain_g']:.2f} g/d")

    project = DesignProject.load(PROJECT_YAML)
    T_light, T_dark = project.setpoints.T_light, project.setpoints.T_dark
    print(f"[proxy] T_light {T_light} C, T_dark {T_dark} C, "
          f"PAR {PAR_WM2:.1f} W/m2, photoperiod {PHOTO_ON}-{PHOTO_OFF} h")

    results, tables = {}, {}
    for name, c_pld, xd0, c_rp in CONFIGS:
        print(f"[engine] {name}: c_pl_d={c_pld}, X0={xd0}, "
              f"c_rad_phot={c_rp if c_rp else 'default'} ...")
        sim = run_sim(args.cache, c_pld, xd0, c_rp)
        sim["fw_sim"] = sim["X_d"] / DRY_FRAC / RHO_MAIN * 1000.0
        j = obs.merge(sim[["Date", "fw_sim"]], on="Date", how="inner")
        m = metrics(j["fw_sim"].to_numpy(), j["mean"].to_numpy())
        jj = j.sort_values("DAT")
        f = features(jj["fw_sim"].to_numpy(), jj["DAT"].to_numpy())
        results[name] = {"m": m, "f": f, "c_pld": c_pld, "xd0": xd0,
                         "c_rp": c_rp}
        tables[name] = jj
        print(f"[engine] {name}: RMSE {m['rmse']:.2f} g, MBE {m['mbe']:+.2f}, "
              f"mult {f['growth_mult_DAT1_end']:.1f}x, "
              f"final {f['final_fw_g']:.1f} g")

    # efficiency diagnostic (proxy, C3 config): scan c_rad_phot
    scan = []
    for c_rp in (2e-9, 3.5e-9, 5.17e-9, 8e-9, 1.2e-8):
        fw = proxy_trajectory(C_PLD_BJAAF, XD0_MEASURED, c_rp, T_light, T_dark)
        n = min(len(fw), len(obs_fw))
        mm = metrics(fw[:n], obs_fw[:n])
        mult = fw[n - 1] / fw[0] if fw[0] > 0 else float("nan")
        scan.append((c_rp, mm["rmse"], mm["mbe"], fw[n - 1], mult))
        print(f"[proxy] c_rad_phot {c_rp:.2e}: RMSE {mm['rmse']:.2f} g, "
              f"final {fw[n-1]:.1f} g, mult {mult:.1f}x")

    if args.no_report:
        return 0

    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    L = [
        "# UC Davis 鲜重 benchmark — Stage 2 迁移验证（BJAAF 锚定 c_pl_d）\n",
        f"- 生成时间: {now}  |  vfed git: {_git_sha()}",
        "- 问题: T4 基线 RMSE 21.49 g/株，形态 5.4× 近线性 vs 实测 19.1× 近指数",
        "- 迁移参数: c_pl_d = 32.7 m²/kg（BJAAF Exp_c 截获分数 LSQ 锚定，"
        "LAI/X_d 比值型观测量，见 bjaaf_growth_calibration_report.md）",
        "- 设计: 2×2 因子（c_pl_d ∈ {53 默认, 32.7 锚定} × "
        "X₀ ∈ {0.02 默认, 0.008 实测 DAT2}）+ 完整迁移格 C4（锚定+实测 X₀+"
        "BJAAF 效率）+ 效率单因子格 C5，全年 engine 运行，其余同 T4",
        "- 依旧成立的范围声明: PPFD 250 假设、ρ=20、dry_frac=0.05、"
        "14 h 光期均为乘性假设，绝对水平可缩放；曲线形状为主信号\n",
        "## 结果（ρ=20 株/m²）\n",
        "| 配置 | c_pl_d | X₀ | c_rad_phot | RMSE [g] | MBE [g] | P95 [g] | "
        "生长倍数 | 最大日增 [g/d] | 终点 [g] |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name, _, _, _ in CONFIGS:
        r = results[name]
        c_rp_txt = f"{r['c_rp']:.2e}" if r["c_rp"] else "3.5e-9*"
        L.append(
            f"| {name} | {r['c_pld']:.1f} | {r['xd0']:.3f} | {c_rp_txt} "
            f"| {r['m']['rmse']:.2f} | {r['m']['mbe']:+.2f} "
            f"| {r['m']['p95abs']:.2f} | {r['f']['growth_mult_DAT1_end']:.1f}× "
            f"| {r['f']['max_daily_gain_g']:.2f} | {r['f']['final_fw_g']:.1f} |")
    L += [
        f"| 实测 | — | — | — | — | — | — | {fo['growth_mult_DAT1_end']:.1f}× "
        f"| {fo['max_daily_gain_g']:.2f} | {fo['final_fw_g']:.1f} |",
        "\n## 效率诊断（快速代理：定点 T/光制度，无环境耦合；C3 配置）\n",
        "| c_rad_phot [kg/J] | proxy RMSE [g] | MBE [g] | 终点 [g] | 倍数 |",
        "|---|---|---|---|---|",
    ]
    for c_rp, rm, mb, fin, mult in scan:
        L.append(f"| {c_rp:.2e} | {rm:.2f} | {mb:+.2f} | {fin:.1f} "
                 f"| {mult:.1f}× |")
    L += [
        "\n## 结论\n",
        "- （见下方生成后人工核对填写）\n",
        "\n## 复现\n\n```bash\n"
        "python scripts/benchmarks/uc_davis/run_biomass_stage2.py\n```\n",
    ]
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print(f"\n[report] written {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
