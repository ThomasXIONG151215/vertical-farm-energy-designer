"""Output layer (skeleton): calibration result with provenance labels.

 规划文档 v0.4 §4 贯穿能力线——输出层。开放校准主张的前提:
 每个参数必须携带来源标签（ANCHORED/FITTED/TRANSFERRED/ASSUMED）与
 可辨识性结论，禁止输出无出处的裸参数值。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from .adapter_ratio import InterceptAnchor
from .contracts import IdentifiabilityReport, ParameterLabel


@dataclass
class CalibrationMetrics:
    """Fit-window agreement metrics for the calibrated series."""

    rmse_kg_m2: float
    n_samples: int
    window_days: Optional[float] = None


@dataclass
class CalibrationResult:
    """Complete output of one calibration run (planning v0.4 §4)."""

    dataset: str
    generated_at: datetime = field(default_factory=datetime.now)
    params: Dict[str, float] = field(default_factory=dict)
    labels: Dict[str, ParameterLabel] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)
    metrics: Optional[CalibrationMetrics] = None
    anchor: Optional[InterceptAnchor] = None
    identifiability: Optional[IdentifiabilityReport] = None

    def add_param(self, name: str, value: float,
                  label: ParameterLabel, note: str = "") -> None:
        self.params[name] = float(value)
        self.labels[name] = label
        if note:
            self.notes.append("%s: %s" % (name, note))

    def to_markdown(self) -> str:
        t = ["# 生长模型校准结果 — %s" % self.dataset,
             "",
             "生成时间: %s" % self.generated_at.strftime("%Y-%m-%d %H:%M"),
             ""]
        t.append("| 参数 | 值 | 来源标签 |")
        t.append("|---|---|---|")
        for name, value in self.params.items():
            label = self.labels.get(name)
            zh = label.zh if label is not None else "?"
            t.append("| %s | %.6g | %s |" % (name, value, zh))
        t.append("")
        if self.metrics is not None:
            win = ("%.1f" % self.metrics.window_days
                   if self.metrics.window_days is not None else "—")
            t.append("拟合指标: RMSE = %.4f kg/m2, n = %d, 窗口 = %s 天"
                     % (self.metrics.rmse_kg_m2, self.metrics.n_samples, win))
            t.append("")
        if self.anchor is not None:
            a = self.anchor
            t.append("截获锚定（适配器 A）: c_pl_d = %.2f（LSQ 取用值）；"
                     "过原点回归 %.2f；k_PAR = %.2f" %
                     (a.value, a.c_regression, a.k_par))
            t.append("LAI/X_d 比值: 均值 %.1f, 范围 %.1f–%.1f, "
                     "漂移 %.2f×（非单调漂移 = 单状态结构残差信号）" %
                     (a.ratio_mean, a.ratio_min, a.ratio_max, a.ratio_drift))
            t.append("")
        if self.identifiability is not None:
            t.append("可辨识性结论:")
            t.extend(self.identifiability.lines())
            t.append("")
        if self.notes:
            t.append("备注:")
            for note in self.notes:
                t.append("- %s" % note)
            t.append("")
        return "\n".join(t)
