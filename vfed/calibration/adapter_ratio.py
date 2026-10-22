"""Input-adaptation layer -- Adapter A (ratio type, planning v0.4 §4).

配对 LAI/X_d 观测（同株同日）-> 光截获参数 c_pl_d 截获锚。

数学出处（Stage 1 手工校准，2026-10-16）:
    vfed 在干重域截获:     f_vfed = 1 - exp(-c_pl_d * X_d)
    冠层物理在叶面积域截获: f_true = 1 - exp(-k_PAR * LAI)
    配对观测钉住 c_pl_d * X_d ~= k_PAR * LAI  ->  c_pl_d = k_PAR * LAI/X_d

双估计:
    (a) 过原点回归 LAI ~ X_d（斜率稳健，交叉验证）
    (b) 截获分数 LSQ: min_c Σ (f_vfed(c) - f_true)^2（形态忠实，取用值）

破简并依据: 单曲线只能辨识 K_eff = c_pl_d x c_rad_phot x PAR x (1/rho)
四因子乘积（T4）；LAI/X_d 比值为纯比值型观测，无需通量推断即可单独
分离 c_pl_d（Stage 1，报告 ``user-gym/benchmarks/bjaaf_growth_calibration_report.md``）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np
import pandas as pd

from .contracts import GrowthObservations
from .fit_scalar import golden_section

K_PAR_DEFAULT = 0.9   # m2/m2 leaf; BJAAF PhotosynthesisLightResponse.m


@dataclass
class InterceptAnchor:
    """Anchoring result for c_pl_d (adapter A output)."""

    value: float               # 取用锚定值 = 截获分数 LSQ (b)
    c_regression: float        # 过原点回归估计 (a)，交叉验证
    k_par: float
    n_points: int
    ratio_mean: float          # mean(LAI/X_d)
    ratio_min: float
    ratio_max: float
    table: pd.DataFrame        # 逐点诊断（times/xd/lai/ratio/f_true/f_fit）
    method_note: str

    @property
    def ratio_drift(self) -> float:
        """Relative drift of the LAI/X_d ratio across samples.

        非单调漂移 = 单状态结构残差信号（Stage 1: 33.8 -> 45.9）。
        """
        return self.ratio_max / self.ratio_min


def anchor_c_pl_d(obs: GrowthObservations,
                  k_par: float = K_PAR_DEFAULT,
                  bounds: Tuple[float, float] = (5.0, 200.0),
                  xatol: float = 1e-3) -> InterceptAnchor:
    """Estimate the light-extinction anchor c_pl_d [m2/kg].

    Raises ``ValueError`` when the observations lack the paired LAI column
    (adapter A requires it; UC-Davis-type datasets need adapter B or
    transfer instead).
    """
    if obs.lai is None:
        raise ValueError(
            "adapter A requires paired LAI/X_d observations; "
            "got x_d only (dataset signature lacks paired_lai_xd)")
    xd = np.asarray(obs.x_d, dtype=float)
    lai = np.asarray(obs.lai, dtype=float)
    if np.any(xd <= 0.0) or np.any(lai <= 0.0):
        raise ValueError("paired LAI/X_d samples must be strictly positive")
    ratio = lai / xd

    # (a) through-origin regression: k_PAR * LAI = c * X_d
    slope = float(np.sum(xd * lai) / np.sum(xd * xd))
    c_reg = k_par * slope

    # (b) LSQ on the interception fraction: f(c) ~ f_true
    f_true = 1.0 - np.exp(-k_par * lai)

    def sse(c: float) -> float:
        f_sim = 1.0 - np.exp(-c * xd)
        return float(np.sum((f_sim - f_true) ** 2))

    c_int, _, _ = golden_section(sse, bounds[0], bounds[1], xatol=xatol)

    table = pd.DataFrame({
        "xd_kg_m2": xd,
        "lai": lai,
        "lai_over_xd": ratio,
        "f_int_true": f_true,
        "f_int_fit": 1.0 - np.exp(-c_int * xd),
    })
    times: Optional[pd.Series] = None
    try:
        times = pd.Series(pd.to_datetime(list(obs.times)))
        table.insert(0, "time", times.dt.strftime("%Y-%m-%d"))
    except (TypeError, ValueError):
        pass   # engine stays date-agnostic when times are not datetimes

    note = ("c_pl_d = k_PAR*(LAI/X_d); LSQ on interception fraction "
            "(take value %.2f), through-origin regression cross-check "
            "%.2f (k_PAR=%.2f, n=%d)" % (c_int, c_reg, k_par, len(xd)))
    return InterceptAnchor(
        value=float(c_int), c_regression=float(c_reg), k_par=float(k_par),
        n_points=int(len(xd)),
        ratio_mean=float(np.mean(ratio)), ratio_min=float(np.min(ratio)),
        ratio_max=float(np.max(ratio)), table=table, method_note=note)
