"""
Building envelope heat & mass transfer model.

Replaces the sign-based ``Q_infil_base`` in the vendored ``digital_twin`` ODE with
physically consistent mass-flow infiltration (sensible + latent heat) plus an
optional envelope vapour permeance term (latent only). Heat transfer through the
envelope is UA conduction; solar gain is ``eta_solar * A_window * GHI``.

R28 (additive, default off): an optional 2R2C wall thermal-mass network
(``wall_rc_nodes=2``) adds a lumped mass node T_m coupled to the air node
through ``g_im`` (W/K) and to outdoors through ``g_em`` (W/K), storing heat in
``C_mass`` (Wh/K).  With ``wall_rc_nodes=0`` (the default) the legacy
single-node ``Q_wall = U_wall_A * (T_ext - T_z)`` is returned bit-for-bit.
The air-node integrator (``vfed/physics/ode.py``) is untouched: T_m is stepped
explicitly by the envelope itself (``step_mass``), using the substep-start
T_ext/T_z (staggered Euler, same O(dt) order as the air node).

R28 step 3 (additive, default off): ``wall_rc_nodes=3`` extends the network to
2R3C -- a surface node T_s (capacity ``C_surface`` Wh/K) sits between the mass
node and the air node, coupled by ``g_sa`` (surface->air film, W/K) and
``g_sm`` (surface->mass conduction, W/K).  ``step_mass`` additionally accepts
``Q_source_w`` (W): the solar-split source term (``solar_mass_fraction`` of
the window gain), deposited on the surface node for 2R3C and on the mass node
for 2R2C -- mirroring the LBNL ``SolarRadiationExchange`` rule that transmits
solar to the construction surfaces, never directly to the air.

R28 step 6 (additive, default off): ``wall_fd_nodes >= 10`` replaces the
lumped RC wall by a 1-D finite-difference continuum through the
``wall_layers`` stack (cell-centered control volumes; nodes distributed per
layer proportional to sqrt(R_i·C_i), min 1 per layer -- the same discretise-
per-material idea as LBNL ``MultiLayer.mo`` with ``nStaRef``).  The FD system
is advanced with a FULLY IMPLICIT (backward-Euler) solve; the system matrix
is constant for a fixed ``dt``, so the inverse is cached and each substep
costs one small dense matvec.  Implicit solves are unconditionally stable for
any ``dt``.  Boundary channels:

  * exterior: film ``h_ext_wm2 * A`` to the sol-air temperature
    ``T_os = T_ext + wall_solar_abs * I_ext / h_ext_wm2`` (``wall_solar_abs=0``
    disables the solar term; the sky long-wave term is not modelled);
  * interior: convective film ``g_c = h_int_c_wm2 * A`` to the zone air
    (returns through ``Q_wall``), plus the ``g_sm`` coupling to the internal
    mass node T_m (``C_mass`` Wh/K, no outdoor path);
  * source: ``Q_source_w`` (solar split / radiant internal gains) deposited
    on the inner-surface control volume.

Because every boundary film is evaluated at the NEW (implicit) state and the
air balance consumes the mirrored film product at the same states, the wall +
air energy balance closes with NO staggering residual (unlike the explicit
RC networks whose g_sa leg carries an O(dt) stagger).
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from .psychrometrics import latent_heat_vaporization

__all__ = ["Envelope"]


@dataclass
class _WallRC:
    """2R2C / 2R3C wall thermal-mass network state (R28, R28 step 3).

    2R2C topology (g in W/K, C in Wh/K)::

                g_em                    g_im
      T_ext --/\\/\\/-- T_m --/\\/\\/-- T_z     (+ infiltration direct to T_z)
                   |                 |
                 C_mass             C_z

    The mass node carries NO source terms (unless ``step_mass`` receives the
    solar-split ``Q_source_w``): it charges/discharges through the g_em
    (outdoor) and g_im (air) conductances -- the daytime store / night-time
    release "regenerative buffer" is the g_im channel.

    2R3C topology (``wall_rc_nodes=3``; the optional fields below are set)::

                g_em          g_sm            g_sa
      T_ext --/\\/\\/-- T_m --/\\/\\/-- T_s --/\\/\\/-- T_z
                   |               |
                 C_mass          C_surface

    The surface node T_s is the solar landing pad (LBNL SolarRadiationExchange:
    transmitted solar is absorbed at the construction surfaces, the air only
    through the inner film g_sa); the air-coupling discharge becomes
    ``g_sa * (T_s - T_z)`` and g_im is unused.
    """

    C_mass: float  # Wh/K lumped mass-layer capacity
    g_im: float  # W/K mass node -> air node (2R2C); unused in 2R3C
    g_em: float  # W/K mass node -> outdoors (outer half-layer + exterior film); 0 = pure internal mass
    T_m: float = 20.0  # degC mass-node temperature state (engine resets to T_z init)
    # -- R28 step 3: 2R3C surface node (None = 2R2C, no surface node) --
    C_surface: Optional[float] = None  # Wh/K surface-node capacity
    g_sa: Optional[float] = None  # W/K surface node -> air node (inner film)
    g_sm: Optional[float] = None  # W/K surface node -> mass node (inner half-layer)
    T_s: Optional[float] = None  # degC surface-node temperature state

    @property
    def is_rc3(self) -> bool:
        """True when the 2R3C surface node is present."""
        return self.T_s is not None


def distribute_nodes_fd(layers: List[Tuple[float, float, float, float]], n_total: int) -> List[int]:
    """Distribute ``n_total`` FD nodes across wall layers.

    Layer shares follow sqrt(R_i·C_i) (geometric mean of the layer's thermal
    resistance ``d_i/k_i`` and areal capacity ``rho_i·c_i·d_i`` -- the
    diffusion-penetration scaling: thick resistive layers AND heavy layers
    both earn resolution).  Largest-remainder rounding keeps the total exact
    and every layer keeps >= 1 node.
    """
    weights = [
        ((d / k) * (rho * c * d)) ** 0.5 for (d, k, rho, c) in layers
    ]
    total = sum(weights)
    raw = [n_total * w / total for w in weights]
    counts = [max(1, int(r)) for r in raw]
    # Largest-remainder top-up / trim while keeping every layer >= 1.
    while sum(counts) > n_total:
        idx = max(range(len(counts)), key=lambda i: counts[i] - raw[i])
        if counts[idx] <= 1:
            raise ValueError(
                "wall_fd_nodes too small for the wall_layers stack: cannot "
                f"fit {n_total} nodes with >=1 node per layer "
                f"({len(layers)} layers)."
            )
        counts[idx] -= 1
    order = sorted(range(len(counts)), key=lambda i: raw[i] - int(raw[i]), reverse=True)
    i = 0
    while sum(counts) < n_total:
        counts[order[i % len(order)]] += 1
        i += 1
    return counts


@dataclass
class _WallFD:
    """1-D finite-difference wall continuum + internal mass node (R28 step 6).

    Cell-centered control volumes through the layer stack (index 0 = exterior
    cell, index n-1 = interior cell).  Units: C in J/K, conductances in W/K,
    temperatures in degC.  The implicit system matrix (fixed per ``dt``) is
    cached inverted in ``a_inv`` -- one dense matvec per substep.

    States: ``T`` (len n wall cells) and ``T_m`` (internal mass node, no
    outdoor path, coupled to the interior cell through ``g_sm``).
    """

    C: np.ndarray  # J/K per wall cell
    G_cond: np.ndarray  # W/K conductance between adjacent cells (len n-1)
    G_ext: float  # W/K exterior film (h_ext_wm2 * A)
    g_c: float  # W/K interior convective film -> zone air
    g_sm: float  # W/K interior cell -> internal mass node
    C_m: float  # J/K internal mass node
    T: np.ndarray = field(default_factory=lambda: np.zeros(0))
    T_m: float = 20.0
    T_sol_air: float = 20.0  # last sol-air boundary drive (diagnostic)
    a_inv: Dict[float, np.ndarray] = field(default_factory=dict)

    @classmethod
    def build(
        cls,
        layers: List[Tuple[float, float, float, float]],
        n_nodes: int,
        area_m2: float,
        h_ext_wm2: float,
        h_int_c_wm2: float,
        g_sm: float,
        C_mass_whk: float,
    ) -> "_WallFD":
        """Assemble the cell-centered FD grid from physical layer data.

        Cell resistances are ``d_i / (k_i * n_i * A)`` (K/W) and cell
        capacities ``rho_i * c_i * d_i / n_i * A`` (J/K); adjacent cells
        couple through the harmonic half-cell resistance
        ``r_a/2 + r_b/2`` (exact for the piecewise-constant-k stack).
        """
        counts = distribute_nodes_fd(layers, n_nodes)
        caps: List[float] = []
        res: List[float] = []
        for (d, k, rho, c), n_i in zip(layers, counts):
            caps.extend([rho * c * (d / n_i) * area_m2] * n_i)
            res.extend([d / (k * n_i * area_m2)] * n_i)
        C = np.asarray(caps, dtype=float)
        G_cond = np.asarray(
            [1.0 / (0.5 * res[i] + 0.5 * res[i + 1]) for i in range(len(res) - 1)],
            dtype=float,
        )
        # Cell-centered films see the BOUNDARY-CELL CENTRES, so the film
        # resistance is put in series with the outer half-cell: the DC
        # ladder then closes EXACTLY onto the continuum
        # R_tot = 1/(h_o*A) + R_layers/A + 1/(h_c*A) (the pure-centre
        # coupling would omit r_0/2 + r_n-1/2 and bias the steady flux by
        # ~0.7% on the 140 constructions).
        g_ext = 1.0 / (1.0 / (h_ext_wm2 * area_m2) + 0.5 * res[0])
        g_c = 1.0 / (1.0 / (h_int_c_wm2 * area_m2) + 0.5 * res[-1])
        return cls(
            C=C,
            G_cond=G_cond,
            G_ext=g_ext,
            g_c=g_c,
            g_sm=float(g_sm),
            C_m=C_mass_whk * 3600.0,  # Wh/K -> J/K
            T=np.full(len(C), 20.0),
            T_m=20.0,
        )

    @property
    def n(self) -> int:
        return len(self.C)

    def reset(self, T_init: float) -> None:
        self.T = np.full(self.n, float(T_init))
        self.T_m = float(T_init)
        self.T_sol_air = float(T_init)

    def _system_inverse(self, dt: float) -> np.ndarray:
        """Constant implicit matrix A(dt) inverted once per distinct dt.

        A is symmetric negative definite (positive diagonal, negative
        off-diagonals, strictly diagonally dominant via the C/dt terms), so
        the cached inverse is numerically safe and every solve is one
        matvec -- O(n^2) with tiny n instead of an O(n^3) factorisation
        per substep.
        """
        inv = self.a_inv.get(dt)
        if inv is None:
            n = self.n
            a = np.zeros((n + 1, n + 1), dtype=float)
            for i in range(n):
                # diagonal = C/dt + sum of ALL conductances touching cell i
                g_sum = 0.0
                if i == 0:
                    g_sum += self.G_ext
                else:
                    a[i, i - 1] = -self.G_cond[i - 1]
                    g_sum += self.G_cond[i - 1]
                if i < n - 1:
                    a[i, i + 1] = -self.G_cond[i]
                    g_sum += self.G_cond[i]
                else:
                    # interior cell: convective film to air + mass coupling
                    g_sum += self.g_c + self.g_sm
                    a[i, n] = -self.g_sm
                a[i, i] = self.C[i] / dt + g_sum
            a[n, n] = self.C_m / dt + self.g_sm
            a[n, n - 1] = -self.g_sm
            inv = self.a_inv[dt] = np.linalg.inv(a)
        return inv

    def step(
        self,
        T_ext: float,
        T_z: float,
        dt: float,
        Q_source_w: float = 0.0,
        I_ext_wm2: float = 0.0,
        solar_abs: float = 0.0,
        h_ext_wm2: float = 0.0,
    ) -> float:
        """Advance one fully implicit step; return the interior-cell temp.

        ``solar_abs > 0`` activates the sol-air exterior boundary
        ``T_os = T_ext + solar_abs * I_ext_wm2 / h_ext_wm2``.
        """
        t_os = T_ext
        if solar_abs > 0.0:
            t_os = T_ext + solar_abs * float(I_ext_wm2) / h_ext_wm2
        self.T_sol_air = float(t_os)
        inv = self._system_inverse(dt)
        n = self.n
        b = (self.C / dt) * self.T
        b[0] += self.G_ext * t_os
        # g_sm*T_m and g_sm*T_inner are matrix off-diagonal terms (A), NOT
        # RHS entries -- only the BOUNDARY drives (T_os, T_z) and sources go
        # on the right-hand side.
        b[n - 1] += self.g_c * T_z + Q_source_w
        b = np.append(b, (self.C_m / dt) * self.T_m)
        x = inv @ b
        t_in = float(x[n - 1])
        t_out = float(x[0])
        t_m = float(x[n])
        for name, v in (("exterior", t_out), ("interior", t_in), ("mass", t_m)):
            if not (-100.0 <= v <= 100.0):
                raise RuntimeError(
                    f"FD wall {name} node diverged to {v:.1f} C -- check "
                    f"wall_fd config (n={n}, g_ext={self.G_ext:.1f} W/K, "
                    f"g_c={self.g_c:.1f} W/K, g_sm={self.g_sm:.1f} W/K, "
                    f"C_m={self.C_m / 3600.0:.0f} Wh/K, dt={dt:.0f} s, "
                    f"T_ext={T_ext:.1f} C, T_z={T_z:.1f} C)"
                )
        self.T = x[:n].copy()
        self.T_m = t_m
        return t_in


class Envelope:
    """Envelope thermal + hygric model.

    Parameters
    ----------
    U_wall_A : float
        Overall envelope conductance UA (W/K).
    A_window : float
        Effective window / glazed area (m^2).
    eta_solar : float
        Solar heat gain coefficient (fraction of incident irradiance admitted as heat).
    ach : float
        Air changes per hour from infiltration / leakage (1/h). Drives the mass-flow
        sensible + latent exchange with outdoor air.
    permeance : float
        Envelope vapour permeance coefficient (kg/(s·(kg/kg))) — passive moisture
        migration through the envelope driven by the indoor/outdoor AH gradient.
        Set to 0 to disable.
    rho_air : float
        Air density (kg/m^3).
    cp_air : float
        Specific heat of air (J/(kg·K)).
    wall_rc_nodes : int
        R28 additive switch: 0 (default) = legacy single-node envelope
        (``Q_wall = U_wall_A*(T_ext-T_z)``, bit-for-bit unchanged); 2 = enable
        the 2R2C wall thermal-mass network (T_z air node + T_m mass node).
    C_mass : float
        Lumped mass-node heat capacity (Wh/K); required > 0 when
        ``wall_rc_nodes=2``.  ``Σ A_i·d_i·ρ_i·c_i / 3600`` over the mass layers
        (includes pure internal mass with no outdoor path, e.g. a floor slab
        on insulation).
    g_im : float
        Mass node -> air node conductance (W/K) when ``wall_rc_nodes=2``;
        required > 0.  Inner surface film (R_si ≈ 0.125 m²K/W) + inner half
        of the mass layer, areas in parallel: ``Σ A_i / (R_si + d_i/(2 k_i))``.
    g_em : float
        Mass node -> outdoor conductance (W/K) when ``wall_rc_nodes=2``;
        required >= 0 (0 for pure internal mass).  Outer half of the mass
        layer + remaining layers + exterior film: ``Σ A_i / R_i,ext``.
        With RC on, ``U_wall_A`` means the DIRECT channel only (window +
        lightweight surfaces that bypass the mass node); the steady-state
        design conductance is ``UA_dc = U_wall_A + g_em·g_im/(g_em+g_im)``.
    C_surface : float
        R28 step 3: surface-node heat capacity (Wh/K) when
        ``wall_rc_nodes=3``; required > 0.  Lumped solar-receiving inner
        surfaces (floor slab + inner boards), ``Σ A_i·d_i·ρ_i·c_i / 3600``.
    g_sa : float
        R28 step 3: surface node -> air node film conductance (W/K) when
        ``wall_rc_nodes=3``; required > 0.  ``Σ A_i / R_si`` over the
        solar-receiving surfaces, R_si ≈ 0.125 m²K/W.
    g_sm : float
        R28 step 3: surface node -> mass node conductance (W/K) when
        ``wall_rc_nodes=3``; required > 0.  ``Σ A_i / (d_i/(2·k_i))`` into
        the inner half of the mass layer.
    solar_mass_fraction : float
        R28 step 3: fraction [0, 1] of the window solar gain deposited as a
        heat source inside the RC network by ``step_mass`` (mass node for
        2R2C, surface node for 2R3C); the remainder goes to the air node.
        0.0 (default) = legacy single-point air injection, bit-for-bit
        identical to pre-step-3 builds.  Requires ``wall_rc_nodes > 0``.
    wall_fd_nodes : int
        R28 step 6: 0 (default) = FD wall off (all paths unchanged);
        10..100 = enable the 1-D finite-difference wall continuum.
        Mutually exclusive with ``wall_rc_nodes > 0``.
    wall_layers : list
        (thickness_m, k_W_mK, rho_kg_m3, c_J_kgK) per layer, EXTERIOR ->
        INTERIOR; required when ``wall_fd_nodes > 0`` (all entries > 0).
    wall_area_m2 : float
        Conductive FD-wall area (m2); required > 0 when ``wall_fd_nodes > 0``.
    h_ext_wm2 : float
        Exterior film coefficient (W/m2K); required > 0 when ``wall_fd_nodes > 0``.
    wall_solar_abs : float
        Exterior solar absorptance [0, 1]; 0 (default) = sol-air disabled.
    h_int_c_wm2 : float
        Interior convective film (W/m2K); required > 0 when ``wall_fd_nodes > 0``.
    erv_enabled : bool
        R34/W3-E (H7): true = a mechanical fresh-air stream of
        ``erv_flow_m3h`` m3/h runs through an ERV/HRV heat-recovery core,
        IN ADDITION to the ``ach`` infiltration (the two channels
        superpose; the ERV flow does not replace leakage).  False
        (default) = no mechanical ventilation, bit-for-bit legacy path.
    erv_flow_m3h : float
        Mechanical fresh-air volume flow (m3/h); required > 0 when
        ``erv_enabled``.  Typical PFAL fresh air 0.5-2 room volumes/h
        (100-400 m3/h on a 200 m3 room).
    erv_sensible_eff : float
        Sensible (dry-bulb) recovery effectiveness in [0, 0.95].
        Fixed-effectiveness model per ASHRAE Handbook HVAC Systems and
        Equipment, Ch. 26 (Air-to-Air Energy Recovery Equipment);
        certified cores rate 0.5-0.85 (AHRI 1060 / EN 13141 classes).
    erv_latent_eff : float
        Latent (moisture) recovery effectiveness in [0, 0.95].
        0 (default) = sensible-only HRV (plate heat exchanger);
        > 0 = enthalpy ERV (membrane / enthalpy wheel) that also
        transfers moisture; enthalpy cores typically rate 0.45-0.75.
    """

    def __init__(
        self,
        U_wall_A: float = 50.0,
        A_window: float = 0.0,
        eta_solar: float = 0.15,
        ach: float = 0.001,
        permeance: float = 0.0,
        rho_air: float = 1.2,
        cp_air: float = 1005.0,
        V_room: float = 200.0,
        wall_rc_nodes: int = 0,
        C_mass: float = 0.0,
        g_im: float = 0.0,
        g_em: float = 0.0,
        C_surface: float = 0.0,
        g_sa: float = 0.0,
        g_sm: float = 0.0,
        solar_mass_fraction: float = 0.0,
        wall_fd_nodes: int = 0,
        wall_layers: Optional[List[Tuple[float, float, float, float]]] = None,
        wall_area_m2: float = 0.0,
        h_ext_wm2: float = 0.0,
        wall_solar_abs: float = 0.0,
        h_int_c_wm2: float = 0.0,
        erv_enabled: bool = False,
        erv_flow_m3h: float = 0.0,
        erv_sensible_eff: float = 0.7,
        erv_latent_eff: float = 0.0,
    ):
        self.U_wall_A = U_wall_A
        self.A_window = A_window
        self.eta_solar = eta_solar
        self.ach = ach
        self.permeance = permeance
        self.rho_air = rho_air
        self.cp_air = cp_air
        self.V_room = V_room
        # R34/W3-E (H7): ERV/HRV mechanical fresh air (defence-in-depth
        # guards; DesignProject.from_dict enforces the same rules at load
        # time, this catches programmatic Envelope(...) constructions).
        if not isinstance(erv_enabled, bool):
            raise ValueError(
                f"erv_enabled must be a boolean, got "
                f"{type(erv_enabled).__name__}: {erv_enabled!r}"
            )
        if isinstance(erv_flow_m3h, bool) or not isinstance(
            erv_flow_m3h, (int, float)
        ):
            raise ValueError(
                f"erv_flow_m3h must be a number (m3/h), got "
                f"{type(erv_flow_m3h).__name__}: {erv_flow_m3h!r}"
            )
        if float(erv_flow_m3h) < 0.0:
            raise ValueError(f"erv_flow_m3h must be >= 0, got {erv_flow_m3h}")
        for _eff_name, _eff_val in (
            ("erv_sensible_eff", erv_sensible_eff),
            ("erv_latent_eff", erv_latent_eff),
        ):
            if isinstance(_eff_val, bool) or not isinstance(_eff_val, (int, float)):
                raise ValueError(
                    f"{_eff_name} must be a number (effectiveness), got "
                    f"{type(_eff_val).__name__}: {_eff_val!r}"
                )
            if not (0.0 <= float(_eff_val) <= 0.95):
                raise ValueError(
                    f"{_eff_name} must be within [0, 0.95] (certified core "
                    f"band 0.5-0.85 sensible / 0.45-0.75 enthalpy), got "
                    f"{_eff_val}"
                )
        if erv_enabled and not (float(erv_flow_m3h) > 0.0):
            raise ValueError(
                f"erv_enabled=true requires erv_flow_m3h > 0 m3/h (got "
                f"{erv_flow_m3h}); an enabled ERV with no flow is a config "
                f"error, not a zero-flow machine."
            )
        if not erv_enabled and float(erv_flow_m3h) > 0.0:
            raise ValueError(
                f"erv_flow_m3h > 0 ({erv_flow_m3h}) requires "
                f"erv_enabled=true -- otherwise the mechanical fresh air "
                f"is silently ignored."
            )
        self.erv_enabled = erv_enabled
        self.erv_flow_m3h = float(erv_flow_m3h)
        self.erv_sensible_eff = float(erv_sensible_eff)
        self.erv_latent_eff = float(erv_latent_eff)
        # R28 step 3: solar-split fraction (only consumed on RC paths; the
        # engine reads it every substep, so store unconditionally).
        if not (0.0 <= solar_mass_fraction <= 1.0):
            raise ValueError(
                "solar_mass_fraction must be within [0, 1], got "
                f"{solar_mass_fraction!r}"
            )
        if solar_mass_fraction > 0.0 and wall_rc_nodes == 0 and wall_fd_nodes == 0:
            raise ValueError(
                "solar_mass_fraction > 0 requires wall_rc_nodes=2, 3 or "
                "wall_fd_nodes > 0 (no mass/surface node exists in the "
                f"legacy single-node envelope; got {solar_mass_fraction})"
            )
        self.solar_mass_fraction = float(solar_mass_fraction)
        # R28 step 6: 1-D FD wall continuum (None = off; mutually exclusive
        # with the lumped RC network).
        if wall_fd_nodes != 0:
            if wall_rc_nodes != 0:
                raise ValueError(
                    "wall_fd_nodes and wall_rc_nodes are mutually exclusive "
                    f"wall models (got {wall_fd_nodes} / {wall_rc_nodes})"
                )
            if not isinstance(wall_fd_nodes, int) or not (10 <= wall_fd_nodes <= 100):
                raise ValueError(
                    f"wall_fd_nodes must be an int in [10, 100] (got "
                    f"{wall_fd_nodes!r}); 0 disables the FD wall"
                )
            layers = list(wall_layers or [])
            if not layers:
                raise ValueError(
                    "wall_fd_nodes > 0 requires wall_layers "
                    "[(thickness_m, k, rho, c_J_kgK), ...] exterior->interior"
                )
            if len(layers) > wall_fd_nodes:
                raise ValueError(
                    f"wall_fd_nodes ({wall_fd_nodes}) must be >= the number "
                    f"of wall_layers ({len(layers)})"
                )
            clean_layers = []
            for li, lay in enumerate(layers):
                if not isinstance(lay, (list, tuple)) or len(lay) != 4:
                    raise ValueError(
                        f"wall_layers[{li}] must be (thickness_m, k, rho, c), "
                        f"got {lay!r}"
                    )
                d_i, k_i, rho_i, c_i = (float(v) for v in lay)
                for name, v in (
                    ("thickness_m", d_i),
                    ("k_W_mK", k_i),
                    ("rho_kg_m3", rho_i),
                    ("c_J_kgK", c_i),
                ):
                    if not (v > 0.0):
                        raise ValueError(
                            f"wall_layers[{li}].{name} must be > 0, got {v}"
                        )
                clean_layers.append((d_i, k_i, rho_i, c_i))
            if not (wall_area_m2 > 0.0):
                raise ValueError(
                    f"wall_fd_nodes > 0 requires wall_area_m2 > 0 (got {wall_area_m2})"
                )
            if not (h_ext_wm2 > 0.0):
                raise ValueError(
                    f"wall_fd_nodes > 0 requires h_ext_wm2 > 0 (got {h_ext_wm2})"
                )
            if not (h_int_c_wm2 > 0.0):
                raise ValueError(
                    f"wall_fd_nodes > 0 requires h_int_c_wm2 > 0 (got {h_int_c_wm2})"
                )
            if not (0.0 <= wall_solar_abs <= 1.0):
                raise ValueError(
                    f"wall_solar_abs must be within [0, 1], got {wall_solar_abs}"
                )
            if C_mass <= 0.0:
                raise ValueError(
                    f"wall_fd_nodes > 0 requires C_mass > 0 Wh/K (internal "
                    f"mass node for the surface radiation exchange; got {C_mass})"
                )
            if g_sm <= 0.0:
                raise ValueError(
                    f"wall_fd_nodes > 0 requires g_sm > 0 W/K (surface <-> "
                    f"internal mass coupling; got {g_sm})"
                )
            for name, v in (
                ("g_em", g_em),
                ("g_im", g_im),
                ("C_surface", C_surface),
                ("g_sa", g_sa),
            ):
                if v != 0.0:
                    raise ValueError(
                        f"{name} must be 0 when wall_fd_nodes > 0 (the FD "
                        f"wall replaces the RC network; got {v})"
                    )
            self._fd = _WallFD.build(
                layers=clean_layers,
                n_nodes=wall_fd_nodes,
                area_m2=float(wall_area_m2),
                h_ext_wm2=float(h_ext_wm2),
                h_int_c_wm2=float(h_int_c_wm2),
                g_sm=float(g_sm),
                C_mass_whk=float(C_mass),
            )
            self._fd_params = {
                "solar_abs": float(wall_solar_abs),
                "h_ext_wm2": float(h_ext_wm2),
            }
        else:
            self._fd = None
            self._fd_params = None
        # R28: additive 2R2C/2R3C wall mass network (None = legacy single node).
        if wall_rc_nodes not in (0, 2, 3):
            raise ValueError(
                f"wall_rc_nodes must be 0 (single node, legacy), 2 (2R2C wall "
                f"mass network) or 3 (2R3C wall network with surface node), "
                f"got {wall_rc_nodes!r}"
            )
        if wall_rc_nodes == 2:
            if C_mass <= 0.0:
                raise ValueError("wall_rc_nodes=2 requires C_mass > 0 Wh/K")
            if g_im <= 0.0:
                raise ValueError("wall_rc_nodes=2 requires g_im > 0 W/K")
            if g_em < 0.0:
                raise ValueError("wall_rc_nodes=2 requires g_em >= 0 W/K")
            self._rc = _WallRC(C_mass=C_mass, g_im=g_im, g_em=g_em)
        elif wall_rc_nodes == 3:
            if C_mass <= 0.0:
                raise ValueError("wall_rc_nodes=3 requires C_mass > 0 Wh/K")
            if g_em < 0.0:
                raise ValueError("wall_rc_nodes=3 requires g_em >= 0 W/K")
            if C_surface <= 0.0:
                raise ValueError("wall_rc_nodes=3 requires C_surface > 0 Wh/K")
            if g_sa <= 0.0:
                raise ValueError("wall_rc_nodes=3 requires g_sa > 0 W/K")
            if g_sm <= 0.0:
                raise ValueError("wall_rc_nodes=3 requires g_sm > 0 W/K")
            self._rc = _WallRC(
                C_mass=C_mass,
                g_im=0.0,  # unused in 2R3C: air coupling is g_sa via T_s
                g_em=g_em,
                C_surface=C_surface,
                g_sa=g_sa,
                g_sm=g_sm,
                T_s=20.0,
            )
        else:
            self._rc = None  # default: legacy path, zero behavioural drift

    @property
    def rc_enabled(self) -> bool:
        """True when the 2R2C/2R3C wall mass network is active (wall_rc_nodes>0)."""
        return self._rc is not None

    @property
    def rc3_enabled(self) -> bool:
        """True when the 2R3C surface node is active (wall_rc_nodes=3)."""
        return self._rc is not None and self._rc.is_rc3

    @property
    def fd_enabled(self) -> bool:
        """True when the 1-D FD wall continuum is active (wall_fd_nodes>0)."""
        return self._fd is not None

    def reset(self, T_init: float) -> None:
        """Reset the mass-node state to ``T_init`` (degC); engine calls this
        once at run start with the air-node initial temperature so all RC
        states start consistent."""
        if self._rc is None and self._fd is None:
            return
        if self._fd is not None:
            self._fd.reset(float(T_init))
            return
        self._rc.T_m = float(T_init)
        if self._rc.T_s is not None:
            self._rc.T_s = float(T_init)

    @property
    def T_m(self) -> Optional[float]:
        """Current mass-node temperature (degC), or None when RC/FD is off."""
        if self._fd is not None:
            return self._fd.T_m
        return None if self._rc is None else self._rc.T_m

    @property
    def T_s(self) -> Optional[float]:
        """Current surface-node temperature (degC), or None when 2R2C/off.

        FD wall: the interior control volume (innermost cell) temperature.
        """
        if self._fd is not None:
            return float(self._fd.T[-1])
        return None if self._rc is None else self._rc.T_s

    @property
    def T_wall_out(self) -> Optional[float]:
        """FD wall: exterior control volume temperature (degC), else None."""
        return None if self._fd is None else float(self._fd.T[0])

    @property
    def T_sol_air(self) -> Optional[float]:
        """FD wall: last sol-air boundary temperature (degC), else None."""
        return None if self._fd is None else self._fd.T_sol_air

    def step_mass(
        self,
        T_ext: float,
        T_z: float,
        dt: float,
        Q_source_w: float = 0.0,
        I_ext_wm2: float = 0.0,
    ) -> float:
        """Advance the wall nodes one step (dt seconds); return the air-side
        discharge node temperature.

        RC networks: explicit Euler from the SUBSTEP-START T_ext/T_z
        (staggered with the air-node integrator, same O(dt) ordering error);
        the engine calls this before the air-node heat balance so Q_wall sees
        the freshly stepped states.  ``Q_source_w`` (W) is the solar-split
        source (``solar_mass_fraction`` of the window gain): deposited on the
        surface node in 2R3C and on the mass node in 2R2C; default 0
        reproduces the pre-step-3 balance bit-for-bit.

        FD wall (``wall_fd_nodes > 0``): fully implicit (backward-Euler) solve
        of the whole continuum + mass node; boundary films are evaluated at
        the NEW states so the air-side film product mirrors the wall balance
        exactly (no staggering residual).  ``I_ext_wm2`` (W/m2) drives the
        sol-air exterior boundary through ``wall_solar_abs`` (0 = off).

        Only a +-100 degC divergence guard applies (no clamp: the wall nodes
        are slow, large-inertia states and clamping them would mask physics).
        """
        if self._fd is not None:
            return self._fd.step(
                T_ext,
                T_z,
                dt,
                Q_source_w=Q_source_w,
                I_ext_wm2=I_ext_wm2,
                solar_abs=self._fd_params["solar_abs"],
                h_ext_wm2=self._fd_params["h_ext_wm2"],
            )
        if self._rc is None:
            raise RuntimeError("step_mass called with wall mass network disabled")
        rc = self._rc
        if rc.T_s is not None:
            # 2R3C: coupled explicit Euler on (T_s, T_m) from substep-start
            # states.  C_surface/C_mass are Wh/K -> J/K via x3600; g in W/K,
            # dt in s -> fluxes in W, energies in J.
            q_s = (
                rc.g_sa * (T_z - rc.T_s)
                + rc.g_sm * (rc.T_m - rc.T_s)
                + Q_source_w
            )
            q_m = rc.g_sm * (rc.T_s - rc.T_m) + rc.g_em * (T_ext - rc.T_m)
            t_s_new = rc.T_s + q_s * dt / (rc.C_surface * 3600.0)
            t_m_new = rc.T_m + q_m * dt / (rc.C_mass * 3600.0)
            for name, v in (("surface", t_s_new), ("mass", t_m_new)):
                if not (-100.0 <= v <= 100.0):
                    raise RuntimeError(
                        f"RC3 {name} node diverged to {v:.1f} C -- check "
                        f"wall_rc stability (C_surface={rc.C_surface:.1f} Wh/K, "
                        f"g_sa={rc.g_sa:.1f} W/K, g_sm={rc.g_sm:.1f} W/K, "
                        f"C_mass={rc.C_mass:.1f} Wh/K, g_em={rc.g_em:.1f} W/K, "
                        f"dt={dt:.0f} s, T_s={rc.T_s:.1f} C, T_m={rc.T_m:.1f} C)"
                    )
            rc.T_s = t_s_new
            rc.T_m = t_m_new
            return t_s_new
        # 2R2C: C_mass is Wh/K -> J/K via x3600; g in W/K, dt in s -> energy J.
        q_net = rc.g_em * (T_ext - rc.T_m) + rc.g_im * (T_z - rc.T_m) + Q_source_w
        T_new = rc.T_m + q_net * dt / (rc.C_mass * 3600.0)
        if not (-100.0 <= T_new <= 100.0):
            raise RuntimeError(
                f"Mass-node temperature diverged to {T_new:.1f} C -- check "
                f"wall_rc stability (C_mass={rc.C_mass:.1f} Wh/K, g_im="
                f"{rc.g_im:.1f} W/K, g_em={rc.g_em:.1f} W/K, dt={dt:.0f} s, "
                f"T_m={rc.T_m:.1f} C)"
            )
        rc.T_m = T_new
        return T_new

    # -- Heat transfer -----------------------------------------------------
    def Q_wall(self, T_ext: float, T_z: float, T_m: Optional[float] = None) -> float:
        """Conductive envelope heat flow (W). + = into room.

        Legacy path (``T_m`` is None or RC/FD off): ``U_wall_A * (T_ext - T_z)``
        -- the historical single-node expression, unchanged.  RC path: the
        direct channel (window + lightweight surfaces) plus the discharge of
        the RC node returned by :meth:`step_mass` -- ``g_im * (T_m - T_z)``
        for 2R2C, ``g_sa * (T_s - T_z)`` for 2R3C; the outdoor leg g_em
        enters only through the RC-node dynamics.  FD path: direct channel
        plus the interior convective film ``g_c * (T_inner - T_z)``; the
        exterior film and interior conduction enter through the FD dynamics.
        """
        if self._fd is not None:
            if T_m is None:
                raise RuntimeError(
                    "FD wall active: pass the step_mass return value "
                    "(interior surface temperature) into Q_wall"
                )
            return self.U_wall_A * (T_ext - T_z) + self._fd.g_c * (T_m - T_z)
        if self._rc is None or T_m is None:
            return self.U_wall_A * (T_ext - T_z)
        if self._rc.T_s is not None:
            return self.U_wall_A * (T_ext - T_z) + self._rc.g_sa * (T_m - T_z)
        return self.U_wall_A * (T_ext - T_z) + self._rc.g_im * (T_m - T_z)

    def Q_solar(self, solar_radiation_wm2: float) -> float:
        """Solar heat gain through glazing (W)."""
        return self.eta_solar * self.A_window * solar_radiation_wm2

    # -- Infiltration (sensible + latent) ---------------------------------
    def infiltration(
        self, T_ext: float, T_z: float, W_ext: float, W_z: float
    ) -> Tuple[float, float, float]:
        """Mass-flow infiltration with explicit sensible + latent energy.

        Returns
        -------
        (Q_sens_W, M_lat_kgs, Q_lat_W) : (float, float, float)
            Sensible heat flow (W, + into room), latent moisture flow
            (kg/s, + into room) and the latent heat carried by that
            moisture (W, + into room).  Q_lat = M_lat * L_v(T_z); together
            Q_sens_W + Q_lat_W form the complete enthalpy flux of the
            infiltrating air.  Callers MUST include Q_lat_W in the room
            heat balance or energy conservation is violated.
        """
        if self.ach <= 0.0:
            return 0.0, 0.0, 0.0
        m_dot = self.ach * self.V_room * self.rho_air / 3600.0  # kg/s
        Q_sens = m_dot * self.cp_air * (T_ext - T_z)  # W
        M_lat = m_dot * (W_ext - W_z)  # kg/s
        Q_lat = M_lat * latent_heat_vaporization(T_z) * 1000.0  # W  (kJ/kg -> J/kg)
        return Q_sens, M_lat, Q_lat

    def envelope_moisture(self, W_ext: float, W_z: float) -> float:
        """Passive moisture migration through envelope (kg/s, + into room)."""
        return self.permeance * (W_ext - W_z)

    # -- Mechanical ventilation with ERV/HRV heat recovery (R34/W3-E) ----
    def mechanical_ventilation(
        self, T_ext: float, T_z: float, W_ext: float, W_z: float
    ) -> Tuple[float, float, float, float, float]:
        """Mass-flow mechanical fresh air through an ERV/HRV core.

        The ventilation mass flow ``m_v = erv_flow_m3h * rho_air / 3600``
        is INDEPENDENT of the ``ach`` infiltration channel (leakage keeps
        running; both superpose).  Recovery follows the fixed-effectiveness
        model of ASHRAE Handbook HVAC Systems and Equipment, Ch. 26
        (Air-to-Air Energy Recovery Equipment): with effectiveness eps the
        supply stream leaves the core at the eps-weighted state of the two
        streams, so the NET load imposed on the room is the un-recovered
        (1 - eps) share of the full mass-flow expression::

            Q_sens_net = (1 - eps_s) * m_v * cp * (T_ext - T_z)   [W, + into room]
            M_lat_net  = (1 - eps_l) * m_v * (W_ext - W_z)        [kg/s, + into room]
            Q_lat_net  = M_lat_net * L_v(T_z)                     [W, + into room]

        eps_s > 0 recovers heat in winter (T_ext < T_z) and "coolth" in
        summer (T_ext > T_z) symmetrically -- both directions reduce the
        magnitude of the net load.  eps_l = 0 (HRV) passes the full
        humidity difference; eps_l > 0 (enthalpy ERV) attenuates it.

        Returns
        -------
        (Q_sens_net_W, M_lat_net_kgs, Q_lat_net_W, Q_rec_sens_W, Q_rec_lat_W)
            The three NET terms (same sign convention as :meth:`infiltration`)
            plus the two RECOVERED fluxes for metering.  ``Q_rec_sens =
            eps_s * m_v * cp * (T_ext - T_z)`` and ``Q_rec_lat =
            eps_l * m_v * (W_ext - W_z) * L_v(T_z)`` carry the sign of the
            driving difference (negative in winter = heat retained); the
            engine meters their absolute values as recovered energy.
            Disabled ERV returns all zeros.
        """
        if not self.erv_enabled or self.erv_flow_m3h <= 0.0:
            return 0.0, 0.0, 0.0, 0.0, 0.0
        m_v = self.erv_flow_m3h * self.rho_air / 3600.0  # kg/s
        q_full_sens = m_v * self.cp_air * (T_ext - T_z)  # W, un-recovered basis
        m_full_lat = m_v * (W_ext - W_z)  # kg/s
        # Same evaluation order as infiltration() ((M*lv)*1000) so the
        # eps=0 channel is bitwise identical to the infiltration expression.
        Q_sens_net = (1.0 - self.erv_sensible_eff) * q_full_sens
        M_lat_net = (1.0 - self.erv_latent_eff) * m_full_lat
        Q_lat_net = M_lat_net * latent_heat_vaporization(T_z) * 1000.0
        Q_rec_sens = self.erv_sensible_eff * q_full_sens
        Q_rec_lat = (
            self.erv_latent_eff
            * m_full_lat
            * latent_heat_vaporization(T_z)
            * 1000.0
        )
        return Q_sens_net, M_lat_net, Q_lat_net, Q_rec_sens, Q_rec_lat
