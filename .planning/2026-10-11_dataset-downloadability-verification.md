# 植物工厂运行数据资源清单 —— 链接与可下载性核查报告

> **核查日期**：2026-10-11
> **核查对象**：`data/植物工厂运行数据资源清单.md`（原清单检索日期 2026-10-10）
> **核查方式**：逐条 webfetch 页面抓取 + figshare/Zenodo/Crossref API 元数据查询 + `curl -I` HEAD 请求验证下载直链（**未实际下载数据文件本体**）
> **核查结论速览**：共核查 32 条外部链接：**✅ 有效 23 / ↪️ 重定向 3 / ❌ 失效或张冠李戴 4 / ⚠️ 无法当场核实 2**。数据资源 21 个入口：**✅ 直接下载 12 / 📧 注册后下载 2 / 📋 需申请审批 1 / 💰 付费 2 / ❌ 不可得或暂时不可下 4**。

---

## 1. 核查汇总表

### 1.1 数据集条目（原清单编号 1–13）

| # | 数据集 | 链接状态 | 可下载性 | 实测/记录大小 | 许可 |
|---|--------|----------|----------|----------------|------|
| 1 | AGC 2018 黄瓜（figshare 12717758） | ↪️ 有效（权威页面已迁至 data.4tu.nl，figshare API + 下载直链 200 OK） | ✅ 直接下载 | data.zip **8.98 MB**（HEAD 实测 200，Content-Length 8,975,944） | CC0 |
| 2 | AGC 2019 番茄（figshare 12764777） | ↪️ 有效（同上） | ✅ 直接下载 | edition2.7z **8.42 MB**（HEAD 实测 200） | CC0 |
| 3 | AGC 2022 生菜时序（4TU DOI 10.4121/21960932.v1） | ✅ 元数据页有效，但 ⚠️ **文件暂不可下载**（4TU 存储维护，公告称约 2026-10-11 恢复） | ⚠️ 暂时不可下（平台维护） | 约 45 GB（原清单值；维护横幅遮挡文件列表，未核验） | CC BY 4.0 |
| 4 | 意大利垂直农场能源情景（amsacta 8914） | ✅ 有效 | ✅ 直接下载（302→200 实测） | Dataset_Energy_Scenarios_in_VF.xlsx **2 MB** + README.rtf 119 kB | CC BY 4.0 |
| 5 | 比利时番茄温室微气候（Mendeley tkbkzzdt5nr/2） | ✅ 有效（v2，2024-04-29） | ✅ 直接下载（页面有 Download All） | 未核验（Mendeley 文件 API 返回 400） | CC BY 4.0 |
| 6 | UC Davis 生菜多模态（Zenodo 17041810） | ✅ 有效（API + HEAD 200） | ✅ 直接下载 | Lettuce_growth.zip **742.9 MB**（HEAD 实测 200） | CC BY 4.0 |
| 7 | HydroGrowNet Batavia（Mendeley g6cm3v3wdp） | ↪️ 有效（无版本号 URL 重定向至 **v5**，2025-06-16 发布） | ✅ 直接下载 | 4.22 GB（原清单值，未核验） | CC BY 4.0 |
| 8 | 温室生菜生长模型数据（Mendeley r7z9ttvkyh/2） | ✅ 有效（v2，2024-11-28） | ✅ 直接下载 | 未核验 | CC BY 4.0 |
| 9 | PPFD/DLI 校准验证（Zenodo 21910738） | ✅ 有效（2026-08-13 新发布） | ✅ 直接下载 | 17 个文件合计 **约 6.4 MB**（API 实测：主数据 xlsx 1.7–2.1 MB ×2 + Colab notebook + 图表文档） | CC BY 4.0 |
| 10 | Kaggle Lettuce Growth Days | ✅ 页面存在（标题确认；正文需 JS 渲染） | 📧 免费注册后下载 | 3169 条（原清单值，未核验） | Kaggle 开放 |
| 11 | IEEE DataPort 垂直农场光配方（DOI 10.21227/367s-gr63） | ✅ 有效（DOI、页面、文件均确认） | 💰 **需 IEEE DataPort 付费订阅**（页面明示 "Subscription Required"，非免费注册；IEEE 学会会员可享） | Dataset.csv **50.95 KB**（页面标注，与原清单 51 KB 一致） | 订阅制 |
| 12 | 番茄温室气候-作物仿真（Zenodo 6697043） | ✅ 有效（concept→version 6697044） | ✅ 直接下载 | ds.csv **12.8 MB**（HEAD 实测 200） | CC BY 4.0 |
| 13 | 中国植物工厂温湿度（NBSDC） | ✅ 页面模板加载（元数据 JS 渲染不可见；页脚弹窗"暂无权限，请先注册或登录"） | 📋 需注册+申请审批（与原清单一致） | 1 分钟间隔 / 24 h（原清单值，未能独立核实） | 申请制 |

