"""PV module library (G3) + low-irradiance response hooks (G4) + per-module
degradation (G13).

Every registry entry below is transcribed from the validation-anchor database
``reference/pvbes-validation/modules/*.yaml`` (built 2026-11-01; provenance
rules in ``reference/pvbes-validation/readme.md``):

* datasheet-derived numbers are copied verbatim from the YAML files and the
  YAML ``status`` is recorded next to each entry (verified / partial);
* fields the YAML leaves ``null`` stay ``None`` here -- never fabricated;
* pure-arithmetic conversions permitted by the readme ("computed" values):
  ``degradation = degradation_annual_pct / 100``;
  ``area_to_power = area_m2 / (p_mp_w / 1000)`` where both are published,
  otherwise the STC identity ``area_to_power = 1 / eta_stc`` (a module with
  eta efficiency needs exactly 1/eta m^2 per kWp at 1000 W/m2);
* ``NOCT`` is not a datasheet point anywhere in the database: every entry
  keeps the legacy VFED modeling default 45 degC (the pre-G3 inline value)
  pending a per-module anchor;
* G4 low-irradiance relative-efficiency curves: NO module has a validated
  curve yet -- the PVWatts v5 polynomial lives behind an unreachable
  NREL/OSTI host (see ``reference/pvbes-validation/anchors/low_irradiance.yaml``,
  status ``inaccessible``), so every preset ships the identity curve
  ``eta_rel_nodes = None`` (eta_rel == 1.0 everywhere).  TODO(G4): swap in
  node tables per module once anchor data lands (a-Si glass qualitatively
  keeps a flatter low-G curve than c-Si per the Onyx FAQ, still
  unquantified);
* ``bifaciality`` is reserved for G5 (bifacial gain); all YAML entries leave
  it ``null``, so it defaults to ``None`` here;
* ``jinko_jkm580n`` is the legacy VFED baseline: its STC electrical points
  equal ``reference/pvbes-validation/modules/jinko_jkm580n.yaml`` (status
  ``partial`` -- research-sourced, datasheet origin unconfirmed), while
  eta_pv / area_to_power / degradation / NOCT are VFED modeling defaults
  (not datasheet values), kept bit-identical to the pre-G3 ``PVSystem``
  inline values for golden zero-drift.
"""

import math
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

__all__ = ["ModuleSpec", "MODULES", "resolve_module", "validate_eta_rel_nodes"]

# G4: piecewise-linear relative-efficiency table eta_rel(G).
# Sequence of (G [W/m2], eta_rel [-]) pairs; None = identity curve.
EtaRelNodes = Tuple[Tuple[float, float], ...]

# STC point set the PVSystem SDM power chain cannot run without (G3
# fail-fast contract; also the completeness rule for registry entries).
_SDM_POINT_FIELDS = (
    "I_sc_stc",
    "V_oc_stc",
    "I_mp_stc",
    "V_mp_stc",
    "gamma_pmp",
)


def validate_eta_rel_nodes(nodes) -> EtaRelNodes:
    """Normalize and validate a piecewise-linear eta_rel(G) node table (G4).

    Contract: ``nodes`` is a sequence of ``(G, eta_rel)`` pairs with finite
    entries, eta_rel > 0, G >= 0 strictly increasing, and an anchor node
    ``(1000.0, 1.0)`` so that eta_rel(1000) == 1 exactly (STC
    normalization).  Returns the nodes as a tuple of float pairs.
    """
    try:
        pairs = [(float(g), float(e)) for g, e in nodes]
    except (TypeError, ValueError):
        raise ValueError(
            "eta_rel_nodes entries must be (G, eta_rel) pairs of numbers"
        ) from None
    if not pairs:
        raise ValueError("eta_rel_nodes must not be empty")
    for g, e in pairs:
        if not (math.isfinite(g) and math.isfinite(e)):
            raise ValueError("eta_rel_nodes entries must be finite numbers")
        if g < 0.0:
            raise ValueError("eta_rel_nodes G values must be >= 0")
        if e <= 0.0:
            raise ValueError("eta_rel_nodes eta values must be > 0")
    gs = [g for g, _ in pairs]
    if any(b <= a for a, b in zip(gs, gs[1:])):
        raise ValueError("eta_rel_nodes G values must be strictly increasing")
    if not any(g == 1000.0 and e == 1.0 for g, e in pairs):
        raise ValueError("eta_rel_nodes needs the STC anchor node (1000.0, 1.0)")
    return tuple(pairs)


