"""Shared benchmark helpers (metrics only, by design).

Second consumer triggered extraction per the scripts/benchmarks contract
(rule-of-three: 1st inline -> 2nd extract -> 3rd YAML spec + runner).
Keep this file dependency-free (numpy only) so any benchmark can import.
"""
import numpy as np


def metrics(sim: np.ndarray, obs: np.ndarray) -> dict:
    """Hourly-series comparison stats. sim/obs same length, aligned.

    Returns N, rmse, mbe (sim - obs, signed), p95abs (95th percentile of
    |error|). All in the units of the input arrays.
    """
    e = np.asarray(sim, dtype=float) - np.asarray(obs, dtype=float)
    n = int(len(e))
    return {
        "N": n,
        "rmse": float(np.sqrt(np.mean(e * e))),
        "mbe": float(np.mean(e)),
        "p95abs": float(np.percentile(np.abs(e), 95)),
    }
