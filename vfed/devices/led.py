"""
LED growth-light model.

The lamp's electrical power is the dominant internal load. Essentially all
electrical energy is eventually converted to heat inside the room (photosynthetically
useful radiation is re-radiated / absorbed by the canopy and crops), so the
thermal gain equals the electrical draw (scaled by ``heat_fraction``).

When ``auto_deduce=True``, the electrical power is deduced from efficacy,
target PPFD and covered area::

    power_w = ppfd_target * covered_area / efficacy

The ``_SPECTRUM_PAR_FACTOR`` table provides the standard PPFD-to-PAR
conversion (µmol/J) used by other modules to compute PAR energy flux. 
Standard values are based on McCree (1972):

    spectrum  | µmol/J_PAR | typical efficacy | notes
    white     | 4.57       | 2.5 µmol/J       | phosphor-converted white LED
    rb_3to1   | 2.45       | 3.2 µmol/J       | red:blue = 3:1
    rb_4to1   | 2.35       | 3.5 µmol/J       | red:blue = 4:1
    rb_2to1   | 2.60       | 2.9 µmol/J       | red:blue = 2:1

Override ``auto_deduce=False`` to set ``power_w`` directly.
"""

from dataclasses import dataclass, field
from typing import Tuple

__all__ = ["LEDDevice"]

_SPECTRUM_PAR_FACTOR = {
    "white":   4.57,
    "rb_3to1": 2.45,
    "rb_4to1": 2.35,
    "rb_2to1": 2.60,
}


@dataclass
class LEDDevice:
    power_w: float = 1300.0
    light_start_hour: int = 6        # hour (0–23) when photoperiod begins
    photoperiod_hours: float = 16.0  # duration of light period (e.g., 12–20)
    # P2-9: default 1.0 deliberately ignores the ~2-5% of photon energy fixed
    # into biomass (photosynthetic carbon fixation) — stored chemical energy,
    # not room heat.  Cumulative error stays within 5% of LED heat (<1% of
    # annual facility energy); lowering to 0.95-0.98 is config-only.
    heat_fraction: float = 1.0       # fraction of electrical power ending as room heat
    auto_deduce: bool = True
    efficacy: float = 2.5            # µmol/J
    ppfd_target: float = 400.0       # µmol/(m²·s)
    covered_area: float = 45.0       # m²
    spectrum: str = "white"          # white | rb_3to1 | rb_4to1 | rb_2to1

    @property
    def par_factor(self) -> float:
        """Spectrum-specific PPFD-to-PAR conversion factor (µmol/J)."""
        return _SPECTRUM_PAR_FACTOR.get(self.spectrum, 4.57)

    @property
    def par_wm2(self) -> float:
        """Canopy PAR irradiance (W/m²) consistent with the runtime LED state.

        P4-11 (MINOR): ``power_w * efficacy / par_factor`` yields the PAR flux
        for BOTH auto_deduce modes — with auto_deduce=True it reduces exactly
        to ``ppfd_target / par_factor``, and with auto_deduce=False it tracks
        the directly-configured power instead of the (possibly stale)
        ppfd_target, keeping the design/DEH-sizing light consistent with the
        runtime LED power.
        """
        return (self.power_w * self.efficacy / max(self.par_factor, 1e-9)
                / max(self.covered_area, 1e-9))

    def __post_init__(self):
        # P5-6: deliberate — auto_deduce=True makes power_w a documented
        # placeholder (recomputed here); par_wm2 tracks power_w in manual
        # mode (P4-11) and from_dict warns when both are set.
        if self.auto_deduce:
            self.power_w = (self.ppfd_target * self.covered_area
                            / max(self.efficacy, 0.1))

    def is_light(self, hour: float) -> bool:
        """True if ``hour`` (0–23, supports fractional) falls within the photoperiod.

        Supports wrap-around photoperiods (e.g. start=22, photoperiod=6h → 22–4).
        """
        if self.photoperiod_hours <= 0:
            return False
        h = hour % 24
        end = (self.light_start_hour + self.photoperiod_hours) % 24
        if end > self.light_start_hour:
            return self.light_start_hour <= h < end
        else:
            # wrap-around (end has cycled past midnight)
            return h >= self.light_start_hour or h < end

    def step(self, hour: float) -> Tuple[float, float]:
        """Return (Q_LED_W, P_elec_W) for the given hour-of-day."""
        if self.is_light(hour):
            p = self.power_w
            return self.heat_fraction * p, p
        return 0.0, 0.0
