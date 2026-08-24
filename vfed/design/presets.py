"""
Design presets.

``preset_609`` reproduces the Fengxian lettuce PFAL (the "609 project") physics
so the new simulator can be validated against the archived digital twin. Other
presets provide convenient starting points.
"""

from .project import (DEHConfig, DesignProject, EnvelopeConfig, HVACConfig,
                      LEDConfig, SiteConfig)

__all__ = ["preset_default", "preset_609", "PRESETS"]


def preset_default() -> DesignProject:
    """Small-scale DIY starting point (~10 m² canopy).

    Deliberately prosumer-friendly (F4):
    - ``site.city="Shanghai"`` so the bundled offline weather file
      ``data/weather/Shanghai_2025.csv`` is used on first run (no E003 offline).
      Weather year is locked to 2025 for offline reference data.
    - small envelope (40 m³ room / 10 m² canopy) so the derived LED power and
      energy figures are home-scale, not 609-farm-scale.
    - ``hvac.auto_size`` / ``deh.auto_size`` = True so capacities are sized
      from the design load instead of inheriting 609-custom fixed powers.
    """
    return DesignProject(
        name="default",
        site=SiteConfig(lat=31.2, lon=121.5, tz_hours=8.0, city="Shanghai"),
        envelope=EnvelopeConfig(
            U_wall_A=20.0,        # W/K — insulated small room (~10 m² footprint)
            A_window=0.0,
            eta_solar=0.15,
            ach=0.001,
            permeance=0.0,
            V_room=40.0,          # m³
            C_z=40000.0,          # Wh/K
        ),
        led=LEDConfig(covered_area=10.0),   # 10 m² canopy → auto power ~1600 W
        hvac=HVACConfig(auto_size=True),
        deh=DEHConfig(auto_size=True),
    )


def preset_609() -> DesignProject:
    """Fengxian lettuce PFAL reference (digital-twin calibrated parameters).

    P4-5 (MAJOR): the digital twin shipped C_z = 499,597 Wh/K (== ~430 m^3 of
    water in a 200 m^3 room), a "quasi-frozen" thermal state — T_z locked in
    [18.5, 22.5] C with zero heating hours in Shanghai winter.  Physical lumped
    capacity of a light sandwich-panel PFAL is dominated by room air
    (V=200 m^3 -> ~67 kWh/K); structure/racking/equipment/canopy water add
    ~30-130 kWh/K.  C_z = 200,000 Wh/K sits mid-range of the defensible
    100-300 kWh/K band and lets cold-season nights drop below
    T_heat_setpoint so heat-pump mode engages at the P2-3 COP.  Re-verify
    with a cold-climate sensitivity before any re-calibration.
    """
    return DesignProject(
        name="fengxian_lettuce_609",
        site=SiteConfig(lat=30.9, lon=121.5, tz_hours=8.0, city="Shanghai"),
        envelope=EnvelopeConfig(
            U_wall_A=125.3,
            A_window=0.0,
            eta_solar=0.15,
            ach=0.001,
            permeance=0.0,
            V_room=200.0,
            C_z=200000.0,  # Wh/K (200 kWh/K) — see P4-5: ~3x room-air capacity
        ),
        led=LEDConfig(light_start_hour=6, photoperiod_hours=16, heat_fraction=1.0),
    )


PRESETS = {
    "609": {"label": "609 — Fengxian Lettuce PFAL", "factory": preset_609},
    "default": {"label": "Default", "factory": preset_default},
}
