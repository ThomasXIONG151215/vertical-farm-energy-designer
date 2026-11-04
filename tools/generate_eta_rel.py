"""Offline generator for ModuleSpec.eta_rel_nodes (G4 enhancement layer).

Method (see docs/references/pvbes-validation/anchors/low_irradiance.yaml):
  1. Fit the De Soto / CEC single-diode five reference parameters
     (I_L_ref, I_o_ref, a_ref, R_s, R_sh_ref) to each module's datasheet
     STC five-point plus temperature coefficients (least-squares on the
     four STC equations + beta_voc and gamma_pmp temperature matches).
  2. Sample the model at 25 C over G = 100..1000 W/m2, take
     eta_rel(G) = P(G) / (G/1000 * P(1000)), anchored so eta(1000)=1.
  3. For HJT (huasun) also run a PVsyst-style Rsh(G) sensitivity sweep
     (Rsh_0 in {2x, 4x, 8x} Rsh_ref, exponent 5.5) to expose the
     high-Rsh low-light uncertainty band that a constant-Rsh fit cannot
     identify from datasheet data alone.

Runtime vfed code never imports pvlib/scipy; this script is [dev] only.
Usage:  python tools/generate_eta_rel.py
"""

import sys

import numpy as np
from scipy.optimize import least_squares

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pvlib
from pvlib.pvsystem import calcparams_cec
from pvlib.singlediode import bishop88_mpp

K_B = 1.380649e-23
Q = 1.602176634e-19
T_REF = 25.0
G_REF = 1000.0
# Crystalline-silicon defaults used throughout SAM's CEC calculator.
EG_REF = 1.121
DEGD_T = -0.0002677

G_SAMPLE = np.array([100.0, 200.0, 400.0, 600.0, 800.0, 1000.0])

# Datasheet inputs beyond the STC five-point.  Sources:
#   huasun_himalaya  HSN-210-B132 DS730 datasheet (raw/datasheets/), 2026-11-02
#   longi_himo9_670m Hi-MO 9 LR8-66HYD 670 datasheet, 2026-11-02
#   jinko_jkm580n    JKM625-650N-66HL4M-BDV datasheet neighbor (comparison only)
MODULES = {
    "jinko_jkm580n": dict(  # TOPCon -- default baseline, curve NOT written back
        I_sc=13.98, V_oc=57.34, I_mp=12.66, V_mp=45.85,
        alpha_sc_pct=0.045, beta_voc_pct=-0.25, gamma_pmp=-0.0030,
        N_s=156,
    ),
    "huasun_himalaya": dict(  # HJT
        I_sc=18.35, V_oc=50.37, I_mp=17.26, V_mp=42.32,
        alpha_sc_pct=0.04, beta_voc_pct=-0.22, gamma_pmp=-0.0024,
        N_s=132,
    ),
    "longi_himo9_670m": dict(  # BC (HPBC platform, Hi-MO 9)
        I_sc=16.86, V_oc=50.12, I_mp=16.19, V_mp=41.38,
        alpha_sc_pct=0.050, beta_voc_pct=-0.200, gamma_pmp=-0.0026,
        N_s=132,
    ),
}


def _model_p(x, G, T_cell, alpha_sc_abs, rsh_0_factor=None):
    """P_mp of the single-diode model at (G, T_cell) for params x."""
    I_L_ref, I_o_ref, a_ref, R_s, R_sh_ref = x
    if rsh_0_factor is None:
        # plain CEC path (constant Rsh)
        params = calcparams_cec(
            G, T_cell, alpha_sc_abs,  # pvlib temp_cell is CELSIUS
            a_ref, I_L_ref, I_o_ref, R_sh_ref, R_s,
            EgRef=EG_REF, dEgdT=DEGD_T, Adjust=0.0,
        )
        p_mp = bishop88_mpp(*params)[2]  # (i_mp, v_mp, p_mp)
        return np.atleast_1d(p_mp)
    raise NotImplementedError


def _residuals(x, m, alpha_sc_abs, beta_voc_abs):
    I_L, I_o, a, R_s, R_sh = x
    I_sc, V_oc, I_mp, V_mp = m["I_sc"], m["V_oc"], m["I_mp"], m["V_mp"]
    # E1 at V=0
    r1 = I_sc - (I_L - I_o * (np.exp(I_sc * R_s / a) - 1.0) - I_sc * R_s / R_sh)
    # E2 at I=0
    r2 = I_L - I_o * (np.exp(V_oc / a) - 1.0) - V_oc / R_sh
    # E3 at MPP
    v_d = V_mp + I_mp * R_s
    r3 = I_mp - (I_L - I_o * (np.exp(v_d / a) - 1.0) - v_d / R_sh)
    # E4 dP/dV = 0 at MPP  (dI/dV = -I_mp/V_mp)
    didv = -(I_o / a * np.exp(v_d / a) + 1.0 / R_sh) / (
        1.0 + I_o * R_s / a * np.exp(v_d / a)
    )
    r4 = didv + I_mp / V_mp
    # E5 beta_voc: numeric Voc slope vs datasheet (K/V)
    dt = 2.0
    voc_25 = _voc(x, G_REF, T_REF, alpha_sc_abs)
    voc_hot = _voc(x, G_REF, T_REF + dt, alpha_sc_abs)
    if not np.isfinite(voc_25) or not np.isfinite(voc_hot):
        return [r1, r2, r3, r4, 1e3, 0.0]
    r5 = (voc_hot - voc_25) / dt - beta_voc_abs
    # E6 gamma_pmp: numeric Pmax slope vs datasheet (1/K)
    p_25 = float(_model_p(x, np.array([G_REF]), T_REF, alpha_sc_abs)[0])
    p_hot = float(_model_p(x, np.array([G_REF]), T_REF + dt, alpha_sc_abs)[0])
    r6 = (p_hot - p_25) / dt / p_25 - m["gamma_pmp"]
    return [r1, r2, r3, r4, r5, r6]