@dataclass(frozen=True)
class ModuleSpec:
    """STC parameter set for one library preset (G3 registry entry).

    ``None`` means "not published / not confirmed in the reference YAML";
    PVSystem refuses to run the SDM power chain on a spec whose
    ``sdm_complete`` is False (fail fast, no silent fallback to leftover
    values).  See the module docstring for per-entry provenance.
    """

    eta_pv: float  # STC efficiency (-); informational, matches 1/area_to_power
    area_to_power: float  # m^2 of module per kWp
    I_sc_stc: Optional[float] = None  # A
    V_oc_stc: Optional[float] = None  # V
    I_mp_stc: Optional[float] = None  # A
    V_mp_stc: Optional[float] = None  # V
    N_s: Optional[int] = None  # cells in series (informational metadata)
    gamma_pmp: Optional[float] = None  # Pmax temperature coefficient (/K, relative)
    NOCT: float = 45.0  # degC; legacy VFED modeling default, not a datasheet point
    degradation: Optional[float] = None  # per year (G13, (1-deg)**year semantics)
    eta_rel_nodes: Optional[EtaRelNodes] = None  # G4; None = identity curve
    bifaciality: Optional[float] = None  # reserved for G5 (bifacial gain)

    def __post_init__(self):
        for fname in ("eta_pv", "area_to_power", "NOCT"):
            v = getattr(self, fname)
            if not math.isfinite(v):
                raise ValueError(f"ModuleSpec.{fname} must be a finite number, got {v!r}")
        if self.eta_pv <= 0.0:
            raise ValueError(f"ModuleSpec.eta_pv must be > 0, got {self.eta_pv!r}")
        if self.area_to_power <= 0.0:
            raise ValueError(
                f"ModuleSpec.area_to_power must be > 0, got {self.area_to_power!r}"
            )
        for fname in _SDM_POINT_FIELDS + ("N_s", "degradation", "bifaciality"):
            v = getattr(self, fname)
            if v is not None and not math.isfinite(v):
                raise ValueError(f"ModuleSpec.{fname} must be finite or None, got {v!r}")
        if self.eta_rel_nodes is not None:
            object.__setattr__(
                self, "eta_rel_nodes", validate_eta_rel_nodes(self.eta_rel_nodes)
            )
        if self.sdm_complete and self.degradation is None:
            raise ValueError(
                "a ModuleSpec with a complete STC point set must set degradation"
            )

    @property
    def sdm_complete(self) -> bool:
        """True when every STC point the SDM power chain needs is present."""
        return all(getattr(self, f) is not None for f in _SDM_POINT_FIELDS)


