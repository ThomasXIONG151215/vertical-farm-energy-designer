"""3R4C wall-conduction-chain experiment (BESTEST Layer C, harness-only).

Adds a 4th RC node T_w (wall conduction core) on top of the rc3 2R3C network,
WITHOUT touching vfed/: Envelope.step_mass is wrapped (installed/restored per
run) to

  1. advance T_w explicitly (Jacobi, staggered on substep-start T_m/T_ext):
         dT_w = [g_wm*(T_m - T_w) + g_we*(T_ext - T_w)] * dt / (C_w*3600)
  2. let the engine advance T_s/T_m exactly as in --rc3 (solar split fs=1.0
     lands on T_s; the 140 radiant internal gain rides on Q_source_w),
  3. post-correct T_m with the chain coupling:
         T_m += g_wm*(T_w_start - T_m_new) * dt / (C_mass*3600)

Topology (g in W/K, C in Wh/K) -- wall chain attached to the SURFACE node:

    T_ext --g_we-- T_w(C_w) --g_wm-- T_s(C_s) --g_sa-- T_z(C_z)
                                     |
                                   g_sm
                                     |
                                 T_m(C_m) --g_em-- (0 = pure internal mass)

T_s aggregates the solar-receiving INTERIOR WALL surfaces (inner half of the
140 wall construction); the chain T_s->T_w->outdoor is the wall continuum
(inner half -> outer half + siding -> exterior film).  T_m becomes pure
INTERNAL mass (floor slab; g_em = 0): its stored heat returns to the room at
night (free-float min-T support) instead of draining outward -- the floor sits
on R-25 insulation and has no outdoor path.  g_em > 0 keeps a rc3-style fast
leg (2-time-constant export ladder) for scanning.

Parameter anchors = 2-cell finite-difference discretisation of the ASHRAE 140
wall constructions (see layerC_3r4c_design.md):
  600 wall (63.6 m2): R_w=1.789 -> g_wm=A/(R/2)=71.1, g_we=A/(R/2+0.044)=67.7,
       C_w = areal 14.53 kJ/m2K * 63.6 / 2 / 3.6 = 128.7 Wh/K
  900 wall (63.6 m2): R_w=1.698 -> g_wm=74.9, g_we=71.2,
       C_w = areal 145.2 kJ/m2K * 63.6 / 2 / 3.6 = 1282 Wh/K
Euler stability at dt=60 s: worst node T_w(600) sum-g/C = 139/(129*3600)
= 3.0e-4 1/s -> dt_max = 2/lambda = 6690 s >> 60 s (margin >100x).

Usage:
  python exp_3r4c.py --only 600 600FF
  python exp_3r4c.py --only 600 --gsa 200 300 384 --eta 0.68
Any parameter may take several values (cartesian product, printed per run).
No report file is written; this is a scan tool.
"""
from __future__ import annotations

import argparse
import itertools
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd

import bestest_lib as lib
import vfed.design.engine as eng
import vfed.physics.ode as ode_mod
import vfed.physics.envelope as env_mod

# ---------------------------------------------------------------------------
# Anchor chains per case family (2-cell FD of the 140 wall constructions)
# ---------------------------------------------------------------------------
CHAIN_ANCHOR = {
    "600": dict(cw=129.0, gwm=71.0, gwe=67.7),
    "900": dict(cw=1373.0, gwm=75.0, gwe=71.2),
}


