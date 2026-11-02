"""
PV system model — single-diode model (SDM) at maximum-power-point.

Parametric re-implementation of the reused ``vfed/system.py:PVSystem`` (drop-in
for the design simulator): no numba/cuda dependency. All cell parameters are
configurable; the defaults resolve through the G3 module library
(``vfed/pvbes/modules.py``) to the Jinko 78 HL4-BDV reference module — the
same inline value set the pre-G3 ``PVSystem`` carried.

PV power (kW) per timestep is computed from the plane-of-array irradiance
(direct + diffuse) and cell temperature (NOCT model).

G3 (Wave 1): ``module`` selects a ``ModuleSpec`` from the library.  Fields
left at the ``_UNSET`` sentinel resolve from that spec in ``__post_init__``;
explicitly passed fields ALWAYS win (engine.py / sweep.py pass every legacy
field explicitly, so legacy YAML configs behave exactly as before), and the
default construction resolves to the legacy inline values bit-identically.

G4 (Wave 1): ``eta_rel_nodes`` is a piecewise-linear relative-efficiency
curve eta_rel(G) multiplying the MPP power, with an anchor node
(1000, 1.0) enforced by ``validate_eta_rel_nodes``.  ``None`` — every
current preset, pending anchor data — is the identity curve eta_rel == 1.0,
bit-identical to the pre-G4 formula.

G13 (Wave 1): ``degradation`` resolves from the module spec; the
exponential ``(1 - degradation) ** year`` semantics are unchanged.
"""

from dataclasses import dataclass
from typing import Any, Dict

import numpy as np

from .modules import ModuleSpec, resolve_module, validate_eta_rel_nodes

__all__ = ["PVSystem"]

# G3 sentinel: "field not passed -> inherit from the resolved ModuleSpec".
_UNSET: Any = object()

# PVSystem fields resolved from ModuleSpec when left at _UNSET (G3/G4/G13).
_SPEC_FIELDS = (
    "eta_pv",
    "area_to_power",
    "N_s",
    "I_sc_stc",
    "V_oc_stc",
    "I_mp_stc",
    "V_mp_stc",
    "gamma_pmp",
    "NOCT",
    "degradation",
    "eta_rel_nodes",
)

# Fields the SDM power chain cannot run without (G3 fail-fast): a module
# whose reference data is partial (STC points null in the anchor YAML) must
# not silently run on leftover / mixed values.
_SDM_REQUIRED = (
    "I_sc_stc",
    "V_oc_stc",
    "I_mp_stc",
    "V_mp_stc",
    "gamma_pmp",
    "NOCT",
    "eta_pv",
    "area_to_power",
    "degradation",
)


