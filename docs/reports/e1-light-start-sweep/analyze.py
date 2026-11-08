"""E-1 analysis: grid-cost / LCOE / load curves vs light_start_hour.

Answers acceptance items (a) grid-cost curve, (b) LCOE consistency,
(c) annual load drift, (e) PV-capacity interaction, from e1_results.csv
(Shanghai TOU primary) with the flat-tariff arm as comparison.
"""
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parent
tou = pd.read_csv(OUT / "e1_results.csv")
flat = pd.read_csv(OUT / "e1_results_flat_tariff.csv")

pd.set_option("display.width", 200)
pd.set_option("display.max_rows", 100)

# sanity: load depends only on hour (identical across pv/battery for same hour)
for tag, df in [("TOU", tou), ("flat", flat)]:
    spread = df.groupby("light_start_hour")["annual_load_kwh"].nunique()
    assert (spread == 1).all(), f"[{tag}] load varies within an hour group"
print("sanity OK: annual_load_kwh is unique per light_start_hour in both arms\n")

# ---- per-hour table (building physics identical across pv/bat combos) ----
hourly = tou.groupby("light_start_hour").agg(
    load_kwh=("annual_load_kwh", "first"),
    biomass_kg=("biomass_kg", "first"),
    kwh_per_kg=("kwh_per_kg_fresh", "first"),
).reset_index()

def slice_cfg(df, pv, bat):
    return df[(df.pv_area == pv) & (df.battery_kwh == bat)][
        ["light_start_hour", "annual_grid_cost", "lcoe", "cost_per_kg_fresh",
         "annual_pv_generation", "grid_independence_pct"]
    ].sort_values("light_start_hour")

for pv, bat in [(0, 0), (40, 0), (80, 0), (80, 10)]:
    s = slice_cfg(tou, pv, bat).set_index("light_start_hour")
    hourly[f"grid_pv{pv}_b{bat}"] = s["annual_grid_cost"]
    hourly[f"lcoe_pv{pv}_b{bat}"] = s["lcoe"]

# ---- (a) grid cost curve, pv=0 bat=0 (pure tariff effect) ----
g = hourly.set_index("light_start_hour")
base_hour = 6
base_cost = g.loc[base_hour, "grid_pv0_b0"]
best_hour = g["grid_pv0_b0"].idxmin()
worst_hour = g["grid_pv0_b0"].idxmax()
print("=== (a) annual_grid_cost (CNY/yr), pv=0 battery=0, Shanghai TOU ===")
for h in range(24):
    star = " <-baseline" if h == base_hour else (" <-BEST" if h == best_hour else (" <-WORST" if h == worst_hour else ""))
    print(f"  hour {h:2d}: {g.loc[h, 'grid_pv0_b0']:10.1f}{star}")
print(f"\nbest  hour={best_hour}: {g.loc[best_hour,'grid_pv0_b0']:.1f} CNY/yr")
print(f"worst hour={worst_hour}: {g.loc[worst_hour,'grid_pv0_b0']:.1f} CNY/yr")
print(f"baseline hour=6: {base_cost:.1f} CNY/yr")
print(f"savings best vs baseline: {base_cost - g.loc[best_hour,'grid_pv0_b0']:.1f} CNY/yr "
      f"({100*(base_cost - g.loc[best_hour,'grid_pv0_b0'])/base_cost:.1f}%)")
print(f"savings worst vs baseline: {base_cost - g.loc[worst_hour,'grid_pv0_b0']:.1f} CNY/yr "
      f"({100*(base_cost - g.loc[worst_hour,'grid_pv0_b0'])/base_cost:.1f}%)")

