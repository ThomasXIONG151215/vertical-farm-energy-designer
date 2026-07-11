"""
Hysteresis (deadband) thermostat / compressor state machine.

Fixed-speed equipment runs in ON/OFF mode. The machine turns ON when a signed
``demand`` signal exceeds ``on_threshold`` and turns OFF when demand drops below
``off_threshold`` (anti-short-cycling via minimum run/stop times).

Sign convention for the demand signal: positive means "need action".
  - Cooling : demand = T_z - T_setpoint               (too warm -> positive)
  - Heating : demand = T_heat_setpoint - T_z          (too cold -> positive)
  - Dehumid.: demand = RH_z - RH_setpoint             (too humid -> positive)

Typical use: on_threshold = 0, off_threshold = -deadband, giving a control band
of width ``deadband`` around the setpoint.
"""

from typing import Optional

__all__ = ["CompressorState"]


class CompressorState:
    def __init__(
        self,
        deadband: float = 1.0,   # band width (used as default off_threshold magnitude)
        min_on_s: float = 180.0,
        min_off_s: float = 180.0,
        fan_power_w: float = 70.0,
        initial_on: bool = False,
    ):
        self.deadband = deadband
        self.min_on = min_on_s
        self.min_off = min_off_s
        self.fan_power_w = fan_power_w
        self._on = initial_on
        self._t_in_state = 0.0

    @property
    def is_on(self) -> bool:
        return self._on

    def reset(self, initial_on: bool = False) -> None:
        self._on = initial_on
        self._t_in_state = 0.0

    def update(self, demand: float, dt: float,
               on_threshold: float = 0.0, off_threshold: float = None) -> bool:
        """Advance state given a signed demand signal.

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
        return self._on
