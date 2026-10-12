"""vfed FD hourly vs EnergyPlus hourly -- BESTEST Cases 600/900/600FF/900FF.

Alignment: both are 8760-row TMY3 standard years. E+ row h (hour-ending
h+1:00) is compared against vfed year-2 hour h. E+ energy comes in
Joules (hourly sum) -> kWh = J / 3.6e6.

No official ASHRAE 140 hourly band exists (140 publishes annual totals
only; LBNL Dymola txt is ~99 sparse points/yr). Verdicts here are
DIAGNOSTIC with self-declared bands:

  - HVAC case zone temp : RMSE <= 1.0 C   (both pinned at thermostat)
  - FF case zone temp   : RMSE <= 3.0 C   (free-float swing ~76 C/yr,
                           qualified tools disagree by degrees at min/max)
  - heat/cool hourly    : no hard band; annual diff % + monthly shape
                           carry the correspondence judgement

Usage (repo root):
    python scripts/benchmarks/bestest/energyplus/probe_vs_eplus.py
        [--report user-gym/benchmarks/energyplus_hourly_report.md]
"""
import argparse
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
BESTEST = HERE.parent
BENCH = BESTEST.parent
REPO = BENCH.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(BESTEST))
sys.path.insert(0, str(BENCH))

import bestest_lib as lib  # noqa: E402
from _common import metrics  # noqa: E402

EPW = BESTEST / "USA_CO_Denver.Intl.AP.725650_TMY3.epw"

CASES = ["600", "600p", "900", "600FF", "900FF"]
WINTER_WEEK = slice(17 * 24, 25 * 24)  # Jan 18-25

MONTH_DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
MONTH_EDGES = np.cumsum([0] + [d * 24 for d in MONTH_DAYS])

TEMP_BAND_HVAC = 1.0   # C
TEMP_BAND_FF = 3.0     # C

# run_energyplus.py output dirs; 600p's E+ run lives in out_case600p
OUT_DIR = {"600p": "out_case600p"}


def month_of(h):
    return int(np.searchsorted(MONTH_EDGES, h, side="right") - 1)


MONTHS = np.array([month_of(h) for h in range(8760)])


def load_eplus(case: str) -> dict:
    d = HERE / OUT_DIR.get(case, f"out{case.lower()}") / "eplusout.csv"
    ep = pd.read_csv(d)
    ep.columns = [c.strip() for c in ep.columns]
    out = {"dt": ep["Date/Time"].astype(str).str.strip().to_numpy()}
    tcol = [c for c in ep.columns if "Mean Air Temperature" in c]
    out["t_z"] = ep[tcol[0]].astype(float).to_numpy()
    for key, frag, div in (
            ("heat_kwh", "Supply Air Sensible Heating Energy", 3.6e6),
            ("cool_kwh", "Supply Air Sensible Cooling Energy", 3.6e6),
            ("rh_z", "Zone Air Relative Humidity", 1.0),
            ("deh_kwh", "Dehumidifier Electricity Energy", 3.6e6)):
        cols = [c for c in ep.columns if frag in c]
        if cols:
            out[key] = ep[cols[0]].astype(float).to_numpy() / div
    return out


def run_pair(case: str, df: pd.DataFrame) -> dict:
    """Run both sides for one case, return aligned hourly arrays."""
    hourly = {}
    lib.run_case(case, df, fd=True, hourly_out=hourly,
                 wet=case.endswith("p"))
    ep = load_eplus(case)
    pair = {"case": case, "hvac": not case.endswith("FF"), "dt": ep["dt"]}
    chans = [c for c in ("t_z", "heat_kwh", "cool_kwh", "rh_z", "deh_kwh")
             if c in ep]
    for ch in chans:
        v, e = hourly[ch], ep[ch]
        assert len(v) == 8760 == len(e), (case, ch, len(v), len(e))
        m = metrics(v, e)
        pair[ch] = {
            "vfed": np.asarray(v, dtype=float),
            "eplus": np.asarray(e, dtype=float),
            "m": m,
            "sum_v": float(np.sum(v)),
            "sum_e": float(np.sum(e)),
        }
    return pair


def temp_verdict(case_hvac: bool, rmse: float) -> str:
    band = TEMP_BAND_HVAC if case_hvac else TEMP_BAND_FF
    return "PASS" if rmse <= band else "OUT"


