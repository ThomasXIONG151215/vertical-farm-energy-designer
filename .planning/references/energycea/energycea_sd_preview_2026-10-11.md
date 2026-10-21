# EnergyCEA — ScienceDirect 公开可读内容存档（2026-10-11 抓取）

> 来源：https://www.sciencedirect.com/science/article/pii/S0306261926004769
> 抓取方式：r.jina.ai 渲染代理（Cloudflare 挑战下仍可拿到的 SD 公开预览变体）
> 性质：Highlights + Abstract + Keywords + Introduction 全文 + 4 个 Section snippets + CRediT/致谢。
> **方法学（Section 2）全文未包含**——SD 仅向交互式浏览器会话渲染全文（该文章为 Hybrid OA，
> 人工打开上述链接即可免费阅读/下载全文 PDF，CC BY-NC-ND）。

---

## Highlights

- Constructed the EnergyCEA multi-zone framework for PFALs energy simulation.
- Climate, equipment, and vertical scaling determine plant energy performance.
- Latent and sensible loads are primary drivers of regional energy variations.
- Ambient enthalpy governs energy limits, requiring climate-adaptive control.

## Abstract

High energy intensity remains a primary barrier for plant factories with artificial lighting, yet standard single-zone models fail to account for the thermodynamic heterogeneity inherent in large-scale production. To address this limitation, we developed EnergyCEA, a multi-zone simulation framework that couples a triple-zone physical environment model with a calibrated strawberry growth module to quantify the dynamic energy-yield nexus. Validated against operational data from a commercial facility, this study evaluates the non-linear energy penalties associated with vertical scaling and performs global psychrometric sensitivity analyses. Results show that strawberry cultivation exhibits a distinct energy structure. HVAC accounts for 65.3% of total consumption, driven by specific requirements for light-dark period temperature differentials and high transpiration rates. Furthermore, passive vertical expansion reaches a thermodynamic threshold where aerodynamic deficits eventually outweigh land-use benefits. The coupling of outdoor environment conditions and dynamic equipment Coefficient of Performance dictates seasonal energy variances, causing summer energy intensity to exceed winter baselines by 25%. Crucially, global psychrometric mapping indicates that ambient enthalpy governs theoretical limits. Cold climates leverage enthalpy-based free cooling to minimize specific energy consumption to 60.9 kWh/kg. In humid or hot regions, the thermodynamic penalties driven by extreme latent or sensible loads elevate energy intensity to a peak of about 70.0 kWh/kg. These findings underscore the need to shift from standardized facility designs to climate-adaptive control strategies for sustainable high-value crop production.

## Keywords

Plant factories with artificial lighting; Multi-zone energy simulation; Vertical scaling; Coefficient of performance; Psychrometric energy mapping

## Introduction（全文，摘自页面）

[Para 1] Controlled environment agriculture (CEA) has emerged as a resilient solution to global food security challenges [1], [2]. Plant factories with artificial lighting (PFALs) represent the most advanced form of environmental control compared with traditional greenhouses [3]. These fully enclosed systems effectively decouple crop production from external climate volatility and improve land-use efficiency [4], [5]. PFALs are widely used to cultivate high-value herbs, fruits, and vegetables, ensuring year-round reliable harvests [6], [7]. However, unlike solar-driven facilities, maintaining stable indoor conditions requires substantial energy inputs for artificial lighting and air conditioning [8]. Recent studies indicate that electricity consumption accounts for a major portion of total operating costs in PFALs [9], [10]. High energy intensity remains the primary barrier to the widespread commercial adoption of plant factories [11]. Therefore, developing precise simulation tools is essential to identify energy-saving potential and optimize system design and operation.

