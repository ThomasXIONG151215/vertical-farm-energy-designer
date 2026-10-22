# -*- coding: utf-8 -*-
"""Night CO2 analysis for BJAAF lettuce greenhouse (T5 respiration R1-R3).

Question
--------
Can night-time CO2 slopes in the BJAAF greenhouses constrain crop
maintenance respiration (R_d) the way a sealed PFAL would?

Method
------
1. Segment nights: rad <= 0 continuous runs >= 3 h.
2. Linear fit CO2 vs time per segment -> slope ppm/h, R^2, mean T.
3. Predict crop-only slope with the 3-state R_d form (Van Henten school,
   author frozen coefficients) using season-interpolated X_d:
       R_d = (c_Rd_25_s*(1-sigmar) + c_Rd_25_r*sigmar) * X_d * Q10^((T-25)/10)
       ppm/h = R_d * DM_TO_CO2 / (h_air * rho_mol_air) * 3600 * 1e6
   with assumed greenhouse air height h_air (4 m base case, 3-5 m
   sensitivity), rho_mol from ideal gas at segment T.
4. soil_residual = observed slope - predicted crop slope (lumped:
   soil/media + unknown leak).

Outputs
-------
- console summary + per-experiment tables
- markdown report -> user-gym/benchmarks/respiration_night_co2_report.md

Assumptions are logged in the report; no PASS/FAIL gate (diagnostic).

Sources: data/datasets/bjaaf-lettuce-growth/ (Mendeley r7z9ttvkyh v2,
CC BY 4.0). Climate sheet 5-min; growth summary per ~5 days.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[3]
BENCH = REPO / "user-gym" / "benchmarks"
BASE = REPO / "data" / "datasets" / "bjaaf-lettuce-growth"

EXPS = {
    "Exp_c": {
        "climate": BASE / "Greenhouse Climate & Crop data_Exp_c.xlsx",
        "rho_c": 11.31,
        "season": "winter 2020-11/2021-01 (calibration)",
    },
    "Exp_v1": {
        "climate": BASE / "Greenhouse Climate & Crop data_Exp_v1.xlsx",
        "rho_c": 11.71,
        "season": "spring 2020-04/05 (holdout)",
    },
    "Exp_v2": {
        "climate": BASE / "Lettuce growth model program" / "Greenhouse Climate & Crop data_Exp_v2.xlsx",
        "rho_c": 11.52,
        "season": "winter 2022-01/03 (holdout)",
    },
}

# 3-state respiration block, author frozen values (run_calibration.py LR/RD/SR)
RD25_S = 3.47e-7  # 1/s, shoot maintenance at 25 C
RD25_R = 1.16e-7  # 1/s, root maintenance at 25 C
Q10_RD = 2.0
SIGMAR_1 = -0.026
SIGMAR_2 = -0.076

DM_TO_CO2 = 44.01 / 30.03  # kg CO2 per kg dry matter (glucose polymer)
R_GAS = 8.314  # J/(mol K)
P_ATM = 101325.0  # Pa
M_CO2 = 44.01e-3  # kg/mol

H_AIR = 4.0  # m, assumed mean greenhouse air height (base case)
H_SENS = (3.0, 5.0)  # m, sensitivity band
MIN_HOURS = 3.0
R2_GOOD = 0.9


def load_exp(path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    clim = pd.read_excel(path, sheet_name="Greenhouse climate", usecols=[0, 1, 2, 3, 4])
    clim.columns = ["time", "co2", "temp", "rh", "rad"]
    clim["time"] = pd.to_datetime(clim["time"])
    clim = clim.dropna(subset=["time", "co2"]).reset_index(drop=True)
    gro = pd.read_excel(path, sheet_name="Lettuce growth summary")
    gro = gro.rename(columns={"Time": "date", "Xd [kg m-2]": "xd", "LAI [-]": "lai"})
    gro = gro[["date", "xd", "lai"]].dropna()
    gro["date"] = pd.to_datetime(gro["date"])
    gro = gro.sort_values("date").reset_index(drop=True)
    return clim, gro


def xd_at(gro: pd.DataFrame, when: pd.Timestamp) -> float:
    """Linear interpolation of measured X_d at night midpoint."""
    t = when
    if t <= gro["date"].iloc[0]:
        return float(gro["xd"].iloc[0])
    if t >= gro["date"].iloc[-1]:
        return float(gro["xd"].iloc[-1])
    secs = (gro["date"] - t).dt.total_seconds()
    i = int(np.argmax(secs.to_numpy() > 0))  # first sample after t
    d0, d1 = gro["date"].iloc[i - 1], gro["date"].iloc[i]
    x0, x1 = float(gro["xd"].iloc[i - 1]), float(gro["xd"].iloc[i])
    frac = (t - d0).total_seconds() / max((d1 - d0).total_seconds(), 1.0)
    return x0 + frac * (x1 - x0)


def crop_slope_ppm_h(x_d: float, temp_c: float, rho_c: float, h_air: float) -> float:
    """3-state R_d form -> ppm CO2 per hour for the whole canopy."""
    x_d = max(x_d, 1e-9)
    sigmar = SIGMAR_1 * np.log(x_d / rho_c) + SIGMAR_2
    r_d = (RD25_S * (1.0 - sigmar) + RD25_R * sigmar) * x_d * Q10_RD ** ((temp_c - 25.0) / 10.0)
    kg_co2_m2_s = r_d * DM_TO_CO2
    t_k = temp_c + 273.15
    mol_per_m3 = P_ATM / (R_GAS * t_k)
    ppm_per_h = kg_co2_m2_s / M_CO2 / h_air / mol_per_m3 * 1e6 * 3600.0
    return float(ppm_per_h)


def night_segments(clim: pd.DataFrame, gro: pd.DataFrame, rho_c: float) -> pd.DataFrame:
    night = (clim["rad"] <= 0.0).to_numpy()
    rows = []
    i, n = 0, len(clim)
    while i < n:
        if not night[i]:
            i += 1
            continue
        j = i
        while j < n and night[j]:
            j += 1
        seg = clim.iloc[i:j]
        hours = (seg["time"].iloc[-1] - seg["time"].iloc[0]).total_seconds() / 3600.0
        if hours >= MIN_HOURS and len(seg) >= 10:
            t_h = (seg["time"] - seg["time"].iloc[0]).dt.total_seconds() / 3600.0
            t_h = t_h.reset_index(drop=True)
            co2 = seg["co2"].to_numpy(dtype=float)
            ok = np.isfinite(co2)
            if ok.sum() >= 10 and (float(t_h[ok].max()) - float(t_h[ok].min())) > 0:
                slope, intercept = np.polyfit(t_h[ok], co2[ok], 1)
                pred = slope * t_h[ok] + intercept
                ss_res = float(((co2[ok] - pred) ** 2).sum())
                ss_tot = float(((co2[ok] - co2[ok].mean()) ** 2).sum())
                r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan
                mid = seg["time"].iloc[0] + pd.Timedelta(hours=hours / 2.0)
                temp_c = float(seg["temp"].astype(float).mean())
                x_d = xd_at(gro, mid)
                pred_h4 = crop_slope_ppm_h(x_d, temp_c, rho_c, H_AIR)
                rows.append(
                    {
                        "start": seg["time"].iloc[0],
                        "hours": hours,
                        "slope_ppm_h": float(slope),
                        "r2": float(r2),
                        "temp_c": temp_c,
                        "xd_kg_m2": x_d,
                        "pred_crop_h4": pred_h4,
                        "soil_resid_h4": float(slope) - pred_h4,
                        "co2_start": float(co2[ok][0]),
                        "co2_end": float(co2[ok][-1]),
                    }
                )
        i = j
    return pd.DataFrame(rows)


def q(s: pd.Series) -> str:
    return "%.1f / %.1f / %.1f" % (s.quantile(0.1), s.median(), s.quantile(0.9))


def analyse(name: str, cfg: dict) -> tuple[pd.DataFrame, dict]:
    clim, gro = load_exp(Path(cfg["climate"]))
    seg = night_segments(clim, gro, cfg["rho_c"])
    good = seg[seg["r2"] > R2_GOOD]
    late = seg.tail(10)
    early = seg.head(10)
    stats = {
        "rows": len(clim),
        "nights": len(seg),
        "slope_q": q(seg["slope_ppm_h"]),
        "pred_q": q(seg["pred_crop_h4"]),
        "resid_q": q(seg["soil_resid_h4"]),
        "n_good": len(good),
        "good_slope": q(good["slope_ppm_h"]) if len(good) else "-",
        "early_slope": q(early["slope_ppm_h"]),
        "early_pred": q(early["pred_crop_h4"]),
        "late_slope": q(late["slope_ppm_h"]),
        "late_pred": q(late["pred_crop_h4"]),
        "late_xd": "%.3f" % late["xd_kg_m2"].median(),
        "temp_mean": "%.1f" % seg["temp_c"].mean(),
    }
    return seg, stats


def render(name: str, cfg: dict, seg: pd.DataFrame, stats: dict) -> str:
    lines = []
    lines.append("### %s — %s" % (name, cfg["season"]))
    lines.append("")
    lines.append("- climate rows: %d; night segments (>= %.0f h): %d" % (stats["rows"], MIN_HOURS, stats["nights"]))
    lines.append("- observed slope ppm/h p10/med/p90: %s; night mean T: %s C" % (stats["slope_q"], stats["temp_mean"]))
    lines.append("- crop-only predicted ppm/h (h=%.0f m): %s" % (H_AIR, stats["pred_q"]))
    lines.append("- residual (obs - crop): %s -> lumped soil/media + leak" % stats["resid_q"])
    lines.append("- linear-fit R^2 > %.1f segments: %d%s" % (R2_GOOD, stats["n_good"], (" (%s)" % stats["good_slope"]) if stats["n_good"] else ""))
    lines.append("- early season (first 10 nights): obs %s vs crop %s" % (stats["early_slope"], stats["early_pred"]))
    lines.append("- late season (last 10 nights): obs %s vs crop %s (median X_d %s kg/m2)" % (stats["late_slope"], stats["late_pred"], stats["late_xd"]))
    lines.append("")
    cols = ["start", "hours", "slope_ppm_h", "r2", "temp_c", "xd_kg_m2", "pred_crop_h4", "soil_resid_h4"]
    lines.append(seg[cols].head(5).to_markdown(index=False, floatfmt=".3f"))
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    all_stats = {}
    parts = []
    for name, cfg in EXPS.items():
        seg, stats = analyse(name, cfg)
        all_stats[name] = stats
        parts.append(render(name, cfg, seg, stats))
        print(name, "->", stats["slope_q"], "pred", stats["pred_q"], "good", stats["n_good"])

    tot = sum(s["nights"] for s in all_stats.values())
    tot_good = sum(s["n_good"] for s in all_stats.values())
    report = []
    report.append("# Night CO2 vs crop respiration — BJAAF greenhouse check")
    report.append("")
    report.append("- date: 2026-10-22; task: T5 respiration R1-R3 (planning v0.5)")
    report.append("- question: do night CO2 slopes constrain maintenance respiration R_d?")
    report.append("- method: rad<=0 segments >= %.0f h; linear slope; 3-state R_d prediction;" % MIN_HOURS)
    report.append("  DM_TO_CO2=%.3f; assumed air height %.0f m (sensitivity %.0f-%.0f m scales ppm/h by 1/h)." % (DM_TO_CO2, H_AIR, H_SENS[0], H_SENS[1]))
    report.append("- combined: %d night segments, %d with R^2>%.1f" % (tot, tot_good, R2_GOOD))
    report.append("")
    report.extend(parts)
    report.append("## Reading")
    report.append("")
    report.append("- observed medians (3-5 ppm/h) are order-consistent with crop R_d only at high X_d;")
    report.append("  early-season nights (small canopy) show slopes far above crop prediction -> soil/media + heater CO2 dominate.")
    report.append("- per-night linearity is poor (vent actuation + wind leak). Greenhouse night CO2 is a mixed")
    report.append("  signal: crop resp + soil resp + leakage. Without a bare-ground baseline it is degenerate for")
    report.append("  crop R_d alone.")
    report.append("- AGC 2018 (local, unzipped check): columns CO2air/VentLee/Ventwind/EnScr/AssimLight present ->")
    report.append("  leak correction possible in principle; cucumber crop (cross-species), substrate culture likely.")
    report.append("")
    report.append("## Identifiability verdict (R2)")
    report.append("")
    report.append("- PFAL (sealed, no soil): night slope -> resp coefficient identifiable in principle (M1 CO2 target).")
    report.append("- greenhouse data: DEGENERATE for crop-only R_d without soil/leak model; usable as method test only.")
    report.append("- action: respiration separation stays in the upgrade pipeline; parameter source remains")
    report.append("  TRANSFERRED (author frozen Rd25) until PFAL CO2 data exists (609 has no CO2 sensor).")
    report.append("")
    BENCH.mkdir(parents=True, exist_ok=True)
    out = BENCH / "respiration_night_co2_report.md"
    out.write_text("\n".join(report), encoding="utf-8")
    print("report ->", out)


if __name__ == "__main__":
    main()