# same at pv=80
for pv, bat in [(40, 0), (80, 0), (80, 10)]:
    col = f"grid_pv{pv}_b{bat}"
    bh = g[col].idxmin()
    print(f"[pv={pv} bat={bat}] best hour={bh} cost={g.loc[bh,col]:.1f}; "
          f"hour6={g.loc[6,col]:.1f}; worst hour={g[col].idxmax()} "
          f"{g[col].max():.1f}; save vs h6: {g.loc[6,col]-g.loc[bh,col]:.1f} CNY/yr "
          f"({100*(g.loc[6,col]-g.loc[bh,col])/g.loc[6,col]:.1f}%)")

# ---- (b) LCOE consistency ----
print("\n=== (b) LCOE (CNY/kWh) vs hour ===")
for pv, bat in [(0, 0), (80, 0), (80, 10)]:
    col = f"lcoe_pv{pv}_b{bat}"
    bh = g[col].idxmin()
    print(f"[pv={pv} bat={bat}] LCOE best hour={bh} ({g.loc[bh,col]:.3f}); "
          f"hour6={g.loc[6,col]:.3f}; worst={g[col].idxmax()} ({g[col].max():.3f}); "
          f"delta best vs h6: {g.loc[6,col]-g.loc[bh,col]:+.3f} "
          f"({100*(g.loc[6,col]-g.loc[bh,col])/g.loc[6,col]:.1f}%)")

# ---- (c) annual load drift ----
print("\n=== (c) annual_load_kwh vs hour (TOU arm; identical in flat arm) ===")
lmin, lmax = hourly["load_kwh"].min(), hourly["load_kwh"].max()
l6 = hourly.loc[hourly.light_start_hour == 6, "load_kwh"].iloc[0]
print(f"min={lmin:.0f} kWh (hour {hourly.loc[hourly.load_kwh.idxmin(),'light_start_hour']}), "
      f"max={lmax:.0f} kWh (hour {hourly.loc[hourly.load_kwh.idxmax(),'light_start_hour']}), "
      f"baseline h6={l6:.0f} kWh")
print(f"range: {(lmax-lmin)/l6*100:.2f}% of baseline; vs baseline: "
      f"{(lmin-l6)/l6*100:+.2f}% .. {(lmax-l6)/l6*100:+.2f}%")
bmin, bmax = hourly["biomass_kg"].min(), hourly["biomass_kg"].max()
print(f"biomass: min={bmin:.1f} kg, max={bmax:.1f} kg "
      f"({(bmax-bmin)/bmax*100:.2f}% spread); kwh/kg fresh "
      f"{hourly['kwh_per_kg'].min():.2f}..{hourly['kwh_per_kg'].max():.2f}")

# ---- (e) PV interaction: best hour per pv level ----
print("\n=== (e) best hour by pv_area (battery=0 and battery=10) ===")
for bat in (0, 10):
    for pv in (0, 40, 80):
        s = tou[(tou.pv_area == pv) & (tou.battery_kwh == bat)]
        b = s.loc[s.annual_grid_cost.idxmin()]
        bl = s.loc[s.lcoe.idxmin()]
        print(f"bat={bat} pv={pv}: grid-cost best hour={int(b.light_start_hour)} "
              f"({b.annual_grid_cost:.1f} CNY); LCOE best hour={int(bl.light_start_hour)} "
              f"({bl.lcoe:.3f})")

# ---- flat-tariff comparison: physics-only effect ----
print("\n=== flat tariff (USD, 0.10/kWh) arm: grid cost vs hour, pv=0 bat=0 ===")
sf = flat[(flat.pv_area == 0) & (flat.battery_kwh == 0)].sort_values("light_start_hour")
sfar = sf.set_index("light_start_hour")["annual_grid_cost"]
print(f"best hour={sfar.idxmin()} ({sfar.min():.1f} USD), worst={sfar.idxmax()} "
      f"({sfar.max():.1f} USD), h6={sfar.loc[6]:.1f}, spread={100*(sfar.max()-sfar.min())/sfar.loc[6]:.2f}%")

hourly.to_csv(OUT / "e1_hourly_summary.csv", index=False)
print("\nsaved -> e1_hourly_summary.csv")
