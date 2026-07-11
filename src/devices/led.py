"""
LED growth-light model.

The lamp's electrical power is the dominant internal load. Essentially all
electrical energy is eventually converted to heat inside the room (photosynthetically
useful radiation is re-radiated / absorbed by the canopy and crops), so the
thermal gain equals the electrical draw (scaled by ``heat_fraction``).

When ``auto_deduce=True``, the electrical power is deduced from efficacy,
target PPFD and covered area::

    power_w = ppfd_target * covered_area / efficacy / 4.57

where 4.57 converts µmol/s of PAR photons to electrical Watts for a typical
white-LED spectrum.  Override ``auto_deduce=False`` to set ``power_w`` directly.
"""

from dataclasses import dataclass, field
from typing import Tuple

__all__ = ["LEDDevice"]

_PAR_TO_WATTS: float = 4.57   # µmol/J → W  (PAR photon energy conversion)


@dataclass
class LEDDevice:
    power_w: float = 1300.0
    start_hour: int = 6
    end_hour: int = 22
    heat_fraction: float = 1.0   # fraction of electrical power ending as room heat
    auto_deduce: bool = True
    efficacy: float = 2.5        # µmol/J
    ppfd_target: float = 400.0   # µmol/(m²·s)
    covered_area: float = 45.0   # m²

    def __post_init__(self):
        if self.auto_deduce:
            self.power_w = (self.ppfd_target * self.covered_area
                            / max(self.efficacy, 0.1) / _PAR_TO_WATTS)

    def is_light(self, hour: float) -> bool:
        if self.start_hour <= self.end_hour:
            return self.start_hour <= (hour % 24) < self.end_hour
        # wrap-around photoperiod
        h = hour % 24
        return h >= self.start_hour or h < self.end_hour

    def step(self, hour: float) -> Tuple[float, float]:
        """Return (Q_LED_W, P_elec_W) for the given hour-of-day."""
        if self.is_light(hour):
            p = self.power_w
            return self.heat_fraction * p, p
        return 0.0, 0.0
