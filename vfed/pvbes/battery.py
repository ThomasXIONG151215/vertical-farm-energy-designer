"""
Battery energy storage model (Zhao et al. 2024 parametric formulation).

Pure-Python, vectorised timestep loop. Power balance ``pv - load`` (kW) is
balanced by the battery within C-rate and SOC limits; the residual is exported
to / imported from the grid by ``EnergySystem``.

    charge   : surplus <= P_charge_max, soc rises by P*eta_ch*dt/E_bat
    discharge: deficit  <= P_discharge_max*eta_dis, soc falls accordingly

P1-2: with ``allow_grid_charging=True`` the battery additionally buys grid
power in valley-price hours (price == tariff minimum) to top up SOC, so the
stored energy can later be discharged into higher-priced hours (TOU
arbitrage).  Simple greedy, no optimisation: arbitrage is enabled only when
the tariff's peak price exceeds the round-trip breakeven
    ``valley / (eta_ch * eta_dis)`` — flat tariffs never qualify, so the default
    ``False`` (PV charging only) dispatch path is bitwise unchanged.

P2-4: usable capacity fades linearly with accumulated equivalent cycles
(``soh_eol`` = capacity fraction at ``cycle_life`` cycles, default 0.80).
The fade applies inside the dispatch loop (C-rate limit, SOC headroom, SOC
update denominators); ``battery_cycles`` keeps its nameplate-capacity
definition so replacement timing (P4-15) is unchanged.  ``soh_eol = 1.0``
disables the fade (bitwise legacy dispatch).
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np

__all__ = ["BatterySystem"]


@dataclass
class BatterySystem:
    c_energy: float = 220.0  # $/kWh
    c_rate: float = 1.0  # max C-rate (1/h)
    eta_ch: float = 0.91
    eta_dis: float = 0.91
    soc_min: float = 0.10
    soc_max: float = 0.90
    cycle_life: int = 4000  # full (dis)charge cycles to end-of-life.
    # P4-15: equivalent life years = cycle_life /
    # battery_cycles; if < system lifetime a
    # mid-life replacement is due (computed in
    # EnergySystem.calculate_metrics).
    soh_eol: float = 0.80  # P2-4: usable-capacity fraction at end of life
    # (cycle_life equivalent cycles). Linear fade per
    # equivalent cycle: k = (1 - soh_eol) / cycle_life;
    # usable capacity = E_bat * max(1 - k*cycles_so_far,
    # 1e-3). 0.80 = industry-standard EOL criterion (80%
    # of initial capacity); 1.0 disables the fade (k = 0,
    # bitwise legacy dispatch). Cycles are counted against
    # NAMEPLATE capacity (EFC convention), matching the
    # battery_cycles return; replacement year (P4-15) is
    # therefore unchanged. layerD B4: a no-fade model
    # implied 11.0 yr life vs Sandia 6.7-10 yr @ 1 cyc/d.
    self_discharge: float = 0.0  # per hour (fraction)
    maintenance: float = 0.01  # LEGACY (P4-15/P5): config field removed,
    # never read anywhere; kept for interface
    # stability only.
    allow_grid_charging: bool = False  # P1-2: TOU arbitrage — buy grid power
    # in valley-price hours (price == tariff min) to displace peak-price
    # imports later.  Gated on peak > valley/(eta_ch*eta_dis) (round-trip
    # breakeven); flat tariffs are a no-op.  Default False = legacy
    # PV-charging-only dispatch, bitwise unchanged.

    def calculate_battery_flows(
        self,
        power_balance: np.ndarray,  # pv - load (kW)
        load_profile: np.ndarray,  # kW (used only for shape)
        E_bat: float,
        dt: float = 1.0,
        soc0: float = 0.5,
        hourly_prices: Optional[List[float]] = None,  # P1-2: tariff table
        hours: Optional[np.ndarray] = None,  # hour-of-day per timestep
    ) -> Dict[str, np.ndarray]:
        n = len(power_balance)

        # ── P1-2: TOU grid-charging setup (fail-fast, no silent fallback) ──
        if self.allow_grid_charging and (hourly_prices is None or hours is None):
            raise ValueError(
                "battery.allow_grid_charging=True requires the tariff "
                "hourly_prices and the hour-of-day array; EnergySystem "
                "supplies both automatically."
            )
        grid_charged = np.zeros(n)  # kW bought from the grid for charging
        grid_charging_on = False
        valley_set: frozenset = frozenset()
        n_p = 0
        if self.allow_grid_charging and E_bat > 0 and n > 0:
            prices = np.asarray(hourly_prices, dtype=float)
            if prices.size == 0:
                raise ValueError("hourly_prices must be non-empty when allow_grid_charging=True")
            if len(hours) != n:
                raise ValueError(
                    f"hours length {len(hours)} != power_balance length {n} "
                    "(allow_grid_charging=True)"
                )
            n_p = int(prices.size)
            p_min = float(prices.min())
            p_max = float(prices.max())
            # Arbitrage pays only if some hour repays the round-trip loss:
            # 1 kWh bought at valley returns eta_ch*eta_dis kWh, so it must
            # displace a price > valley/(eta_ch*eta_dis).  A flat tariff
            # (p_max == p_min) never qualifies -> exact no-op.
            if p_max > p_min / max(self.eta_ch * self.eta_dis, 1e-9) + 1e-12:
                grid_charging_on = True
                valley_set = frozenset(h for h in range(n_p) if float(prices[h]) <= p_min + 1e-12)

        battery_power = np.zeros(n)  # signed: + discharge, - charge
        battery_discharge = np.zeros(n)  # kW delivered to load
        battery_charge = np.zeros(n)  # kW into battery
        battery_soc = np.zeros(n)
        soc = float(soc0)
        total_charged = 0.0
        total_discharged = 0.0
        # ── P2-4: linear SOH fade setup ──────────────────────────────────
        # Usable capacity fades with accumulated equivalent cycles: SOH =
        # 1 - k * cycles_now, k = (1 - soh_eol) / cycle_life.  soh_eol = 1.0
        # -> k = 0 -> E_now == E_bat for every step (bitwise legacy
        # dispatch).  cycles_now counts storage-side throughput against
        # NAMEPLATE capacity, i.e. exactly the running sum behind the
        # battery_cycles return.
        soh_k = (1.0 - self.soh_eol) / max(int(self.cycle_life), 1)
        cycles_now = 0.0
        E_now = E_bat
        for i in range(n):
            net = power_balance[i]
            soc *= 1.0 - self.self_discharge * dt
            if E_bat <= 0:
                battery_soc[i] = 0.0
                continue
            p_charge_max = min(self.c_rate * E_now, (self.soc_max - soc) * E_now / dt)
            p_discharge_max = (
                min(self.c_rate * E_now, (soc - self.soc_min) * E_now / dt) * self.eta_dis
            )
            if net >= 0:  # surplus -> charge
                ch = min(net, max(0.0, p_charge_max))
                soc += ch * self.eta_ch * dt / E_now
                battery_charge[i] = ch
                battery_power[i] = -ch
                total_charged += ch * dt
            else:  # deficit -> discharge
                deficit = -net
                dch = min(deficit, max(0.0, p_discharge_max))
                soc -= dch * dt / (self.eta_dis * E_now)
                battery_discharge[i] = dch
                battery_power[i] = dch
                total_discharged += dch * dt
            soc = min(self.soc_max, max(self.soc_min, soc))
            battery_soc[i] = soc

            # ── P1-2: valley-hour grid top-up (after the normal PV step) ──
            # Greedy: fill remaining headroom at the valley price; the extra
            # SOC is discharged by the existing deficit path into (on
            # average) higher-priced hours.  Skipped entirely unless the
            # tariff passed the round-trip breakeven check above.
            if grid_charging_on and int(hours[i]) % n_p in valley_set:
                headroom = min(self.c_rate * E_now, (self.soc_max - soc) * E_now / dt)
                g = max(0.0, headroom)
                if g > 0.0:
                    soc += g * self.eta_ch * dt / E_now
                    battery_charge[i] += g
                    grid_charged[i] = g
                    total_charged += g * dt
                    soc = min(self.soc_max, max(self.soc_min, soc))
                    battery_soc[i] = soc

            # ── P2-4: age the cell by this step's throughput (nameplate
            # EFC), then refresh the usable capacity for the next step.
            cycles_now += (
                battery_charge[i] * self.eta_ch
                + battery_discharge[i] / max(self.eta_dis, 0.01)
            ) * dt / (2.0 * E_bat)
            E_now = E_bat * max(1.0 - soh_k * cycles_now, 1e-3)

        # ── Year-end periodic reconciliation (P4-18) ──────────────────────
        # Dispatch starts at soc0 but is not guaranteed to end there, leaving
        # E_now*(soc_end - soc0) of stored energy unaccounted in the annual
        # balance.  P2-4: the stored energy at year end sits in the FADED
        # capacity E_now (== E_bat when the fade is off), so the correction
        # must use E_now, not nameplate, to keep the annual identity exact.
        # Restore the periodic SOC boundary and report the electrical energy
        # that must cross the grid interface so that
        # pv + import + discharge = load + charge + export closes exactly.
        # EnergySystem applies it to both the battery and grid sides at the
        # last timestep (signed: + import / top-up, - export / dump).
        soc_end = float(soc)
        soc_target = min(self.soc_max, max(self.soc_min, float(soc0)))
        recon_grid_kwh = 0.0
        if E_bat > 0 and n > 0:
            need_stored = E_now * (soc_target - soc_end)
            if need_stored > 0.0:
                recon_grid_kwh = need_stored / self.eta_ch  # grid top-up (import)
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
            # P1-2: grid power bought for valley charging (kW).  Zero array
            # unless allow_grid_charging=True and the tariff qualifies;
            # EnergySystem routes it into grid_import (never against export).
            "grid_charged": grid_charged,
            "total_charged": total_charged,
            "total_discharged": total_discharged,
            "battery_cycles": (
                total_charged * self.eta_ch + total_discharged / max(self.eta_dis, 0.01)
            )
            / (2.0 * E_bat)
            if E_bat > 0
            else 0.0,
            "soc_end": soc_end,
            "recon_grid_kwh": recon_grid_kwh,
        }

    def calculate_costs(self, E_bat: float) -> Dict[str, float]:
        return {
            "energy_capacity_kwh": E_bat,
            "capital_cost": E_bat * self.c_energy,
        }
