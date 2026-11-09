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
from typing import Dict, FrozenSet, Mapping, Optional, Protocol, Tuple


@dataclass
class ZoneAction:
    """Per-zone overrides for one control tick.

    Every field defaults to ``None``, which means "keep the legacy
    config-driven value" at the consumption site.  Fields that carry
    device-level commands (``led_dim``, ``hvac_m``, ``deh_m``,
    ``econ_flow_m3h``, ``erv_flow_m3h``, ``co2_sp``) are carried by
    C1 and consumed once the device parameter hooks land (C2b).
    """

    led_on: Optional[bool] = None
    led_dim: Optional[float] = None
    T_sp: Optional[float] = None
    T_heat_sp: Optional[float] = None
    RH_sp: Optional[float] = None
    hvac_m: Optional[float] = None
    deh_m: Optional[float] = None
    econ_override: Optional[bool] = None
    econ_flow_m3h: Optional[float] = None
    erv_flow_m3h: Optional[float] = None
    co2_sp: Optional[float] = None


@dataclass
class ControlAction:
    """Actions for one control tick, keyed by zone id."""

    zones: Mapping[str, ZoneAction] = field(default_factory=dict)


@dataclass
class Observation:
    """Zone and crop state handed to the policy at a control tick.

    ``pv_w`` carries the hourly PV AC output (kW; power series keep
    the kW convention despite the ``_w`` name, matching the dispatch
    protocol) when a policy is attached and PV is configured, else
    ``None``.  v1 wires the single-zone path only; multi-zone runs
    keep ``pv_w`` at ``None``.
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

    Wave 6 (owns authority): every policy must declare ``owns``, the
    frozenset of ``BUILDING_CONTROL_NAMES`` fields it takes over.  An
    owned field MUST carry a value every tick (step or plan_daily); a
    field outside ``owns`` MUST stay ``None``.  A pure-observation
    policy declares ``frozenset()``.
    """

    owns: frozenset

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
# Wave 6 (owns authority): the control-field registry.  Each ZoneAction
# field a policy may claim is described once here.  ``voids_params`` are
# FLATTENED config-parameter names (the keys of project.PARAM_PATH_MAP /
# PARAM_TOPLEVEL_MAP) whose config authority lapses at runtime while the
# field is owned by a policy: the loop then drives that quantity and the
# config key only feeds sizing/auto-size paths.  control.py stays a pure
# leaf, so it cannot import project.py — the voids_params <-> map-key
# sync is enforced by tests (test_47).
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ControlField:
    """One claimable control field and the config keys it hollows out."""

    name: str
    tier: int  # 0 = building loop, 1 = PVBES dispatch
    config_counterpart: str
    voids_params: Tuple[str, ...] = ()


CONTROL_FIELDS: Dict[str, ControlField] = {
    "led_on": ControlField(
        "led_on",
        0,
        "led.light_start_hour/led.photoperiod_hours (clock)",
        ("light_start_hour", "photoperiod_hours"),
    ),
    "led_dim": ControlField("led_dim", 0, "led PPFD at full-on", ()),
    "T_sp": ControlField("T_sp", 0, "setpoints.T_light/setpoints.T_dark", ("T_light", "T_dark")),
    "T_heat_sp": ControlField("T_heat_sp", 0, "setpoints.T_heat", ("T_heat",)),
    "RH_sp": ControlField("RH_sp", 0, "setpoints.RH/setpoints.RH_dark", ("RH", "RH_dark")),
    "hvac_m": ControlField("hvac_m", 0, "HVAC modulation (auto)", ()),
    "deh_m": ControlField("deh_m", 0, "DEH modulation (auto)", ()),
    "econ_override": ControlField("econ_override", 0, "economizer auto state", ()),
    "econ_flow_m3h": ControlField("econ_flow_m3h", 0, "economizer auto flow", ()),
    "erv_flow_m3h": ControlField("erv_flow_m3h", 0, "ERV ventilation auto flow", ()),
    "co2_sp": ControlField("co2_sp", 0, "setpoints.co2_ppm", ("co2_ppm",)),
    "charge_w": ControlField("charge_w", 1, "PVBES greedy dispatch (battery charge)", ()),
    "discharge_w": ControlField("discharge_w", 1, "PVBES greedy dispatch (battery discharge)", ()),
}

