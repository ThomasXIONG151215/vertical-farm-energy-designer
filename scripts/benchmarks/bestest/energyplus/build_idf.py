"""Generate ASHRAE 140 BESTEST Case 600/600FF/900/900FF EnergyPlus idf files,
plus Case 600p -- an in-house plant-factory wet variant (NOT part of ASHRAE
140; no official band exists for it).

Definitions transcribed verbatim from the LBNL modelica-buildings BESTEST
package (Buildings/ThermalZones/Detailed/Validation/BESTEST/, 2022 revision
of issues #3005/#3396) -- the same source bestest_lib.py wall layers came
from.  Per-case deltas vs Case600FF (all cases share geometry/window/roof/
gains/infiltration):

  600p     : Case 600 skeleton + 200 W latent-only constant moisture source
             (≈7.1 L/day, mirrors vfed transpiration daily_water_L=7.08) +
             ZoneHVAC:Dehumidifier:DX (15 L/day, EF 2.0 L/kWh == SMER 2.0,
             flat curves) + humidistat 60 % -- wet-path cross-check vs vfed
             DEH (on_off, deadband 2).  DX control is E+ cycling PLR, so RH
             will hug the setpoint while vfed bang-bangs 60..62 %; annual
             DEH energy/water removal are the real comparators (DIAGNOSTIC).

  600/600FF : light-weight wall (siding + 66mm insulation + gypsum),
              raised floor (R25 + 25mm wood deck)
  900/900FF : high-mass wall (siding + 61.5mm insulation + 100mm concrete
              block), raised floor (R25 + 80mm concrete)

Fidelity gate (run_energyplus.py): annual heating/cooling [GJ] and FF
min/max/mean must land inside the ASHRAE 140-2020 reference bands.

Usage:  python build_idf.py      (writes case600.idf ... case900ff.idf here)
Then:   python run_energyplus.py (runs E+ 23.1, gates vs bands, hourly csv)
"""

from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent

# --- LBNL BESTEST Data records (verbatim, outside -> inside) ---------------
# (thickness m, k W/mK, rho kg/m3, c J/kgK)
MAT_WOOD_SIDING = (0.009, 0.140, 530.0, 900.0)
MAT_GYPSUM = (0.012, 0.160, 950.0, 840.0)   # wall 600
MAT_GYPSUM_R = (0.010, 0.160, 950.0, 840.0)  # roof (10 mm)
MAT_ROOF_DECK = (0.019, 0.140, 530.0, 900.0)

WALL_600 = [MAT_WOOD_SIDING, (0.066, 0.040, 12.0, 840.0), MAT_GYPSUM]
WALL_900 = [MAT_WOOD_SIDING, (0.0615, 0.040, 10.0, 1400.0),
            (0.100, 0.510, 1400.0, 1000.0)]
ROOF = [MAT_ROOF_DECK, (0.1118, 0.040, 12.0, 840.0), MAT_GYPSUM_R]
# Floors: R-only layer (k0.04, c=0, d=0) -> E+ Material:NoMass, plus a mass layer.
FLOOR_600 = (25.075, (0.025, 0.140, 650.0, 1200.0))    # 1003mm insul + 25mm wood
FLOOR_900 = (25.175, (0.080, 1.130, 1400.0, 1000.0))   # 1007mm insul + 80mm concrete

# Window Win600/Glass600 (2022 revision): double 3.048mm clear, 12mm air gap.
GLASS = dict(x=0.003048, k=1.0, tau_sol=0.834, rho_sol=0.075, tau_ir=0.0,
             eps_ir=0.84)
GAP_AIR = 0.012

# Case control: 140-2020 constant 200 W internal gain (80 conv + 120 rad),
# 0.414 ACH (altitude-corrected), thermostat 20/27 C continuous.
Q_INT_W, RAD_FRAC = 200.0, 0.6
ACH = 0.414
T_HEAT, T_COOL = 20.0, 27.0

