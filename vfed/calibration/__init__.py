"""Growth-model calibration engine (skeleton).

 规划文档 v0.4 §4 贯穿能力线——数据校准引擎的最小骨架。
 Phase 1 手工校准经验（BJAAF Stage 1 / UC Davis T4+Stage 2）的产品化：

 四层架构:
   * 输入适配层  adapter_ratio（适配器 A, 比值型 LAI/X_d）
   * 可辨识性层  identifiability（规则引擎）
   * 参数拟合层  fit_scalar（numpy-only 黄金分割）
   * 输出层      result（参数 + 来源标签 + 指标）

 适配器 B（图像型，UC Davis 727 张冠层 RGB）待实现（2026-10-16 决策
 保留为 Phase 3 图像输入适配测试用例）。
"""
from .contracts import (AssessmentStatus, ClimateSeries, DataSignature,
                        GrowthObservations, IdentifiabilityReport,
                        ParameterAssessment, ParameterLabel)
from .adapter_ratio import K_PAR_DEFAULT, InterceptAnchor, anchor_c_pl_d
from .identifiability import analyze_signature
from .fit_scalar import fit_c_rad_phot, golden_section, run_growth_series
from .result import CalibrationMetrics, CalibrationResult

__all__ = [
    "AssessmentStatus",
    "ClimateSeries",
    "DataSignature",
    "GrowthObservations",
    "IdentifiabilityReport",
    "ParameterAssessment",
    "ParameterLabel",
    "K_PAR_DEFAULT",
    "InterceptAnchor",
    "anchor_c_pl_d",
    "analyze_signature",
    "fit_c_rad_phot",
    "golden_section",
    "run_growth_series",
    "CalibrationMetrics",
    "CalibrationResult",
]
