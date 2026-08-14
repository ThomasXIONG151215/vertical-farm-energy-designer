"""
SimulationResult — typed container for engine.run() output.

Provides a standard JSON-serializable structure consumed by both CLI
(``vfed evaluate``) and the browser-based web app (``vfed-web/``).
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

__all__ = ["SimulationResult"]


def _ensure_json_safe(obj: Any) -> Any:
    """Recursively convert numpy/pandas types to plain Python for JSON."""
    import numpy as np

    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.generic):
        return obj.item()
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, dict):
        return {k: _ensure_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_ensure_json_safe(v) for v in obj]
    return obj


@dataclass
class SimulationResult:
    """Complete output of a single-point building + energy-system simulation.

    All numeric fields use plain Python ``int`` / ``float`` / ``list`` so
    the result is directly JSON-serializable.
    """

    project_name: str
    currency: str = "USD"
    exchange_rate: float = 1.0
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    # ── summary KPIs ──────────────────────────────────────────────
    summary: Dict[str, Any] = field(default_factory=dict)

    # ── climate overview ─────────────────────────────────────────
    climate: Dict[str, Any] = field(default_factory=dict)

    # ── full 8760-h timeseries (column-major dict of lists) ─────
    timeseries: Dict[str, List[float]] = field(default_factory=dict)

    # ── 12-month aggregations ────────────────────────────────────
    monthly: Dict[str, Any] = field(default_factory=dict)

    # ── annual energy composition (%) ────────────────────────────
    energy_breakdown: Dict[str, float] = field(default_factory=dict)

    # ── typical daily load (12 months × 24 hours) ─────────────────
    typical_daily: Dict[str, Any] = field(default_factory=dict)

    # ── raw 8760-h arrays (kept for sweep reuse, backward compat) ─────
    _raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    # -----------------------------------------------------------------
    def __getitem__(self, key: str) -> Any:
        """Backward-compat dict-like access for sweep.py and legacy callers."""
        # legacy keys mapped to new locations
        _legacy_map = {
            "load": lambda: self._raw.get("load"),
            "weather": lambda: self._raw.get("weather"),
            "kwh_per_kg_fresh": lambda: self.summary.get("specific_energy_kwh_per_kg"),
            "annual_load_kwh": lambda: self.summary.get("annual_energy_kwh"),
            "biomass_kg": lambda: self.summary.get("annual_harvest_kg"),
            "kwh_per_kg": lambda: (
                self.summary.get("specific_energy_kwh_per_kg", 0) / self.summary.get("dry_matter_fraction", 0.05)
                if self.summary.get("specific_energy_kwh_per_kg") else 0
            ),
            "timeseries": lambda: self._as_dataframe(),
        }
        if key in _legacy_map:
            return _legacy_map[key]()
        raise KeyError(f"SimulationResult has no key '{key}'")

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    def __contains__(self, key: str) -> bool:
        try:
            self[key]
            return True
        except KeyError:
            return False

    def _as_dataframe(self):
        """Return timeseries as a pandas DataFrame (backward compat)."""
        import pandas as pd
        return pd.DataFrame(self.timeseries)
    def to_dict(self) -> dict:
        """Serialize to the standard JSON schema (v1.0)."""
        raw = {
            "version": "1.0",
            "project_name": self.project_name,
            "currency": self.currency,
            "exchange_rate": self.exchange_rate,
            "timestamp": self.timestamp,
            "summary": _ensure_json_safe(self.summary),
            "climate": _ensure_json_safe(self.climate),
            "timeseries": _ensure_json_safe(self.timeseries),
            "monthly": _ensure_json_safe(self.monthly),
            "energy_breakdown": _ensure_json_safe(self.energy_breakdown),
            "typical_daily": _ensure_json_safe(self.typical_daily),
        }
        return raw

    def json(self) -> str:
        """Return compact JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False)

    def json_pretty(self) -> str:
        """Return indented JSON string."""
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    def save(self, path: str) -> None:
        """Write full result as JSON to *path*."""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    def save_summary_csv(self, path: str) -> None:
        """Write a single-row CSV of scalar KPIs."""
        s = self.summary
        keys = sorted(s.keys())
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(keys)
            w.writerow([s[k] for k in keys])

    def save_timeseries_csv(self, path: str) -> None:
        """Write the full timeseries as a CSV (columns = keys)."""
        ts = self.timeseries
        if not ts:
            return
        cols = list(ts.keys())
        n = len(ts[cols[0]])
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(cols)
            for i in range(n):
                w.writerow([ts[c][i] for c in cols])

    def save_monthly_csv(self, path: str) -> None:
        """Write monthly aggregations as CSV (one row = one month)."""
        m = self.monthly
        if not m:
            return
        flat = {}
        for k, v in m.items():
            if isinstance(v, dict):
                for sk, sv in v.items():
                    flat[f"{k}__{sk}"] = sv
            else:
                flat[k] = v
        cols = sorted(flat.keys())
        n = max((len(flat[c]) if isinstance(flat[c], list) else 1) for c in cols)
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(cols)
            for i in range(n):
                row = []
                for c in cols:
                    v = flat[c]
                    if isinstance(v, list):
                        row.append(v[i] if i < len(v) else "")
                    else:
                        row.append(v if i == 0 else "")
                w.writerow(row)

    @classmethod
    def load(cls, path: str) -> "SimulationResult":
        """Reconstruct from a JSON file created by :meth:`save`."""
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        return cls.from_dict(d)

    @classmethod
    def from_dict(cls, d: dict) -> "SimulationResult":
        """Create from a dict produced by :meth:`to_dict`."""
        return cls(
            project_name=d.get("project_name", "unnamed"),
            currency=d.get("currency", "USD"),
            exchange_rate=d.get("exchange_rate", 1.0),
            timestamp=d.get("timestamp", ""),
            summary=d.get("summary", {}),
            climate=d.get("climate", {}),
            timeseries=d.get("timeseries", {}),
            monthly=d.get("monthly", {}),
            energy_breakdown=d.get("energy_breakdown", {}),
            typical_daily=d.get("typical_daily", {}),
        )


# ---------------------------------------------------------------------------
# self-check (run: python -m src.design.result)
# ---------------------------------------------------------------------------
def _demo():
    r = SimulationResult(project_name="test_demo", currency="CNY", exchange_rate=7.2)
    r.summary = {"annual_energy_kwh": 1e5, "specific_cost": 2.4}
    r.climate = {"city": "Shanghai", "annual_avg_temp_c": 17.2}
    r.timeseries = {"T_z": [22.0, 22.1], "load_kw": [10.0, 10.5]}
    r.monthly = {"total_energy_kwh": [8000, 7200, 7500]}
    r.energy_breakdown = {"hvac": 0.30, "led": 0.45, "deh": 0.15, "misc": 0.10}
    r.typical_daily = {
        "months": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
        "hours": list(range(24)),
        "load_kw": [[5.0] * 24 for _ in range(12)],
    }

    # round-trip
    d = r.to_dict()
    r2 = SimulationResult.from_dict(d)
    assert r2.project_name == "test_demo"
    assert r2.currency == "CNY"
    assert r2.exchange_rate == 7.2
    assert r2.summary["annual_energy_kwh"] == 100000.0
    assert r2.climate["city"] == "Shanghai"
    assert r2.timeseries["T_z"] == [22.0, 22.1]
    assert len(r2.typical_daily["load_kw"]) == 12
    assert len(r2.typical_daily["load_kw"][0]) == 24

    print("SimulationResult self-check PASSED")


if __name__ == "__main__":
    _demo()
