"""
Design presets.

``preset_609`` reproduces the Fengxian lettuce PFAL (the "609 project") physics
so the new simulator can be validated against the archived digital twin. Other
presets provide convenient starting points.

R26 (currency engine): presets are built through ``DesignProject.from_dict``
(not raw dataclass construction) so every omitted price is materialized from
the USD-baseline defaults with the project's ``exchange_rate`` — a preset is
numerically identical to an equivalent YAML, and programmatic consumers
(engine, template writer) always see concrete project-currency values instead
of the ``None`` sentinels.
"""

from .project import DEHConfig, DesignProject

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
    return DesignProject.from_dict(
        {
            "name": "default",
            # T5 (P2-3): coords are the authoritative city_db["Shanghai"] values
            # (vfed/weather/city_db.py) so the preset cache key matches the city
            # it simulates (was 31.2/121.5).
            # Round 22: weather_provider/ghi_scale stay at their SiteConfig
            # defaults ("open-meteo", 1.0) — presets do not pin the weather
            # source, so every baseline is bitwise unchanged by the provider
            # switch.
            "site": {"lat": 31.23, "lon": 121.47, "tz_hours": 8.0, "city": "Shanghai"},
            "envelope": {
                "U_wall_A": 20.0,  # W/K — insulated small room (~10 m² footprint)
                "A_window": 0.0,
                "eta_solar": 0.15,
                "ach": 0.001,
                "permeance": 0.0,
                "V_room": 40.0,  # m³
                "C_z": 40000.0,  # Wh/K
            },
            "led": {"covered_area": 10.0},  # 10 m² canopy → auto power ~1600 W
            # T6 (P2-3): led.power_w keeps the LEDConfig 1300 W class default,
            # which is a PLACEHOLDER example only -- size it from your actual
            # fixture schedule (or keep auto_deduce=true, which recomputes
            # power_w = ppfd_target * covered_area / efficacy and ignores it).
            "hvac": {"auto_size": True},
            "deh": {"auto_size": True},
        }
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
    return DesignProject.from_dict(
        {
            "name": "fengxian_lettuce_609",
            # T5 (P2-3): coords are the authoritative city_db["Shanghai"] values
            # (vfed/weather/city_db.py) so the preset cache key matches the city
            # it simulates (was 30.9/121.5).
            "site": {"lat": 31.23, "lon": 121.47, "tz_hours": 8.0, "city": "Shanghai"},
            "envelope": {
                "U_wall_A": 125.3,
                "A_window": 0.0,
                "eta_solar": 0.15,
                "ach": 0.001,
                "permeance": 0.0,
                "V_room": 200.0,
                "C_z": 200000.0,  # Wh/K (200 kWh/K) — see P4-5: ~3x room-air capacity
            },
            "led": {"light_start_hour": 6, "photoperiod_hours": 16, "heat_fraction": 1.0},
            # T6 (P2-3): led.power_w keeps the LEDConfig 1300 W class default,
            # which is a PLACEHOLDER example only -- size it from the real
            # fixture schedule (auto_deduce=true here recomputes it from
            # ppfd_target * covered_area / efficacy and ignores power_w).
            # P0-4: explicit dark-period setpoint (see docstring) — the 18 C class
            # default is unreachable against this room's night balance.
            "setpoints": {"T_dark": 21.0},
            # R34/W3-D (609 counterpart alignment, sweep report route3): pin
            # the two device-re calibration knobs recommended by the wave 1-A
            # sensitivity scan (user-gym/benchmarks/route3_sensitivity_scan.md,
            # migration candidate D1).
            #   deh.smer 3.5  — rated SMER of a GB/T 19411 whole-facility
            #                   dehumidifier class (delivered SMER ~1.03 at the
            #                   609 load; the class default 2.0 carried the B8
            #                   -47% conservatism vs the ENERGY STAR IEF band).
            #   hvac.eta_II 0.33 — Carnot 2nd-law efficiency: moves the annual
            #                   demand-weighted COP 3.99 -> 3.85, mid-band of
            #                   the GB 21455 SCOP 3.0-4.0 comparison window,
            #                   clearing the B7 optimism flag.
            # Pure parameter re-calibration: every R33/R34 switch (smer_curve,
            # smer_map, cop_soft_cap, defrost, crankcase) stays at its default
            # OFF — no model-structure change.
            "hvac": {"eta_II": 0.33},
            "deh": {"smer": 3.5},
        }
    )


def preset_609_identified() -> DesignProject:
    """preset_609 + identified DEH commissioning map (609 digital twin).

    Same room/site/LED/setpoints as preset_609; the DEH device is replaced
    by the identified commissioning configuration ported from the 609
    digital twin (models/deh_{power_coeffs_calibrated, modulation}.json,
    updater re-calibration 2026-09-22).  Gate evidence (holdout week
    2026-09-16..23, one-step replay): P_deh MAE 389 W vs twin-local-hybrid
    507 W; free-run RH MAE 14.98 % (conservation-stable).  smer = 0.25 is
    an EFFECTIVE commissioning value (train bias-zero crossing, absorbing
    infiltration / HVAC-latent / transpiration residual) — NOT a physical
    SMER claim.  fan_power_w = 0 because P_ref was identified against the
    NET meter (fan included).

    preset_609 itself stays on stock DEH: its published annual baselines
    (Energy & Buildings 361:117462) must remain reproducible.
    """
    p = preset_609()
    p.name = "fengxian_lettuce_609_identified"
    p.deh = DEHConfig(
        P_ref_w=1554.3,
        poly_e=(1.0, 0.013103, 0.002662, 0.002768, 0.002078, -0.002861),
        T_mean=21.4,
        T_std=1.69,
        W_mean=0.011328,
        W_std=0.001357,
        smer=0.25,
        control="on_off",
        fan_power_w=0.0,
        tau_q=(90.0, 30.0),
        tau_m=(120.0, 20.0),
        setpoint_modulation={
            "lookup": {
                "30": 0.7170938104635799,
                "40": 0.7267837146359536,
                "45": 0.7331191679313002,
                "50": 0.679025751897272,
                "55": 0.6916748161497909,
                "60": 0.6401562306454929,
                "70": 0.06810030491865396,
                "75": 0.1330467536187675,
                "80": 0.04261066155552269,
            },
            "lookup_dark": {
                "30": 0.9568670496712134,
                "40": 0.9754835034269306,
                "45": 0.918017000012886,
                "50": 0.8945194671329542,
                "55": 0.793355848954101,
                "60": 0.9485119179365091,
                "70": 0.4638576553329792,
                "75": 0.4905356512715363,
                "80": 0.488775933693853,
            },
            "rh_err_coef": 0.009808,
        },
    )
    return p


PRESETS = {
    "609": {"label": "609 — Fengxian Lettuce PFAL", "factory": preset_609},
    "609_identified": {
        "label": "609 Identified — Fengxian Lettuce PFAL, twin-identified DEH",
        "factory": preset_609_identified,
    },
    "default": {"label": "Default", "factory": preset_default},
}
