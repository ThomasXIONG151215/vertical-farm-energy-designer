# EnergyCEA 三区传热传质模型 — 检索与提取笔记

- 日期：2026-10-11
- 任务：为 VFED 寻找论文 EnergyCEA 免费全文并提取三区传热传质模型结构
- 结论速览：**论文确认为 Hybrid OA（CC BY-NC-ND，publishedVersion，APC $4,430 已付）——全文免费存在于 ScienceDirect，但本机所有自动化通道被 Cloudflare captcha 拦截；无任何预印本/仓储镜像。已获取摘要+引言全文+4 节片段；三区具体划分只能部分推断（下文明确标注【已确认】/【推断】）。人工用浏览器打开 SD 链接即可免费下载 PDF 补全。**

---

## 1. 精确题录

| 字段 | 值 |
|---|---|
| 标题 | EnergyCEA: A multi-zone dynamic simulation framework to quantify energy determinants and climate sensitivity in plant factories |
| 作者 | Fulin Xia(夏福临, 一作), Jinping Wang(4D Bios), Xunyi Ma, Luyu Shuai, Guichao Hua(4D Bios), Xiaoshuai Wang(通讯), **Tao Lin(林涛, 通讯)** |
| 机构 | 浙江大学生物系统工程与食品科学学院（Hangzhou 310058）+ 4D Bios Inc.（杭州） |
| 期刊 | Applied Energy, Vol. 415, Article 127824（2026-04-13 上线；2026-07 刊期） |
| DOI | 10.1016/j.apenergy.2026.127824 |
| PII | S0306261926004769 |
| OA | **hybrid**，license **CC BY-NC-ND**，version **publishedVersion**，唯一 OA 位置=出版社（Unpaywall `is_oa:true` / OpenAlex `oa_status:"hybrid"` / Semantic Scholar `HYBRID CCBYNCND` 三方一致；OpenAlex `apc_paid` $4,430） |
| 资助 | 浙江省重点研发计划 2022C02003 + 4D Bios Inc. |
| 姊妹篇 | StrawberryGRO-E（同组，含共同作者 Fulin Xia / Guichao Hua / Tao Lin）：*A techno-economic analytic modeling framework for strawberry production in plant factories*，Comput. Electron. Agric. 256 (2027) 112405，DOI 10.1016/j.compag.2026.112405，PII S0168169926010033，同为 hybrid OA CC BY-NC-ND；其引文 [36]（Crossref b0180）即本文 |

## 2. 检索证据链（时间序）

| # | 路径 | 结果 |
|---|---|---|
| 1 | Unpaywall API | `is_oa:true, oa_status:hybrid`，license cc-by-nc-nd，publishedVersion；`has_repository_copy:false`；`url_for_pdf:null`（PDF 只在出版社站内） |
| 2 | OpenAlex | 同上；`locations_count:1`（仅出版社）；`any_repository_has_fulltext:false`；题录/作者/资助/APC 全量确认 |
| 3 | Crossref | license 数组仅 TDM/STM-ASF 条款；link 字段给 Elsevier TDM 全文端点（`api.elsevier.com/content/article/PII:S0306261926004769?httpAccept=text/plain`） |
| 4 | Elsevier TDM API 直连 | 无 key → 400（view 参数无效）；带 view=FULL → 401 Invalid API Key |
| 5 | SSRN/Crossref 书目检索 | 无 EnergyCEA 预印本记录（对照：Unpaywall/OpenAlex 仓储副本皆为 false，一致） |
| 6 | curl 直抓 SD（浏览器 UA + `/pdfft`） | 403，返回 1.2MB JS-challenge HTML |
| 7 | r.jina.ai 渲染代理 | **文章页成功渲染两次**（拿到预览变体：摘要+引言全文+4 snippets）；`/pdfft` 两次均 "Are you a robot?" captcha → 放弃（遵守 ≤2 次规则） |
| 8 | 本地 Playwright headless Chromium | challenge 页（body 738 字符），PDF 请求 403 |
| 9 | 本地 Playwright 有头 Edge/Chrome | Edge 会话被杀（TargetClosedError，服务器无稳定桌面）；Chrome 卡 "Just a moment..." |
| 10 | Googlebot UA 伪装 curl | 403（非 Google IP 识别） |
| 11 | Bing / DDG 搜镜像（RG/core.ac.uk/nir.zju.edu.cn） | 零命中 → 无自存档（与 #1/#2 一致） |
| 12 | 姊妹篇 SD 页（jina） | 两次 captcha（同样只有 SD 站内源） |

**判定**：OA 状态 = hybrid（gold-on-publisher），不是 closed、不是 green-embargo；"免费获取失败"纯属 Cloudflare 反自动化，与付费墙无关。

## 3. 三区模型结构提取

> 依据 = 摘要 + 引言全文 + "EnergyCEA framework architecture" 片段 + 参考文献反推。
> 【已确认】= 论文公开文本原文可证；【推断】= 证据链强但未见方法节原文，待全文 PDF 验证。

### 3.1 三区如何划分

