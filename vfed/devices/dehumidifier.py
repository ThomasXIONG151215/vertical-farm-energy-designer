"""
Dehumidifier (DEH) device model.

Parametric, design-time re-implementation of the vendored
``digital_twin.models.deh_controller`` / ``deh_efficiency``.

Architecture:
    P_comp   = P_ref * poly(T, W) * S_DH
    m_DH     = SMER * P_comp / 3.6e6         (moisture removal, kg/s)
    Q_DH     = P_comp + m_DH * L_v(T_z)      (condenser heat released to room, W)
                                             + fan_power_w (fan motor + friction heat,
                                             stays in room — airflow returns to the
                                             same space, see ENERGY STAR / Quest /
                                             Anden spec sheets)

SMER convention (P2-5): Specific Moisture Extraction Rate is defined on the
COMPRESSOR electrical input only (P_comp).  The fan (~2% of full load: 40 W /
2233 W) is metered separately in P_elec / Q_DH, so it is neither hidden in nor
double-counted against SMER.  Spec-sheet SMER is usually total-power based;
convert first: smer_comp = smer_total * P_comp / (P_comp + P_fan).

S_DH is the on/off modulation driven by a humidity setpoint (hysteresis).
Moisture removal is governed solely by SMER (Specific Moisture Extraction Rate,
kg water / kWh electricity). The EnthalpyEfficiency class is deprecated and
retained only for backward compatibility.
"""

from dataclasses import dataclass, field
from typing import Dict

from ..physics.psychrometrics import latent_heat_vaporization, temp_rh_to_ah
from .compressor import CompressorState
from .lag import FirstOrderLag

__all__ = ["DEHDevice", "EnthalpyEfficiency", "size_deh"]


class EnthalpyEfficiency:
    """DEPRECATED: ASHRAE saturation DEH efficiency model (no longer used by DEHDevice).

    SMER (Specific Moisture Extraction Rate) is now the sole moisture model.
    Kept for backward compatibility only — may be removed in a future version.
    """

    def __init__(
        self,
        eta_ref: float = 0.11,
        eta_max: float = 0.15,
        ah_min: float = 0.0054,
        ah_ref: float = 0.0099,
    ):
        self.eta_ref = eta_ref
        self.eta_max = eta_max
        self.ah_min = ah_min
        self.ah_ref = ah_ref

    def predict(self, T_c: float, RH_pct: float) -> float:
        ah = temp_rh_to_ah(T_c, RH_pct)
        drive = max(0.0, ah - self.ah_min)
        ref_drive = max(1e-3, self.ah_ref - self.ah_min)
        eta = self.eta_ref * drive / ref_drive
        return max(0.01, min(0.80, eta))


