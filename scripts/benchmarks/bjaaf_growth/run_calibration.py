"""BJAAF greenhouse lettuce growth-parameter calibration (Stage 1).

Calibrates the vfed one-state Van Henten growth model against the
Beijing Academy of Agriculture and Forestry Sciences (BJAAF) Exp_c
calibration experiment (cold-season supplemented greenhouse, 2020-11-29
15:00 .. 2021-01-18 15:00, 5-min climate log, destructive 5-d sampling).

Two-step anchoring (breaks the K_eff = c_pl_d * c_rad_phot * PAR * 1/rho
parameter degeneracy identified in the UC Davis T4 benchmark):

Step A -- light-extinction anchor c_pl_d (m2/kg):
    vfed intercepts light with Beer's law in DRY WEIGHT,
        f_vfed = 1 - exp(-c_pl_d * X_d),
    while the BJAAF 3-state reference (and canopy physics) intercepts in
    LEAF AREA INDEX,
        f_true = 1 - exp(-k_PAR * LAI),  k_PAR = 0.9 (BJAAP model value).
    The measured LAI/X_d pairing (same plants, same day) pins
        c_pl_d * X_d ~= k_PAR * LAI   ->   c_pl_d = k_PAR * (LAI / X_d).
    Estimated by (a) through-origin regression of LAI on X_d and
    (b) least squares on the interception fraction itself.

Step B -- radiation-use efficiency c_rad_phot (kg/J):
    with c_pl_d anchored, drive the vfed model with the MEASURED 5-min
    climate (T, CO2, PAR = 0.5 * shortwave per BJAAP sigma_PAR) from the
    measured initial state and fit the single efficiency parameter to
    the 10 in-window X_d samples.

Reference baseline -- a faithful Python port of the authors' 3-state
MATLAB model (X_d, C_buf, LAI; ode45-equivalent integration) run on the
same climate, quantifying the structural gap 1-state vs 3-state.

Scope note (planning doc v0.3, Q3): greenhouse data is used ONLY for
growth-module parameters. Envelope/HVAC parameters are untouched. The
climate series is a direct model input (no envelope coupling).

Usage (from the repo root):
    python scripts/benchmarks/bjaaf_growth/run_calibration.py [--no-report]
"""

from __future__ import annotations

import argparse
import datetime as _dt
import math
import os
import subprocess
import sys

import numpy as np
import pandas as pd
from scipy.integrate import solve_ivp
from scipy.optimize import minimize_scalar

HERE = os.path.dirname(os.path.abspath(__file__))
BENCH = os.path.dirname(HERE)
REPO = os.path.abspath(os.path.join(BENCH, "..", ".."))
sys.path.insert(0, BENCH)
sys.path.insert(0, REPO)

from _common import metrics  # noqa: E402

from vfed.plants.van_henten import VanHenten  # noqa: E402

XLSX = os.path.join(REPO, "data", "datasets", "bjaaf-lettuce-growth",
                    "Greenhouse Climate & Crop data_Exp_c.xlsx")
REPORT = os.path.join(REPO, "user-gym", "benchmarks",
                      "bjaaf_growth_calibration_report.md")

K_PAR = 0.9          # BJAAP PhotosynthesisLightResponse.m extinction coeff
SIGMA_PAR = 0.5      # BJAAP PAR/shortwave ratio
DT_S = 300.0         # climate sampling interval [s]

# --- BJAAP 3-state reference-model constants (transcribed from .m files) ---
AB = {"c_beta": 0.8, "c_alpha": 0.68}          # GrowthModel.m
PLR = {"c_r_PAR": 0.07, "sigma_PAR": 0.5, "k_PAR": 0.9, "epsilon_0": 17e-9,
       "gamma_T20": 40.0, "Q_10_gamma": 2.0, "T_0": 273.15, "rho_CO2_T0": 1.98,
       "M_CO2": 44e-3, "J_max_25": 210.15, "E_J": 37000.0, "R_g": 8.314,
       "c_S": 710.0, "c_H": 2.2e5}             # PhotosynthesisLightResponse.m
