"""CO2 enrichment injector device (M1) + CO2 unit conversions.

Design proposal: .planning/2026-10-11_co2-model-supplement-proposal.md
(§2.2/§2.4).  Setpoint + deadband on/off injection control with a capacity
cap, mirroring the ``DEHDevice`` interface contract (devices/dehumidifier.py):

    error    e = setpoint_ppm - c_ppm_z            (positive = inject)
    mod      CompressorState deadband hysteresis (ON at e >= band,
             OFF at e <= -band; min_on/min_off anti-short-cycling)
    S_target = mod * capacity_g_per_h / 3.6e6      [kg/s]
    S_inj    = FirstOrderLag(tau_s).step(S_target)  (solenoid/vaporiser line)
    P_elec   = power_w * mod                        (while commanded ON)

``inject_in_dark=False`` (default) forces mod = 0 in the dark period:
photosynthesis is zero, so enrichment has no agronomic benefit (commercial
PFAL practice injects in light only; Kozai et al. 2016).

THERMAL ASSUMPTION (M1, deliberately ignored and documented here): liquid /
bulk CO2 vaporises endothermically at ~350-570 kJ/kg.  At the default
50 g/h scale this is only ~5-8 W of cooling -- negligible against the room
heat balance -- and the gas is usually vaporised outdoors before delivery,
so M1 treats the injection as adiabatic (zero heat disturbance).  An
``injection_heat`` switch is reserved to add it to Q_total should field
measurements ever show a relevant (>10 W) term.

Unit conversions (all T/P aware; ideal-gas form mirrors
plants/van_henten.py:77-88):

* ppm (mole fraction) -> mixing ratio:  c = y * M_co2 / M_air  (linear
  approximation; the error at y = 800e-6 is < 0.1 %);
* ppm -> mass density (kg/m3):  X = y * 1e-6 * M_co2 / v_m(T, P), with
  v_m = 22.414 * (T+273.15)/273.15 * (101.325/P_atm)  L/mol.  References at
  101.325 kPa / 22 C: 1 ppm ~ 1.817 mg/m3, 800 ppm ~ 1.454 g/m3, 420 ppm
  ~ 0.763 g/m3; 800 ppm -> mixing ratio ~1.216e-3 kg/kg.
"""

from typing import Dict

from .compressor import CompressorState
from .lag import FirstOrderLag

__all__ = [
    "CO2Device",
    "CO2_CONTROL_MODES",
    "M_CO2",
    "M_AIR",
    "DM_TO_CO2",
    "G_PER_H_TO_KG_PER_S",
    "ppm_to_mixing_ratio",
    "mixing_ratio_to_ppm",
    "ppm_to_density",
]

# Molar masses (kg/kmol == g/mol; CODATA / standard dry air).
M_CO2 = 44.01
M_AIR = 28.965  # dry air (ASCII name: M_AIR)
# Dry matter (CH2O, 30.03 g/mol) -> CO2 mass ratio for the respiration
# source: respiring 1 kg of dry-matter-equivalent carbohydrate releases
# 44.01/30.03 ~ 1.465 kg CO2 (Thornley & Johnson 2000, Plant and Crop
# Physiology Modelling).
DM_TO_CO2 = M_CO2 / 30.03
# 1 g/h = 1e-3 kg / 3600 s
G_PER_H_TO_KG_PER_S = 1.0 / 3.6e6

# M1 whitelist: "on_off" (bang-bang at full capacity, CompressorState
# hysteresis).  "vfd" (proportional-band modulation, the DEH dual) is a
# planned M2 mode; an unknown value is rejected fail-fast instead of
# silently falling back.
CO2_CONTROL_MODES = ("on_off",)


def ppm_to_mixing_ratio(ppm: float) -> float:
    """CO2 mole fraction (ppm) -> mixing ratio (kg CO2 / kg dry air).

    Linear approximation c = y * M_co2 / M_air (error < 0.1 % at 800 ppm;
    proposal §2.1).  Temperature-independent, so the ventilation exchange
    term m_dot*(c_out - c_z) needs no per-step T correction.
    """
    return ppm * 1e-6 * M_CO2 / M_AIR


def mixing_ratio_to_ppm(c: float) -> float:
    """Mixing ratio (kg/kg) -> CO2 mole fraction (ppm) -- exact inverse."""
    return c * M_AIR / M_CO2 * 1e6