#: Fields a BuildingPolicy may claim in ``owns`` (the dispatch-tier
#: charge_w/discharge_w belong to DispatchPolicy, not BuildingPolicy).
BUILDING_CONTROL_NAMES: FrozenSet[str] = frozenset(
    f for f, cf in CONTROL_FIELDS.items() if cf.tier == 0
)


def validate_owns(owns, policy_desc: str) -> frozenset:
    """Check and normalize a policy's ``owns`` declaration.

    ``None`` means the policy never declared ``owns`` — that is an error
    (a pure-observation policy must declare ``frozenset()``).  Anything
    that is not a frozenset/set, or names a field outside
    ``BUILDING_CONTROL_NAMES``, raises ``ValueError`` naming the
    offender.  Returns the declaration as a frozenset.
    """
    if owns is None:
        raise ValueError(
            f"{policy_desc} must declare 'owns' (a frozenset of control-field "
            f"names); a pure-observation policy declares frozenset()"
        )
    if isinstance(owns, (str, bytes)) or not isinstance(owns, (frozenset, set)):
        raise ValueError(
            f"{policy_desc} owns must be a frozenset of control-field names, "
            f"got {type(owns).__name__}"
        )
    unknown = sorted(set(owns) - BUILDING_CONTROL_NAMES)
    if unknown:
        raise ValueError(
            f"{policy_desc} owns declares unknown control field(s) {unknown}; "
            f"known building fields: {sorted(BUILDING_CONTROL_NAMES)}"
        )
    return frozenset(owns)


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

    Fail-fast contract: an unknown spec key, an unknown type name, a
    missing ``"type"`` key or a non-mapping spec/params all raise
    ``ValueError`` naming the offending key/type, before any simulation
    runs.  Accepted spec keys: ``"type"``, ``"params"`` and the optimize
    escape hatch ``"schedule_echo"`` (see optimize._check_authority_conflicts).
    """
    if not isinstance(spec, Mapping):
        raise ValueError(
            f"policy spec must be a mapping {{'type': str, 'params': dict}}, "
            f"got {type(spec).__name__}"
        )
    allowed_keys = {"type", "params", "schedule_echo"}
    unknown_keys = sorted(set(spec) - allowed_keys)
    if unknown_keys:
        raise ValueError(
            f"policy spec has unknown key(s) {unknown_keys}; "
            f"allowed keys: {sorted(allowed_keys)}"
        )
    ptype = spec.get("type")
    if not isinstance(ptype, str) or not ptype:
        raise ValueError(
            f"policy spec needs a string 'type' key, got {ptype!r} " f"(spec keys: {sorted(spec)})"
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
            f"unknown policy type '{ptype}'; registered types: " f"{sorted(POLICY_REGISTRY)}"
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

    Wave 6 (owns authority): ``owns`` is computed in ``__post_init__``
    from the effective params, so the declaration can never disagree
    with what ``step`` actually sets.  All-default params give
    ``owns == frozenset()`` (pure observer, zero drift).
    """

    t_offset_k: float = 0.0
    rh_offset_pp: float = 0.0
    led_dim: Optional[float] = None
    econ_override: Optional[bool] = None

    def __post_init__(self) -> None:
        self._ctx: Optional[PolicyContext] = None
        claimed = set()
        if self.t_offset_k:
            claimed.update(("T_sp", "T_heat_sp"))
        if self.rh_offset_pp:
            claimed.add("RH_sp")
        if self.led_dim is not None:
            claimed.add("led_dim")
        if self.econ_override is not None:
            claimed.add("econ_override")
        self.owns: frozenset = frozenset(claimed)

    def reset(self, ctx: PolicyContext) -> None:
        self._ctx = ctx

    def plan_daily(self, obs: Observation) -> Optional[DailyPlan]:
        return None

    def step(self, obs: Observation) -> ControlAction:
        if self._ctx is None:
            raise RuntimeError("SetpointOffsetPolicy.step called before reset(ctx)")
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
