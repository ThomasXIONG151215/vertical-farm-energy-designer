#!/usr/bin/env python
"""Plot growth-model validation curves for the UC Davis and BJAAF benchmarks.

Figure 1 (uc_davis_growth_validation.png):
    UC Davis fresh weight, observed vs three simulation tracks
    (1-state C4 transfer, 3-state fit1, 3-state frozen author params),
    with a residual panel below.

Figure 2 (bjaaf_growth_validation.png):
    BJAAF dry weight X_d for Exp_c / Exp_v1 / Exp_v2, observed vs
    3-state frozen author params vs 1-state calibrated values.

Outputs PNG files to user-gym/benchmarks/plots/ (gitignored).
This is a benchmark-layer script: matplotlib is used here only.
"""
from __future__ import annotations

import os
import sys

import numpy as np

BENCH = os.path.dirname(os.path.abspath(__file__))
UCDAVIS = os.path.join(BENCH, "uc_davis")
BJAAF = os.path.join(BENCH, "bjaaf_growth")
REPO = os.path.dirname(BENCH)
for _p in (BENCH, UCDAVIS, BJAAF, REPO):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from run_biomass import DRY_FRAC, RHO_MAIN, load_observed
from run_biomass_stage2 import C_PLD_BJAAF, XD0_MEASURED, proxy_trajectory
import run_calibration as rc
from run_calibration import run_reference
from run_structure_diagnosis import (
    C_RAD_TRANSFER,
    fit_epsilon,
    proxy_climate,
    sample_times,
    to_fw,
)
from run_validation import C_PL_D, C_RAD_PHOT, load_exp, run_vfed_samples

OUT_DIR = os.path.join(REPO, "user-gym", "benchmarks", "plots")
T_LIGHT, T_DARK = 24.5, 18.5
LAI0_UCD = 0.32  # middle of the 0.24/0.32/0.40 sensitivity grid

DATASET_DIR = os.path.join(REPO, "data", "datasets", "bjaaf-lettuce-growth")
BJAAF_EXPS = [
    ("Exp_c", os.path.join(DATASET_DIR, "Greenhouse Climate & Crop data_Exp_c.xlsx"),
     "calibration"),
    ("Exp_v1", os.path.join(DATASET_DIR, "Greenhouse Climate & Crop data_Exp_v1.xlsx"),
     "holdout, spring"),
    ("Exp_v2", os.path.join(DATASET_DIR, "Lettuce growth model program",
                            "Greenhouse Climate & Crop data_Exp_v2.xlsx"),
     "holdout, winter"),
]


def rmse(sim, obs) -> float:
    d = np.asarray(sim, dtype=float) - np.asarray(obs, dtype=float)
    return float(np.sqrt(np.mean(d ** 2)))