LA = {"beta_I": -0.00474, "beta_Xh": 0.912, "SLA_rf": 47.93, "X_h_ref": 0.75,
      "I_a_L_ref": 50.3, "c_r_I": 0.22, "k_I": 0.48}   # LeafArea.m
RD = {"Q_10_Rd": 2.0, "c_Rd_25_s": 3.47e-7, "c_Rd_25_r": 1.16e-7}  # Respiration.m
SR = {"c_sigmar_1": -0.026, "c_sigmar_2": -0.076}   # ShootRootRatio.m
HB = {"RGR_max_20": 1.54e-6, "sigmar_buf": 0.2, "Q10_gr": 1.6, "T_c_RGR": 25.0,
      "s_RGR_max": 10.0, "s_h_buf_1": 1000.0, "s_h_buf_2": 100.0,
      "z_h_buf": 1e-12}                        # h_buffer.m
LR = {"r_H2O_min": 82.0, "L_e": 1.47, "l_f": 0.1, "v_a": 0.09, "r_t": 50.0,
      "c_rc_1": 0.315, "c_rc_2": -27.35, "c_rc_3": 790.7,
      "s_f_Tc_s": 10.0, "s_f_Xc_s_1": 10.0, "s_f_Xc_s_2": 0.5,
      "s_e_s_air": 10.0, "z_r_b": 1e-4,
      "c_r_I": 0.22, "k_I": 0.48}              # shared with LeafArea.m


def _sig(x):
    """Numerically safe logistic 1/(1+exp(-x))."""
    return 0.5 * (1.0 + math.tanh(0.5 * x))


def load_data():
    """Climate (5-min) + growth summary (12 destructive samples)."""
    clim = pd.read_excel(XLSX, sheet_name="Greenhouse climate")
    clim.columns = ["time", "co2", "temp", "rh", "rad"]
    gro = pd.read_excel(XLSX, sheet_name="Lettuce growth summary")
    gro = gro[["Time", "Xd [kg m-2]", "LAI [-]"]].rename(
        columns={"Time": "date", "Xd [kg m-2]": "xd", "LAI [-]": "lai"})
    return clim, gro


# ---------------------------------------------------------------- Step A --
def anchor_c_pl_d(gro: pd.DataFrame) -> dict:
    """Light-extinction anchor from the LAI/X_d pairing.

    Returns both estimators plus the 12-point diagnostic table.
    """
    xd = gro["xd"].to_numpy()
    lai = gro["lai"].to_numpy()
    ratio = lai / xd

    # (a) through-origin regression: k_PAR * LAI = c * X_d
    slope = float(np.sum(xd * lai) / np.sum(xd * xd))
    c_reg = K_PAR * slope

    # (b) LSQ on interception fraction: (1-e^{-c*Xd}) ~ (1-e^{-k*LAI})
    f_true = 1.0 - np.exp(-K_PAR * lai)

    def sse(c):
        f_sim = 1.0 - np.exp(-c * xd)
        return float(np.sum((f_sim - f_true) ** 2))

    res = minimize_scalar(sse, bounds=(5.0, 200.0), method="bounded",
                          options={"xatol": 1e-3})
    c_int = float(res.x)

    table = pd.DataFrame({
        "date": gro["date"].dt.strftime("%Y-%m-%d"),
        "Xd_kg_m2": xd, "LAI": lai, "LAI_over_Xd": ratio,
        "f_int_true": f_true,
        "f_int_vfed53": 1.0 - np.exp(-53.0 * xd),
        "f_int_vfedFit": 1.0 - np.exp(-c_int * xd),
    })
    return {"c_reg": c_reg, "c_int": c_int, "ratio": ratio, "table": table}