### 1.2 附录补充数据入口

| 编号 | 资源 | 链接状态 | 可下载性 | 大小 | 许可 |
|------|------|----------|----------|------|------|
| A1 | Zenodo 16912088（原清单称"伴生记录"） | ✅ 有效 | ✅ 直接下载 | **实为 UC Davis 数据集的概念 DOI（concept record），自动指向最新版 17041810**，742.9 MB | CC BY 4.0 |
| A2 | Zenodo 16912089（原清单称"伴生记录"） | ✅ 有效 | ✅ 直接下载 | **实为同一数据集 v1.0 旧版本**（2025-08-20 发布），742.9 MB；v1 元数据写栽培周期 2022 年，v2 已改为 2024 年（作者修正笔误） | CC BY 4.0 |
| A3 | CERTH 垂直农场能耗（Zenodo 16926135） | ✅ 有效（API 确认 103 个文件） | ✅ 直接下载 | 主文件 Scenarios_Values_FINAL.xlsx 107.8 MB，合计 **约 156 MB**（与原清单 163 MB 相符） | CC BY 4.0 |
| A4 | 四维生态植物工厂数据（zjip.org.cn 公告 7560） | ⚠️ 站点可达但公告内容 JS 渲染不可见（静态抓取仅返回平台标题"浙江省数据知识产权登记平台"） | 💰 付费授权（按平台性质；内容未当场核实） | 2000+ 条（原清单值） | 交易制 |
| A5 | AGC 2022 伴生图像集（DOI 10.4121/15023088） | ✅ 元数据有效（"3rd AGC: Online Challenge Lettuce Images"，2021-08-18） | ⚠️ 暂时不可下（同 4TU 维护） | 1 个 7z/zip 文件（大小被维护横幅遮挡） | CC BY 4.0 |
| A6 | Frontiers 附录 Table_1.docx 直链 | ❌ **404**（API 元数据与文件直链均 404） | ❌ 不可得（需重新定位所属文章） | — | — |
| A7 | UTHM 硕士论文（eprints.uthm.edu.my/8245） | ⚠️ 当场连接失败（HTTP 000）；Wayback 2024-08-28 快照确认页面及内容有效 | 📧 24 页预览 PDF（1 MB）开放下载；**全文 22 MB 限注册用户** | 全文 22 MB | 机构库 |
| A8 | MIT OpenAg（github.com/OpenAgInitiative） | ↪️ 组织页存在，但公告 **"Projects moved to github.com/OpenAgricultureFoundation"，原组织已无任何公开仓库** | ❌ 不可得（此链接下无数据） | — | — |

### 1.3 论文 DOI / 站点链接（11 条）

| 论文（原清单条目） | DOI/链接 | 状态 | 核查结果 |
|---|---|---|---|
| Graamans et al. 2018 | 10.1016/j.agsy.2017.11.003 | ✅ | 正确解析：Agric. Systems 160, 31–43 |
| Graamans et al. 2017 | 10.1016/j.agsy.2017.03.004 | ❌ **张冠李戴** | 该 DOI 实际指向 **van Dijk et al. 2017**（产量差距研究，Agric. Systems 154, 90–99），并非 Graamans 温室气候室论文 |
| Kozai 2013 | 10.2183/pjab.89.447 | ✅ | 正确解析：PJAB Ser. B 89(10), 447–461 |
| Kozai et al. 2022（IHC 会议） | www.ihc2026.org | ✅（但链接不精确） | 网站有效（第 32 届 IHC，2026-08-23~28 京都，**已闭幕**）。这是 2026 年大会官网，并非 Kozai 2022 IHC 论文入口 |
| Barbosa et al. 2015 | 10.3390/ijerph120606876 | ❌ **404（尾号笔误）** | 正确 DOI 为 **10.3390/ijerph120606879**（已验证可解析：IJERPH 12(6), 6879–6891） |
| Martin & Molin 2019 | 10.3390/su11154124 | ✅ | 正确解析：Sustainability 11(15), 4124 |
| Martin et al. 2023 | 10.1016/j.spc.2023.06.020 | ✅ | 正确解析：Sustain. Prod. Consum. 40, 182–193 |
| Martin et al. 2024 | 10.3389/fsufs.2024.1403580 | ✅ | 全文抓取成功；0.78–1.18 kg CO₂-eq/kg 生菜、240 kg/年 与原清单一致 |
| Pennisi et al. 2025 综述 | 10.1007/s13593-025-01055-w | ✅ | 正确解析：Agron. Sustain. Dev. 45(5) |
| Shams Ettehad & Gholami 2024 | 10.1016/j.compag.2024.109115 | ❌ **张冠李戴** | 该 DOI 实际指向 **Rohan et al. 2024 畜牧业行为识别深度学习综述**（Comput. Electron. Agric. 224, 109115）。正确论文经 Crossref 多轮检索未能定位，需人工修复 |
| MDPI Sustainability 16:7189 | mdpi.com/2071-1050/16/16/7189 | ✅（经 Crossref；MDPI 直抓 403 反爬） | DOI 有效：**Ptak et al. 2024 "A New Approach to Vertical Plant Cultivation Maximises Crop Efficiency"**，CC BY 4.0。但论文主题为塔式栽培装置设计，**与原清单描述的"Muke 零售植物工厂 46 天分项电表"不符**（该文仅引用了 Muke 官网），疑内容张冠李戴 |

