"""
Battery energy storage model (Zhao et al. 2024 parametric formulation).

Pure-Python, vectorised timestep loop. Power balance ``pv - load`` (kW) is
balanced by the battery within C-rate and SOC limits; the residual is exported
to / imported from the grid by ``EnergySystem``.

    charge   : surplus <= P_charge_max, soc rises by P*eta_ch*dt/E_bat
    discharge: deficit  <= P_discharge_max*eta_dis, soc falls accordingly
"""

from dataclasses import dataclass
from typing import Dict

import numpy as np

__all__ = ["BatterySystem"]


@dataclass
class BatterySystem:
    c_energy: float = 220.0      # $/kWh
    c_rate: float = 1.0          # max C-rate (1/h)
    eta_ch: float = 0.91
    eta_dis: float = 0.91
    soc_min: float = 0.10
    soc_max: float = 0.90
    cycle_life: int = 4000      # full (dis)charge cycles to end-of-life.
                                # P4-15: equivalent life years = cycle_life /
                                # battery_cycles; if < system lifetime a
                                # mid-life replacement is due (computed in
                                # EnergySystem.calculate_metrics).
    self_discharge: float = 0.0   # per hour (fraction)
    maintenance: float = 0.01     # LEGACY (P4-15/P5): config field removed,
                                # never read anywhere; kept for interface
                                # stability only.

    def calculate_battery_flows(
        self,
        power_balance: np.ndarray,   # pv - load (kW)
        load_profile: np.ndarray,    # kW (used only for shape)
        E_bat: float,
        dt: float = 1.0,
        soc0: float = 0.5,
    ) -> Dict[str, np.ndarray]:
        n = len(power_balance)
        battery_power = np.zeros(n)      # signed: + discharge, - charge
        battery_discharge = np.zeros(n)  # kW delivered to load
        battery_charge = np.zeros(n)     # kW into battery
        battery_soc = np.zeros(n)
        soc = float(soc0)
        total_charged = 0.0
        total_discharged = 0.0
        for i in range(n):
            net = power_balance[i]
            soc *= (1.0 - self.self_discharge * dt)
            if E_bat <= 0:
                battery_soc[i] = 0.0
                continue
            p_charge_max = min(self.c_rate * E_bat,
                               (self.soc_max - soc) * E_bat / dt)
            p_discharge_max = min(self.c_rate * E_bat,
                                  (soc - self.soc_min) * E_bat / dt) * self.eta_dis
            if net >= 0:  # surplus -> charge
                ch = min(net, max(0.0, p_charge_max))
                soc += ch * self.eta_ch * dt / E_bat
                battery_charge[i] = ch
                battery_power[i] = -ch
                total_charged += ch * dt
            else:         # deficit -> discharge
                deficit = -net
                dch = min(deficit, max(0.0, p_discharge_max))
                soc -= dch * dt / (self.eta_dis * E_bat)
                battery_discharge[i] = dch
                battery_power[i] = dch
                total_discharged += dch * dt
            soc = min(self.soc_max, max(self.soc_min, soc))
            battery_soc[i] = soc

        # ── Year-end periodic reconciliation (P4-18) ──────────────────────
        # Dispatch starts at soc0 but is not guaranteed to end there, leaving
        # E_bat*(soc_end - soc0) of stored energy unaccounted in the annual
        # balance.  Restore the periodic SOC boundary and report the
        # electrical energy that must cross the grid interface so that
        # pv + import + discharge = load + charge + export closes exactly.
        # EnergySystem applies it to both the battery and grid sides at the
        # last timestep (signed: + import / top-up, - export / dump).
        soc_end = float(soc)
        soc_target = min(self.soc_max, max(self.soc_min, float(soc0)))
        recon_grid_kwh = 0.0
        if E_bat > 0 and n > 0:
            need_stored = E_bat * (soc_target - soc_end)
            if need_stored > 0.0:
                recon_grid_kwh = need_stored / self.eta_ch   # grid top-up (import)
                total_charged += recon_grid_kwh
            elif need_stored < 0.0:
                recon_grid_kwh = -(-need_stored) * self.eta_dis  # dump (export)
                total_discharged += -recon_grid_kwh
            battery_soc[-1] = soc_target
        return {
            "battery_power": battery_power,
            "battery_discharge": battery_discharge,
            "battery_charge": battery_charge,
            "battery_soc": battery_soc,
            "total_charged": total_charged,
            "total_discharged": total_discharged,
            "battery_cycles": (total_charged * self.eta_ch + total_discharged / max(self.eta_dis, 0.01)) / (2.0 * E_bat) if E_bat > 0 else 0.0,
            "soc_end": soc_end,
            "recon_grid_kwh": recon_grid_kwh,
        }

    def calculate_costs(self, E_bat: float) -> Dict[str, float]:
        return {
            "energy_capacity_kwh": E_bat,
            "capital_cost": E_bat * self.c_energy,
        }
