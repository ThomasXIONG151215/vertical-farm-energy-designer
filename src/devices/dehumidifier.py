"""
Dehumidifier (DEH) device model.

Parametric, design-time re-implementation of the vendored
``digital_twin.models.deh_controller`` / ``deh_efficiency``.

Architecture:
    P_comp   = P_ref * poly(T, W) * S_DH
    m_DH     = SMER * P_comp / 3.6e6         (moisture removal, kg/s)
    Q_DH     = P_comp + m_DH * h_fg          (condenser heat released to room, W)

S_DH is the on/off modulation driven by a humidity setpoint (hysteresis).
Moisture removal is governed solely by SMER (Specific Moisture Extraction Rate,
kg water / kWh electricity). The EnthalpyEfficiency class is deprecated and
retained only for backward compatibility.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional

from ..physics.psychrometrics import temp_rh_to_ah
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
        efficiency: Optional[EnthalpyEfficiency] = None,
        deadband_rh: float = 3.0,
        min_on_s: float = 180.0,
        min_off_s: float = 180.0,
        fan_power_w: float = 40.0,
        smer: float = 2.0,          # kg water / kWh electricity (realistic 1.5–3.0)
        h_fg: float = 2.5e6,
        tau_q: float = 90.0,
        tau_m: float = 120.0,
    ):
        self.P_ref = P_ref_w
        self.poly_e = poly_e
        self.T_mean, self.T_std = T_mean, T_std
        self.W_mean, self.W_std = W_mean, W_std
        # efficiency parameter is deprecated; SMER is the sole moisture model
        # self.eff deliberately not stored — EnthalpyEfficiency is unused dead code
        self.smer = smer
        self.h_fg = h_fg
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

        Returns dict with Q_DH_W, M_deh_kgs, P_elec_W, is_on, S_DH, eta.
        """
        on = self.comp.update(RH_z - deh_setpoint, dt,
                              on_threshold=0.0,
                              off_threshold=-self.comp.deadband)

        Q_target, M_target, P_elec = 0.0, 0.0, 0.0
        s_dh = 0.0
        eta = 0.0
        if on:
            s_dh = 1.0
            P_comp = self._poly_power(T_z, W_z) * s_dh
            # Latent COP from Specific Moisture Extraction Rate (kg/kWh):
            #   m_dh [kg/s] = SMER [kg/kWh] * P_comp [W] / 3.6e6 [J/kWh]
            m_dh = self.smer * P_comp / 3.6e6
            Q_dh = P_comp + m_dh * self.h_fg
            P_elec = P_comp + self.fan_power_w
            Q_target = Q_dh
            M_target = m_dh
            eta = m_dh * self.h_fg / max(P_comp, 1e-6)  # latent COP for reporting

        # Post-shutdown residual (lag_m/lag_q exponential decay) models coil
        # retained-condensate inertia, NOT electrical inertia: after the
        # compressor stops, already-condensed water keeps dripping (M_act>0)
        # and keeps releasing latent heat (Q_act>0), while P_elec=0 is correct
        # because the compressor/fan are off.
        Q_act = self.lag_q.step(Q_target, dt)
        M_act = self.lag_m.step(M_target, dt)
        return {
            "Q_DH_W": Q_act,
            "M_deh_kgs": M_act,
            "P_elec_W": P_elec if on else 0.0,
            "is_on": bool(on),
            "S_DH": s_dh,
            "eta": eta,
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
    """
    p_comp = moisture_load_kgs * 3.6e6 / max(smer, 0.1)
    return p_comp * safety_factor
