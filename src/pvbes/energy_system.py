"""
Integrated PV-Battery-Grid energy system.

Combines the PV single-diode model, the battery dispatch model and the TOU
tariff to evaluate a given (PV area, battery capacity) design against a building
load profile. Produces the same metrics the reused ``EnergySystem`` delivers:
LCOE, TLPS, capital cost, annual savings, payback period.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional

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
    maintenance: float = 0.01

    # ---- simulation -----------------------------------------------------
    def simulate_performance(self, x, weather: Dict[str, np.ndarray],
                              load: np.ndarray,
                              year: int = 0) -> Dict[str, np.ndarray]:
        A_pv, E_bat = float(x[0]), float(x[1])
        load = np.asarray(load, dtype=float)
        pv_power = self.pv.calculate_pv_output(weather, A_pv, year=year)
        power_balance = pv_power - load
        bat = self.battery.calculate_battery_flows(power_balance, load, E_bat)
        battery_discharge = bat["battery_discharge"]
        battery_charge = bat["battery_charge"]
        grid_import = np.maximum(0.0, load - pv_power - battery_discharge)
        grid_export = np.maximum(0.0, pv_power - battery_charge - load)
        return {
            "pv_power": pv_power,
            "battery_discharge": battery_discharge,
            "battery_charge": battery_charge,
            "battery_soc": bat["battery_soc"],
            "battery_cycles": bat["battery_cycles"],
            "grid_import": grid_import,
            "grid_export": grid_export,
            "load": load,
            "power_deficit": np.maximum(0.0, load - pv_power),
        }

    # ---- metrics --------------------------------------------------------
    def calculate_lcoe(self, capital_cost, annual_om, annual_grid_cost,
                        annual_energy) -> float:
        i = self.interest_rate
        N = max(self.lifetime, 1)
        if abs(i) < 1e-12:
            crf = 1.0 / N
        else:
            crf = i * (1 + i) ** N / ((1 + i) ** N - 1)
        annualized = crf * capital_cost + annual_om + annual_grid_cost
        if annual_energy <= 0:
            return float("inf")
        return annualized / annual_energy

    def calculate_metrics(self, x, weather: Dict[str, np.ndarray],
                          load: np.ndarray, dt: float = 1.0,
                          year: int = 0) -> Dict[str, float]:
        A_pv, E_bat = float(x[0]), float(x[1])
        load = np.asarray(load, dtype=float)
        perf = self.simulate_performance(x, weather, load, year=year)
        hours = np.asarray(weather.get("hour", np.zeros(len(load))), dtype=int)

        pv_cost = self.pv.calculate_costs(A_pv)
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
        lcoe = self.calculate_lcoe(capital_cost, annual_om, net_grid_cost, annual_load)

        tlps = float(np.mean(perf["power_deficit"] > 0.0)) * 100.0

        return {
            "lcoe": lcoe,
            "tlps": tlps,
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
