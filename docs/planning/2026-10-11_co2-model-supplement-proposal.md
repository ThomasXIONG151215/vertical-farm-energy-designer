# CO₂ 模型补充方案提案（VFED）

- **日期**：2026-10-11
- **性质**：设计提案（只读审计 + 方案设计，未修改任何代码）
- **状态更新（2026-10-11 晚）**：**M1 已实现并通过全测试套件**（834/834 pytest，含 preset_609 零漂移 sha256 oracle `1764f7e6…`）。落地物：`ode.step_co2`、`devices/co2.py`（CO2Device + 单位换算）、`van_henten.fluxes()` 只读接口、`engine.py` guarded 集成 + CO₂_z/S_co2_inj_g_h/E_co2_Wh 列 + summary/monthly KPI（含 co2_clamp_stats）、`CO2Config`/`EnvelopeConfig.outdoor_co2_ppm` 契约 + HARD_LIMITS/PARAM_PATH_MAP、cli 模板注释、tests/test_co2_{units,balance,control,integration}.py。M2（动态耦合 + 609_co2 变体）/M3（ERV/DCV/经济学）未实施。
- **范围**：室内 CO₂ 浓度动态（质量平衡）、CO₂ 增施设备、与作物模型及通风通道的耦合
- **合规申明**：本方案**不引入 `strategy:` 配置字段**；所有控制均为设备级 setpoint + 死区模式（与 DEH/HVAC 现有模式同构）。新参数全部落点 `vfed/design/project.py` dataclass + `vfed/design/presets.py` 同步。

---

## 1. 现状审计

### 1.1 检索方法

在 `vfed/` 全库（含 cli.py、design/、devices/、physics/、plants/、weather/）以 `(?i)co2|carbon|ppm|photosynth` 检索，共 67 处命中，逐一归类如下（`ppm` 的大量命中来自 `plants_per_m2` 密度字段，与 CO₂ 无关，已剔除）。

### 1.2 CO₂ 目前出现在哪里

| # | 位置 | 现状 | 性质 |
|---|---|---|---|
| 1 | `vfed/design/project.py:861` | `SetpointConfig.co2_ppm: float = 800.0  # ambient CO₂ for plant growth model` | **常量配置**，注释明说是"生长模型的环境输入" |
| 2 | `vfed/design/project.py:104,121` | `HARD_LIMITS["co2_ppm"]=(300,2000)`、`PARAM_PATH_MAP["co2_ppm"]=("setpoints","co2_ppm")` | 可扫描参数（sweep 可对它扫，但每次仍是全年常量） |
| 3 | `vfed/design/project.py:738-746` | `VanHentenConfig.c_co2_1/2/3, c_Gamma` | 光合 CO₂ 响应曲线系数（模型参数，非状态） |
| 4 | `vfed/design/engine.py:552` | DEH 预整定 pre-run：`VanHenten(co2_ppm=p.setpoints.co2_ppm, ...)` | 常量注入 |
| 5 | `vfed/design/engine.py:875` | 运行时生长模型：`VanHenten(co2_ppm=p.setpoints.co2_ppm, ...)` | 常量注入（同一对象全年使用） |
| 6 | `vfed/plants/van_henten.py:67-75` | `self.co2_ppm = co2_ppm` 构造时固定；`self.co2_kgm3` 仅 25 °C 参考值（向后兼容） | **浓度全年恒定** |
| 7 | `vfed/plants/van_henten.py:77-88` | `_co2_density(T_c)`：ppm → kg/m³，理想气体摩尔体积，T/P aware（P3-11） | 单位换算（可复用） |
| 8 | `vfed/plants/van_henten.py:91-108` | `_phi_phot_c`：冠层总光合速率 φ（kg/(m²·s)），浓度项 `X_c − Γ` 驱动 | **CO₂ 响应曲线已存在，但 X_c 来自固定 ppm** |
| 9 | `vfed/plants/van_henten.py:133-138` | 暗呼吸 `resp = c_resp_d·X_d·2^(0.1T−2.5)`（Q10=2） | 呼吸通量可复用为 CO₂ 源 |
| 10 | `vfed/cli.py:339-356` | 项目模板 YAML 注释（"co2_ppm - CO2 concentration (ppm)"等） | 纯文档 |
| 11 | `vfed/design/presets.py` | preset_609 未设 `co2_ppm`（用类默认 800）；无任何 CO₂ 设备/增施字段 | 预设层面无 CO₂ 设备概念 |

