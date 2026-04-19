"""
IDF Builder - Programmatic EnergyPlus IDF Generation for PFAL Buildings

Fully controllable IDF generation without external template files.
Supports parametric construction of PFAL building models via code or CLI.

Usage:
    from idf_builder import IDFBuilder

    idf = IDFBuilder()
    idf.set_building("MyPFAL", floor_area=200, num_zones=6)
    idf.add_lights(zone=0, power_density=350)
    idf.add_ventilation(zone=0, flow_rate=0.5, schedule_name="VentilationSchedule")
    idf.add_constant_schedule("VentilationSchedule", "Fraction", 0.3)
    print(idf.build())
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional


@dataclass
class ScheduleCompact:
    """Schedule:Compact object"""
    name: str
    schedule_type: str  # e.g., "Fraction", "Temperature"
    through: str = "1/1"
    for_field: str = "AllDays"
    values: List[float] = field(default_factory=list)

    def to_idf(self) -> str:
        if not self.values:
            return f"""Schedule:Compact,
    {self.name},                !- Name
    {self.schedule_type},       !- Schedule Type Limits Name
    Through: {self.through},
    For: {self.for_field},
    Value: 0.3;       !- Default"""

        lines = [f"""Schedule:Compact,
    {self.name},                !- Name
    {self.schedule_type},       !- Schedule Type Limits Name"""]

        if len(self.values) == 8760:
            weekly = self.values[:168]
            lines.append("    Through: 1/1,")
            lines.append("    For: AllDays,")
            lines.append(f"    Until: 24:00, {weekly[0]};")
        else:
            lines.append(f"    Through: {self.through},")
            lines.append(f"    For: {self.for_field},")
            if self.values:
                lines.append(f"    Value: {self.values[0]};")
            else:
                lines.append(f"    Value: 0.3;")

        return "\n".join(lines)


@dataclass
class ScheduleConstant:
    """Schedule:Constant object"""
    name: str
    schedule_type: str
    value: float

    def to_idf(self) -> str:
        return f"""Schedule:Constant,
    {self.name},                !- Name
    {self.schedule_type},       !- Schedule Type Limits Name
    {self.value};                    !- Hourly Value"""


@dataclass
class Zone:
    """Zone object"""
    name: str
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    multiplier: int = 1
    ceiling_height: float = 2.5  # m (typical for PFAL racking)
    floor_area: Optional[float] = None

    def to_idf(self) -> str:
        return f"""Zone,
    {self.name},                !- Name
    {self.x},                  !- X Origin {{m}}
    {self.y},                  !- Y Origin {{m}}
    {self.z},                  !- Z Origin {{m}}
    {self.multiplier},         !- Multiplier
    {self.ceiling_height},     !- Ceiling Height {{m}}
    {self.floor_area if self.floor_area else "AutoCalculate"},  !- Floor Area {{m2}}
    ,                          !- Zone Inside Convection Algorithm
    ,                          !- Zone Outside Convection Algorithm
    Yes;                       !- Part of Total Floor Area"""


@dataclass
class Lights:
    """Lights object"""
    name: str
    zone_name: str
    watts_per_zone_floor_area: float  # W/m2
    schedule_name: str = "LightSchedule"

    def to_idf(self) -> str:
        return f"""Lights,
    {self.name},                !- Name
    {self.zone_name},          !- Zone or ZoneList or Space or SpaceList Name
    {self.schedule_name},       !- Schedule Name
    Watts/Area,                !- Design Level Calculation Method
    ,                          !- Lighting Level {{W}}
    {self.watts_per_zone_floor_area},  !- Watts per Zone Floor Area {{W/m2}}
    ,                          !- Watts per Person {{W/person}}
    0,                         !- Return Air Fraction
    0.0,                       !- Fraction Radiant
    0.35,                      !- Fraction Visible
    1;                         !- Fraction Replaceable"""


@dataclass
class ElectricEquipment:
    """ElectricEquipment object (equipment heat gain)"""
    name: str
    zone_name: str
    design_level: float  # W
    schedule_name: str = "EquipSchedule"

    def to_idf(self) -> str:
        return f"""ElectricEquipment,
    {self.name},                !- Name
    {self.zone_name},           !- Zone or ZoneList or Space or SpaceList Name
    {self.schedule_name},       !- Schedule Name
    EquipmentLevel,            !- Design Level Calculation Method
    {self.design_level},        !- Design Level {{W}}
    ,                          !- Watts per Zone Floor Area {{W/m2}}
    ,                          !- Watts per Person {{W/person}}
    0,                         !- Fraction Latent
    0.2,                       !- Fraction Radiant
    0;                         !- Fraction Lost"""


@dataclass
class ZoneVentilation:
    """ZoneVentilation:DesignFlowRate object"""
    name: str
    zone_name: str
    flow_rate_per_zone_floor_area: float  # m3/s/m2
    schedule_name: str = "VentilationSchedule"

    def to_idf(self) -> str:
        return f"""ZoneVentilation:DesignFlowRate,
    {self.name},                !- Name
    {self.zone_name},           !- Zone Name
    {self.flow_rate_per_zone_floor_area},  !- Flow Rate per Zone Floor Area {{m3/s-m2}}
    ,                          !- Flow Rate per Person {{m3/s-person}}
    ,                          !- Air Changes per Hour {{1/hr}}
    ,                          !- Ventilation Type
    {self.schedule_name},       !- Schedule Name
    0.0,                       !- Drift Threshold
    0.0,                       !- Temperature Priority
    Yes,                       !- Canceled
    ,                          !- Design Flow Rate Calculation Method
    ,                          !- Outdoor Air Method
    ,                          !- Outdoor Air Flow Rate per Person {{m3/s-person}}
    ,                          !- Outdoor Air Flow Rate per Zone Floor Area {{m3/s-m2}}
    ,                          !- Outdoor Air Flow Rate per Zone {{m3/s}}
    ,                          !- System Outdoor Air Method
    ,                          !- Zone Maximum Outdoor Air Fraction {{dimensionless}}
    0.0,                       !- Acceleration Factor {{dimensionless}}
    ,                          !- Demand Controlled Ventilation Type
    ;                          !- Outdoor Air recess"""


@dataclass
class BuildingSurfaceDetailed:
    """BuildingSurface:Detailed (simplified envelope)"""
    name: str
    surface_type: str  # Wall, Roof, Floor
    construction_name: str
    zone_name: str
    outside_boundary_condition: str  # Outdoors, Ground, etc.
    area: float  # m2
    tilt: float  # degrees (0=horizontal, 90=vertical)
    azimuth: float  # degrees (0=N, 90=E, 180=S, 270=W)

    def to_idf(self) -> str:
        return f"""BuildingSurface:Detailed,
    {self.name},                !- Name
    {self.surface_type},        !- Surface Type
    {self.construction_name},   !- Construction Name
    {self.zone_name},           !- Zone Name
    ,                          !- Space Name
    {self.outside_boundary_condition},  !- Outside Boundary Condition
    ,                          !- Outside Boundary Condition Object
    ,                          !- Sun Exposure
    ,                          !- Wind Exposure
    {self.area},               !- Area (m2)
    {self.tilt},               !- Tilt (deg)
    {self.azimuth},            !- Azimuth (deg)
    ,                          !- Starting X Position {{m}}
    ,                          !- Starting Y Position {{m}}
    ,                          !- Starting Z Position {{m}}
    ,                          !- Starting Coordinate System
    ,                          !- Number of Vertices
    ,                          !- Vertex 1 X {{m}}
    ,                          !- Vertex 1 Y {{m}}
    ,                          !- Vertex 1 Z {{m}}
    ,                          !- Vertex 2 X {{m}}
    ,                          !- Vertex 2 Y {{m}}
    ,                          !- Vertex 2 Z {{m}}
    ,                          !- Vertex 3 X {{m}}
    ,                          !- Vertex 3 Y {{m}}
    ,                          !- Vertex 3 Z {{m}}
    ;                          !- Vertex 4 X {{m}}
    ;                          !- Vertex 4 Y {{m}}
    ;                          !- Vertex 4 Z {{m}}"""


@dataclass
class Thermostat:
    """Thermostat objects"""
    name: str
    zone_name: str
    heating_setpoint: float = 20.0  # C
    cooling_setpoint: float = 25.0  # C
    heating_schedule: str = "HeatingSetpoint"
    cooling_schedule: str = "CoolingSetpoint"

    def to_idf(self) -> str:
        return f"""ThermostatSetpoint:SingleHeating,
    {self.name}_Heating,        !- Name
    {self.heating_schedule};    !- Schedule Name