[Para 2] Accurate assessment of energy performance in PFALs requires a deep understanding of spatial thermodynamic heterogeneity. Existing simulation frameworks often overlook this factor, focusing instead on small-scale container factories with limited space utilization (Table 1). The lack of verifiable data associated with facilities exceeding a 200% space utilization threshold limits the ability to predict energy trends during vertical expansion. Additionally, standard building simulations typically assume a well-mixed air zone with uniform temperature and humidity [12]. While this single-zone assumption may be acceptable for container farms, it becomes inappropriate for large-scale PFALs [13], where high-density cultivation racks could greatly obstruct airflow [14]. This physical barrier traps heat and moisture within the canopy, creating distinct microclimates within the surrounding room air [15]. This thermodynamic deficit is a major technical barrier to the commercial growth of the industry. Therefore, a multi-zone framework is necessary to capture the heat and mass transfer between the crop canopy and the environment.

[Para 3] Current energy models primarily focus on vegetative crops, such as lettuce, leaving reproductive crops, such as strawberries, insufficiently characterized [16]. Lettuce production involves simple environmental control and short growth cycles (∼30 days) [17], with specific energy consumption typically ranging from 6 to 20 kWh kg−1 [3]. In these systems, artificial lighting is the dominant energy consumer, accounting for 60% to 80% of the total energy use [18]. Recently, commercial interest has been gradually shifting toward high-value cash crops, like strawberries, due to the increased financial challenges in lettuce factories [19]. Compared with lettuce, strawberries require more complex environmental conditions, including longer dark periods and larger temperature and humidity differentials between light and dark cycles [20]. Strawberries go through physiological shifts and maintain higher transpiration rates during fruit development [21]. These biological factors shift the dominant energy demand from lighting to HVAC systems. The energy for cooling and dehumidification has been reported to exceed 64% of total usage [22]. Unlike short-cycle crops, strawberries can remain productive for up to two years [6], necessitating long-term evaluation of the impacts of the external climate variability on energy consumption and overall crop profitability. Existing frameworks calibrated for lettuce fail to explicitly consider these crop-specific requirements, resulting in an underestimate of the cooling and dehumidification demands [23]. Therefore, a robust, crop-specific energy modeling framework is essential to support the sustainable operation of high-value fruit production.

[Para 4] Regional and seasonal climatic variations dictate the theoretical efficiency limits of PFALs, yet these impacts remain poorly quantified. Previous studies evaluating global energy performance often rely on dry-bulb temperature as the primary variable, which fails to account for the influence of absolute humidity on latent cooling loads [32]. In humid regions, the energy consumption for moisture removal via condensation frequently exceeds the cost of sensible cooling [33]. Many simulations assume a fixed coefficient of performance (COP) for HVAC systems, ignoring efficiency fluctuations caused by varying external environments [34]. This lack of systematic quantification limits the applicability of existing models across geographic locations and seasons. The energy penalty of replicating a standardized "one-size-fits-all" factory design across diverse climate zones has not been established, which hinders the global scaling of the industry [35]. Resolving these dynamics and decoupling the specific contributions of air conditioners and dehumidifiers are therefore essential to determine the true energy limits of PFALs.

[Para 5] This study establishes EnergyCEA, an integrated dynamic simulation framework designed to quantify the energy-yield nexus of PFALs. The framework uses a multi-zone dynamic model coupled with a calibrated strawberry growth module to capture internal thermodynamic interactions. This architecture resolves spatial heterogeneity in temperature and humidity, addressing the limitations of conventional single-zone models. Furthermore, the framework enables the evaluation of the non-linear energy trajectory associated with vertical scaling to identify tipping points for industrial expansion. To demonstrate global adaptability, we use enthalpy-based psychrometric mapping to quantify performance disparities across different climate zones. The main objectives of this study are:

- (1) To develop the EnergyCEA multi-zone framework for simulating dynamic energy and mass transfer in PFALs.
- (2) To identify the key parameters governing energy consumption within the simulation framework.
- (3) To evaluate the impact of regional climate variations and establish a global psychrometric energy map.

## Section snippets（SD 预览片段，每节截断）

### EnergyCEA framework architecture

The EnergyCEA framework operated on a structured input-process-output logic to quantify the energy-yield nexus of PFALs (Fig. 1a). The input layer established the boundary conditions by ingesting high-resolution weather data, facility geometric specifications, control setting and equipment specifications. The process layer served as the core calculation engine by integrating three coupled models to simulate system dynamics. These included a dynamic environment model for physical state changes, *[截断]*