### 1.3 CO₂ **没有**出现在哪里（用户说法的验证证据）

1. **室内 CO₂ 浓度不是仿真状态量**：`vfed/physics/ode.py` 的 `RoomODESolver` 只有 `step_temperature`（ode.py:50）与 `step_humidity`（ode.py:89）两个状态积分器，无 CO₂ 通道。状态初始化区（engine.py:895-897）只有 `T_z / W_z / RH_z`。
2. **无 CO₂ 质量平衡**：子步循环（engine.py:1002-1237）的热平衡 `Q_total`（engine.py:1163-1173）与湿平衡 `M_total`（engine.py:1174）均无任何 CO₂ 项。
3. **无 CO₂ 增施设备**：`vfed/devices/` 仅有 led / hvac / dehumidifier / compressor / lag，无 injector。
4. **通风通道不交换 CO₂**：`Envelope.infiltration`（envelope.py:795）返回 (显热, 湿, 潜热)；`mechanical_ventilation`（envelope.py:823）同。均无 CO₂ 通量。
5. **输出无 CO₂ 列**：timeseries 字典（engine.py:1560-1607）与 summary（engine.py:1364-1411）均无 CO₂ 键。
6. **室外 CO₂ 浓度不可配置**：无 `outdoor_co2_ppm` 字段。

> **审计结论**：「现在还没有容纳进去」成立——精确表述为：CO₂ 仅以**全年恒定的设定值输入**形式存在于 Van Henten 生长模型的 CO₂ 响应曲线中（`setpoints.co2_ppm` → 构造期常量），室内浓度动态、增施设备、通风交换、呼吸释放、输出列全部缺失。现有可复用资产：CO₂ 响应曲线（含 T/P aware 密度换算）与暗呼吸 Q10 通量。

---

## 2. 补充方案设计

### 2.1 状态量与平衡方程

**状态量**：室内空气 CO₂ 混合比 `c_z`（kg CO₂ / kg 干空气）。

选择混合比而非密度/直接 ppm 的理由：
- 与湿度状态 `W_z`（kg/kg）同构，通风通道 `envelope.py` 全部是**空气质量流量** `m_dot`（kg/s），交换项写成 `m_dot·(c_out − c_z)` 后量纲自洽、无需每步温度修正；
- `RoomODESolver.step_humidity` 的积分模式（`air_mass = V·ρ`，ode.py:119-122）可直接镜像为 `step_co2`；
- 与 van Henten 模型的接口换算简单：冠层处 CO₂ 质量浓度 `X_c = c_z · ρ_air(T_z, P_atm)`（kg/m³），即 `_phi_phot_c` 需要的量纲。

**平衡方程**（集总参数，显式 Euler，dt = 项目时步，默认 600 s）：

```
V·ρ·dc_z/dt = S_inj + S_resp − S_phot + ṁ_vent·(c_out − c_z)
```

即任务书给出的 `dC/dt = [S_注入 + S_呼吸 − S_光合 + ṁ_通风·(C_out−C) + S_渗风]/V` 的质量流量形式（渗风 S__inf 与机械通风 ṁ_vent 分列，两者在代码中是 `ach` 渗风通道与 `erv_flow_m3h` ERV 通道两条独立叠加的流，见 engine.py:1109-1123）。

**单位制与换算**（全部 T/P aware，复用 van_henten.py:77-88 的理想气体式）：

- ppm（摩尔分数）→ 混合比：`c = y·M_co2/M_air`（线性近似，y≈800e-6 时误差 <0.1%；严格二元式可在实现时用，二者差 <1 ppm 量级）。`M_co2 = 44.01`，`M_air = 28.965`。
- ppm → 密度（输出与生长模型接口）：`X_c = y·1e-6·44.01/v_m(T)`，`v_m = 22.414·(T+273.15)/273.15·(101.325/P_atm)` L/mol。
  参考数值（101.325 kPa）：22 °C 时 1 ppm ≈ 1.817 mg/m³，800 ppm ≈ 1.454 g/m³，420 ppm ≈ 0.763 g/m³；对应混合比 800 ppm → c_z ≈ 1.216e-3 kg/kg。
