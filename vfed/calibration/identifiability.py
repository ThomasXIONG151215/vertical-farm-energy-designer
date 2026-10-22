"""Identifiability layer (skeleton): rule engine over the data signature.

 规划文档 v0.4 §4 贯穿能力线——可辨识性层最小版。

 每类数据形态能约束哪些生长参数（Phase 1 手工校准操作的固化）:
   * c_pl_d（光截获）: 需要截获轴观测——配对 LAI/X_d（适配器 A）或
     冠层图像（适配器 B，待实现）；否则进入 K_eff 乘积简并。
   * c_rad_phot（光能转换效率）: 需要生物量曲线 + PAR 信息；
     PAR 为实测 -> 可辨识；PAR 为配方假设 -> 条件值（Stage 2 实证）。
   * rho（密度）: 面积基生物量不进入校准；株级观测缺密度 -> 1/rho
     加入 K_eff 简并（T4 分析）。

 K_eff 简并（T4, 2026-10-13）: 单条鲜重/干重曲线只能辨识
     K_eff = c_pl_d x c_rad_phot x PAR x (1/rho)
 四因子乘积，因子间互换不可分辨（UC Davis Stage 2 C3/C5/C6 因子设计实证）。
"""
from __future__ import annotations

from .contracts import (AssessmentStatus, DataSignature, IdentifiabilityReport,
                        ParameterAssessment, ParameterLabel)


def _assess_c_pl_d(sig: DataSignature) -> ParameterAssessment:
    if sig.paired_lai_xd:
        return ParameterAssessment(
            "c_pl_d", AssessmentStatus.IDENTIFIABLE, ParameterLabel.ANCHORED,
            "配对 LAI/X_d 比值型观测在位——适配器 A 直接锚定截获轴"
            "（BJAAF Stage 1 实证）")
    if sig.canopy_image:
        return ParameterAssessment(
            "c_pl_d", AssessmentStatus.PENDING_ADAPTER,
            ParameterLabel.ASSUMED,
            "冠层图像时序在位但适配器 B（图像型）未实现；"
            "当前只能迁移或文献假设（UC Davis Stage 2 走迁移）")
    return ParameterAssessment(
        "c_pl_d", AssessmentStatus.NOT_IDENTIFIABLE, ParameterLabel.ASSUMED,
        "无截获轴观测——c_pl_d 卷入 K_eff 乘积简并，"
        "只能迁移或文献假设")


def _assess_c_rad_phot(sig: DataSignature) -> ParameterAssessment:
    has_biomass = sig.area_biomass or sig.plant_biomass
    if not has_biomass:
        return ParameterAssessment(
            "c_rad_phot", AssessmentStatus.NOT_IDENTIFIABLE,
            ParameterLabel.ASSUMED,
            "无生物量曲线——效率参数无约束目标")
    if not sig.biomass_area_ready:
        return ParameterAssessment(
            "c_rad_phot", AssessmentStatus.DEGENERATE,
            ParameterLabel.ASSUMED,
            "株级生物量缺密度——1/rho 卷入 K_eff 乘积简并，"
            "c_rad_phot 不可单独分离")
    if sig.par_series:
        return ParameterAssessment(
            "c_rad_phot", AssessmentStatus.IDENTIFIABLE,
            ParameterLabel.FITTED,
            "实测 PAR 时序 + 面积基生物量——效率轴非简并，可单参数拟合"
            "（BJAAF Stage 1: 5.17e-9 kg/J）")
    if sig.ppfd_recipe:
        return ParameterAssessment(
            "c_rad_phot", AssessmentStatus.CONDITIONAL,
            ParameterLabel.FITTED,
            "PPFD 仅为配方/假设值——拟合值为 c_rad_phot x PPFD 条件值"
            "（UC Davis Stage 2: PPFD=250 假设下 5.17e-9）")
    return ParameterAssessment(
        "c_rad_phot", AssessmentStatus.DEGENERATE, ParameterLabel.ASSUMED,
        "无 PAR 信息——c_rad_phot 卷入 K_eff 乘积简并，不可单独分离")


def _assess_density(sig: DataSignature) -> ParameterAssessment:
    if sig.area_biomass:
        return ParameterAssessment(
            "rho", AssessmentStatus.IDENTIFIABLE, ParameterLabel.ANCHORED,
            "X_d 已为地面面积基——密度不进入校准")
    if sig.plant_biomass and sig.density:
        return ParameterAssessment(
            "rho", AssessmentStatus.IDENTIFIABLE, ParameterLabel.ANCHORED,
            "株级生物量 + 实测密度——换算可用；密度为外部测量输入"
            "（非拟合对象）")
    if sig.plant_biomass:
        return ParameterAssessment(
            "rho", AssessmentStatus.DEGENERATE, ParameterLabel.ASSUMED,
            "株级生物量缺密度——1/rho 卷入 K_eff 简并（T4 分析；"
            "UC Davis 密度由末期称重反推，11.31 株/m2）")
    return ParameterAssessment(
        "rho", AssessmentStatus.NOT_IDENTIFIABLE, ParameterLabel.ASSUMED,
        "无生物量观测——密度与校准无关")


def analyze_signature(sig: DataSignature) -> IdentifiabilityReport:
    """Apply the identifiability rule set to one dataset signature."""
    return IdentifiabilityReport(
        signature=sig,
        assessments=[_assess_c_pl_d(sig),
                     _assess_c_rad_phot(sig),
                     _assess_density(sig)],
    )
