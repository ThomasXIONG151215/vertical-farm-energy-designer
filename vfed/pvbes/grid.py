"""
Electricity tariff model (hourly price table).

Maps each hour-of-day directly to a price via a 24-element array.
Replaces the old three-tier peak/normal/valley model.

G12 (Wave 1): two opt-in tariff extensions, both default-OFF so the legacy
cost path is bit-identical:

* ``export_limit_kw`` -- feed-in power cap (kW).  The cap is enforced in
  ``EnergySystem.simulate_performance`` (dispatch): hourly ``grid_export``
  is clipped to the limit and the clipped excess is curtailed (never sold,
  never reused).  ``annual_cost`` prices whatever export it is handed, so
  it carries no cap logic of its own.
* ``demand_charge_per_kw`` -- monthly peak-demand charge (currency per kW
  per month).  ``annual_cost`` bills the monthly maximum of the hourly
  grid-import power at the per-kW rate, summed over the months of the
  series (12 terms for a full year), folded into ``net_grid_cost``.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

__all__ = ["Tariff"]


@dataclass
class Tariff:
    hourly_prices: List[float] = field(default_factory=lambda: [0.10] * 24)  # index = hour-of-day
    export_price: float = 0.05  # feed-in credit (same currency)
    # ── G12 (Wave 1) ──────────────────────────────────────────────────────
    export_limit_kw: Optional[float] = None  # feed-in cap (kW); None = unlimited
    demand_charge_per_kw: Optional[float] = None  # currency/kW-month; None/0 = off

    def __post_init__(self):
        # fail fast on out-of-band economics (project.py mirrors this for YAML)
        if self.export_limit_kw is not None and self.export_limit_kw < 0:
            raise ValueError(
                f"tariff.export_limit_kw must be non-negative, got {self.export_limit_kw!r}"
            )
        if self.demand_charge_per_kw is not None and self.demand_charge_per_kw < 0:
            raise ValueError(
                f"tariff.demand_charge_per_kw must be non-negative, "
                f"got {self.demand_charge_per_kw!r}"
            )

    def price_for_hour(self, hour: int) -> float:
        h = int(hour) % 24
        if h < len(self.hourly_prices):
            return self.hourly_prices[h]
        return 0.10  # fallback

    def price_array(self, hours: np.ndarray) -> np.ndarray:
        return np.array([self.price_for_hour(h) for h in hours])

    def annual_cost(
        self,
        grid_import: np.ndarray,
        grid_export: np.ndarray,
        hours: np.ndarray,
        dt: float = 1.0,
        months: Optional[np.ndarray] = None,
    ) -> Dict[str, float]:
        """Annual grid bill: energy cost - export credit (+ demand charge).

        Demand charge (G12), billed only when ``demand_charge_per_kw`` is
        not None and not 0: for every month label present in ``months``
        (integer 1-12 per timestep; ``EnergySystem`` reads it from
        ``weather["month"]``), the monthly peak of the hourly grid-import
        POWER (kW -- the max timestep value, with no dt factor: a demand
        charge bills power, not energy) is charged at the per-kW rate; the
        annual charge is the sum over the months (12 terms for a full-year
        series).  The charge is folded into ``net_grid_cost``::

            net_grid_cost = grid_import_cost - grid_export_credit + demand_charge

        which is the same aggregate ``EnergySystem.calculate_metrics``
        reports as ``annual_grid_cost`` and engine/sweep read as their grid
        cost -- one definition everywhere, so ``annual_savings`` /
        ``payback_period`` inherit the charge automatically.  ``months`` is
        required (fail fast) while the charge is active and is never read
        when the charge is off, so legacy calls and results stay
        bit-identical.
        """
        price = self.price_array(hours)
        import_cost = float(np.sum(grid_import * price * dt))
        export_credit = float(np.sum(grid_export * self.export_price * dt))
        cost = {
            "grid_import_cost": import_cost,
            "grid_export_credit": export_credit,
            "net_grid_cost": import_cost - export_credit,
        }
        rate = self.demand_charge_per_kw
        if rate is not None and rate != 0.0:
            if months is None:
                raise ValueError(
                    "demand_charge_per_kw is active but no month labels were "
                    "given; pass months= (one integer 1-12 per timestep; "
                    "EnergySystem reads weather['month'])."
                )
            months_arr = np.asarray(months)
            if len(months_arr) != len(grid_import):
                raise ValueError(
                    f"months length {len(months_arr)} != grid_import length "
                    f"{len(grid_import)} (demand_charge_per_kw)"
                )
            imp = np.asarray(grid_import, dtype=float)
            demand = 0.0
            for mo in np.unique(months_arr):
                demand += float(np.max(imp[months_arr == mo])) * rate
            cost["demand_charge"] = demand
            cost["net_grid_cost"] = import_cost - export_credit + demand
        return cost