---

## 2. 分数据集详情

### 2.1 AGC 2018（黄瓜）—— figshare 12717758

- **核查过程**：figshare.com HTML 页面抓取为空（JS 渲染），改用 figshare API（`api.figshare.com/v2/articles/12717758`）成功；`curl -I` 验证下载直链 `ndownloader.figshare.com/files/24075461` 返回 **200 OK**（Content-Length 8,975,944，application/zip）。
- **链接状态**：有效；注意 API 中 `url_public_html` 已指向 `data.4tu.nl/articles/dataset/...`（4TU 自有 figshare 门户为权威地址），原 figshare.com 链接仍可解析。
- **数据背景**：6 个 96 m² 玻璃温室 compartment（荷兰 Bleiswijk，WUR），黄瓜 Hi Power，**2018-08 至 2018-12 共 4 个月**（API custom field "Time coverage: 2018-08/2018-12" 确认）。内容：温室气候、灌溉、室外气象、设定点、采收与作物管理、资源消耗（水/CO₂/能耗）。5 支国际 AI 队伍 + 1 个人工参考 growers 对照。
- **来源**：WUR（Hemming, de Zwart, Elings 等）；CC0；版本 DOI 10.4121/uuid:e4987a7b-...；引用文献 edepot.wur.nl/473579。
- **文件**：`The 5 International Teams.pdf`（36 KB）+ `data.zip`（8.98 MB）。`download_disabled: false`。

### 2.2 AGC 2019（番茄）—— figshare 12764777

- **核查过程**：同 2.1，API 成功，下载直链 HEAD **200 OK**（8,418,715 字节，7z 格式）。
- **数据背景**：6 个高科技玻璃温室（Bleiswijk），樱桃番茄 Axiany 品种，**6 个月连续生产**；室内外气候、灌溉、执行器状态、请求/实际设定点、资源消耗（加热、电、CO₂）、采收、品质、灌溉/回流液分析、根区岩棉信息。5 队（Automators, AICU, IUA.CAAS, Digilog, Automatoes）+ Reference 对照。
- **来源**：WUR；CC0；2020-09-23 发布（v2）。

### 2.3 AGC 2022（生菜）时序 —— 4TU DOI 10.4121/21960932.v1

- **核查过程**：DOI 页面加载成功，元数据完整；但页面顶部横幅：**"File uploads and downloads are temporarily unavailable while storage is under maintenance... Full service is expected to be restored around 11 October 2026"**，文件列表显示 "temporarily unavailable"。
- **数据背景**：第 3 届 AGC（Bleiswijk，2022），多参赛队 96 m² 温室、两茬生菜；气象、温室气候、控制状态、作物观测 + RGB/深度图像（388 张 RGB + 388 张深度 + GT json + 每日图像）。关联论文 DOI 10.3390/s23062929。统计：3050 views / 10030 downloads。
- **来源**：WUR（Petropoulou 等）；CC BY 4.0；格式 7z/zip/png/json。
- **大小**：约 45 GB（原清单值，维护遮挡未能核验）。
- **影响**：核查日（10-11）恰为预告恢复日，建议 1–2 天后重试下载。