### Model validation and microclimate accuracy

The EnergyCEA framework demonstrates high precision in predicting total energy consumption and environmental dynamics throughout the annual cycle. Validation uses operational data from a commercial strawberry plant factory in Hangzhou. As shown in Fig. 3, simulated energy consumption aligns with recorded operational data. The temporal distribution shows a distinct seasonal pattern, with energy demand peaking in July and August. This surge is driven primarily by cooling and dehumidification *[截断]*

### Future work

Future research will prioritize refining the physiological fidelity of the strawberry growth model to support continuous annual production. While the current framework effectively captures thermodynamic interactions, it relies on simplified assumptions regarding biological dynamics. Specifically, it lacks the capability to simulate complex assimilate partitioning between vegetative and reproductive organs over long-term cycles. The next iteration will integrate dynamic source-sink relationships *[截断]*

### Conclusion

This study established the EnergyCEA multi-zone framework to characterize the dynamic energy consumption of strawberry PFALs. Validated against commercial data, the simulation confirms that energy performance is governed by the interplay of outdoor climate, equipment efficiency, and vertical scaling. A key finding is that strawberry cultivation exhibits a distinct energy structure dominated by HVAC demands, differing significantly from lettuce production. The strict requirement for low *[截断]*

## CRediT / 致谢

**Fulin Xia:** Writing – original draft, Software, Methodology, Conceptualization. **Jinping Wang:** Writing – review & editing. **Xunyi Ma:** Formal analysis. **Luyu Shuai:** Validation. **Guichao Hua:** Resources. **Xiaoshuai Wang:** Writing – review & editing. **Tao Lin:** Writing – review & editing, Supervision.

This work was supported by Key R&D Program of Zhejiang Province under Grant Number: 2022C02003 and 4D Bios Inc.

## 建模相关的关键参考文献（从 Crossref 49 条全表筛出，可反推模型构成）

- [12 近邻] Altes-Buch 2022, *Build Simul* — 温室电-热系统集成建模框架（多区耦合先例）
- Weidner 2021 *Energy Convers Manag*; Weidner 2022 *Nat Food* — 不同气候区 PFAL/温室能量优化与 food-energy-land nexus（气候敏感性方法学源头）
- Graamans 2020 *Appl Energy* — 高内部热负荷下立面设计降需（多层 RF 集总传热先例）; Graamans 2018 *Agric Syst* — 资源效率对比
- Katzin 2021 *Appl Energy* — LED 节能（LED 热源建模）
- Song 2023 *J Clean Prod* — 容器农场能量模型（作物生长耦合）; Eaton 2023 *J Clean Prod* — 生菜资源消耗建模; Keyvan 2024 *Comput Electron Agric* — energy-yield-cost 集成模型
- Talbot 2024 *Appl Energy* — 环境条件对能耗与产量影响
- Choi 2025 *Energ Buildings* — 植物工厂空调系统性能/能耗对比（制冷季）
- Sezen 2022 *Energy Convers Manag* — ASHP 数学建模：COP 随室外温湿度（→ 动态 COP 来源）
- Mitrakusuma 2022 *ARFMTS* — 分体空调不同外温定相对湿度性能; Payne 2026 — R22 vs R410A 高环温对比
- Anwar 2022 *Front Appl Math Stat* — Adams/BDF 数值方法（→ 求解器线索：刚性多区 ODE 用 Adams/BDF，非简单 Euler）
- Kundu 2008 *Fluid Mechanics*（教科书 → 对流换热系数推导）
- 标准 bb0240 "Energy performance of buildings — Ventilation for buildings"（→ 通风/渗风计算规范来源，疑为 EN 16798-1/ISO 家族）
- Woods 2022 *Joule* — 湿度对空调碳排放影响（潜热负荷重要性）
- Shi 2025 *Appl Energy* — 混合间接蒸发冷却（数据中心，热湿地区）（→ enthalpy-based free cooling 相关）