- 设备容量 g/h → kg/s：`1 g/h = 2.778e-7 kg/s`。
- **注意温度依赖**：状态用混合比可让通风项与温度解耦；ppm 仅在（a）读取室内浓度送控制器/生长模型接口、（b）输出列时用当步 `T_z, P_atm` 换算——与 `_co2_density` 现行语义一致。

**积分器**：`RoomODESolver.step_co2(c_z, S_total_kgs, dt, return_meta=False)`，镜像 `step_humidity` 的契约：
- 地板钳位 `c_z ≥ max(Γ_mass, 0)`（Γ = CO₂ 补偿点，`c_Gamma = 5.2e-5 kg/m³` ≈ 30 ppm，project.py:744；混合比下约 3.4e-5 kg/kg）——光合汇不可能把室内 CO₂ 抽到补偿点以下，正如除湿不可能抽到 W=0 以下；
- `return_meta` 报告钳位量（kg），沿用"钳位不静默"的 P0-2 原则。

**数值稳定性**：CO₂ 时间常数 ≈ `V·ρ/(ṁ_vent + S_phot' 斜率)`。最劣情形 ERV 大流量下 τ ~ 小时级，光合汇线性化后 τ ~ 半小时级，dt=600 s 远低于 2τ，显式 Euler 稳定（无需 2R2C 那种特征值守卫；实现时在测试中数值验证即可）。

### 2.2 源/汇建模

#### ① 作物光合/呼吸（与 `vfed/plants/` 的耦合方式）

`VanHenten._phi_phot_c`（van_henten.py:91-108）**已经计算冠层总光合速率** φ_phot,c（kg/(m²·s)），且 van Henten 碳平衡模型的 φ 以 CO₂ 同化质量计；`step()`（van_henten.py:110-141）内部已算暗呼吸 `resp`（kg 干物质/(m²·s)，Q10=2）。取用方式：

- **改造（M2 核心）**：`step()` 增加可选实参 `co2_density: Optional[float] = None`，`_phi_phot_c` 相应增加 `X_c_override`；`None` → 走现行 `self._co2_density(T_z)`（固定 ppm 路径，**位相同/零漂移**）；非 None → 用动态室内密度。另将 `(φ, resp)` 作为返回元数据暴露（如返回 dict 或增加 `last_fluxes` 属性），供 CO₂ 平衡取用。
- **源/汇换算**：
  - 光合汇 `S_phot = φ · A_canopy`（kg/s；`A_canopy = led.covered_area`，engine.py:887 同源）；
  - 呼吸源 `S_resp = resp · (M_co2/M_CH2O) · A_canopy`，干物质→CO₂ 换算系数 `44.01/30.03 ≈ 1.465`（维持呼吸氧化 CH2O 单位干物质，Thornley & Johnson 2000 植物生理模型标准约定）。
- **609 量级核查**（87.5 W/m² PAR、22 °C、800 ppm、成熟冠层 X_d≈0.45、45 m²）：φ ≈ 2.8e-7 kg/(m²·s) → S_phot ≈ **45 g/h**；暗呼吸 resp ≈ 9.0e-8 kg DM/(m²·s) → S_resp ≈ **21 g/h**。密闭暗期 8 h 无注入时累积 ≈ +470 ppm（420 → ~890 ppm），与密闭植物工厂暗期 CO₂ 积累的文献带（800–1500 ppm，Both et al. 2017 等）一致——这是模型自洽性的一个内置 sanity check。

#### ② CO₂ 增施设备（injector）

