"""
Van Henten 2003 one-state carbon-balance plant growth model.

Ported from :file:`reference/van-henten/grow_one_state2003.py`.
State variable: ``X_d`` (dry weight, kg/m²).  Driven by temperature, CO₂
concentration and light (binary photoperiod indicator).

Reference
---------
Van Henten, E.J. (2003). Sensitivity analysis of an optimal control problem in
greenhouse climate management. *Biosystems Engineering*, 85(3), 355–364.
"""

__all__ = ["VanHenten"]


class VanHenten:
    """One-state carbon-balance growth model (Van Henten 2003).

    Parameters
    ----------
    params : dict
        Model parameters (all SI units).  Defaults match the literature values.
        Keys: c_alpha_beta, c_resp_d, c_pl_d, c_rad_phot,
              c_co2_1, c_co2_2, c_co2_3, c_Gamma.
    co2_ppm : float
        Ambient CO₂ concentration during simulation (ppm).
    P_atm : float
        Station pressure (kPa, default 101.325).  Used with the canopy
        temperature to compute the CO₂ mass density (P3-11).
    """

    # literature defaults  (all SI)
    _defaults = {
        "c_alpha_beta": 0.544,      # dimensionless conversion efficiency
        "c_resp_d": 2.65e-7,        # s⁻¹  dark respiration coefficient (25 °C)
        "c_pl_d": 53.0,             # m²/kg  light extinction per LAI
        "c_rad_phot": 1e-8,         # kg/J  radiation use efficiency (calibratable)
        #   CALIBRATION BASIS (C-fix, 2026-08-16): Van Henten 2003 tomato
        #   literature default, NOT recalibrated for 609 lettuce.  Reference
        #   calibration band (reference/van-henten/PSO_Win.py) is 25-100 W/m²
        #   PAR (nominal 70); engine feeds ~87.5 W/m² (PPFD/par_factor), which
        #   falls inside the band.  Model yields ~109 kg fresh/m²/yr vs 30-60
        #   for real PFAL lettuce (~2x high) — see GrowthConfig docstring.
        "c_co2_1": 5.11e-6,         # m/(s·°C²)
        "c_co2_2": 2.3e-4,          # m/(s·°C)
        "c_co2_3": 6.29e-4,         # m/s
        "c_Gamma": 5.2e-5,          # kg/m³  CO₂ compensation point
    }

    def __init__(self, co2_ppm: float = 800.0, P_atm: float = 101.325,
                 **overrides):
        self.params = dict(self._defaults)
        self.params.update(overrides)
        self.co2_ppm = co2_ppm
        self.P_atm = P_atm
        # Nominal 25 °C / 1 atm reference (kept for backward compatibility);
        # the photosynthesis term uses the temperature- and pressure-aware
        # _co2_density(T_z) instead of this fixed value (P3-11).
        self.co2_kgm3 = self._co2_density(25.0)

    def _co2_density(self, T_c: float) -> float:
        """CO₂ mass concentration (kg/m³) at canopy temperature and station
        pressure (P3-11).

        ppm → kg/m³ uses the ideal-gas molar volume
        V_m = 22.414·(T+273.15)/273.15·(101.325/P_atm) L/mol instead of the
        fixed 25 °C / 1 atm value (24.45 L/mol).  At room temperature
        (~22 °C) the fixed value underestimates the density by ~1 %.
        Units: (g/mol)/(L/mol) ≡ g/L ≡ kg/m³.
        """
        v_m = 22.414 * (T_c + 273.15) / 273.15 * (101.325 / self.P_atm)
        return self.co2_ppm * 1e-6 * 44.0 / v_m

    # ------------------------------------------------------------------
    def _phi_phot_c(self, X_d: float, T_z: float, light: float) -> float:
        """Canopy gross photosynthesis rate  φ_phot,c  (kg/(m²·s))."""
        p = self.params
        co2_term = (-p["c_co2_1"] * T_z ** 2
                    + p["c_co2_2"] * T_z
                    - p["c_co2_3"])
        # Guard: the CO₂ response quadratic turns negative above ~42 °C.  Past
        # that, the denominator `c_rad_phot*light + co2_term*(X_c - Γ)` crosses
        # zero (~44.5 °C) and φ flips sign / blows up, collapsing X_d.  Net
        # canopy photosynthesis cannot be negative, so stop cleanly here.
        if co2_term <= 0.0:
            return 0.0
        X_c = self._co2_density(T_z)   # T/P-aware (P3-11)
        Gamma = p["c_Gamma"]
        num = p["c_rad_phot"] * light * co2_term * (X_c - Gamma)
        den = p["c_rad_phot"] * light + co2_term * (X_c - Gamma)
        if abs(den) < 1e-12:
            return 0.0
        light_response = 1.0 - __import__("math").exp(-p["c_pl_d"] * X_d)
        return light_response * num / den

    def step(
        self, T_z: float, light: float, X_d: float, dt: float = 60.0
    ) -> tuple[float, float]:
        """Advance the biomass state by *dt* seconds.

        Parameters
        ----------
        T_z : float
            Room air temperature (°C).
        light : float
            Photosynthetically active radiation at canopy level (W/m², PAR).
        X_d : float
            Current dry weight (kg/m²).
        dt : float
            Timestep (s).

        Returns
        -------
        dX_d : float
            Instantaneous growth rate  dX_d/dt  (kg/(m²·s)).
        X_d_new : float
            Updated dry weight (kg/m²).
        """
        p = self.params
        phi = self._phi_phot_c(X_d, T_z, light)
        # Dark-respiration temperature response: van't Hoff / Q10 convention,
        # Q10 = 2, reference T_ref = 25 °C → 2^((T - 25)/10) ≡ 2^(0.1·T - 2.5)
        # (rate doubles every +10 °C).  Consistent with the 25 °C basis of
        # c_resp_d.  Reference: van't Hoff (1884); standard plant-respiration
        # practice, e.g. Thornley & Johnson (2000).
        resp = p["c_resp_d"] * max(X_d, 0.0) * (2.0 ** (0.1 * T_z - 2.5))
        dX_d = p["c_alpha_beta"] * phi - resp
        X_d_new = max(0.0, X_d + dX_d * dt)
        return dX_d, X_d_new


# ------------------------------------------------------------------
# ponytail: self-consistency snapshot (NOT a reference-parity test).
# Run:  python -m vfed.plants.van_henten
def _demo():
    """One-day self-consistent snapshot under fixed conditions — T = 22 °C,
    constant 400 W/m² PAR, continuous light with no dark period.  It is NOT
    comparable to the reference ``grow_one_state2003`` output, which reads
    time-varying T / CO₂ / light from ``OriginGrow.xlsx``."""
    grow = VanHenten(co2_ppm=800)
    X_d = 0.02  # initial dry weight kg/m^2 (matches VanHentenConfig default)
    T, dt = 22.0, 600.0
    steps_per_day = 86400 // int(dt)  # 144
    for _ in range(steps_per_day):
        _, X_d = grow.step(T, 400.0, X_d, dt)  # 10-min step, constant PAR snapshot
    print("Van Henten self-check (snapshot, not reference parity):")
    print("  X_d after 1 day (light, T=22C): %.6f kg/m2" % X_d)


if __name__ == "__main__":
    _demo()
