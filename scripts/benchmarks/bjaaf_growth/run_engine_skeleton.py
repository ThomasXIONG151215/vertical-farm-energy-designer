"""Calibration-engine skeleton gate run (BJAAF Exp_c, Stage 1 reproduction).

 Drives the ``vfed.calibration`` package end-to-end on the same data and
 alignment as Stage 1 (``run_calibration.py``, 2026-10-16) and asserts the
 skeleton reproduces the hand-calibration values:

     Gate 1  c_pl_d     ~ 32.7    m2/kg   (tol 0.1;   Stage 1 LSQ value)
     Gate 2  c_rad_phot ~ 5.17e-9 kg/J    (tol 1%;    Stage 1 fit value)
     Gate 3  fit RMSE   ~ 0.0074  kg/m2   (tol 2%;    Stage 1 RMSE, 10 pts)

 Equivalence notes (engine vs Stage 1 script):
     * anchor uses ALL 12 samples (incl. pre-window 2020-11-24), k_PAR=0.9;
     * X0 = 2020-11-29 sample; comparison points 12-04..01-18 (10 pts);
     * script sampled by exact timestamp (Exp_c has no ms tails); the
       engine samples by row index -> runner maps timestamps via
       searchsorted, verified within one 5-min row;
     * par = sigma_PAR(0.5) * shortwave applied here (script layer duty
       per contracts.py).

 Usage (from the repo root):
     python scripts/benchmarks/bjaaf_growth/run_engine_skeleton.py
"""

from __future__ import annotations

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
sys.path.insert(0, REPO)

from vfed.calibration import (AssessmentStatus, CalibrationMetrics,  # noqa: E402
                              CalibrationResult, ClimateSeries,
                              DataSignature, GrowthObservations,
                              ParameterLabel, anchor_c_pl_d,
                              analyze_signature, fit_c_rad_phot,
                              run_growth_series)

XLSX = os.path.join(REPO, "data", "datasets", "bjaaf-lettuce-growth",
                    "Greenhouse Climate & Crop data_Exp_c.xlsx")
REPORT = os.path.join(REPO, "user-gym", "benchmarks",
                      "bjaaf_engine_skeleton_report.md")

SIGMA_PAR = 0.5     # BJAAP PAR/shortwave ratio (adapter duty, script layer)
DT_S = 300.0

# Stage 1 gate values (user-gym/benchmarks/bjaaf_growth_calibration_report.md)
GATE_C_PL_D = 32.7          # m2/kg
GATE_C_RAD_PHOT = 5.17e-9   # kg/J
GATE_RMSE = 0.0074          # kg/m2


def load_data():
    clim = pd.read_excel(XLSX, sheet_name="Greenhouse climate")
    clim.columns = ["time", "co2", "temp", "rh", "rad"]
    gro = pd.read_excel(XLSX, sheet_name="Lettuce growth summary")
    gro = gro[["Time", "Xd [kg m-2]", "LAI [-]"]].rename(
        columns={"Time": "date", "Xd [kg m-2]": "xd", "LAI [-]": "lai"})
    return clim, gro


def sample_row_indices(clim: pd.DataFrame,
                       sample_times: pd.DatetimeIndex) -> np.ndarray:
    """Map sample timestamps to climate row indices (Stage 3 lesson)."""
    t = clim["time"].to_numpy()
    idx = np.searchsorted(t, sample_times.to_numpy())
    ok = (idx < len(t)) & (
        np.abs((t[np.minimum(idx, len(t) - 1)] - sample_times.to_numpy()))
        / np.timedelta64(1, "s") <= DT_S)
    if not bool(np.all(ok)):
        raise RuntimeError("sample timestamp misses the climate grid by >1 row")
    return idx