设定值 + 死区控制，容量上限 g/h：
- 控制：`c_ppm_z < setpoint − band` → 开（出力受 `capacity_g_per_h` 上限）；`c_ppm_z > setpoint + band` → 关。可选比例带（VFD 式，与 DEH `control="vfd"` 对偶）或 bang-bang（`control="on_off"` + `min_on/min_off` 防短循环，复用 `CompressorState`，devices/compressor.py）。
- `inject_in_dark: false` 默认：暗期光合为零，注入无农艺收益（文献惯例只在光期增施）。
- 注入速率经一阶滞后 `FirstOrderLag(tau_s)`（复用 devices/lag.py），模拟电磁阀/汽化器管路响应。
- 电力：`power_w`（汽化器/阀/风机，默认 50 W 量级）计入 `P_tot`（engine.py:1225），保证能量侧不丢负荷。
- **热效应假设（M1 明确忽略并文档化）**：液态/压缩 CO₂ 汽化吸热（量级 ~350–570 kJ/kg，即 50 g/h 仅 ~5–8 W 冷量）且通常室外汽化后送入；M1 视为零热扰，预留 `injection_heat` 开关（默认 off = 零漂移）。

#### ③ 通风/渗风与室外交换

- 渗风（M1）：`S_inf = m_dot_ach · (c_out − c_z)`，`m_dot_ach = ach·V_room·ρ_air/3600`（与 envelope.py:812 同式）。默认 preset_609 的 `ach=0.001` 近乎密闭，光期内 CO₂ 会被抽干——这正是增施设备的物理需求来源，也解释了为何 609 实机有 CO₂ 储罐。
- ERV/新风机（M3 接口）：CO₂ 无"回收"概念（芯体交换显热/潜热，但送排风体积全量置换），故通量为**全流量** `S_erv = m_v·(c_out − c_z)`，`m_v = erv_flow_m3h·ρ/3600`（envelope.py:859 同式）。注意这与显热/潜热的 `(1−ε)` 形式不同——`erv_latent_eff` **不**适用于 CO₂。未来 DCV（按 c_z 需求调制新风量）留接口：`EnvelopeConfig` 的 `erv_flow_m3h` 保持常量，DCV 作为 `co2.dcv` 子字段在 M3 设计。
- 室外浓度：`envelope.outdoor_co2_ppm`，默认 420（NOAA GML 2024 全球平均 ~424 ppm；市区富集可配 450–600），硬限 (350, 800)。常数即可；逐时室外 CO₂ 数据不可得，不做天气耦合。

#### ④ 暗期呼吸释放

由 ① 的 `S_resp` 项天然覆盖（van't Hoff Q10=2 温度响应已在 van_henten.py:133-138）。M1 阶段（生长模型未耦合）呼吸源可用 `resp` 在固定 `co2_ppm` 下的取值计算（呼吸不依赖 CO₂ 浓度，只依赖 X_d 与 T），即 M1 即可包含暗期积累效应。

### 2.3 配置契约（YAML 字段清单与落点）

遵循硬约束：所有新字段进 `project.py` dataclass，`from_dict` 解析 + fail-fast 校验（HARD_LIMITS/PARAM_PATH_MAP 同步），`presets.py` 同步。

```yaml
# ── 新增 section：co2（CO₂ 增施设备 + 浓度平衡开关）──
co2:
  enabled: false            # 默认关 = 现行路径位相同（零漂移）
  setpoint_ppm: null        # null → 继承 setpoints.co2_ppm（单一事实源）
  band_ppm: 50.0            # 死区半宽
  control: "on_off"         # "on_off" | "vfd"（对偶 DEH P1-1）
  capacity_g_per_h: 200.0   # 容量上限（609 核查点：~45 g/h 即覆盖成熟冠层）
  inject_in_dark: false     # 暗期不注入（默认）
  min_on_s: 0.0             # 防短循环（CompressorState）
  min_off_s: 300.0
  power_w: 50.0             # 汽化器/阀电力
  tau_s: 30.0               # 注入速率一阶滞后

# ── EnvelopeConfig 增量字段 ──
envelope:
  outdoor_co2_ppm: 420.0    # 室外/新风 CO₂（任务书 building.outdoor_co2_ppm；
                            #   本库建筑 section 名为 envelope）
```