# Case 600p wet path: latent source + DX dehumidifier + humidistat.
# vfed parity: transpiration daily 7.08 L/day (~295 g/h ~ 200 W latent at
# h_fg 2.43-2.45 MJ/kg), DEH M_deh_nom 15 L/day / SMER 2.0 / on_off,
# setpoints RH 60.  DX curves all 1.0 == idealized flat capacity/EF.
Q_LATENT_W = 200.0        # latent-only moisture source, 24 h constant
DEH_L_PER_DAY, DEH_EF = 15.0, 2.0   # L/kWh == SMER (L/kWh), same unit
DEH_AIRFLOW = 0.12        # m3/s, per WindACRHControl.idf DX example
RH_SP = 60.0

# Geometry: 6 m (E-W) x 8 m (N-S) x 2.7 m; south (y=0) wall 8x2.7 with a
# centered 6x2 m frameless window.  Opaque wall 75.6 - 12 = 63.6 m2.
L_X, L_Y, H = 6.0, 8.0, 2.7
WIN_W, WIN_H, WIN_SILL = 6.0, 2.0, (H - 2.0) / 2.0  # vertically centered


def _material(name, m, rough="Rough"):
    t, k, rho, c = m
    # LBNL: absIR 0.9, absSol 0.6 (all BESTEST opaque surfaces)
    return (f"  Material,\n    {name}, !- Name\n    {rough}, !- Roughness\n"
            f"    {t:.4f}, !- Thickness {{m}}\n    {k:.3f}, !- Conductivity "
            f"{{W/m-K}}\n    {rho:.1f}, !- Density {{kg/m3}}\n"
            f"    {c:.1f}, !- Specific Heat {{J/kg-K}}\n"
            f"    0.9, !- Thermal Absorptance\n    0.6, !- Solar Absorptance"
            f"\n    0.6; !- Visible Absorptance\n")


def _nomass(name, r):
    return (f"  Material:NoMass,\n    {name}, !- Name\n    Rough, "
            f"!- Roughness\n    {r:.3f}, !- Thermal Resistance "
            f"{{m2-K/W}}\n    0.9, !- Thermal Absorptance\n"
            f"    0.6, !- Solar Absorptance\n    0.6; !- Visible\n")


def _construction(name, layers):
    body = ",\n".join(f"    {ly}" for ly in layers)
    return f"  Construction,\n    {name}, !- Name\n{body};\n"


def _surface(name, stype, constr, bc, sun, wind, vertices, zone="ZONE1",
             parent=None):
    vs = ",\n".join(
        f"    {x:.3f}, {y:.3f}, {z:.3f}" for x, y, z in vertices)
    # E+ 23.1 field order: Name, Type, Construction, Zone, Space,
    # BC, BC-Object, Sun, Wind, ViewFactor, NVerts, verts...
    return ("  BuildingSurface:Detailed,\n"
            f"    {name}, !- Name\n    {stype}, !- Surface Type\n"
            f"    {constr}, !- Construction Name\n"
            f"    {parent if parent else zone}, !- Zone Name\n"
            f"    , !- Space Name\n"
            f"    {bc}, !- Outside Boundary Condition\n"
            f"    , !- Outside Boundary Condition Object\n"
            f"    {sun}, !- Sun Exposure\n    {wind}, !- Wind Exposure\n"
            f"    , !- View Factor to Ground\n"
            f"    {len(vertices)}, !- Number of Vertices\n"
            f"{vs};\n")