def main() -> int:
    print("[data] loading Exp_c ...")
    clim, gro = load_data()

    # ---- input layer: raw frames -> engine contracts (adapter script duty)
    obs = GrowthObservations(times=gro["date"], x_d=gro["xd"].to_numpy(),
                             lai=gro["lai"].to_numpy())
    climate = ClimateSeries(times=clim["time"], temp_c=clim["temp"].to_numpy(),
                            co2_ppm=clim["co2"].to_numpy(),
                            par_w=SIGMA_PAR * clim["rad"].to_numpy(),
                            dt_s=DT_S)
    sig = DataSignature.bjaaf_like()

    # ---- layer 2: identifiability
    report_id = analyze_signature(sig)
    print("[identifiability]")
    for line in report_id.lines():
        print("   " + line)

    # ---- layer 1: adapter A anchor (all 12 paired samples)
    anchor = anchor_c_pl_d(obs)
    print("[anchor] c_pl_d = %.2f (regression %.2f), ratio %.1f-%.1f"
          % (anchor.value, anchor.c_regression,
             anchor.ratio_min, anchor.ratio_max))

    # ---- alignment (identical to Stage 1 main())
    gro_w = gro[gro["date"] > clim["time"].iloc[0]].reset_index(drop=True)
    xd0 = float(gro["xd"].iloc[1])            # 2020-11-29 = initial state
    sample_times = pd.DatetimeIndex(gro_w["date"])
    obs_xd = gro_w["xd"].to_numpy()
    idx = sample_row_indices(clim, sample_times)
    window_days = (sample_times[-1] - gro["date"].iloc[1]).total_seconds() / 86400.0
    print("[align] X0 = %.6f kg/m2, %d comparison points, window %.1f d"
          % (xd0, len(idx), window_days))

    # ---- layer 3: 1-parameter fit on measured climate drive
    c_rp, rmse, n_evals = fit_c_rad_phot(climate, xd0, anchor.value,
                                         idx, obs_xd)
    print("[fit] c_rad_phot = %.3e kg/J, RMSE = %.4f kg/m2 (%d evals)"
          % (c_rp, rmse, n_evals))

    # ---- gates
    gates = [
        ("c_pl_d", anchor.value, GATE_C_PL_D, abs(anchor.value - GATE_C_PL_D) <= 0.1),
        ("c_rad_phot", c_rp, GATE_C_RAD_PHOT,
         abs(c_rp / GATE_C_RAD_PHOT - 1.0) <= 0.01),
        ("rmse", rmse, GATE_RMSE, abs(rmse / GATE_RMSE - 1.0) <= 0.02),
    ]
    print("[gates]")
    for name, got, want, ok in gates:
        print("   %-12s got %.6g  want %.6g  -> %s"
              % (name, got, want, "PASS" if ok else "FAIL"))

    # ---- layer 4: result object
    sim = run_growth_series(climate, xd0, anchor.value, c_rp, idx)
    result = CalibrationResult(dataset="BJAAF Exp_c (engine skeleton)")
    result.add_param("c_pl_d", anchor.value, ParameterLabel.ANCHORED,
                     anchor.method_note)
    result.add_param("c_rad_phot", c_rp, ParameterLabel.FITTED,
                     "c_pl_d anchored + measured 5-min PAR drive; "
                     "1-param golden-section fit on log10 scale")
    result.metrics = CalibrationMetrics(rmse_kg_m2=rmse, n_samples=len(idx),
                                        window_days=window_days)
    result.anchor = anchor
    result.identifiability = report_id

    # ---- report
    all_pass = all(g[3] for g in gates)
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=REPO,
            stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        sha = "unknown"
    L = ["# 校准引擎骨架运行报告 — BJAAF Exp_c\n",
         "- 生成时间: %s  |  vfed git: %s" % (
             _dt.datetime.now().strftime("%Y-%m-%d %H:%M"), sha),
         "- 引擎: `vfed/calibration/`（骨架，规划 v0.4 §4 贯穿能力线）",
         "- 门禁 = 复现 Stage 1 手工校准（%s）" % (
             "全部 PASS" if all_pass else "存在 FAIL"),
         "",
         "## 门禁\n",
         "| 参数 | 引擎值 | Stage 1 值 | 判定 |", "|---|---|---|---|"]
    for name, got, want, ok in gates:
        L.append("| %s | %.6g | %.6g | %s |" % (name, got, want,
                                                "PASS" if ok else "FAIL"))
    L += ["\n## 逐点 X_d [kg/m²]\n",
          "| 日期 | 实测 | 引擎 1-state |", "|---|---|---|"]
    for d, o, s in zip(gro_w["date"].dt.strftime("%m-%d"), obs_xd, sim):
        L.append("| %s | %.5f | %.5f |" % (d, o, s))
    L += ["\n---\n", result.to_markdown(),
          "\n## 复现\n\n```bash\n"
          "python scripts/benchmarks/bjaaf_growth/run_engine_skeleton.py\n```\n"]
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print("[report] written %s" % REPORT)
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
