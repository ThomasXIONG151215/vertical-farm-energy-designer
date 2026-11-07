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


# ---------------------------------------------------------------------------
# O5: declarative policy registry.  Candidates (optimize.py / YAML) name a
# policy by string type + params dict; ``build_policy`` instantiates it.
# This module stays a pure leaf (stdlib-only imports, see test_40's AST
# gate), so the registry maps names to classes defined HERE only —
# third-party policies are attached programmatically via engine.run.
# ---------------------------------------------------------------------------
POLICY_REGISTRY: Dict[str, type] = {}


def register_policy(name: str):
    """Class decorator: register a BuildingPolicy implementation under *name*."""

    def _wrap(cls):
        if name in POLICY_REGISTRY:
            raise ValueError(
                f"policy type '{name}' is already registered to "
                f"{POLICY_REGISTRY[name].__name__}"
            )
        POLICY_REGISTRY[name] = cls
        return cls

    return _wrap


def build_policy(spec) -> "BuildingPolicy":
    """Instantiate a registered policy from a ``{"type": ..., "params": ...}`` spec.

    Fail-fast contract: an unknown type name, a missing ``"type"`` key or
    a non-mapping spec/params all raise ``ValueError`` naming the
    offending key/type, before any simulation runs.
    """
    if not isinstance(spec, Mapping):
        raise ValueError(
            f"policy spec must be a mapping {{'type': str, 'params': dict}}, "
            f"got {type(spec).__name__}"
        )
    ptype = spec.get("type")
    if not isinstance(ptype, str) or not ptype:
        raise ValueError(
            f"policy spec needs a string 'type' key, got {ptype!r} "
            f"(spec keys: {sorted(spec)})"
        )
    params = spec.get("params", {})
    if params is None:
        params = {}
    if not isinstance(params, Mapping):
        raise ValueError(
            f"policy spec 'params' for type '{ptype}' must be a mapping, "
            f"got {type(params).__name__}"
        )
    cls = POLICY_REGISTRY.get(ptype)
    if cls is None:
        raise ValueError(
            f"unknown policy type '{ptype}'; registered types: "
            f"{sorted(POLICY_REGISTRY)}"
        )
    return cls(**params)


@register_policy("setpoint_offset")
@dataclass
class SetpointOffsetPolicy:
    """Example offset policy: shift setpoints / LED / economizer by fixed deltas.

    Params (all default to no-op):
        t_offset_k: temperature setpoint offset (K).  Non-zero shifts
            both the cooling setpoint (``T_sp`` = config T_light/T_dark
            by ``obs.is_light`` + offset) and the heating setpoint
            (``T_heat_sp`` = config T_dark + offset).  Boundary: the
            optional config fields ``setpoints.T_heat`` / ``RH_dark``
            are not visible in ``PolicyContext``, so a non-zero offset
            re-bases the heat setpoint on ``T_dark`` and the humidity
            setpoint on ``RH`` — projects using those optional twins
            should apply their offsets programmatically.
        rh_offset_pp: humidity setpoint offset (percentage points) on
            ``ctx.RH``.
        led_dim: LED dimming fraction (0-1); ``None`` keeps the config
            LED path.
        econ_override: forced economizer state; ``None`` keeps legacy.

    Zero drift: with all params at their defaults every emitted field is
    ``None``, so the merged ``ZoneAction`` is all-``None`` and the run is
    bit-identical to ``policy=None``.
    """

    t_offset_k: float = 0.0
    rh_offset_pp: float = 0.0
    led_dim: Optional[float] = None
    econ_override: Optional[bool] = None

    def __post_init__(self) -> None:
        self._ctx: Optional[PolicyContext] = None

    def reset(self, ctx: PolicyContext) -> None:
        self._ctx = ctx

    def plan_daily(self, obs: Observation) -> Optional[DailyPlan]:
        return None

    def step(self, obs: Observation) -> ControlAction:
        if self._ctx is None:
            raise RuntimeError(
                "SetpointOffsetPolicy.step called before reset(ctx)"
            )
        za = ZoneAction()
        if self.t_offset_k:
            base_cool = self._ctx.T_light if obs.is_light else self._ctx.T_dark
            za.T_sp = base_cool + self.t_offset_k
            za.T_heat_sp = self._ctx.T_dark + self.t_offset_k
        if self.rh_offset_pp:
            za.RH_sp = self._ctx.RH + self.rh_offset_pp
        za.led_dim = self.led_dim
        za.econ_override = self.econ_override
        return ControlAction(zones={self._ctx.zone_id: za})
