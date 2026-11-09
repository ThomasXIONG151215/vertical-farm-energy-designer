"""Time-indexed weather lookup for the building loop (nested-time v2, T1).

The building loop does not iterate over weather rows; it steps physics at
``dt`` and asks "what is the weather now" at each substep start.  This
module provides that lookup as a zero-order-hold (staircase) table: row
``i`` covers the half-open window ``[start_s[i], start_s[i+1])`` and is
returned verbatim for any ``t`` inside it — values are never interpolated,
so no data is invented between samples.

Sub-sampling rules fall out of the same contract: weather rows finer than
``dt`` are subsampled (the covering row wins), rows coarser than ``dt``
repeat (ZOH hold).  The hourly uniform grid (today's only bridge output)
resolves to exact integer division, keeping the default path bit-identical
to the legacy ``T_ext[h]`` array indexing (zero-drift gate).
"""

from typing import Dict, NamedTuple

import numpy as np


class WeatherSample(NamedTuple):
    """One substep-start weather sample (staircase values, no interpolation)."""

    T_ext: float
    RH_ext: float
    GHI: float


class WeatherSeries:
    """Zero-order-hold weather lookup sampled on the loop's time ledger.

    Contract (nested-time v2):

    * ``t`` is seconds from the first weather row (t=0 at row 0).  The
      building loop derives it from its substep position as
      ``t = hour*3600 + s*dt`` (idealized hour window), so hourly rows
      always resolve to row ``hour`` even for a non-integral ``dt``.
    * Construction validates: integer strictly-increasing starts, all
      columns finite and matching the row count.  Out-of-range ``t``
      raises (fail fast) — never silently clamps to the last row.
    * ``sample()`` returns the loop's three consumed columns
      (T_ext/RH_ext/GHI); ``at()`` reads any column by name.
    """

    __slots__ = ("_start", "_n", "_step", "_columns")

    def __init__(self, start_s, columns: Dict[str, np.ndarray]):
        start = np.asarray(start_s)
        if start.ndim != 1 or start.size == 0:
            raise ValueError("start_s must be a non-empty 1-D array of row starts")
        if not np.issubdtype(start.dtype, np.integer):
            raise ValueError("start_s must be integer seconds (the loop time ledger is integer)")
        if start.size > 1 and not np.all(np.diff(start) > 0):
            raise ValueError("start_s must be strictly increasing")
        self._start = start
        self._n = int(start.size)
        # Uniform-grid fast path: exact O(1) integer division (the hourly
        # default).  Non-uniform grids fall back to searchsorted.
        self._step = None
        if self._n > 1:
            d = int(start[1] - start[0])
            if np.all(np.diff(start) == d):
                self._step = d
        cols = {}
        for name, arr in columns.items():
            a = np.asarray(arr, dtype=float)
            if a.ndim != 1 or a.size != self._n:
                raise ValueError(
                    f"weather column {name!r} must be 1-D with {self._n} rows "
                    f"(got shape {a.shape})"
                )
            if not np.isfinite(a).all():
                raise ValueError(f"weather column {name!r} contains NaN/inf values")
            cols[name] = a
        self._columns = cols

    @classmethod
    def hourly(cls, columns: Dict[str, np.ndarray]) -> "WeatherSeries":
        """Uniform hourly grid: row ``i`` covers ``[i*3600, (i+1)*3600)``."""
        first = next(iter(columns.values()))
        return cls(np.arange(len(first), dtype=np.int64) * 3600, columns)

    @classmethod
    def from_dataframe(cls, df) -> "WeatherSeries":
        """Build a series from a timestamped weather DataFrame (T3).

        The frame follows the weather-bridge column contract
        (``temperature_2m``, ``relative_humidity_2m``, ``shortwave_radiation``)
        and carries either a ``DatetimeIndex`` or a ``timestamp`` column.
        Stamps become integer seconds relative to the first row; a stamp
        that is not a whole number of seconds raises (the loop time ledger
        is integer, so sub-second weather is a contract violation).
        ``__init__`` then enforces strictly-increasing starts and finite
        values — no silent interpolation or row dropping happens here.
        """
        import pandas as pd  # lazy: numpy-only importors stay numpy-only

        if isinstance(df.index, pd.DatetimeIndex):
            index = df.index
        elif "timestamp" in df.columns:
            index = pd.DatetimeIndex(df["timestamp"])
        else:
            raise ValueError("weather frame needs a DatetimeIndex or a 'timestamp' column")
        if len(index) == 0:
            raise ValueError("weather frame contains 0 rows")
        # pandas 3 changed the default datetime64 unit from ns to us, so
        # raw asi8 integers no longer mean ns there.  Normalize to ns
        # first (lossless); pandas 1.x has no .unit but is ns-only.
        unit = getattr(index, "unit", "ns")
        if unit != "ns":
            index = index.as_unit("ns")
        deltas_ns = index.asi8 - index.asi8[0]
        if np.any(deltas_ns % 1_000_000_000 != 0):
            raise ValueError(
                "weather timestamps must be whole seconds apart (the loop "
                "time ledger is integer); got a sub-second offset"
            )
        start_s = (deltas_ns // 1_000_000_000).astype(np.int64)
        mapping = {
            "T_ext": "temperature_2m",
            "RH_ext": "relative_humidity_2m",
            "GHI": "shortwave_radiation",
        }
        columns = {}
        for series_name, frame_name in mapping.items():
            if frame_name not in df.columns:
                raise ValueError(
                    f"weather frame is missing column {frame_name!r} "
                    f"(needed for the {series_name!r} series)"
                )
            columns[series_name] = df[frame_name].to_numpy()
        return cls(start_s, columns)

    def at(self, t_s, column: str) -> float:
        """Return ``column`` held at time ``t_s`` (staircase, no interpolation)."""
        return float(self._columns[column][self._index(t_s)])

    def sample(self, t_s) -> WeatherSample:
        """Return the (T_ext, RH_ext, GHI) triple held at time ``t_s``."""
        i = self._index(t_s)
        return WeatherSample(
            self._columns["T_ext"][i],
            self._columns["RH_ext"][i],
            self._columns["GHI"][i],
        )

    def _index(self, t_s) -> int:
        if self._step is not None:
            i = int(t_s // self._step)
        else:
            i = int(np.searchsorted(self._start, t_s, side="right") - 1)
        if not 0 <= i < self._n:
            last = int(self._start[-1]) + (self._step or 0)
            raise IndexError(
                f"weather sample time {t_s}s is outside the data window "
                f"[0, {last}s); the bridge must supply gapless coverage"
            )
        return i