def run_case_3r4c(
    case: str,
    weather_year: pd.DataFrame,
    *,
    cz=None,
    ua=None,
    eta=None,
    cmass=None,
    gsm=None,
    gsa=None,
    gem=None,
    cs=None,
    cw=None,
    gwm=None,
    gwe=None,
    fs=None,
    equip_rad_w: float = 120.0,
    mod_band=None,
    t_max: float = 90.0,
) -> lib.CaseResult:
    """One BESTEST case on the rc3 network + harness 3R4C chain (T_w node).

    Defaults resolve from INITIAL_RC3 for the (cz, ua, eta, cmass, gsm, gsa,
    gem, cs, fs) group and from CHAIN_ANCHOR for (cw, gwm, gwe).
    """
    import vfed.design.engine as eng  # noqa: F401  (patch targets)
    from vfed.design.project import DesignProject

    init = dict(lib.INITIAL_RC3[case])
    anchor = dict(CHAIN_ANCHOR[case.rstrip("FF")])
    cz = init["cz"] if cz is None else cz
    ua = init["ua"] if ua is None else ua
    eta = init["eta"] if eta is None else eta
    cmass = init["cmass"] if cmass is None else cmass
    gsm = init["gsm"] if gsm is None else gsm
    gsa = init["gsa"] if gsa is None else gsa
    gem = init["g_em"] if gem is None else gem
    cs = init["cs"] if cs is None else cs
    fs = init["fs"] if fs is None else fs
    cw = anchor["cw"] if cw is None else cw
    gwm = anchor["gwm"] if gwm is None else gwm
    gwe = anchor["gwe"] if gwe is None else gwe

    free_float = case.endswith("FF")
    d = lib.case_dict(
        case, cz=cz, u_wall_a=ua, eta_solar=eta, free_float=free_float,
        rc3=True, cmass=cmass, gem=gem, cs=cs, gsa=gsa, gsm=gsm, fs=fs,
        mod_band_c=1.0 if mod_band is None else mod_band,
    )
    project = DesignProject.from_dict(d)
    dt = project.space.timestep_s

    n = len(weather_year)
    sub = int(round(3600.0 / dt))
    heat_wh = np.zeros(2 * n)
    cool_wh = np.zeros(2 * n)
    counter = {"i": 0}

    # -- chain state holder: one T_w per Envelope instance (id-keyed) -------
    chain_state: dict = {}

    orig_step = eng.HVACDevice.step
    orig_tmax = ode_mod._DEFAULT_T_MAX
    orig_step_mass = env_mod.Envelope.step_mass

    def patched_step(self, T_z, RH_z, T_ext, dt=60.0, **kw):
        out = orig_step(self, T_z, RH_z, T_ext, dt, **kw)
        q = out["Q_HVAC_W"]
        h = counter["i"] // sub
        if h < 2 * n:
            if q >= 0.0:
                heat_wh[h] += q * dt / 3600.0
            else:
                cool_wh[h] += -q * dt / 3600.0
        counter["i"] += 1
        return out

    def patched_step_mass(self, T_ext, T_z, dt, Q_source_w=0.0):
        rc = self._rc
        st = chain_state.get(id(self))
        if st is None:
            st = chain_state[id(self)] = {"tw": 20.0}
        tw0 = st["tw"]
        # 1) T_w explicit Euler on substep-start T_s / T_ext (Jacobi leg)
        tw1 = tw0 + (gwm * (rc.T_s - tw0) + gwe * (T_ext - tw0)) * dt / (cw * 3600.0)
        if not (-100.0 <= tw1 <= 100.0):
            raise RuntimeError(
                f"3R4C T_w node diverged to {tw1:.1f} C (C_w={cw}, g_wm={gwm}, "
                f"g_we={gwe}, dt={dt}, T_s={rc.T_s:.1f}, T_w={tw0:.1f})"
            )
        # 2) engine advances T_s / T_m unchanged (solar split + radiant gain)
        out = orig_step_mass(self, T_ext, T_z, dt, Q_source_w=Q_source_w)
        # 3) post-correct T_s with the wall-chain coupling (substep-start T_w)
        rc.T_s += gwm * (tw0 - rc.T_s) * dt / (rc.C_surface * 3600.0)
        if not (-100.0 <= rc.T_s <= 100.0):
            raise RuntimeError(
                f"3R4C T_s post-correction diverged to {rc.T_s:.1f} C "
                f"(C_s={rc.C_surface}, g_wm={gwm}, T_w={tw0:.1f})"
            )
        st["tw"] = tw1
        return out

    eng.HVACDevice.step = patched_step
    env_mod.Envelope.step_mass = patched_step_mass
    ode_mod._DEFAULT_T_MAX = float(t_max)
    try:
        engine = eng.DesignEngine()
        result = engine.run(project, weather=lib.dual_year(weather_year))
    finally:
        eng.HVACDevice.step = orig_step
        env_mod.Envelope.step_mass = orig_step_mass
        ode_mod._DEFAULT_T_MAX = orig_tmax

    t_z = np.asarray(result.timeseries["T_z"], dtype=float)
    if len(t_z) != 2 * n:
        raise ValueError(f"expected {2*n} hourly rows, got {len(t_z)}")
    t2 = t_z[n:]
    h2, c2 = heat_wh[n:] / 1000.0, cool_wh[n:] / 1000.0

    clip = int(result.summary.get("moisture_clamp_stats", {}).get("temp_clip_events", 0))
    extra = {
        "heating_hours": float((h2 > 0.0).sum()),
        "cooling_hours": float((c2 > 0.0).sum()),
        "timestep_s": float(dt),
        "wall_rc_nodes": 3,
        "mode": "3r4c",
        "cmass": float(cmass),
        "g_em": float(gem),
        "cs": float(cs),
        "g_sa": float(gsa),
        "g_sm": float(gsm),
        "fs": float(fs),
        "cw": float(cw),
        "g_wm": float(gwm),
        "g_we": float(gwe),
        "equip_rad_w": float(equip_rad_w),
    }
    tw_final = [v["tw"] for k, v in chain_state.items()]
    extra["t_w_final_c"] = float(tw_final[-1]) if tw_final else float("nan")
    return lib.CaseResult(
        case=case,
        annual_heating_kwh=float(h2.sum()),
        annual_cooling_kwh=float(c2.sum()),
        peak_heating_kw=float(h2.max()),
        peak_cooling_kw=float(c2.max()),
        min_t=float(t2.min()),
        max_t=float(t2.max()),
        mean_t=float(t2.mean()),
        temp_clip_events=clip,
        cz=cz,
        u_wall_a=ua,
        eta_solar=eta,
        extra=extra,
    )


