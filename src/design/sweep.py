"""
Design sweeper — enumerates the (PV area × battery capacity) search space and
evaluates each configuration with the PVBES energy system, returning the
LCOE-optimal design plus the full enumeration table.
"""

from typing import Dict, Optional

import numpy as np
import pandas as pd

from ..pvbes.pv import PVSystem
from ..pvbes.battery import BatterySystem
from ..pvbes.grid import Tariff
from ..pvbes.energy_system import EnergySystem
from .project import DesignProject

__all__ = ["sweep_design"]


def _build_energy_system(project: DesignProject) -> EnergySystem:
    pv = PVSystem(
        eta_pv=project.pv.eta_pv, area_to_power=project.pv.area_to_power,
        N_s=project.pv.N_s, I_sc_stc=project.pv.I_sc_stc,
        V_oc_stc=project.pv.V_oc_stc, I_mp_stc=project.pv.I_mp_stc,
        V_mp_stc=project.pv.V_mp_stc, alpha_sc=project.pv.alpha_sc,
        beta_voc=project.pv.beta_voc, NOCT=project.pv.NOCT,
        eta_inv=project.pv.eta_inv, C_pv=project.pv.C_pv,
        degradation=project.pv.degradation,
    )
    battery = BatterySystem(
        c_energy=project.battery.c_energy, c_rate=project.battery.c_rate,
        eta_ch=project.battery.eta_ch, eta_dis=project.battery.eta_dis,
        soc_min=project.battery.soc_min, soc_max=project.battery.soc_max,
        cycle_life=project.battery.cycle_life, maintenance=project.battery.maintenance,
    )
    tariff = Tariff(
        peak_price=project.tariff.peak_price, normal_price=project.tariff.normal_price,
        valley_price=project.tariff.valley_price, export_price=project.tariff.export_price,
        peak_hours=list(project.tariff.peak_hours),
        valley_hours=list(project.tariff.valley_hours),
    )
    return EnergySystem(pv=pv, battery=battery, tariff=tariff)


def sweep_design(project: DesignProject, load, weather: Dict,
                 tlps_max: float = 100.0,
                 require_profit: bool = True) -> Dict:
    es = _build_energy_system(project)
    sp = project.space
    pv_areas = np.arange(sp.pv_area_range[0], sp.pv_area_range[1] + 1e-9, sp.pv_area_step)
    bats = np.arange(sp.battery_range[0], sp.battery_range[1] + 1e-9, sp.battery_step)

    rows = []
    best = None
    for A_pv in pv_areas:
        for E_bat in bats:
            m = es.calculate_metrics([A_pv, E_bat], weather, load)
            feasible = (m["tlps"] <= tlps_max) and (not require_profit or m["annual_savings"] > 0)
            rows.append({
                "pv_area_m2": A_pv, "battery_kwh": E_bat,
                "lcoe": m["lcoe"], "tlps": m["tlps"],
                "capital_cost": m["capital_cost"],
                "annual_savings": m["annual_savings"],
                "payback_period": m["payback_period"],
                "annual_pv_generation": m["annual_pv_generation"],
                "annual_grid_import": m["annual_grid_import"],
                "peak_power_kwp": m["peak_power_kwp"],
                "feasible": feasible,
            })
            if feasible:
                if best is None or m["lcoe"] < best["metrics"]["lcoe"]:
                    best = {"pv_area_m2": A_pv, "battery_kwh": E_bat, "metrics": m}

    results = pd.DataFrame(rows)
    return {"results": results, "best": best, "energy_system": es}
