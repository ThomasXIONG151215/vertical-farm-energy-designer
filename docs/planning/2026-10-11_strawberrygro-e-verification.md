# StrawberryGRO-E 文献核查报告（VFED Q2）

- **核查日期**：2026-10-11
- **核查对象**：Fu, Rongmei, et al. "StrawberryGRO-E: A techno-economic analytic modeling framework for strawberry production in plant factories." *Computers and Electronics in Agriculture* 256 (2027): 112405.
- **核查目的**：验证该文是否为 VFED 规划文档 §6 Q2 所指「林涛团队的三区传热传质」模型文献。
- **证据来源**：Crossref API、OpenAlex API、Semantic Scholar API、Unpaywall/S2 OA 元数据、RePEc/IDEAS 镜像、colab.ws 镜像、DDG/Bing 检索快照。**未读取付费墙/反爬后的正文全文**（见 §6 证据边界）。

---

## 1. 书目信息（存在性 ✅ 已确认）

| 字段 | 值 |
|---|---|
| 标题 | StrawberryGRO-E: A techno-economic analytic modeling framework for strawberry production in plant factories |
| **DOI** | **10.1016/j.compag.2026.112405** |
| 期刊 | Computers and Electronics in Agriculture（ISSN 0168-1699，Elsevier，SCImago Q1） |
| 卷/文章号 | Vol. 256, Article 112405（与用户引用完全一致） |
| 在线日期 | 2026-09-12（OpenAlex `publication_date`） |
| 卷期标注 | 2027 年 1 月卷（Crossref `issued: 2027-01`）——「卷标 2027 但今天 2026-10」属期刊提前编卷，正常 |
| PII | S0168169926010033 |
| 参考文献数 | 46 |
| 索引一致性 | Crossref / OpenAlex / Semantic Scholar / RePEc 四源一致 |

**结论：该文献真实存在，书目信息与用户提供的引用逐字吻合。**

## 2. 作者团队与林涛关系 ✅ 已确认

完整作者列表（依 Crossref/OpenAlex，共 7 人）：

| # | 作者 | 单位 | 备注 |
|---|---|---|---|
| 1 | **Rongmei Fu（傅荣梅*）** | 浙江大学生物系统工程与食品科学学院，杭州 310058 | 第一作者 |
| 2 | Wei Liu | 同上 | |
| 3 | Fulin Xia | 同上 | 亦为 EnergyCEA 第一作者（见 §3） |
| 4 | Renhai Zhong | 浙江大学农业遥感与信息技术应用研究所 | |
| 5 | K.C. Ting | University of Illinois Urbana-Champaign，农业与生物工程系 | 著名设施农业工程学者 |
| 6 | Guichao Hua | 4D Bios Inc.，杭州 | 企业方 |
| 7 | **Tao Lin** | 浙江大学生物系统工程与食品科学学院 | **通讯作者**（OpenAlex `is_corresponding: true`），ORCID **0000-0001-9721-5363**（ORCID 记录确认其雇佣单位为 Zhejiang University） |

*中文名仅「傅荣梅」音译推测，未独立核实。

**与「林涛团队」的关系**：
- Tao Lin 为本文**通讯作者（末位作者）**，单位浙江大学——与规划文档 Q2 所述「林涛团队」匹配。
- 该团队近期成果（OpenAlex 检索）：EnergyCEA（Appl. Energy 2026，Tao Lin 通讯）、生菜动态光效 3D 表型（Comput. Electron. Agric. 2025，Tao Lin 通讯）、ChatCEA 智能问答代理（2026）等，均围绕植物工厂（PFAL）环境-能源-作物方向，属同一持续课题组（浙大 + 4D Bios）。
- 「Tao Lin = 林涛」的中文写法：ORCID 仅登记拼音，公开网络检索受限于反爬未能直接取得中文署名页；结合「浙大·生物系统工程·植物工厂」语境与用户 Q2 表述，判定为**高置信推断**（非逐字核验）。

## 3. 方法结构：是否包含三区传热传质 ⚠️ 关键发现

### 3.1 StrawberryGRO-E 本身（摘要层面）