### 2.4 意大利商业垂直农场能源情景 —— amsacta 8914

- **核查过程**：页面有效；两个文件下载直链 `curl -I` 均 **302→200**（xlsx mimetype 正确）。
- **数据背景**：伦巴第大型商业生菜垂直农场（私有公司数据），cradle-to-grave LCA 清单 + **8+1 种能源情景**（Biomethane 基线 / 电网 / 天然气 / 混合可再生 / 径流水电 / 水库水电 / 风电 / 光伏）的能耗-环境影响结果；含术语表与敏感性表。配套论文 DOI 10.1002/fes3.70234。
- **来源**：博洛尼亚大学 + KTH/IVL（Piovano, Arcas Pilz, Pennisi, Gianquinto, Martin, Orsini）；**CC BY 4.0**；2026-05-13 存入（很新）；EU NextGenerationEU MADLoop + Formas 资助。
- **注意**：这是 **LCA 情景清单数据，非时序运行数据**——适用于 VFED 的能源情景/排放对标，不能直接做逐时 ODE 验证。

### 2.5 比利时商业番茄温室微气候 —— Mendeley tkbkzdt5nr/2

- **核查过程**：页面有效（v2，2024-04-29，DOI 10.17632/tkbkzdt5nr.2）；"Download All" 按钮存在。Mendeley 公开文件 API 返回 400，**文件级大小未核验**。
- **数据背景**：Proefcentrum Hoogstraten 商业标准番茄生产温室，**2018–2020 多年**；环境（温度/湿度/PAR 光照，Priva 气象站 + SHT31 + SQ300）+ 植物测量（穗重、穗数、硬度、颜色、可溶性固形物、乙烯释放率、株高、茎粗，周测）。
- **来源**：KU Leuven（Salagovic, Verboven, Nicolai 等），Interreg Vl-Nl GROW! 项目；**CC BY 4.0**。
- **局限**：**无能耗数据**；环境时序粒度未在页面明示（传感器采集频率需下载数据后确认）。

### 2.6 UC Davis 生菜多模态 —— Zenodo 17041810

- **核查过程**：zenodo.org HTML 有反爬验证（"Checking your browser"），改用 **Zenodo API** 成功取全部元数据；下载直链 HEAD **200 OK**（742,925,862 字节）。
- **数据背景**：NFT 双层架 70 株结球生菜（butterhead），UC Davis 生物与农业工程系；**栽培周期 2024-02-21 至 2024-03-23**（v2 元数据）。内容：逐小时冠层 RGB（RealSense D405）；**30 分钟均值环境/营养液时序**（上下层气温、上下层湿度、水温、EC、储液体积）；**逐日非破坏鲜重**（18 株参照株 B22–B47）。
- **来源**：Karimzadeh & Ahamed（UC Davis）；**CC BY 4.0**；open access；配套论文 2 篇（OptiDose, Computers and Electronics in Agriculture 243:111428；Real-Time Lettuce Biomass Forecasting, J. ASABE 69(1)）。
- **伴生记录澄清**：16912088 = **概念 DOI**（指向最新版），16912089 = **v1.0 旧版**（其元数据将栽培周期写为 2022 年，v2 已修正为 2024 年）。二者并非独立数据集。
- **局限**：**无能耗计量**；单栽培周期约 31 天。

### 2.7 HydroGrowNet Batavia —— Mendeley g6cm3v3wdp

- **核查过程**：无版本号 URL 现重定向至 **/datasets/g6cm3v3wdp/5**（v5，2025-06-16 发布）。页面有效，Download All 存在；4.22 GB 未核验。
- **数据背景**：NFT 水培 Batavia 生菜，**3 个连续 30 天周期（共约 3 个月）**；39 万+ 张 YOLO-v8 分割图像 + 逐株时间戳对齐的水温/EC/pH 水质时序。阿拉伯科技与海运学院（AAST，埃及）。
- **来源**：CC BY 4.0；配套论文 DOI 10.1016/j.engappai.2025.111214（+SSRN 预印本）。
- **局限**：环境变量少（水质为主，无气温/湿度/能耗）。

### 2.8 温室生菜生长模型数据 —— Mendeley r7z9ttvkyh/2