def ppm_to_density(ppm: float, T_c: float, P_kpa: float = 101.325) -> float:
    """CO2 mole fraction (ppm) -> mass density (kg/m3) at temperature T_c
    (degC) and pressure P_kpa -- the canopy-level mass concentration the
    Van Henten photosynthesis term consumes.  Same ideal-gas molar-volume
    form as plants/van_henten.py:77-88 (v_m in L/mol; (g/mol)/(L/mol) is
    kg/m3)."""
    v_m = 22.414 * (T_c + 273.15) / 273.15 * (101.325 / P_kpa)
    return ppm * 1e-6 * M_CO2 / v_m


class CO2Device:
    """CO2 enrichment injector (setpoint + deadband on/off, capacity cap).

    Interface contract mirrors ``DEHDevice``: explicit-parameter
    ``__init__`` with fail-fast validation, ``reset()``, and
    ``step(...) -> dict`` returning the mass flux and electrical draw the
    engine keys on.  No auto-sizing in M1 (a ``size_co2(peak_phot_kgs)``
    counterpart to ``size_deh`` is an M3 deliverable).
    """

    def __init__(
        self,
        capacity_g_per_h: float = 200.0,
        band_ppm: float = 50.0,
        control: str = "on_off",
        inject_in_dark: bool = False,
        min_on_s: float = 0.0,
        min_off_s: float = 300.0,
        power_w: float = 50.0,
        tau_s: float = 30.0,
    ):
        if control not in CO2_CONTROL_MODES:
            raise ValueError(
                f"CO2 control must be one of {'|'.join(CO2_CONTROL_MODES)}, "
                f"got {control!r}. Proportional 'vfd' modulation is a planned "
                f"follow-up mode (M2)."
            )
        if capacity_g_per_h <= 0.0:
            raise ValueError(
                f"CO2 capacity_g_per_h must be > 0 g/h, got {capacity_g_per_h}"
            )
        if band_ppm <= 0.0:
            raise ValueError(f"CO2 band_ppm must be > 0 ppm, got {band_ppm}")
        if tau_s <= 0.0:
            raise ValueError(f"CO2 tau_s must be > 0 s, got {tau_s}")
        if min_on_s < 0.0 or min_off_s < 0.0:
            raise ValueError(
                f"CO2 min_on_s/min_off_s must be >= 0 s, got "
                f"{min_on_s}/{min_off_s}"
            )
        if power_w < 0.0:
            raise ValueError(f"CO2 power_w must be >= 0 W, got {power_w}")
        self.capacity_g_per_h = float(capacity_g_per_h)
        self.capacity_kgs = capacity_g_per_h * G_PER_H_TO_KG_PER_S
        self.band_ppm = float(band_ppm)
        self.control = control
        self.inject_in_dark = bool(inject_in_dark)
        self.power_w = float(power_w)
        # One shared CompressorState hysteresis: demand = setpoint - c_ppm_z
        # (positive = below setpoint = inject).  ON at demand >= band
        # (c_z <= sp - band), OFF at demand <= -band (c_z >= sp + band);
        # proportional_band = 0 -> bang-bang, m = 1 exactly while ON (the
        # DEH "on_off" pattern, P1-1).
        self.comp = CompressorState(
            deadband=band_ppm,
            min_on_s=min_on_s,
            min_off_s=min_off_s,
            fan_power_w=0.0,
            proportional_band=0.0,
            m_min=0.0,
        )
        self.lag_inj = FirstOrderLag(tau_s, tau_s)

    def reset(self) -> None:
        self.comp.reset(False)
        self.lag_inj.reset(0.0)

    def step(
        self,
        co2_ppm_z: float,
        dt: float,
        setpoint_ppm: float,
        is_light: bool = True,
    ) -> Dict[str, float]:
        """Advance one timestep.

        Parameters: current indoor CO2 (ppm), timestep (s), enrichment
        setpoint (ppm), light-period flag.  With ``inject_in_dark=False``
        the dark period forces mod = 0 (valve closed; the lag lets the
        line's residual gas decay physically while the power draw is 0).

        Returns dict with ``S_inj_kgs`` (injection mass flux, kg/s, after
        the first-order line lag), ``P_elec_W`` (vaporiser/valve draw),
        ``is_on`` and ``mod`` (commanded modulation, 0/1 for on_off).
        """
        demand = setpoint_ppm - co2_ppm_z
        mod = self.comp.update(
            demand, dt, on_threshold=self.band_ppm, off_threshold=-self.band_ppm
        )
        if mod > 0.0 and not is_light and not self.inject_in_dark:
            mod = 0.0
        S_target = mod * self.capacity_kgs
        S_inj = self.lag_inj.step(S_target, dt)
        P_elec = self.power_w * mod
        return {
            "S_inj_kgs": S_inj,
            "P_elec_W": P_elec,
            "is_on": bool(mod > 0.0),
            "mod": mod,
        }