def _voc(x, G, T_cell, alpha_sc_abs):
    I_L, I_o, a, R_s, R_sh = x
    params = calcparams_cec(
        np.atleast_1d(G), np.atleast_1d(T_cell), alpha_sc_abs,  # Celsius
        a, I_L, I_o, R_sh, R_s, EgRef=EG_REF, dEgdT=DEGD_T, Adjust=0.0,
    )
    i_l, i_o, a_t, r_s, r_sh = params
    # solve I=0: Lambert-free bisection on V
    from scipy.optimize import brentq

    def f(v):
        return i_l[0] - i_o[0] * (np.exp(v / a_t[0]) - 1.0) - v / r_sh[0]

    hi = a_t[0] * np.log((i_l[0] + 1e-9) / (i_o[0] + 1e-30)) + 1.0
    if hi <= 1.0:
        hi = 2.0
    while f(hi) > 0.0 and hi < 1e4:  # expand bracket upward if needed
        hi *= 1.5
    if f(0.0) * f(hi) > 0:
        return np.nan  # caller: residual -> large via least_squares penalty
    return brentq(f, 0.0, hi, xtol=1e-9)


def fit_module(name, m):
    alpha_sc_abs = m["alpha_sc_pct"] / 100.0 * m["I_sc"]  # A/K
    beta_voc_abs = m["beta_voc_pct"] / 100.0 * m["V_oc"]  # V/K
    n_guess = 1.25
    a0 = n_guess * m["N_s"] * K_B / Q * (T_REF + 273.15)
    rs0 = 0.8 * (m["V_oc"] - m["V_mp"]) / m["I_mp"]
    rsh0 = m["V_oc"] / (0.0015 * m["I_sc"])
    x0 = [m["I_sc"], 1e-10, a0, rs0, rsh0]
    sol = least_squares(
        _residuals, x0, args=(m, alpha_sc_abs, beta_voc_abs),
        bounds=([0.1 * m["I_sc"], 1e-16, 0.3 * a0, 1e-4, 10.0],
                [2.0 * m["I_sc"], 1e-6, 3.0 * a0, 5.0, 1e6]),
        xtol=1e-14, ftol=1e-14, max_nfev=20000,
    )
    print(f"\n== {name} ==")
    print(f"  cost={sol.cost:.3e}  x={sol.x}")
    I_L, I_o, a, R_s, R_sh = sol.x
    # STC reproduction check
    p_stc = float(_model_p(sol.x, np.array([G_REF]), T_REF, alpha_sc_abs)[0])
    print(f"  P_stc model={p_stc:.2f} W vs datasheet {m['I_mp']*m['V_mp']:.2f} W"
          f"  (dev {100*(p_stc/(m['I_mp']*m['V_mp'])-1):+.3f}%)")
    eta = []
    p_ref = p_stc
    for G in G_SAMPLE:
        p = float(_model_p(sol.x, np.array([G]), T_REF, alpha_sc_abs)[0])
        eta.append(p / (G / G_REF * p_ref))
    nodes = [(float(g), round(e, 4)) for g, e in zip(G_SAMPLE, eta)]
    nodes[-1] = (1000.0, 1.0)
    print(f"  eta_rel_nodes = {nodes}")
    return sol.x, nodes, alpha_sc_abs


def pvsyst_sensitivity(name, x, alpha_sc_abs):
    """HJT band: replace constant Rsh with PVsyst Rsh(G) at G=200 W/m2."""
    I_L, I_o, a, R_s, R_sh_ref = x
    G = 200.0
    out = {}
    for k in (2.0, 4.0, 8.0):
        rsh_0 = R_sh_ref * k
        rsh_g = R_sh_ref + (rsh_0 - R_sh_ref) * np.exp(-5.5 * G / G_REF)
        params = calcparams_cec(
            np.array([G]), T_REF, alpha_sc_abs,  # Celsius
            a, I_L, I_o, rsh_g, R_s, EgRef=EG_REF, dEgdT=DEGD_T, Adjust=0.0,
        )
        p = float(bishop88_mpp(*params)[2][0])
        out[k] = p
    return out


def main():
    print(f"pvlib {pvlib.__version__}")
    results = {}
    for name, m in MODULES.items():
        x, nodes, alpha_sc_abs = fit_module(name, m)
        results[name] = (x, nodes)
        if name == "huasun_himalaya":
            # cross-kernel sensitivity at 200 W/m2 (const-Rsh baseline P)
            p_cec_200 = float(_model_p(x, np.array([200.0]), T_REF, alpha_sc_abs)[0])
            band = pvsyst_sensitivity(name, x, alpha_sc_abs)
            print(f"  HJT 200W/m2 CEC P={p_cec_200:.3f} W; PVsyst-Rsh(G) band:")
            for k, p in band.items():
                print(f"    Rsh0={k:.0f}xRsh_ref -> P={p:.3f} W "
                      f"({100*(p/p_cec_200-1):+.2f}% vs CEC)")
    print("\n-- writeback candidates (huasun & longi only; jinko stays None) --")
    for name in ("huasun_himalaya", "longi_himo9_670m"):
        print(f"{name}: {results[name][1]}")


if __name__ == "__main__":
    main()
