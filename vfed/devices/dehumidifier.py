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

Operating-condition SMER correction (R33, benchmark B10): the rated SMER holds
only at the DOE rating point.  With ``smer_curve=True`` the effective SMER is

    SMER_eff = smer * clamp(0.25 + 0.75 * (W_z/W_nom)^0.7, 0.25, 1.0)

where W_z is the room humidity ratio at the step and W_nom the humidity ratio
at the DOE 10 CFR 430 Appendix X1 dehumidifier test condition (26.7 C / 60 %
RH).  Moisture capacity is unchanged; the compressor power for the same
condensate rises as 1/SMER_eff (P = M * 3.6e6 / SMER_eff), which restores the
1.5-2x dry-air pessimism the constant-SMER assumption was missing.

Operating-condition (T, RH) maps (R34/W2-C, upgrade D1): with ``smer_map=True``
the device is isomorphic to the EnergyPlus ``ZoneHVAC:Dehumidifier:DX`` model --
TWO normalized biquadratic curves of the inlet air state (E+ v9.5.0 reference
curves ZoneDehumidWaterRemoval / ZoneDehumidEnergyFactor, fitted by NREL to the
DOE 10 CFR 430 Appendix X1 test matrix):

    M         = M_nom * m * WR(T_z, RH_z)          (capacity also derated)
    SMER_eff  = smer * smer_speed_mod(m) * EF(T_z, RH_z)
    P_comp    = M * 3.6e6 / SMER_eff               (same P2-5 basis as above)

Both maps are exactly 1.0 at the DOE rating point (26.7 C / 60 % RH); inputs
are clamped to the E+ curve domain [21, 32.22] C x [40, 80] % RH (no
extrapolation).  ``smer_map`` and ``smer_curve`` are mutually exclusive -- they
model the same DOE dry-air SMER penalty on two functional forms.

Control modes (P1-1): ``control`` selects how S_DH is produced from the
humidity error ``RH_z - deh_setpoint``:
    * ``"vfd"``    (default) variable-speed modulation inside the proportional
      band (``mod_band_rh``); SMER follows the DOE part-load curve, so part-
      load operation is efficiency-lossy (effective SMER < rated).
    * ``"on_off"`` bang-bang cycling between 0 and full speed on the same
      hysteresis (deadband + min_on/min_off anti-short-cycling, CompressorState
      with proportional_band=0).  While running, m = 1 exactly -> the DOE speed
      modifier is 1.0 at m = 1, i.e. the machine runs at its RATED SMER.
