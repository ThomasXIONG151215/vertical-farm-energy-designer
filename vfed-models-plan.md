# VFED Models Plan — Simulation & Computation Layer

> 所有仿真模型、计算方法、数据基础设施的改动都在此文件。
> UI/WebApp层改动见 `vfed-web-gran-plan.md`。

---

## 0. Baseline — Already Implemented

| 模块 | 能力 | 关键文件 |
|------|------|----------|
| 建筑热湿ODE | Euler积分, T_z + W_z 双状态耦合 | `physics/ode.py` |
| 围护结构 | UA传热, 太阳得热, ACH渗透, 蒸汽渗透 | `physics/envelope.py` |
| 湿空气热力学 | Magnus公式, AH↔RH, VPD, 露点 | `physics/psychrometrics.py` |
| SHR | 旁通系数/机器露点法, 显热比0.30~1.00 | `physics/shr.py` |
| HVAC | COP四模式 (carnot默认: η_II × 卡诺, constant, linear, table), 显热比除湿, 滞回温控, 一阶滞后 | `devices/hvac.py` |
| 除湿机 | 6系数多项式功率面, SMER, 焓效率, 滞回 | `devices/dehumidifier.py` |
| LED | PPFD+光效自动推算功率, 光谱×PAR因子 (white/rb_3to1/rb_4to1/rb_2to1), 光周期(支持跨日) | `devices/led.py` |
| 压缩机 | 滞回死区状态机, 最短启停保护 | `devices/compressor.py` |
| 一阶滞后 | 非对称上升/下降时间常数 | `devices/lag.py` |
| 植物生长 | Van Henten 2003 单状态碳平衡模型, CO₂-温度-光联动 | `plants/van_henten.py` |
| 蒸腾 | 5种模式: 1模型耦合(van_henten) + 4直接设定(daily/per_plant/daily_per_period/per_plant_per_period) | `plants/transpiration.py` |
| PV | 单二极管MPP, NOCT电池温度, POA辐照, 逆变器效率 | `pvbes/pv.py` |
| 电池 | C-rate调度, SOC追踪, 充放电效率, 循环计数 | `pvbes/battery.py` |
| 电网 | 24h逐时电价表, 上网电价, 区域电价DB (10地区) | `pvbes/grid.py`, `pvbes/tariff_db.py` |
| 能源系统 | PV+Battery+Grid联动, LCOE, CRF, TLPS, 投资回收期 | `pvbes/energy_system.py` |
| 天气 | Open-Meteo Archive获取, CSV缓存, Erbs分离, POA计算 | `weather/weather_bridge.py` |
| 城市DB | 60城市坐标库 (中国+国际), 模糊查询 | `weather/city_db.py` |
| 地理编码 | 城市名→lat/lon (Open-Meteo API) | `weather/geocode.py` |
| 水泵 | 定速循环泵, η_pump × η_motor, 光期联动 | `devices/pump.py` |
| 配置模型 | 15个dataclass, YAML序列化, 严格校验 (新增 OpexConfig) | `design/project.py` |
| 设计引擎 | 8760h逐时ODE仿真, 设备构建, 收获循环 | `design/engine.py` |
| 参数扫描 | 笛卡尔积枚举, LCOE优化, 三目标(kWh/kg, $/kg, LCOE) | `design/sweep.py` |
| 预设 | 奉贤609(生菜植物工厂), default | `design/presets.py` |

---

## 1. Gap Analysis — Missing Models

