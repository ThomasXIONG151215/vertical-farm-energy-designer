"""
Integrated PV-Battery-Grid energy system.

Combines the PV single-diode model, the battery dispatch model and the TOU
tariff to evaluate a given (PV area, battery capacity) design against a building
load profile. Produces the same metrics the reused ``EnergySystem`` delivers:
grid dependency, capital cost, annual savings, payback period.
NOTE (P6-5): the economics inside ``calculate_metrics`` are an ALTERNATIVE /
legacy scope (single-lifetime CRF + hard-coded maintenance).  The authoritative
LCOE is computed centrally in ``sweep._compute_lcoe`` / ``sweep._annualized_capital``
(per-component CRF depreciation years) and reused by ``engine.run``; O&M is charged
there via ``opex.maintenance_pct``.  Do not read LCOE from this class.

G12 (Wave 1): optional tariff features, both default-OFF (bit-identical
legacy path).  ``tariff.export_limit_kw`` caps the hourly feed-in at the
grid interface (the clipped surplus is curtailed, reported only while the
cap is configured); ``tariff.demand_charge_per_kw`` adds a monthly peak
demand charge inside ``Tariff.annual_cost``/``net_grid_cost`` (requires
``weather["month"]`` labels, fail-fast while active).

T5 (dispatch hook): ``simulate_performance``/``calculate_metrics`` accept an
optional ``dispatch_policy`` callable that replaces the built-in greedy
battery dispatch with a per-timestep policy (see the protocol in
``simulate_performance``).  ``None`` (the default) keeps the greedy path
bit-identical.
"""

import math
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional, Tuple

import numpy as np

from .pv import PVSystem
from .battery import BatterySystem, CALENDAR_MONTH_HOURS
from .grid import Tariff

__all__ = ["EnergySystem"]


