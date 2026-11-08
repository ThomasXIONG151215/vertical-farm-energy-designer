"""E-4: TOU-aware dispatch policy vs built-in greedy dispatch.

Compares three dispatch arms against the built-in greedy baseline on the
identical load/weather series (preset_609, PV 100 m2, battery 50 kWh,
Shanghai TOU tariff + assumed demand charge):

  1. greedy_builtin        dispatch_policy=None (anchor: must equal the
                           engine_report quick-eval summary number)
  2. greedy_policy_replica a policy that reproduces greedy behaviour via
                           the dispatch_policy protocol (sanity check that
                           the policy hook is faithful)
  3. valley_tou            greedy + valley-hour (22:00-06:00) grid top-up
                           charging at the maximum terminal-allowed rate
  4. valley_tou_reserve    valley_tou + SOC never discharged below 30%
                           + pre-peak (h7/h17) grid top-up to SOC>=30%

Outputs e4_results.csv (arms x metrics) next to this script and prints a
summary table.  Re-runnable offline: ``python docs/reports/e4-dispatch-policy/run_e4.py``
from anywhere inside the repo (weather cache is resolved absolutely).
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from vfed.design.engine import DesignEngine  # noqa: E402
from vfed.design.fx import USD_C_ENERGY, USD_C_PV, resolve_unit_price  # noqa: E402
from vfed.design.presets import preset_609  # noqa: E402
from vfed.pvbes.battery import BatterySystem  # noqa: E402
from vfed.pvbes.energy_system import EnergySystem  # noqa: E402
from vfed.pvbes.grid import Tariff  # noqa: E402
from vfed.pvbes.pv import PVSystem  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent
CACHE_DIR = str(ROOT / "weather_cache")

# ── Experiment assumptions (documented in report.md) ──────────────────
# Shanghai TOU (vfed.pvbes.tariff_db 'Shanghai', CNY/kWh):
#   valley 0.30 h22-05, flat 0.60 h06-07/11-17/21, peak 1.00 h08-10/18-20.
SHANGHAI_HOURLY = (
    [0.30] * 6          # h00-05 valley
    + [0.60, 0.60]      # h06-07 flat
    + [1.00] * 3        # h08-10 peak
    + [0.60] * 7        # h11-17 flat
    + [1.00] * 3        # h18-20 peak
    + [0.60]            # h21 flat
    + [0.30, 0.30]      # h22-23 valley
)
EXPORT_PRICE_CNY = 0.4155
# Assumed representative two-part-tariff demand charge (CNY/kW-month).
# The engine has no Shanghai demand rate built in; 40 is a stated
# assumption for this experiment, not a verified tariff parameter.
DEMAND_CNY_PER_KW_MONTH = 40.0

VALLEY_HOURS = {0, 1, 2, 3, 4, 5, 22, 23}
PRE_PEAK_HOURS = {7, 17}  # flat hours immediately before the peak blocks
RESERVE_FRAC = 0.30

# preset_609 BatteryConfig defaults (kept as constants so the policies
# stay plain functions; the sim itself reads them from the config).
SOC_MAX = 0.90
ETA_CH = 0.91
ETA_DIS = 0.91

X = [100.0, 50.0]  # [A_pv_m2, E_bat_kwh] — same as the golden PVBES case


# ── Policies (protocol: obs dict -> (charge_kw, discharge_kw)) ────────
def greedy_replica(obs):
    pv, load = obs["pv_w"], obs["load_w"]
    if pv > load:
        return (pv - load, 0.0)
    return (0.0, load - pv)


def valley_tou(obs):
    h = obs["hour"]
    pv, load = obs["pv_w"], obs["load_w"]
    soc, cap = obs["soc_kwh"], obs["capacity_kwh"]
    surplus = max(0.0, pv - load)
    deficit = max(0.0, load - pv)
    if h in VALLEY_HOURS:
        fill = max(0.0, SOC_MAX * cap - soc)  # kW for dt = 1 h
        return (surplus + fill, 0.0)
    if surplus > 0.0:
        return (surplus, 0.0)
    return (0.0, deficit)


def valley_tou_reserve(obs):
    h = obs["hour"]
    pv, load = obs["pv_w"], obs["load_w"]
    soc, cap = obs["soc_kwh"], obs["capacity_kwh"]
    surplus = max(0.0, pv - load)
    deficit = max(0.0, load - pv)
    if h in VALLEY_HOURS:
        return valley_tou(obs)
    if h in PRE_PEAK_HOURS and soc < RESERVE_FRAC * cap:
        top_up = (RESERVE_FRAC * cap - soc) / ETA_CH  # kW for dt = 1 h
        return (surplus + top_up, 0.0)
    if surplus > 0.0:
        return (surplus, 0.0)
    # discharge floor: never spend the 30% reserve
    dch = min(deficit, max(0.0, soc - RESERVE_FRAC * cap) * ETA_DIS)
    return (0.0, dch)


# ── Experiment ─────────────────────────────────────────────────────────
def build_project():
    p = preset_609()
    p.pv_area_m2 = X[0]
    p.battery_kwh = X[1]
    p.currency = "CNY"
    p.tariff.hourly_prices = list(SHANGHAI_HOURLY)
    p.tariff.export_price = EXPORT_PRICE_CNY
    p.tariff.demand_charge_per_kw = DEMAND_CNY_PER_KW_MONTH
    return p


def build_es(p):
    """Mirror the engine_report quick-eval construction verbatim."""
    pv_sys = PVSystem(
        module=p.pv.module,
        eta_pv=p.pv.eta_pv,
        area_to_power=p.pv.area_to_power,
        N_s=p.pv.N_s,
        I_sc_stc=p.pv.I_sc_stc,
        V_oc_stc=p.pv.V_oc_stc,
        I_mp_stc=p.pv.I_mp_stc,
        V_mp_stc=p.pv.V_mp_stc,
        alpha_sc=p.pv.alpha_sc,
        beta_voc=p.pv.beta_voc,
        gamma_pmp=p.pv.gamma_pmp,
        NOCT=p.pv.NOCT,
        eta_inv=p.pv.eta_inv,
        C_pv=resolve_unit_price(p.pv.C_pv, USD_C_PV, p.currency, p.exchange_rate),
        degradation=p.pv.degradation,
        eta_system=p.pv.eta_system,
    )
    bat_sys = BatterySystem(
        c_energy=resolve_unit_price(
            p.battery.c_energy, USD_C_ENERGY, p.currency, p.exchange_rate
        ),
        c_rate=p.battery.c_rate,
        eta_ch=p.battery.eta_ch,
        eta_dis=p.battery.eta_dis,
        soc_min=p.battery.soc_min,
        soc_max=p.battery.soc_max,
        cycle_life=p.battery.cycle_life,
        soh_eol=p.battery.soh_eol,
        allow_grid_charging=p.battery.allow_grid_charging,
        power_kw=p.battery.power_kw,
        chemistry=p.battery.chemistry,
    )
    tariff = Tariff(
        hourly_prices=p.tariff.hourly_prices,
        export_price=p.tariff.export_price,
        export_limit_kw=p.tariff.export_limit_kw,
        demand_charge_per_kw=p.tariff.demand_charge_per_kw,
    )
    return EnergySystem(
        pv=pv_sys, battery=bat_sys, tariff=tariff, interest_rate=p.interest_rate
    )


def run_arm(es, tariff, weather, load, policy):
    perf = es.simulate_performance(
        X, weather, load, year=es.lifetime // 2, dispatch_policy=policy
    )
    hours = np.asarray(weather["hour"], dtype=int)
    months = np.asarray(weather["month"], dtype=int)
    tcost = tariff.annual_cost(
        perf["grid_import"], perf["grid_export"], hours, months=months, dt=1.0
    )
    metrics = es.calculate_metrics(
        X, weather, load, year=es.lifetime // 2, dispatch_policy=policy
    )

    pv = np.asarray(perf["pv_power"], dtype=float)
    ld = np.asarray(perf["load"], dtype=float)
    ch = np.asarray(perf["battery_charge"], dtype=float)
    dch = np.asarray(perf["battery_discharge"], dtype=float)
    soc = np.asarray(perf["battery_soc"], dtype=float)
    gi = np.asarray(perf["grid_import"], dtype=float)

    # grid-bought charging share (same accounting identity the engine uses)
    surplus = np.maximum(0.0, pv - ld)
    grid_charged = np.maximum(0.0, ch - np.minimum(ch, surplus))

    peak_per_month = np.array([gi[months == m].max() for m in range(1, 13)])

    return {
        "annual_grid_cost_net_cny": round(float(tcost["net_grid_cost"]), 2),
        "import_cost_cny": round(float(tcost["grid_import_cost"]), 2),
        "export_credit_cny": round(float(tcost["grid_export_credit"]), 2),
        "demand_charge_cny": round(float(tcost.get("demand_charge", 0.0)), 2),
        "grid_import_kwh": round(float(np.sum(gi)), 1),
        "grid_export_kwh": round(float(np.sum(perf["grid_export"])), 1),
        "pv_generation_kwh": round(float(np.sum(pv)), 1),
        "pv_self_consumption_pct": round(
            float(np.sum(np.minimum(pv, ld))) / max(float(np.sum(pv)), 1e-6) * 100.0, 2
        ),
        "battery_cycles": round(float(perf["battery_cycles"]), 2),
        "battery_charge_kwh": round(float(np.sum(ch)), 1),
        "battery_discharge_kwh": round(float(np.sum(dch)), 1),
        "grid_charged_kwh": round(float(np.sum(grid_charged)), 1),
        "soc_min": round(float(np.min(soc)), 4),
        "soc_mean": round(float(np.mean(soc)), 4),
        "soc_max": round(float(np.max(soc)), 4),
        "monthly_peak_import_mean_kw": round(float(np.mean(peak_per_month)), 2),
        "monthly_peak_import_max_kw": round(float(np.max(peak_per_month)), 2),
        "battery_life_years": round(float(metrics["battery_life_years"]), 2),
        "battery_replacement_annual_cny": round(
            float(metrics["battery_replacement_annual"]), 2
        ),
        "_metrics_annual_grid_cost": round(float(metrics["annual_grid_cost"]), 2),
    }


def main():
    p = build_project()

    print("Running engine (offline, cached weather) ...", flush=True)
    r = DesignEngine(cache_dir=CACHE_DIR).run(p)
    weather = r["weather"]
    load = r["load"]
    anchor = r.summary["annual_grid_cost_net"]
    print(f"engine quick-eval anchor annual_grid_cost_net = {anchor} CNY")
    print(f"engine summary battery_cycles            = {r.summary['battery_cycles']}")

    es = build_es(p)

    arms = [
        ("greedy_builtin", None),
        ("greedy_policy_replica", greedy_replica),
        ("valley_tou", valley_tou),
        ("valley_tou_reserve", valley_tou_reserve),
    ]

    results = {}
    for name, pol in arms:
        print(f"simulating arm: {name} ...", flush=True)
        results[name] = run_arm(es, es.tariff, weather, load, pol)

    # acceptance check 1: greedy arm must reproduce the engine anchor
    g = results["greedy_builtin"]
    delta = abs(g["annual_grid_cost_net_cny"] - anchor)
    ok = delta <= 0.01
    print("\n=== anchor check ===")
    print(f"greedy_builtin net = {g['annual_grid_cost_net_cny']} CNY")
    print(f"engine anchor      = {anchor} CNY")
    print(f"|delta|            = {delta:.4f} -> {'PASS' if ok else 'FAIL'}")

    rep = results["greedy_policy_replica"]
    same = rep["annual_grid_cost_net_cny"] == g["annual_grid_cost_net_cny"]
    print("\n=== policy-hook fidelity check ===")
    print(
        f"greedy_policy_replica net = {rep['annual_grid_cost_net_cny']} CNY "
        f"(== greedy_builtin: {same})"
    )

    print("\n=== arm table ===")
    cols = [k for k in g if not k.startswith("_")]
    print("metric," + ",".join(results))
    for c in cols:
        print(f"{c}," + ",".join(str(results[n][c]) for n in results))

    # write CSV (wide: one row per metric, one column per arm)
    csv_path = OUT_DIR / "e4_results.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["metric"] + list(results))
        for c in cols:
            w.writerow([c] + [results[n][c] for n in results])
    print(f"\nwrote {csv_path}")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