| # | 缺失模型 | 描述 | 优先级 | 状态 |
|---|----------|------|--------|------|
| M1 | LED光谱→真实效率 | 给定光谱分布 → 光合有效光子通量 → 真实PPF/W, 替代固定efficacy | 中 | ✅ 2026-07 |
| M2 | HVAC设定导向 | 给定T_setpoint + 围护负荷 → 推算需冷量 → 反选COP → 动态P_elec | 高 | ✅ 2026-07 |
| M3 | DEH设定导向 | 给定RH_setpoint + 蒸腾量 → 推算需除湿量 → SMER → 反选设备功率 | 高 | ✅ 2026-07 |
| M4 | 天气城市搜索+预下载DB | 城市名→匹配预下载CSV, 标注"2023-2025均值逐时" | 中 | ✅ 2026-07 |
| M5 | 电价爬取数据库 | 按国家/地区爬取电价结构(峰谷平), 存为结构化数据 | 中 | ✅ 2026-07 |
| M6 | 空间布局模型 | 集装箱尺寸 → 栽培架排布(行数/层数/过道≥0.6m) → 可用栽培面积 | 中 | ⬜ |
| M7 | 围护厚度→空间挤压 | 向内增厚 → 净空间减小 → 压缩栽培面积 → 单位面积产量联动 | 中 | ⬜ |
| M8 | 设备空间占位 | 外机(必在外面), 水肥间/电控箱(可选内置隔间 or 外附) | 低 | ⬜ |
| M9 | 水电系统 | 水泵功率/频率, 自定义其它能耗项 | 低 | ✅ 2026-07 |
| M10 | 综合成本模型 | CAPEX(设备+结构) + OPEX(电+水+维护) → 总$, $/kg, 投资回收期 | 高 | ✅ 2026-07 |
| M11 | AI策略对比模型 | AI光(动态PPFD), AI温(动态setpoint), AI电(动态调度) vs 固定策略 | 低 | ⬜ |

---

## 2. Model Implementation Phases

### Phase M-HIGH — 基础重构（Web W1之前必须完成）

#### M2: HVAC 设定导向重构

**现状**: HVAC需要手动给定 `P_rated_w` 和 `cop_value`，用户必须知道设备额定功率。

**目标**: 用户只设定 `T_light`/`T_dark` setpoint → 引擎根据围护负荷 + 内部得热 + 太阳得热 → 自动计算每小时需冷量 → 反选COP（可从温度-COP曲线查） → 推算P_elec。

**改动范围**:
- `devices/hvac.py`: `HVACDevice` 新增 `size_from_load()` 方法
- `design/project.py`: `HVACConfig` 新增可选字段 `auto_size: bool`, `cop_curve: str`
- `design/engine.py`: `_build_devices()` 支持自动选型分支

#### M3: DEH 设定导向重构

**现状**: DEH需要手动给定 `P_ref_w` 和多项式系数。

**目标**: 用户只设定 `RH` setpoint → 引擎根据蒸腾量+渗透得湿 → 自动计算每小时需除湿量 → SMER → 反推P_comp。

**改动范围**:
- `devices/dehumidifier.py`: `DEHDevice` 新增 `size_from_moisture_load()` 方法
- `design/project.py`: `DEHConfig` 新增可选字段 `auto_size: bool`

---

### Phase M-MID — 数据基础设施（Web W1同期或之后）

#### M4: 天气城市搜索 + 预下载数据库

**目标**: 用户输入城市名 → 自动匹配 → 加载预下载的逐时天气CSV。

**方案**: 
- 预下载50+主要城市2023-2025均值逐时数据 → 打包为 `weather_cache/city_db/`
- 建立 `city → (lat, lon, tz, csv_path)` 索引表
- mini搜索引擎: 城市名模糊匹配 → 返回候选列表

**改动范围**:
- `weather/`: 新增 `city_db.py`（索引+搜索）, `batch_download.py`（批量下载脚本）
- `weather/weather_bridge.py`: `fetch_weather()` 增加 `city` 参数

#### M5: 电价数据库

**目标**: 用户选择国家/地区 → 自动加载当地电价结构。

**方案**:
- 爬取主要市场电价(中国各省, 欧洲各国, 美国各州)
- 存为 `data/tariffs/{country}_{region}.yaml`
- 用户选地区 → 自动填充 `TariffConfig.hourly_prices`

**改动范围**:
- 新建 `src/energy_market/`: 爬虫 + 数据库
- `design/project.py`: `TariffConfig` 增加 `region: str` 字段

---

### Phase M-LOW — 高级模型（Web后期阶段对应）

#### M1: LED 光谱模型（对应 Web W3）

**目标**: 给定光谱分布 → 计算光合有效辐射(PAR) → 真实光合光子效率(PPF/W) → 替代固定 efficacy。

**输入**:
- 波长分布: λ(nm) → 相对强度
- PPFD 目标: µmol/m²/s