MODULES: Dict[str, ModuleSpec] = {
    # jinko_jkm580n -- legacy VFED baseline (pre-G3 PVSystem inline set).
    # STC points == modules/jinko_jkm580n.yaml (status: partial -- the
    #   Jinko datasheet PDF is unreachable from the anchor network, values
    #   are research-sourced); eta_pv / area_to_power / degradation / NOCT
    #   are VFED modeling defaults (null in the YAML), bit-identical to the
    #   pre-G3 inline values (golden zero-drift contract).
    # G4: identity curve (no validated anchor).
    "jinko_jkm580n": ModuleSpec(
        eta_pv=0.233,
        area_to_power=4.3,
        I_sc_stc=13.98,
        V_oc_stc=57.34,
        I_mp_stc=12.66,
        V_mp_stc=45.85,
        N_s=156,
        gamma_pmp=-0.0030,
        NOCT=45.0,
        degradation=0.004,
    ),
    # huasun_himalaya -- HJT anchor.  YAML status: verified
    #   (pv-magazine 2025-11-28, 770 W / 2000 V HJT page).  v_mp / i_mp not
    #   published -> None -> SDM-incomplete on purpose.  area_to_power
    #   computed: 3.106 m2 / 0.770 kWp.  degradation = 0.3 %/yr (annual
    #   warranty limit; the separate 1.0 % first-year loss is not
    #   representable in the single-coefficient (1-deg)**year model).
    #   NOCT 45 = VFED modeling default.  G4: identity curve (TODO anchor).
    "huasun_himalaya": ModuleSpec(
        eta_pv=0.248,
        area_to_power=3.106 / 0.770,
        I_sc_stc=19.33,
        V_oc_stc=50.46,
        I_mp_stc=None,
        V_mp_stc=None,
        N_s=132,
        gamma_pmp=-0.0024,
        NOCT=45.0,
        degradation=0.3 / 100.0,
    ),
    # longi_himo_x10 -- BC anchor.  YAML status: verified (pv-magazine
    #   2026-03-10, fire-resistant rooftop page).  STC electrical points
    #   (v_oc / i_sc / v_mp / i_mp) and the degradation curve not published
    #   -> None -> SDM-incomplete.  n_s = 108 (half-cell count per YAML
    #   note).  eta 0.248 (peak); area_to_power computed 1/eta.
    #   NOCT 45 = VFED modeling default.  G4: identity curve (TODO anchor).
    "longi_himo_x10": ModuleSpec(
        eta_pv=0.248,
        area_to_power=1.0 / 0.248,
        N_s=108,
        gamma_pmp=-0.0026,
        NOCT=45.0,
        degradation=None,
    ),
    # microquanta_bipv -- perovskite-silicon tandem BIPV anchor.  YAML
    #   status: verified (pv-magazine 2026-06-24).  Make-to-order module:
    #   all STC electrical points, n_s and the temperature coefficient are
    #   not published -> None -> SDM-incomplete.  eta 0.26 (26% class);
    #   area_to_power computed 1/eta.  degradation = 0.7 %/yr (annual
    #   warranty limit; the separate 2.0 % first-year loss is not
    #   representable in the single-coefficient model).
    #   NOCT 45 = VFED modeling default.  G4: identity curve (TODO anchor).
    "microquanta_bipv": ModuleSpec(
        eta_pv=0.26,
        area_to_power=1.0 / 0.26,
        NOCT=45.0,
        degradation=0.7 / 100.0,
    ),
    # onyx_asi_glass -- amorphous-silicon BIPV glass anchor.  YAML status:
    #   verified (onyxsolar.com compare-pv-glass-options).  Only a nominal
    #   power density exists: eta computed 57.6 Wp/m2 / 1000 W/m2 = 0.0576;
    #   area_to_power computed 1/eta.  All STC points -> None ->
    #   SDM-incomplete.  a-Si has a QUALITATIVE diffuse-light advantage
    #   (anchors/low_irradiance.yaml, verified) but no quantitative curve:
    #   identity eta_rel TODO until an anchor lands.
    #   NOCT 45 = VFED modeling default.
    "onyx_asi_glass": ModuleSpec(
        eta_pv=57.6 / 1000.0,
        area_to_power=1.0 / (57.6 / 1000.0),
        NOCT=45.0,
        degradation=None,
    ),
}


def resolve_module(name: str) -> ModuleSpec:
    """Return the ``ModuleSpec`` registered under ``name`` (G3).

    Raises ValueError for unknown names (message is pure ASCII).
    """
    try:
        return MODULES[name]
    except KeyError:
        raise ValueError(
            f"unknown PV module {name!r}; known modules: {', '.join(sorted(MODULES))}"
        ) from None