摘要要点（OpenAlex 全文摘录）：
- 研究动机：PFAL 经济性受高支出与产量异质性制约；即使宏环境均匀，内源节律与微环境波动导致**花序异步重叠**，是产出波动的关键生物驱动。
- 提出 **SAI（Simultaneous Active Inflorescences，同时活跃花序数）指数**量化动态生殖负荷，并做源-库（source-sink）竞争生理实验。
- 将上述关系纳入 **StrawberryGRO-E 技术经济解析建模框架**，评估三种花序管理策略：Conservative（SAI_max=1）/ Moderate（=2）/ Intensive（=3）。
- 结果：Intensive 策略**单位能耗最低 83.7 kWh/kg**（摊薄固定成本）；Moderate 在品质敏感高端市场净利最高 **1115.55 CNY/m²/年**；敏感性分析给出电价与市场波动下的盈利交叉点。
- 检索快照中的结论句：「为草莓生产从产量导向管理转向价值优化商业运营提供量化工具」。

**摘要中未出现「three-zone / 三区」字样**。本文的重心是**生物学（花序管理）× 技术经济分析**，而非传热传质建模本身。

### 3.2 三区模型的真正出处：同团队前作 EnergyCEA

StrawberryGRO-E 参考文献第 [36] 条：

> Xia, F., Wang, J., Ma, X., Shuai, L., Hua, G., **Wang, X.** (corr), **Lin, T.** (corr). "**EnergyCEA: A multi-zone dynamic simulation framework to quantify energy determinants and climate sensitivity in plant factories**." *Applied Energy* 415 (2026) 127824. **DOI: 10.1016/j.apenergy.2026.127824**（在线 2026-04-13；PII S0306261926004769）

EnergyCEA 摘要（RePEc 全文摘录）核心句：

> "we developed EnergyCEA, a multi-zone simulation framework that couples a **triple-zone physical environment model** with a calibrated strawberry growth model..."

要点：
- **明确针对单区模型的不足**："standard single-zone models fail to account for the thermodynamic heterogeneity inherent in large-scale production"——即三区 vs 单区的对立正是该文立论。
- 与校准草莓生长模型耦合，**用杭州某商业草莓植物工厂运行数据全年验证**（能耗总量与环境动态预测精度高）。
- 能耗结构：HVAC 占 65.3%；被动垂直扩层存在气动短板的热力学阈值；室外环境 × 设备动态 COP 耦合决定季节差异（夏季强度超冬季基线 25%）。
- 全局湿空气敏感性分析：环境焓主导理论极限，冷凉气候利用焓差免费供冷低至 60.9 kWh/kg，湿热地区显热/潜热惩罚使峰值达约 70.0 kWh/kg。

**团队内继承关系**：EnergyCEA 第一作者 Fulin Xia 是 StrawberryGRO-E 的第三作者；两文通讯作者均含 Tao Lin（EnergyCEA 另有 Xiaoshuai Wang 共同通讯）。Semantic Scholar 显示 EnergyCEA 目前全网唯一施引文献即 StrawberryGRO-E 本身。

**推断（标注为推断）**：StrawberryGRO-E（后缀 "-E" = Economics/技术经济层）大概率在能量侧**复用或简化继承 EnergyCEA 的三区物理模型**（其 83.7 kWh/kg 的能耗口径与 EnergyCEA 的 60.9–70.0 kWh/kg 谱系一致），但其摘要与可获得的元数据中**未声明**这一点，正文不可自动获取，无法逐字确认。

### 3.3 三区的具体分区方式

EnergyCEA 摘要仅给出 "triple-zone physical environment model" 的定性表述；**具体分区命名（如灯具区/冠层区/冠下空气区之类的划分）与各区平衡方程结构需读正文才能确认**。其参考文献谱系（CROPGRO-strawberry 作物模型、ASHP 变工况 COP 实验关联式、Joule 湿度-空调排放、CFD 气流均匀性系列）支持「集总参数分区 + 湿空气物性 + 动态 COP」的建模风格，与 VFED 现有技术栈（psychrometrics + Carnot COP + ODE）高度同构。