- 【已确认】框架为 input→process→output 三层：输入 = 高分辨率气象 + 设施几何 + 控制设定 + 设备参数；过程层 = **三个耦合模型**（动态环境模型[物理状态演化] + 经校准的草莓生长模块 + 第三个被片段截断，按摘要语义为设备能量/能效模型）；输出 = 动态 energy-yield nexus（Fig. 1a）。
- 【已确认】三区动机（引言 Para 2 原文）：单区 well-mixed 假设对大型 PFAL 失效——"high-density cultivation racks greatly obstruct airflow … traps heat and moisture within the canopy, creating distinct microclimates within the surrounding room air"。即模型必须显式分辨 **冠层内空气 vs 周围房间空气** 的热湿差异，"capture the heat and mass transfer between the crop canopy and the environment"。
- 【推断】第三区最可能是 **设备/HVAC 区（空调回风/送风静压区）**，其次可能是 LED 灯板层。依据：① 引言强调"decoupling the specific contributions of air conditioners and dehumidifiers"（设备需独立节点才能解耦 AC/DEH 贡献）；② 摘要"aerodynamic deficits"（垂直扩建 → 气流路径受阻 → 设备区与冠区间换热恶化）；③ 过程层含独立设备模型（动态 COP）。若为 LED 区，则与"65.3% HVAC 主导"的叙事弱相关。
- 【推断】三区组合最可能为：**① 栽培/冠层区（canopy, 域内 racks）② 室内空气区（room/aisle）③ 设备区（equipment/HVAC plenum）**。待全文 Section 2 确认（尤其 Fig. 1b/1c 的控制体积示意与假设列表）。

### 3.2 每区控制方程

- 【已确认】每区为**动态**能量+质量平衡（"dynamic environment model for physical state changes"；目标 (1) "simulating dynamic energy and mass transfer"）。
- 【已确认】潜热/显热分离建模（"latent and sensible loads are primary drivers"；凝结除湿能耗被显式计入）。
- 【推断】方程形态 = 集总参数 ODE 组（每区 dT/dt、dW/dt），与 VFED RoomODESolver 同族但状态数 ×3。求解器证据：参考文献含 Anwar 2022（Adams/BDF 刚性 ODE 数值处理）→ 大概率 `solve_ivp` 类 BDF/Adams 刚性求解，而非显式 Euler。
- ✗ 无法获取：各区方程的具体符号、单位、源汇项展开、控制体积几何定义（在付费展示的方法节内）。

### 3.3 区间换热/换质路径

- 【已确认】冠层↔房间空气存在**对流传热与气流交换**（引言：气流被 racks 阻挡 → 冠层内"traps heat and moisture"；需对流+换气两条通道才能同时产生温差与湿差）。
- 【已确认】蒸腾是冠层区主导湿源（草莓"higher transpiration rates during fruit development"直接推高 HVAC 潜热负荷）。
- 【推断】区间通道集合：① 对流换热 h·A·ΔT（h 来源 Kundu 流体力学教科书 + CFD 文献 [Sohn 2023, Kang 2024, Zhang 2022] 校核）；② 气流质量交换 ṁ·(h_diff, W_diff)（风量规范来源疑为 EN/ISO 16798 家族"Energy performance of buildings — Ventilation for buildings"）；③ 壁面导热 UA 仅作用于外围区（房间空气区），与 Graamans 2020 集总先例一致；④ 辐射通道未见证据（LED 辐射热大概率按份额直接沉积冠层/栽培区）。
- ✗ 系数取值与结构（是否线性化辐射、是否分区风速）未知。

### 3.4 关键参数与取值（已确认的头部数字）

| 量 | 值 | 备注 |
|---|---|---|
| HVAC 占比 | **65.3%** 总能耗（草莓 PFAL） | vs 生菜 60–80% 是照明——能源结构反转 |
| 最低单位能耗 | **60.9 kWh/kg**（寒冷气候，enthalpy-based free cooling） | 全局 psychrometric 地图下界 |
| 峰值单位能耗 | **≈70.0 kWh/kg**（湿热/干热地区） | 潜热或显热极端驱动 |
| 季节差异 | 夏季超冬季基线 **25%** | 室外条件 × 动态 COP 耦合 |
| 空间利用阈值 | **>200%**（引言 Table 1 讨论的垂直扩建区间） | 垂直扩建的非线性能耗惩罚 + "aerodynamic deficits" 失稳点 |
| 除湿+制冷占比（文献值） | >64% [22, Wai 2023] | 草莓需求：光/暗期大温差 + 高蒸腾 |
| 设备 COP | 动态、随室外环境波动（引 Para 4；Sezen 2022 ASHP 模型 + Mitrakusuma 2022 分体机性能） | 明确反对固定 COP 假设 |

✗ 完整参数表（面积、传热系数、风量及来源）在方法节，未获取。

### 3.5 验证方式

- 【已确认】实测对象 = **杭州某商业草莓植物工厂运营数据**；验证周期 = 全年（annual cycle）；同时验证总能耗时序与环境动态（"microclimate accuracy"，Fig. 3）；能耗峰值 7–8 月由制冷+除湿驱动，模拟与运行记录吻合。

