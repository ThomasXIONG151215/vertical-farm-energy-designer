"""R28 step-6 FD channel-level energy audit for the BESTEST controlled cases.

Run ONE dual-year FD case with per-substep instrumentation of every room heat
balance channel, then report:

  1. annual + monthly channel sums (GJ): wall (direct + film), infiltration
     (sensible + latent), solar (air share + wall share), radiant/convective
     internal gains, LED, HVAC heating/cooling;
  2. annual heat-balance closure residual (must be ~0 in periodic year 2);
  3. analytic steady-state anchors per channel (same formula the engine uses,
     evaluated on vfed's own T_z series) to expose any channel whose engine
     value deviates from its own analytic identity;
  4. slush evidence: hours (and energy) with heating AND cooling active in the
     same calendar month, HVAC min-modulation pulse statistics.

Usage:
    python exp_fd_audit.py 600
    python exp_fd_audit.py 600 --eta 0.5 --prated 3000 --prateat 3000
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd

import bestest_lib as lib
import vfed.design.engine as eng
import vfed.physics.ode as ode_mod
import vfed.physics.envelope as env_mod


WH2GJ = 3.6e-6  # Wh -> GJ


def build_project(case: str, df: pd.DataFrame, overrides: dict) -> tuple:
    """DesignProject for one FD case with harness parameter overrides."""
    import vfed.design.project as proj

    init = dict(lib.INITIAL_FD[case])
    d = lib.case_dict(
        case,
        cz=overrides.get("cz", init["cz"]),
        u_wall_a=overrides.get("ua", init["ua"]),
        eta_solar=overrides.get("eta", init["eta"]),
        free_float=case.endswith("FF"),
        fd=True,
        cmass=overrides.get("cmass", init["cmass"]),
        gsm=overrides.get("gsm", init["gsm"]),
        fs=overrides.get("fs", init["fs"]),
        nodes=overrides.get("nodes", init["nodes"]),
        layers=init["layers"],
        area=init["area"],
        h_ext=overrides.get("hext", init["h_ext"]),
        abs_sol=overrides.get("abs_sol", init["abs_sol"]),
        h_c=overrides.get("h_c", init["h_c"]),
        mod_band_c=overrides.get("band", 1.0),
    )
    if not case.endswith("FF"):
        hv = d["hvac"]
        hv["P_rated_w"] = overrides.get("prated", 8000.0)
        hv["P_rated_heat_w"] = overrides.get("prateat", 8000.0)
    d["led"]["power_w"] = overrides.get("led_w", 80.0)
    project = proj.DesignProject.from_dict(d)
    return project, d


def run_audit(case: str, df: pd.DataFrame, overrides: dict) -> dict:
    project, d = build_project(case, df, overrides)
    dt = project.space.timestep_s
    n = len(df)
    sub = int(round(3600.0 / dt))
    total = 2 * n
    nsub = total * sub

    env = None  # resolved at first engine callback
    rec = {
        "T_z": np.zeros(nsub),
        "T_ext": np.zeros(nsub),
        "T_rc": np.zeros(nsub),
        "T_z_post": np.zeros(nsub),
        "q_hvac": np.zeros(nsub),
        "q_src_wall": np.zeros(nsub),
        "i_ext": np.zeros(nsub),
        "mode_cool_substeps": np.zeros(nsub),
        "mode_heat_substeps": np.zeros(nsub),
        "mod_cool": np.zeros(nsub),
        "mod_heat": np.zeros(nsub),
    }
    state = {"i": 0, "env": None, "ext_h": 0.0}
    orig_hvac = eng.HVACDevice.step
    orig_sm = env_mod.Envelope.step_mass
    orig_tmax = ode_mod._DEFAULT_T_MAX

    ext_arr = lib.dual_year(df)["temperature_2m"].to_numpy(dtype=float)
    poa_hourly = lib.dual_year(df)["shortwave_radiation"].to_numpy(dtype=float)
    rh_ext_hourly = lib.dual_year(df)["relative_humidity_2m"].to_numpy(dtype=float)

    def patched_hvac(self, T_z, RH_z, T_ext, dt=60.0, **k):
        i = state["i"]
        state["ext_h"] = T_ext
        out = orig_hvac(self, T_z, RH_z, T_ext, dt, **k)
        j = min(i, nsub - 1)
        rec["T_z"][j] = T_z
        rec["T_ext"][j] = T_ext
        rec["q_hvac"][j] = out["Q_HVAC_W"]
        if out["mode"] == "cool" and out["mod"] > 0:
            rec["mode_cool_substeps"][j] = 1.0
            rec["mod_cool"][j] = out["mod"]
        elif out["mode"] == "heat" and out["mod"] > 0:
            rec["mode_heat_substeps"][j] = 1.0
            rec["mod_heat"][j] = out["mod"]
        return out

    def patched_sm(self, T_ext, T_z, dt, Q_source_w=0.0, I_ext_wm2=0.0):
        out = orig_sm(self, T_ext, T_z, dt, Q_source_w=Q_source_w,
                      I_ext_wm2=I_ext_wm2)
        j = min(state["i"], nsub - 1)
        rec["T_rc"][j] = out
        rec["T_z_post"][j] = T_z
        rec["q_src_wall"][j] = Q_source_w
        rec["i_ext"][j] = I_ext_wm2
        state["i"] += 1
        return out

    eng.HVACDevice.step = patched_hvac
    env_mod.Envelope.step_mass = patched_sm
    ode_mod._DEFAULT_T_MAX = 90.0
    try:
        engine = eng.DesignEngine()
        result = engine.run(project, weather=lib.dual_year(df))
    finally:
        eng.HVACDevice.step = orig_hvac
        env_mod.Envelope.step_mass = orig_sm
        ode_mod._DEFAULT_T_MAX = orig_tmax

    counts = min(state["i"], nsub)
    sl = slice(0, counts)
    T_z = rec["T_z"][sl]
    T_ext = rec["T_ext"][sl]
    T_rc = rec["T_rc"][sl]
    q_hvac = rec["q_hvac"][sl]
    hours = np.arange(counts) // sub  # hour index in the dual-year timeline
    months = np.asarray(result.timeseries["month"], dtype=float)
    month_sub = months[hours]  # per-substep month

    project_env = result  # engine result
    # Build a physics Envelope mirror (same params) for the channel constants.
    from vfed.physics.envelope import Envelope as _Env
    import inspect

    _sig = set(inspect.signature(_Env.__init__).parameters)
    env_kwargs = {k: v for k, v in d["envelope"].items() if k in _sig}
    env_consts = _Env(**env_kwargs)
    fd = env_consts._fd
    ua_direct = env_consts.U_wall_A
    g_c = fd.g_c
    g_ext = fd.G_ext
    m_dot = env_consts.ach * env_consts.V_room * env_consts.rho_air / 3600.0
    cp = env_consts.cp_air
    eta = env_consts.eta_solar
    a_win = env_consts.A_window
    f_m = env_consts.solar_mass_fraction
    U_fd = 1.0 / (1.0 / g_ext + float(np.sum(1.0 / fd.G_cond)) + 1.0 / g_c)

    from vfed.physics.psychrometrics import temp_rh_to_ah, latent_heat_vaporization

    rh_ext = np.repeat(rh_ext_hourly, sub)[:counts]
    poa_sub = np.repeat(poa_hourly, sub)[:counts]
    p_atm = float(df["surface_pressure"].mean())
    _ah = np.vectorize(lambda t, rh: temp_rh_to_ah(float(t), float(rh), pressure_kpa=p_atm))
    W_ext = _ah(T_ext, rh_ext)
    rh_z = np.asarray(result.timeseries["RH_z"], dtype=float)[hours]
    W_z = _ah(T_z, rh_z)

    q_wall_direct = ua_direct * (T_ext - T_z)
    q_wall_film = g_c * (T_rc - T_z)
    q_inf_sens = m_dot * cp * (T_ext - T_z)
    L_v = latent_heat_vaporization(T_z) * 1000.0
    q_inf_lat = m_dot * (W_ext - W_z) * L_v
    q_sol_full = eta * a_win * poa_sub
    q_sol_air = (1.0 - f_m) * q_sol_full
    q_sol_wall = f_m * q_sol_full
    q_src_wall = rec["q_src_wall"][sl]  # = q_sol_wall + 120 W radiant
    q_rad_equip = np.where(q_src_wall > 0, 120.0, 0.0) if True else None
    led_w = d["led"]["power_w"]
    q_led = np.full(counts, led_w)
    q_hvac_heat = np.where(q_hvac > 0, q_hvac, 0.0)
    q_hvac_cool = np.where(q_hvac < 0, q_hvac, 0.0)

    dtw = float(dt)
    def gj(x):
        return float(np.sum(x) * dtw * WH2GJ)

    t_os = T_ext + env_consts._fd_params["solar_abs"] * poa_sub / env_consts._fd_params["h_ext_wm2"]
    chan = {
        "hvac_heat": gj(q_hvac_heat),
        "hvac_cool": gj(-q_hvac_cool),
        "wall_direct": gj(q_wall_direct),
        "wall_film": gj(q_wall_film),
        "infil_sens": gj(q_inf_sens),
        "infil_lat": gj(q_inf_lat),
        "solar_air": gj(q_sol_air),
        "solar_wall": gj(q_sol_wall),
        "rad_equip": gj(np.full(counts, 120.0)),
        "led": gj(q_led),
        "sol_air_drive": gj(g_ext * (t_os - T_ext)),
    }
    # closure: sum of all room-balance channels (transp=0, deh=0)
    closure = (gj(q_hvac) + chan["wall_direct"] + chan["wall_film"]
               + chan["infil_sens"] + chan["infil_lat"] + chan["solar_air"]
               + chan["led"] + chan["rad_equip"] - chan["rad_equip"])  # radiant reaches the room THROUGH the wall film (step_mass source), not directly
    chan["closure_residual"] = closure

    # analytic identities on vfed's own states
    analytic = {
        "wall_direct_UdW_sumDT": ua_direct * float(np.sum(T_ext - T_z)) * dtw * WH2GJ,
        "wall_film_gcW_sumDTrc": g_c * float(np.sum(T_rc - T_z)) * dtw * WH2GJ,
        "infil_mdotcp_sumDT": m_dot * cp * float(np.sum(T_ext - T_z)) * dtw * WH2GJ,
        "solar_etaA_sumPOA": eta * a_win * float(np.sum(poa_hourly)) * dtw * WH2GJ,
        "wall_ss_UfdW_sumDtosTz": U_fd * float(np.sum(t_os - T_z)) * dtw * WH2GJ,
        "sumDT_extTz_Kh": float(np.sum(T_ext - T_z)) * dtw / 3600.0,
        "sumDT_solair_Kh": float(np.sum(t_os - T_z)) * dtw / 3600.0,
    }

    # monthly table (year 2 only)
    y2 = hours >= n
    mon_out = []
    for m in range(1, 13):
        sel = y2 & (month_sub == m)
        both = sel & (rec["mode_heat_substeps"][sl] > 0) & (rec["mode_cool_substeps"][sl] > 0)
        mon_out.append({
            "m": m,
            "heat": float(np.sum(q_hvac_heat[sel]) * dtw * WH2GJ),
            "cool": float(np.sum(-q_hvac_cool[sel]) * dtw * WH2GJ),
            "heat_h": float(np.sum(sel & (rec["mode_heat_substeps"][sl] > 0)) * dtw / 3600.0),
            "cool_h": float(np.sum(sel & (rec["mode_cool_substeps"][sl] > 0)) * dtw / 3600.0),
            "both_h": float(np.sum(both) * dtw / 3600.0),
            "solar": float(np.sum(q_sol_full[sel]) * dtw * WH2GJ),
            "Tz_mean": float(np.mean(T_z[sel])),
            "Text_mean": float(np.mean(T_ext[sel])),
        })

    # HVAC min-modulation pulse statistics (year 2)
    y2s = y2
    cool_on = rec["mod_cool"][sl] > 0
    heat_on = rec["mod_heat"][sl] > 0
    pulse = {
        "heat_on_frac_y2": float(np.mean(heat_on[y2s])),
        "cool_on_frac_y2": float(np.mean(cool_on[y2s])),
        "heat_mod_mean_when_on": float(np.mean(rec["mod_heat"][sl][heat_on])) if heat_on.any() else 0.0,
        "cool_mod_mean_when_on": float(np.mean(rec["mod_cool"][sl][cool_on])) if cool_on.any() else 0.0,
        "heat_min_q_w": float(np.min(q_hvac_heat[heat_on])) if heat_on.any() else 0.0,
        "cool_min_q_w": float(np.min(-q_hvac_cool[cool_on])) if cool_on.any() else 0.0,
    }

    return {
        "chan": chan,
        "analytic": analytic,
        "monthly": mon_out,
        "pulse": pulse,
        "consts": dict(ua_direct=ua_direct, g_c=g_c, g_ext=g_ext, U_fd=U_fd,
                       m_dot=m_dot, eta=eta, a_win=a_win, f_m=f_m, dt=dt,
                       cz=overrides.get("cz", lib.INITIAL_FD[case]["cz"]),
                       led_w=led_w, nsub=counts),
        "summary_tz": (float(np.min(np.asarray(result.timeseries["T_z"], dtype=float)[n:])),
                       float(np.mean(np.asarray(result.timeseries["T_z"], dtype=float)[n:])),
                       float(np.max(np.asarray(result.timeseries["T_z"], dtype=float)[n:]))),
    }


def run_probe(case: str, df: pd.DataFrame, overrides: dict) -> dict:
    """Fast probe: lib-style instrumented run (Q_HVAC only), KPI verdicts."""
    project, d = build_project(case, df, overrides)
    dt = project.space.timestep_s
    n = len(df)
    sub = int(round(3600.0 / dt))
    heat_wh = np.zeros(2 * n)
    cool_wh = np.zeros(2 * n)
    counter = {"i": 0}
    orig_hvac = eng.HVACDevice.step
    orig_sm = env_mod.Envelope.step_mass
    orig_tmax = ode_mod._DEFAULT_T_MAX

    def patched_hvac(self, T_z, RH_z, T_ext, dt=60.0, **k):
        out = orig_hvac(self, T_z, RH_z, T_ext, dt, **k)
        h = counter["i"] // sub
        if h < 2 * n:
            q = out["Q_HVAC_W"]
            if q >= 0.0:
                heat_wh[h] += q * dt / 3600.0
            else:
                cool_wh[h] += -q * dt / 3600.0
        counter["i"] += 1
        return out

    def patched_sm(self, T_ext, T_z, dt, Q_source_w=0.0, I_ext_wm2=0.0):
        return orig_sm(self, T_ext, T_z, dt, Q_source_w=Q_source_w + 120.0,
                       I_ext_wm2=I_ext_wm2)

    eng.HVACDevice.step = patched_hvac
    env_mod.Envelope.step_mass = patched_sm
    ode_mod._DEFAULT_T_MAX = 90.0
    try:
        result = eng.DesignEngine().run(project, weather=lib.dual_year(df))
    finally:
        eng.HVACDevice.step = orig_hvac
        env_mod.Envelope.step_mass = orig_sm
        ode_mod._DEFAULT_T_MAX = orig_tmax

    tz = np.asarray(result.timeseries["T_z"], dtype=float)[n:]
    h2, c2 = heat_wh[n:] / 1000.0, cool_wh[n:] / 1000.0
    metrics = ({"annual_heating_gj": h2.sum() * 0.0036,
                "annual_cooling_gj": c2.sum() * 0.0036,
                "peak_heating_kw": float(h2.max()),
                "peak_cooling_kw": float(c2.max())}
               if not case.endswith("FF") else
               {"min_t": float(tz.min()), "max_t": float(tz.max()),
                "mean_t": float(tz.mean())})
    verdicts = {k: lib.verdict(v, lib.REF[case][k]) for k, v in metrics.items()}
    return {"metrics": metrics, "verdicts": verdicts,
            "heat_h": float((h2 > 0).sum()), "cool_h": float((c2 > 0).sum())}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("case", nargs="?", default="600")
    ap.add_argument("--eta", type=float, default=None)
    ap.add_argument("--cz", type=float, default=None)
    ap.add_argument("--ua", type=float, default=None)
    ap.add_argument("--cmass", type=float, default=None)
    ap.add_argument("--gsm", type=float, default=None)
    ap.add_argument("--fs", type=float, default=None)
    ap.add_argument("--abs-sol", type=float, default=None, dest="abs_sol")
    ap.add_argument("--band", type=float, default=None)
    ap.add_argument("--prated", type=float, default=None,
                    help="HVAC cooling electrical rating (W)")
    ap.add_argument("--h-c", type=float, default=None, dest="h_c",
                    help="FD wall interior convective film (W/m2K)")
    ap.add_argument("--nodes", type=int, default=None, dest="nodes",
                    help="FD wall node count")
    ap.add_argument("--hext", type=float, default=None, dest="hext",
                    help="FD wall exterior film coefficient (W/m2K)")
    ap.add_argument("--prateat", type=float, default=None,
                    help="HVAC heating electrical rating (W)")
    ap.add_argument("--led-w", type=float, default=None, dest="led_w")
    ap.add_argument("--probe", action="store_true",
                    help="fast probe mode: KPI verdicts only, no full audit")
    args = ap.parse_args()

    df = lib.load_epw(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "USA_CO_Denver.Intl.AP.725650_TMY3.epw"))
    overrides = {k: v for k, v in dict(
        eta=args.eta, cz=args.cz, ua=args.ua, cmass=args.cmass, gsm=args.gsm,
        fs=args.fs, abs_sol=args.abs_sol, band=args.band,
        prated=args.prated, prateat=args.prateat, led_w=args.led_w, hext=args.hext, nodes=args.nodes, h_c=args.h_c,
    ).items() if v is not None}
    if args.probe:
        out = run_probe(args.case, df, overrides)
        m, v = out["metrics"], out["verdicts"]
        ms = "  ".join(f"{k}={val:.3f}[{v[k]}]" for k, val in m.items())
        print(f"[probe] {args.case} {overrides or '(initial FD)'} -> {ms} "
              f"heat-h {out['heat_h']:.0f} cool-h {out['cool_h']:.0f}")
        return 0
    out = run_audit(args.case, df, overrides)

    print(f"[audit] case {args.case} overrides={overrides or '(initial FD)'}")
    c = out["consts"]
    print(f"  consts: UA_direct={c['ua_direct']:.1f} g_c={c['g_c']:.1f} "
          f"g_ext={c['g_ext']:.1f} U_fd={c['U_fd']:.2f} W/K  m_dot={c['m_dot']*1000:.2f} g/s  "
          f"eta={c['eta']:.2f} f_m={c['f_m']:.2f} dt={c['dt']:.0f}s")
    print("\n  == annual channel sums (GJ) ==")
    for k, v in out["chan"].items():
        print(f"  {k:18s} {v:10.3f}")
    print("\n  == analytic identities ==")
    for k, v in out["analytic"].items():
        unit = " K.h" if k.startswith("sumDT") else " GJ"
        print(f"  {k:24s} {v:10.3f}{unit}")
    p = out["pulse"]
    print("\n  == HVAC pulse stats (year 2) ==")
    for k, v in p.items():
        print(f"  {k:24s} {v:10.3f}")
    print(f"\n  T_z year2: min {out['summary_tz'][0]:.2f} mean "
          f"{out['summary_tz'][1]:.2f} max {out['summary_tz'][2]:.2f}")
    print("\n  mo |  heat |  cool | heat_h | cool_h | both_h | solar | Tz_m | Text_m")
    for r in out["monthly"]:
        print(f"  {r['m']:2d} | {r['heat']:5.3f} | {r['cool']:5.3f} | "
              f"{r['heat_h']:6.0f} | {r['cool_h']:6.0f} | {r['both_h']:6.1f} | "
              f"{r['solar']:5.2f} | {r['Tz_mean']:5.2f} | {r['Text_mean']:6.2f}")
    h = sum(r["heat"] for r in out["monthly"])
    cl = sum(r["cool"] for r in out["monthly"])
    print(f"  yr | {h:5.3f} | {cl:5.3f} | heat_h {sum(r['heat_h'] for r in out['monthly']):.0f}"
          f" | cool_h {sum(r['cool_h'] for r in out['monthly']):.0f}"
          f" | both_h {sum(r['both_h'] for r in out['monthly']):.1f}"
          f" | solar {sum(r['solar'] for r in out['monthly']):.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
