"""
Electricity tariff model (hourly price table).

Maps each hour-of-day directly to a price via a 24-element array.
Replaces the old three-tier peak/normal/valley model.
"""

from dataclasses import dataclass, field
from typing import Dict, List

import numpy as np

__all__ = ["Tariff"]


@dataclass
class Tariff:
    hourly_prices: List[float] = field(
        default_factory=lambda: [0.10] * 24)  # index = hour-of-day
    export_price: float = 0.05                 # feed-in credit (same currency)

    def price_for_hour(self, hour: int) -> float:
        h = int(hour) % 24
        if h < len(self.hourly_prices):
            return self.hourly_prices[h]
        return 0.10  # fallback

    def price_array(self, hours: np.ndarray) -> np.ndarray:
        return np.array([self.price_for_hour(h) for h in hours])

    def annual_cost(self, grid_import: np.ndarray, grid_export: np.ndarray,
                    hours: np.ndarray, dt: float = 1.0) -> Dict[str, float]:
        price = self.price_array(hours)
        import_cost = float(np.sum(grid_import * price * dt))
        export_credit = float(np.sum(grid_export * self.export_price * dt))
        return {
            "grid_import_cost": import_cost,
            "grid_export_credit": export_credit,
            "net_grid_cost": import_cost - export_credit,
        }
