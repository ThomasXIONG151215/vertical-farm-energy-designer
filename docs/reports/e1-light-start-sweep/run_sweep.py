"""E-1: light-start-hour sweep on the 609 preset (Shanghai TOU tariff).

Primary run: currency=CNY, exchange_rate=7.2, tariff=TARIFF_DB["Shanghai"]
(valley 0.30 / normal 0.60 / peak 1.00 CNY/kWh, export 0.4155) — mirrors
`vfed design new --tariff Shanghai` with a CNY project.

Secondary run (kept for comparison): stock preset_609 defaults (USD, flat
0.10 USD/kWh) — isolates the physics-only effect of shifting the light
window from the tariff-price effect.

Sweeps light_start_hour 0..23 x pv_area {0,40,80} m2 x battery {0,10,20} kWh
(216 rows each). Offline: site.city="Shanghai" reads
data/weather/Shanghai_2025.csv (no network).
"""
import time
from pathlib import Path

from vfed.design.project import DesignProject
from vfed.design.presets import preset_609
from vfed.design.sweep import sweep_design
from vfed.pvbes.tariff_db import lookup_tariff

OUT = Path(__file__).resolve().parent


def project_tou() -> DesignProject:
    """preset_609 + CNY currency + Shanghai TOU tariff (CLI-equivalent)."""
    d = preset_609().to_dict()
    d["currency"] = "CNY"
    d["exchange_rate"] = 7.2
    rec = lookup_tariff("Shanghai")
    d["tariff"] = {
        "hourly_prices": list(rec["hourly_prices"]),
        "export_price": float(rec["export_price"]),
    }
    return DesignProject.from_dict(d)


def project_flat() -> DesignProject:
    """Stock preset_609 (USD, flat tariff) — comparison arm."""
    return preset_609()


RANGES = {
    "light_start_hour": [0, 23, 1],
    "pv_area": [0, 80, 40],
    "battery": [0, 20, 10],
}

for tag, factory, fname in [
    ("TOU (Shanghai, CNY)", project_tou, "e1_results.csv"),
    ("flat (stock preset, USD)", project_flat, "e1_results_flat_tariff.csv"),
]:
    p = factory()
    if tag.startswith("TOU"):
        assert p.currency == "CNY", p.currency
        assert p.tariff.hourly_prices[0] == 0.30 and p.tariff.hourly_prices[8] == 1.00
        print(f"[{tag}] currency={p.currency} fx={p.exchange_rate} "
              f"tariff h0={p.tariff.hourly_prices[0]} h8={p.tariff.hourly_prices[8]} "
              f"h12={p.tariff.hourly_prices[12]} h23={p.tariff.hourly_prices[23]} "
              f"export={p.tariff.export_price}")
    p.space.parameter_ranges = dict(RANGES)
    p.space.objective = "lcoe"

    t0 = time.time()
    out = sweep_design(p, cache_dir=None)
    elapsed = time.time() - t0

    df = out["results"]
    print(f"[{tag}] shape={df.shape} elapsed={elapsed:.1f}s")
    df.to_csv(OUT / fname, index=False)
    b = out["best"]
    print(f"[{tag}] best: hour={b['light_start_hour']} pv={b['pv_area']} "
          f"bat={b['battery_kwh']} lcoe={b['lcoe']:.4f} grid={b['annual_grid_cost']:.1f}")
    print(f"[{tag}] saved -> {OUT / fname}")
