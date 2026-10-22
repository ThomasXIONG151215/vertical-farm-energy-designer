"""Data contracts for the growth-model calibration engine (skeleton).

规划文档 v0.4 §4 贯穿能力线（数据校准引擎）—— 输入/输出数据契约。

骨架范围（Phase 1 手工经验固化，非 Phase 3 自动化）：
  * 输入适配层 适配器 A（比值型）: 配对 LAI/X_d 观测 -> c_pl_d 截获锚
  * 可辨识性层: 数据形态签名 -> 参数可辨识性结论
  * 参数拟合层: numpy-only 黄金分割单参数拟合（零 scipy 依赖）
  * 输出层: 参数 + 可辨识性标签 + 指标

单位约定（全引擎统一）:
  * X_d  [kg/m2]  地面面积基干重
  * LAI  [-]
  * PAR  [W/m2]   冠层光合有效辐射；数据集适配器负责任何短波->PAR 换算
                  （如 BJAAF 的 PAR = 0.5 x 短波）
  * 温度 [deg C]，CO2 [ppm]，时间步 [s]

采样契约（Stage 3 教训）: 对气候序列的采样以**行索引**表达
（``sample_indices``），不做时刻精确匹配——实测时间戳可能带毫秒尾数。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Sequence


# ---------------------------------------------------------------- labels --
class ParameterLabel(Enum):
    """Parameter source label (planning doc v0.3.2, §4 output layer).

    每个校准参数必须标注来源四类之一——「开放校准」主张的前提。
    """

    ANCHORED = "直接锚定"        # 独立比值型/图像型观测量直接定参
    FITTED = "拟合"              # 在锚定/已知条件下由目标曲线拟合
    TRANSFERRED = "迁移"         # 从另一数据集的校准结果迁移（条件值）
    ASSUMED = "假设"             # 文献值/默认值，未经本数据约束

    @property
    def zh(self) -> str:
        return self.value


class AssessmentStatus(Enum):
    """Identifiability assessment status for one parameter."""

    IDENTIFIABLE = "可辨识"
    CONDITIONAL = "条件可辨识"
    DEGENERATE = "乘积简并"
    PENDING_ADAPTER = "待适配器"
    NOT_IDENTIFIABLE = "不可辨识"

    @property
    def zh(self) -> str:
        return self.value


# ----------------------------------------------------------------- inputs --
@dataclass
class GrowthObservations:
    """Destructive growth samples (paired where available).

    ``lai`` 为可选: 适配器 A 需要同株同日 LAI/X_d 配对；缺 LAI 的数据集
    （UC Davis 型）走适配器 B 或迁移路径。
    """

    times: Sequence          # sample timestamps (any datetime-like)
    x_d: Sequence            # [kg/m2] dry weight on ground-area basis
    lai: Optional[Sequence] = None   # [-] paired leaf area index

    def __post_init__(self) -> None:
        n = len(self.x_d)
        if len(self.times) != n:
            raise ValueError("times/x_d length mismatch: %d vs %d"
                             % (len(self.times), n))
        if self.lai is not None and len(self.lai) != n:
            raise ValueError("lai/x_d length mismatch: %d vs %d"
                             % (len(self.lai), n))


@dataclass
class ClimateSeries:
    """Climate driver for the fit window (regular sampling, row-aligned).

    ``par_w`` 必须已是冠层 PAR [W/m2]；短波->PAR 换算由数据集适配器完成。
    """

    times: Sequence
    temp_c: Sequence         # [deg C]
    co2_ppm: Sequence        # [ppm]
    par_w: Sequence          # [W/m2] PAR at canopy
    dt_s: float              # [s] sampling interval (Euler step)

    def __post_init__(self) -> None:
        n = len(self.times)
        for name in ("temp_c", "co2_ppm", "par_w"):
            if len(getattr(self, name)) != n:
                raise ValueError("%s/times length mismatch: %d vs %d"
                                 % (name, len(getattr(self, name)), n))
        if self.dt_s <= 0.0:
            raise ValueError("dt_s must be positive")


@dataclass
class DataSignature:
    """Dataset capability signature (planning doc v0.4 §4, input layer).

    可辨识性层的输入。字段回答「该数据集能约束哪些参数」：
      * paired_lai_xd  同株同日 LAI/X_d 配对测量（BJAAF 型）-> 锚 c_pl_d
      * canopy_image   冠层图像时序（UC Davis 型）-> 适配器 B 锚 c_pl_d
      * par_series     实测 PAR/辐射时序 -> 效率轴非简并
      * ppfd_recipe    PPFD 仅为配方/假设值 -> c_rad_phot 为条件值
      * area_biomass   X_d 直接以 kg/m2 观测（无需密度换算）
      * plant_biomass  株级鲜/干重观测（换算 X_d 需密度）
      * density        种植密度 [plants/m2] 已知
    """

    paired_lai_xd: bool = False
    canopy_image: bool = False
    par_series: bool = False
    ppfd_recipe: bool = False
    area_biomass: bool = False
    plant_biomass: bool = False
    density: bool = False

    @classmethod
    def bjaaf_like(cls) -> "DataSignature":
        """BJAAF Exp_c 型签名（Stage 1 校准路径，全锚定+拟合）。"""
        return cls(paired_lai_xd=True, par_series=True, area_biomass=True,
                   plant_biomass=True, density=True)

    @classmethod
    def uc_davis_like(cls) -> "DataSignature":
        """UC Davis 型签名（T4/Stage 2 简并路径，适配器 B 候选）。"""
        return cls(canopy_image=True, ppfd_recipe=True, plant_biomass=True)

    @property
    def biomass_area_ready(self) -> bool:
        """X_d 可直接或经密度换算得到 [kg/m2] 时序。"""
        return self.area_biomass or (self.plant_biomass and self.density)


# ---------------------------------------------------------------- outputs --
@dataclass
class ParameterAssessment:
    """Identifiability conclusion for a single parameter."""

    name: str                        # e.g. "c_pl_d"
    status: AssessmentStatus
    label: ParameterLabel            # 该参数在本数据集上的来源标签
    note: str                        # 依据/边界说明（一句话）


@dataclass
class IdentifiabilityReport:
    """Rule-based identifiability conclusions for one dataset signature."""

    signature: DataSignature
    assessments: List[ParameterAssessment] = field(default_factory=list)

    def find(self, name: str) -> ParameterAssessment:
        for a in self.assessments:
            if a.name == name:
                return a
        raise KeyError("no assessment for %r" % name)

    def lines(self) -> List[str]:
        out = []
        for a in self.assessments:
            out.append("- %s: %s（来源标签: %s）—— %s"
                       % (a.name, a.status.zh, a.label.zh, a.note))
        return out