ThermostatSetpoint:SingleCooling,
    {self.name}_Cooling,        !- Name
    {self.cooling_schedule};    !- Schedule Name

ZoneControl:Thermostat,
    {self.name},                !- Name
    {self.zone_name},           !- Zone Name
    {self.name}_Thermostat,     !- Control Type Schedule Name
    ThermostatStaged;           !- Control Object Type"""


class IDFBuilder:
    """
    PFAL Building IDF Generator

    Fully programmatic construction without external templates.
    Supports lighting, equipment heat gain, ventilation, thermostat for PFAL-specific objects.
    """

    def __init__(self, version: str = "23.1"):
        self.version = version
        self.building_name = "PFAL_Building"
        self.building_floor_area = 100.0  # m2
        self.num_zones = 1
        self.zone_height = 2.5  # m

        # Object storage
        self._schedules_const: List[ScheduleConstant] = []
        self._schedules_compact: List[ScheduleCompact] = []
        self._zones: List[Zone] = []
        self._lights: List[Lights] = []
        self._electric_equipment: List[ElectricEquipment] = []
        self._ventilation: List[ZoneVentilation] = []
        self._surfaces: List[BuildingSurfaceDetailed] = []
        self._thermostats: List[Thermostat] = []

        # Default schedules (inline, no external files)
        self._default_schedules()

    def _default_schedules(self):
        """Add default schedules (inline, no external files)"""
        # Lighting schedule: 24hr constant
        self.add_constant_schedule("LightSchedule", "Fraction", 1.0)

        # Ventilation schedule: 24hr constant 0.3 (air change rate)
        self.add_constant_schedule("VentilationSchedule", "Fraction", 0.3)

        # Thermostat schedules
        self.add_constant_schedule("HeatingSetpoint", "Temperature", 20.0)
        self.add_constant_schedule("CoolingSetpoint", "Temperature", 25.0)

        # Equipment schedule
        self.add_constant_schedule("EquipSchedule", "Fraction", 1.0)

    def set_building(self, name: str, floor_area: float = 100.0, num_zones: int = 1):
        """Set building parameters"""
        self.building_name = name
        self.building_floor_area = floor_area
        self.num_zones = num_zones
        return self

    def add_constant_schedule(self, name: str, schedule_type: str, value: float):
        """Add Schedule:Constant (inline, no external file)"""
        self._schedules_const.append(ScheduleConstant(name, schedule_type, value))
        return self

    def add_compact_schedule(self, schedule: ScheduleCompact):
        """Add Schedule:Compact"""
        self._schedules_compact.append(schedule)
        return self

    def add_zone(self, name: str, x: float = 0.0, y: float = 0.0, z: float = 0.0,
                 multiplier: int = 1, ceiling_height: float = 2.5,
                 floor_area: Optional[float] = None):
        """Add growing zone (rack level)"""
        zone = Zone(
            name=name,
            x=x, y=y, z=z,
            multiplier=multiplier,
            ceiling_height=ceiling_height,
            floor_area=floor_area
        )
        self._zones.append(zone)
        return self

    def add_lights(self, zone_idx: int = 0, power_density: float = 350.0,
                   zone_name: Optional[str] = None, schedule_name: str = "LightSchedule"):
        """
        Add lighting

        Args:
            zone_idx: Zone index (if using auto-naming)
            power_density: Lighting power density W/m2
            zone_name: Zone name (preferred if provided)
            schedule_name: Schedule name
        """
        if zone_name is None:
            zone_name = f"Zone_{zone_idx:02d}"

        lights = Lights(
            name=f"{zone_name}_Lights",
            zone_name=zone_name,
            watts_per_zone_floor_area=power_density,
            schedule_name=schedule_name
        )
        self._lights.append(lights)
        return self

    def add_electric_equipment(self, zone_idx: int = 0, design_level: float = 500.0,
                               zone_name: Optional[str] = None, schedule_name: str = "EquipSchedule"):
        """
        Add electric equipment heat gain (pumps, AC terminals, etc.)

        Args:
            zone_idx: Zone index
            design_level: Equipment power W
            zone_name: Zone name
            schedule_name: Schedule name
        """
        if zone_name is None:
            zone_name = f"Zone_{zone_idx:02d}"

        equip = ElectricEquipment(
            name=f"{zone_name}_Equipment",
            zone_name=zone_name,
            design_level=design_level,
            schedule_name=schedule_name
        )
        self._electric_equipment.append(equip)
        return self

    def add_ventilation(self, zone_idx: int = 0, flow_rate_per_area: float = 0.0005,
                       zone_name: Optional[str] = None, schedule_name: str = "VentilationSchedule"):
        """
        Add ventilation (ZoneVentilation:DesignFlowRate)

        Args:
            zone_idx: Zone index
            flow_rate_per_area: Ventilation rate per unit area m3/s/m2
            zone_name: Zone name
            schedule_name: Schedule name
        """
        if zone_name is None:
            zone_name = f"Zone_{zone_idx:02d}"

        vent = ZoneVentilation(
            name=f"{zone_name}_Ventilation",
            zone_name=zone_name,
            flow_rate_per_zone_floor_area=flow_rate_per_area,
            schedule_name=schedule_name
        )
        self._ventilation.append(vent)
        return self

    def add_thermostat(self, zone_idx: int = 0,
                      heating_setpoint: float = 20.0,
                      cooling_setpoint: float = 25.0,
                      zone_name: Optional[str] = None):
        """Add thermostat"""
        if zone_name is None:
            zone_name = f"Zone_{zone_idx:02d}"

        thermo = Thermostat(
            name=f"{zone_name}_Thermostat",
            zone_name=zone_name,
            heating_setpoint=heating_setpoint,
            cooling_setpoint=cooling_setpoint
        )
        self._thermostats.append(thermo)
        return self

    def add_surface(self, surface: BuildingSurfaceDetailed):
        """Add building surface"""
        self._surfaces.append(surface)
        return self

    def _build_simulation_control(self) -> str:
        return """SimulationControl,
    Yes,                     !- Do Zone Sizing Calculation
    Yes,                     !- Do System Sizing Calculation
    No,                      !- Do Plant Sizing Calculation
    No,                      !- Run Simulation for Sizing Periods
    Yes,                     !- Run Simulation for Weather File Run Periods
    No,                      !- Do HVAC Sizing Simulation for Sizing Periods
    1;                       !- Maximum Number of HVAC Sizing Simulation Passes"""

    def _build_building(self) -> str:
        return f"""Building,
    {self.building_name},    !- Name
    0.0,                     !- North Axis {chr(123)}deg{chr(125)}
    Suburbs,                 !- Terrain
    0.04,                    !- Loads Convergence Tolerance Value {chr(123)}W{chr(125)}
    0.4,                     !- Temperature Convergence Tolerance Value {chr(123)}deltaC{chr(125)}
    FullInteriorAndExterior, !- Solar Distribution
    25,                      !- Maximum Number of Warmup Days
    6;                       !- Minimum Number of Warmup Days"""

    def _build_timestep(self) -> str:
        return """Timestep,
    6;                       !- Number of Timesteps per Hour"""

    def _build_convergence_limits(self) -> str:
        return """ConvergenceLimits,
    1,                       !- Minimum System Timestep {minutes}
    50,                      !- Maximum HVAC Iterations
    2,                       !- Minimum Plant Iterations
    8;                       !- Maximum Plant Iterations"""

    def _build_site_location(self) -> str:
        return """Site:Location,
    Shanghai,                !- Name
    31.2,                    !- Latitude {deg}
    121.5,                   !- Longitude {deg}
    8.0,                     !- Time Zone {hr}
    4.0;                     !- Elevation {m}"""

    def _build_run_period(self) -> str:
        return """RunPeriod,
    Annual,                  !- Name
    1,                       !- Begin Month
    1,                       !- Begin Day of Month
    ,                        !- Begin Year
    12,                      !- End Month
    31,                      !- End Day of Month
    ,                        !- End Year
    UseWeatherFile,          !- Day of Week for Start Day
    ,                        !- Apply Weekend Holiday Rule
    ,                        !- Use Weather File Holidays and Daylight Saving
    ,                        !- Rain Indicator
    ,                        !- Snow Indicator
    ,                        !- Daylight Saving Time Indicator
    ;                        !- Solar Model Indicators"""

    def _build_output_variables(self) -> str:
        return """Output:Variable,
    *,                       !- Key Value
    Zone Lights Electric Power,  !- Variable Name
    Hourly;                  !- Reporting Frequency

