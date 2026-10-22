"""Three-state Van Henten lettuce growth model (X_d, C_buf, LAI).

Ported from the MATLAB reference model shipped with the BJAAF lettuce-growth
dataset (Beijing Academy of Agriculture and Forestry Sciences; Mendeley
DOI 10.17632/r7z9ttvkyh.2, ``Lettuce growth model program`` folder:
``MainProgram.m`` + 8 ``.m`` files).  The same equations were validated in
Python at script level (``scripts/benchmarks/bjaaf_growth/run_calibration.py``,
``run_validation.py``) and numerically qualified for vfed's 600 s explicit
Euler stepping in ``run_euler_check.py`` (max X_d deviation vs RK45
< 0.5 % on four tracks).

States
------
X_d   structural dry weight          (kg DM/m²)  — held by the caller
                                           (engine) and passed into step/fluxes
C_buf non-structural carbon buffer   (kg DM/m²)  — instance attribute
LAI   leaf area index                (m²/m²)     — instance attribute

Derivatives (per second)
------------------------
dX_d/dt = c_beta · (c_alpha · A_C · h_buf − R_d)
dC_buf/dt = c_alpha · A_C · h_buf − R_d − RGR_max · X_d / c_beta
dLAI/dt = dX_d/dt · (1 − sigmar) · SLA

A_C is canopy net photosynthesis in CO₂ currency, kg CO₂/(m²·s).  For the
M1 CO₂ balance (``vfed/devices/co2.py``) ``fluxes()`` returns

    phi = A_C · h_buf     (kg CO₂/(m²·s), used directly as S_phot_co2)
    resp = R_d            (kg DM/(m²·s),  converted with DM_TO_CO2 upstream)

which mirrors the 1-state contract (``vfed/plants/van_henten.py``).

Light convention
----------------
``light`` is canopy PAR in W/m² (same as the 1-state model).  The MATLAB
model consumes greenhouse shortwave ``I``; the shortwave-equivalent used by
the stomata/SLA terms is reconstructed as ``I = light / sigma_PAR``, and the
canopy quadrature uses ``k_PAR·(1−c_r_PAR)·light·e^(−k_PAR·l_i)`` so that
sigma_PAR cancels (identical to the benchmark proxy convention
``rad_sw = PAR / sigma_PAR``).

Parameter status (calibration labels, see vfed/calibration/)
------------------------------------------------------------
* Default values are the MATLAB authors' frozen global set (greenhouse,
  supplementary-lighting lettuce, Exp_c).
* ``epsilon_0`` = 17e-9 kg/J is the author value.  Transferring it to a PFAL
  recipe overestimates growth: UC Davis diagnosis +88 % endpoint vs observed;
  re-anchored value ≈ 7.3e-9 kg/J (structure-diagnosis report).  Treat
  ``epsilon_0`` as a TRANSFERABLE/conditional parameter per dataset.
* SLA_rf / sigmar constants are anchorable from paired LAI/X_d observations
  (BJAAF ``SLA calibration`` / ``Root ratio`` sheets).

Numerical guards
----------------
* Division-by-zero: LAI and X_d are floored at 1e-9 inside log/divisions.
* Negative buffer: C_buf may transiently go slightly negative under explicit
  Euler; the MATLAB guard ``dBuf = |dBuf| when C_buf < 0`` is preserved
  (no clamping — Step 1 verification: min ≈ −2e-4 kg/m², no oscillation).
"""

from __future__ import annotations

import math

__all__ = ["VanHenten3State"]


def _sig(x: float) -> float:
    """Smooth step used throughout the MATLAB reference: 0.5·(1+tanh(x/2))."""
    return 0.5 * (1.0 + math.tanh(0.5 * x))