- **核查过程**：页面有效（v2，2024-11-28）。
- **数据背景**：3 个试验（冷季标定 Exp_c、暖季验证 Exp_v1、冷暖季验证 Exp_v2）；每试验含 Greenhouse climate（模型输入）、Lettuce growth（实验室测量）、生长摘要（干重/LAI 按种植密度换算）、SLA 标定、根冠比等 sheet。
- **来源**：北京市农林科学院智能装备技术研究中心（孙伟托等）+ Nottingham Trent University；**CC BY 4.0**；**含完整 MATLAB 生长模型源码**（1 主脚本 + 8 函数 + 数据文件）。
- **对 VFED 价值**：与 VFED 的 Van Henten 生长模型直接可比，代码可移植参考。

### 2.9 PPFD/DLI 校准验证 —— Zenodo 21910738

- **核查过程**：API 有效；17 个文件（对齐观测数据 xlsx 1.75 MB + 分析工作簿 xlsx 2.1 MB + Colab notebook + 数据字典 + checksums），合计约 6.4 MB。
- **数据背景**：植物工厂光照装置，AS7265x 多光谱传感节点 vs LI-COR LI-180 参照；**3600 对观测、25 个完整 24h 循环、10 分钟间隔**（13 个恒定光 + 12 个正弦光；17 开发 / 8 留出验证）。
- **来源**：Universitas Gadjah Mada（印尼）；CC BY 4.0；**2026-08-13 发布（很新）**。作者明确声明：仅适用于本装置条件的 PPFD/DLI 验证，非跨设备通用标定集。

### 2.10 Kaggle Lettuce Growth Days

- **核查过程**：页面标题加载成功（"Lettuce Growth Days Analysis"），正文 JS 渲染，无法进一步核验 3169 条等细节。
- **可下载性**：Kaggle 标准流程，📧 免费注册后下载。背景信息缺失（原清单判断"质量存疑"合理）。

### 2.11 IEEE DataPort 光配方数据（DOI 10.21227/367s-gr63）

- **核查过程**：页面完整抓取。DOI 确认；数据格式 CSV；**文件 Dataset.csv 50.95 KB**；另有一个无需登录即可下载的 Python 可视化脚本（S3 直链）。
- **数据背景**：30 株植物多时间点纵向测量（鲜重 g、株高 mm、株宽 mm、叶片数）× 红绿蓝光配方百分比（合计 100%）× 实验组；2024-12 起测量。Centro Universitario FEI + EMBRAPA（巴西）。
- **❗关键修正**：页面 "Dataset Access Information" 明示 **"Subscription Required — This dataset requires an IEEE DataPort Subscription to access"**。原清单写"需免费注册 IEEE 账号"**不成立**：一般用户需付费订阅（IEEE 学会会员可免费获得订阅）。

### 2.12 番茄温室气候-作物仿真 —— Zenodo 6697043

- **核查过程**：concept 6697043 → version 6697044，API 有效；ds.csv HEAD 200 OK（12,769,130 字节）。
- **数据背景**：**仿真数据（非实测）**，30+ 变量：室外气象（CO₂/风速/湿度/辐射/温度）、覆盖层/空气/地面/土壤温度、蒸腾热损失、室内辐射、绝对湿度、CO₂、通风率、窗/幕开度、作物碳库（果/叶/茎/缓冲）、LAI、VPD、作物吸水等。
- **来源**：University of Deusto（西班牙），HortiMED/PRIME 项目；CC BY 4.0。
- **用途**：可作为温室 ODE 模型（VFED physics 引擎同类）的**模型间交叉验证**参考，不可当实测。

### 2.13 NBSDC 沈阳植物工厂温湿度

- **核查过程**：页面模板加载（站点正常），但数据集元数据（名称/DOI/摘要/文件）全部 JS 渲染，静态抓取不可见；页面底部弹窗 **"暂无权限，请先注册或登录"**。
- **结论**：链接有效；📋 注册+申请+审批的获取方式与原清单一致；"1 分钟间隔、连续 24 h、沈阳农业大学"等细节**未能独立核实**。

### 2.14 CERTH 垂直农场能耗仿真 —— Zenodo 16926135

- **核查过程**：API 有效；**103 个文件**全部枚举，合计约 156 MB。
- **数据背景**：希腊团队（Ketikidis 等），**TRNSYS 18 单区建筑（ISOBOX）垂直农场仿真 + 试点混合**；生菜多情景（约 48 个 S 编号情景）逐时能耗、能耗分项（Energy Breakdown / Various Energy Data / Power Requirements 7.7 MB）、CO₂ 排放、PV 逐月发电与缺口（PV Deficit / Grid Dependency / Resilience）、照明安全降载与 HVAC 联调、设备规格（希腊语 PDF：电气连接、照明、水泵、电池）。配套论文："Dynamic energy optimization and lighting flexibility classification for sustainable vertical farming"。
- **来源**：CC BY 4.0；Python 脚本；open access；下载量 1237 次。
- **注意**：⚠️ 与原清单标注一致——**非纯实测**（仿真+试点混合），且部分设备资料为希腊语。**但其"垂直农场 + PV + 逐时能耗 + 调度"结构与 VFED 的 PVBES 模块高度同构**，是模型间对标的最佳候选。

