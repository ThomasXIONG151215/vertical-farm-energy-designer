"""
Hysteresis (deadband) thermostat / variable-speed compressor state machine.

Fixed-speed equipment runs in ON/OFF mode (bang-bang). Variable-speed
(inverter) equipment additionally modulates output between a minimum
turndown and full speed, governed by a proportional band around the
setpoint: the closer the controlled variable is to setpoint, the lower
the modulation coefficient ``m``.

The machine turns ON when a signed ``demand`` signal exceeds
``on_threshold`` and turns OFF when demand drops below ``off_threshold``
(anti-short-cycling via minimum run/stop times).

Sign convention for the demand signal: positive means "need action".
  - Cooling : demand = T_z - T_setpoint               (too warm -> positive)
  - Heating : demand = T_heat_setpoint - T_z          (too cold -> positive)
  - Dehumid.: demand = RH_z - RH_setpoint             (too humid -> positive)

Typical use: on_threshold = 0, off_threshold = -deadband, giving a control band
of width ``deadband`` around the setpoint.

Modulation: while ON, ``m = clamp((demand - on_threshold) / proportional_band,
m_min, 1)``. A 600 s substep is a 10-min average, so low ``m`` values are
physically realised by time-averaging (duty cycle) below the compressor
turndown; ``m_min`` models the lowest continuous speed of real inverter
compressors (~15-25% rated, oil return constraint).
"""

__all__ = ["CompressorState"]


class CompressorState:
    def __init__(
        self,
        deadband: float = 1.0,  # band width (used as default off_threshold magnitude)
        min_on_s: float = 180.0,
        min_off_s: float = 180.0,
        fan_power_w: float = 70.0,
        initial_on: bool = False,
        proportional_band: float = 0.0,  # control band for VFD modulation (0 = bang-bang)
        m_min: float = 0.2,  # lowest continuous speed (turndown)
    ):
        self.deadband = deadband
        self.min_on = min_on_s
        self.min_off = min_off_s
        self.fan_power_w = fan_power_w
        self.proportional_band = proportional_band
        self.m_min = m_min
        self._on = initial_on
        self._t_in_state = 0.0

    @property
    def is_on(self) -> bool:
        return self._on

    def reset(self, initial_on: bool = False) -> None:
        self._on = initial_on
        self._t_in_state = 0.0

    def update(
        self, demand: float, dt: float, on_threshold: float = 0.0, off_threshold: float = None
    ) -> float:
        """Advance state given a signed demand signal.

        Returns the modulation coefficient ``m`` in [0, 1] (0 = OFF,
        ``m_min``..1 = modulated, ``1`` = full speed). With
        ``proportional_band = 0`` the legacy bang-bang behaviour is kept
        (returns 1.0 while ON).

        on_threshold  : turn ON when demand >= on_threshold
        off_threshold : turn OFF when demand <= off_threshold (defaults to -deadband)
        """
        if off_threshold is None:
            off_threshold = -self.deadband
        self._t_in_state += dt
        if self._on:
            if demand <= off_threshold and self._t_in_state >= self.min_on:
                self._on = False
                self._t_in_state = 0.0
        else:
            if demand >= on_threshold and self._t_in_state >= self.min_off:
                self._on = True
                self._t_in_state = 0.0

        if not self._on:
            return 0.0
        if demand <= off_threshold:
            # Locked ON by min_on but explicitly commanded OFF: hold the state
            # (anti-short-cycle) with zero output (VFD can idle the compressor
            # at near-zero load while the min-run lock expires).
            return 0.0
        if self.proportional_band <= 0:
            return 1.0
        m = (demand - on_threshold) / self.proportional_band
        m = min(max(m, 0.0), 1.0)
        return max(m, self.m_min)