class VanHenten3State:
    """Three-state growth model with the 1-state call signature.

    The caller owns X_d (single number, advanced by the engine); C_buf and
    LAI live on this instance and are advanced in lockstep inside ``step``.
    """

    _defaults = {
        # AB — conversion efficiencies (c_beta·c_alpha = 0.544, same product
        # as the 1-state c_alpha_beta)
        "c_beta": 0.8,
        "c_alpha": 0.68,
        # PLR — photosynthesis light response
        "c_r_PAR": 0.07,
        "sigma_PAR": 0.5,
        "k_PAR": 0.9,
        "epsilon_0": 17e-9,
        "gamma_T20": 40.0,
        "Q_10_gamma": 2.0,
        "T_0": 273.15,
        "rho_CO2_T0": 1.98,
        "M_CO2": 44e-3,
        "J_max_25": 210.15,
        "E_J": 37000.0,
        "R_g": 8.314,
        "c_S": 710.0,
        "c_H": 2.2e5,
        # LA — leaf area
        "beta_I": -0.00474,
        "beta_Xh": 0.912,
        "SLA_rf": 47.93,
        "X_h_ref": 0.75,
        "I_a_L_ref": 50.3,
        "c_r_I": 0.22,
        "k_I": 0.48,
        # RD — respiration
        "Q_10_Rd": 2.0,
        "c_Rd_25_s": 3.47e-7,
        "c_Rd_25_r": 1.16e-7,
        # SR — shoot/root fraction
        "c_sigmar_1": -0.026,
        "c_sigmar_2": -0.076,
        # HB — carbon buffer
        "RGR_max_20": 1.54e-6,
        "sigmar_buf": 0.2,
        "Q10_gr": 1.6,
        "T_c_RGR": 25.0,
        "s_RGR_max": 10.0,
        "s_h_buf_1": 1000.0,
        "s_h_buf_2": 100.0,
        "z_h_buf": 1e-12,
        # LR — leaf resistance (CO₂ pathway)
        "r_H2O_min": 82.0,
        "L_e": 1.47,
        "l_f": 0.1,
        "v_a": 0.09,
        "r_t": 50.0,
        "c_rc_1": 0.315,
        "c_rc_2": -27.35,
        "c_rc_3": 790.7,
        "s_f_Tc_s": 10.0,
        "s_f_Xc_s_1": 10.0,
        "s_f_Xc_s_2": 0.5,
        "s_e_s_air": 10.0,
        "z_r_b": 1e-4,
    }

    def __init__(
        self,
        co2_ppm: float = 800.0,
        rho_c: float = 11.5,
        initial_lai: float | None = None,
        **overrides: float,
    ) -> None:
        """Parameters follow the MATLAB frozen set; override any by name.

        Parameters
        ----------
        co2_ppm : float
            CO₂ concentration (ppm).  Live attribute — the caller may update
            it every step (M1 CO₂ balance feedback), like the 1-state model.
        rho_c : float
            Planting density (plants/m²).  Used by the shoot/root fraction
            sigmar = c_sigmar_1·ln(X_d/rho_c) + c_sigmar_2.
        initial_lai : float, optional
            LAI at reset (m²/m²).  When None, reset() derives it as
            x_d0 · 40 (40 m²/kg ≈ round of the BJAAF paired LAI/X_d mean
            37.6 m²/kg).  Per-dataset anchoring is preferred.
        """
        self.params = dict(self._defaults)
        unknown = set(overrides) - set(self._defaults)
        if unknown:
            raise ValueError(
                "Unknown VanHenten3State parameters: %s" % sorted(unknown)
            )
        self.params.update(overrides)
        self.co2_ppm = float(co2_ppm)
        self.rho_c = float(rho_c)
        self.initial_lai = initial_lai
        #: Live relative-humidity attribute (%) — set by the engine each step
        #: (``grow.rh_pct = RH_z``); defaults to 70 % like the proxy climate.
        self.rh_pct = 70.0
        # Internal states — created lazily on first step/fluxes/reset.
        self.C_buf: float | None = None
        self.LAI: float | None = None

    # ------------------------------------------------------------------
    # state lifecycle
    # ------------------------------------------------------------------
    def _initial_lai_for(self, x_d0: float) -> float:
        if self.initial_lai is not None:
            return float(self.initial_lai)
        return float(x_d0) * 40.0  # BJAAF LAI/X_d mean ≈ 37.6 → 40

    def _ensure_state(self, x_d0: float) -> None:
        """Lazily create C_buf/LAI on first use (mirrors engine warm start)."""
        if self.C_buf is None or self.LAI is None:
            self.C_buf = 0.0
            self.LAI = self._initial_lai_for(x_d0)

    def reset(self, x_d0: float) -> None:
        """Reset buffer/LAI at harvest (engine calls with X_d_init)."""
        self.C_buf = 0.0
        self.LAI = self._initial_lai_for(x_d0)

    # ------------------------------------------------------------------
    # derivatives
    # ------------------------------------------------------------------
    def _derivs(
        self, T_z: float, light: float, X_d: float
    ) -> tuple[float, float, float, float, float]:
        """Return (dX_d, dC_buf, dLAI, phi, resp) — all per-second rates."""
        p = self.params
        C = self.co2_ppm
        H = min(max(self.rh_pct / 100.0, 0.0), 1.0)
        lai = self.LAI if self.LAI is not None else self._initial_lai_for(X_d)
        lai_s = max(lai, 1e-9)
        xd_s = max(X_d, 1e-9)

        # Shortwave-equivalent for the I-based terms (vfed passes canopy PAR)
        I = light / p["sigma_PAR"]

        # shoot/root fraction & maintenance respiration
        sigmar = p["c_sigmar_1"] * math.log(xd_s / self.rho_c) + p["c_sigmar_2"]
        R_d = (
            p["c_Rd_25_s"] * (1.0 - sigmar) + p["c_Rd_25_r"] * sigmar
        ) * X_d * p["Q_10_Rd"] ** ((T_z - 25.0) / 10.0)

        # --- leaf resistance (CO₂ pathway) ------------------------------
        I_a = (1.0 - p["c_r_I"]) * I * (1.0 - math.exp(-p["k_I"] * lai_s))
        q = 0.5 * I_a / lai_s
        f_I_s = (q + 4.3) / (q + 0.54)
        sig_I = _sig(p["s_f_Tc_s"] * (I - 3.0))
        f_Tc_s = sig_I * (1.0 + 2.3e-2 * (T_z - 24.5) ** 2) + (1.0 - sig_I) * (
            1.0 + 0.5e-2 * (T_z - 33.6) ** 2
        )
        sig_Xc = _sig(p["s_f_Xc_s_2"] * (C - 1100.0))
        f_Xc_s = sig_I * (
            sig_Xc * 1.5 + (1.0 - sig_Xc) * (1.0 + 6.1e-7 * (C - 200.0) ** 2)
        ) + (1.0 - sig_I)
        sig_T = _sig(p["s_e_s_air"] * T_z)
        e_star = sig_T * 10.0 ** (2.7857 + 7.5 * T_z / (237.3 + T_z)) + (
            1.0 - sig_T
        ) * 10.0 ** (2.7857 + 9.5 * T_z / (265.5 + T_z))
        e_c_a = e_star * (1.0 - H)
        f_Xh_s = 4.0 / (1.0 + 255.0 * math.exp(-0.54e-2 * e_c_a)) ** 0.25
        r_s = 1.6 * p["r_H2O_min"] * f_I_s * f_Tc_s * f_Xc_s * f_Xh_s
        r_b = (
            p["L_e"] ** 0.67
            * 1174.0
            * p["l_f"] ** 0.5
            / (p["l_f"] * p["z_r_b"] + 207.0 * p["v_a"] ** 2) ** 0.25
        )
        r_c = p["c_rc_1"] * T_z ** 2 + p["c_rc_2"] * T_z + p["c_rc_3"]
        r_CO2 = r_s + r_b + r_c + p["r_t"]

        # --- biochemical light response ---------------------------------
        T_K = T_z + p["T_0"]
        gamma = p["gamma_T20"] * p["Q_10_gamma"] ** ((T_z - 20.0) / 10.0)
        eps = p["epsilon_0"] * (C - gamma) / (C + 2.0 * gamma)
        T25_K = 25.0 + p["T_0"]
        J_max = (
            p["J_max_25"]
            * math.exp(p["E_J"] * (T_K - T25_K) / (T_K * p["R_g"] * T25_K))
            * (1.0 + math.exp((p["c_S"] * T25_K - p["c_H"]) / (p["R_g"] * T25_K)))
            / (1.0 + math.exp((p["c_S"] * T_K - p["c_H"]) / (p["R_g"] * T_K)))
        )
        A_L_mm = p["M_CO2"] * J_max * 0.25e-6
        rho_CO2 = p["rho_CO2_T0"] * p["T_0"] / T_K
        A_L_c_n = rho_CO2 * (C - gamma) / r_CO2 * 1e-6
        A_L_sat_n = min(A_L_c_n, A_L_mm)
        A_L_sat = A_L_sat_n + R_d / lai_s / p["c_alpha"]

        # --- 3-layer Gaussian-Legendre canopy quadrature ----------------
        A_L_sum = 0.0
        root15 = math.sqrt(0.15)
        for w, frac in ((1.0, 0.5 - root15), (1.6, 0.5), (1.0, 0.5 + root15)):
            l_i = frac * lai
            PAR_a = (
                p["k_PAR"]
                * (1.0 - p["c_r_PAR"])
                * light
                * math.exp(-p["k_PAR"] * l_i)
            )
            if A_L_sat > 0.0:
                A_L_sum += w * A_L_sat * (1.0 - math.exp(-eps * PAR_a / A_L_sat))
        A_C = A_L_sum / 3.6 * lai  # kg CO₂/(m²·s)

        # --- carbon buffer regulation (sink-limited photosynthesis) -----
        C_buf = self.C_buf if self.C_buf is not None else 0.0
        C_buf_max = p["sigmar_buf"] * X_d
        sig_r = _sig(p["s_RGR_max"] * (T_z - p["T_c_RGR"]))
        RGR_max = (
            sig_r * p["RGR_max_20"] * p["Q10_gr"] ** ((20.0 - T_z) / 10.0)
            + (1.0 - sig_r) * p["RGR_max_20"] * p["Q10_gr"] ** ((T_z - 20.0) / 10.0)
        )
        w_buf = _sig(p["s_h_buf_1"] * (C_buf / C_buf_max - 0.99))
        u = (R_d + RGR_max * X_d / p["c_beta"]) / (
            p["c_alpha"] * (A_C + p["z_h_buf"])
        )
        h_buf = w_buf * (-1.0 / p["s_h_buf_2"]) * math.log(
            math.exp(-p["s_h_buf_2"] * u) + math.exp(-p["s_h_buf_2"])
        ) + (1.0 - w_buf)

        # --- specific leaf area -----------------------------------------
        f_I_SLA = 1.0 / (1.0 + p["beta_I"] * (p["I_a_L_ref"] - I_a / lai_s))
        f_Xh_SLA = 1.0 / (1.0 + p["beta_Xh"] * (p["X_h_ref"] - H))
        SLA = p["SLA_rf"] * f_I_SLA * f_Xh_SLA

        # --- assemble derivatives ---------------------------------------
        phi = A_C * h_buf  # kg CO₂/(m²·s) — M1 contract
        resp = R_d  # kg DM/(m²·s) — M1 contract (DM_TO_CO2 upstream)
        d_xd = p["c_beta"] * (p["c_alpha"] * phi - resp)
        d_buf = (
            p["c_alpha"] * phi - resp - RGR_max * X_d / p["c_beta"]
        )
        if C_buf < 0.0:
            d_buf = abs(d_buf)  # MATLAB guard, preserved verbatim
        d_lai = d_xd * (1.0 - sigmar) * SLA
        return d_xd, d_buf, d_lai, phi, resp

    # ------------------------------------------------------------------
    # public interface (1-state compatible)
    # ------------------------------------------------------------------
    def fluxes(
        self, T_z: float, light: float, X_d: float
    ) -> tuple[float, float]:
        """Read-only fluxes at current state — M1 CO₂ contract.

        Returns (phi, resp):
            phi  photosynthesis, kg CO₂/(m²·s) (use directly as S_phot_co2)
            resp maintenance respiration, kg DM/(m²·s) (×DM_TO_CO2 upstream)
        """
        self._ensure_state(X_d)
        _, _, _, phi, resp = self._derivs(T_z, light, X_d)
        return phi, resp

    def step(
        self, T_z: float, light: float, X_d: float, dt: float = 60.0
    ) -> tuple[float, float]:
        """Advance C_buf/LAI in lockstep and return (rate, X_d_new).

        Returns
        -------
        dX_d : float
            Instantaneous growth rate dX_d/dt (kg/(m²·s)) — same semantics
            as the 1-state ``VanHenten.step``.
        X_d_new : float
            Updated dry weight (kg/m²), floored at zero.
        """
        self._ensure_state(X_d)
        d_xd, d_buf, d_lai, _, _ = self._derivs(T_z, light, X_d)
        self.C_buf += d_buf * dt
        self.LAI += d_lai * dt
        X_d_new = max(0.0, X_d + d_xd * dt)
        return d_xd, X_d_new
