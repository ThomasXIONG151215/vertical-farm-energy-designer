"""Golden-section search and 1-state series/fit round-trip (synthetic)."""
import numpy as np
import pandas as pd
import pytest

from vfed.calibration import (ClimateSeries, fit_c_rad_phot, golden_section,
                              run_growth_series)


def test_golden_section_recovers_known_minimum():
    def f(x):
        return (x - 3.14) ** 2

    x, fx, n = golden_section(f, 0.0, 10.0, xatol=1e-5)
    assert abs(x - 3.14) <= 1e-4
    assert abs(fx) <= 1e-8
    assert n >= 2


def test_golden_section_rejects_empty_interval():
    with pytest.raises(ValueError):
        golden_section(lambda x: x * x, 1.0, 1.0)


def _synthetic_climate(days: int = 20) -> ClimateSeries:
    idx = pd.date_range("2024-01-01", periods=days * 24 * 4, freq="300s")
    hour = idx.hour.to_numpy() + idx.minute.to_numpy() / 60.0
    par = 150.0 * np.clip(np.sin(np.pi * (hour - 6.0) / 16.0), 0.0, None)
    return ClimateSeries(times=idx, temp_c=np.full(len(idx), 22.0),
                         co2_ppm=np.full(len(idx), 700.0), par_w=par,
                         dt_s=300.0)


def test_run_growth_series_sample_zero_is_initial_state():
    clim = _synthetic_climate(2)
    out = run_growth_series(clim, x_d0=0.01, c_pl_d=30.0, c_rad_phot=4e-9,
                            sample_indices=[0, len(clim.times) - 1])
    assert out[0] == pytest.approx(0.01)
    assert out[1] > 0.01          # growth in a driven climate


def test_fit_recovers_synthetic_c_rad_phot():
    clim = _synthetic_climate(20)
    truth = 4.0e-9
    idx = np.linspace(0, len(clim.times) - 1, 9).astype(int)
    obs = run_growth_series(clim, x_d0=0.002, c_pl_d=30.0,
                            c_rad_phot=truth, sample_indices=idx)
    c_hat, rmse, _ = fit_c_rad_phot(clim, 0.002, 30.0, idx, obs)
    assert abs(c_hat / truth - 1.0) < 0.01
    assert rmse < 1e-5
