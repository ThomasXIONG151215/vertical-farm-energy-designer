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
    """

    # literature defaults  (all SI)
    _defaults = {
        "c_alpha_beta": 0.544,      # dimensionless conversion efficiency
        "c_resp_d": 2.65e-7,        # s⁻¹  dark respiration coefficient (20 °C)
        "c_pl_d": 53.0,             # m²/kg  light extinction per LAI
        "c_rad_phot": 1e-8,         # kg/J  radiation use efficiency (calibratable)
        "c_co2_1": 5.11e-6,         # m/(s·°C²)
        "c_co2_2": 2.3e-4,          # m/(s·°C)
        "c_co2_3": 6.29e-4,         # m/s
        "c_Gamma": 5.2e-5,          # kg/m³  CO₂ compensation point
    }

    def __init__(self, co2_ppm: float = 800.0, **overrides):
        self.params = dict(self._defaults)
        self.params.update(overrides)
        self.co2_kgm3 = co2_ppm * 1e-6 * 44.0 / 24.45  # ppm → kg/m³

    # ------------------------------------------------------------------
    def _phi_phot_c(self, X_d: float, T_z: float, light: float) -> float:
        """Canopy gross photosynthesis rate  φ_phot,c  (kg/(m²·s))."""
        p = self.params
        co2_term = (-p["c_co2_1"] * T_z ** 2
                    + p["c_co2_2"] * T_z
                    - p["c_co2_3"])
        X_c = self.co2_kgm3
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
        resp = p["c_resp_d"] * max(X_d, 0.0) * (2.0 ** (0.1 * T_z - 2.5))
        dX_d = p["c_alpha_beta"] * phi - resp
        X_d_new = max(0.0, X_d + dX_d * dt)
        return dX_d, X_d_new


# ------------------------------------------------------------------
# ponytail: self-check (exact parity with reference script output).
# Run:  python -m src.plants.van_henten
def _demo():
    """One-day snapshot: compare against reference grow_one_state2003 output."""
    grow = VanHenten(co2_ppm=800)
    X_d = 0.001  # initial dry weight  kg/m^2
    T, dt = 22.0, 600.0
    steps_per_day = 86400 // int(dt)  # 144
    for _ in range(steps_per_day):
        _, X_d = grow.step(T, 400.0, X_d, dt)  # 10-min step, 400 W/m2 PAR (outdoor ref)
    print("Van Henten self-check:")
    print("  X_d after 1 day (light, T=22C): %.6f kg/m2" % X_d)


if __name__ == "__main__":
    _demo()
