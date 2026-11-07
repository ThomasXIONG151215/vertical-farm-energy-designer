"""Building-loop control protocol types (C1).

This module is a pure leaf: it imports only from the standard library
(no ``vfed`` imports, no third-party imports), so any layer may import
it without creating cycles.  The hourly loop in ``engine_loop.py``
consumes these types through the tick hook; a ``BuildingPolicy``
implementation produces actions that override the config defaults at
the consumption sites.

Merge semantics (E2 ruling): for every ``ZoneAction`` field the value
comes from the step action when set, else from the daily plan entry for
the current hour, else ``None``.  A field that is ``None`` everywhere
leaves the legacy config-driven path untouched, so an all-``None``
policy is bit-identical to ``policy=None`` (zero drift).
"""

import dataclasses
from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional, Protocol


@dataclass
class ZoneAction:
    """Per-zone overrides for one control tick.

    Every field defaults to ``None``, which means "keep the legacy
    config-driven value" at the consumption site.  Fields that carry
    device-level commands (``led_dim``, ``hvac_m``, ``deh_m``,
    ``erv_flow_m3h``, ``co2_sp``) are carried by C1 and consumed once
    the device parameter hooks land (C2b).
    """

    led_on: Optional[bool] = None
    led_dim: Optional[float] = None
    T_sp: Optional[float] = None
    T_heat_sp: Optional[float] = None
    RH_sp: Optional[float] = None
    hvac_m: Optional[float] = None
    deh_m: Optional[float] = None
    econ_override: Optional[bool] = None
    erv_flow_m3h: Optional[float] = None
    co2_sp: Optional[float] = None


@dataclass
class ControlAction:
    """Actions for one control tick, keyed by zone id."""

    zones: Mapping[str, ZoneAction] = field(default_factory=dict)


@dataclass
class Observation:
    """Zone and crop state handed to the policy at a control tick.

    ``pv_w`` is always ``None`` in v1 because the building loop runs
    before the PVBES dispatch layer; the field is pinned so later
    versions can fill it without breaking the protocol.
    """

    t_s: int
    hour: int
    day_of_year: int
    month: int
    price: Optional[float]
    is_light: bool
    T_z: float
    RH_z: float
    W_z: float
    X_d: float
    cycle_h: float
    c_z: Optional[float]
    pv_w: Optional[float]


@dataclass
class PolicyContext:
    """Immutable simulation facts a policy may rely on."""

    dt: float
    control_period_s: float
    zone_id: str = "main"
    light_start_hour: int = 6
    photoperiod_hours: float = 16.0
    T_light: float = 22.0
    T_dark: float = 18.0
    RH: float = 65.0
    hourly_prices: list = field(default_factory=list)


DailyPlan = Dict[int, ZoneAction]


class BuildingPolicy(Protocol):
    """The building-loop control seat (E1 ruling).

    ``reset`` is called once before the first hour.  ``plan_daily`` is
    called at each day boundary before the first step of that day and
    may return ``None`` when no daily plan applies.  ``step`` is called
    at every control tick and must return a ``ControlAction``.
    """

    def reset(self, ctx: PolicyContext) -> None:
        ...

    def plan_daily(self, obs: Observation) -> Optional[DailyPlan]:
        ...

    def step(self, obs: Observation) -> ControlAction:
        ...


def merge(action: Optional[ZoneAction], daily: Optional[DailyPlan], hour: int) -> ZoneAction:
    """Merge a step action over the daily-plan entry for ``hour``.

    Per-field priority: the step action wins when its field is set,
    then the daily plan entry for ``hour``, then ``None``.  Both inputs
    may be ``None`` (a policy without a daily plan, or a tick for a
    zone the action did not mention), which yields an all-``None``
    ``ZoneAction`` — exactly the legacy path.
    """

    daily_action = daily.get(hour) if daily is not None else None
    merged = ZoneAction()
    for f in dataclasses.fields(ZoneAction):
        value = getattr(action, f.name) if action is not None else None
        if value is None and daily_action is not None:
            value = getattr(daily_action, f.name)
        setattr(merged, f.name, value)
    return merged
