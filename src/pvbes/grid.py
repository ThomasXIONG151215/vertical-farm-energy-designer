"""
Electricity tariff model (time-of-use).

Maps each hour-of-day to a price tier (peak / normal / valley) and computes
grid import cost and export (feed-in) credit. Fully parametric for design studies.
"""

from dataclasses import dataclass, field
from typing import Dict, List

import numpy as np

__all__ = ["Tariff"]


@dataclass
class Tariff:
    peak_price: float = 0.096      # $/kWh
    normal_price: float = 0.096
    valley_price: float = 0.096
    export_price: float = 0.05     # $/kWh feed-in credit
    peak_hours: List[int] = field(default_factory=lambda: [10, 11, 12, 13, 14, 18, 19, 20, 21])
    valley_hours: List[int] = field(default_factory=lambda: [0, 1, 2, 3, 4, 5, 23])

    def price_for_hour(self, hour: int) -> float:
        h = int(hour) % 24
        if h in self.peak_hours:
            return self.peak_price
        if h in self.valley_hours:
            return self.valley_price
        return self.normal_price

    def price_array(self, hours: np.ndarray) -> np.ndarray:
        return np.array([self.price_for_hour(h) for h in hours])

    def annual_cost(self, grid_import: np.ndarray, grid_export: np.ndarray,
                    hours: np.ndarray) -> Dict[str, float]:
        price = self.price_array(hours)
        import_cost = float(np.sum(grid_import * price))
        export_credit = float(np.sum(grid_export * self.export_price))
        return {
            "grid_import_cost": import_cost,
            "grid_export_credit": export_credit,
            "net_grid_cost": import_cost - export_credit,
        }