def render_report(pairs: list, sha: str) -> str:
    L = []
    a = L.append
    a("# vfed vs EnergyPlus hourly benchmark (BESTEST Cases 600/900/FF)")
    a("")
    a("## Scope")
    a("")
    a("- **What is tested**: hourly-level correspondence of vfed FD wall model")
    a("  vs a self-built EnergyPlus 23.1 replica of ASHRAE 140 Cases")
    a("  600/900 (thermostat 20/27 C) and 600FF/900FF (free float).")
    a("  Channels: zone temp all cases; hourly heat/cool energy for HVAC cases.")
    a("- **Case 600p (in-house, NOT ASHRAE 140)**: Case 600 skeleton + 200 W")
    a("  latent-only moisture source + dehumidifier (vfed DEH on_off 15 L/day")
    a("  SMER 2.0 vs E+ ZoneHVAC:Dehumidifier:DX 15 L/day EF 2.0) + RH")
    a("  setpoint 60 %.  First wet-path cross-check: RH and DEH channels.")
    a("- **What is NOT tested**: no official hourly band exists (140")
    a("  publishes annual totals only), so bands below are self-declared")
    a("  diagnostic sentinels for future regressions, not ASHRAE verdicts.")
    a("- **E+ replica fidelity**: annual totals 14/14 PASS vs 140 official")
    a("  bands (see energyplus_report.md) -- E+ side qualifies as reference.")
    a("")
    a("## Setup")
    a("")
    a(f"- vfed git sha `{sha}`, INITIAL_FD params via bestest_lib (--fd)")
    a("- EnergyPlus 23.1, self-built idf (build_idf.py), Denver TMY3 EPW")
    a("- alignment: E+ hour-ending h+1:00 vs vfed year-2 hour h (both 8760)")
    a("")
    a("## Hourly stats")
    a("")
    a("| case | channel | RMSE | MBE | P95abs | vfed sum | E+ sum | diff% |")
    a("|---|---|---|---|---|---|---|---|")
    for p in pairs:
        for ch, d in p.items():
            if ch in ("case", "hvac", "dt"):
                continue
            unit = {"t_z": "C", "rh_z": "%"}.get(ch, "kWh")
            sv, se = d["sum_v"], d["sum_e"]
            if ch in ("t_z", "rh_z"):
                a(f"| {p['case']} | {ch} ({unit}) | {d['m']['rmse']:.2f} | "
                  f"{d['m']['mbe']:+.2f} | {d['m']['p95abs']:.2f} | "
                  f"mean {sv/8760:.2f} | mean {se/8760:.2f} | "
                  f"{(sv-se)/8760:+.2f} |")
            else:
                diff = (sv - se) / se * 100 if se else float("nan")
                a(f"| {p['case']} | {ch} ({unit}) | {d['m']['rmse']:.2f} | "
                  f"{d['m']['mbe']:+.3f} | {d['m']['p95abs']:.2f} | "
                  f"{sv:.0f} | {se:.0f} | {diff:+.1f}% |")
    a("")
    a("## Verdict (self-declared diagnostic bands)")
    a("")
    a("| case | channel | RMSE | band | verdict |")
    a("|---|---|---|---|---|")
    for p in pairs:
        d = p["t_z"]
        band = TEMP_BAND_HVAC if p["hvac"] else TEMP_BAND_FF
        a(f"| {p['case']} | t_z (C) | {d['m']['rmse']:.2f} | <= {band:.1f} | "
          f"{temp_verdict(p['hvac'], d['m']['rmse'])} |")
        for ch in ("heat_kwh", "cool_kwh", "rh_z", "deh_kwh"):
            if ch in p:
                a(f"| {p['case']} | {ch} | {p[ch]['m']['rmse']:.2f} | "
                  f"none (diagnostic) | DIAGNOSTIC |")
    a("")
    a("## Monthly heat/cool (kWh, vfed / E+ / diff)")
    a("")
    for p in pairs:
        if not p["hvac"]:
            continue
        for ch in ("heat_kwh", "cool_kwh"):
            d = p[ch]
            a(f"### Case {p['case']} {ch[:-4]}")
            a("")
            a("| mon | vfed | E+ | diff |")
            a("|---|---|---|---|")
            for m in range(12):
                i = MONTHS == m
                a(f"| {m+1} | {d['vfed'][i].sum():.0f} | "
                  f"{d['eplus'][i].sum():.0f} | "
                  f"{(d['vfed'] - d['eplus'])[i].sum():+.0f} |")
            a("")
    a("## FF free-float extremes (annual)")
    a("")
    a("| case | stat | vfed | E+ |")
    a("|---|---|---|---|")
    for p in pairs:
        if p["hvac"]:
            continue
        v, e = p["t_z"]["vfed"], p["t_z"]["eplus"]
        for name, f in (("min", np.min), ("max", np.max), ("mean", np.mean)):
            a(f"| {p['case']} | {name} (C) | {f(v):.2f} | {f(e):.2f} |")
    a("")
    a("## Winter week excerpt (Case 600 hourly heat kWh, Jan 18-25)")
    a("")
    a("| time | hour | vfed | E+ |")
    a("|---|---|---|---|")
    d = pairs[0]["heat_kwh"]
    dt = pairs[0]["dt"]
    for h in range(WINTER_WEEK.start, WINTER_WEEK.stop):
        a(f"| {dt[h][:11]} | {h % 24} | {d['vfed'][h]:.3f} | "
          f"{d['eplus'][h]:.3f} |")
    a("")
    a("## Reading")
    a("")
    a("Known structural differences (from probe diagnostics):")
    a("")
    a("- vfed thermostat settles at 19.65-19.84 C vs E+ 20.00 -> heating")
    a("  hours/energy skew slightly high in vfed (dead-zone implementation)")
    a("- night UA_eff: vfed ~95 vs E+ ~86 W/K -> small steady night gap")
    a("- cooling path matches closely (annual diff < 1%)")
    a("- 600p wet path (vfd primary, follow-up attribution closed): vfed")
    a("  DEH control=\"vfd\" (proportional-band modulation, DOE 87 FR 35286")
    a("  part-load SMER penalty) vs E+ ZoneHVAC:Dehumidifier:DX (PLR capacity")
    a("  modulation, flat Energy-Factor curve) -- like-for-like continuous")
    a("  modulation on both sides.  Authoritative ledger (summary.")
    a("  dehumidifier_performance): vfd DEH 259.1 kWh / 480.1 kg water,")
    a("  effective SMER 1.85 L/kWh vs rated 2.0 (only -8 %: utilization 0.83")
    a("  keeps the compressor in the efficient high-speed band).  E+: DX")
    a("  86.5 kWh / 172.9 kg at constant EF 2.0.  The residual 3.0x electric")
    a("  gap decomposes exactly: 2.78x water-allocation (E+ IdealLoads latent")
    a("  cooling removes 141.8 kg as a side effect of its fixed 0.009 kg/kg")
    a("  supply-air state point -- vfed HVAC is pure sensible, SHR=1, so the")
    a("  whole load lands on the DEH) x 1.08 efficiency (DOE penalty).  No")
    a("  unexplained residual.  (on_off baseline for reference: 529 kWh,")
    a("  effective SMER 0.85 -- bang-bang burns rated power while the")
    a("  inventory limiter throttles the actual removal; not a wet-balance")
    a("  bug, a control-mode coupling artefact.)")
    a("- infiltration channel exonerated: monthly carry-out vfed/E+ =")
    a("  0.98-1.00x all winter; annual 2345 vs 2308 kg; both water ledgers")
    a("  close on the 2584 kg source within 9 % / 1.5 %.")
    a("")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", default=None,
                    help="write markdown report to this path")
    args = ap.parse_args()

    df = lib.load_epw(str(EPW))
    print(f"[weather] {len(df)} rows")
    pairs = []
    for case in CASES:
        print(f"[run] case {case} ...", flush=True)
        p = run_pair(case, df)
        pairs.append(p)
        for ch, d in p.items():
            if ch in ("case", "hvac", "dt"):
                continue
            print(f"  {ch:9s} RMSE {d['m']['rmse']:8.3f} "
                  f"MBE {d['m']['mbe']:+8.3f}", flush=True)

    if args.report:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, cwd=REPO).stdout.strip()
        path = Path(args.report)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_report(pairs, sha), encoding="utf-8")
        print(f"[report] {path}")


if __name__ == "__main__":
    main()