### 2.15 UTHM 硕士论文（MARDI 能耗研究）

- **核查过程**：直连两次失败（curl HTTP 000 / webfetch 超时）——**本网络不可达**。经 Internet Archive Wayback（2024-08-28 快照）确认：Shaari, Abdul Muin (2022) "Energy management study in indoor farming plant factory", Masters thesis, UTHM。
- **内容核实**（快照摘要）：AgroCube 集装箱 vs MARDI 商业植物工厂，**一周电力负荷记录**（LED/水泵/空调分项）；**414.153 vs 3788.423 kWh/周**；SEC **17.15 vs 19.2 kWh/kg**——与原清单数值**完全一致**。
- **获取**：24 页预览 PDF（1 MB）开放；全文 22 MB **限注册用户**；备用入口：`web.archive.org/web/20240828235133/http://eprints.uthm.edu.my/8245/`。

### 2.16 其余条目速记

- **zjip 公告 7560**：站点可达、内容 JS 不可见；按平台性质为 💰 数据交易授权，细节无法核实。
- **Frontiers Table_1.docx**：❌ 双重 404。原清单称其为"单表提炼价值最高、优先提炼"目标，**已失效**，需通过 Frontiers 站内检索重新定位综述文章（线索：表格含 Kikuchi 2018 / Casey 2022 / Parkes 2022 等案例的面积、kWh/m²、kg CO₂/m²）。
- **OpenAgInitiative**：组织页公告 "Projects moved to github.com/OpenAgricultureFoundation"，原组织 **0 个公开仓库**。佐证原清单"平台停维护、可用性不稳定"的判断；对 VFED 该链接已无数据价值。

---

## 3. 与原清单不一致处清单

| # | 条目 | 原清单记载 | 核查发现 | 严重度 |
|---|------|-----------|----------|--------|
| 1 | IEEE DataPort（#11） | "需免费注册 IEEE 账号" | **需付费订阅**（页面明示 Subscription Required；仅 IEEE 学会会员/机构订阅者免费） | 🔴 高（获取成本误判） |
| 2 | Graamans 2017 DOI | 10.1016/j.agsy.2017.03.004 | DOI 有效但指向 **van Dijk et al. 2017**（产量差距研究），非 Graamans 论文 | 🔴 高（张冠李戴） |
| 3 | Shams Ettehad 2024 DOI | 10.1016/j.compag.2024.109115 | DOI 有效但指向 **Rohan et al. 2024 畜牧行为识别综述**；正确 DOI 未能定位 | 🔴 高（张冠李戴） |
| 4 | Frontiers Table_1.docx | "如果只提炼一处，优先这份"（最高优先级） | **404 失效**（API 与直链均不可用） | 🔴 高（核心提炼目标丢失） |
| 5 | Barbosa 2015 DOI | 10.3390/ijerph120606876 | **404**；尾号笔误，正确为 **…6879**（已验证） | 🟡 中（一行可修复） |
| 6 | AGC 2022（#3）及伴生图像集 | "免费直接下载" | 4TU 平台存储维护中，**文件暂时不可下载**（公告预计约 10-11 恢复）；AGC 2018/2019 托管于 figshare CDN 不受影响（HEAD 200） | 🟡 中（暂时性） |
| 7 | UC Davis "伴生记录" 16912088/16912089 | 作为伴生数据集列出 | 实为**同一数据集的概念 DOI 与 v1 旧版本**，非独立资源；v1 元数据年份（2022）与 v2（2024）不一致（作者笔误已修正） | 🟡 中（结构误述） |
| 8 | MDPI Sustainability 16:7189 | "Muke 零售植物工厂 46 天分项电表（照明 49.9%、HVAC 40.4%）、日均 50.22 kWh" | 论文实为 **Ptak et al. 2024 塔式栽培装置设计**（波兰弗罗茨瓦夫理工大学），摘要与"46 天分项电表"不符；论文仅引用了 Muke 官网。疑描述与文章不匹配，**需人工复核全文** | 🟡 中（疑张冠李戴） |
| 9 | HydroGrowNet（#7） | 直链 g6cm3v3wdp | 现**重定向至 v5**（2025-06-16）；引用时建议固定版本 DOI 10.17632/g6cm3v3wdp.5 | 🟢 低（版本更新） |
| 10 | AGC 2018/2019 figshare 链接 | figshare.com 链接 | 权威页面已迁至 **data.4tu.nl**（原链接仍可解析，下载不受影响） | 🟢 低（域名迁移） |
| 11 | Kozai et al. 2022（IHC） | 链接 www.ihc2026.org | 该站为 **2026 京都大会官网（已闭幕）**，非 2022 IHC 论文入口；线索价值有限 | 🟢 低（链接不精确） |
| 12 | OpenAg | "可用性不稳定" | 组织已清空并迁移（OpenAgricultureFoundation），该链接**实际无数据** | 🟢 低（判断已被证实） |