@dataclass
class PVSystem:
    # G3 (Wave 1): module-library key (vfed/pvbes/modules.py).  The default
    # names the legacy inline parameter set, so the default construction is
    # bit-identical to the pre-G3 PVSystem.  Fields left at _UNSET resolve
    # from the spec; explicitly passed fields always win.
    module: str = "jinko_jkm580n"
    # Informational only: module efficiency at STC (Jinko 78HL4-BDV ~0.23).
    # MPP power is computed from I_mp x V_mp via the SDM below, so eta_pv does
    # not enter the power calculation — kept as a config-contract field.
    eta_pv: Any = _UNSET  # resolved from the ModuleSpec when unset
    area_to_power: Any = _UNSET  # m^2 of module per kWp (from the ModuleSpec)
    N_s: Any = _UNSET  # cells in series; informational metadata
    I_sc_stc: Any = _UNSET  # A
    V_oc_stc: Any = _UNSET  # V
    I_mp_stc: Any = _UNSET  # A  (JKM580N-78HL4-BDV nameplate)
    V_mp_stc: Any = _UNSET  # V  (JKM580N-78HL4-BDV nameplate)
    #    P_module_at_STC = 45.85*12.66 = 580.5 W  (jinko spec)
    alpha_sc: float = 0.00045  # /K  (relative, ~0.045 %/K for Jinko 78HL4-BDV)
    beta_voc: float = -0.0025  # /K  (relative, ~-0.25 %/K for Jinko 78HL4-BDV)
    # P2-5: nameplate Pmax temperature coefficient (relative, /K).  This is
    #    the SINGLE coefficient driving the MPP power's temperature dependence;
    #    it replaces the legacy implicit stacking alpha_sc + beta_voc =
    #    -0.00205/K, which was ~32 % weaker than the TOPCon nameplate -0.30 %/K
    #    (layerD benchmark D5: hot-hour temperature loss undercounted
    #    ~1.3 %/yr).  alpha_sc / beta_voc stay as datasheet metadata only.
    #    Reproduce legacy output with gamma_pmp = -0.00205 (residual = the
    #    second-order cross term alpha_sc*beta_voc*dT^2, ~0.1 % at dT = 30 K).
    gamma_pmp: Any = _UNSET  # /K (from the ModuleSpec)
    NOCT: Any = _UNSET  # C (from the ModuleSpec; legacy default 45)
    T_stc: float = 25.0  # C
    eta_inv: float = 0.97  # inverter efficiency
    # P6-7: aggregate derate for soiling (~2-5 %), DC wiring (~1-2 %) and
    # module mismatch (~1-2 %).  Self-shading neglected (PFAL roof arrays are
    # laid flat).  Applied AFTER eta_inv: total derate = 0.97*0.95 = 0.9215.
    # P1-3: 0.9215 describes a near-new, regularly cleaned, unshaded array.
    # For absolute-energy benchmarking against PVWatts v5 defaults
    # (96 % inverter x 14 % system losses = 0.8256, i.e. -11.6 % vs ours;
    # layerD benchmark D6) override in YAML:
    #   pv: {eta_inv: 0.96, eta_system: 0.86}
    # The derate is a common multiplier across a sweep, so LCOE ranking is
    # unaffected; only absolute savings / payback shift.  See README
    # "Size PV + battery for your site".
    eta_system: float = 0.95
    # P0-1: market-anchored default (was 110, 4-8x below market).  China C&I
    # distributed PV 2025 (module + install) ~= 3-3.5 RMB/W ~= 3000-3500
    # RMB/kWp ~= 420-490 USD/kWp at 7.2; 500 = rounded mid-band, USD-anchored.
    C_pv: float = 500.0  # currency/kWp (legacy fallback when pv.capital absent)
    # G13 (Wave 1): per-year degradation, resolved from the ModuleSpec;
    # applied as (1 - degradation) ** year (semantics unchanged).
    degradation: Any = _UNSET
    # G4 (Wave 1): low-irradiance relative-efficiency curve eta_rel(G) as a
    # piecewise-linear node table validated by ``validate_eta_rel_nodes``
    # (STC anchor (1000, 1.0) enforced).  None — every current preset, the
    # validated anchor data is inaccessible — is the identity curve, so the
    # default bitstream is unchanged.
    eta_rel_nodes: Any = _UNSET

    def __post_init__(self):
        """G3: resolve _UNSET fields from the module spec, then fail fast
        when the resolved set cannot drive the SDM power chain."""
        spec = resolve_module(self.module)
        for fname in _SPEC_FIELDS:
            if getattr(self, fname) is _UNSET:
                setattr(self, fname, getattr(spec, fname))
        if self.eta_rel_nodes is not None:
            self.eta_rel_nodes = validate_eta_rel_nodes(self.eta_rel_nodes)
        missing = [f for f in _SDM_REQUIRED if getattr(self, f) is None]
        if missing:
            raise ValueError(
                f"PV module {self.module!r} cannot run the SDM power chain: "
                f"missing {', '.join(missing)} (reference data partial; see "
                f"reference/pvbes-validation/modules/)"
            )

    def spec(self) -> ModuleSpec:
        """The resolved module spec (G3; registry lookup by key)."""
        return resolve_module(self.module)

    def cell_temperature(self, G: np.ndarray, T_amb: np.ndarray) -> np.ndarray:
        """Nominal-Operating-Cell-Temperature model."""
        G = np.asarray(G, dtype=float)
        T_amb = np.asarray(T_amb, dtype=float)
        return T_amb + (self.NOCT - 20.0) * G / 800.0

    def _eta_rel(self, G: np.ndarray) -> np.ndarray:
        """G4: relative efficiency eta_rel(G) of the module at irradiance G.

        ``eta_rel_nodes is None`` is the identity curve (1.0 everywhere).
        Otherwise piecewise-linear interpolation over the node table with
        flat extrapolation outside the covered range (np.interp semantics).
        """
        G = np.asarray(G, dtype=float)
        if self.eta_rel_nodes is None:
            return np.ones_like(G)
        gs = np.asarray([g for g, _ in self.eta_rel_nodes], dtype=float)
        es = np.asarray([e for _, e in self.eta_rel_nodes], dtype=float)
        return np.interp(G, gs, es)

    def _sd_mpp(self, G: np.ndarray, T_cell: np.ndarray) -> np.ndarray:
        """Approximate SDM maximum-power-point power per module (W).

        P2-5: the temperature dependence of the MPP power is the single
        nameplate coefficient ``gamma_pmp`` (relative, /K) applied to the
        STC-normalized I_mp x V_mp product.  The legacy chain multiplied
        I_mp by (1 + alpha_sc dT) and V_oc by (1 + beta_voc dT), stacking to
        an implicit ~-0.205 %/K — ~32 % weaker than the TOPCon nameplate
        -0.30 %/K (layerD D5), because the real fill-factor loss with
        temperature was missing.  alpha_sc / beta_voc no longer drive the
        power chain; gamma_pmp = -0.00205 reproduces the legacy output to
        within the second-order cross term (~0.1 % at dT = 30 K).

        G4: the MPP power is multiplied by the relative-efficiency curve
        eta_rel(G).  The identity curve (eta_rel_nodes is None, every
        current preset pending anchor data) returns the product untouched —
        bit-identical to the pre-G4 formula.
        """
        G = np.asarray(G, dtype=float)
        T_cell = np.asarray(T_cell, dtype=float)
        I_mp = self.I_mp_stc * (G / 1000.0)
        I_mp = np.clip(I_mp, 0.0, None)
        k_v_stc = self.V_mp_stc / self.V_oc_stc
        k_v = k_v_stc * (1.0 + 0.03 * np.log(np.maximum(G, 1.0) / 1000.0))
        k_v = np.clip(k_v, 0.5, 0.95)
        V_mp = self.V_oc_stc * k_v
        # clip guards the deep-hot tail (gamma_pmp < 0, dT > -1/gamma_pmp)
        p_temp = np.clip(1.0 + self.gamma_pmp * (T_cell - self.T_stc), 0.0, None)
        p_mpp = I_mp * V_mp * p_temp
        if self.eta_rel_nodes is None:
            return p_mpp
        return p_mpp * self._eta_rel(G)

    def calculate_pv_output(
        self, weather: Dict[str, np.ndarray], A_pv: float, year: int = 0
    ) -> np.ndarray:
        """Hourly PV AC output (kW).

        weather keys: 'direct_radiation', 'diffuse_radiation', 'temperature_2m'.
        Plane-of-array irradiance = direct + diffuse (see weather_bridge.add_poa).
        """
        G = np.asarray(weather["direct_radiation"], dtype=float) + np.asarray(
            weather["diffuse_radiation"], dtype=float
        )
        T_amb = np.asarray(weather["temperature_2m"], dtype=float)
        G = np.clip(G, 0.0, None)
        T_cell = self.cell_temperature(G, T_amb)
        P_module_w = self._sd_mpp(G, T_cell)
        total_kwp = A_pv / self.area_to_power
        P_module_at_STC = self.V_mp_stc * self.I_mp_stc
        n_modules = total_kwp * 1000.0 / max(1e-9, P_module_at_STC)
        P_ac_w = P_module_w * n_modules * self.eta_inv * self.eta_system  # P6-7
        P_ac_w = np.where(G <= 0.0, 0.0, P_ac_w)
        P_ac_w = P_ac_w / 1000.0
        P_ac_w *= (1.0 - self.degradation) ** year
        return P_ac_w

    def calculate_costs(self, A_pv: float) -> Dict[str, float]:
        peak_power_kwp = A_pv / self.area_to_power
        capital = peak_power_kwp * self.C_pv
        return {
            "peak_power_kwp": peak_power_kwp,
            "capital_cost": capital,
        }
