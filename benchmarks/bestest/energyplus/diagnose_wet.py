"""Diagnose 600p moisture divergence: monthly infiltration-carryout ledger.

W_z is rebuilt from (T_z, RH_z) via Magnus on BOTH sides so the humidity
ratio derivation is identical (X_d in vfed timeseries is crop dry mass,
NOT humidity ratio -- learned the hard way).

vfed carry-out:  m_dot * (W_z - W_ext) * 3600,  m_dot = ach*V*rho/3600.
E+ carry-out:    hourly 'Infiltration Latent Heat Loss Energy' [J] / L_v.

Reverse-engineering: assuming E+'s W_z == magnus_w(T_z, RH_z) from its own
csv, the implied mass flow m_dot_eff = loss_J / ((W_z-W_ext)*L_v*3600).
If m_dot_eff >> 0.0149 kg/s, E+'s infiltration air mass is the divergence.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
BESTEST = HERE.parent
REPO = BESTEST.parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(BESTEST))
import bestest_lib as lib  # noqa: E402

EPW = BESTEST / "USA_CO_Denver.Intl.AP.725650_TMY3.epw"
CSV = HERE / "out_case600p" / "eplusout.csv"

# Case 600 geometry / infiltration (mirrors bestest_lib case_dict)
ACH, VOL, RHO, P_HPA = 0.346, 129.6, 1.2, 835.0
M_DOT = ACH * VOL * RHO / 3600.0  # kg/s
L_V = 2.43e6  # J/kg approx latent heat


def magnus_w(t_c, rh_pct):
    es = 6.112 * np.exp(17.62 * t_c / (243.12 + t_c))
    e = es * rh_pct / 100.0
    return 0.622 * e / (P_HPA - e)


def main() -> None:
    df = lib.load_epw(str(EPW))
    print(f"[weather] {len(df)} rows  m_dot(vfed) = {M_DOT:.5f} kg/s")

    hourly: dict = {}
    print("[run] vfed 600p ...", flush=True)
    lib.run_case("600p", df, fd=True, hourly_out=hourly, wet=True)

    w_z_v = magnus_w(np.asarray(hourly["t_z"], float),
                     np.asarray(hourly["rh_z"], float))
    rh_v = np.asarray(hourly["rh_z"], float)
    deh_kwh = np.asarray(hourly["deh_kwh"], float)
    w_ext = magnus_w(df["temperature_2m"].to_numpy(float),
                     df["relative_humidity_2m"].to_numpy(float))
    print(f"[check] vfed W_z mean {w_z_v.mean()*1000:.2f} g/kg "
          f"(RH {rh_v.mean():.1f}%), W_ext mean {w_ext.mean()*1000:.2f}")

    net = M_DOT * (w_z_v - w_ext) * 3600.0
    v_loss = np.where(net > 0, net, 0.0)
    v_gain = np.where(net < 0, -net, 0.0)

    ep = pd.read_csv(CSV)
    ep.columns = [c.strip() for c in ep.columns]
    lcol = [c for c in ep.columns if "Infiltration Latent Heat Loss" in c][0]
    gcol = [c for c in ep.columns if "Infiltration Latent Heat Gain" in c][0]
    wcol = [c for c in ep.columns if "Removed Water" in c][0]
    rcol = [c for c in ep.columns if "Relative Humidity" in c][0]
    tcol = [c for c in ep.columns if "Mean Air Temperature" in c][0]
    e_loss_j = ep[lcol].astype(float).to_numpy()
    e_loss = e_loss_j / L_V
    e_gain = ep[gcol].astype(float).to_numpy() / L_V
    e_dh2o = ep[wcol].astype(float).to_numpy()
    e_rh = ep[rcol].astype(float).to_numpy()
    e_t = ep[tcol].astype(float).to_numpy()

    # E+ own W_z from its csv T/RH
    w_z_e = magnus_w(e_t, e_rh)

    # ---- reverse-engineer E+ implied mass flow on carry-out hours ----
    dw_e = w_z_e - w_ext
    mask = e_loss_j > 1e6  # meaningful carry-out hours only
    m_eff = e_loss_j[mask] / (np.maximum(dw_e[mask], 1e-6) * L_V * 3600.0)
    print(f"\n[reverse] E+ implied m_dot on {mask.sum()} carry-out h: "
          f"median {np.median(m_eff):.5f} p10 {np.percentile(m_eff,10):.5f} "
          f"p90 {np.percentile(m_eff,90):.5f} kg/s  (vfed {M_DOT:.5f})")

    print("\n== annual ledger (kg) ==")
    src = 7.08 * 365
    print(f"source           : {src:.0f} (200 W latent / L_v)")
    print(f"infil carry-out  : vfed {v_loss.sum():7.1f} | E+ {e_loss.sum():7.1f}")
    print(f"infil carry-in   : vfed {v_gain.sum():7.1f} | E+ {e_gain.sum():7.1f}")
    print(f"DEH water        : vfed {deh_kwh.sum()*2.0:7.1f} | E+ {e_dh2o.sum():7.1f}")
    print(f"balance vfed     : out {v_loss.sum()+deh_kwh.sum()*2.0:7.1f} vs {src:.0f}")
    print(f"balance E+       : out {e_loss.sum()+e_dh2o.sum():7.1f} vs {src:.0f}")

    months = np.asarray(df.index.month)
    print("\n== monthly carry-out kg / mean W_z g/kg ==")
    print("mon | v_loss | e_loss | ratio | Wz_v | Wz_e | dW_v | dW_e")
    for m in range(1, 13):
        i = months == m
        vl, el = v_loss[i].sum(), e_loss[i].sum()
        dwv = (w_z_v[i] - w_ext[i]).mean() * 1000
        dwe = (w_z_e[i] - w_ext[i]).mean() * 1000
        print(f" {m:2d} | {vl:6.0f} | {el:6.0f} | "
              f"{vl/max(el,1e-9):5.2f}x | {w_z_v[i].mean()*1000:5.2f} | "
              f"{w_z_e[i].mean()*1000:5.2f} | {dwv:5.2f} | {dwe:5.2f}")


if __name__ == "__main__":
    main()
