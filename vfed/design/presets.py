"""
Design presets.

``preset_609`` reproduces the Fengxian lettuce PFAL (the "609 project") physics
so the new simulator can be validated against the archived digital twin. Other
presets provide convenient starting points.
"""

from .project import (
    DEHConfig,
    DesignProject,
    EnvelopeConfig,
    HVACConfig,
    LEDConfig,
    SetpointConfig,
    SiteConfig,
)

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
            U_wall_A=20.0,  # W/K — insulated small room (~10 m² footprint)
            A_window=0.0,
            eta_solar=0.15,
            ach=0.001,
            permeance=0.0,
            V_room=40.0,  # m³
            C_z=40000.0,  # Wh/K
        ),
        led=LEDConfig(covered_area=10.0),  # 10 m² canopy → auto power ~1600 W
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

    P0-4 (MAJOR): setpoints.T_dark is pinned to 21.0 C explicitly (the
    SetpointConfig class default of 18.0 C stays untouched for other
    presets).  With C_z = 200 kWh/K the LED-off room floats at ~21.7-23.4 C
    at night (envelope gains plus DEH condenser heat), so T_dark = 18 C was
    physically unreachable: holding 18 C against a ~22 C night balance needs
    ~800 kWh of net heat removal (4 K x 200 kWh/K) while the 3 kW unit at
    COP ~4 extracts ~96 kWh over an 8-h night — the result was 2,920/2,920
    dark hours pinned at full 3,070 W (8,964 kWh/yr of pure saturation,
    HVAC 74.5%) chasing a setpoint the room cannot reach, with dark T_z
    never dropping below 20.6 C.  21 C sits inside the common lettuce
    dark-period band (18-22 C; a slightly warm dark period is standard PFAL
    practice to avoid pointless night conditioning) and near the room's
    natural night balance, so the VFD modulates instead of saturating:
    dark full-speed hours drop 2,920 -> 195 (6.7% of dark hours) and the
    dark-period mean T_z lands within 1.5 K of the setpoint, verified by
    simulation.  T_dark is also the heating setpoint (T_heat_setpoint), so
    it must NOT float above the night balance temperature: at 22 C the
    heat pump would engage ~93 h/yr at night to hold a setpoint above the
    natural float, swapping cooling waste for heating waste.
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
        # P0-4: explicit dark-period setpoint (see docstring) — the 18 C class
        # default is unreachable against this room's night balance.
        setpoints=SetpointConfig(T_dark=21.0),
    )


PRESETS = {
    "609": {"label": "609 — Fengxian Lettuce PFAL", "factory": preset_609},
    "default": {"label": "Default", "factory": preset_default},
}
