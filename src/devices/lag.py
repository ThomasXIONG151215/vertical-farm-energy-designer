"""
First-order lag (transient inertia) used for device thermal/moisture dynamics.

    dY/dt = (Y_target - Y) / tau   ->   Y_{n+1} = Y_target + (Y_n - Y_target) * exp(-dt/tau)

Asymmetric rise/fall time constants are supported (L3 transient in the
vendored digital twin).
"""

import math
from typing import Optional

__all__ = ["FirstOrderLag"]


class FirstOrderLag:
    def __init__(self, tau_rise: float = 60.0, tau_fall: float = 30.0,
                 initial: float = 0.0):
        self.tau_rise = tau_rise
        self.tau_fall = tau_fall
        self._current = initial

    @property
    def current(self) -> float:
        return self._current

    def reset(self, value: float = 0.0) -> None:
        self._current = value

    def step(self, target: float, dt: float) -> float:
        tau = self.tau_rise if target >= self._current else self.tau_fall
        if tau <= 0:
            self._current = target
            return self._current
        alpha = math.exp(-dt / tau)
        self._current = target + (self._current - target) * alpha
        return self._current