**计算链**:
1. 光谱 → PAR范围(400-700nm)积分 → PPF(µmol/s)
2. PPF / P_elec = 真实光效(µmol/J)
3. P_elec = PPFD × area / 真实光效 / 4.57

**改动范围**:
- `devices/led.py`: `LEDDevice` 新增 `set_spectrum(wavelengths, intensities)` 方法
- `design/project.py`: `LEDConfig` 新增 `spectrum` 字段

#### M6 + M7 + M8: 空间布局模型（对应 Web W6）

**核心逻辑**:
```
集装箱外尺寸: L × W × H (固定)
围护厚度: δ (每面)
净内部尺寸: (L-2δ) × (W-2δ) × (H-2δ)

栽培架:
  - 排布方向: 沿长度方向
  - 列数 N: 由(净宽 - 过道) / (架宽+间隙) 得出
  - 过道 ≥ 0.6m
  - 层数: 可配置
  - 每层高度: 可配置
  - 可用栽培面积 = N列 × (L-2δ) × 架宽 × 层数

设备占位:
  - 外机: 固定在外, 不计入内部空间
  - 水肥间: 可选内置(占用 L_util × W_util, 压缩栽培面积) 或外附(额外体积)
  - 电控箱: 同水肥间
```

**输出**:
- 实际可用栽培面积 (m²)
- 空间利用率 (%)
- 单位面积日产量联动

**改动范围**:
- 新建 `src/spatial/`: `container.py`, `layout.py`, `equipment.py`
- `design/project.py`: 新增 `SpatialConfig`, `RackConfig`, `EquipmentPlacement`

#### M9: 水电系统（对应 Web W6）

**改动范围**:
- 新建 `src/devices/pump.py`: 功率 × 运行频率
- `design/project.py`: 新增 `PumpConfig`, `MiscLoadConfig`（自定义负载列表）

#### M10: 综合成本模型（对应 Web W5）

**现状**: 已有 `CapitalCostConfig` 和基本CRF折旧, LCOE计算。

**扩展**:
- 设备采购成本（从规格反推, 如 $/W_cooling）
- 结构成本（集装箱/厂房单价）
- 水费
- 维护成本
- 人工成本
- 输出: 总CAPEX, 年OPEX, $/kg, 投资回收期(年)

**改动范围**:
- `pvbes/energy_system.py`: `calculate_metrics()` 扩展
- `design/project.py`: `CapitalCostConfig` 扩展, 新增 `OpexConfig`

#### M11: AI 策略对比模型（对应 Web 后续）

**三种策略**:
1. **AI 光**: 根据外部光照 + 电价 → 动态调整PPFD和光周期（在作物容忍范围内）
2. **AI 温**: 根据外部温度 + 电价 → 动态调整T_setpoint（例如凌晨降温蓄冷）
3. **AI 电**: 根据电价波动 → 动态调度HVAC/DEH启停（预冷/预热, 避开峰电）

**输出**: 每种策略 vs 固定基线 → kWh/kg 差异 → $/kg 差异

**改动范围**:
- 新建 `src/strategies/`: `ai_light.py`, `ai_temperature.py`, `ai_power.py`
- `design/engine.py`: 支持策略模式切换

---

## 3. 依赖关系总图

```
M2(HVAC重构) ──┐
                ├──→ 基础引擎升级 ──→ Web W1(纯数值实时预览)
M3(DEH重构) ───┘

M4(天气DB) ──→ Web W1场景设定
M5(电价DB) ──→ Web W1+W5成本计算

M1(LED光谱) ──→ Web W3(LED光谱UI)

M6+M7+M8(空间布局) ──→ Web W6(3D集装箱)
M9(水电) ──────────→ Web W6

M10(综合成本) ──→ Web W5(全成本计算)

M11(AI策略) ──→ Web后续(AI对比UI)
```

---

## 4. 不在本Plan范围的内容

以下内容归 `vfed-web-gran-plan.md`:
- UI布局和交互设计
- 图表类型和渲染方式
- 用户流程（语言选择、无注册、URL分享）
- 3D可视化（Three.js/Babylon.js）
- 模式切换（单方案 vs 参数遍历）
- 所有前端技术选型