"""

from typing import Dict

from ..physics.psychrometrics import latent_heat_vaporization, temp_rh_to_ah
from .compressor import CompressorState
from .lag import FirstOrderLag

__all__ = ["DEHDevice", "EnthalpyEfficiency", "size_deh"]

# P1-1: DEH control modes.  "vfd" = variable-speed (DOE part-load SMER curve),
# "on_off" = bang-bang cycling at full speed (rated SMER).  An unknown value
# is rejected (fail-fast) instead of silently falling back to VFD.
DEH_CONTROL_MODES = ("vfd", "on_off")

# DOE 87 FR 35286 (2022), measured variable-speed dehumidifier: SMER DROPS at
# part load — opposite to inverter A/C.  As speed falls the evaporator
# temperature approaches the inlet dew point, so condensate per unit of
# cooling falls.  Curve fitted to (m, SMER/SMER_rated) = (0.25, 0.54),
# (0.75, 0.89), (1.0, 1.0); "SMER constant" holds only for m >= 0.75.
# Normalised to 1.0 at m = 1.0.  DOE even concludes inverter drives are not
# a viable efficiency path for dehumidifiers.
_SMER_SPEED_B0, _SMER_SPEED_B1, _SMER_SPEED_B2 = 0.30, 1.0467, -0.3467
_DEH_SPEED_M_MIN = 0.2  # compressor turndown (lowest continuous speed)

# R33 (B10): operating-condition SMER correction, anchored to the DOE 10 CFR
# 430 Appendix X1 dehumidifier test condition 26.7 C (80 F) / 60 % RH.  W_nom
# is computed with the same bundled Magnus-formula psychrometrics the engine
# uses for W_ext, so the anchor is reproducible from the code base instead of
# a hardcoded magic number (~0.013176 kg/kg at 101.325 kPa).
_W_NOM_DOE = temp_rh_to_ah(26.7, 60.0)
# Correction band: clamp(0.25 + 0.75*(W_z/W_nom)^0.7, 0.25, 1.0).  Same DOE
# part-load measurement family as the speed curve above (capacity ratio
# m = 0.25 -> 0.54, m = 0.75 -> 0.89, m = 1 -> 1.0): as the inlet air dries
# the evaporator approaches the dew point and condensate per kWh falls; the
# floor 0.25 bounds the penalty, the ceiling 1.0 forbids beating the rating.
_SMER_AIR_B0, _SMER_AIR_EXP, _SMER_AIR_FLOOR = 0.25, 0.7, 0.25

# R34/W2-C (D1): EnergyPlus ZoneHVAC:Dehumidifier:DX isomorphic (T, RH)
# biquadratic maps.  Coefficients are the REFERENCE curves shipped with
# EnergyPlus (v9.5.0 testfiles/SingleFamilyHouse_HP_Slab_Dehumidification.idf,
# curve objects ZoneDehumidWaterRemoval / ZoneDehumidEnergyFactor), fitted by
# NREL to the DOE 10 CFR 430 Appendix X1 dehumidifier test matrix:
#     f(T, RH) = a + b*T + c*T^2 + d*RH + e*RH^2 + f*T*RH
# with x = inlet dry-bulb temperature (C) and y = inlet relative humidity (%).
# E+ Curve:Biquadratic semantics: inputs are clamped to the min/max x/y domain
# BEFORE evaluation (no extrapolation); domain x in [21.0, 32.22] C (70-90 F),
# y in [40, 80] % RH.  The published curves evaluate to ~0.9806 (WR) and
# ~0.9750 (EF) at the DOE rating point (26.7 C / 60 % RH) -- i.e. not exactly
# normalized -- so the runtime modifiers divide by the rating-point raw value
# (IEEE-754 x/x = 1.0 exactly, per the E+ I/O Reference requirement that the
# curves "should be normalized to have the value of 1.0 at the rating point").
# Unlike the R33 power law (ceiling 1.0), the E+ curves may legitimately
# EXCEED 1.0 in wetter-than-rated air (EF ~1.12 at 21 C / 68 % RH): the rating
# point is an anchor, not a cap, per the E+ model.
_WR_MAP_COEF = (-2.724878664080, 0.100711983591, -0.000990538285,
                0.050053043874, -0.000203629282, -0.000341750531)
_EF_MAP_COEF = (-2.388319068955, 0.093047739452, -0.001369700327,
                0.066533716758, -0.000343198063, -0.000562490295)
_MAP_T_MIN, _MAP_T_MAX = 21.0, 32.22  # E+ curve x domain (C)
_MAP_RH_MIN, _MAP_RH_MAX = 40.0, 80.0  # E+ curve y domain (% RH)
_MAP_FLOOR = 0.05  # normalized-output floor (safety only; in-domain > 0.34)


def _biquad_raw(coef, T_c, rh_pct):
    """E+ Curve:Biquadratic with domain-clamped inputs (min/max x/y)."""
    a, b, c, d, e, f = coef
    x = min(max(T_c, _MAP_T_MIN), _MAP_T_MAX)
    y = min(max(rh_pct, _MAP_RH_MIN), _MAP_RH_MAX)
    return a + b * x + c * x * x + d * y + e * y * y + f * x * y


_WR_MAP_RATED = _biquad_raw(_WR_MAP_COEF, 26.7, 60.0)  # ~0.980619
_EF_MAP_RATED = _biquad_raw(_EF_MAP_COEF, 26.7, 60.0)  # ~0.975010


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
        deadband_rh: float = 2.0,
        min_on_s: float = 180.0,
        min_off_s: float = 180.0,
        fan_power_w: float = 40.0,
        smer: float = 2.0,  # kg water / kWh COMPRESSOR input (P2-5);
        # realistic 1.5-3.0, fan excluded from SMER
        smer_curve: bool = False,  # R33/B10: apply the W_z operating-condition
        # SMER correction (SMER_eff = smer * clamp(0.25+0.75*(W_z/W_nom)^0.7,
        # 0.25, 1.0), W_nom anchored at DOE 26.7 C / 60 % RH).  False =
        # constant rated SMER, bit-identical to the pre-R33 path.
        smer_map: bool = False,  # R34/W2-C (D1): EnergyPlus Dehumidifier:DX
        # isomorphic (T, RH) biquadratic maps (capacity M = M_nom*WR(T,RH),
        # SMER_eff = smer*EF(T,RH), both 1.0 at the DOE 26.7 C / 60 % RH
        # rating point, inputs clamped to the E+ curve domain).  Mutually
        # exclusive with smer_curve.  False = bit-identical pre-R34 path.
        tau_q: float = 90.0,
        tau_m: float = 120.0,
        mod_band_rh: float = 4.0,  # VFD proportional band (% RH)
        control: str = "vfd",  # "vfd" | "on_off" (P1-1)
    ):
        if control not in DEH_CONTROL_MODES:
            raise ValueError(
                f"DEH control must be one of {'|'.join(DEH_CONTROL_MODES)}, got {control!r}"
            )
        if smer_map and smer_curve:
            raise ValueError(
                "smer_map and smer_curve are mutually exclusive air-side SMER "
                "corrections (both model the same DOE rating-point dry-air "
                "penalty on two functional forms); enable exactly one."
            )
        self.P_ref = P_ref_w
        self.poly_e = poly_e
        self.T_mean, self.T_std = T_mean, T_std
        self.W_mean, self.W_std = W_mean, W_std
        # SMER is the sole moisture model (P2-4b: removed the deprecated
        # EnthalpyEfficiency parameter).  P_ref_w is the COMPRESSOR reference
        # power; fan_power_w is metered separately in P_elec / Q_DH.
        self.smer = smer
        self.smer_curve = smer_curve
        self.smer_map = smer_map
        self.fan_power_w = fan_power_w
        self.mod_band_rh = mod_band_rh
        self.control = control
        # P1-1: both modes share one CompressorState hysteresis (deadband +
        # min_on/min_off anti-short-cycling).  "on_off" passes
        # proportional_band=0 -> bang-bang, m = 1 exactly while ON, so the DOE
        # speed modifier is 1.0 at m = 1 (rated SMER, full-speed compressor).
        # "vfd" keeps the proportional band modulation (default, unchanged).
        self.comp = CompressorState(
            deadband=deadband_rh,
            min_on_s=min_on_s,
            min_off_s=min_off_s,
            fan_power_w=fan_power_w,
            proportional_band=0.0 if control == "on_off" else mod_band_rh,
            m_min=_DEH_SPEED_M_MIN,
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

    def _smer_speed_mod(self, m: float) -> float:
        """SMER modifier vs speed ratio (DOE measured variable-speed curve):
        part-load SMER falls as the evaporator approaches the dew point."""
        m = min(max(m, _DEH_SPEED_M_MIN), 1.0)
        return max(_SMER_SPEED_B0 + _SMER_SPEED_B1 * m + _SMER_SPEED_B2 * m * m, 0.05)

    def _smer_air_mod(self, W_z: float) -> float:
        """SMER modifier vs room humidity ratio (R33/B10, DOE rating-point
        anchored): drier air means less condensate per kWh of compressor
        input, so the effective SMER falls with W_z/W_nom."""
        ratio = max(W_z, 0.0) / _W_NOM_DOE
        return min(
            max(_SMER_AIR_B0 + 0.75 * ratio ** _SMER_AIR_EXP, _SMER_AIR_FLOOR),
            1.0,
        )

    def _wr_map_mod(self, T_z: float, RH_z: float) -> float:
        """Water-removal CAPACITY modifier (R34/W2-C): the E+ reference
        biquadratic WR(T, RH), normalized to exactly 1.0 at the DOE rating
        point (26.7 C / 60 % RH).  Falls steeply in cold/dry air (0.349 at
        the 21 C / 40 % RH domain corner); may exceed 1.0 in warm/wet air."""
        return max(_biquad_raw(_WR_MAP_COEF, T_z, RH_z) / _WR_MAP_RATED, _MAP_FLOOR)

    def _ef_map_mod(self, T_z: float, RH_z: float) -> float:
        """Energy-factor (SMER) modifier (R34/W2-C): the E+ reference
        biquadratic EF(T, RH), normalized to exactly 1.0 at the DOE rating
        point.  Drier air degrades (0.617 at the 21 C / 40 % RH corner, the
        same DOE dry-air physics as the R33 power law); humid air may beat
        the rating (1.124 at 21 C / 68 % RH) -- anchor, not cap, per E+."""
        return max(_biquad_raw(_EF_MAP_COEF, T_z, RH_z) / _EF_MAP_RATED, _MAP_FLOOR)

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
        latent_cop (with legacy ``eta`` alias), smer_air_mod (R33) and
        wr_map_mod / ef_map_mod (R34, 1.0 when the map is off).

        ``control="vfd"`` (default): variable-speed modulation (second-round
        research, DOE 87 FR 35286): capacity scales linearly with m
        (``m_dh = m * M_full``) while SMER FALLS at part load
        (``smer_eff = smer * smer_speed_mod(m)``), so the compressor power
        ``P_comp = P_full * m / smer_mod`` rises faster than linearly —
        running a dehumidifier at low speed wastes efficiency.

        ``control="on_off"`` (P1-1): the same equations hold with m = 1 while
        running, so ``smer_speed_mod(1) = 1`` and the machine extracts
        moisture at its rated SMER, cycling on the hysteresis deadband
        (min_on/min_off anti-short-cycling included via CompressorState).

        ``smer_curve=True`` (R33/B10): the air-side operating-condition factor
        ``smer_air = clamp(0.25 + 0.75*(W_z/W_nom)^0.7, 0.25, 1.0)`` (W_nom at
        the DOE 26.7 C / 60 % RH rating point) multiplies the effective SMER
        in BOTH control modes -- full speed included -- so
        ``SMER_eff = smer * smer_speed_mod(m) * smer_air`` and the compressor
        power for the same condensate rises as 1/smer_air.

        ``smer_map=True`` (R34/W2-C, exclusive with smer_curve): the E+
        Dehumidifier:DX (T, RH) maps replace the air-side factor -- capacity
        AND efficiency both follow the inlet air state:

            M        = M_nom * m * wr_map(T_z, RH_z)
            SMER_eff = smer * smer_speed_mod(m) * ef_map(T_z, RH_z)
            P_comp   = M * 3.6e6 / SMER_eff = P_full*m*wr_map/(smer_mod*ef_map)

        At the DOE rating point wr_map = ef_map = 1.0 exactly, so the map-on
        machine is bit-identical to map-off there.  Both default-off factors
        are exactly 1.0 and multiply through IEEE-754 exactly, so the default
        path is bit-identical to the pre-R34 baselines (zero drift).
        """
        mod = self.comp.update(
            RH_z - deh_setpoint, dt, on_threshold=0.0, off_threshold=-self.comp.deadband
        )

        Q_sens_target, M_target, P_elec = 0.0, 0.0, 0.0
        s_dh = 0.0
        latent_cop = 0.0
        # R33/B10: operating-condition SMER correction.  The rated SMER holds
        # only at the DOE rating point (26.7 C / 60 % RH); in drier air the
        # moisture-per-power relation degrades by the air-side factor below.
        # Capacity (M vs m) is UNCHANGED -- the compressor power for the same
        # condensate rises as 1/smer_air (P = M * 3.6e6 / SMER_eff), exactly
        # the DOE-observed dry-air pessimism the constant-SMER assumption was
        # missing.  Default off: the 1.0 factor multiplies through IEEE-754
        # exactly, so the pre-R33 path is bit-identical (zero drift).
        smer_air = self._smer_air_mod(W_z) if self.smer_curve else 1.0
        # R34/W2-C: E+ (T, RH) maps.  wr_map derates the water-removal
        # CAPACITY as well (the E+ Water Removal curve); ef_map is the
        # air-side SMER factor (the E+ Energy Factor curve) and REPLACES the
        # R33 factor (mutually exclusive switches).  Default off: both are
        # exactly 1.0 and multiply through IEEE-754 exactly (zero drift).
        if self.smer_map:
            wr_map = self._wr_map_mod(T_z, RH_z)
            ef_map = self._ef_map_mod(T_z, RH_z)
        else:
            wr_map = 1.0
            ef_map = 1.0
        # L_v(T_z) evaluated every step so the post-shutdown condensate drip
        # (M_act > 0) releases latent heat at the current room temperature.
        L_v = latent_heat_vaporization(T_z) * 1000.0
        if mod > 0.0:
            s_dh = mod
            P_full = self._poly_power(T_z, W_z)
            smer_mod = self._smer_speed_mod(s_dh)
            # VFD compressor power: P/P_rated = m / smer_mod (DOE curve:
            # capacity linear, SMER falling, so power super-linear).  With an
            # air-side factor on (smer_air from smer_curve, or ef_map from
            # smer_map) and the capacity map wr_map (smer_map only), the SAME
            # removal demand draws P = M*3.6e6/SMER_eff
            #                            = P_full*m*wr_map/(smer_mod*ef_map*smer_air).
            P_comp = P_full * s_dh * wr_map / max(smer_mod * smer_air * ef_map, 1e-6)
            # Specific Moisture Extraction Rate (kg water / kWh COMPRESSOR
            # input, P2-5): m_dh [kg/s] = SMER * P_comp [W] / 3.6e6 [J/kWh].
            # The fan is intentionally excluded from the SMER denominator and
            # counted exactly once in P_elec below -- no double-count.
            m_dh = self.smer * smer_mod * smer_air * ef_map * P_comp / 3.6e6
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
            # No longer constant: SMER falls with m, so latent_cop falls too
            # (and with W_z when smer_curve is on — R33).
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
            "P_elec_W": P_elec if mod > 0.0 else 0.0,
            "is_on": bool(mod > 0.0),
            "mod": mod,
            "S_DH": s_dh,
            "latent_cop": latent_cop,
            "eta": latent_cop,  # DEPRECATED alias (P2-10) -- use "latent_cop"
            "smer_air_mod": smer_air,  # R33: air-side factor (1.0 when curve off)
            "wr_map_mod": wr_map,  # R34: E+ capacity factor (1.0 when map off)
            "ef_map_mod": ef_map,  # R34: E+ energy-factor factor (1.0 when map off)
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