**project.py 落点**：
1. 新 dataclass `CO2Config`（字段如上；挂 `DesignProject.co2`，`field(default_factory=CO2Config)`），加入 `__all__`。
2. `EnvelopeConfig.outdoor_co2_ppm: float = 420.0`。
3. `HARD_LIMITS` 增：`outdoor_co2_ppm: (350, 800)`、`co2_band_ppm: (10, 300)`、`co2_capacity_g_per_h: (0, 10000)`；`PARAM_PATH_MAP` 相应条目（使 sweep 可扫描增施设定点/容量——CO₂ 设定点的 LCOE 扫描是本功能的直接研究价值）。
4. `SetpointConfig.co2_ppm` **语义升级而非改名**：`co2.enabled=true` 时它是增施设定点（动态浓度的目标）；`false`（默认）时维持现状语义（生长模型固定环境输入）。避免双字段漂移。
5. `co2_initial_ppm: Optional[float] = None`（CO2Config）：初始浓度；`None` → enabled 时取 setpoint（避免启动瞬态，与 `T_z` 初始化于 `T_light` 的惯例一致，engine.py:895），否则取室外值。

**presets.py 同步**：
- `preset_609` / `preset_609_identified` **不加 co2 字段**（默认 enabled=false，全年基线位相同）——`preset_609` 的年度基线已发表（Energy & Buildings 361:117462，presets.py:156-157 明言必须可复现），任何默认开启都会破坏它。
- M2/M3 交付时新增独立变体预设 `"609_co2"`（`co2.enabled=true, capacity_g_per_h=100, outdoor_co2_ppm=450` 市区值），不动原预设。
- `vfed/cli.py` 项目模板注释块增 `co2:` section 说明（纯文档）。

### 2.4 设备模块：`vfed/devices/co2.py`

遵循 `DEHDevice`（dehumidifier.py）的接口约定（先读该类确认）：
- `__init__(...)`：全部参数显式 + fail-fast 校验（`control` 白名单、`capacity > 0`、`band > 0`、`tau > 0`——同 `_as_tau_pair` 风格）；
- `reset() -> None`：复位 CompressorState 与 Lag；
- `step(co2_ppm_z, dt, setpoint_ppm, is_light) -> Dict[str, float]`：返回 `{"S_inj_kgs", "P_elec_W", "is_on", "mod"}`——与 `DEHDevice.step` 的 dict 契约同构（engine 按 key 取通量与电力）。

内部结构：
```
误差 e = setpoint − c_ppm_z
mod = CompressorState(deadband=band_ppm, proportional_band=0 或 band,
                      min_on_s, min_off_s, m_min=0).update(e, dt, ...)
S_target = mod · capacity_g_per_h / 3.6e6          # kg/s
S_inj   = FirstOrderLag(tau_s).step(S_target, dt)   # 管路/阀滞后
P_elec  = power_w · mod（ON 时；同 DEH 风机计量口径）
inject_in_dark=False 且非光期 → 强制 mod=0
```
无 `size_co2` 自动整定（M1）；M3 加 `size_co2(peak_phot_kgs, safety_factor)` 对偶 `size_deh`（dehumidifier.py:566）。

### 2.5 engine.py 集成点（枢纽改动清单）

`_build_devices`（engine.py:414-770）：
- 末尾按 `p.co2.enabled` 构造 `CO2Device`，返回 tuple 增补一项（默认 None，下游全部 guard 在 flag 后——R34/W3-E 的 `erv_on` 模式，engine.py:981/1116）。

`DesignEngine.run` 状态初始化（engine.py:895 一带）：
- `enabled` 时：`c_z = ppm→混合比(co2_initial_ppm 或 setpoint)`；关闭时不创建、不积分、不加列（**零漂移硬要求**：默认路径一个浮点都不触达，参照 R33/R34 的 IEEE-754 位相同论证，dehumidifier.py:452-453）。