未发现不一致（核实相符）：AGC 2018/2019 内容与许可、amsacta（CC BY 4.0 + 直链 200）、UC Davis 742.9 MB、PPFD/DLI 数据结构、CERTH ~156 MB 与"非纯实测"标注、NBSDC 需审批、UTHM 论文数值（414/3788 kWh/周；17.15/19.2 kWh/kg）、Martin 2024 数值（240 kg/年；0.78–1.18 kg CO₂-eq/kg）、Kozai 2013 / Martin 2019 / Martin 2023 / Pennisi 2025 / Graamans 2018 DOI。

---

## 4. VFED 验证用推荐排序及理由

VFED = 垂直农场 ODE 建模 + PV-电池-电网能源系统仿真，验证需求按优先级：**真实能耗 + 环境时序 + 产量** 三位一体 > 两项 > 单项。

| 排名 | 数据集 | 理由 | 使用建议 |
|------|--------|------|----------|
| **1** | **AGC 2018 黄瓜**（9.0 MB，CC0，直链已验证 200） | 唯一"资源消耗（水/CO₂/能耗）+ 室内外气候 + 采收产量 + 设定值"全要素且**当下即刻可下载**的实测数据集；含 6 compartment 对照（AI vs 人工），天然提供控制策略对比样本 | 温室 ODE 热平衡/作物模块的**主验证集**。注意为太阳光玻璃温室（加热主导），照明项需与 VFED 人工光预设解耦校验 |
| **2** | **AGC 2019 番茄**（8.4 MB，CC0，直链 200） | 同构要素 + 执行器状态 + 回流液 + 品质；含加热与电耗分项 | 与 #1 组成跨作物、跨季节验证对；能源分项拆解可校验 VFED 的 HVAC/压缩机 COP 模型 |
| **3** | **AGC 2022 生菜**（45 GB，CC BY 4.0，暂维护中） | **作物与 VFED 预设（生菜）一致**；含气象/气候/控制/作物观测 + 图像 | 待 4TU 恢复后下载（预计即日）；生菜时序用于植物模块 + 环境耦合验证 |
| **4** | **CERTH 16926135**（156 MB，CC BY 4.0，可下载） | 结构与 VFED **最同构**：垂直农场 + TRNSYS 逐时能耗 + PV 发电/缺口 + 电池 + 照明柔度调度 | 作为 **PVBES 调度与能源系统的模型间对标基准**（model-to-model）；非实测，不能作最终实证 |
| **5** | **UC Davis 17041810**（742.9 MB，CC BY 4.0，直链 200） | **PFAL 实测时序中最完整**：30 min 环境（双层温/湿）+ 水温/EC/储液体积 + 逐日鲜重；双层 NFT 架构与 VFED 设施设定直接可比 | 植物-环境 ODE（transpiration + Van Henten 生长）**室内人工光场景验证**；无能耗是短板，需与 #7 论文基准拼接 |
| **6** | **北京生菜生长模型 r7z9ttvkyh**（CC BY 4.0） | 温室气候 + 干重/LAI/SLA/根冠比 + **MATLAB 模型代码** | Van Henten 生长模块的标定/验证与代码级对照 |
| **7** | **amsacta 8914 意大利能源情景**（2 MB，CC BY 4.0，直链 200） | 商业垂直农场 8 种能源情景（含 **PV 情景**）LCA 清单 | VFED sweep 的 LCOE/排放结果**量级对标**与情景设计参考 |
| **8** | **比利时番茄 tkbkzdt5nr**（CC BY 4.0） | 2018–2020 **多年**环境时序（温/湿/PAR） | 长时序气候模型的稳健性验证（无能耗） |
| **9** | **PPFD/DLI 21910738**（6.4 MB，CC BY 4.0） | 10 min 光照模式 3600 对观测 + Colab 复现 | LED 光照子模型（DLI/PPFD 时序）校准专用 |
| **10** | Zenodo 6697043 番茄仿真（12.8 MB） | 30+ 变量仿真时序 | 温室 ODE 模型间交叉检查（非实测，权重低） |
| 不推荐依赖 | NBSDC（审批长）、zjip（付费）、IEEE DataPort（订阅）、Kaggle（无背景）、HydroGrowNet（无环境/能耗）、OpenAg（已迁移） | 获取成本高或变量缺失 | — |
| 论文基准 | Graamans 2018（DOI ✅）、Kozai 2013（✅）、Pennisi 2025（✅）、Martin 2019/2023/2024（✅） | 7–12 kWh/kg（高效日本厂）至 20–40 kWh/kg（欧美厂）、产量 40–520 kg/m²/年 等基准带 | 修复 §3 中 4 处失效/错误 DOI 后，作为 VFED 能耗/产量结果的文献区间校验 |