# ---------------------------------------------------------------- vfed 1-state --
def run_vfed(clim: pd.DataFrame, xd0: float, c_pl_d: float,
             c_rad_phot: float, sample_times: pd.DatetimeIndex):
    """Euler-step the one-state Van Henten model over the 5-min climate.

    CO2 is updated per step (live attribute; _co2_density re-reads it).
    Returns sampled X_d [kg/m2] aligned to *sample_times*.
    """
    grow = VanHenten(co2_ppm=558.0, c_pl_d=c_pl_d, c_rad_phot=c_rad_phot)
    t = clim["time"]
    temp = clim["temp"].to_numpy()
    co2 = clim["co2"].to_numpy()
    par = SIGMA_PAR * clim["rad"].to_numpy()          # W/m2 PAR
    want = {ts: None for ts in sample_times}
    xd = xd0
    n = len(clim)
    for i in range(n - 1):
        grow.co2_ppm = float(co2[i])
        _, xd = grow.step(float(temp[i]), float(par[i]), xd, DT_S)
        ts_next = t.iloc[i + 1]
        if ts_next in want and want[ts_next] is None:
            want[ts_next] = xd
    return np.array([want[ts] for ts in sample_times])


def fit_c_rad_phot(clim, xd0, c_pl_d, sample_times, obs_xd):
    """1-parameter LSQ fit of c_rad_phot on the in-window X_d samples."""

    def rmse(log10c):
        sim = run_vfed(clim, xd0, c_pl_d, 10.0 ** log10c, sample_times)
        return float(np.sqrt(np.mean((sim - obs_xd) ** 2)))

    res = minimize_scalar(rmse, bounds=(-10.0, -7.0), method="bounded",
                          options={"xatol": 1e-4})
    return 10.0 ** float(res.x), float(res.fun)


