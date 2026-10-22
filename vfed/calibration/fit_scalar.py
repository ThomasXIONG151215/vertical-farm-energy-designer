"""Parameter-fitting layer (skeleton): numpy-only scalar search.

零 scipy 依赖约束（规划 v0.4 引擎骨架决策）: 包内只允许 numpy/pandas。
黄金分割搜索替代 ``scipy.optimize.minimize_scalar(method="bounded")``——
对单峰目标函数数值等价（Stage 1 已证两个目标函数均单峰：
截获分数 SSE 与效率拟合 RMSE）。

数学出处: Stage 1 手工校准 ``scripts/benchmarks/bjaaf_growth/run_calibration.py``
（报告 ``user-gym/benchmarks/bjaaf_growth_calibration_report.md``）。
"""
from __future__ import annotations

import math
from typing import Callable, Sequence, Tuple

import numpy as np

from vfed.plants.van_henten import VanHenten

from .contracts import ClimateSeries

_INVPHI = (math.sqrt(5.0) - 1.0) / 2.0   # 1/phi ~ 0.618


# ------------------------------------------------------------- minimizer --
def golden_section(func: Callable[[float], float], a: float, b: float,
                   xatol: float = 1e-4) -> Tuple[float, float, int]:
    """Bounded golden-section minimization of a unimodal ``func`` on [a, b].

    Deterministic; tolerance is on x (interval width), matching the
    ``minimize_scalar(..., method="bounded", options={"xatol": ...})``
    convention used by the Stage 1 scripts.

    Returns ``(x_best, f_best, n_evals)``.
    """
    if not (b > a):
        raise ValueError("require b > a, got a=%r b=%r" % (a, b))
    c = b - _INVPHI * (b - a)
    d = a + _INVPHI * (b - a)
    fc, fd = func(c), func(d)
    n_evals = 2
    while (b - a) > xatol:
        if fc <= fd:
            b, d, fd = d, c, fc
            c = b - _INVPHI * (b - a)
            fc = func(c)
        else:
            a, c, fc = c, d, fd
            d = a + _INVPHI * (b - a)
            fd = func(d)
        n_evals += 1
    x = 0.5 * (a + b)
    return x, func(x), n_evals + 1


# ------------------------------------------------------- 1-state runner --
def run_growth_series(climate: ClimateSeries, x_d0: float, c_pl_d: float,
                      c_rad_phot: float,
                      sample_indices: Sequence[int]) -> np.ndarray:
    """Euler-step the one-state Van Henten model over ``climate``.

    Semantics identical to Stage 1 ``run_vfed``: CO2 updated per step
    (live attribute), X_d sampled at the state **after** stepping into
    row ``j``; ``sample_indices == [0]`` returns the initial state.

    Sampling is row-index based (never exact-timestamp matching)——
    Stage 3 教训: 实测时间戳可能带毫秒尾数。
    """
    grow = VanHenten(co2_ppm=float(climate.co2_ppm[0]),
                     c_pl_d=c_pl_d, c_rad_phot=c_rad_phot)
    temp = np.asarray(climate.temp_c, dtype=float)
    co2 = np.asarray(climate.co2_ppm, dtype=float)
    par = np.asarray(climate.par_w, dtype=float)
    n = len(temp)
    want = {int(j): None for j in sample_indices}
    xd = float(x_d0)
    if 0 in want:
        want[0] = xd
    for i in range(n - 1):
        grow.co2_ppm = float(co2[i])
        _, xd = grow.step(float(temp[i]), float(par[i]), xd, climate.dt_s)
        j = i + 1
        if j in want and want[j] is None:
            want[j] = xd
    return np.array([want[int(j)] for j in sample_indices], dtype=float)


# ------------------------------------------------------------- fitting --
def fit_c_rad_phot(climate: ClimateSeries, x_d0: float, c_pl_d: float,
                   sample_indices: Sequence[int], obs_x_d: np.ndarray,
                   log10_bounds: Tuple[float, float] = (-10.0, -7.0),
                   xatol: float = 1e-4) -> Tuple[float, float, int]:
    """1-parameter LSQ fit of c_rad_phot on in-window X_d samples.

    Objective minimized on log10(c_rad_phot) over ``log10_bounds``
    (same parameterisation as Stage 1 ``fit_c_rad_phot``).

    Returns ``(c_rad_phot, rmse, n_evals)``.
    """
    obs = np.asarray(obs_x_d, dtype=float)
    if len(obs) != len(sample_indices):
        raise ValueError("obs_x_d/sample_indices length mismatch")

    def rmse(log10c: float) -> float:
        sim = run_growth_series(climate, x_d0, c_pl_d, 10.0 ** log10c,
                                sample_indices)
        return float(np.sqrt(np.mean((sim - obs) ** 2)))

    x, f, n = golden_section(rmse, log10_bounds[0], log10_bounds[1],
                             xatol=xatol)
    return 10.0 ** x, f, n
