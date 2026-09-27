"""R28 step-2 harness experiment: solar heat-gain air/mass split scan.

TEMPORARY EXPERIMENT (no vfed/ source changes).  Monkeypatches
``vfed.physics.envelope.Envelope`` so the window solar gain is split:

    Q_sol_z = (1 - f_split) * eta_solar * A_window * POA   -> air node  (engine.py:870)
    Q_sol_m = f_split * eta_solar * A_window * POA         -> mass node source (T_m)

Reference rule (LBNL modelica-buildings, SolarRadiationExchange.mo): 100% of
transmitted solar lands on construction surface nodes; air receives heat only
through the inner film.  f_split=1.0 is the strictest translation; 0.6 is the
canonical radiative/convective simplification (140 internal gains 120/200).

Patch mechanics: ``Envelope.Q_solar`` returns the air share and caches the
FULL heat rate in a module holder; the re-implemented ``step_mass`` adds
``f_split * Q_full`` as a source in the mass-node balance.  Within an hour the
cached value is constant (weather is hourly); the first substep of each hour
reads the previous hour's cache -> <=1 substep/hour (60 s) lag, negligible.

Usage (repo root):
    python scripts/benchmarks/bestest/solar_split_scan.py --case 600 \
        --f 0 0.3 0.6 --gim 50 100 200 400
    python scripts/benchmarks/bestest/solar_split_scan.py --case 600FF \
        --f 0.6 --gim 100 --eta 0.80 0.85
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bestest_lib as lib  # noqa: E402

STATE = {"f": 0.0, "q_full_w": 0.0}
RC3 = {"on": False, "g_sm": 0.0, "c_s": 0.0}


def install_patch():
    import vfed.physics.envelope as env_mod

    # BESTEST HVAC is ideal (unlimited capacity); the harness 4 kW cooling cap
    # clips the reference peak-cooling band (5.42-6.48 kW).  Wrap case_dict to
    # raise the headroom (harness-side only).
    orig_q_solar = env_mod.Envelope.Q_solar
    orig_step_mass = env_mod.Envelope.step_mass
    orig_q_wall = env_mod.Envelope.Q_wall
    orig_reset = env_mod.Envelope.reset
    orig_case_dict = lib.case_dict

    def case_dict_big_cap(name, **kw):
        d = orig_case_dict(name, **kw)
        if not name.endswith("FF"):
            d["hvac"]["P_rated_w"] = max(d["hvac"]["P_rated_w"], 8000.0)
            d["hvac"]["P_rated_heat_w"] = max(d["hvac"]["P_rated_heat_w"], 8000.0)
        return d

    lib.case_dict = case_dict_big_cap

    def q_solar(self, solar_radiation_wm2):
        q_full = self.eta_solar * self.A_window * solar_radiation_wm2
        STATE["q_full_w"] = q_full
        return (1.0 - STATE["f"]) * q_full

    def _rc3_nodes(self):
        st = getattr(self, "_rc3", None)
        if st is None:
            st = {"T_s": self._rc.T_m}
            self._rc3 = st
        return st

    def step_mass(self, T_ext, T_z, dt):
        rc = self._rc
        q_sol_m = STATE["f"] * STATE["q_full_w"]
        if RC3["on"]:
            st = _rc3_nodes(self)
            T_s = st["T_s"]
            c_s = RC3["c_s"]
            g_sm = RC3["g_sm"]
            g_sa = rc.g_im  # g_im doubles as the surface->air film conductance
            q_s = q_sol_m + g_sm * (rc.T_m - T_s) + g_sa * (T_z - T_s)
            q_m = g_sm * (T_s - rc.T_m) + rc.g_em * (T_ext - rc.T_m)
            T_s_new = T_s + q_s * dt / (c_s * 3600.0)
            T_m_new = rc.T_m + q_m * dt / (rc.C_mass * 3600.0)
            for nm, v in (("surface", T_s_new), ("mass", T_m_new)):
                if not (-100.0 <= v <= 100.0):
                    raise RuntimeError(
                        f"RC3 {nm} node diverged to {v:.1f} C "
                        f"(T_s={T_s:.1f}, T_m={rc.T_m:.1f}, q_sol="
                        f"{q_sol_m:.0f} W, g_sa={g_sa}, g_sm={g_sm}, "
                        f"C_s={c_s}, C_m={rc.C_mass}, g_em={rc.g_em})")
            st["T_s"] = T_s_new
            rc.T_m = T_m_new
            return T_s_new
        q_net = (
            rc.g_em * (T_ext - rc.T_m)
            + rc.g_im * (T_z - rc.T_m)
            + q_sol_m
        )
        T_new = rc.T_m + q_net * dt / (rc.C_mass * 3600.0)
        if not (-100.0 <= T_new <= 100.0):
            raise RuntimeError(
                f"Mass-node temperature diverged to {T_new:.1f} C (solar-split "
                f"patch: f={STATE['f']}, Q_sol={STATE['q_full_w']:.0f} W, "
                f"C_mass={rc.C_mass:.1f}, g_im={rc.g_im:.1f}, g_em={rc.g_em:.1f})"
            )
        rc.T_m = T_new
        return T_new

    def q_wall(self, T_ext, T_z, T_m=None):
        if self._rc is None or T_m is None:
            return orig_q_wall(self, T_ext, T_z, T_m)
        if RC3["on"]:
            st = _rc3_nodes(self)
            return (self.U_wall_A * (T_ext - T_z)
                    + self._rc.g_im * (st["T_s"] - T_z))
        return orig_q_wall(self, T_ext, T_z, T_m)

    def reset(self, T_init):
        out = orig_reset(self, T_init)
        if RC3["on"] and self._rc is not None:
            getattr(self, "_rc3", {"T_s": T_init})["T_s"] = float(T_init)
            self._rc3 = {"T_s": float(T_init)}
        return out

    env_mod.Envelope.Q_solar = q_solar
    env_mod.Envelope.step_mass = step_mass
    env_mod.Envelope.Q_wall = q_wall
    env_mod.Envelope.reset = reset
    return env_mod, {
        "Q_solar": orig_q_solar,
        "step_mass": orig_step_mass,
        "Q_wall": orig_q_wall,
        "reset": orig_reset,
        "case_dict": orig_case_dict,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--case", nargs="+", default=["600"],
                    choices=["600", "600FF", "900", "900FF"])
    ap.add_argument("--f", nargs="*", type=float, default=[0.0],
                    help="f_split grid (solar fraction into mass node)")
    ap.add_argument("--gim", nargs="*", type=float, default=[None],
                    help="g_im grid (W/K); default = INITIAL_RC value")
    ap.add_argument("--eta", nargs="*", type=float, default=[None],
                    help="eta_solar grid; default = INITIAL_RC value")
    ap.add_argument("--cmass", nargs="*", type=float, default=[None],
                    help="C_mass grid (Wh/K); default = INITIAL_RC value")
    ap.add_argument("--gem", nargs="*", type=float, default=[None],
                    help="g_em grid (W/K); default = INITIAL_RC value")
    ap.add_argument("--cz", nargs="*", type=float, default=[None])
    ap.add_argument("--rc3", action="store_true",
                    help="emulated 2R3C: air --g_sa(--gim)-- surface(C_s, "
                         "--cs) --g_sm-- mass(C_m); solar -> surface node "
                         "(f is forced 1.0)")
    ap.add_argument("--gsm", nargs="*", type=float, default=[None],
                    help="[rc3] surface->mass conductance (W/K)")
    ap.add_argument("--cs", nargs="*", type=float, default=[None],
                    help="[rc3] surface-node capacity (Wh/K)")
    args = ap.parse_args()

    RC3["on"] = args.rc3
    if args.rc3:
        STATE["f"] = 1.0  # LBNL rule: all solar to the surface node
    if args.rc3 and (args.gsm == [None] or args.cs == [None]):
        ap.error("--rc3 requires --gsm and --cs")

    env_mod, orig = install_patch()
    df = lib.load_epw(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "USA_CO_Denver.Intl.AP.725650_TMY3.epw"))

    rows = []
    try:
        for f in args.f:
            STATE["f"] = 1.0 if args.rc3 else f
            for gim in args.gim:
                for eta in args.eta:
                    for cmass in args.cmass:
                        for gem in args.gem:
                            for cz in args.cz:
                                for gsm in args.gsm:
                                    for cs in args.cs:
                                        RC3["g_sm"] = float(gsm or 0.0)
                                        RC3["c_s"] = float(cs or 0.0)
                                        for case in args.case:
                                            print(f"[run] {case} f={f} g_im={gim} "
                                                  f"eta={eta} C_m={cmass} "
                                                  f"g_sm={gsm} C_s={cs} ...", flush=True)
                                            res = lib.run_case(
                                                case, df, eta_solar=eta, gim=gim,
                                                cmass=cmass, gem=gem, cz=cz, rc=True)
                                            rows.append((f, gim, eta, cmass, gsm, cs, res))
                                            print(f"      heat {res.annual_heating_gj:.3f} "
                                                  f"cool {res.annual_cooling_gj:.3f} GJ  "
                                                  f"h-h {res.extra['heating_hours']:.0f}  "
                                                  f"T {res.min_t:.1f}/{res.mean_t:.1f}/"
                                                  f"{res.max_t:.1f}", flush=True)
    finally:
        STATE["f"] = 0.0
        RC3["on"] = False
        env_mod.Envelope.Q_solar = orig["Q_solar"]
        env_mod.Envelope.step_mass = orig["step_mass"]
        env_mod.Envelope.Q_wall = orig["Q_wall"]
        env_mod.Envelope.reset = orig["reset"]
        lib.case_dict = orig["case_dict"]

    ff = all(c.endswith("FF") for c in args.case)
    if ff:
        print("\nf | g_sa | eta | C_m | g_sm | C_s | case | minT | maxT | "
              "meanT | verdicts")
    else:
        print("\nf | g_sa | eta | C_m | g_sm | C_s | case | heatGJ | coolGJ | "
              "heat-h | cool-h | pkH kW | pkC kW | V_h | V_c | V_pkH | V_pkC")
    for f, gim, eta, cmass, gsm, cs, res in rows:
        ex = res.extra
        pfx = f"{f} | {gim} | {eta} | {cmass} | {gsm} | {cs} | {res.case} | "
        if res.case.endswith("FF"):
            bands = lib.REF[res.case]
            v = lambda key, val: lib.verdict(val, bands[key])  # noqa: E731
            print(pfx + f"{res.min_t:.2f} | {res.max_t:.2f} | {res.mean_t:.2f} | "
                  f"{v('min_t', res.min_t)}/{v('max_t', res.max_t)}/"
                  f"{v('mean_t', res.mean_t)}")
        else:
            bands = lib.REF[res.case]
            vh = lib.verdict(res.annual_heating_gj, bands["annual_heating_gj"])
            vc = lib.verdict(res.annual_cooling_gj, bands["annual_cooling_gj"])
            ph = lib.verdict(res.peak_heating_kw, bands["peak_heating_kw"])
            pc = lib.verdict(res.peak_cooling_kw, bands["peak_cooling_kw"])
            print(pfx + f"{res.annual_heating_gj:.3f} | {res.annual_cooling_gj:.3f} | "
                  f"{ex['heating_hours']:.0f} | {ex['cooling_hours']:.0f} | "
                  f"{res.peak_heating_kw:.2f} | {res.peak_cooling_kw:.2f} | "
                  f"{vh} | {vc} | {ph} | {pc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
