"""R28 step-2 diagnostic: January trace of the best 2R2C solar-split corner.

Runs one controlled case with the solar-split patch and dumps January (year 2)
hourly T_z / T_m / Q_solar / Q_heat / Q_cool plus monthly conditioning sums,
to attribute the residual out-of-band loads (peak collapse, cooling excess).
Harness-side only; no vfed/ changes.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import bestest_lib as lib  # noqa: E402
from solar_split_scan import STATE, install_patch  # noqa: E402


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--case", default="600")
    ap.add_argument("--f", type=float, default=1.0)
    ap.add_argument("--gim", type=float, default=150.0)
    ap.add_argument("--gem", type=float, default=12.0)
    ap.add_argument("--cmass", type=float, default=6000.0)
    ap.add_argument("--eta", type=float, default=0.72)
    ap.add_argument("--month", type=int, default=1, help="1-based month of year 2")
    args = ap.parse_args()

    STATE["f"] = args.f
    env_mod, orig = install_patch()
    df = lib.load_epw(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "USA_CO_Denver.Intl.AP.725650_TMY3.epw"))

    import vfed.design.engine as eng
    import vfed.physics.ode as ode_mod

    n = len(df)
    sub = 60  # dt=60 s
    heat_wh = np.zeros(2 * n)
    cool_wh = np.zeros(2 * n)
    counter = {"i": 0}
    orig_step = eng.HVACDevice.step
    orig_tmax = ode_mod._DEFAULT_T_MAX

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

    eng.HVACDevice.step = patched_step
    ode_mod._DEFAULT_T_MAX = 90.0
    try:
        res = lib.run_case(args.case, df, eta_solar=args.eta, gim=args.gim,
                           gem=args.gem, cmass=args.cmass, rc=True)
    finally:
        eng.HVACDevice.step = orig_step
        ode_mod._DEFAULT_T_MAX = orig_tmax
        STATE["f"] = 0.0
        env_mod.Envelope.Q_solar = orig["Q_solar"]
        env_mod.Envelope.step_mass = orig["step_mass"]
        env_mod.Envelope.Q_wall = orig["Q_wall"]
        env_mod.Envelope.reset = orig["reset"]
        lib.case_dict = orig["case_dict"]

    ts = res.extra  # noqa: F841
    # Re-run is expensive; instead reuse lib result timeseries if present.
    print(f"[kpi] heat {res.annual_heating_gj:.3f} cool {res.annual_cooling_gj:.3f}"
          f" pkH {res.peak_heating_kw:.2f} pkC {res.peak_cooling_kw:.2f}"
          f" T {res.min_t:.1f}/{res.mean_t:.1f}/{res.max_t:.1f}")

    # The engine result object is gone; recover January from the buckets.
    # heat_wh/cool_wh: hourly Wh over the dual year; year 2 starts at n.
    h2 = heat_wh[n:] / 1000.0
    c2 = cool_wh[n:] / 1000.0
    months = np.arange(8760) // 24 // 30 + 1  # coarse 30-day months
    months = np.repeat(np.arange(12), (8760 // 12)) if False else months
    print("\nmonthly conditioning (kWh):")
    print("mo |   heat |   cool | heat-h | cool-h")
    for m in range(12):
        sel = slice(m * 730, (m + 1) * 730)
        hm, cm = h2[sel], c2[sel]
        print(f"{m+1:2d} | {hm.sum():6.0f} | {cm.sum():6.0f} | "
              f"{(hm > 0).sum():6.0f} | {(cm > 0).sum():6.0f}")

    m0 = (args.month - 1) * 730
    print(f"\nJanuary year-2 trace (first 14 days, hour: T_z-ish heat_kW "
          f"cool_kW):")
    for i in range(m0, m0 + 24 * 14, 1):
        hk, ck = h2[i], c2[i]
        d, hh = divmod(i, 24)
        bar = ("H" * int(round(hk / 200.0))) + ("C" * int(round(ck / 200.0)))
        if hk > 0 or ck > 0:
            print(f"d{d:02d} h{hh:02d} | {hk:5.2f} | {ck:5.2f} | {bar}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
