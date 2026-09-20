# Vertical Farm Energy Designer (VFED)

[中文版](./README_zh.md) | [English](./README.md)

> 面向**人工光植物工厂 (PFALs)** 的开源设计模拟器 — 将基于第一性原理的建筑能耗模型与光伏-电池-电网（PVBES）系统耦合，实现最低 LCOE 的光伏+储能容量优化。

[![GitHub stars](https://img.shields.io/github/stars/ThomasXIONG151215/vertical-farm-energy-designer?style=social)](https://github.com/ThomasXIONG151215/vertical-farm-energy-designer/stargazers)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/)

## 背景

人工光植物工厂 (PFALs) — 用 LED 替代阳光的封闭式多层种植设施 — 是能耗最高的农业系统之一，照明、空调和除湿的合计能耗高达 **200–500 kWh/m²/年**。电网电力在运营成本中占主导地位，往往超过总生产成本的 30%。

将屋顶光伏 (PV) 与电池储能 (BES) 结合，可以显著降低电网依赖和运营成本。但最优光伏阵列面积和电池容量取决于多个复杂因素的交织：地理位置、当地气候、建筑围护结构、作物光周期安排以及分时电价。没有放之四海而皆准的经验法则 — 每个设施都需要因地制宜的设计。

**VFED** 解决了这个问题。它使用第一性原理物理（湿空气热力学、围护结构传热、基于 ODE 的房间模型）模拟植物工厂的逐时能量平衡，然后扫描光伏面积 × 电池容量，找到使**平准化能源成本 (LCOE)** 最小的设计。

> 📄 本工具配套论文：
> **Xiong, T., Cai, W., Hu, Y., Song, M., Qian, T., & Bao, H. (2026).** *Photovoltaic-battery integration strategy in plant factories with artificial lighting.* Energy and Buildings, 361, 117462.
> [DOI: 10.1016/j.enbuild.2026.117462](https://doi.org/10.1016/j.enbuild.2026.117462)

`research/xiong-pvbes-photoperiod-2026/` 目录包含该论文的归档代码和实验数据。当前活跃代码库 (`vfed/`) 用纯 Python 第一性原理 ODE 求解器替代了基于 EnergyPlus 的负荷生成器，并增加了参数化设计扫描 — 详见 [research/xiong-pvbes-photoperiod-2026/](research/xiong-pvbes-photoperiod-2026/)。

## VFED 工作原理

| 挑战 | VFED 方法 |
|------|-----------|
| PFAL 负荷取决于气候、围护结构和光照计划 | 第一性原理 ODE 求解器 — 房间热湿平衡，无 EnergyPlus 依赖 |
| 光伏输出随位置、倾角和天气变化 | 单二极管 PV 模型 + Open-Meteo 逐时天气数据 |
| 电池容量是成本与自给率之间的权衡 | 对 (光伏面积 × 电池容量) 进行参数化扫描 → LCOE 最优设计 |
| 电价结构影响经济性 | 分时电价模型（24 小时价格表 + 售电价格） |
| 植物蒸腾增加潜热负荷 | 5 种蒸腾方法 — 1 种模型耦合（Van Henten）与 4 种直接设定（daily / per_plant / daily_per_period / per_plant_per_period） |

## 快速开始

### 安装

```bash
git clone https://github.com/ThomasXIONG151215/vertical-farm-energy-designer.git
cd vertical-farm-energy-designer
pip install -e .
# 或安装开发/测试依赖：
pip install -e ".[dev]"
```

### 1. 创建设计

```bash
vfed design new my_farm --preset 609 --city Shanghai --year 2025
```

从奉贤生菜预设创建 `my_farm.yaml`。默认输出名为 `<name>.yaml` — 可用 `--out path.yaml` 更改。`--city` 会从内置城市表（`vfed design cities` 列出）填入纬度/经度/时区，并使用预下载的 `data/weather/Shanghai_2025.csv`，使整个快速体验**完全离线**。如需任意地点，改用 `--lat <度> --lon <度> [--year YYYY]`；此时首次运行需联网（见下文"天气数据"）。`--year` 默认 2025。

### 2. 校验配置

```bash
vfed validate my_farm.yaml
```

在不运行仿真的情况下，对照项目 schema 校验 YAML。

### 3. 评估配置

```bash
vfed evaluate my_farm.yaml --cache weather_cache
```

对单一配置运行建筑仿真，报告年负荷、生物量与能耗强度（kWh/kg，即每千克鲜重的千瓦时）。`609` 预设自带 `pv_area_m2=0` / `battery_kwh=0`，因此此处能源系统为禁用状态 — 输出会显示 `Energy system = disabled`。若项目声明了 `pv` / `battery`（如 `example_lcoe_full.yaml`），本步骤还会报告光伏发电量与电网购电/售电量。单次全年仿真（8760 个逐时步长）在普通笔记本上约 10 秒（视机器而定）。

### 4. 参数化扫描 — 寻找 LCOE 最优的光伏+电池装机

`609` 预设未声明任何扫描范围，因此 `sweep my_farm.yaml` 只会重新评估这一组固定配置。为演示核心的光伏-电池容量优化，请使用仓库内已声明 `space.parameter_ranges` 的示例文件：

```bash
# 3 个参数（ppfd_target × pv_area × battery）= 100 组配置，约 6 秒（普通笔记本）
vfed sweep example_sweep.yaml --cache weather_cache --out results.csv
```

`--out results.csv` 将完整枚举表写入 CSV（每行一组配置）。控制台打印使目标最小化的最优设计 — 目标可选 `lcoe`（默认）、`kwh_per_kg_fresh` 或 `cost_per_kg_fresh` — 包括最优 `pv_area` 与 `battery` 装机。更完整的 225 组配置（含全资本成本）演示见 `example_lcoe_full.yaml`。没有单独的 `optimize` 命令；容量优化通过 `sweep` 完成。

### 5. 在浏览器中可视化

`vfed-web/` 是通过 Pyodide 运行同一引擎的浏览器前端。本地试运行：

```bash
cd vfed-web
npm run build   # 可选：从 vfed/ 源码重新打包 worker.js（需 python）
npm start       # 在 http://localhost:8000/ 启动本地服务
```

打开 http://localhost:8000/ 即可在浏览器中配置设计，或把生成的 YAML 粘贴进编辑器。部署到 Cloudflare Pages 使用 `npm run deploy`。

### 天气数据 — 联网、缓存与离线

天气按 lat/lon/year 在首次使用时从 Open-Meteo 逐时拉取，并缓存为 CSV 到 `weather_cache/`（可用 `--cache <dir>` 指定其他目录）。数据来源按优先级：

1. **预下载城市 CSV** — `data/weather/{城市}_{年份}.csv`，全部 51 座内置城市均含 **2025** 年数据（见 `vfed design cities`）。无需联网；当项目的 `site.city` 与年份匹配时自动使用。
2. **`weather_cache/`** — 之前拉取过的结果，按 lat/lon/year/tilt/azimuth/timezone 键复用。
3. **Open-Meteo 在线** — 用于任意 (lat, lon, year) 组合。需要联网；失败时 CLI 以 `[ERROR E003]` 终止。断网时请使用已缓存的年份或 `--cache`。

离线快速体验：使用内置城市 + `--year 2025` 即可。任意地点离线运行：先联网预取一次（`vfed evaluate <yaml> --cache weather_cache`），之后复用缓存。显式坐标优先于内置城市：`vfed design new --lat <度> --lon <度>` 会清除预设自带的 `site.city`（创建时打印 `[WARN] clearing preset city ...`）——lat/lon 缓存键与城市 CSV 描述的是两个不同地点，保留 city 会悄悄仿真错误的气候。生成的 YAML 随后以坐标作为天气缓存键（`weather_<lat>_<lon>_<year>_*.csv`），首次运行联网走 Open-Meteo 拉取（`tz_hours` 仍为预设值，除非自行修改）。反之，若在仍带 `site.city` 的 YAML 里手工修改 `lat`/`lon`，只要年份匹配，城市 CSV 依旧优先——想强制走 lat/lon（在线）路径，请在 YAML 中把 `site.city` 置为 null。示例扫描文件（`example_sweep.yaml` / `example_lcoe_full.yaml`）使用 2023 年 + 显式 lat/lon（不在预下载城市数据内），首次运行需联网（几秒，取决于网络），之后命中缓存即可离线。

## 架构

```
┌─────────────┐     ┌──────────────────────────────────────────────┐
│   天气数据   │────▶│              设计引擎                       │
│  (Open-Meteo)│     │  (vfed/design/engine.py — ODE 积分)         │
└─────────────┘     │                                              │
                    │  ┌──────────┐ ┌──────────┐ ┌──────────────┐ │
                    │  │  物理模型 │ │  设备模型 │ │   植物模型    │ │
                    │  │ 湿空气,  │ │ 空调,    │ │ 蒸腾,        │ │
                    │  │ 围护,    │ │ 除湿,    │ │ Van Henten   │ │
                    │  │ ODE, SHR │ │ LED,     │ │              │ │
                    │  │          │ │ 压缩机    │ │              │ │
                    │  └──────────┘ └──────────┘ └──────────────┘ │
                    └──────────────────┬───────────────────────────┘
                                       │ 逐时负荷曲线
                    ┌──────────────────▼───────────────────────────┐
                    │         PVBES 扫描与优化                     │
                    │  (vfed/design/sweep.py + vfed/pvbes/)         │
                    │  PVSystem → BatterySystem → Tariff → LCOE   │
                    └──────────────────┬───────────────────────────┘
                                       │
                               LCOE 最优设计
```

## 仓库结构

```
vertical-farm-energy-designer/
├── vfed/                    # 核心模拟器代码
│   ├── physics/            # 湿空气热力学、围护传热、ODE 求解器、SHR（显热比）
│   ├── devices/            # 空调、除湿机、LED、压缩机、热滞后
│   ├── pvbes/              # 光伏（单二极管）、电池（Zhao 2024）、电网（分时）、能源系统
│   ├── design/             # 项目配置（YAML）、引擎、预设、扫描
│   ├── weather/            # Open-Meteo 接口、Erbs GHI 分解、POA、地理编码
│   ├── plants/             # 蒸腾（5 种方法）、Van Henten 生长模型
│   ├── agent/              # 评估器（保留 agent-cli 错误码契约）
│   └── cli.py              # CLI 入口：vfed
├── research/               # 论文归档代码与数据（见下）
├── reference/              # 参考文献
├── weather_cache/          # 缓存的天气 CSV（自动生成）
├── pyproject.toml          # 项目元数据与依赖
├── vfed-web/               # 浏览器可视化（Pyodide Web Worker）
├── test_project.yaml       # 最小夹具 YAML — 仅供 tests/ 使用，非模板
├── test_web_yaml.py        # vfed-web 端到端契约脚本 — 用法：python test_web_yaml.py
└── README.md
```

## 论文与数据

`research/xiong-pvbes-photoperiod-2026/` 目录包含该论文的归档代码和实验数据。此代码为可复现性而保留，但已不再是活跃代码库 — 当前模拟器位于 `vfed/`。

| 子目录 | 描述 |
|--------|------|
| `research/xiong-pvbes-photoperiod-2026/` | 原始 PV-BES 优化器（基于 EnergyPlus 的负荷生成）。包含论文所用 CLI、优化器、电池模型、天气处理器和验证数据。 |

`research/` 下每个子目录都有自己的 `README.md` 提供详细文档。

## CLI 命令参考

| 命令 | 描述 |
|------|------|
| `vfed design new <name>` | 从预设创建项目 YAML（默认输出 `<name>.yaml`；可选 `--preset 609`、`--city`、`--lat`、`--lon`、`--year`、`--tariff`、`--out`） |
| `vfed design presets` | 列出可用预设 |
| `vfed design cities` | 列出内置城市（预下载 2025 年天气） |
| `vfed design tariffs` | 列出内置电价区域 |
| `vfed validate <project.yaml>` | 校验项目 YAML（不运行仿真） |
| `vfed evaluate <project.yaml> [--cache dir]` | 对单一配置运行建筑仿真 |
| `vfed sweep <project.yaml> [--cache dir] [--out results.csv]` | 枚举 `space.parameter_ranges`（如光伏面积 × 电池容量）并输出 CSV；未声明 range 时评估单一固定配置 |

## 配置

所有设计参数都位于 `vfed design new` 生成的单个 YAML 文件中。主要部分：

- **site** — 纬度、经度、年份、时区
- **envelope** — 传热系数、面积、太阳吸收率、透湿率
- **hvac** — 额定制冷量、COP 模式（carnot / constant / linear / table）、设定点
- **deh** — 除湿机额定容量、相对湿度设定点、效率模型
- **led** — PPFD、光效、光周期计划
- **transpiration** — 方法（van_henten / daily / per_plant / daily_per_period / per_plant_per_period）
- **growth** — Van Henten 生长模型参数（`c_rad_phot` 已按生菜标定至商业 PFAL 产量带 30-60 kg 鲜重/m²/年；见"输出结果解读"的产量标定说明）
- **pv** — 面板效率、NOCT、倾角、方位角
- **battery** — 容量、C-rate、往返效率、SOC 限制
- **tariff** — 电价：
  - 新格式（推荐）：`hourly_prices`（24 个值，下标=小时 0-23）+ `export_price`。
  - legacy 格式（兼容）：`peak_price` / `normal_price` / `valley_price` + `peak_hours` / `valley_hours`，加载时展开为 24 值。
  - 参考电价：`vfed design tariffs` 列出区域；`vfed design new ... --tariff <region>` 直接载入。
- **space** — 可选扫描参数范围与目标（`lcoe` / `kwh_per_kg_fresh` / `cost_per_kg_fresh`）
- **opex / equipment_capital / envelope_capital / pump_capital** — 资本与运营成本输入
- **currency / exchange_rate** — 成本报告的货币设置

## 模型适用范围与已知局限

在底层证据薄弱之处，VFED 的物理与作物模型刻意保持简洁。以下边界均附量化数字，便于以恰当的置信度解读结果；另见"输出结果解读"中的产量模型标定说明（生菜标定的 `growth.c_rad_phot`，30-60 kg 鲜重/m²/年 合理性区间）与 Output Glossary（输出术语与警告解释）。

### 作物与生长模型

Van Henten 生物量只响应光照与温度 — 没有水分胁迫耦合：灌溉量变化 2.7 倍，年产量仅移动约 ±0.5%。direct-set 蒸腾方法同样不向生长模型反馈胁迫项。光强响应呈轻微超线性，且没有长光周期惩罚 — 而真实作物在光照超过 17-18 h 后边际递减并出现烧尖（tipburn）。年产量随 `crop_cycle_days` 单调下降，且对生长速率校准敏感 — 引用绝对数值前，请先用自己的收获记录重新标定 `growth.c_rad_phot`（见"输出结果解读"的 30-60 kg 鲜重/m²/年 合理性区间警示与生菜标定说明）。

### 水量参数

`daily_water_L` / `ml_per_plant_day`（及 `_per_period` 变体）代表的是**光期**水量，而非 24 小时总量：模型在夜间仍持续蒸腾，会在名义日水量之上再叠加约 7.5%。请把参数值理解为光期口径，并预期仿真得到的 24 小时总量比它高出这一幅度。

### 天气与光伏（单年）

仿真只用单一年份的天气（默认 2025）— 没有年际波动。光伏出力同样取寿命中值年份：不含组件衰减，也不含逐年差异。

### HVAC COP 冬季上限

制热 COP 被 4.5 的硬顶封顶 — 这是工程上限而非物理规律，冬季不加顶的 Carnot 值可超过 17。参数对 (η_II = 0.35, ΔT_cond = 15 K) 不可唯一辨识：多组参数对给出相同的 COP，请把这个顶当作工程包络，而非标定出来的物理结果。

### 热湿数值处理

温度 ODE 携带一项焓流项，按标准负荷计算的口径处理；在真实换气速率下其影响可忽略。湿度积分器以湿空气质量近似（标准做法为干空气质量），影响约 1-2%。

这些边界在此如实声明，并非当作定论接受 — 后续版本可能收紧。

## 输出结果解读

`vfed evaluate` 与 `vfed sweep` 输出同一套经济/能耗 KPI。所有货币值均以项目配置的 `currency`（默认 USD）报告；`exchange_rate` 仅用于显示标注（如 "1 USD = 7.2 CNY"），**不改变数值**。

> **产量模型标定说明 — 引用绝对 KPI 前必读**：Van Henten 生长系数 `c_rad_phot` 已按 PFAL 生菜标定（P0-3R）：默认 `3.5e-9 kg/J` 将 609 preset 锚定到商业 PFAL 生菜产量带 **30-60 kg 鲜重/m²/年** 的中值附近（约 45 kg/m²/年；30 天茬期、400 µmol/m²/s、800 ppm CO₂），替换此前偏乐观 2-4 倍的文献默认值。推导与交叉校验（量子产额上限、单茬鲜重、整茬光能利用效率）见 `vfed/plants/van_henten.py`。残余不确定性：这是**单参数标定**——与外部设施数据对比 `kwh_per_kg_fresh` / `cost_per_kg_fresh` 前，请先用贵方设施收获记录校验（调整 `growth.c_rad_phot`）；这些 KPI 在 VFED 设计变体之间横向比较仍然有效。

> **默认 OPEX 与货币量级（P1-7）**：若项目 yaml 省略整个 `opex` 节，USD 量级的默认值将**静默生效**：`labor_cost_per_year = 30000` + `misc_opex_per_year = 5000`（currency/年）——在自带 preset 上约占 LCOE 分子的 72-96%。因此 summary 始终报告 `opex_labor_per_year` / `opex_misc_per_year` / `annual_om_pct_of_cost`（= `annual_om` ÷（年化资本 + `annual_om` + 净购电成本）），`vfed evaluate` 控制台会打印 OPEX 占比行；当 opex 节缺省**且** OPEX 占年成本总额超过 50% 时触发一条 WARNING（每次运行至多一条）。请保持量级一致：`opex` 金额、`tariff.hourly_prices` 与所有资本单价都应与 `currency` 声明**同币种**——内置 OPEX 默认值是 USD 量级预设，人民币项目若省略该节，会得到贴着 RMB 标签的 USD 量级数字。

### evaluate 输出（核心 KPI）

> **天气来源自证（P2-2）**：`Project:` 下方第一行标明本次评估实际使用的气象数据：`Weather source  : pre-downloaded city file (Shanghai_2025.csv)`、`cache hit (weather_<lat>_<lon>_<year>_...csv)` 或 `live fetch (api.open-meteo.com)`。P1-3b 之后预下载城市文件与 lat/lon 缓存是两种不同口径——对比结果前先看这一行。该行仅打印在控制台（纯 ASCII）：sweep 输出不会重复（百行扫描不刷屏），导出的 CSV / JSON 保持不变。

| KPI | JSON summary 键 / CLI 标签 | 单位 | 定义 |
|---|---|---|---|
| 年总负荷 | `annual_energy_kwh` / Annual load | kWh/年 | 全年建筑耗电量（LED+HVAC+DEH+杂项） |
| 年产量（干重） | `annual_harvest_kg` / Biomass (dry) | kg 干重/年 | Van Henten 模型全年干物质收获量 |
| 年产量（鲜重） | `annual_harvest_fw_kg` | kg 鲜重/年 | 干重 ÷ `dry_matter_fraction` |
| 单位能耗强度 | `specific_energy_kwh_per_kg` / kWh/kg (fresh) | kWh/kg 鲜重 | 每 kg 鲜重作物的耗电量；CLI 另打印 `kwh_per_kg`（干重口径） |
| 干物质占比 | `dry_matter_fraction` | 无量纲 | 干重→鲜重换算系数（默认 0.05） |
| 年耗水量 | `annual_water_m3` | m³/年 | 全年蒸腾耗水 |
| 平准化成本 | `lcoe` | currency/kWh | （年化资本 + 年运营 + 净购电成本）÷ 年负荷。**注意：是"设施全成本每 kWh 负荷"而非经典发电 LCOE**，列名保留兼容 |
| 单位鲜重成本 | `specific_cost_per_kg` / Cost/kg (fresh) | currency/kg 鲜重 | 全成本 ÷ 鲜重产量 |
| 总资本 | `capital_total` | currency | 全系统装机资本（LED+HVAC+DEH+光伏+电池+设备+围护） |
| 年化资本 | `annual_capital` | currency/年 | 按各组件折旧年限 CRF 年化 |
| 年运营成本 | `annual_om` | currency/年 | 维护费（资本×比例）+ 水费 + 人工 + 杂项 |
| 净购电成本 | `annual_grid_cost_net` | currency/年 | 购电费 − 售电收入 |
| 光伏年发电量 | `pv_generation_kwh` | kWh/年 | 年化 PV 发电（按寿命中期年份计，配合 CRF 年化口径） |
| 电网购电量 | `grid_import_kwh` | kWh/年 | 年电网购入 |
| 电网售电量 | `grid_export_kwh` | kWh/年 | 年电网卖出 |
| 电池循环 | `battery_cycles` | 等效满循环/年 | 全年充放吞吐 ÷（2×电池容量） |
| 光伏自用量 | `pv_self_consumed_kwh` | kWh/年 | PV 直接供给负荷的部分 |
| 光伏自用率 | `pv_self_consumption_rate` | 0–1 | 自用 ÷ 总发电 |
| 电池放电量 | `battery_discharge_kwh` | kWh/年 | 年电池放电 |
| 免费能源 | `free_energy_kwh` | kWh/年 | PV 自用 + 电池放电 |
| 电网独立率 | `grid_independence_pct` | % | （1 − 电网购入 ÷ 负荷）× 100；**电网依赖率 = 100 − 该值** |

其余附带输出：`energy_breakdown`（`hvac_pct`/`led_pct`/`deh_pct`/`misc_pct`，分数形式如 0.30=30%）、`monthly`（12 个月聚合）、`timeseries`（逐时列：`load_kw`/`T_z`/`RH_z`/`E_*_Wh` 等）、`typical_daily`（12×24 典型日负荷）、`sizing`（自动选型铭牌值）。仅当项目配置了 `pv`/`battery` 时 `evaluate` 才打印光伏/电网行。若能源系统禁用（`pv_area_m2=0` 且 `battery_kwh=0`），`grid_import_kwh=年负荷`，电费仍按 `grid_import_kwh × tariff` 计价——计入 `annual_grid_cost_net`、`total_electricity_cost`、`lcoe` 与 `specific_cost_per_kg`，与 sweep 路径的 `(0, 0)` 行口径一致——而光伏/电池相关列（`pv_generation_kwh`、`grid_export_kwh`、`battery_*`、`grid_independence_pct` 等）为 0。三个导出 CSV 的逐列语义见下方 **CSV 列字典**。

### sweep 输出（results.csv 列清单）

`vfed sweep --out results.csv` 按目标升序排列（首行即最优）；单点（`parameter_ranges` 为空）输出单行 CSV。列集取决于是否配置/扫描 PV-电池：未配置 PV/BES 时省略末尾 4 列。

| 列名 | 单位 | 含义 |
|---|---|---|
| （扫描参数列） | 视参数而定 | 被扫描的建筑参数轴：`ppfd_target`/`efficacy`/`photoperiod_hours`/`light_start_hour`/`T_light`/`T_dark`/`RH`/`co2_ppm`/`crop_cycle_days` |
| `currency` | — | 所有货币列使用的货币代码（如 USD、CNY） |
| `pv_area` | m² | 光伏面积（扫描轴或项目固定值） |
| `battery_kwh` | kWh | 电池容量（扫描轴或项目固定值） |
| `lcoe` | currency/kWh | 目标 1（默认） |
| `cost_per_kg_fresh` | currency/kg 鲜重 | 目标 2 |
| `kwh_per_kg_fresh` | kWh/kg 鲜重 | 目标 3 |
| `capital_total` / `capital_led` / `capital_hvac` / `capital_deh` / `capital_pv` / `capital_battery` / `capital_equipment` / `capital_envelope` | currency | 全系统资本分解（泵资本计入总额但未单列） |
| `annual_capital` | currency/年 | CRF 年化资本 |
| `annual_om` | currency/年 | 年运营成本 |
| `annual_grid_cost` | currency/年 | 净购电成本 |
| `annual_load_kwh` | kWh/年 | 年负荷 |
| `biomass_kg` | kg 干重/年 | 年干重产量 |
| `annual_pv_generation` | kWh/年 | 光伏年发电 |
| `annual_grid_import` | kWh/年 | 年购电 |
| `annual_grid_export` | kWh/年 | 年售电 |
| `battery_cycles` | 等效满循环/年 | 电池循环 |

### CSV 列字典

`vfed evaluate --export <dir>` 导出 `summary.csv`、`timeseries.csv`、`monthly.csv` 三个文件。**质量口径：所有产量（harvest）列均为干重（kg DM），仅 `_fw` 后缀列为鲜重换算。** summary 中的 dict 值单元格均为 Python 字面量字典（可用 `ast.literal_eval` 解析），不会出现 numpy repr。removal-limited events / RH clamp / X_d / LCOE 等特殊键的白话解释见下方「输出术语与警告解释（Output Glossary）」。

**RH 合规 / 病害风险（P1-4）：** summary 报告 RH 设定值的实际守持情况。`rh_setpoint_pct` 为目标值（`setpoints.RH`）；`rh_exceed_hours` / `rh_exceed_pct` 统计室内 RH **高于**设定值的小时数（严格 `>`；`rh_exceed_pct` 为占全年 0-1 分数）；`rh_p95_pct` / `rh_max_pct` 给出分布尾部；`rh_disease_risk_hours` 统计室内 RH **达到或超过** `setpoints.rh_disease_risk_threshold` 的小时数（默认 85 % RH — 灰霉病风险带下沿，可在项目 yaml 中配置）。全部指标与 timeseries.csv 导出的逐时 `RH_z` 序列同源，可从 CSV 独立复算；风险小时数 > 0 时发出纯 ASCII `WARNING`。

summary.csv（单行 — 标量 KPI）：

| 列名 | 单位 | 含义 / 口径 |
|---|---|---|
| `annual_energy_kwh` | kWh/年 | 全年建筑耗电（LED+HVAC+DEH+杂项） |
| `annual_led_kwh` / `annual_hvac_kwh` | kWh/年 | LED / HVAC 全年电量（与逐时 `E_led_Wh` / `E_hvac_Wh` 求和一致） |
| `hvac_pct` / `deh_pct` / `led_pct` / `misc_pct` | 分数（0-1） | 各设备占年电量比（`energy_breakdown` 扁平化；0.30 = 30%） |
| `annual_harvest_kg` | kg 干重/年 | 全年干物质收获 — **含**年末在田生物量 |
| `annual_harvest_fw_kg` | kg 鲜重/年 | `annual_harvest_kg` ÷ `dry_matter_fraction` |
| `harvest_final_standing_kg` | kg 干重 | 年末在田生物量（最后一茬未完成部分）。计入 `annual_harvest_kg` 但**不并入任何月份** — `monthly.harvest_kg` 合计 = `annual_harvest_kg` − 该值 |
| `harvest_per_month_avg_kg` | kg 干重 | 月均收割事件产量（仅事件，不含在田） |
| `specific_energy_kwh_per_kg` | kWh/kg **鲜重** | `annual_energy_kwh` ÷ `annual_harvest_fw_kg` — 鲜重口径，列名无 `_fw` 后缀（兼容保留） |
| `specific_cost_per_kg` | currency/kg 鲜重 | （年化资本 + 运营 + 净购电）÷ 鲜重产量 |
| `dry_matter_fraction` | — | 干→鲜换算系数（默认 0.05） |
| `annual_water_m3` | m³/年 | 全年蒸腾耗水 |
| `lcoe` | currency/kWh | （年化资本 + 运营 + 净购电）÷ 年负荷 — 设施全成本口径，非发电 LCOE |
| `capital_total` / `annual_om` | currency、currency/年 | 总资本 / 年运营 |
| `total_electricity_cost` = `annual_grid_cost_net` | currency/年 | 净电费：Σ(`grid_import` × 逐时电价) − Σ(`grid_export` × `export_price`)。始终计价 — 没有"禁用电价"模式；yaml 无 `tariff` 节时用默认值（平价 0.10/kWh、上网 0.05） |
| `grid_import_kwh` / `grid_export_kwh` / `pv_generation_kwh` | kWh/年 | 年购电 / 售电 / 光伏发电（纯电网运行为 0，此时购电 = 负荷） |
| `battery_cycles` / `battery_discharge_kwh` / `pv_self_consumed_kwh` / `pv_self_consumption_rate` / `free_energy_kwh` / `grid_independence_pct` | 混合 | 电池吞吐、光伏自用、电网独立率（见上方 KPI 表） |
| `moisture_clamp_stats` / `temperature_clamp_stats` | dict | 湿度积分器削顶事件（饱和上限 / 零下限）与温度削顶事件 |
| `dehumidifier_performance` | dict | 名义 vs 实际（受室内湿存水限制）除湿量；`removal_limited_*` |
| `deh_smer` | dict | 有效/送达/额定 SMER（kg/kWh，压缩机输入口径，不含风机）；`deh_comp_energy_kwh` 不含风机，`deh_total_energy_kwh` 含风机 |
| `full_load_diagnostics` | dict | 各设备满载运行的小时数/占比/最长连续时长 + 告警阈值 |
| `rh_setpoint_pct` / `rh_exceed_hours` / `rh_exceed_pct` | % / h / 分数（0-1） | RH 目标与控制偏差：室内 RH **高于**设定值（严格 `>`）的小时数及其占全年比例（见上方 RH 合规说明） |
| `rh_p95_pct` / `rh_max_pct` / `rh_disease_risk_hours` | % / % / h | 室内 RH 第 95 百分位与最大值；**达到或超过** `setpoints.rh_disease_risk_threshold` 的小时数（灰霉病风险带，默认 85 % RH，yaml 可配置） |

timeseries.csv（8760 行逐时数据）：

**时间轴口径（P1-3b）：** 仿真窗口为**本地自然年** — 第 0 小时 = 本地 1/1 00:00，月度桶为自然月（2025 年 1 月 = 744 h）。`timestamp` 列为 ISO8601 **本地墙钟**时间（naive，不带 UTC 偏移）。摄取守卫对每个预下载城市文件做对齐检查（首行 = `{year}-01-01 00:00`、8760/8784 行、严格单调）；不满足的文件在打一条可 grep 的 ASCII `WARNING`（含文件名与实际首行时间戳）后**原样沿用 — 绝不插值造数**。旧旋转窗文件（首行为本地 1/1 08:00、尾部回卷到次年 1/1）的值本就是本地墙钟，`+00:00` 后缀是误导性遗留标签：读取时会剥掉该标签，旋转窗由守卫告警（文件里物理上不存在本地 1/1 00:00-07:00 这 8 小时，1 月桶混入次年 1/1 的 8 h，约合年电量的 +0.6%）。此类文件应从 Open-Meteo 重新生成对齐窗。

| 列名 | 单位 | 含义 |
|---|---|---|
| `hour_of_year` | 0-8759 | 仿真步序号 |
| `timestamp` | ISO8601（本地墙钟） | 每小时一条 `YYYY-MM-DDTHH:MM:SS`，8760 个严格单调、无重复的时间戳，从 `{year}-01-01T00:00:00` 起 |
| `price` | currency/kWh | 该小时适用的电价（`tariff.hourly_prices[hour_of_day]`）— 使 CSV 中每个 `electricity_cost` 格子都可独立复算 |
| `month` / `day` / `hour_of_day` | — | 标签取自天气文件（对齐的本地自然年，见上方时间轴说明） |
| `T_z` / `RH_z` | °C / % | 室内温度 / 相对湿度 |
| `T_ext` / `RH_ext` | °C / % | 室外温度 / 相对湿度 |
| `GHI` | W/m² | 水平面总辐照 |
| `load_kw` | kW | 建筑电功率（1 小时步长：kW = kWh/h） |
| `E_hvac_Wh` / `E_deh_Wh` / `E_led_Wh` / `E_misc_Wh` | Wh | 各设备逐时电量（misc = `equipment_power_w`） |
| `X_d` | kg 干重/m² | 在田干物质密度：**锯齿态状态变量，每次收割重置为 `growth.initial_dry_weight`，非累积量** |

monthly.csv（12 行，`month` 为 1-12 不含年份 — 每个桶即天气年的一个自然月，见上方时间轴说明）：

| 列名 | 单位 | 含义 / 口径 |
|---|---|---|
| `energy_kwh__total` / `__hvac` / `__deh` / `__led` / `__misc` | kWh | 各设备月度电量（12 月合计 = 年值） |
| `avg_T_z` / `avg_RH_z` | °C / % | 月均室内状态 |
| `harvest_kg` | kg 干重 | **仅收割事件**（干重）。合计 = `annual_harvest_kg` − `harvest_final_standing_kg` |
| `harvest_fw_kg` | kg 鲜重 | 鲜重换算：`harvest_kg` ÷ `dry_matter_fraction` |
| `water_m3` | m³ | 月度蒸腾耗水（合计 = `annual_water_m3`） |
| `rh_exceed_hours` | h | 月度室内 RH 高于设定值的小时数（12 月合计 = `summary.rh_exceed_hours`） |
| `grid_import_kwh` | kWh | 月度购电（纯电网运行 = `energy_kwh__total`） |
| `electricity_cost` | currency | 月度净电费：Σ(`grid_import` × 逐时电价) − Σ(`grid_export` × `export_price`)；12 个月合计与 `annual_grid_cost_net` 闭合（差 < 0.01）。始终计价（见上方电价说明） |
| `pv_generation_kwh` / `grid_export_kwh` / `battery_net_kwh` | kWh | 仅 PV/电池启用时输出：月度光伏发电 / 售电 / 电池净电量（放电 − 充电） |

### 输出术语与警告解释（Output Glossary）

summary 中最常被问到的输出/警告键的白话解释：

- **removal-limited events** — `dehumidifier_performance.removal_limited_events` / `removal_limited_water_kg`。DEH / HVAC 盘管被要求冷凝的湿分超过房间实际水汽存量的子步。引擎每个子步把名义除湿量钳制到当前室内水汽库存，事件数即被钳制的子步数，`removal_limited_water_kg` 为未能移除的水量（名义 − 实际）。计数大说明除湿配置超出房间可供给的水汽 — 请检查 DEH 选型 / RH 设定值，不要按铭牌容量外推。

- **RH clamp** — `moisture_clamp_stats`。湿度积分器每个子步把室内绝对湿度钳制到物理边界 [0, W_sat(T)]：
  - `sat_clip_events` / `sat_clip_water_kg` — 在饱和上限处被冷凝的水汽（否则 RH 会超过 100 %）；该水的潜热已加回房间热平衡。
  - `floor_clip_events` / `floor_clip_water_kg` — 被"除湿"到零下限以下的水（设备试图把房间干燥到 0 kg/kg — 幻影冷凝）；对应的幻影冷凝热已从热平衡中扣除。
  
  偶发事件属正常数值簿记；水量很大说明湿平衡被强行推出物理边界（DEH 选型不足、设定值不当）。

- **X_d** — timeseries.csv 的 `X_d` 列：在田干物质密度（kg 干重/m²）。它是**锯齿形状态变量**：随茬期增长，每次收割重置为 `growth.initial_dry_weight` — 不是累积产量计数器。年产量看 `annual_harvest_kg`。

- **LCOE** — `lcoe` 是设施全成本每 kWh 负荷：`(annual_capital + annual_om + annual_grid_cost_net) ÷ annual_load_kwh`。玩具算例（货币任意）：`capital_total` 12,000 按 10 年、6 % 折现 → CRF ≈ 0.136 → `annual_capital` ≈ 1,630；`annual_om` = 600；`annual_grid_cost_net` = 1,770 → 年全成本 4,000；年负荷 10,000 kWh → **lcoe = 0.40 currency/kWh**。

## Web 可视化（vfed-web）

`vfed-web/` 是无需后端的浏览器版 VFED：真正的 VFED Python 代码在 **Pyodide Web Worker**（`worker.js`）内运行，前端用 Chart.js 绘图，天气数据在构建时内嵌，浏览器内**不会调用 Open-Meteo**。

### 本地运行

```bash
cd vfed-web
npm start        # 在 http://localhost:8000/ 启动本地服务（= python -m http.server 8000）
# 浏览器打开 http://localhost:8000
```

不建议直接双击 `index.html`（`file://` 协议下 Web Worker 无法加载）。首次加载需联网（从 CDN 拉取 Pyodide + numpy/pandas）。

### 内置预设与仿真链路

- **内置预设** `BUILTIN_PRESETS`：`609`（Fengxian Lettuce PFAL，奉贤生菜）、`lettuce_standard`（Lettuce — Standard PFAL）。
- **仿真链路**：表单 → `generateYaml()` 生成 YAML → `postMessage({type:'simulate', projectYaml})` → Worker 内 Pyodide 运行 vfed 仿真 → 结果回传 → 图表渲染。
- **重新打包**：修改 `vfed/` Python 代码或更新 `weather_cache/` 后，需在 `vfed-web/` 目录重跑 `python bundle.py`，把源码与天气缓存重新内嵌进 `worker.js`。

## 故障排除

第一道防线是 `vfed validate <project.yaml>`：不跑仿真即可校验 YAML、`timestep_s`、`space.objective` 与扫描参数范围。同一套配置检查——包括下文硬限表——在**所有三个入口**（`validate` / `evaluate` / `sweep`）的配置加载阶段统一生效，越界值会在任何仿真开始前以 `[ERROR E001]` 快速失败。

### 错误码速查

| 错误码 | 含义 | 常见触发 | 解决办法 |
|---|---|---|---|
| **E001** | 配置错误 | 文件缺失、YAML 损坏/未知字段/越界；标量字段超出 `HARD_LIMITS`；`--tariff` 地区币种与项目不一致；`parameter_ranges` 非法（未知参数名、非 `[min,max,step]` 三元组、步数非整数、超出硬限）——由 `validate` 报出，`sweep` 入口的范围违规报 **E101** | `vfed design new <name> --preset 609` 重新生成，`vfed validate <yaml>` 定位 |
| **E003** | 天气获取失败 | 无网络、无缓存、缺 `requests` 包 | 见下文"天气离线"三种解法 |
| **E101** | 仿真失败 | 引擎/能系统异常（timestep 非法、天气数据含 NaN、能系统评估抛错）；经 `sweep` 入口触发的 `parameter_ranges` 违规（`validate` 对同一违规报 E001） | 读完整 stderr 报错；`vfed validate`；检查 `timestep_s`；核对天气数据完整性 |
| **E103** | 零负荷 | 年负荷 ≤ 0 | 检查 LED 功率（`auto_deduce` 下 = `ppfd_target`×`covered_area`÷`efficacy`）、`equipment_power_w`、`setpoints` |

### 常见问题与解决

1. **`timestep_s` 必须整除 3600**。校验规则：`sub=max(1,round(3600/dt))` 且 `|sub·dt−3600|≤1`。合法值如 600、900、1200、1800、3600。`vfed validate` 与 `vfed evaluate` 都会报错（"does not evenly divide 3600s"）。

2. **配置值超出 `HARD_LIMITS`（配置加载即报 E001）**。硬限表已迁移至 `vfed/design/project.py`，在**三个入口**（`validate` / `evaluate` / `sweep`）统一生效：下表每个标量配置字段在 YAML 加载时即被检查；扫描范围 `[min,max,step]` 额外要求整体落在带内且 `(max−min)/step` 为整数。越界报错包含字段路径、实际值与合法区间——例如 `led.ppfd_target: 9999` 会在仿真前被拒绝，而不是跑出一个无意义的结果：

   | 参数 | 硬限 | 参数 | 硬限 |
   |---|---|---|---|
   | `ppfd_target` | 50–500 µmol/m²/s | `T_dark` | 10–28 °C |
   | `efficacy` | 1.5–4.0 µmol/J | `RH` | 40–90 % |
   | `photoperiod_hours` | 0–24 h/天 | `co2_ppm` | 300–2000 ppm |
   | `light_start_hour` | 0–23 h | `crop_cycle_days` | 15–60 天 |
   | `T_light` | 15–30 °C | `pv_area`（`pv_area_m2`） | 0–1000 m² |
   | | | `battery`（`battery_kwh`） | 0–500 kWh |

   表中键名为 `space.parameter_ranges` 的参数名；对应的标量 YAML 字段为 `led.*` / `setpoints.*` 以及顶层 `pv_area_m2` / `battery_kwh`。

3. **天气离线（E003）的三种解法**：
   - **联网重试**：联网环境重跑即可，成功后会写入 `weather_cache/` 供后续离线复用；
   - **缓存/预取**：联网环境先执行一次 `vfed evaluate <yaml> --cache weather_cache` 填充缓存；旧格式缓存会自动回退复用（见第 7 条的一行通知）；
   - **离线 CSV**：手动放置缓存 CSV 到 `weather_cache/`（文件名含 lat/lon/year，tilt-aware 键含 tilt/azimuth/tz）。浏览器版则在联网构建时通过 `bundle.py` 内嵌。

4. **E103 零负荷**：多为 LED 功率推导为 0（`auto_deduce` 且 `ppfd_target`/`covered_area`/`efficacy` 配置缺失）或 `equipment_power_w=0`。用 `vfed validate` + 检查上述字段。

5. **LCOE 口径**：`lcoe` 列是设施全成本/每 kWh 负荷，跨项目比较时注意各项目 `currency` 可能不同。

6. **电价币种不一致（E001）**。tariff 库每个地区都带币种标注（`vfed design tariffs` 可查）。`vfed evaluate/sweep --tariff <地区>` 在地区币种与项目 `currency` 不一致时快速失败——例如把 RMB 计价的 `Beijing` 灌进 `currency: USD` 的项目，旧版会产出标签失真约 7 倍的 LCOE。两条出路自行选择：改项目 YAML 的 `currency:`（随后自行核对 `opex`/capital 价格与 `exchange_rate` 是否同币——VFED 不做换算也不改写），或换用与项目同币种的地区。用户自带的 `--tariff` YAML 文件一律视为项目自身币种，不做检查。`vfed design new --tariff <地区>` 是新建场景：新项目 `currency` 自动设为该地区币种（创建回显中明示）。

7. **旧格式天气缓存通知（每次运行至多一条）**。早于 tilt-aware 缓存键的缓存 CSV（`weather_<lat>_<lon>_<year>.csv`，文件名不含 tilt/azimuth/时区）不携带面板几何信息，读取时会从 GHI 重算 `poa_radiation`，并打印一条 ASCII 通知（含缓存文件名）。这是预期行为而非错误：仿真始终按项目请求的几何计算。要永久消除：删除该文件（如 `weather_cache/weather_31.230_121.470_2025.csv`）后联网重跑一次，即可重新取回带几何键的新缓存。sweep 全程只打印一条，不会逐行刷屏。

## 贡献

1. Fork 仓库
2. 创建分支：`git checkout -b feature/my-feature`
3. 进行修改并添加测试
4. 运行测试：`pytest`
5. 提交 Pull Request

## 许可证

本项目基于 MIT 许可证 — 详见 [LICENSE](LICENSE)。

## 引用

如果您在研究中使用了 VFED，请引用：

**论文：**
```bibtex
@article{xiong2026photovoltaic,
  title={Photovoltaic-battery integration strategy in plant factories with artificial lighting},
  author={Xiong, Tianzheng and Cai, Wenxin and Hu, Yue and Song, Mingxuan and Qian, Tao and Bao, Huashan},
  journal={Energy and Buildings},
  volume={361},
  pages={117462},
  year={2026},
  publisher={Elsevier},
  doi={10.1016/j.enbuild.2026.117462}
}
```

**软件：**
```bibtex
@software{vertical-farm-energy-designer,
  title = {Vertical Farm Energy Designer (VFED)},
  author = {Thomas XIONG},
  url = {https://github.com/ThomasXIONG151215/vertical-farm-energy-designer},
  year = {2024}
}
```

## 支持

- **Issues**: https://github.com/ThomasXIONG151215/vertical-farm-energy-designer/issues
- **Discussions**: https://github.com/ThomasXIONG151215/vertical-farm-energy-designer/discussions