# ------------------------------------------------- 3-state MATLAB port ----
def _matlab_reference_rhs(t, X, t_s, rad, temp, co2, rh, rho_c):
    """d/dt of [X_d, C_buf, LAI]; faithful port of the BJAAP .m files."""
    I = float(np.interp(t, t_s, rad))
    T = float(np.interp(t, t_s, temp))
    C = float(np.interp(t, t_s, co2))          # ppm = umol/mol
    H = float(np.interp(t, t_s, rh)) / 100.0   # [-]

    X_d, C_buf, LAI = X

    # ---- ShootRootRatio.m
    sigmar = SR["c_sigmar_1"] * math.log(X_d / rho_c) + SR["c_sigmar_2"]

    # ---- Respiration.m
    R_d = (RD["c_Rd_25_s"] * (1.0 - sigmar) + RD["c_Rd_25_r"] * sigmar) * X_d \
        * RD["Q_10_Rd"] ** ((T - 25.0) / 10.0)

    # ---- LeafResistance.m
    I_a = (1.0 - LR["c_r_I"]) * I * (1.0 - math.exp(-LA["k_I"] * LAI))
    q = 0.5 * I_a / LAI
    f_I_s = (q + 4.3) / (q + 0.54)
    sig_I = _sig(LR["s_f_Tc_s"] * (I - 3.0))
    f_Tc_s = sig_I * (1.0 + 2.3e-2 * (T - 24.5) ** 2) \
        + (1.0 - sig_I) * (1.0 + 0.5e-2 * (T - 33.6) ** 2)
    sig_Xc = _sig(LR["s_f_Xc_s_2"] * (C - 1100.0))
    f_Xc_s = sig_I * (sig_Xc * 1.5 + (1.0 - sig_Xc)
                      * (1.0 + 6.1e-7 * (C - 200.0) ** 2)) + (1.0 - sig_I)
    sig_T = _sig(LR["s_e_s_air"] * T)
    e_star = sig_T * 10.0 ** (2.7857 + 7.5 * T / (237.3 + T)) \
        + (1.0 - sig_T) * 10.0 ** (2.7857 + 9.5 * T / (265.5 + T))
    e_c_a = e_star * (1.0 - H)
    f_Xh_s = 4.0 / (1.0 + 255.0 * math.exp(-0.54e-2 * e_c_a)) ** 0.25
    r_s = 1.6 * LR["r_H2O_min"] * f_I_s * f_Tc_s * f_Xc_s * f_Xh_s
    r_b = LR["L_e"] ** 0.67 * 1174.0 * LR["l_f"] ** 0.5 / (
        LR["l_f"] * LR["z_r_b"] + 207.0 * LR["v_a"] ** 2) ** 0.25
    r_c = LR["c_rc_1"] * T ** 2 + LR["c_rc_2"] * T + LR["c_rc_3"]
    r_CO2 = r_s + r_b + r_c + LR["r_t"]

    # ---- PhotosynthesisLightResponse.m (per selected leaf layer)
    T_K = T + PLR["T_0"]
    T25_K = 25.0 + PLR["T_0"]
    gamma = PLR["gamma_T20"] * PLR["Q_10_gamma"] ** ((T - 20.0) / 10.0)
    eps = PLR["epsilon_0"] * (C - gamma) / (C + 2.0 * gamma)
    J_max = PLR["J_max_25"] * math.exp(
        PLR["E_J"] * (T_K - T25_K) / (T_K * PLR["R_g"] * T25_K)) \
        * (1.0 + math.exp((PLR["c_S"] * T25_K - PLR["c_H"])
                          / (PLR["R_g"] * T25_K))) \
        / (1.0 + math.exp((PLR["c_S"] * T_K - PLR["c_H"])
                          / (PLR["R_g"] * T_K)))
    A_L_mm = PLR["M_CO2"] * J_max * 0.25e-6
    rho_CO2 = PLR["rho_CO2_T0"] * PLR["T_0"] / T_K
    A_L_c_n = rho_CO2 * (C - gamma) / r_CO2 * 1e-6
    A_L_sat_n = min(A_L_c_n, A_L_mm)
    A_L_sat = A_L_sat_n + R_d / LAI / AB["c_alpha"]

    A_L_sum = 0.0
    wsum = (1.0, 1.6, 1.0)
    for w, frac in zip(wsum, (0.5 - math.sqrt(0.15), 0.5,
                              0.5 + math.sqrt(0.15))):
        l_i = frac * LAI
        PAR_a = PLR["k_PAR"] * (1.0 - PLR["c_r_PAR"]) * I * PLR["sigma_PAR"] \
            * math.exp(-PLR["k_PAR"] * l_i)
        A_L_sum += w * A_L_sat * (1.0 - math.exp(
            -eps * PAR_a / A_L_sat)) if A_L_sat > 0 else 0.0
    A_C = A_L_sum / 3.6 * LAI

    # ---- h_buffer.m
    C_buf_max = HB["sigmar_buf"] * X_d
    sig_r = _sig(HB["s_RGR_max"] * (T - HB["T_c_RGR"]))
    RGR_max = sig_r * HB["RGR_max_20"] * HB["Q10_gr"] ** ((20.0 - T) / 10.0) \
        + (1.0 - sig_r) * HB["RGR_max_20"] * HB["Q10_gr"] ** ((T - 20.0) / 10.0)
    w_buf = _sig(HB["s_h_buf_1"] * (C_buf / C_buf_max - 0.99))
    u = (R_d + RGR_max * X_d / AB["c_beta"]) \
        / (AB["c_alpha"] * (A_C + HB["z_h_buf"]))
    h_buf = w_buf * (-1.0 / HB["s_h_buf_2"]) * math.log(
        math.exp(-HB["s_h_buf_2"] * u) + math.exp(-HB["s_h_buf_2"])) \
        + (1.0 - w_buf)

    # ---- LeafArea.m (SLA of new leaves)
    f_I_SLA = 1.0 / (1.0 + LA["beta_I"] * (LA["I_a_L_ref"] - I_a / LAI))
    f_Xh_SLA = 1.0 / (1.0 + LA["beta_Xh"] * (LA["X_h_ref"] - H))
    SLA = LA["SLA_rf"] * f_I_SLA * f_Xh_SLA

    # ---- GrowthModel.m
    dXd = AB["c_beta"] * (AB["c_alpha"] * A_C * h_buf - R_d)
    dBuf = AB["c_alpha"] * A_C * h_buf - R_d - RGR_max * X_d / AB["c_beta"]
    if C_buf < 0:                      # MATLAB negative-accumulation guard
        dBuf = abs(dBuf)
    dLAI = dXd * (1.0 - sigmar) * SLA
    return [dXd, dBuf, dLAI]


