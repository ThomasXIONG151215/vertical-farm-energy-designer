"""Diagnose the controlled-case (600) annual-load gap: monthly heating/cooling
energy + duty hours on the FD wall mode."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd

import bestest_lib as lib
import vfed.design.engine as eng
import vfed.physics.ode as ode_mod


def run_diag(case: str, df: pd.DataFrame, **kw) -> dict:
    import vfed.design.project as proj
    import vfed.physics.envelope as env_mod

    init = dict(lib.INITIAL_FD[case])
    cz = init["cz"] if kw.get("cz") is None else kw["cz"]
    eta = init["eta"] if kw.get("eta") is None else kw["eta"]
    free_float = case.endswith("FF")
    d = lib.case_dict(
        case, cz=cz, u_wall_a=kw.get("ua", init["ua"]), eta_solar=eta,
        free_float=free_float, fd=True,
        cmass=init["cmass"], gsm=kw.get("gsm", init["gsm"]), fs=kw.get("fs", init["fs"]),
        nodes=init["nodes"], layers=init["layers"], area=init["area"],
        h_ext=init["h_ext"], abs_sol=kw.get("abs_sol", init["abs_sol"]), h_c=init["h_c"],
        mod_band_c=1.0,
    )
    project = proj.DesignProject.from_dict(d)
    dt = project.space.timestep_s
    n = len(df)
    sub = int(round(3600.0 / dt))
    heat_wh = np.zeros(2 * n)
    cool_wh = np.zeros(2 * n)
    counter = {"i": 0}
    orig_step = eng.HVACDevice.step
    orig_tmax = ode_mod._DEFAULT_T_MAX
    orig_step_mass = env_mod.Envelope.step_mass
    rad_w = 120.0  # ASHRAE 140-2020 radiant internal-gain share (run_case parity)

    def patched_step(self, T_z, RH_z, T_ext, dt=60.0, **k):
        out = orig_step(self, T_z, RH_z, T_ext, dt, **k)
        q = out["Q_HVAC_W"]
        h = counter["i"] // sub
        if h < 2 * n:
            if q >= 0.0:
                heat_wh[h] += q * dt / 3600.0
            else:
                cool_wh[h] += -q * dt / 3600.0
        counter["i"] += 1
        return out

    def patched_step_mass(self, T_ext, T_z, dt, Q_source_w=0.0, I_ext_wm2=0.0):
        return orig_step_mass(
            self, T_ext, T_z, dt,
            Q_source_w=Q_source_w + rad_w,
            I_ext_wm2=I_ext_wm2,
        )

    eng.HVACDevice.step = patched_step
    env_mod.Envelope.step_mass = patched_step_mass
    ode_mod._DEFAULT_T_MAX = 90.0
    try:
        result = eng.DesignEngine().run(project, weather=lib.dual_year(df))
    finally:
        eng.HVACDevice.step = orig_step
        env_mod.Envelope.step_mass = orig_step_mass
        ode_mod._DEFAULT_T_MAX = orig_tmax

    months = np.asarray(result.timeseries["month"], dtype=float)[n:]
    h2 = heat_wh[n:] / 1000.0  # kWh per hour
    c2 = cool_wh[n:] / 1000.0
    out = {"summary": []}
    for m in range(1, 13):
        sel = months == m
        # kWh -> GJ: x 0.0036 (1 kWh = 3.6 MJ).  The old x1/1000 here
        # reported MWh mislabelled as GJ (R28 step-6 unit bug, fixed).
        out["summary"].append(
            (m, h2[sel].sum() * 0.0036, c2[sel].sum() * 0.0036,
             float((h2[sel] > 0).sum()), float((c2[sel] > 0).sum()))
        )
    out["t_z"] = np.asarray(result.timeseries["T_z"], dtype=float)[n:]
    out["heat"] = h2
    out["cool"] = c2
    return out


if __name__ == "__main__":
    df = lib.load_epw(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "USA_CO_Denver.Intl.AP.725650_TMY3.epw"))
    case = sys.argv[1] if len(sys.argv) > 1 else "600"
    print(f"[diag] case {case} (FD, INITIAL_FD params)")
    out = run_diag(case, df)
    print(" mo |   heat GJ |  cool GJ | heat h | cool h")
    for m, hj, cj, hh, ch in out["summary"]:
        print(f"  {m:2d} | {hj:9.3f} | {cj:8.3f} | {hh:6.0f} | {ch:6.0f}")
    hj = sum(r[1] for r in out["summary"])
    cj = sum(r[2] for r in out["summary"])
    print(f" yr | {hj:9.3f} | {cj:8.3f} | heat-h {sum(r[3] for r in out['summary']):.0f} | "
          f"cool-h {sum(r[4] for r in out['summary']):.0f}")
    tz = out["t_z"]
    print(f"T_z: min {tz.min():.2f} max {tz.max():.2f} mean {tz.mean():.2f}")