子步循环（engine.py:1002-1237 内）插入顺序——与 plants 光合的先后依赖：
```
1. led.step → light_wm2                                (现有, :1003)
2. 光合/呼吸通量: φ, resp ← grow.fluxes(T_z, light_wm2, X_d,
                     co2_density = c_z·ρ(T_z) [M2] 或 None [M1固定])
   （显式 Euler：通量取步起 c_z，与 T_z/W_z 的顺序约定一致,
     O(dt) 顺序误差已文档化, ode.py:105-110 同款说明）
3. injector.step(ppm(c_z, T_z, P_atm), dt, setpoint, is_light) → S_inj
4. S_vent = (m_dot_ach [+ m_dot_erv 全流量, M3]) · (c_out − c_z)
5. S_total = S_inj + S_resp·1.465 − S_phot + S_vent
   （光合汇经 2.1 的 Γ 地板钳位: 复用 _limit_removal_by_inventory
     的思路, 新增 _limit_co2_uptake — 汇不超过 (c_z − Γ)·air_mass/dt + 当步源）
6. c_z_new = ode.step_co2(c_z, S_total, dt, return_meta=True)
7. grow.step(T_z, light_wm2, X_d, dt, co2_density=c_z_new)   # M2 起反馈
8. 现有 T/W 平衡照旧                                     (:1163-1203)
9. P_tot += P_co2                                        (:1225 增量)
```

输出列（仅 `enabled` 时追加，遵循 T_m/PPFD 的"附加列不得泄漏进默认路径"约定，engine.py:1567-1587）：
- timeseries：`CO2_z`（ppm，子步均值，同 `T_z_out` 口径）、`S_co2_inj_g_h`、`E_co2_Wh`；
- summary：`annual_co2_injected_kg`、`co2_mean_ppm / co2_min_ppm / co2_max_ppm`、`co2_energy_kwh`、`co2_below_setpoint_hours`（对标 `rh_exceed_hours` 的合规 KPI，engine.py:1512）；
- monthly：`co2_injected_kg`（对标 `water_m3` 的月度闭合，engine.py:1549）；
- `energy_breakdown` 保持 4 键结构（CO₂ 电力并入 misc 口径文档说明，避免破坏 test_09/test_19 列契约）。

对 agent/evaluator 的影响：`run(project, weather)` 签名不变；`SimulationResult` 仅增量键；`vfed/agent/` 透传 timeseries/summary，无契约破坏。CAPEX：M3 才在 `sweep._total_capital` 增 CO₂ 项（注入器 + 储罐，`CO2Config.capital: CapitalCostConfig`），M1/M2 不动经济学。

### 2.6 验证数据

- **实测时序**：`data/datasets/agc-2018/`（含 data.zip 等）、`data/datasets/agc-2019/`——AGC 数据集含室内 CO₂ 时序，用于（a）暗期积累斜率标定（呼吸源强）、（b）增施启停带宽度核对、（c）通风purge 衰减时间常数核对。路径已核实存在（2026-10-11 dataset-downloadability-verification.md）。
- **文献基准**：
  - 增施设定带 800–1200 ppm（商业 PFAL 惯例，Kozai et al. 2016 Plant Factory；本库 `co2_ppm` 默认 800 即锚定 van Henten 609 工作点，project.py 注释链）；
  - CO₂ 响应曲线 van Henten (1994, 2003)——已在 `van_henten.py` 实现，动态化只是把常数输入换成状态量，曲线本身不动；
  - 暗呼吸 Q10=2、干物质→CO₂ 系数 1.465（Thornley & Johnson 2000）；
  - 室外 420–424 ppm（NOAA GML 2024）；
  - 密闭暗期积累 800–1500 ppm（Both et al. 2017 等）与 2.2① 的自洽核查一致。

### 2.7 测试计划（pytest，tests/）

