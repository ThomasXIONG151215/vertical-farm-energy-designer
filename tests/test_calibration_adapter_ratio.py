"""Adapter A (ratio-type LAI/X_d anchoring) on synthetic paired data."""
import numpy as np
import pandas as pd
import pytest

from vfed.calibration import GrowthObservations, anchor_c_pl_d


def _paired(c_true: float, n: int = 12):
    xd = np.linspace(0.005, 0.15, n)
    lai = (c_true / 0.9) * xd            # exact ratio -> both estimators hit
    times = pd.date_range("2024-01-01", periods=n, freq="5D")
    return GrowthObservations(times=times, x_d=xd, lai=lai)


def test_anchor_recovers_constant_ratio():
    a = anchor_c_pl_d(_paired(35.0))
    assert abs(a.value - 35.0) < 0.2
    assert abs(a.c_regression - 35.0) < 1e-6
    assert a.n_points == 12
    assert a.ratio_drift == pytest.approx(1.0)   # no drift by construction


def test_anchor_table_carries_time_column():
    a = anchor_c_pl_d(_paired(35.0))
    assert "time" in a.table.columns
    assert a.table["time"].iloc[0] == "2024-01-01"


def test_anchor_requires_paired_lai():
    obs = GrowthObservations(times=pd.date_range("2024-01-01", periods=5),
                             x_d=np.linspace(0.01, 0.1, 5), lai=None)
    with pytest.raises(ValueError):
        anchor_c_pl_d(obs)


def test_anchor_rejects_nonpositive_samples():
    xd = np.linspace(0.005, 0.15, 12)
    lai = 40.0 * xd / 0.9
    lai[3] = 0.0
    obs = GrowthObservations(times=pd.date_range("2024-01-01", periods=12),
                             x_d=xd, lai=lai)
    with pytest.raises(ValueError):
        anchor_c_pl_d(obs)