class DEHDevice:
    def __init__(
        self,
        P_ref_w: float = 2233.0,
        # Parametric power surface: P_comp_max = P_ref * (e0 + e1*tn + ... )
        poly_e: tuple = (1.0, 0.02, 0.0, 0.05, 0.0, 0.0),
        T_mean: float = 22.0,
        T_std: float = 5.0,
        W_mean: float = 0.012,
        W_std: float = 0.003,
        deadband_rh: float = 3.0,
        min_on_s: float = 180.0,
        min_off_s: float = 180.0,
        fan_power_w: float = 40.0,
        smer: float = 2.0,          # kg water / kWh COMPRESSOR input (P2-5);
                                    # realistic 1.5-3.0, fan excluded from SMER
        tau_q: float = 90.0,
        tau_m: float = 120.0,
    ):
        self.P_ref = P_ref_w
        self.poly_e = poly_e
        self.T_mean, self.T_std = T_mean, T_std
        self.W_mean, self.W_std = W_mean, W_std
        # SMER is the sole moisture model (P2-4b: removed the deprecated
        # EnthalpyEfficiency parameter).  P_ref_w is the COMPRESSOR reference
        # power; fan_power_w is metered separately in P_elec / Q_DH.
        self.smer = smer
        self.fan_power_w = fan_power_w
        self.comp = CompressorState(
            deadband=deadband_rh, min_on_s=min_on_s, min_off_s=min_off_s,
            fan_power_w=fan_power_w,
        )
        self.lag_q = FirstOrderLag(tau_rise=tau_q, tau_fall=tau_q)
        self.lag_m = FirstOrderLag(tau_rise=tau_m, tau_fall=tau_m)

    def reset(self) -> None:
        self.comp.reset(False)
        self.lag_q.reset(0.0)
        self.lag_m.reset(0.0)

    def _poly_power(self, T_z: float, W_z: float) -> float:
        e0, e1, e2, e3, e4, e5 = self.poly_e
        tn = (T_z - self.T_mean) / max(self.T_std, 0.1)
        wn = (W_z - self.W_mean) / max(self.W_std, 1e-4)
        poly = e0 + e1 * tn + e2 * tn * tn + e3 * wn + e4 * wn * wn + e5 * tn * wn
        return max(0.0, self.P_ref * poly)

    def step(
        self,
        T_z: float,
        RH_z: float,
        W_z: float,
        dt: float = 60.0,
        deh_setpoint: float = 60.0,
    ) -> Dict[str, float]:
        """Advance one timestep.

        Returns dict with Q_DH_W, M_deh_kgs, P_elec_W, is_on, S_DH,
        latent_cop (with legacy ``eta`` alias).
        """
        on = self.comp.update(RH_z - deh_setpoint, dt,
                              on_threshold=0.0,
                              off_threshold=-self.comp.deadband)

        Q_sens_target, M_target, P_elec = 0.0, 0.0, 0.0
        s_dh = 0.0
        latent_cop = 0.0
        # L_v(T_z) evaluated every step so the post-shutdown condensate drip
        # (M_act > 0) releases latent heat at the current room temperature.
        L_v = latent_heat_vaporization(T_z) * 1000.0
        if on:
            s_dh = 1.0
            P_comp = self._poly_power(T_z, W_z) * s_dh
            # Specific Moisture Extraction Rate (kg water / kWh COMPRESSOR
            # input, P2-5): m_dh [kg/s] = SMER * P_comp [W] / 3.6e6 [J/kWh].
            # The fan is intentionally excluded from the SMER denominator and
            # counted exactly once in P_elec below — no double-count.
            m_dh = self.smer * P_comp / 3.6e6
            # MINOR-7 (D): latent heat evaluated at room temperature T_z so the
            # condenser term exactly cancels the engine's evaporative sink
            # (engine L_v = latent_heat_vaporization(T_z)*1000) — the closure
            # gap is identically zero at every temperature (no fixed h_fg).
            P_elec = P_comp + self.fan_power_w
            # Fan motor + air friction heat is released into the room airflow
            # (dehumidifier exhausts into the same space).
            Q_sens_target = P_comp + self.fan_power_w
            M_target = m_dh
            # Latent COP for reporting (P2-10): condensation power per unit of
            # compressor input (fan excluded) — renamed from the misleading
            # "eta"; the module's deprecated EnthalpyEfficiency is unrelated.
            latent_cop = m_dh * L_v / max(P_comp, 1e-6)

        # Energy-self-consistent transient (P2-6): Q_act is DERIVED from M_act,
        #   Q_act = M_act * L_v + Q_sens_act
        # so the latent heat released tracks exactly the moisture condensed at
        # the same lag (tau_m = coil retained-condensate inertia), and the
        # compressor+fan heat is lagged separately at tau_q (coil thermal
        # inertia).  Previously Q (tau_q=90 s) and M (tau_m=120 s) lagged
        # independently, so on/off transients released "heat without moisture"
        # (~283 W excess on the first dt=60 s step at full load).  Post-shutdown
        # residual (exponential decay) models condensate dripping: M_act>0 and
        # Q_act>0 while P_elec=0 (compressor/fan off) — correct, and the
        # engine's q_removal_corr now backs out phantom latent heat exactly.
        Q_sens_act = self.lag_q.step(Q_sens_target, dt)
        M_act = self.lag_m.step(M_target, dt)
        Q_act = M_act * L_v + Q_sens_act
        return {
            "Q_DH_W": Q_act,
            "M_deh_kgs": M_act,
            "P_elec_W": P_elec if on else 0.0,
            "is_on": bool(on),
            "S_DH": s_dh,
            "latent_cop": latent_cop,
            "eta": latent_cop,  # DEPRECATED alias (P2-10) — use "latent_cop"
        }


def size_deh(
    moisture_load_kgs: float,
    smer: float = 2.0,
    safety_factor: float = 1.2,
) -> float:
    """Calculate required DEH P_ref (W) from design moisture load.

    ``moisture_load_kgs`` is the peak moisture gain rate (kg/s) the
    dehumidifier must remove: transpiration + infiltration moisture +
    envelope permeance at design conditions.

    P_ref [W] = moisture [kg/s] * 3.6e6 [J/kWh] / SMER [kg/kWh]

    ``smer`` is the COMPRESSOR-input basis (P2-5): the returned P_ref is the
    compressor reference power.  The fan (~2% of full load) is added separately
    at runtime (P_elec = P_comp + fan_power_w), so it is never double-counted.
    Convert spec-sheet (total-power) SMER before use:
    smer_comp = smer_total * P_comp / (P_comp + P_fan).
    """
    p_comp = moisture_load_kgs * 3.6e6 / max(smer, 0.1)
    return p_comp * safety_factor