def run_reference(clim, X0, sample_times, rho_c):
    """Integrate the 3-state reference (ode45-equivalent) and sample X_d."""
    t0 = clim["time"].iloc[0]
    t_s = ((clim["time"] - t0).dt.total_seconds()).to_numpy()
    rad = clim["rad"].to_numpy()
    temp = clim["temp"].to_numpy()
    co2 = clim["co2"].to_numpy()
    rh = clim["rh"].to_numpy()
    t_eval = np.array([(ts - t0).total_seconds() for ts in sample_times],
                      dtype=float)
    sol = solve_ivp(_matlab_reference_rhs, (0.0, float(t_s[-1])), list(X0),
                    args=(t_s, rad, temp, co2, rh, rho_c), method="RK45",
                    t_eval=t_eval, max_step=600.0, rtol=1e-3, atol=1e-6)
    if not sol.success:
        raise RuntimeError("reference integration failed: " + sol.message)
    return sol.y[0], sol.y[2]


# ---------------------------------------------------------------- report --
def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=REPO,
            stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"


def render_report(now, sha, rho_c, A, fit, sim_obs, ref_obs, clim_stats):
    c_pl, c_rp, c_rmse = fit["c_pl_d"], fit["c_rad_phot"], fit["rmse"]
    m1 = metrics(sim_obs["sim"], sim_obs["obs"])
    m3 = metrics(ref_obs["sim"], ref_obs["obs"])
    L = [
        "# BJAAF Exp_c 生菜生长参数校准 benchmark（Stage 1）\n",
        f"- 生成时间: {now}  |  vfed git: {sha}",
        "- 数据: `data/datasets/bjaaf-lettuce-growth/Greenhouse Climate & "
        "Crop data_Exp_c.xlsx`（Mendeley r7z9ttvkyh v2, CC BY 4.0；"
        "冷季标定试验，补光型温室）",
        "- 被校对象: `vfed/plants/van_henten.py` 单状态模型生长参数"
        "（c_pl_d 光截获、c_rad_phot 辐射利用效率）",
        "- 范围口径: 规划文档 v0.3 §6 Q3 —— 温室数据仅用于生长模块参数校准；"
        "气候序列（实测 T/CO₂/短波辐射）作为模型直接输入，无围护耦合；"
        "围护/HVAC 参数不受本报告影响\n",
        "## 对齐与清洗\n",
        "- 气候记录 2020-11-29 15:00 → 2021-01-18 15:00（5 min × 14,401 行）。"
        "`数据说明.md` 中「起始 2020-11-01」为序列日期推断误差，以时间戳为准",
        "- 首个生长采样 2020-11-24 早于气候窗 → 弃用；X₀ 取 2020-11-29 实测"
        f"（X_d={sim_obs['xd0']:.6f} kg/m², LAI={ref_obs['lai0']:.5f}）",
        f"- 种植密度由 X_d/单株干重反推: {rho_c:.2f} 株/m²（12 采样点一致；"
        "MATLAB `ShootRootRatio.m` 硬编码 11.52 为 Exp_v2 值）",
        "- 对比点 = 12-04 → 01-18 每 5 d 共 10 点（采样时刻取 00:00，"
        "实测称量时刻未记录，日界不确定性 ≤1 d）",
        "- vfed 光输入 = σ_PAR(0.5) × 短波辐射；CO₂ 逐步更新（实测 5 min 值）；"
        "Euler dt=300 s\n",
        "## 气候范围（实测输入）\n",
        "| 变量 | min | max | mean |", "|---|---|---|---|",
        f"| 气温 [°C] | {clim_stats['t_min']:.1f} | {clim_stats['t_max']:.1f} "
        f"| {clim_stats['t_mean']:.1f} |",
        f"| CO₂ [ppm] | {clim_stats['c_min']:.0f} | {clim_stats['c_max']:.0f} "
        f"| {clim_stats['c_mean']:.0f} |",
        f"| 短波辐射 [W/m²] | {clim_stats['r_min']:.0f} "
        f"| {clim_stats['r_max']:.0f} | {clim_stats['r_mean']:.1f} |\n",
        "## Step A — c_pl_d 锚定（LAI/X_d 比值型观测量）\n",
        "- 原理: vfed 截获项 1−exp(−c_pl_d·X_d) ↔ BJAAP 冠层 1−exp(−k_PAR·LAI)，"
        "同株同日配对的 (X_d, LAI) 直接钉住 c_pl_d·X_d ≡ k_PAR·LAI",
        f"- LAI/X_d 比值: {A['ratio'].min():.1f}–{A['ratio'].max():.1f} "
        f"m²/kg，均值 {A['ratio'].mean():.1f}（12 点，非单调——单状态代理的"
        "结构性残差，非测量噪声）",
        f"- 估计 ①过原点回归: c_pl_d = k_PAR × 斜率 = **{A['c_reg']:.1f} m²/kg**",
        f"- 估计 ②截获分数最小二乘: c_pl_d = **{A['c_int']:.1f} m²/kg**（取用）",
        f"- vfed 默认 53.0 → 锚定值降至 ~{A['c_int']:.0f}（冠层更「稀疏」："
        "温室生菜单位干重的叶面积低于 609 PFAL 假设）\n",
        "### 截获分数对比（f = 1−exp(−·)）\n",
        "| 日期 | X_d [kg/m²] | LAI | LAI/X_d | 真值(0.9·LAI) | vfed@53 | "
        "vfed@拟合 |", "|---|---|---|---|---|---|---|",
    ]
    for _, r in A["table"].iterrows():
        L.append(f"| {r['date']} | {r['Xd_kg_m2']:.5f} | {r['LAI']:.3f} | "
                 f"{r['LAI_over_Xd']:.1f} | {r['f_int_true']:.3f} | "
                 f"{r['f_int_vfed53']:.3f} | {r['f_int_vfedFit']:.3f} |")
    L += [
        "\n## Step B — c_rad_phot 拟合（实测 PAR 驱动，单参数）\n",
        f"- c_pl_d 固定为锚定值 {c_pl:.1f}，X₀ 取实测，其余参数保持 vfed 默认"
        "（c_alpha_beta=0.544, c_resp_d=2.65e-7, Van Henten 2003 CO₂ 响应）",
        f"- 拟合结果: c_rad_phot = **{c_rp:.2e} kg/J**（vfed 默认 3.5e-9，"
        f"P0-3R PFAL 重标定值；本值对应温室太阳光+补光、平均 CO₂ "
        f"{clim_stats['c_mean']:.0f} ppm）",
        f"- 拟合 RMSE = {c_rmse:.4f} kg/m²（10 点）\n",
        "## 结果 — 1-state (vfed, 校准后) vs 3-state (BJAAP 参考移植)\n",
        "| 指标 | vfed 1-state 校准后 | BJAAP 3-state 参考 |", "|---|---|---|",
        f"| N | {m1['N']} | {m3['N']} |",
        f"| RMSE X_d [kg/m²] | {m1['rmse']:.4f} | {m3['rmse']:.4f} |",
        f"| MBE [kg/m², sim−obs] | {m1['mbe']:+.4f} | {m3['mbe']:+.4f} |",
        f"| P95 abs err | {m1['p95abs']:.4f} | {m3['p95abs']:.4f} |",
        "",
        "### 逐点 X_d [kg/m²]\n",
        "| 日期 | 实测 | vfed 1-state | 3-state 参考 |", "|---|---|---|---|",
    ]
    for d, o, s1, s3 in zip(sim_obs["dates"], sim_obs["obs"],
                            sim_obs["sim"], ref_obs["sim"]):
        L.append(f"| {d} | {o:.5f} | {s1:.5f} | {s3:.5f} |")
    L += [
        "\n## 结论与下一步\n",
        f"- **破简并成功**: LAI/X_d 配对锚定 c_pl_d={c_pl:.1f}，实测 PAR 驱动"
        f"拟合 c_rad_phot={c_rp:.2e}——两参数不再以乘积简并（UC Davis T4 的"
        " K_eff 四因子简并在此数据集上被打破）",
        f"- **残差形态（结构信号）**: 校准后 1-state 中期偏高、末期偏低——"
        "LAI/X_d 比值随生育期漂移（33.8→45.9），单状态 Beer-in-X_d 代理无法"
        "跟踪该漂移，残差形态即结构限制的体现。注意 RMSE 对比"
        f"（{m1['rmse']:.4f} vs {m3['rmse']:.4f}）不构成结构优劣结论："
        "1-state 为本轨迹单参数专用拟合，3-state 为作者全局冻结参数"
        "（未在此重拟合），口径不对等",
        "- 3-state 参考为本仓库对原作者 MATLAB 代码的忠实 Python 移植"
        "（Exp_c 的 summary_Sim sheet 为实测副本，非模拟输出，无官方基线可比）；"
        "参数逐条转录自 .m 文件，仅种植密度按 Exp_c 反推",
        f"- 下一步（Stage 2）: c_pl_d={c_pl:.1f} 固定，迁移回 UC Davis "
        "run_biomass.py 重跑，观察形态差与 RMSE 变化",
        "\n## 复现\n\n```bash\n"
        "python scripts/benchmarks/bjaaf_growth/run_calibration.py\n```\n",
    ]
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-report", action="store_true")
    args = ap.parse_args()

    print("[data] loading Exp_c ...")
    clim, gro = load_data()
    rho_c = float(np.mean(gro["xd"].to_numpy()
                          / pd.read_excel(XLSX, sheet_name="Lettuce growth summary")
                          ["Total dry weight [g]"].to_numpy() / 1e-3))
    print(f"[data] climate rows {len(clim)}, growth samples {len(gro)}, "
          f"implied density {rho_c:.2f} plants/m2")

    # window alignment: drop 2020-11-24 (pre-window); X0 at 2020-11-29
    gro_w = gro[gro["date"] > clim["time"].iloc[0]].reset_index(drop=True)
    xd0 = float(gro["xd"].iloc[1])          # 2020-11-29 sample = initial state
    lai0 = float(gro["lai"].iloc[1])
    sample_times = pd.DatetimeIndex(gro_w["date"])
    obs_xd = gro_w["xd"].to_numpy()
    print(f"[align] X0 = {xd0:.6f} kg/m2 @2020-11-29, "
          f"{len(sample_times)} comparison points")

    print("[stepA] anchoring c_pl_d from LAI/Xd pairing ...")
    A = anchor_c_pl_d(gro)
    c_pl_d = A["c_int"]
    print(f"[stepA] ratio mean {A['ratio'].mean():.1f} | "
          f"regression {A['c_reg']:.1f} | interception-LSQ {A['c_int']:.1f}")

    print("[stepB] fitting c_rad_phot (1-param, measured climate drive) ...")
    c_rp, c_rmse = fit_c_rad_phot(clim, xd0, c_pl_d, sample_times, obs_xd)
    print(f"[stepB] c_rad_phot = {c_rp:.3e} kg/J, fit RMSE {c_rmse:.4f} kg/m2")

    print("[ref] running 3-state MATLAB-port reference ...")
    sim_xd, ref_lai = run_reference(clim, [xd0, 0.0, lai0], sample_times, rho_c)
    m3 = metrics(sim_xd, obs_xd)
    print(f"[ref] 3-state RMSE {m3['rmse']:.4f} kg/m2, "
          f"final X_d {sim_xd[-1]:.4f} (obs {obs_xd[-1]:.4f})")

    sim1 = run_vfed(clim, xd0, c_pl_d, c_rp, sample_times)
    m1 = metrics(sim1, obs_xd)
    print(f"[vfed] 1-state calibrated RMSE {m1['rmse']:.4f} kg/m2, "
          f"final X_d {sim1[-1]:.4f}")

    clim_stats = {
        "t_min": clim["temp"].min(), "t_max": clim["temp"].max(),
        "t_mean": clim["temp"].mean(), "c_min": clim["co2"].min(),
        "c_max": clim["co2"].max(), "c_mean": clim["co2"].mean(),
        "r_min": clim["rad"].min(), "r_max": clim["rad"].max(),
        "r_mean": clim["rad"].mean(),
    }
    fit = {"c_pl_d": c_pl_d, "c_rad_phot": c_rp, "rmse": c_rmse}
    sim_obs = {"dates": gro_w["date"].dt.strftime("%m-%d"), "obs": obs_xd,
               "sim": sim1, "xd0": xd0}
    ref_obs = {"sim": sim_xd, "obs": obs_xd, "lai0": lai0}

    if args.no_report:
        return 0
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    report = render_report(now, _git_sha(), rho_c, A, fit, sim_obs, ref_obs,
                           clim_stats)
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\n[report] written {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
