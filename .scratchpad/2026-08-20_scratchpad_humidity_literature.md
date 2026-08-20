# Scratchpad: 密闭植物工厂湿度平衡与控制建模调研

## 1. Background and Motivation
- 609 项目 ODE 仿真冬季暗期 RH 崩溃到 3–10%（物理不可能）。
- 根因：①暗期蒸腾=0；②渗透项 M_lat=m_dot×(W_ext−W_z) 冬季把 RH 压到室外平衡点；③无加湿器。
- 任务：文献调研，为三项建模缺口提供校准依据（纯研究，不写代码）。

## 2. Key Challenges and Analysis
- 暗期蒸腾：E_night/E_day 典型 5–15%（Caird 2007, Plant Physiol 143:4-10），最高 30%；葡萄 5–13%（Dayer 2021, PCE）。生菜暗期 gs/g_day=0.11–0.39（Kim 2004, Ann Bot 94:691）。植物工厂夜间 VPD 不降（65%RH@18°C≈0.73 kPa）→ 建议暗期因子 0.10–0.15。
- 渗透：密闭 PFAL 换气率 N≈0.01–0.02 h⁻¹（Kozai 2013; WUR WPR-1315），可近 0（WUR Bleiswijk）。VFED 现 ach=0.5 偏高 ~25–50×。m_dot×(W_ext−W_z) 形式本身是标准全混合模型（ASHRAE/EnergyPlus），问题在 ACH 量级与通风调度。
- 蒸腾模型：Graamans 2017 ET=LAI·VCD/(rs+ra)；rs=60(1500+PPFD)/(200+PPFD)，ra=100(强制)/200(自然)。VFED van_henten k=1e-4（1/s/kPa）×X_d×VPD。
- 湿度控制：生菜 RH 50–70%（Cornell Handbook）；叶菜 VPD 0.65–0.9 kPa（Kozai; Ahamed 2023）。双边控制（除湿+加湿）、死区 ±2–5% RH。

## 3. High-level Task Breakdown
- [x] 文献检索（夜间蒸腾 / ACH / ERV / 蒸腾模型 / 湿度控制设定）
- [x] 代码定位（project.py ach=0.5; transpiration.py light_factor; envelope.py infiltration; dehumidifier.py）
- [x] 撰写结构化中文报告（输出中）

## 4. Project Status Dashboard
- 调研完成度 100%。核心参考文献：Caird 2007; Dayer 2021; Kim 2004; Graamans 2017; Talbot&Monfet 2024; Kozai 2013/Plant Factory 2nd ed; WUR WPR-1315; FAO-56; Cornell CEA Lettuce Handbook。
- 校准建议已给出：暗期因子 0.10–0.15；ACH→0.05–0.15（或 ERV ε_lat 0.5–0.7 或通风调度）；加湿器建模必要（容量=渗透干燥−暗期蒸腾）。

## 5. Executor Feedback or Help Requests
- 无阻塞。实现阶段注意：新配置字段（ach 标定、night_factor、humidifier）需同步 project.py + presets.py + engine。
