"""
Design presets.

``preset_609`` reproduces the Fengxian lettuce PFAL (the "609 project") physics
so the new simulator can be validated against the archived digital twin. Other
presets provide convenient starting points.
"""

from .project import DesignProject, EnvelopeConfig, LEDConfig, SiteConfig

__all__ = ["preset_default", "preset_609", "PRESETS"]


def preset_default() -> DesignProject:
    return DesignProject(name="default")


def preset_609() -> DesignProject:
    """Fengxian lettuce PFAL reference (digital-twin calibrated parameters)."""
    return DesignProject(
        name="fengxian_lettuce_609",
        site=SiteConfig(lat=30.9, lon=121.5, tz_hours=8.0, city="Shanghai"),
        envelope=EnvelopeConfig(
            U_wall_A=125.3,
            A_window=0.0,
            eta_solar=0.15,
            ach=0.5,
            permeance=0.0,
            V_room=200.0,
            C_z=499597.0,
        ),
        led=LEDConfig(light_start_hour=6, photoperiod_hours=16, heat_fraction=1.0),
    )


PRESETS = {
    "609": {"label": "609 — Fengxian Lettuce PFAL", "factory": preset_609},
    "default": {"label": "Default", "factory": preset_default},
}