Output:Variable,
    *,                       !- Key Value
    Zone Ventilation Mass Flow Rate,  !- Variable Name
    Hourly;                  !- Reporting Frequency"""

    def build(self) -> str:
        """
        Generate complete IDF string

        All objects are inline, no external file dependencies.
        """
        lines = [
            "! ===========================================",
            f"! IDF Generated by IDFBuilder v{self.version}",
            f"! Building: {self.building_name}",
            f"! Floor Area: {self.building_floor_area} m2",
            f"! Zones: {self.num_zones}",
            "! ===========================================",
            "",
            "! =========== VERSION ==========",
            f"Version,{self.version};",
            "",
            "! =========== SIMULATION CONTROL ==========",
            self._build_simulation_control(),
            "",
            "! =========== BUILDING ==========",
            self._build_building(),
            "",
            "! =========== CONVERGENCE ==========",
            self._build_convergence_limits(),
            "",
            "! =========== SITE LOCATION ==========",
            self._build_site_location(),
            "",
        ]

        # Run period
        lines.extend([
            "! =========== RUN PERIOD ==========",
            self._build_run_period(),
            "",
        ])

        # Timestep
        lines.extend([
            "! =========== TIMESTEP ==========",
            self._build_timestep(),
            "",
        ])

        # Schedules (inline, no external files)
        if self._schedules_const:
            lines.extend([
                "! =========== SCHEDULE:CONSTANT ==========",
            ])
            for sched in self._schedules_const:
                lines.append(sched.to_idf())
            lines.append("")

        if self._schedules_compact:
            lines.extend([
                "! =========== SCHEDULE:COMPACT ==========",
            ])
            for sched in self._schedules_compact:
                lines.append(sched.to_idf())
            lines.append("")

        # Zones
        if self._zones:
            lines.extend([
                "! =========== ZONE ==========",
            ])
            for zone in self._zones:
                lines.append(zone.to_idf())
            lines.append("")

        # Lighting
        if self._lights:
            lines.extend([
                "! =========== LIGHTS ==========",
            ])
            for lights in self._lights:
                lines.append(lights.to_idf())
            lines.append("")

        # Electric equipment
        if self._electric_equipment:
            lines.extend([
                "! =========== ELECTRIC EQUIPMENT ==========",
            ])
            for equip in self._electric_equipment:
                lines.append(equip.to_idf())
            lines.append("")

        # Ventilation
        if self._ventilation:
            lines.extend([
                "! =========== ZONE VENTILATION ==========",
            ])
            for vent in self._ventilation:
                lines.append(vent.to_idf())
            lines.append("")

        # Thermostats
        if self._thermostats:
            lines.extend([
                "! =========== THERMOSTAT ==========",
            ])
            for thermo in self._thermostats:
                lines.append(thermo.to_idf())
            lines.append("")

        # Building surfaces
        if self._surfaces:
            lines.extend([
                "! =========== BUILDING SURFACES ==========",
            ])
            for surf in self._surfaces:
                lines.append(surf.to_idf())
            lines.append("")

        # Output variables
        lines.extend([
            "! =========== OUTPUT ==========",
            self._build_output_variables(),
            "",
        ])

        return "\n".join(lines)


def demo():
    """Demo IDFBuilder usage"""
    # Create simple PFAL model
    idf = IDFBuilder()
    idf.set_building("DemoPFAL", floor_area=100, num_zones=1)

    # Add lighting (350 W/m2)
    idf.add_lights(zone_idx=0, power_density=350)

    # Add equipment heat gain (pump 500W)
    idf.add_electric_equipment(zone_idx=0, design_level=500)

    # Add ventilation (air change 0.3)
    idf.add_ventilation(zone_idx=0, flow_rate_per_area=0.0005)

    # Add thermostat
    idf.add_thermostat(zone_idx=0, heating_setpoint=18, cooling_setpoint=25)

    # Generate IDF
    print(idf.build())


if __name__ == "__main__":
    demo()
