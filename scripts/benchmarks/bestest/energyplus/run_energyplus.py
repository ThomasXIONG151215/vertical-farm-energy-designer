"""EnergyPlus 23.1 vs ASHRAE 140 BESTEST: build, run, verify, report.

The 140 idf files are NOT distributed by NREL (checked: installer
ExampleFiles, GitHub testfiles, historical tags).  We rebuild them from
the same LBNL Case*.mo definitions that bestest_lib.py mirrors (see
build_idf.py), then accept idf fidelity by the 140 reference bands
(bestest_lib.REF).  Once accepted, the hourly zone-temperature /
ideal-load series are the tier-3 (8760-point) reference for vfed.

Two bugs found while bringing this up (both fixed in build_idf.py /
this script's GJ conversion):
  * E+ 23.1 ZoneInfiltration:DesignFlowRate: ACH value is field 8;
    writing it in field 5 silently yields 0 m3/s infiltration.
  * J -> GJ is /1e9 (NOT /3.6e9; kWh->GJ is the one with 3.6).

Usage (repo root):
    python scripts/benchmarks/bestest/energyplus/run_energyplus.py \
        [--epw PATH] [--eplus PATH] [--out user-gym/benchmarks] [--keep]
"""
import argparse
import subprocess
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
BESTEST = HERE.parent
REPO = BESTEST.parents[2]
sys.path.insert(0, str(BESTEST))

import bestest_lib as lib  # noqa: E402
from build_idf import render_idf  # noqa: E402

CASES = ["600", "600ff", "900", "900ff"]
DEFAULT_EPLUS = r"C:\EnergyPlusV23-1-0\energyplus.exe"
DEFAULT_EPW = str(BESTEST / "USA_CO_Denver.Intl.AP.725650_TMY3.epw")


def run_case(case: str, eplus: str, epw: str) -> dict:
    """Render idf, run EnergyPlus, return metrics + hourly arrays."""
    out_dir = HERE / f"out{case}"
    idf = HERE / f"case{case}.idf"
    idf.write_text(render_idf(case.upper()), encoding="utf-8")
    subprocess.run(
        [eplus, "-w", epw, "-d", str(out_dir), "-r", str(idf)],
        cwd=HERE, capture_output=True, timeout=300,
    )
    end = out_dir / "eplusout.end"
    if not end.exists() or "Completed Successfully" not in end.read_text():
        err = (out_dir / "eplusout.err").read_text(errors="replace")[-2000:]
        raise RuntimeError(f"case {case}: EnergyPlus failed\n{err}")

    ep = pd.read_csv(out_dir / "eplusout.csv")
    ep.columns = [c.strip() for c in ep.columns]
    tc = [c for c in ep.columns if "Mean Air Temperature" in c][0]
    T = ep[tc].astype(float).to_numpy()
    r = {"case": case, "t": T, "csv": out_dir / "eplusout.csv"}
    if case.endswith("ff"):
        r.update(min_t=T.min(), max_t=T.max(), mean_t=T.mean())
    else:
        hc = [c for c in ep.columns if "Heating Energy" in c][0]
        cc = [c for c in ep.columns if "Cooling Energy" in c][0]
        h_kwh = ep[hc].astype(float).to_numpy() / 3.6e6  # J -> kWh
        c_kwh = ep[cc].astype(float).to_numpy() / 3.6e6
        r.update(
            annual_heating_gj=h_kwh.sum() * 3.6 / 1000,   # kWh -> GJ (x3.6/1000)
            annual_cooling_gj=c_kwh.sum() * 3.6 / 1000,
            peak_heating_kw=h_kwh.max(),                  # kWh/h == kW avg
            peak_cooling_kw=c_kwh.max(),
            heat_kwh=h_kwh, cool_kwh=c_kwh,
        )
    return r


def verdict(v, band):
    return "PASS" if band[0] <= v <= band[1] else "OUT"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--epw", default=DEFAULT_EPW)
    ap.add_argument("--eplus", default=DEFAULT_EPLUS)
    ap.add_argument("--out", default=str(REPO / "user-gym" / "benchmarks"))
    ap.add_argument("--only", nargs="*", default=CASES)
    args = ap.parse_args()

    results = [run_case(c, args.eplus, args.epw) for c in args.only]

    lines = [
        "# EnergyPlus 23.1 vs ASHRAE 140 BESTEST (idf fidelity)",
        "",
        "- idf source: rebuilt from LBNL Case*.mo definitions via "
        "`build_idf.py` (same source as `bestest_lib.py` walls/geometry)",
        f"- weather: `{Path(args.epw).name}` (Denver TMY3)",
        "- bands: `bestest_lib.REF` (ASHRAE 140-2020 via LBNL mirror)",
        "- scope: idf acceptance only. Once in-band, the hourly series "
        "(zone T / ideal loads) serve as the tier-3 vfed reference.",
        "",
        "## Results",
        "",
        "| case | metric | E+ 23.1 | band | verdict |",
        "|---|---|---|---|---|",
    ]
    n_pass = n_tot = 0
    for r in results:
        bands = lib.REF[r["case"].upper()]
        for key, band in bands.items():
            if key.startswith("accept_"):
                continue
            v = r[key]
            vd = verdict(v, band)
            n_tot += 1
            n_pass += vd == "PASS"
            lines.append(
                f"| {r['case']} | {key} | {v:.3f} | "
                f"{band[0]:.3f}..{band[1]:.3f} | **{vd}** |"
            )
    lines += ["", f"**{n_pass}/{n_tot} metrics PASS**", ""]

    out = Path(args.out) / "energyplus_report.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"\n[report] {out}")
    return 0 if n_pass == n_tot else 1


if __name__ == "__main__":
    sys.exit(main())
