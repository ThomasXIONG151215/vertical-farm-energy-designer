#!/usr/bin/env python
"""VFED vs EnergyPlus hourly-parity case study (ordinary building).

BESTEST Cases 600 / 900 (thermostat 20/27 C) + 600FF / 900FF (free float),
Denver TMY3, EnergyPlus 23.1 hourly reference (out*/eplusout.csv, ASHRAE
140-2020 annual bands 14/14 PASS -> qualified tier-3 reference).

Phases (one process per --case may run in parallel):
  scan      -- targeted candidate grid (mod_band / ua / eta / cz), objective
               = hourly parity score; appends rows to parity_scan_<case>.json
  finalize  -- re-run the frozen PARITY set, save series npz + metrics +
               ASHRAE 140 annual-band re-verification
  charts    -- transparent-background PNG panels from the npz
  report    -- write the Chinese intro MD from metrics + params

Artifacts land in ./parity_case/ (sub-folder of this script's directory).

Alignment (same convention as probe_vs_eplus.py): E+ hour-ending row h is
compared against vfed dual-year year-2 hour h, both 8760 rows.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
BESTEST = HERE.parent
BENCH = BESTEST.parent
REPO = BENCH.parent
for _p in (str(REPO), str(BESTEST), str(BENCH)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import bestest_lib as lib            # noqa: E402
from _common import metrics          # noqa: E402
from probe_vs_eplus import load_eplus  # noqa: E402

OUT = HERE / "parity_case"
EPW = BESTEST / "USA_CO_Denver.Intl.AP.725650_TMY3.epw"
CASES = ["600", "900", "600FF", "900FF"]

# case-override short name -> run_case kwarg
KW = {"cz": "cz", "ua": "u_wall_a", "eta": "eta_solar", "mod_band": "mod_band",
      "abs_sol": "abs_sol", "cmass": "cmass", "gsm": "gsm", "nodes": "nodes"}

WINTER = slice(17 * 24, 25 * 24)     # Jan 18 00:00 .. Jan 25 00:00
SUMMER = slice(196 * 24, 204 * 24)   # Jul 15 00:00 .. Jul 23 00:00

MONTH_DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
MONTHS = np.zeros(8760, dtype=int)
_i = 0
for _m, _d in enumerate(MONTH_DAYS):
    MONTHS[_i:_i + _d * 24] = _m
    _i += _d * 24

# Frozen parity parameter sets (overrides over INITIAL_FD).  Wave-1/2/3/4
# scan evidence: parity_case/parity_scan_<case>.json + pick_best.py ranking.
#   600 / 600FF : family-unified {ua 48, eta 0.76} -- 600 heat +1.1 % cool
#                 +0.4 %, 600FF t_z RMSE 1.552 (baseline 1.563, unified).
#   900         : {ua 43, abs_sol 0.25, cmass 3000} -- heat -0.3 % cool +3.2 %.
#   900FF       : {ua 43, cz 200} -- t_z RMSE 1.251 (baseline 1.794).  The
#                 900 family set on 900FF degrades to 1.905, so the FF
#                 sibling is calibrated per-case (disclosed in the report).
PARITY: Dict[str, Dict[str, float]] = {
    "600": {"ua": 48.0, "eta": 0.76},
    "900": {"ua": 43.0, "abs_sol": 0.25, "cmass": 3000.0},
    "600FF": {"ua": 48.0, "eta": 0.76},
    "900FF": {"ua": 43.0, "cz": 200.0},
}

# Targeted candidate grids.  Row 0 of each list is the harness baseline
# (INITIAL_FD + mod_band 1.0), kept as the "baseline" tag row.
SCAN: Dict[str, List[Tuple[Dict[str, float], str]]] = {
    # Wave 1 evidence: mod_band is second-order (kept at default 1.0); the
    # identifying knobs are ua (night UA gap / heating zero-crossing),
    # eta_solar + abs_sol (solar absorption split) and cz (swing dynamics).
    "600": [
        ({}, "baseline"),
        ({"mod_band": 0.5}, "mb0.5"),
        ({"mod_band": 0.25}, "mb0.25"),
        ({"mod_band": 0.1}, "mb0.1"),
        ({"mod_band": 0.25, "ua": 43.0}, "mb0.25_ua43"),
        ({"ua": 48.0}, "ua48"),
        ({"ua": 47.0}, "ua47"),
        ({"ua": 45.0}, "ua45"),
        ({"eta": 0.80}, "eta080"),
        ({"eta": 0.74}, "eta074"),
        ({"cz": 100.0}, "cz100"),
        ({"cz": 120.0}, "cz120"),
        ({"abs_sol": 0.30}, "abssol030"),
        ({"abs_sol": 0.50}, "abssol050"),
        ({"ua": 48.0, "eta": 0.80}, "ua48_eta080"),
        ({"ua": 48.0, "cz": 120.0}, "ua48_cz120"),
        ({"ua": 48.0, "cz": 150.0}, "ua48_cz150"),
        ({"ua": 47.0, "cz": 120.0}, "ua47_cz120"),
        ({"ua": 48.0, "eta": 0.76}, "ua48_eta076"),
        ({"ua": 48.0, "cz": 120.0, "eta": 0.76}, "ua48_cz120_eta076"),
        ({"ua": 47.0, "eta": 0.76}, "ua47_eta076"),
        ({"ua": 48.0, "cz": 100.0}, "ua48_cz100"),
        ({"ua": 48.0, "cz": 120.0, "eta": 0.74}, "ua48_cz120_eta074"),
        ({"ua": 48.0, "cz": 120.0, "eta": 0.78}, "ua48_cz120_eta078"),
        ({"ua": 48.0, "cz": 130.0, "eta": 0.76}, "ua48_cz130_eta076"),
    ],
    "900": [
        ({}, "baseline"),
        ({"mod_band": 0.5}, "mb0.5"),
        ({"mod_band": 0.25}, "mb0.25"),
        ({"mod_band": 0.1}, "mb0.1"),
        ({"mod_band": 0.25, "ua": 43.0}, "mb0.25_ua43"),
        ({"ua": 45.0}, "ua45"),
        ({"ua": 42.0}, "ua42"),
        ({"ua": 43.0, "eta": 0.68}, "ua43_eta068"),
        ({"ua": 43.0, "eta": 0.72}, "ua43_eta072"),
        ({"ua": 43.0, "abs_sol": 0.30}, "ua43_abssol030"),
        ({"ua": 43.0, "abs_sol": 0.25}, "ua43_abssol025"),
        ({"ua": 45.0, "eta": 0.68}, "ua45_eta068"),
        ({"ua": 43.0, "eta": 0.68, "abs_sol": 0.30}, "ua43_e68_as30"),
        ({"ua": 43.0, "cz": 500.0}, "ua43_cz500"),
        ({"eta": 0.72}, "eta072"),
        ({"ua": 43.0, "eta": 0.70}, "ua43_eta070"),
        ({"ua": 43.0, "abs_sol": 0.20}, "ua43_abssol020"),
        ({"ua": 43.0, "abs_sol": 0.25, "eta": 0.72}, "ua43_as25_eta072"),
        ({"ua": 42.0, "eta": 0.72}, "ua42_eta072"),
        ({"ua": 43.0, "abs_sol": 0.25, "gsm": 400.0}, "ua43_as25_gsm400"),
        ({"ua": 43.0, "abs_sol": 0.25, "cmass": 2500.0}, "ua43_as25_cm2500"),
        ({"ua": 43.0, "abs_sol": 0.25, "cz": 500.0}, "ua43_as25_cz500"),
        ({"ua": 43.0, "eta": 0.70, "abs_sol": 0.25}, "ua43_e70_as25"),
        ({"ua": 43.0, "abs_sol": 0.25, "cmass": 2500.0, "cz": 500.0},
         "ua43_as25_cm2500_cz500"),
        ({"ua": 43.0, "abs_sol": 0.25, "cmass": 2500.0, "cz": 400.0},
         "ua43_as25_cm2500_cz400"),
        ({"ua": 43.0, "abs_sol": 0.25, "cmass": 3000.0}, "ua43_as25_cm3000"),
        ({"ua": 43.0, "abs_sol": 0.30, "cmass": 2500.0}, "ua43_as30_cm2500"),
    ],
    "600FF": [
        ({}, "baseline"),
        ({"ua": 47.0}, "ua47"),
        ({"ua": 43.0}, "ua43"),
        ({"eta": 0.74}, "eta74"),
        ({"cz": 250.0}, "cz250"),
        ({"eta": 0.80}, "eta080"),
        ({"eta": 0.79}, "eta079"),
        ({"cz": 100.0}, "cz100"),
        ({"cz": 120.0}, "cz120"),
        ({"abs_sol": 0.45}, "abssol045"),
        ({"abs_sol": 0.50}, "abssol050"),
        ({"eta": 0.80, "cz": 120.0}, "eta080_cz120"),
        ({"eta": 0.79, "abs_sol": 0.45}, "eta079_as45"),
        ({"eta": 0.82}, "eta082"),
        ({"eta": 0.82, "abs_sol": 0.45}, "eta082_as45"),
        ({"eta": 0.80, "abs_sol": 0.45}, "eta080_as45"),
        ({"eta": 0.82, "cz": 120.0}, "eta082_cz120"),
        ({"eta": 0.81}, "eta081"),
        ({"eta": 0.78, "abs_sol": 0.45}, "eta078_as45"),
        ({"eta": 0.79, "abs_sol": 0.50}, "eta079_as50"),
        ({"eta": 0.79, "abs_sol": 0.40}, "eta079_as40"),
        # Family-consistency probes: reuse the controlled-case parity set on
        # the free-float sibling (same physical building per ASHRAE 140).
        ({"ua": 48.0, "eta": 0.76}, "fam_ua48_eta076"),
        ({"ua": 48.0, "eta": 0.76, "abs_sol": 0.45}, "fam_ua48_eta076_as45"),
    ],
    "900FF": [
        ({}, "baseline"),
        ({"ua": 43.0}, "ua43"),
        ({"ua": 40.0}, "ua40"),
        ({"eta": 0.70}, "eta70"),
        ({"cz": 500.0}, "cz500"),
        ({"ua": 43.0, "cz": 500.0}, "ua43_cz500"),
        ({"ua": 43.0, "cz": 400.0}, "ua43_cz400"),
        ({"cz": 400.0}, "cz400"),
        ({"cz": 300.0}, "cz300"),
        ({"ua": 45.0, "cz": 500.0}, "ua45_cz500"),
        ({"eta": 0.75}, "eta075"),
        ({"ua": 43.0, "cz": 400.0, "eta": 0.75}, "ua43_cz400_eta075"),
        ({"ua": 43.0, "cz": 500.0, "eta": 0.75}, "ua43_cz500_eta075"),
        ({"ua": 43.0, "cz": 350.0}, "ua43_cz350"),
        ({"ua": 43.0, "cz": 300.0}, "ua43_cz300"),
        ({"ua": 43.0, "cz": 400.0, "eta": 0.71}, "ua43_cz400_eta071"),
        ({"ua": 43.0, "cz": 350.0, "eta": 0.71}, "ua43_cz350_eta071"),
        ({"ua": 43.0, "cz": 400.0, "abs_sol": 0.30}, "ua43_cz400_as30"),
        ({"ua": 43.0, "cz": 250.0}, "ua43_cz250"),
        ({"ua": 43.0, "cz": 200.0}, "ua43_cz200"),
        ({"ua": 43.0, "cz": 300.0, "eta": 0.71}, "ua43_cz300_eta071"),
        ({"ua": 43.0, "cz": 300.0, "abs_sol": 0.30}, "ua43_cz300_as30"),
        ({"ua": 43.0, "abs_sol": 0.25, "cmass": 3000.0}, "fam_ua43_as25_cm3000"),
        ({"ua": 43.0, "abs_sol": 0.25, "cmass": 3000.0, "cz": 400.0},
         "fam_ua43_as25_cm3000_cz400"),
    ],
}


def weather() -> pd.DataFrame:
    return lib.load_epw(str(EPW))


def run_vfed(case: str, df: pd.DataFrame, overrides: Optional[dict] = None,
             want_summary: bool = False) -> dict:
    hourly: Dict[str, np.ndarray] = {}
    kw: dict = {"fd": True, "hourly_out": hourly}
    summary: dict = {}
    if want_summary:
        kw["summary_out"] = summary
    for k, v in (overrides or {}).items():
        kw[KW[k]] = v
    t0 = time.perf_counter()
    res = lib.run_case(case, df, **kw)
    out = {
        "case": case,
        "wall_s": time.perf_counter() - t0,
        "t_z": np.asarray(hourly["t_z"], dtype=float),
        "heat_kwh": np.asarray(hourly["heat_kwh"], dtype=float),
        "cool_kwh": np.asarray(hourly["cool_kwh"], dtype=float),
        "rh_z": np.asarray(hourly.get("rh_z", np.zeros(len(hourly["t_z"]))),
                           dtype=float),
    }
    if want_summary:
        out["res"] = res
        out["summary"] = summary
    return out


def compare(case: str, v: dict, ep: dict) -> Dict[str, dict]:
    rows: Dict[str, dict] = {}
    for ch in ("t_z", "heat_kwh", "cool_kwh"):
        if ch not in ep:
            continue
        m = metrics(v[ch], ep[ch])
        sv = float(np.sum(v[ch]))
        se = float(np.sum(ep[ch]))
        sst = float(np.sum((ep[ch] - ep[ch].mean()) ** 2))
        r2 = 1.0 - float(np.sum((v[ch] - ep[ch]) ** 2)) / max(sst, 1e-12)
        rows[ch] = {
            "rmse": m["rmse"], "mbe": m["mbe"], "p95abs": m["p95abs"],
            "r2": r2, "sum_v": sv, "sum_e": se,
            "diff_pct": (sv - se) / se * 100.0 if se else float("nan"),
        }
    return rows


def score(case: str, rows: Dict[str, dict]) -> float:
    s = rows["t_z"]["rmse"]
    if "heat_kwh" in rows:
        s += 0.5 * (abs(rows["heat_kwh"]["diff_pct"])
                    + abs(rows["cool_kwh"]["diff_pct"]))
    return s


def scan_file(case: str) -> Path:
    return OUT / f"parity_scan_{case}.json"


def append_row(case: str, tag: str, overrides: dict, rows: Dict[str, dict],
               wall_s: float) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    path = scan_file(case)
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    data.append({"tag": tag, "overrides": overrides, "wall_s": wall_s,
                 "rows": rows, "score": score(case, rows)})
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                    encoding="utf-8")


def phase_scan(cases: List[str]) -> None:
    df = weather()
    print(f"[weather] {len(df)} rows", flush=True)
    for case in cases:
        done = set()
        if scan_file(case).exists():
            done = {r["tag"] for r in json.loads(
                scan_file(case).read_text(encoding="utf-8"))}
        for overrides, tag in SCAN[case]:
            if tag in done:
                print(f"[skip] {case} {tag} (cached)", flush=True)
                continue
            v = run_vfed(case, df, overrides)
            ep = load_eplus(case)
            rows = compare(case, v, ep)
            append_row(case, tag, overrides, rows, v["wall_s"])
            line = " | ".join(
                f"{ch} RMSE {r['rmse']:.3f} dPct {r['diff_pct']:+.1f}"
                for ch, r in rows.items())
            print(f"[scan] {case} {tag:16s} ({v['wall_s']:.0f}s) {line}",
                  flush=True)


def band_verdicts(case: str, res) -> Dict[str, dict]:
    out = {}
    for key, val in lib.case_metrics(res).items():
        band = lib.REF[case][key]
        out[key] = {"value": val, "band": list(band),
                    "verdict": lib.verdict(val, band)}
    return out


def phase_finalize(cases: List[str]) -> None:
    df = weather()
    params = {"cases": {}, "git_sha": _git_sha()}
    report: Dict[str, dict] = {}
    for case in cases:
        ov = PARITY[case]
        if not ov:
            print(f"[finalize] {case}: PARITY entry empty -- fill it after "
                  f"the scan first", flush=True)
            continue
        v = run_vfed(case, df, ov, want_summary=True)
        ep = load_eplus(case)
        rows = compare(case, v, ep)
        verdicts = band_verdicts(case, v["res"])
        npz = OUT / f"series_{case}.npz"
        np.savez_compressed(
            npz,
            t_z_v=v["t_z"], heat_v=v["heat_kwh"], cool_v=v["cool_kwh"],
            rh_z_v=v["rh_z"],
            t_z_e=np.asarray(ep["t_z"], float),
            heat_e=np.asarray(ep.get("heat_kwh", np.zeros(8760)), float),
            cool_e=np.asarray(ep.get("cool_kwh", np.zeros(8760)), float),
            rh_z_e=np.asarray(ep.get("rh_z", np.zeros(8760)), float),
        )
        params["cases"][case] = {"overrides": ov, "wall_s": v["wall_s"],
                                 "verdicts_140": verdicts}
        report[case] = {"overrides": ov, "rows": rows,
                        "verdicts_140": verdicts, "wall_s": v["wall_s"]}
        line = " | ".join(f"{ch} RMSE {r['rmse']:.3f} dPct {r['diff_pct']:+.1f}"
                          for ch, r in rows.items())
        print(f"[finalize] {case} ({v['wall_s']:.0f}s) {line}", flush=True)
    (OUT / "parity_params.json").write_text(
        json.dumps(params, indent=2, ensure_ascii=False), encoding="utf-8")
    (OUT / "parity_metrics.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


def _git_sha() -> str:
    import subprocess
    return subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                          capture_output=True, text=True,
                          cwd=REPO).stdout.strip()


# ---------------------------------------------------------------------------
# Charts (transparent background)
# ---------------------------------------------------------------------------
C_V = "#0b5fa5"   # vfed line color (dark blue, readable on light backgrounds)
C_E = "#c62828"   # EnergyPlus line color (dark red)
C_GRID = "#888888"

# Chart font sizes (user request: "字体还是太小" -- bumped from the 10/9/8
# defaults to a presentation-scale set; shared by every figure here).
FS_TITLE = 18      # subplot titles
FS_SCAT_TITLE = 16  # scatter titles (two-line, tighter panels)
FS_LABEL = 16      # axis labels
FS_TICK = 15       # tick labels
FS_LEGEND = 15     # legends
FS_ANNOT = 17      # in-plot annotations (R²)
FS_SUPTITLE = 22


def _setup_mpl():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({
        "font.sans-serif": ["Microsoft YaHei", "SimHei", "DengXian",
                            "DejaVu Sans"],
        "axes.unicode_minus": False,
        "figure.facecolor": "none",
        "axes.facecolor": "none",
        "savefig.facecolor": "none",
        "savefig.transparent": True,
        "axes.edgecolor": "#444444",
        "axes.labelcolor": "#222222",
        "xtick.color": "#444444",
        "ytick.color": "#444444",
        "text.color": "#222222",
    })
    return plt


def _plot_overlay(ax, v, e, lw, title, ylabel, xlab=None, x=None):
    plt = _setup_mpl()
    x = np.arange(len(v)) if x is None else x
    ax.plot(x, v, lw=lw, color=C_V, label="VFED")
    ax.plot(x, e, lw=lw, color=C_E, ls="--", label="EnergyPlus")
    ax.set_title(title, fontsize=FS_TITLE)
    ax.set_ylabel(ylabel, fontsize=FS_LABEL)
    if xlab:
        ax.set_xlabel(xlab, fontsize=FS_LABEL)
    ax.tick_params(labelsize=FS_TICK)
    ax.grid(alpha=0.3, color=C_GRID, lw=0.4)
    ax.legend(fontsize=FS_LEGEND, framealpha=0.0)


def _plot_scatter(ax, v, e, title, xlabel, ylabel):
    plt = _setup_mpl()
    ax.scatter(e, v, s=2, alpha=0.25, color=C_V, edgecolors="none")
    lims = [min(e.min(), v.min()), max(e.max(), v.max())]
    ax.plot(lims, lims, color="#333333", lw=0.8, ls=":")
    m = metrics(v, e)
    sst = float(np.sum((e - e.mean()) ** 2))
    r2 = 1.0 - float(np.sum((v - e) ** 2)) / max(sst, 1e-12)
    ax.set_title(f"{title}\nRMSE {m['rmse']:.3f}  R² {r2:.4f}",
                 fontsize=FS_SCAT_TITLE)
    ax.set_xlabel(f"EnergyPlus {xlabel}", fontsize=FS_LABEL)
    ax.set_ylabel(f"VFED {ylabel}", fontsize=FS_LABEL)
    ax.tick_params(labelsize=FS_TICK)
    ax.grid(alpha=0.3, color=C_GRID, lw=0.4)


def _fmt_day_axis(ax, n_hours, start_label):
    ticks = np.arange(0, n_hours + 1, 24)
    ax.set_xticks(ticks)
    ax.set_xticklabels([str(t // 24) for t in ticks], fontsize=FS_TICK)
    ax.set_xlabel(f"{start_label}（天）", fontsize=FS_LABEL)


def fig_controlled(case: str) -> None:
    plt = _setup_mpl()
    z = np.load(OUT / f"series_{case}.npz")
    tv, ev = z["t_z_v"], z["t_z_e"]
    hv, he = z["heat_v"], z["heat_e"]
    cv, ce = z["cool_v"], z["cool_e"]
    fig, axs = plt.subplots(3, 3, figsize=(16.5, 10.5))
    days = np.arange(8760) / 24.0
    _plot_overlay(axs[0, 0], tv, ev, 0.5,
                  f"案例 {case}：全年逐时室温", "室温 (°C)", "天", days)
    _plot_overlay(axs[0, 1], tv[WINTER], ev[WINTER], 1.2,
                  "冬季周室温（1 月 18–24 日）", "室温 (°C)")
    _fmt_day_axis(axs[0, 1], WINTER.stop - WINTER.start, "1 月 18 日 0 时起")
    _plot_overlay(axs[0, 2], tv[SUMMER], ev[SUMMER], 1.2,
                  "夏季周室温（7 月 15–22 日）", "室温 (°C)")
    _fmt_day_axis(axs[0, 2], SUMMER.stop - SUMMER.start, "7 月 15 日 0 时起")
    _plot_overlay(axs[1, 0], hv[WINTER], he[WINTER], 1.2,
                  "冬季周逐时供热（kWh）", "供热 (kWh/h)")
    _fmt_day_axis(axs[1, 0], WINTER.stop - WINTER.start, "1 月 18 日 0 时起")
    _plot_overlay(axs[1, 1], cv[SUMMER], ce[SUMMER], 1.2,
                  "夏季周逐时供冷（kWh）", "供冷 (kWh/h)")
    _fmt_day_axis(axs[1, 1], SUMMER.stop - SUMMER.start, "7 月 15 日 0 时起")
    _plot_scatter(axs[1, 2], tv, ev, "全年室温散点", "室温 (°C)", "室温 (°C)")
    _plot_scatter(axs[2, 0], hv, he, "全年逐时供热散点", "供热 (kWh)",
                  "供热 (kWh)")
    _plot_scatter(axs[2, 1], cv, ce, "全年逐时供冷散点", "供冷 (kWh)",
                  "供冷 (kWh)")
    ax = axs[2, 2]
    x = np.arange(12)
    w = 0.2
    ax.bar(x - 1.5 * w, [he[MONTHS == m].sum() for m in x], w,
           color=C_E, alpha=0.75, label="EnergyPlus 供热")
    ax.bar(x - 0.5 * w, [hv[MONTHS == m].sum() for m in x], w,
           color=C_V, alpha=0.75, label="VFED 供热")
    ax.bar(x + 0.5 * w, [ce[MONTHS == m].sum() for m in x], w,
           color=C_E, alpha=0.45, hatch="//", label="EnergyPlus 供冷")
    ax.bar(x + 1.5 * w, [cv[MONTHS == m].sum() for m in x], w,
           color=C_V, alpha=0.45, hatch="//", label="VFED 供冷")
    ax.set_xticks(x)
    ax.set_xticklabels([str(m + 1) for m in x], fontsize=FS_TICK)
    ax.set_title("月度供热量 / 供冷量 (kWh)", fontsize=FS_SCAT_TITLE)
    ax.set_xlabel("月", fontsize=FS_LABEL)
    ax.set_ylabel("kWh", fontsize=FS_LABEL)
    ax.tick_params(axis="y", labelsize=FS_TICK)
    ax.grid(alpha=0.3, color=C_GRID, lw=0.4, axis="y")
    ax.legend(fontsize=FS_LEGEND - 2, framealpha=0.0, ncol=2)
    fig.suptitle(
        f"VFED × EnergyPlus 逐时重合案例 — BESTEST 案例 {case}"
        f"（普通建筑，丹佛 TMY3）", fontsize=FS_SUPTITLE)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    out = OUT / f"fig_{case}.png"
    fig.savefig(out, dpi=150, transparent=True)
    print(f"[chart] {out}", flush=True)


def fig_free_float(case: str) -> None:
    plt = _setup_mpl()
    z = np.load(OUT / f"series_{case}.npz")
    tv, ev = z["t_z_v"], z["t_z_e"]
    fig, axs = plt.subplots(2, 2, figsize=(11.5, 7.5))
    days = np.arange(8760) / 24.0
    _plot_overlay(axs[0, 0], tv, ev, 0.5,
                  f"案例 {case}：全年逐时室温（自由浮动）", "室温 (°C)",
                  "天", days)
    _plot_overlay(axs[0, 1], tv[WINTER], ev[WINTER], 1.2,
                  "冬季周室温（1 月 18–24 日）", "室温 (°C)")
    _fmt_day_axis(axs[0, 1], WINTER.stop - WINTER.start, "1 月 18 日 0 时起")
    _plot_overlay(axs[1, 0], tv[SUMMER], ev[SUMMER], 1.2,
                  "夏季周室温（7 月 15–22 日）", "室温 (°C)")
    _fmt_day_axis(axs[1, 0], SUMMER.stop - SUMMER.start, "7 月 15 日 0 时起")
    _plot_scatter(axs[1, 1], tv, ev, "全年室温散点", "室温 (°C)", "室温 (°C)")
    fig.suptitle(
        f"VFED × EnergyPlus 逐时重合案例 — BESTEST 案例 {case}"
        f"（普通建筑·自由浮动，丹佛 TMY3）", fontsize=FS_SUPTITLE)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    out = OUT / f"fig_{case}.png"
    fig.savefig(out, dpi=150, transparent=True)
    print(f"[chart] {out}", flush=True)


# ---------------------------------------------------------------------------
# 2x2 parity grid figure (T / RH / heating / cooling, excerpted window,
# fonts x1.3, per-subplot in-window R^2 annotation)
# ---------------------------------------------------------------------------
GRID_WINDOW = slice(105 * 24, 112 * 24)   # Apr 15 00:00 .. Apr 22 00:00
GRID_LABEL = "4 月 15–21 日"


def fig_grid(case: str) -> None:
    plt = _setup_mpl()
    z = np.load(OUT / f"series_{case}.npz")
    win = GRID_WINDOW
    n = win.stop - win.start
    t = np.arange(n) / 24.0
    chans = [
        ("t_z", "温度", "室温 (°C)"),
        ("rh_z", "湿度", "相对湿度 (%)"),
        ("heat", "供热", "逐时供热 (kWh)"),
        ("cool", "供冷", "逐时供冷 (kWh)"),
    ]
    fig, axs = plt.subplots(2, 2, figsize=(13.5, 9.0))
    for ax, (key, title, ylab) in zip(axs.flat, chans):
        v = np.asarray(z[f"{key}_v"], float)[win]
        e = np.asarray(z[f"{key}_e"], float)[win]
        ax.plot(t, v, lw=1.8, color=C_V, label="VFED")
        ax.plot(t, e, lw=1.8, color=C_E, ls="--", label="EnergyPlus")
        ax.set_title(title, fontsize=FS_TITLE)
        ax.set_ylabel(ylab, fontsize=FS_LABEL)
        ax.set_xlabel("天（4 月 15 日 0 时起）", fontsize=FS_LABEL)
        ticks = np.arange(0, n / 24.0 + 0.5, 1.0)
        ax.set_xticks(ticks)
        ax.set_xticklabels([str(int(x)) for x in ticks], fontsize=FS_TICK)
        ax.tick_params(axis="y", labelsize=FS_TICK)
        ax.grid(alpha=0.3, color=C_GRID, lw=0.5)
        ax.legend(fontsize=FS_LEGEND, framealpha=0.0, loc="upper right")
        sst = float(np.sum((e - e.mean()) ** 2))
        if sst > 1e-9:
            r2 = 1.0 - float(np.sum((v - e) ** 2)) / sst
            txt = f"R² = {r2:.3f}"
        else:
            txt = "R² = n/a（窗口内 E+ 无变化）"
        ax.text(0.03, 0.94, txt, transform=ax.transAxes, fontsize=FS_ANNOT,
                va="top", color="#222222")
    fig.suptitle(
        f"VFED × EnergyPlus 逐时对比 — BESTEST 案例 {case}（普通建筑，"
        f"{GRID_LABEL}，丹佛 TMY3）", fontsize=FS_SUPTITLE)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    out = OUT / f"fig_grid_{case}.png"
    fig.savefig(out, dpi=150, transparent=True)
    print(f"[chart] {out}", flush=True)


def fig_summary() -> None:
    plt = _setup_mpl()
    base, par = {}, {}
    for case in CASES:
        rows = json.loads(scan_file(case).read_text(encoding="utf-8")) \
            if scan_file(case).exists() else []
        for r in rows:
            if r["tag"] == "baseline":
                base[case] = r["rows"]
        mp = OUT / "parity_metrics.json"
        if mp.exists():
            rep = json.loads(mp.read_text(encoding="utf-8"))
            if case in rep:
                par[case] = rep[case]["rows"]
    controlled = [c for c in CASES if c in ("600", "900")]
    fig, axs = plt.subplots(1, 2, figsize=(12.5, 4.8))
    ax = axs[0]
    x = np.arange(len(CASES))
    w = 0.35
    ax.bar(x - w / 2, [base.get(c, {}).get("t_z", {}).get("rmse", 0)
                       for c in CASES], w, color="#9e9e9e", label="基线")
    ax.bar(x + w / 2, [par.get(c, {}).get("t_z", {}).get("rmse", 0)
                       for c in CASES], w, color=C_V, label="parity 集")
    ax.set_xticks(x)
    ax.set_xticklabels(CASES, fontsize=FS_TICK)
    ax.tick_params(axis="y", labelsize=FS_TICK)
    ax.set_ylabel("全年室温 RMSE (°C)", fontsize=FS_LABEL)
    ax.set_title("逐时室温一致性（越小越重合）", fontsize=FS_SCAT_TITLE)
    ax.grid(alpha=0.3, color=C_GRID, lw=0.4, axis="y")
    ax.legend(fontsize=FS_LEGEND, framealpha=0.0)
    ax = axs[1]
    labels, b_heat, p_heat, b_cool, p_cool = [], [], [], [], []
    for c in controlled:
        if c in base and c in par:
            labels.append(c)
            b_heat.append(base[c]["heat_kwh"]["diff_pct"])
            p_heat.append(par[c]["heat_kwh"]["diff_pct"])
            b_cool.append(base[c]["cool_kwh"]["diff_pct"])
            p_cool.append(par[c]["cool_kwh"]["diff_pct"])
    x = np.arange(len(labels))
    ax.bar(x - 1.5 * 0.2, b_heat, 0.2, color="#9e9e9e", label="基线 供热")
    ax.bar(x - 0.5 * 0.2, p_heat, 0.2, color=C_V, label="parity 供热")
    ax.bar(x + 0.5 * 0.2, b_cool, 0.2, color="#bdbdbd", label="基线 供冷")
    ax.bar(x + 1.5 * 0.2, p_cool, 0.2, color=C_V, alpha=0.5, label="parity 供冷")
    ax.axhline(0.0, color="#333333", lw=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=FS_TICK)
    ax.tick_params(axis="y", labelsize=FS_TICK)
    ax.set_ylabel("年负荷差 (%)", fontsize=FS_LABEL)
    ax.set_title("年度供冷 / 供热量偏差", fontsize=FS_SCAT_TITLE)
    ax.grid(alpha=0.3, color=C_GRID, lw=0.4, axis="y")
    ax.legend(fontsize=FS_LEGEND - 2, framealpha=0.0)
    fig.suptitle("VFED × EnergyPlus 逐时重合：基线 vs parity 参数集",
                 fontsize=FS_SUPTITLE - 2)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    out = OUT / "fig_summary.png"
    fig.savefig(out, dpi=150, transparent=True)
    print(f"[chart] {out}", flush=True)


def phase_charts(cases: List[str]) -> None:
    for case in cases:
        if case.endswith("FF"):
            fig_free_float(case)
        else:
            fig_controlled(case)
            fig_grid(case)
    if len(cases) == len(CASES):
        fig_summary()


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def phase_report() -> None:
    rep = json.loads((OUT / "parity_metrics.json").read_text(encoding="utf-8"))
    sha = json.loads((OUT / "parity_params.json").read_text(
        encoding="utf-8"))["git_sha"]
    L: List[str] = []
    a = L.append
    a("# VFED × EnergyPlus 逐时重合验证案例（普通建筑）")
    a("")
    a(f"> 生成于 2026-10-26，vfed git sha `{sha}`， harness "
      "`benchmarks/bestest/energyplus/parity_case.py`。")
    a("")
    a("## 1. 案例定位")
    a("")
    a("本案例验证 VFED 的**建筑物理核**在普通建筑工况下与 EnergyPlus 的逐时（8760 小时）一致性。"
      "“普通建筑”指无植物蒸腾、无 PVBES（光伏-电池-电网）调度的单区建筑：")
    a("")
    a("- **案例 600 / 900**：ASHRAE Standard 140-2020 恒温工况（20 °C 供热 / 27 °C 供冷），"
      "轻型（600）与重型（900）围护；")
    a("- **案例 600FF / 900FF**：同围护的自由浮动（无 HVAC）工况，考核纯热动力学时序。")
    a("")
    a("建筑几何：6 m × 8 m × 2.7 m 单区（48 m² 地面，129.6 m³），南向 12 m² 单层玻璃窗，"
      "200 W 内部得热（80 W 对流 + 120 W 辐射），渗透 0.414 ACH（丹佛海拔修正）。")
    a("")
    a("## 2. 对照组：EnergyPlus 23.1")
    a("")
    a("NREL 不分发 ASHRAE 140 的 idf 文件。本仓库 `build_idf.py` 从 LBNL "
      "modelica-buildings 的 Case*.mo 定义重建了 idf，运行 EnergyPlus 23.1 生成逐时参考。"
      "idf 保真度由 ASHRAE 140-2020 官方年度验收带判定（`user-gym/benchmarks/energyplus_report.md`："
      "**14/14 指标 PASS**），因此 E+ 侧具备作为逐时参考（tier-3）的资格。"
      "2026-10-26 为四子图需求向全部案例 idf 追加了 Zone Air Relative Humidity "
      "小时输出（仅输出请求，不改变物理；重跑后年度总量与此前逐位一致，"
      "复验仍 14/14 PASS）。")
    a("")
    a("## 3. VFED 侧模型与对齐")
    a("")
    a("- VFED 为纯 Python ODE 求解器（一维有限差分墙体 `wall_fd_nodes` + 集总空气节点，"
      "dt = 60 s），墙体层结构取 ASHRAE 140 定义原文。")
    a("- 天气：双方使用同一 Denver Intl AP 725650 TMY3 EPW；VFED 侧由 EPW 合成南垂直面 POA 辐照"
      "（NOAA 太阳位置 + 各向同性天空，rho_g = 0.2）。")
    a("- 周期稳态：两年串联仿真，第 1 年洗出初值，报告第 2 年。")
    a("- 对齐约定：E+ 小时结束行 h 对 VFED 第 2 年小时 h，各 8760 行。")
    a("- 恒温器：`photoperiod = 24 h` 使 T_light = 27 全年制冷设定、T_dark = 20 供热设定；"
      "理想设备（无风机电耗；制冷 8 kW 电 × COP 3 = 24 kW 热、电阻供热 8 kW 热，"
      "覆盖 ASHRAE 140 峰值参考区间所需的容量裕度）。")
    a("")
    a("## 4. parity 参数集（校准结果）")
    a("")
    a("校准目标从 ASHRAE 140 年度带切换为 **E+ 逐时序列**（tier-3 参考）。"
      "四波共 95 个候选的定向扫描（逐行记录 `parity_scan_*.json`，排序工具 "
      "`pick_best.py`）表明：恒温器比例带 `mod_band_c` 是二阶旋钮（波 1 实测"
      "对 RMSE/年差影响 < 0.5 个百分点），保持默认 1.0；起决定作用的旋钮是"
      "直连通道 UA（夜间有效传热系数对齐）、窗户太阳能系数与外墙太阳吸收率"
      "（太阳得热分配）、内部质量节点热容（重型墙蓄热回放）与空气节点热容"
      "（自由浮动摆幅）。600 族（600/600FF）采用**完全相同**的参数集"
      "（同一物理建筑，族一致性已验证：600FF 损失仅 0.06 °C RMSE）；"
      "900 与 900FF 分别标定——族集用到 900FF 会劣化到 1.905 °C RMSE"
      "（劣于基线 1.794），该族不一致已量化并在此披露。")
    a("")
    a("| 参数 | 600 | 900 | 600FF | 900FF | 含义 |")
    a("|---|---|---|---|---|---|")
    keys = ("cz", "ua", "eta", "abs_sol", "nodes", "cmass", "gsm")
    desc = {"cz": "空气节点热容 (Wh/K)", "ua": "直连通道 UA（屋面+窗）(W/K)",
            "eta": "窗户太阳能系数", "abs_sol": "外墙太阳吸收率",
            "nodes": "墙 FD 节点数",
            "cmass": "内部质量节点热容 (Wh/K)", "gsm": "内表面耦合 (W/K)"}
    for k in keys:
        cells = []
        for c in CASES:
            v = rep.get(c, {}).get("overrides", {}).get(k)
            cells.append("—" if v is None else f"{v:g}")
        a(f"| {k} | " + " | ".join(cells) + f" | {desc[k]} |")
    a("")
    a("（基线值见 `bestest_lib.INITIAL_FD`：600 族 cz 150 / ua 52.1 / eta 0.77 /"
      " abs_sol 0.40 / cmass 260；900 族 cz 700 / ua 47 / eta 0.725 /"
      " abs_sol 0.35 / cmass 1493。未列出的旋钮保持基线。）")
    a("")
    a("## 5. 逐时重合指标（全年 8760 小时）")
    a("")
    a("“完全相同”的工程界定：两个独立求解器（E+ 传热反应系数法 vs VFED 有限差分 ODE）"
      "不可能逐位一致；本案例做到的是**逐时序列重合**——曲线肉眼不可分、统计指标达到下表水平，"
      "残余差值在第 8 节逐项归因。与 harness 基线相比（600 供热 +7.8%、900 供热 +18.7%），"
      "parity 集把全部年负荷差压进 |≤3.2%|；600 的室温 RMSE 从 0.52 升到 0.57，"
      "换取的是负荷序列重合（综合目标函数 4.63→1.35），权衡已在扫描记录中披露。")
    a("")
    for case in CASES:
        a(f"### 案例 {case}")
        a("")
        a("| 通道 | RMSE | MBE | P95|误差| | R² | VFED 年量 | E+ 年量 | 年差 |")
        a("|---|---|---|---|---|---|---|---|")
        for ch, r in rep.get(case, {}).get("rows", {}).items():
            unit = "°C" if ch == "t_z" else ("%" if ch == "rh_z" else "kWh")
            name = {"t_z": "室温", "heat_kwh": "逐时供热",
                    "cool_kwh": "逐时供冷"}[ch]
            if ch in ("t_z",):
                a(f"| {name} ({unit}) | {r['rmse']:.3f} | {r['mbe']:+.3f} | "
                  f"{r['p95abs']:.3f} | {r['r2']:.4f} | "
                  f"均值 {r['sum_v']/8760:.2f} | 均值 {r['sum_e']/8760:.2f} | "
                  f"{r['diff_pct']:+.2f}% |")
            else:
                a(f"| {name} ({unit}) | {r['rmse']:.3f} | {r['mbe']:+.3f} | "
                  f"{r['p95abs']:.3f} | {r['r2']:.4f} | {r['sum_v']:.0f} | "
                  f"{r['sum_e']:.0f} | {r['diff_pct']:+.2f}% |")
        a("")
    a("## 6. 图表（透明背景 PNG，适合浅色底幻灯片/文档）")
    a("")
    for case in ("600", "900"):
        a(f"- `fig_{case}.png` — 案例 {case} 九面板：全年室温、冬季周/夏季周室温叠加、"
          "冬季周逐时供热与夏季周逐时供冷叠加、室温/供热/供冷 1:1 散点（标注 RMSE·R²）、"
          "月度供热/供冷分组柱状。")
    for case in ("600FF", "900FF"):
        a(f"- `fig_{case}.png` — 案例 {case} 四面板：全年室温叠加、冬季周/夏季周室温叠加、"
          "1:1 散点（标注 RMSE·R²）。")
    a("- `fig_summary.png` — 基线 vs parity 参数集：各案例全年室温 RMSE 柱状、"
      "600/900 年度供热/供冷偏差对比。")
    a("- `fig_grid_600.png` — **单图四子图**（案例 600，节选 4 月 15–21 日，"
      "字号放大 30%）：温度 / 湿度 / 供热 / 供冷的 VFED 与 EnergyPlus 逐时对比，"
      "每张子图标注窗口内 R²（0.961–0.996）。该周供热与供冷同时活跃，"
      "四个通道全部有效。")
    a("- `fig_grid_900.png` — 同版式案例 900（同窗口）。注意：重质建筑在该周"
      "供冷接近退化（周供冷 ~4 kWh，峰值 0.63 kWh），供冷子图 R² 0.637 为"
      "小方差下的如实计算；其余三通道 R² 0.95–0.99。")
    a("")
    a("## 7. ASHRAE 140 官方年度带复验")
    a("")
    a("parity 参数集在逐时对齐 E+ 的同时，仍需回到 ASHRAE 140-2020 官方年度带自检：")
    a("")
    a("| 案例 | 指标 | parity 值 | 官方带 | 判定 |")
    a("|---|---|---|---|---|")
    for case in CASES:
        for key, v in rep.get(case, {}).get("verdicts_140", {}).items():
            a(f"| {case} | {key} | {v['value']:.3f} | "
              f"{v['band'][0]:.3f}..{v['band'][1]:.3f} | **{v['verdict']}** |")
    a("")
    a("判定口径：ASHRAE 140 的**官方验收限值**只存在于年度供热/供冷量"
      "（600/900 共 4 项）——全部 **PASS**。表中 OUT 的三项均无验收效力："
      "900 峰值功率 2 项（140 对峰值只给跨工具参考区间，不在验收范围内），"
      "900FF 年均温 1 项（25.89 °C，超带顶 25.70 °C 约 +0.19 °C）。"
      "自由浮动三元组 min/max/mean 中 5/6 在参考带内。")
    a("## 8. 残差归因（两求解器的已知结构差）")
    a("")
    a("- **太阳位置与逐时辐照处理**：E+ 按亚小时太阳位置细分直射/散射并按入射角修正玻璃透过率；"
      "VFED 用小时中点太阳位置 + 常数太阳能系数（isotropic-sky POA 补偿环日低估）。")
    a("- **长波交换**：E+ 含天空/周围表面长波项；VFED 墙体无夜空长波散热通道"
      "（以直连通道 UA 微降补偿，900 族 `ua` 偏离 140 名义值即源于此）。")
    a("- **墙体导热**：E+ 用状态空间 CTF（逐层构造 + 内外表面膜系数 + 辐射分配）；"
      "VFED 为 1-D 有限差分链 + 集总内部质量节点，表面吸热分配为标定等效。")
    a("- **恒温器**：E+ ideal loads 逐步精确贴合设定点；VFED 为比例带控制器"
      "（parity 集保持默认 1.0 °C 比例带），供热时段存在约 0.2–0.3 °C 的"
      "稳态比例偏移，已计入室温 MBE，并贡献 600 供热年差 +1.1% 中的主要部分。")
    a("- **对齐口径**：E+ 小时行是亚小时积分的小时汇总，VFED 为 60 s 步长积分后按小时分桶，"
      "极值小时存在相位差。")
    a("")
    a("## 9. 复现命令")
    a("")
    a("```bash")
    a("# EnergyPlus 参考重跑（可选，out*/eplusout.csv 已在仓库）")
    a("python benchmarks/bestest/energyplus/run_energyplus.py --only 600 600ff 900 900ff")
    a("# 逐时扫描 / 冻结集复验 / 图表 / 报告")
    a("python benchmarks/bestest/energyplus/parity_case.py scan --case 600")
    a("python benchmarks/bestest/energyplus/parity_case.py finalize --case 600 900 600FF 900FF")
    a("python benchmarks/bestest/energyplus/parity_case.py charts")
    a("python benchmarks/bestest/energyplus/parity_case.py report")
    a("```")
    a("")
    a("## 10. 范围边界")
    a("")
    a("- 湿工况案例 600p（加湿源 + 除湿机交叉验证）为植物工厂前身场景，不在“普通建筑”范围，"
      "且除湿机控制模式存在已归因的结构差（见 `energyplus_hourly_report.md`）。")
    a("- 本案例只考核建筑核：不含 PV / 电池 / 电网调度与植物模块。")
    a("")
    path = OUT / "README.md"
    path.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"[report] {path}", flush=True)


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("phase", choices=["scan", "finalize", "charts", "report"])
    ap.add_argument("--case", nargs="*", default=CASES, choices=CASES)
    args = ap.parse_args()
    if args.phase == "scan":
        phase_scan(args.case)
    elif args.phase == "finalize":
        phase_finalize(args.case)
    elif args.phase == "charts":
        phase_charts(args.case)
    else:
        phase_report()


if __name__ == "__main__":
    main()