def render_idf(case):
    heavy = case.startswith("900")
    hvac = not case.endswith("FF")
    wet = case.endswith("p")
    wall = WALL_900 if heavy else WALL_600
    floor_r, floor_m = FLOOR_900 if heavy else FLOOR_600

    mats = [
        _material("WOOD-SIDING", wall[0]),
        _material("WALL-INSUL", wall[1]),
        _material("WALL-INNER", wall[2]),
        _material("ROOF-DECK", ROOF[0]),
        _material("ROOF-INSUL", ROOF[1]),
        _material("ROOF-GYPSUM", ROOF[2]),
        _nomass("FLOOR-INSUL-R", floor_r),
        _material("FLOOR-MASS", floor_m),
    ]
    if heavy:
        wall_layers = "WOOD-SIDING, WALL-INSUL, WALL-INNER"
        floor_layers = "FLOOR-INSUL-R, FLOOR-MASS"
    else:
        wall_layers = "WOOD-SIDING, WALL-INSUL, WALL-INNER"
        floor_layers = "FLOOR-INSUL-R, FLOOR-MASS"
    constrs = [
        _construction("WALL-CASE", wall_layers.split(", ")),
        _construction("ROOF-CASE", ["ROOF-DECK", "ROOF-INSUL", "ROOF-GYPSUM"]),
        _construction("FLOOR-CASE", floor_layers.split(", ")),
        _construction("WIN-CASE", ["GLASS-CASE", "AIR-GAP-CASE", "GLASS-CASE"]),
    ]
    glass = (
        "  WindowMaterial:Glazing,\n    GLASS-CASE, !- Name\n"
        "    SpectralAverage, !- Optical Data Type\n    , !- Data File\n"
        f"    {GLASS['x']:.6f}, !- Thickness {{m}}\n"
        f"    {GLASS['tau_sol']}, !- Solar Transmittance\n"
        f"    {GLASS['rho_sol']}, !- Front Solar Reflectance\n"
        f"    {GLASS['rho_sol']}, !- Back Solar Reflectance\n"
        f"    {GLASS['tau_sol']}, !- Visible Transmittance\n"
        f"    {GLASS['rho_sol']}, !- Front Visible Reflectance\n"
        f"    {GLASS['rho_sol']}, !- Back Visible Reflectance\n"
        f"    {GLASS['tau_ir']}, !- Infrared Transmittance\n"
        f"    {GLASS['eps_ir']}, !- Front Emissivity\n"
        f"    {GLASS['eps_ir']}, !- Back Emissivity\n"
        f"    {GLASS['k']}, !- Conductivity {{W/m-K}}\n    1.0; !- Dirt "
        "Correction\n"
        "  WindowMaterial:Gas,\n    AIR-GAP-CASE, !- Name\n"
        f"    Air, {GAP_AIR:.3f}; !- Gas Type, Thickness\n"
    )

    x1, x2 = (L_X - WIN_W) / 2, (L_X + WIN_W) / 2
    z1, z2 = WIN_SILL, WIN_SILL + WIN_H
    surfaces = "".join([
        _surface("FLOOR", "Floor", "FLOOR-CASE", "Outdoors", "NoSun",
                 "NoWind", [(0, 0, 0), (0, L_Y, 0), (L_X, L_Y, 0), (L_X, 0, 0)]),
        _surface("ROOF", "Roof", "ROOF-CASE", "Outdoors", "SunExposed",
                 "WindExposed",
                 [(0, 0, H), (L_X, 0, H), (L_X, L_Y, H), (0, L_Y, H)]),
        _surface("SOUTH-WALL", "Wall", "WALL-CASE", "Outdoors", "SunExposed",
                 "WindExposed", [(0, 0, 0), (L_X, 0, 0), (L_X, 0, H), (0, 0, H)]),
        _surface("NORTH-WALL", "Wall", "WALL-CASE", "Outdoors", "SunExposed",
                 "WindExposed",
                 [(L_X, L_Y, 0), (0, L_Y, 0), (0, L_Y, H), (L_X, L_Y, H)]),
        _surface("EAST-WALL", "Wall", "WALL-CASE", "Outdoors", "SunExposed",
                 "WindExposed",
                 [(L_X, 0, 0), (L_X, L_Y, 0), (L_X, L_Y, H), (L_X, 0, H)]),
        _surface("WEST-WALL", "Wall", "WALL-CASE", "Outdoors", "SunExposed",
                 "WindExposed",
                 [(0, L_Y, 0), (0, 0, 0), (0, 0, H), (0, L_Y, H)]),
        ("  FenestrationSurface:Detailed,\n    WIN-S, !- Name\n"
         "    Window, !- Class\n    WIN-CASE, !- Construction\n"
         "    SOUTH-WALL, !- Building Surface\n    , !- Outside Facing Env\n"
         "    , !- View Factor to Ground\n    , !- Frame/Divider\n"
         "    1, !- Multiplier\n    4, !- Number of Vertices\n"
          f"    {x1:.3f}, 0, {z1:.3f}, {x2:.3f}, 0, {z1:.3f}, "
          f"{x2:.3f}, 0, {z2:.3f}, {x1:.3f}, 0, {z2:.3f};\n"),
    ])

    loads = (
        "  Schedule:Compact,\n    ALWAYS, Fraction, Through: 12/31, "
        "For: AllDays, Until: 24:00, 1.0;\n"
        f"  OtherEquipment,\n    INT-GAIN, None, ZONE1, ALWAYS, "
        f"EquipmentLevel, {Q_INT_W:.1f}, , , 0.0, {RAD_FRAC}, 0.0; "
        "!- 200W, 0 latent, 0.6 radiant (120W rad + 80W conv), 0 lost\n"
        f"  ZoneInfiltration:DesignFlowRate,\n    INFIL, ZONE1, ALWAYS, "
        f"AirChanges/Hour, 0, 0, 0, {ACH}, 1;\n"
        "!- E+ 23.1: ACH value is field 8; field 5 is Design Flow Rate\n"
    )

    # Empty SeqCool/HeatFrac schedule fields are read as fraction=0 under
    # the default SequentialLoad scheme -- loads collapse to ~28% (verified:
    # 600 heat 14.702 -> 4.084 GJ).  Name an explicit 1.0 schedule instead.
    eq_list = ("  Schedule:Compact,\n    FRAC1, Fraction, Through: 12/31, "
               "For: AllDays, Until: 24:00, 1.0;\n"
               "  ZoneHVAC:EquipmentList,\n    ZONE-EQ, , "
               "ZoneHVAC:IdealLoadsAirSystem, IDEAL, 1, 1, FRAC1, FRAC1"
               + (",\n    ZoneHVAC:Dehumidifier:DX, DEH-DX, 2, 2, FRAC1, "
                  "FRAC1" if wet else "") + ";\n")
    if wet:
        # DX inlet must be a zone exhaust node, DX outlet a zone inlet node
        # (idd).  NodeList is the official pattern (WindACRHControl.idf) and
        # is innocent -- the earlier load collapse was the empty SeqFrac
        # fields (=0) in the equipment list, not the NodeList.  DX must have
        # its own outlet node; sharing ZONE1-AIR-IN with IdealLoads corrupts
        # the supply node (thermostat stops tracking, T free-floats).
        connections = (
            "  NodeList,\n    ZONE1-INLETS, ZONE1-AIR-IN, ZONE1-DEH-OUT;\n"
            "  NodeList,\n    ZONE1-EXHAUSTS, ZONE1-DEH-IN;\n"
            "  ZoneHVAC:EquipmentConnections,\n    ZONE1, ZONE-EQ, "
            "ZONE1-INLETS, ZONE1-EXHAUSTS, ZONE1-AIR-NODE, "
            "ZONE1-AIR-RETURN;\n"
        )
        deh_nodes = ("    ZONE1-DEH-IN, !- Air Inlet Node\n"
                     "    ZONE1-DEH-OUT, !- Air Outlet Node\n")
    else:
        connections = (
            "  ZoneHVAC:EquipmentConnections,\n    ZONE1, ZONE-EQ, "
            "ZONE1-AIR-IN, , ZONE1-AIR-NODE, ZONE1-AIR-RETURN;\n"
        )
        deh_nodes = ""

    hvac_block = "" if not hvac else (
        "  Schedule:Compact,\n    HEAT-SP, Temperature, Through: 12/31, "
        f"For: AllDays, Until: 24:00, {T_HEAT};\n"
        "  Schedule:Compact,\n    COOL-SP, Temperature, Through: 12/31, "
        f"For: AllDays, Until: 24:00, {T_COOL};\n"
        "  Schedule:Compact,\n    TSTAT-TYPE, Number, Through: 12/31, "
        "For: AllDays, Until: 24:00, 4;\n"
        "  ThermostatSetpoint:DualSetpoint,\n    DUAL-SP, HEAT-SP, COOL-SP;\n"
        "  ZoneControl:Thermostat,\n    ZONE-TSTAT, ZONE1, TSTAT-TYPE, "
        "ThermostatSetpoint:DualSetpoint, DUAL-SP;\n"
        "  ZoneHVAC:IdealLoadsAirSystem,\n    IDEAL, , ZONE1-AIR-IN, , , "
        "50, 13, 0.015, 0.009, NoLimit, , , NoLimit, , , , , None; !- "
        "supply T/W per PurchAirTables.idf; NoLimit caps; field 18 A10=None "
        "(no dehumid) -- E+ default is ConstantSensibleHeatRatio w/ SHR 0.7, "
        "which silently removes moisture alongside sensible cooling (found "
        "in 600p wet audit: IdealLoads was the 3rd moisture sink)\n"
        + eq_list + connections
    )

    wet_block = "" if not wet else (
        # 200 W latent-only constant source ~ 7.1 L/day (vfed: 7.08)
        f"  OtherEquipment,\n    TRANSPIRE-GAIN, None, ZONE1, ALWAYS, "
        f"EquipmentLevel, {Q_LATENT_W:.1f}, , , 1.0, 0.0, 0.0; "
        "!- latent-only (E+ converts W->kg/s via internal h_fg)\n"
        f"  Schedule:Compact,\n    HUM-SP, Fraction, Through: 12/31, "
        f"For: AllDays, Until: 24:00, 0.0;\n"
        f"  Schedule:Compact,\n    DEH-SP, Fraction, Through: 12/31, "
        f"For: AllDays, Until: 24:00, {RH_SP};\n"
        "  ZoneControl:Humidistat,\n    ZONE-HSTAT, ZONE1, HUM-SP, DEH-SP; "
        "!- humidify field is required -> pin 0 (no humidifier present)\n"
        "  Curve:Biquadratic,\n    DX-WATER-CURVE, 1.0, 0, 0, 0, 0, 0, "
        "10.0, 35.0, 0.0, 100.0; !- x=Tdb 10-35C, y=RH 0-100%, flat 1.0\n"
        "  Curve:Biquadratic,\n    DX-EF-CURVE, 1.0, 0, 0, 0, 0, 0, "
        "10.0, 35.0, 0.0, 100.0;\n"
        "  Curve:Quadratic,\n    DX-PLF-CURVE, 1.0, 0, 0, 0.0, 1.0;\n"
        f"  ZoneHVAC:Dehumidifier:DX,\n    DEH-DX, !- Name\n    ALWAYS, "
        f"!- Availability Schedule\n" + deh_nodes +
        f"    {DEH_L_PER_DAY}, !- Rated Water Removal {{L/day}}\n    {DEH_EF}, "
        f"!- Rated Energy Factor {{L/kWh}} (= SMER)\n    {DEH_AIRFLOW}, "
        "!- Rated Air Flow Rate {m3/s}\n    DX-WATER-CURVE, "
        "!- Water Removal Curve\n    DX-EF-CURVE, !- Energy Factor Curve\n"
        "    DX-PLF-CURVE, !- Part Load Factor Curve\n    10.0, "
        "!- Min Dry-Bulb {C}\n    35.0, !- Max Dry-Bulb {C}\n    0.0; "
        "!- Off-Cycle Parasitic {W}\n"
    )

    # Moisture-audit variables: infiltration latent (all cases) +
    # IdealLoads latent (HVAC cases only -- FF has no IdealLoads and a
    # wildcard request would warn).  Names per out_case600p/eplusout.rdd.
    outputs = (
        "  Output:VariableDictionary, IDF;\n"
        "  Output:Variable, *, Zone Mean Air Temperature, Hourly;\n"
        "  Output:Variable, *, Infiltration Latent Heat Loss Energy, "
        "Hourly;\n"
        "  Output:Variable, *, Infiltration Latent Heat Gain Energy, "
        "Hourly;\n"
        + ("  Output:Variable, *, Zone Ideal Loads Supply Air Sensible "
           "Heating Energy, Hourly;\n"
           "  Output:Variable, *, Zone Ideal Loads Supply Air Sensible "
           "Cooling Energy, Hourly;\n"
           "  Output:Variable, *, Zone Ideal Loads Supply Air Latent "
           "Cooling Energy, Hourly;\n" if hvac else "")
        + ("  Output:Variable, *, Zone Air Relative Humidity, Hourly;\n"
           "  Output:Variable, *, Zone Dehumidifier Electricity Energy, "
           "Hourly;\n"
           "  Output:Variable, *, Zone Dehumidifier Removed Water Mass, "
           "Hourly;\n"
           "  Output:Variable, *, Zone Dehumidifier Sensible Heating "
           "Energy, Hourly;\n"
           if wet else "")
    )

    header = (
        f"!- What: ASHRAE 140 BESTEST Case {case} (E+ re-implementation)\n"
        "!- Source: LBNL modelica-buildings Buildings/ThermalZones/Detailed/"
        "Validation/BESTEST (2022 rev, issues #3005/#3396)\n"
        "!- Geometry: 6x8x2.7 m, south window 12 m2, 200 W int gain, "
        f"{ACH} ACH, {'thermostat 20/27 C' if hvac else 'free float'}\n"
        "!- Gate: annual loads / FF stats must land in the 140-2020 bands "
        "(run_energyplus.py)\n\n"
    )

    body = (
        "  Version,23.1;\n"
        "  Timestep,6;\n"
        "  GlobalGeometryRules, LowerLeftCorner, Counterclockwise, "
        "Relative, Relative;\n"
        "  Building,\n    BESTEST-CASE, !- Name\n    0, !- North Axis\n"
        "    Country, !- Terrain\n    , !- Loads Convergence\n"
        "    , !- Temp Convergence\n"
        "    FullInteriorAndExterior, !- Solar Distribution\n"
        "    25, !- Max Warmup Days\n    6; !- Min Warmup\n"
        "  SimulationControl, No, No, No, No, Yes;\n"
        "  RunPeriod,\n    RP, !- Name\n    1, 1, , 12, 31, , "
        "!- begin m/d/yr, end m/d/yr\n"
        "    Sunday, !- Day of Week\n    Yes, !- Use Weather File DOW\n"
        "    Yes, !- Use Weather File Holidays\n"
        "    Yes; !- Use Weather File Daylight Saving\n"
        "  Zone,\n    ZONE1, !- Name\n    0, 0, 0, 0, !- dir/x/y/z\n"
        "    , !- Zone Type\n    1, !- Multiplier\n"
        "    , !- Ceiling Height\n    , !- Volume\n"
        "    48.0, !- Floor Area\n"
        "    , !- Inside Convection\n    , !- Outside Convection\n"
        "    Yes; !- Part of Total Floor Area\n"
    )

    return (header + "".join(mats) + "\n" + "".join(constrs) + "\n" + glass
            + "\n" + body + "\n" + surfaces + "\n" + loads + "\n"
            + hvac_block + "\n" + wet_block + outputs)


def main():
    for case in ("600", "600p", "600FF", "900", "900FF"):
        p = OUT_DIR / f"case{case.lower()}.idf"
        p.write_text(render_idf(case), encoding="utf-8")
        print(f"wrote {p} ({p.stat().st_size} B)")


if __name__ == "__main__":
    main()
