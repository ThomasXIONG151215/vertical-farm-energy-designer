# PVBES 验证锚点数据库（pvbes-validation anchors）

本目录是 VFED 项目 PVBES 仿真能力强化（G1-G13）的验证锚点数据库。
`tests/` 中的物理正确性测试从这里读取参考数值，用于约束 PV 组件模型、
双面增益、弱光响应、电池老化、逆变器效率与植物工厂-光伏覆盖案例的
仿真输出量级。

## 铁律

1. **准确性高于覆盖度**。拿不到来源的数值一律为 `null`，绝不编造或猜测。
2. **测试只从本目录读数**。禁止把任何科学数值内联进测试代码。
3. **每个 URL 都必须被真实访问过**（本数据库建立于 2026-11-01，
   全部来源逐条访问核验）。
4. 付费墙内的来源标 `paywalled`，网络不可达的标 `inaccessible`，
   值留 `null`。

## 目录结构

```
reference/pvbes-validation/
├── readme.md          # 本文件：溯源规则与 schema
├── raw/               # 原始证据文件（PVGIS JSON 响应、论文 PDF、提取文本）
├── modules/           # 光伏组件数据表提取，每组件一个 YAML
└── anchors/           # 验证锚点 YAML
```

## YAML schema

每个条目必带 `source` 块与 `status` 字段：

```yaml
source:
  url: <建立本条目时真实访问过的 URL>
  accessed: "2026-11-01"
  method: table_value | api_response | figure_digitized | datasheet
  note: <提取方式、来源覆盖范围、不确定度、与调研数值的差异>
status: verified | partial | paywalled | inaccessible | to_follow
```

- 数值字段查不到时写 `null`，并在 `note` 中说明原因。
- 由来源数值做纯算术换算的（如面积功率密度÷1000 W/m² 得效率），
  保留换算值但在 `note` 中声明"computed"。
- 同一文件内可以有多个条目，每个条目独立携带 `source` 与 `status`。

## status 枚举定义

| 状态 | 含义 |
|---|---|
| `verified` | 来源可访问，条目数值在来源中逐字核对一致 |
| `partial` | 来源可访问但只覆盖条目部分数值；其余来自项目调研且未能复核，或正文在付费区 |
| `paywalled` | 来源在付费墙内，无法核对，值为 `null` |
| `inaccessible` | 来源 URL 从建立网络无法访问（含 PDF 不可解析），值为 `null` |
| `to_follow` | 尚未找到可访问的公开来源，值为 `null`，待补 |

## raw/ 与提取文件的对应关系

| raw 文件 | 内容 | 对应条目 |
|---|---|---|
| `pvgis_shanghai.json` | PVGIS v5_2 PVcalc 原始 JSON（上海 25° 南向） | `anchors/pv_yield_bands.yaml` shanghai_fixed25 |
| `pvgis_beijing.json` | PVGIS v5_2 PVcalc 原始 JSON（北京 35° 南向） | `anchors/pv_yield_bands.yaml` beijing_fixed35 |
| `keil2016_calendar_aging_jes.pdf` (+ `_extracted.txt`) | Keil et al. 2016 JES 开放获取论文原文与提取文本 | `anchors/battery_aging.yaml` keil2016_calendar_aging |
| `keil2016_page4/6/7/8.png` | 论文图页 200 dpi 渲染（图 2 在 page4） | `anchors/battery_aging.yaml` figure2_digitized |
| `cec_modules.csv`（git-ignored，6.3 MB） | NREL SAM CEC 组件库 develop 分支（版本 2026.7.3），URL https://raw.githubusercontent.com/NREL/SAM/develop/deploy/libraries/CEC%20Modules.csv | `modules/jinko_jkm580n.yaml` cec_72hl4_neighbor |
| `sandia_modules.csv`（git-ignored，195 KB） | NREL SAM Sandia 组件库同源 | 备用组件参数来源 |
| `fetch_list.md` | datasheet 取数清单（2026-11-02 更新：huasun/longi 已解决，jinko 仍待直接复核） | modules/huasun、longi、jinko 的补齐路径 |
| `datasheets/`（git-ignored，8 文件） | 2026-11-02 用户人工提供：LONGi Hi-MO 9 三变体 PDF（Edge 2.8MB / Edgeclear 51.8MB / Sea-Shield 3.2MB）、Huasun HSN-210-B132 中文版 PDF + HSN-210R HTML 壳（无数据）、Jinko 三份邻档 PDF（66HL4M-BDV-Z4C1 / 48HL4M-DV / 48HL6M-T） | `modules/huasun_himalaya.yaml`（主条目 DS730）、`modules/longi_himo9_670m.yaml`（主条目 670 档）、`modules/jinko_jkm580n.yaml`（datasheet_66hl4m_neighbor 旁证） |

## 已知网络限制（2026-11-01 建库时）

从建库网络访问 `*.nrel.gov`、`*.osti.gov` 的 TLS 握手全部失败
（webfetch、curl/schannel、Python requests/OpenSSL 三种栈均试过），
Wayback Machine 对 PDF 抓取持续返回 429。因此 NREL/OSTI 托管的
文档一律标 `inaccessible`，这是网络可达性问题，不是文档不存在。
例外：NREL 的 GitHub raw 域（raw.githubusercontent.com）可达，CEC/Sandia
组件库即由此获得（2026-11-01）。

Huasun / LONGi / Jinko 官网产品规格表为 JS 渲染页面，webfetch 只拿到
空壳。2026-11-02 用户人工下载放入 reference/ 根（后移入
`raw/datasheets/`），7 份 PDF 全部可解析：huasun 与 longi 预设自此
datasheet-complete（唯一带 datasheet NOCT 的预设是 huasun 44±2°C，
其余 NOCT=45 仍是建模默认）。

2026-11-02 弱光替代路径调研（详见 `anchors/low_irradiance.yaml` 新增
9 条）：SAPM 排除（Sandia 库 2014 冻结+系数不可反推，本地 525 行实证
零命中）；首选增强路径 = 离线 pvlib 单二极管反推采样 eta_rel 节点表
（TOPCon/BC 用 calcparams_cec、HJT 用 calcparams_pvsyst，输入三预设
已全有）；ADR 五参数模型是填表友好的未来内核；验证通道 = OEDI S3
镜像的 PVDAQ 电站实测（NREL 主站仍不可达但镜像可达）+ SiliconPV 2026
开放论文（TOPCon 弱光锚点）。已知数据空白：BC/HPBC 模块级实测 eta(G)
无公开文献（gap_bc_hpbc_no_public_data）。