def plot_uc_davis() -> dict:
    obs = load_observed()
    obs = obs[obs["Date"] >= "2024-02-22"].sort_values("DAT")
    dats = obs["DAT"].to_numpy(dtype=int)
    obs_fw = obs["mean"].to_numpy(dtype=float)
    obs_std = obs["std"].to_numpy(dtype=float)

    # 1-state C4 full transfer (BJAAF-calibrated c_pl_d / X_d0 / c_rad_phot).
    fw1 = proxy_trajectory(C_PLD_BJAAF, XD0_MEASURED, C_RAD_TRANSFER, T_LIGHT, T_DARK)
    sim_1s = fw1[dats - 1]

    # 3-state tracks under the same proxy climate.
    clim = proxy_climate(T_LIGHT, T_DARK)
    st = sample_times(clim, dats)
    x0 = [XD0_MEASURED, 0.0, LAI0_UCD]

    # fit1: free epsilon_0 only (same single-parameter freedom as 1-state).
    eps_fit, _ = fit_epsilon(clim, x0, obs_fw, st)
    orig_eps = rc.PLR["epsilon_0"]
    try:
        rc.PLR["epsilon_0"] = eps_fit
        xd_fit, _ = run_reference(clim, x0, st, RHO_MAIN)
    finally:
        rc.PLR["epsilon_0"] = orig_eps
    sim_3s_fit = to_fw(xd_fit, DRY_FRAC)

    # frozen: author greenhouse parameters, zero local calibration.
    xd_frz, _ = run_reference(clim, x0, st, RHO_MAIN)
    sim_3s_frz = to_fw(xd_frz, DRY_FRAC)

    r_1s = rmse(sim_1s, obs_fw)
    r_fit = rmse(sim_3s_fit, obs_fw)
    r_frz = rmse(sim_3s_frz, obs_fw)

    fig, (ax, axr) = plt.subplots(
        2, 1, figsize=(10, 7), sharex=True,
        gridspec_kw={"height_ratios": [2.2, 1.0]},
    )
    ax.errorbar(
        dats, obs_fw, yerr=obs_std, fmt="o", ms=4, color="black",
        ecolor="0.65", capsize=2, label="Observed (18 plants/day)", zorder=5,
    )
    ax.plot(dats, sim_1s, color="#1f77b4", lw=1.6,
            label=f"1-state C4 transfer (RMSE {r_1s:.1f} g, final {sim_1s[-1]:.0f} g)")
    ax.plot(dats, sim_3s_fit, color="#d62728", lw=1.6,
            label=f"3-state fit1 (RMSE {r_fit:.1f} g, final {sim_3s_fit[-1]:.0f} g)")
    ax.plot(dats, sim_3s_frz, color="0.45", lw=1.3, ls="--",
            label=f"3-state frozen (RMSE {r_frz:.1f} g, final {sim_3s_frz[-1]:.0f} g)")
    ax.set_ylabel("Fresh weight per plant (g)")
    ax.set_title("UC Davis fresh weight — 30-day cycle, proxy climate "
                 f"(PPFD 250, 14 h photoperiod, CO$_2$ 800 ppm)")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8.5, loc="upper left")

    axr.axhline(0.0, color="0.3", lw=0.8)
    axr.plot(dats, sim_1s - obs_fw, color="#1f77b4", lw=1.3, marker=".", ms=4,
             label="1-state C4")
    axr.plot(dats, sim_3s_fit - obs_fw, color="#d62728", lw=1.3, marker=".", ms=4,
             label="3-state fit1")
    axr.plot(dats, sim_3s_frz - obs_fw, color="0.45", lw=1.1, ls="--",
             label="3-state frozen")
    axr.set_xlabel("Days after transplant (DAT)")
    axr.set_ylabel("Residual (g)")
    axr.grid(alpha=0.3)
    axr.legend(fontsize=8.5, loc="upper left")

    fig.tight_layout()
    path = os.path.join(OUT_DIR, "uc_davis_growth_validation.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)

    return {
        "rmse_1s": r_1s, "rmse_3s_fit": r_fit, "rmse_3s_frozen": r_frz,
        "final_1s": float(sim_1s[-1]), "final_3s_fit": float(sim_3s_fit[-1]),
        "final_3s_frozen": float(sim_3s_frz[-1]),
        "final_obs": float(obs_fw[-1]), "eps_fit": eps_fit,
    }


def plot_bjaaf() -> dict:
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.5))
    out = {}
    for ax, (name, path, tag) in zip(axes, BJAAF_EXPS):
        clim, gro = load_exp(path)
        rho_c = float(np.mean(gro["xd"] * 1e3 / gro["tdw"]))
        t0 = clim["time"].iloc[0]
        pre = gro[gro["date"] <= t0]
        x0row = pre.iloc[-1]
        xd0 = float(x0row["xd"])
        lai0 = float(x0row["lai"])
        post = gro[gro["date"] > t0]
        sts = list(post["date"])
        obs_xd = post["xd"].to_numpy(dtype=float)
        days = (post["date"] - x0row["date"]).dt.total_seconds().to_numpy() / 86400.0

        # 3-state with author frozen parameters (zero local calibration).
        xd3, _ = run_reference(clim, [xd0, 0.0, lai0], sts, rho_c)
        # 1-state with values calibrated on Exp_c only.
        xd1 = run_vfed_samples(clim, xd0, C_PL_D, C_RAD_PHOT, sts)

        r3 = rmse(xd3, obs_xd)
        r1 = rmse(xd1, obs_xd)
        out[name] = {"rmse_3s_frozen": r3, "rmse_1s_cal": r1,
                     "final_obs": float(obs_xd[-1]),
                     "final_3s": float(xd3[-1]), "final_1s": float(xd1[-1])}

        ax.plot(days, obs_xd, "o", ms=4, color="black", label="Observed", zorder=5)
        ax.plot(days, xd3, color="#d62728", lw=1.6,
                label=f"3-state frozen (RMSE {r3:.4f})")
        ax.plot(days, xd1, color="#1f77b4", lw=1.6,
                label=f"1-state calibrated (RMSE {r1:.4f})")
        ax.set_title(f"{name} ({tag})")
        ax.set_xlabel("Days since initial sample")
        ax.set_ylabel("Dry weight X$_d$ (kg/m$^2$)")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8)
    fig.tight_layout()
    path = os.path.join(OUT_DIR, "bjaaf_growth_validation.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return out


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    ucd = plot_uc_davis()
    print("[UC Davis]")
    print(f"  1-state C4      RMSE {ucd['rmse_1s']:7.2f} g   final {ucd['final_1s']:6.1f} g")
    print(f"  3-state fit1    RMSE {ucd['rmse_3s_fit']:7.2f} g   final {ucd['final_3s_fit']:6.1f} g"
          f"   (epsilon_0 = {ucd['eps_fit']:.3e})")
    print(f"  3-state frozen  RMSE {ucd['rmse_3s_frozen']:7.2f} g   final {ucd['final_3s_frozen']:6.1f} g")
    print(f"  observed        final {ucd['final_obs']:6.1f} g")
    print(f"  -> {os.path.join(OUT_DIR, 'uc_davis_growth_validation.png')}")

    bj = plot_bjaaf()
    print("[BJAAF dry weight, kg/m^2]")
    for name, v in bj.items():
        print(f"  {name}: 3S frozen RMSE {v['rmse_3s_frozen']:.4f} (final {v['final_3s']:.4f})"
              f" | 1S calibrated RMSE {v['rmse_1s_cal']:.4f} (final {v['final_1s']:.4f})"
              f" | observed final {v['final_obs']:.4f}")
    print(f"  -> {os.path.join(OUT_DIR, 'bjaaf_growth_validation.png')}")


if __name__ == "__main__":
    main()