def _fmt(res: lib.CaseResult) -> str:
    ex = res.extra
    p = (f"eta={res.eta_solar:.2f} cs={ex['cs']:.0f} gsa={ex['g_sa']:.0f} "
         f"gsm={ex['g_sm']:.0f} cm={ex['cmass']:.0f} gem={ex['g_em']:.1f} "
         f"cw={ex['cw']:.0f} gwm={ex['g_wm']:.0f} gwe={ex['g_we']:.1f}")
    if res.case.endswith("FF"):
        m = (f"min {res.min_t:7.2f} max {res.max_t:7.2f} mean {res.mean_t:6.2f}")
        verdicts = []
        for k, v in (("min_t", res.min_t), ("max_t", res.max_t), ("mean_t", res.mean_t)):
            verdicts.append(lib.verdict(v, lib.REF[res.case][k]))
        flag = "PASS" if all(v == "PASS" for v in verdicts) else "OUT"
        return f"{res.case:6s} | {p} | {m} | {flag} {verdicts}"
    m = (f"H {res.annual_heating_gj:6.3f} C {res.annual_cooling_gj:6.3f} "
         f"pkH {res.peak_heating_kw:5.2f} pkC {res.peak_cooling_kw:5.2f}")
    verdicts = []
    for k, v in lib.case_metrics(res).items():
        verdicts.append(f"{k.split('_')[1]}:{lib.verdict(v, lib.REF[res.case][k])}")
    return f"{res.case:6s} | {p} | {m} | {' '.join(verdicts)}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--epw", default=lib.__dict__.get("DEFAULT_EPW", None)
                    or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "USA_CO_Denver.Intl.AP.725650_TMY3.epw"))
    ap.add_argument("--only", nargs="*", default=["600", "600FF", "900", "900FF"])
    ap.add_argument("--eta", nargs="*", type=float, default=[None])
    ap.add_argument("--cz", nargs="*", type=float, default=[None])
    ap.add_argument("--ua", nargs="*", type=float, default=[None])
    ap.add_argument("--cmass", nargs="*", type=float, default=[None])
    ap.add_argument("--gsm", nargs="*", type=float, default=[None])
    ap.add_argument("--gsa", nargs="*", type=float, default=[None])
    ap.add_argument("--gem", nargs="*", type=float, default=[None])
    ap.add_argument("--cs", nargs="*", type=float, default=[None])
    ap.add_argument("--cw", nargs="*", type=float, default=[None])
    ap.add_argument("--gwm", nargs="*", type=float, default=[None])
    ap.add_argument("--gwe", nargs="*", type=float, default=[None])
    ap.add_argument("--fs", nargs="*", type=float, default=[None])
    ap.add_argument("--modband", nargs="*", type=float, default=[None])
    args = ap.parse_args()

    for c in args.only:
        if c not in lib.REF:
            ap.error(f"unknown case {c!r}")
    df = lib.load_epw(args.epw)
    print(f"[weather] {args.epw}  POA/GHI={df.attrs['poa_to_ghi_annual']:.3f}")

    grids = [args.eta, args.cz, args.ua, args.cmass, args.gsm, args.gsa,
             args.gem, args.cs, args.cw, args.gwm, args.gwe, args.fs,
             args.modband]
    combos = list(itertools.product(*grids))
    print(f"[scan] {len(combos)} combos x {len(args.only)} cases = "
          f"{len(combos)*len(args.only)} runs")
    results = []
    for i, combo in enumerate(combos):
        (eta, cz, ua, cmass, gsm, gsa, gem, cs, cw, gwm, gwe, fs, mb) = combo
        kw = dict(eta=eta, cz=cz, ua=ua, cmass=cmass, gsm=gsm, gsa=gsa,
                  gem=gem, cs=cs, cw=cw, gwm=gwm, gwe=gwe, fs=fs, mod_band=mb)
        for case in args.only:
            print(f"[{i+1}/{len(combos)}] {case} ...", flush=True)
            res = run_case_3r4c(case, df, **kw)
            results.append(res)
            print("    " + _fmt(res), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