| 测试 | 文件 | 断言 |
|---|---|---|
| 单位换算 | `test_co2_units.py` | ppm↔混合比↔密度往返（22/25 °C × 101.325/95 kPa）误差 <1e-9 相对 |
| 质量守恒（注入） | `test_co2_balance.py` | 密闭（ach=0, ERV off, enabled, 无作物汇的 M1 极简配置）恒定注入：`Δ(c_z·air_mass) == S_inj·dt` 逐位闭合；浓度线性上升斜率 = S_inj/(V·ρ) |
| 质量守恒（汇+地板） | `test_co2_balance.py` | 恒定光合汇线性下降；触及 Γ 地板时钳位并经 return_meta 报告（不静默） |
| 控制逻辑 | `test_co2_control.py` | 死区启停（< sp−band 开、> sp+band 关）；`inject_in_dark=false` 暗期 mod=0；min_off 防短循环；容量上限；fail-fast（非法 control/负容量） |
| 零漂移回归 | `test_co2_integration.py` | `preset_609` 默认配置全年结果与现行基线**位相同**（沿用 test_05/test_09 的 sha256 oracle 模式）——这是合入的门禁 |
| 启用集成 | `test_co2_integration.py` | enabled=true 短窗运行：CO₂_z ∈ [outdoor, setpoint+band+ε]、无 NaN、E_co2_Wh > 0 仅光期 |
| 模型耦合（M2） | `test_co2_coupling.py` | `co2_density=None` 路径与现行 `VanHenten.step` 位相同；动态路径下 800 ppm 恒定注入时 φ 与固定路径解析一致 |
| AGC 回放（slow 标记） | `test_co2_agc_replay.py` | 暗期积累斜率落在 AGC 实测 ±30% 带内（呼吸系数不重标定前提下的物理一致性门槛） |

### 2.8 分阶段落地

| 阶段 | 内容 | 交付物 | 依赖 |
|---|---|---|---|
| **M1 最小版** | c_z 状态 + `step_co2` + 渗风交换 + `CO2Device`（setpoint/band/capacity, on_off）+ 光合/呼吸通量取**固定 setpoint 浓度**下的现行模型值（呼吸项即含暗期积累）+ 输出列/summary + 全套单测 | project.py/presets.py 契约、devices/co2.py、ode.step_co2、engine 集成、tests | 无 |
| **M2 模型耦合** | `VanHenten.step(co2_density=...)` 动态反馈（生长吃动态浓度、浓度平衡吃动态 φ/resp）+ `"609_co2"` 变体预设 + vfd 控制模式 + AGC 暗期/增施回放验证 | van_henten.py 增量接口、耦合测试、AGC 回放报告 | M1 |
| **M3 通风/新风联动** | ERV 全流量 CO₂ 通道（envelope 增通量输出）+ DCV 接口（`co2.dcv`，按 c_z 调新风）+ `size_co2` 自动整定 + CAPEX/经济学（`_total_capital` 增 CO₂ 项）+ sweep 扫描配方（setpoint_ppm × capacity × pv_area 的 LCOE 交互） | envelope/envelope.py 增量、sweep/economics、609_co2 预设完整化 | M2 |

### 2.9 风险与兼容性

1. **零漂移（最高优先）**：`co2.enabled=false`（默认）下，所有新代码路径 guard 在 flag 之后，默认路径不触达任何新浮点运算——这是 preset_609 已发表基线与 sha256 回归 oracle 的硬要求。
2. **engine.py 枢纽影响**：`_build_devices` 返回 tuple 增项、子步循环插入 3 个 guarded 块、ts/summary 增量键——`run()` 签名与 `SimulationResult` 既有键全部不变，agent/evaluator 契约无破坏；在 M1 PR 描述中显式列出这三处供 reviewer 对照。
3. **`setpoints.co2_ppm` 语义升级**：向后兼容（默认关=原语义），但 sweep 文档与 CLI 模板注释需同步说明双语义，避免用户误解。
4. **热耦合近似**：忽略汽化冷量的假设写进 co2.py 模块 docstring 与本提案；若未来实测显示可观（>10 W），以 `injection_heat` 开关补入 `Q_total`。
5. **顺序 Euler 的 O(dt) 顺序误差**：与 T_z/W_z 现行约定一致（ode.py:105-110 已有先例文档），dt=600 s 下 CO₂ 时间常数（分钟~小时级）远大于步长，误差可忽略；在 `step_co2` docstring 中同样注明。

---

## 3. 结论

CO₂ 在 VFED 中目前是"生长模型的固定环境输入"（`setpoints.co2_ppm=800` 常量 → Van Henten CO₂ 响应曲线），而非仿真状态量；本提案以最小侵入（默认关闭、零漂移、增量列）补齐浓度动态平衡、增施设备与模型耦合，M1 即可交付可验证的质量守恒与控制仿真，M2/M3 逐步接通作物反馈与新风联动，并利用库内 AGC 数据集与 609 预设完成实证闭环。