**推荐组合策略**：#1+#2（即刻可用的能耗-气候-产量全要素验证）→ #5（人工光室内场景 + 产量时序）→ #4（PVBES 模型间对标）→ #7（情景/排放量级）→ 论文基准带（最终合理性区间）。

---

## 5. 核查方法与局限说明

### 5.1 核查方法

1. **页面抓取**：webfetch 抓取清单中全部 32 条外部链接的着陆页。
2. **API 替代**：对反爬/JS 渲染站点改用官方 API——figshare（`api.figshare.com/v2/articles/{id}`）、Zenodo（`zenodo.org/api/records/{id}`）、Crossref（DOI 元数据与文献检索）、Internet Archive Wayback（UTHM 快照）。
3. **下载入口验证（非本体下载）**：`curl -I`（HEAD 请求）验证文件直链的 HTTP 状态码与 Content-Length，**未下载任何大文件**（UC Davis 742.9 MB、AGC 2022 约 45 GB、CERTH 156 MB 等均仅确认入口可用与确切字节数）。
4. **元数据交叉**：许可、版本、时间覆盖、地理坐标等以数据仓库 API 字段为准，与原清单记载比对。

### 5.2 局限（哪些是入口验证而非实际下载）

- **全部数据集均为"入口级"验证**：确认链接有效、文件清单真实存在、下载直链返回 200 及准确大小；**未解压检查数据内容、变量完整性、时间对齐质量**。Kaggle（#10）、NBSDC（#13）、zjip（A4）的正文细节因 JS 渲染未能核验。
- **4TU 维护窗口的时效性**：AGC 2022（#3）与伴生图像集（A5）的"暂时不可下载"是平台公告（预计 2026-10-11 前后恢复），属**瞬时状态**，建议 1–2 日后复查；本报告对其 45 GB 规模未能核验。
- **Mendeley 文件级大小未核验**：#5/#7/#8 的页面确认可下载与许可，但公开文件 API 返回 400，逐文件大小（如 HydroGrowNet 4.22 GB）沿用原清单值。
- **两处张冠李戴 DOI 的"正确目标"未定位**：Shams Ettehad & Gholami 2024 与 Graamans 2017 的正确 DOI 经 Crossref 多轮检索未果，需人工（Google Scholar/期刊站内）修复；MDPI 16:7189 与"Muke 46 天电表"的匹配性需全文复核。
- **网络环境差异**：UTHM 站点在本网络不可达（HTTP 000），可能为区域性网络问题而非站点失效（Wayback 2024-08 快照证明其曾正常）；zjip/NBSDC 的动态内容在浏览器中或可正常显示。
- **Frontiers Table_1.docx 的 404** 不排除是 API 路径调整所致，但文章 ID 1533433 本身亦无法解析，判定为失效；如需恢复，建议在 Frontiers 站内按"Kikuchi 2018 / Casey 2022 / Parkes 2022"引用线索检索该综述。
- 原清单检索日期（10-10）与核查日期（11-10）仅隔 1 天，数据集本体内容理论上无变化；本报告所有"大小/许可/版本"均以核查当日 API 实测为准。

---

*报告生成：2026-10-11 · 核查工具：webfetch + figshare/Zenodo/Crossref API + curl HEAD · 共 32 条链接、21 个数据资源入口*
