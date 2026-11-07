"""Tests for the T1 nested-time v2 WeatherSeries (vfed/weather/series.py).

Covers the ZOH staircase contract: hourly uniform grids resolve by exact
integer division (the zero-drift fast path), finer grids subsample (the
covering row wins), coarser grids hold, non-uniform grids fall back to
searchsorted, and every malformed input raises at construction while an
out-of-range sample time raises at lookup (fail fast, never clamps).
"""

import numpy as np
import pytest

from vfed.weather.series import WeatherSeries


def _hourly(n=48):
    cols = {
        "T_ext": np.arange(n, dtype=float) + 10.0,
        "RH_ext": np.full(n, 65.0),
        "GHI": np.arange(n, dtype=float) * 10.0,
    }
    return WeatherSeries.hourly(cols), cols


class TestUniformHourly:
    def test_substep_ledger_resolves_row_h(self):
        """t = h*3600 + s*dt must hit row h for every substep of the hour."""
        ws, cols = _hourly()
        dt = 600.0
        for h in (0, 1, 13, 47):
            for s in range(6):
                t = h * 3600 + s * dt
                assert ws.sample(t).T_ext == cols["T_ext"][h]

    def test_non_integral_dt_stays_in_hour_window(self):
        """dt=719.9 (passes the engine's +/-1s tolerance) stays in row h."""
        ws, cols = _hourly()
        dt = 719.9
        for h in (0, 5, 20):
            for s in range(5):
                t = h * 3600 + s * dt
                assert ws.sample(t).T_ext == cols["T_ext"][h]

    def test_window_boundary_moves_to_next_row(self):
        ws, _ = _hourly()
        assert ws.sample(0).T_ext == 10.0
        assert ws.sample(3599).T_ext == 10.0
        assert ws.sample(3600).T_ext == 11.0

    def test_sample_bit_identical_to_legacy_indexing(self):
        ws, cols = _hourly()
        smp = ws.sample(13 * 3600 + 3 * 600.0)
        assert smp.T_ext == cols["T_ext"][13]
        assert smp.RH_ext == cols["RH_ext"][13]
        assert smp.GHI == cols["GHI"][13]

    def test_at_reads_any_column(self):
        ws, cols = _hourly()
        assert ws.at(7 * 3600, "GHI") == cols["GHI"][7]


class TestSubAndSuperSampling:
    def test_finer_rows_subsample_covering_row_wins(self):
        """15-min rows with dt=600 s: t=900 s must return row 1, not an
        average of rows 0-1 (staircase, never interpolated)."""
        n = 96
        cols = {
            "T_ext": np.arange(n, dtype=float),
            "RH_ext": np.zeros(n),
            "GHI": np.zeros(n),
        }
        start = np.arange(n, dtype=np.int64) * 900
        ws = WeatherSeries(start, cols)
        assert ws.sample(0).T_ext == 0.0
        assert ws.sample(899).T_ext == 0.0
        assert ws.sample(900).T_ext == 1.0
        assert ws.sample(1500).T_ext == 1.0

    def test_coarser_rows_hold(self):
        """2-hour rows repeat across the hold window (ZOH)."""
        cols = {
            "T_ext": np.array([1.0, 2.0, 3.0]),
            "RH_ext": np.zeros(3),
            "GHI": np.zeros(3),
        }
        start = np.array([0, 7200, 14400], dtype=np.int64)
        ws = WeatherSeries(start, cols)
        assert ws.sample(0).T_ext == 1.0
        assert ws.sample(7199).T_ext == 1.0
        assert ws.sample(7200).T_ext == 2.0
        assert ws.sample(14400).T_ext == 3.0

    def test_non_uniform_grid_uses_searchsorted(self):
        start = np.array([0, 1000, 3000, 7000], dtype=np.int64)
        cols = {
            "T_ext": np.array([10.0, 20.0, 30.0, 40.0]),
            "RH_ext": np.zeros(4),
            "GHI": np.zeros(4),
        }
        ws = WeatherSeries(start, cols)
        assert ws._step is None  # non-uniform: searchsorted path
        assert ws.sample(999).T_ext == 10.0
        assert ws.sample(1000).T_ext == 20.0
        assert ws.sample(2999).T_ext == 20.0
        assert ws.sample(3000).T_ext == 30.0
        assert ws.sample(6999).T_ext == 30.0
        assert ws.sample(7000).T_ext == 40.0


class TestValidation:
    def test_rejects_non_integer_starts(self):
        with pytest.raises(ValueError, match="integer seconds"):
            WeatherSeries(np.array([0.0, 3600.0]), {"T_ext": np.ones(2)})

    def test_rejects_unsorted_starts(self):
        with pytest.raises(ValueError, match="strictly increasing"):
            WeatherSeries(
                np.array([3600, 0], dtype=np.int64),
                {"T_ext": np.ones(2)},
            )

    def test_rejects_column_length_mismatch(self):
        with pytest.raises(ValueError, match="1-D with"):
            WeatherSeries(
                np.arange(3, dtype=np.int64) * 3600,
                {"T_ext": np.ones(2)},
            )

    def test_rejects_nan_column(self):
        arr = np.ones(3)
        arr[1] = np.nan
        with pytest.raises(ValueError, match="NaN/inf"):
            WeatherSeries(np.arange(3, dtype=np.int64) * 3600, {"T_ext": arr})

    def test_rejects_empty_grid(self):
        with pytest.raises(ValueError, match="non-empty"):
            WeatherSeries(np.array([], dtype=np.int64), {"T_ext": np.array([])})

    def test_out_of_range_raises_never_clamps(self):
        ws, _ = _hourly()
        with pytest.raises(IndexError, match="outside the data window"):
            ws.sample(48 * 3600)
        with pytest.raises(IndexError):
            ws.sample(-1)