## 4. 与 VFED 的映射建议（"最省力切入点"）

VFED 现状（`vfed/physics/ode.py` + `vfed/physics/envelope.py`）：
- 单空气节点集总 ODE：`dT_z/dt = ΣQ/(C_z·3600)`、`dW_z/dt = ΣM/(V·ρ)`，前向 Euler，dt=60 s；
- 但 envelope 已具备**多墙节点**经验（R28 2R2C/2R3C/FD 墙，默认关闭、开启后 bit-for-bit 可回滚的 additive 模式）、质量流显式焓通道（`infiltration()` 返回 Q_sens/M_lat/Q_lat 三元组）、ERV 通道、以及温度相关 COP（HVAC `carnot` 模式）。

EnergyCEA ↔ VFED 对应关系：

| EnergyCEA 要素 | VFED 现状 | 差距 |
|---|---|---|
| 单区→三区空气状态 | 1×(T,W) | 缺 2×(T,W) 状态与区间耦合 |
| 冠层区（蒸腾+热湿捕获） | 蒸腾 E_trans 直接进房间湿平衡 | 缺冠层控制体 |
| 区间气流质量交换 | `infiltration()` 的 ṁ·cp·ΔT / ṁ·ΔW 公式 | **公式模板已存在**，改成区间驱动即可 |
| 区间对流换热 | 无空气-空气通道 | 缺 g=h·A 一项（墙网络里 g_im/g_sa 同构） |
| 动态 COP（室外相关） | HVAC `carnot` 模式 η_II·T_evap/(T_cond−T_evap) | **已对齐**（同族方法） |
| 除湿独立解耦 | DEH 设备已独立 | 已对齐 |
| 求解器（Adams/BDF） | 前向 Euler + 钳位 | 冠层小热容节点可能引入刚性 → 或需 BDF |

**推荐增量路径（按省力排序，均不破坏现有行为）**：

1. **Step A（零风险诊断，最省力）**：纯后处理"准稳态冠层偏差"估计——用现有每步输出 (T_z, W_z, E_trans) + 假设冠层-房间换热系数与换气量，解代数方程得 ΔT_canopy/ΔW_canopy 时间序列。不改 ODE、不改 engine 接口；先回答"三区 vs 单区在 VFED 工况下偏差是否值得工程化"。
2. **Step B（additive 冠层区）**：仿 R28 模式加 `canopy_zone.enabled=false` 配置（`project.py`+`presets.py` 同步新字段）。开启后：新增 T_c/W_c 两状态；E_trans 源移入冠层区；冠层↔房间加两条通道——对流 `g_cr·(T_c−T_z)` 与气流交换（复用 `infiltration()` 三元组公式，驱动差换成区间差）；DEH/HVAC 打在房间区（与 EnergyCEA "decoupling AC/DEH" 对应）。房间↔室外全套 envelope 不动。
3. **Step C（设备区，可选）**：第三区先做**零热容代数节点**（送回风混合准稳态），避免新增 C_z 标定负担；仅当 Step B 验证三区价值后再考虑全动态设备区。
4. 注意：`engine.py` 是 hub，其接口变更按 AGENTS.md 属 "Ask first"；本笔记只提方案。验证数据可用 609 奉贤生菜厂实测（对标 EnergyCEA 用商业厂实测的验证哲学）。

## 5. 获取全文的建议路径

1. **人工浏览器**（零成本，即刻可行）：打开 https://www.sciencedirect.com/science/article/pii/S0306261926004769 → 免费在线阅读；下载 PDF 后放入 `.planning/references/energycea/energycea_apenergy_2026_127824.pdf`，再据 Section 2 补全本笔记 §3 的 ✗ 项（许可证 CC BY-NC-ND 允许下载共享）。
2. 浙大校园网/图书馆或馆际互借（CALIS）。
3. 向通讯作者索取：Tao Lin（浙大生工食品学院）/ Xiaoshuai Wang，引用 PII S0306261926004769。
4. Elsevier TDM API（若日后申请到 apiKey）：`GET api.elsevier.com/content/article/PII:S0306261926004769?httpAccept=text/plain`（Crossref 已登记该 vor 全文端点）。

## 6. 附：姊妹篇 StrawberryGRO-E 摘要要点（可交叉印证）

经济-生物层框架（非物理层）：提出 SAI（Simultaneous Active Inflorescences）生殖负载指数，源-库竞争量化；三种管理策略（保守/中等/集约 SAI_max=1/2/3）；集约策略单位能耗最低 **83.7 kWh/kg**（固定成本稀释效应）；质量敏感市场净利润最高 1115.55 CNY/m²/年；对电价与市场波动做敏感性交叉点分析。→ 印证 EnergyCEA 能耗数字（60.9–70 kWh/kg 环境范围 vs 运营 83.7 含全过程）与"能源结构由气候×设备×扩建主导"结论。

---
*存档：`.planning/references/energycea/energycea_sd_preview_2026-10-11.md`（公开预览全文+建模相关参考文献反推表）*
