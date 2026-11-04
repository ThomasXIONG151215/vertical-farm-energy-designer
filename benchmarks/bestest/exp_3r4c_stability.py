"""3R4C chain explicit-Euler stability check (numpy eigenvalues).

State vector x = [T_s, T_m, T_w] (degC), explicit Euler with dt=60 s.
C' = C*3600 (J/K); g in W/K.
    dT_s = [ g_sa*(T_z-T_s) + g_sm*(T_m-T_s) + g_wm*(T_w-T_s) ] / C_s'
    dT_m = [ g_sm*(T_s-T_m) ]                                / C_m'
    dT_w = [ g_wm*(T_s-T_w) + g_we*(T_ext-T_w) ]             / C_w'
Air node (engine-integrated, scalar): dT_z = -(ua+g_sa+g_inf)/C_z' * T_z + ...
"""
import numpy as np

FAMILIES = {
    "600": dict(cz=60.0, cs=300.0, cm=535.0, cw=129.0,
                g_sa=384.0, g_sm=60.0, g_wm=71.0, g_we=67.7,
                ua=52.1, g_inf=0.0149 * 1005.0),
    "900": dict(cz=150.0, cs=2200.0, cm=1493.0, cw=1373.0,
                g_sa=750.0, g_sm=246.0, g_wm=75.0, g_we=71.2,
                ua=52.1, g_inf=0.0149 * 1005.0),
}

for name, p in FAMILIES.items():
    Cs, Cm, Cw, Cz = (p[k] * 3600.0 for k in ("cs", "cm", "cw", "cz"))
    A = np.array([
        [-(p["g_sa"] + p["g_sm"] + p["g_wm"]) / Cs, p["g_sm"] / Cs, p["g_wm"] / Cs],
        [p["g_sm"] / Cm, -p["g_sm"] / Cm, 0.0],
        [p["g_wm"] / Cw, 0.0, -(p["g_wm"] + p["g_we"]) / Cw],
    ])
    lam = np.linalg.eigvals(A)
    lam_max = max(abs(l.real) for l in lam)
    dt_max = 2.0 / lam_max
    lam_z = (p["ua"] + p["g_sa"] + p["g_inf"]) / Cz
    dt_max_z = 2.0 / lam_z
    print(f"[{name}] chain eigenvalues (1/s): "
          + ", ".join(f"{l.real:.3e}" if abs(l.imag) < 1e-12 else f"{l.real:.3e}{l.imag:+.3e}j"
                      for l in sorted(lam, key=lambda x: -abs(x))))
    print(f"[{name}] |lambda|max = {lam_max:.3e} 1/s  ->  dt_max(Euler) = {dt_max:.0f} s"
          f"   (operating dt = 60 s, margin {dt_max/60:.0f}x)")
    print(f"[{name}] air node lambda = {lam_z:.3e} 1/s  ->  dt_max = {dt_max_z:.0f} s"
          f"   (margin {dt_max_z/60:.0f}x)")
    print(f"[{name}] per-node diag check dt*|diag|: "
          f"T_s {60*(p['g_sa']+p['g_sm']+p['g_wm'])/Cs:.4f} "
          f"T_m {60*p['g_sm']/Cm:.4f} "
          f"T_w {60*(p['g_wm']+p['g_we'])/Cw:.4f} "
          f"T_z {60*lam_z:.4f}  (all << 0.5 required)")
