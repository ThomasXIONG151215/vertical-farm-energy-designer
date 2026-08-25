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
"""

from dataclasses import dataclass, field
from typing import Dict

import numpy as np

from .pv import PVSystem
from .battery import BatterySystem
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
        self, x, weather: Dict[str, np.ndarray], load: np.ndarray, year: int = 0
    ) -> Dict[str, np.ndarray]:
        A_pv, E_bat = float(x[0]), float(x[1])
        load = np.asarray(load, dtype=float)
        pv_power = self.pv.calculate_pv_output(weather, A_pv, year=year)
        power_balance = pv_power - load
        bat = self.battery.calculate_battery_flows(power_balance, load, E_bat)
        battery_discharge = np.array(bat["battery_discharge"])
        battery_charge = np.array(bat["battery_charge"])
        grid_import = np.maximum(0.0, load - pv_power - battery_discharge)
        grid_export = np.maximum(0.0, pv_power - battery_charge - load)
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
        return {
            "pv_power": pv_power,
            "battery_discharge": battery_discharge,
            "battery_charge": battery_charge,
            "battery_soc": bat["battery_soc"],
            "battery_cycles": bat["battery_cycles"],
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

    # ---- metrics --------------------------------------------------------
    def calculate_metrics(
        self, x, weather: Dict[str, np.ndarray], load: np.ndarray, dt: float = 1.0, year: int = 0
    ) -> Dict[str, float]:
        A_pv, E_bat = float(x[0]), float(x[1])
        load = np.asarray(load, dtype=float)
        perf = self.simulate_performance(x, weather, load, year=year)
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

        tcost = self.tariff.annual_cost(perf["grid_import"], perf["grid_export"], hours, dt=dt)
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

        return {
            "grid_dependency_pct": grid_dependency_pct,  # P6-6
            "tlps": grid_dependency_pct,  # backward-compat alias
            "lpsp_pct": lpsp_pct,  # P6-6 energy-weighted LPSP
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
        }