@dataclass
class EnergySystem:
    pv: PVSystem = field(default_factory=PVSystem)
    battery: BatterySystem = field(default_factory=BatterySystem)
    tariff: Tariff = field(default_factory=Tariff)
    interest_rate: float = 0.06
    lifetime: int = 25
    maintenance: float = 0.01  # LEGACY (P6-5): the pv/battery maintenance
    # config fields were removed in P5; O&M is
    # charged uniformly via ``opex.maintenance_pct``
    # in sweep/engine.  Only feeds
    # calculate_metrics' own (alternative-scope)
    # annual_om.

    # ---- simulation -----------------------------------------------------
    def simulate_performance(
        self,
        x,
        weather: Dict[str, np.ndarray],
        load: np.ndarray,
        year: int = 0,
        pv_power_override: Optional[np.ndarray] = None,
        dispatch_policy: Optional[Callable[[Dict], Tuple[float, float]]] = None,
    ) -> Dict[str, np.ndarray]:
        """Simulate the PV-battery-grid dispatch over the load series.

        T5 (dispatch hook): ``dispatch_policy`` (default ``None``) optionally
        replaces the built-in greedy battery dispatch with a per-timestep
        policy.  Protocol (frozen; the C1 DispatchPolicy must align with it):

        * ``dispatch_policy(obs) -> (charge_w, discharge_w)`` runs once per
          hourly timestep, in timestep order.
        * ``obs`` is a plain dict with exactly these fields: ``t`` (int,
          0-based timestep index), ``hour`` (int hour-of-day), ``month``
          (int 1-12), ``price`` (float, tariff price of ``hour``), ``pv_w``
          and ``load_w`` (floats, this step's PV and load power), ``soc_kwh``
          (float, stored energy now), ``capacity_kwh`` (float, current usable
          capacity after fade), ``dt_h`` (float, 1.0).
        * The action is a pair of *requested* charge/discharge powers.  The
          engine clamps every request with the same C-rate / SOC-headroom /
          efficiency limits as the greedy path.  Charging is NOT limited to
          the PV surplus (the policy may buy from the grid -- this is the
          deliberate difference from greedy); discharging IS clamped to the
          current load deficit (discharge serves load only).  The clamped
          grid import/export is derived from the energy balance downstream.
        * ``charge_w > 0`` together with ``discharge_w > 0`` is a contract
          violation and raises ``ValueError``; negative requests also raise.
        * The policy sees current-and-past information ONLY.  Feeding any
          future load/PV array into the policy is forbidden by this contract;
          explicit forecast fields are a separate future project.
        * Both plain functions and callable objects work.  An object exposing
          ``reset(timesteps, capacity_kwh)`` has it called once before the
          first observation (nameplate ``E_bat``); without it nothing extra
          happens.  When ``E_bat <= 0`` there is no battery to dispatch and
          the policy is not invoked.
        * ``None`` keeps the exact greedy dispatch below (bit-identical).
        """
        A_pv, E_bat = float(x[0]), float(x[1])
        load = np.asarray(load, dtype=float)
        # G1 (Wave 2): multi-array mode sums per-array PV output upstream and
        # injects it here, bypassing the single-array model call.  None keeps
        # the exact legacy path (bitwise-identical).
        if pv_power_override is not None:
            pv_power = np.asarray(pv_power_override, dtype=float)
        else:
            pv_power = self.pv.calculate_pv_output(weather, A_pv, year=year)
        power_balance = pv_power - load
        # T5 (dispatch hook): a supplied dispatch_policy OWNS the battery
        # dispatch (the greedy and its P1-2 valley variant are bypassed);
        # None keeps the exact greedy calls below, untouched.
        if dispatch_policy is not None:
            bat = self._dispatch_with_policy(pv_power, load, E_bat, weather, dispatch_policy)
        # P1-2: hand the tariff + hour-of-day to the battery only when grid
        # charging is enabled; the default path keeps the exact previous
        # call (bitwise-identical dispatch).
        # T2 (B8-2): explicit hourly dt — the engine exports hourly arrays,
        # so every dispatch step is 1 h (the battery default, now stated at
        # the call).  Sub-hourly PVBES is a future bounded project; an
        # explicit dt keeps any later change from silently mispricing energy.
        elif self.battery.allow_grid_charging:
            bat = self.battery.calculate_battery_flows(
                power_balance,
                load,
                E_bat,
                dt=1.0,
                hourly_prices=self.tariff.hourly_prices,
                hours=np.asarray(weather.get("hour", np.zeros(len(load))), dtype=int),
            )
        else:
            bat = self.battery.calculate_battery_flows(power_balance, load, E_bat, dt=1.0)
        battery_discharge = np.array(bat["battery_discharge"])
        battery_charge = np.array(bat["battery_charge"])
        grid_import = np.maximum(0.0, load - pv_power - battery_discharge)
        grid_export = np.maximum(0.0, pv_power - battery_charge - load)
        # P1-2: TOU grid charging draws power FROM the grid.  It must land
        # in grid_import; grid_export stays PV-only (grid-bought charging
        # power must not be netted against PV surplus).  battery_charge
        # keeps the grid-charged component so the annual balance
        # (pv + import + discharge = load + charge + export) closes exactly.
        grid_charged = np.asarray(bat.get("grid_charged", np.zeros_like(grid_import)))
        if np.any(grid_charged != 0.0):
            grid_import = grid_import + grid_charged
            grid_export = np.maximum(0.0, pv_power - (battery_charge - grid_charged) - load)
        # P4-18: year-end SOC reconciliation (battery restored to soc0).  The
        # drift E_bat*(soc0 - soc_end) crosses the grid interface at the last
        # timestep.  Applied AFTER the max() above so both sides of the annual
        # balance move together and the equation closes exactly.
        recon = float(bat.get("recon_grid_kwh", 0.0))
        if recon > 0.0:
            battery_charge[-1] += recon
            grid_import[-1] += recon
        elif recon < 0.0:
            battery_discharge[-1] += -recon
            grid_export[-1] += -recon
        # ── G12 (Wave 1): feed-in cap and curtailment ─────────────────────
        # The surplus that reaches the grid interface (PV after load and
        # charging, including the P4-18 year-end dump applied above) is
        # clipped hour by hour to tariff.export_limit_kw.  The clipped
        # excess is curtailed energy: it is never sold (annual_cost prices
        # the capped grid_export only) and never redirected to load or
        # battery -- those are served earlier in the dispatch order, so
        # only the feed-in share beyond the cap is lost.  None (default)
        # skips the block entirely: bit-identical legacy dispatch, no
        # curtailment array, no extra perf key.
        pv_curtailed = None
        if self.tariff.export_limit_kw is not None:
            _cap = float(self.tariff.export_limit_kw)
            _capped = np.minimum(grid_export, _cap)
            pv_curtailed = grid_export - _capped
            grid_export = _capped
        perf = {
            "pv_power": pv_power,
            "battery_discharge": battery_discharge,
            "battery_charge": battery_charge,
            "battery_soc": bat["battery_soc"],
            "battery_cycles": bat["battery_cycles"],
            # Round 21 F4: the P4-18 reconciliation energy (kWh, signed:
            # + grid top-up / import, - dump / export) exported alongside the
            # arrays so annual bookkeeping identities close from summary.csv.
            "battery_recon_grid_kwh": float(bat.get("recon_grid_kwh", 0.0)),
            "grid_import": grid_import,
            "grid_export": grid_export,
            "load": load,
            # Loss-of-power (islanded view): load that cannot be met by PV +
            # battery discharge together. Grid import is not subtracted — on a
            # connected grid import is always available, so this quantity is the
            # residual unmet load that would remain in an islanded scenario.
            # P6-6: arithmetically identical to grid_import except the P4-18
            # recon-adjusted last timestep.
            "power_deficit": np.maximum(0.0, load - pv_power - battery_discharge),
        }
        if pv_curtailed is not None:
            # G12: hourly curtailed energy (kW), present ONLY while a
            # feed-in cap is configured (metrics expose the annual sum as
            # pv_curtailed_kwh).
            perf["pv_curtailed"] = pv_curtailed
        return perf

    # ---- T5 policy dispatch ---------------------------------------------
    def _dispatch_with_policy(
        self,
        pv_power: np.ndarray,
        load: np.ndarray,
        E_bat: float,
        weather: Dict[str, np.ndarray],
        dispatch_policy: Callable[[Dict], Tuple[float, float]],
    ) -> Dict[str, np.ndarray]:
        """Hourly dispatch loop driven by ``dispatch_policy`` (T5 hook).

        Returns the same key set as ``BatterySystem.calculate_battery_flows``
        so the shared accounting tail of ``simulate_performance`` (grid
        import/export derivation, P4-18 reconciliation, G12 feed-in cap)
        applies unchanged.  Clamping choice (one of the two the T5 brief
        allows): call-side pre-clamp with the SAME formulas battery.py uses
        internally -- the per-step limits are loop-locals there and are not
        exposed, and battery.py itself is signature-locked by the test_34
        gate, so the equivalent formulas are mirrored below expression for
        expression (self-discharge, G10 terminal cap, P2-4 cycle fade, G11
        calendar fade, P4-18 reconciliation).

        obs conventions: ``hour`` defaults to 0 and ``month`` to 1 when the
        weather dict lacks the label (the greedy path shares the hour-0
        convention).  ``capacity_kwh``/``soc_kwh`` use the CURRENT usable
        capacity ``E_now`` (nameplate while no fade has accrued), so the
        policy can read the exact SOC fraction as their ratio.  ``pv_w`` /
        ``load_w`` / the action powers use the same power unit as the load
        series (kW in this codebase) despite the protocol's ``_w`` names.
        """
        n = len(pv_power)
        b = self.battery
        dt = 1.0  # hourly dispatch, identical to the greedy call sites (T2).
        hours = np.asarray(weather.get("hour", np.zeros(n)), dtype=int)
        months = np.asarray(weather.get("month", np.ones(n, dtype=int)), dtype=int)

        # Protocol reset hook: object policies may expose
        # reset(timesteps, capacity_kwh); it runs once, before the first
        # observation.  Plain functions simply skip this.
        reset = getattr(dispatch_policy, "reset", None)
        if callable(reset):
            reset(n, E_bat)

        power_balance = pv_power - load
        battery_power = np.zeros(n)  # signed: + discharge, - charge
        battery_discharge = np.zeros(n)  # kW delivered to load
        battery_charge = np.zeros(n)  # kW into battery
        grid_charged = np.zeros(n)  # kW of the charge bought from the grid
        battery_soc = np.zeros(n)
        soc = 0.5  # soc0 default of calculate_battery_flows (the greedy call).
        total_charged = 0.0
        total_discharged = 0.0
        # P2-4/G11 aging state -- identical formulas to battery.py.
        soh_k = (1.0 - b.soh_eol) / max(int(b.cycle_life), 1)
        cycles_now = 0.0
        E_now = E_bat
        k_cal = b.calendar_sqrt_coeff()

        for i in range(n):
            net = power_balance[i]
            soc *= 1.0 - b.self_discharge * dt
            if E_bat <= 0:
                # No battery to dispatch: mirror battery.py (soc row zeroed,
                # step skipped).  The policy is deliberately not invoked --
                # there is no dispatch decision to make.
                battery_soc[i] = 0.0
                continue
            # G10: effective terminal power cap (same expression as
            # battery.py).
            if b.power_kw is None:
                p_crate_cap = b.c_rate * E_now
            else:
                p_crate_cap = min(b.c_rate * E_now, b.power_kw)
            p_charge_max = min(p_crate_cap, (b.soc_max - soc) * E_now / dt)
            p_discharge_max = min(p_crate_cap, (soc - b.soc_min) * E_now / dt) * b.eta_dis

            obs = {
                "t": i,
                "hour": int(hours[i]),
                "month": int(months[i]),
                "price": self.tariff.price_for_hour(int(hours[i])),
                "pv_w": float(pv_power[i]),
                "load_w": float(load[i]),
                "soc_kwh": float(soc * E_now),
                "capacity_kwh": float(E_now),
                "dt_h": dt,
            }
            action = dispatch_policy(obs)
            try:
                charge_req, discharge_req = action
            except (TypeError, ValueError):
                raise ValueError(
                    "dispatch_policy must return a (charge_w, discharge_w) "
                    f"pair of two numbers, got {action!r}"
                )
            charge_req = float(charge_req)
            discharge_req = float(discharge_req)
            if charge_req > 0.0 and discharge_req > 0.0:
                raise ValueError(
                    "dispatch_policy contract violation: charge_w and "
                    f"discharge_w are both positive at t={i} "
                    f"({charge_req!r}, {discharge_req!r}); the battery cannot "
                    "charge and discharge in the same timestep."
                )
            if charge_req < 0.0 or discharge_req < 0.0:
                raise ValueError(
                    "dispatch_policy contract violation: power requests must "
                    f"be non-negative, got ({charge_req!r}, {discharge_req!r}) "
                    f"at t={i}."
                )

            surplus = max(0.0, net)
            deficit = max(0.0, -net)
            # Charge: clamped by the terminal limits ONLY (grid charging is
            # allowed -- the deliberate difference from greedy, which would
            # also clamp to the PV surplus).  Discharge: clamped to the load
            # deficit and the terminal limits (the greedy boundary -- the
            # battery serves load only, it never dumps into exports).
            ch = min(charge_req, max(0.0, p_charge_max))
            dch = min(discharge_req, deficit, max(0.0, p_discharge_max))
            if ch > 0.0:
                soc += ch * b.eta_ch * dt / E_now
                battery_charge[i] = ch
                battery_power[i] = -ch
                total_charged += ch * dt
                # Split the charge at the PV surplus first; the remainder is
                # bought from the grid and lands in grid_import downstream
                # (same accounting the P1-2 valley charging uses).
                grid_charged[i] = ch - min(ch, surplus)
            if dch > 0.0:
                soc -= dch * dt / (b.eta_dis * E_now)
                battery_discharge[i] = dch
                battery_power[i] = dch
                total_discharged += dch * dt
            soc = min(b.soc_max, max(b.soc_min, soc))
            battery_soc[i] = soc

            # P2-4/G11: age the cell exactly like battery.py (nameplate EFC
            # throughput, then linear cycle fade plus the optional calendar
            # term), so a policy-driven schedule ages identically to a greedy
            # one with the same power flows.
            cycles_now += (
                (battery_charge[i] * b.eta_ch + battery_discharge[i] / max(b.eta_dis, 0.01))
                * dt
                / (2.0 * E_bat)
            )
            fade = soh_k * cycles_now
            if k_cal > 0.0:
                fade += k_cal * math.sqrt((i + 1) * dt / CALENDAR_MONTH_HOURS)
            E_now = E_bat * max(1.0 - fade, 1e-3)

        # P4-18: year-end periodic reconciliation, verbatim battery.py logic
        # (restore soc0, report the grid energy that must cross the
        # interface so the annual balance closes exactly).
        soc_end = float(soc)
        soc_target = min(b.soc_max, max(b.soc_min, 0.5))
        recon_grid_kwh = 0.0
        if E_bat > 0 and n > 0:
            need_stored = E_now * (soc_target - soc_end)
            if need_stored > 0.0:
                recon_grid_kwh = need_stored / b.eta_ch  # grid top-up (import)
                total_charged += recon_grid_kwh
            elif need_stored < 0.0:
                recon_grid_kwh = -(-need_stored) * b.eta_dis  # dump (export)
                total_discharged += -recon_grid_kwh
            battery_soc[-1] = soc_target
        return {
            "battery_power": battery_power,
            "battery_discharge": battery_discharge,
            "battery_charge": battery_charge,
            "battery_soc": battery_soc,
            "grid_charged": grid_charged,
            "total_charged": total_charged,
            "total_discharged": total_discharged,
            "battery_cycles": (
                total_charged * b.eta_ch + total_discharged / max(b.eta_dis, 0.01)
            )
            / (2.0 * E_bat)
            if E_bat > 0
            else 0.0,
            "soc_end": soc_end,
            "recon_grid_kwh": recon_grid_kwh,
        }

    # ---- metrics --------------------------------------------------------
    def calculate_metrics(
        self,
        x,
        weather: Dict[str, np.ndarray],
        load: np.ndarray,
        dt: float = 1.0,
        year: int = 0,
        pv_power_override: Optional[np.ndarray] = None,
        dispatch_policy: Optional[Callable[[Dict], Tuple[float, float]]] = None,
    ) -> Dict[str, float]:
        """Full metric set; ``dispatch_policy`` passes through to
        ``simulate_performance`` (T5 hook, same protocol and default
        ``None`` = bit-identical greedy path)."""
        A_pv, E_bat = float(x[0]), float(x[1])
        load = np.asarray(load, dtype=float)
        perf = self.simulate_performance(
            x,
            weather,
            load,
            year=year,
            pv_power_override=pv_power_override,
            dispatch_policy=dispatch_policy,
        )
        hours = np.asarray(weather.get("hour", np.zeros(len(load))), dtype=int)

        pv_cost = self.pv.calculate_costs(A_pv)
        # ── ALTERNATIVE / legacy economics scope (P6-5) ───────────────
        # Capital/OM/payback below use a single-lifetime CRF and the hard-coded
        # ``maintenance`` above.  Informational ONLY — the authoritative LCOE /
        # annualized capital come from ``sweep._compute_lcoe`` /
        # ``sweep._annualized_capital`` (per-component depreciation years,
        # ``opex.maintenance_pct``).  Keep the two in sync, never read both.
        bat_cost = self.battery.calculate_costs(E_bat)
        capital_cost = pv_cost["capital_cost"] + bat_cost["capital_cost"]
        annual_om = capital_cost * self.maintenance

        # G12 (Wave 1): month labels for the demand charge (one integer
        # 1-12 per timestep).  Read from weather["month"]; absent labels
        # stay None, which Tariff.annual_cost accepts silently while the
        # charge is off and rejects (fail fast) while it is active.
        months = weather.get("month")
        tcost = self.tariff.annual_cost(
            perf["grid_import"], perf["grid_export"], hours, dt=dt, months=months
        )
        net_grid_cost = tcost["net_grid_cost"]

        # Baseline: same load served entirely from grid (no PV/battery).
        baseline_cost = float(np.sum(load * self.tariff.price_array(hours) * dt))

        annual_savings = baseline_cost - net_grid_cost
        payback = (capital_cost / annual_savings) if annual_savings > 0 else float("inf")

        annual_load = float(np.sum(load))
        # NOTE: LCOE is intentionally NOT computed here — it is computed
        # centrally by ``sweep._compute_lcoe`` (per-component CRF depreciation
        # years) so that the sweep and engine code paths share one definition.
        # A single-lifetime CRF here would silently disagree with that.

        # P6-6: renamed TLPS -> grid_dependency_pct.  The metric is the share
        # of hours with a grid purchase (mean(hour | grid_import>0) x 100),
        # NOT the classical energy-weighted LPSP — a PFAL draws power almost
        # every hour, so this is grid dependency, not "loss of power supply".
        grid_dependency_pct = float(np.mean(perf["grid_import"] > 0.0)) * 100.0
        # Classical energy-weighted unmet-load share (LPSP), informational.
        lpsp_pct = float(np.sum(perf["power_deficit"])) / max(float(np.sum(load)), 1e-9) * 100.0

        # P1-2: PV self-consumption share — direct PV-to-load fraction of
        # total generation (same formula as engine.py's summary, so sweep
        # CSV and evaluate summary.csv column values agree).
        pv_self_consumed = float(np.sum(np.minimum(perf["pv_power"], perf["load"])))
        pv_self_consumption_rate = pv_self_consumed / max(float(np.sum(perf["pv_power"])), 1e-6)

        # P4-15: battery replacement economics.  Equivalent life in years from
        # cycle_life vs actual cycling; if it falls short of the system lifetime
        # a mid-life replacement is due.  Exposed as INFORMATIONAL metrics —
        # the authoritative LCOE path (sweep/engine) should fold replacement in
        # via battery_amort_years = min(capital.depreciation_years, life_years)
        # inside ``sweep._annualized_capital`` (NOT as an additive cost here,
        # which would double count against the existing per-component CRF).
        annual_cycles = float(perf["battery_cycles"])
        battery_life_years = (
            self.battery.cycle_life / annual_cycles if annual_cycles > 0.0 else float(self.lifetime)
        )
        battery_replacement_annual = 0.0
        if np.isfinite(battery_life_years) and battery_life_years < self.lifetime:
            n_extra = int(np.ceil(self.lifetime / battery_life_years)) - 1
            pv_extra = bat_cost["capital_cost"] * sum(
                (1.0 + self.interest_rate) ** (-(k * battery_life_years))
                for k in range(1, n_extra + 1)
            )
            if abs(self.interest_rate) > 1e-12:
                crf_life = (
                    self.interest_rate
                    * (1 + self.interest_rate) ** self.lifetime
                    / ((1 + self.interest_rate) ** self.lifetime - 1)
                )
            else:
                crf_life = 1.0 / self.lifetime
            battery_replacement_annual = pv_extra * crf_life

        # ── G12 (Wave 1) bookkeeping ───────────────────────────────────────
        # New keys appear ONLY while the corresponding tariff feature is
        # active; with both off (the defaults) the dict below is the exact
        # legacy key set and every value is bit-identical.  The demand
        # charge itself already sits inside net_grid_cost (annual_grid_cost)
        # via Tariff.annual_cost, so annual_savings / payback_period and the
        # export credit (curtailment removes the capped kWh from the priced
        # grid_export) inherit both features with no further edits.
        extras: Dict[str, float] = {}
        if "pv_curtailed" in perf:
            extras["pv_curtailed_kwh"] = float(np.sum(perf["pv_curtailed"]))
        _rate = self.tariff.demand_charge_per_kw
        if _rate is not None and _rate != 0.0:
            extras["annual_demand_charge"] = float(tcost["demand_charge"])

        return {
            "grid_dependency_pct": grid_dependency_pct,  # P6-6
            "tlps": grid_dependency_pct,  # backward-compat alias
            "lpsp_pct": lpsp_pct,  # P6-6 energy-weighted LPSP
            "pv_self_consumption_rate": pv_self_consumption_rate,  # P1-2
            "battery_life_years": battery_life_years,  # P4-15
            "battery_replacement_annual": battery_replacement_annual,  # P4-15
            "capital_cost": capital_cost,
            "annual_om": annual_om,
            "annual_grid_cost": net_grid_cost,
            "annual_savings": annual_savings,
            "payback_period": payback,
            "annual_pv_generation": float(np.sum(perf["pv_power"])),
            "annual_grid_import": float(np.sum(perf["grid_import"])),
            "annual_grid_export": float(np.sum(perf["grid_export"])),
            "annual_load": annual_load,
            "battery_cycles": perf["battery_cycles"],
            "peak_power_kwp": pv_cost["peak_power_kwp"],
            **extras,
        }