## 4. 获取方式

| 渠道 | 状态 |
|---|---|
| ScienceDirect 正式版 | **Hybrid OA，CC BY-NC-ND**——人工浏览器访问免费全文（StrawberryGRO-E 与 EnergyCEA 均是） |
| 预印本 / 机构仓库 | 未发现（OpenAlex `any_repository_has_fulltext: false`；arXiv/ResearchGate 无副本线索） |
| 自动抓取 | 被 Cloudflare 拦截（403）；Elsevier TDM API 需密钥 |
| 建议路径 | 浏览器直接打开两文 DOI 页即可免费下载 PDF；如需文本挖掘可申请 Elsevier API key |

## 5. 对 VFED Q2 的结论

**判定：部分成立（对的团队、对的作物体系，但不是三区模型的主文献）。**

- 「是不是这篇」→ **是林涛团队的草莓植物工厂系列论文之一，但「三区传热传质」的直接出处是同团队姊妹篇 EnergyCEA（Appl. Energy 2026），而非本篇**。StrawberryGRO-E 是该系列的技术经济层（SAI 花序管理 × 利润敏感性），其摘要不含三区建模内容；它以引文 [36] 依赖 EnergyCEA。
- 对 VFED 的落地建议：
  1. **Q2 的「沿用三区传热传质」应以 EnergyCEA（DOI 10.1016/j.apenergy.2026.127824）为蓝本文献**——其立论（单区无法刻画大规模 PFAL 热力学异质性）、验证方式（商业厂全年运行数据）与 VFED 的「一维可校准」路线直接对齐；其「室外环境 × 动态 COP 耦合」「环境焓主导能耗极限」与 VFED 现有 Carnot COP、psychrometrics、PV-BES 调度可自然衔接。
  2. StrawberryGRO-E 对 VFED 的价值在**技术经济评估层**（单位能耗 kWh/kg 口径、净利 CNY/m²/年、电价敏感性）——可作为 VFED sweep/LCOE 输出指标体系与结果合理性对照带（如生菜 609 预设的能耗强度落位）；其 SAI 源-库生物学属于草莓专属作物模型，超出 VFED 当前「能源仿真为主」的范围，不必引入。
  3. 若确认沿用，建议先人工下载 EnergyCEA 正文，明确三区定义与状态量划分，再决定「重构单区 ODE」还是「仅作验证参照」（Q2 的原始分叉）。

## 6. 证据边界说明

1. **未读正文**：两篇均为 ScienceDirect hybrid OA，但自动抓取被反爬拦截；本报告关于方法结构的结论基于摘要（OpenAlex/RePEc 完整摘要）、参考文献列表（Crossref）与引用网络（Semantic Scholar），**未含正文/公式/图表**。
2. **「StrawberryGRO-E 内部是否复用三区模型」为推断**：由「共同作者（Fulin Xia）+ 引用关系 + 能耗口径谱系」支持，置信度中高，但无正文逐字证据。
3. **三区具体划分（各区命名与守恒方程结构）未知**：EnergyCEA 摘要仅有 "triple-zone physical environment model" 定性表述。
4. **「Tao Lin = 林涛」为中文名推断**：ORCID 仅拼音 + 浙大雇佣记录佐证身份，中文署名页未取得。
5. **第一作者中文名「傅荣梅」为音译推测**，未核实。
6. Unpaywall API 对该 DOI 返回空（疑似尚未收录），OA 判定以 OpenAlex + Semantic Scholar 双源一致为准（hybrid / CC BY-NC-ND）。

---

### 附：关键标识符速查

| 文献 | DOI | 卷期 | 角色 |
|---|---|---|---|
| StrawberryGRO-E（Fu et al.） | 10.1016/j.compag.2026.112405 | CE_A 256 (2027) 112405 | 技术经济层（SAI×利润），Q2 候选引用 |
| EnergyCEA（Xia et al.） | 10.1016/j.apenergy.2026.127824 | Appl. Energy 415 (2026) 127824 | **三区物理环境模型主文献**，Q2 蓝本建议 |
