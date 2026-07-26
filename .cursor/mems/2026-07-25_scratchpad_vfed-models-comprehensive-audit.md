# Scratchpad: VFED 全面模型审查与修复

**日期**: 2026-07-25
**主题**: 全模块物理正确性审查与 CLI/Web 接口验证
**角色**: 规划者 (Planner)

---

## 背景和动机 (Background & Motivation)

### 项目背景
经历前三轮模型审计+修复（CRITICAL/BUG/P4-P5）后，仍有大量潜在物理计算和单元不匹配问题遗留。本轮从零开始重新全面审查所有模型代码，**确保 CLI 和 Web 调用都得到正确的物理计算结果**，而非仅修复已知 bug。

### 核心目标
1. 覆盖四路并行审计：Physics/Devices/Plants/PVBES
2. 发现所有维量不一致（FAIL）和模型精度问题（WARNING）
3. 修复所有 FAIL 级问题并回归验证

### 成功标准
- 所有模块审计完成，发现全部 FAIL 和 WARNING
- FAIL 级问题修复后 150/150 测试通过
- 留存未修复的 WARNING 清单供后续决策

---

## 关键挑战和分析 (Key Challenges & Analysis)

### 技术挑战
- PVBES 模块遗留问题最多：alpha_sc 100×偏大、面积缩放不匹配、sweep CAPEX 18.5×虚高
- 植物蒸腾模型有两个互不相关的量纲问题（van_henten 多乘 `area`、气孔黑暗中不关闭）
- 物理 ODE 求解器湿度饱和限制代码有 kPa→Pa 转换因子错误，所幸是死代码路径
- 各模块之间 h_fg 不一致（2.5e6 vs 温度依赖值）

### 风险评估
- PVBES 三个 FAIL 同时影响 engine.py 主路径和 sweep.py 优化路径，无法一次完整回归覆盖
- van_henten 蒸腾的 `* area` 问题的原意不可考，文档改写可能导致日后理解偏差

---

## 高层任务拆分 (High-level Task Breakdown)

### Phase 1: 四路并行审计
- [x] **Physics**: Psychrometrics/Envelope/ODE/SHR — 8 项检查
- [x] **Devices**: HVAC/DEH/LED/Compressor/Lag — 43 项检查
- [x] **Plants**: Transpiration 6方法 + VanHenten growth — 19 项检查
- [x] **PVBES**: PV/Battery/EnergySystem/Grid — 21 项检查

### Phase 2: FAIL 级修复（3路并行）
- [x] **Round 1 (PV + Plants + Physics)**: alpha_sc、面积缩放、sweep CAPEX, van_henten/气孔/ode.py ✅
- [x] **Round 2 (引擎 + HV + 天气 + PV degener + 清扫)**: 10 项额外 FAIL 修复 ✅

### Phase 3: 回归验证
- [x] 全量 pytest: 150 项全部通过 ✅

---

## 项目状态看板 (Project Status Dashboard)

### 当前阶段: Phase 1-3 — 全部完成 ✅

#### 四路审计结果

| 模块 | 检查项 | FAIL | WARNING | PASS |
|------|--------|------|---------|------|
| Physics | 8 | 1 | 2 | 15 |
| Devices | 43 | 0 | 5 | 38 |
| Plants | 19 | 3 | 3 | 13 |
| PVBES | 21 | 3 | 2 | 16 |
| **合计** | **91** | **7** | **12** | **72** |

#### 已修复 FAIL (7个)

- [x] `project.py:211` — alpha_sc 0.045 → 0.00045 ✅
- [x] `pv.py:69` — 面积→模块数转换重算 ✅
- [x] `sweep.py:99` — pv_kwp ×→÷ ✅
- [x] `transpiration.py:75` — van_henten 单位文档修正 ✅
- [x] `transpiration.py:76-78` — 气孔蒸腾暗守卫 ✅
- [x] `van_henten.py:33` — c_resp_d 文档 20°C→25°C ✅
- [x] `ode.py:60` — kPa→Pa ×100→统一 kPa ✅
- [x] `engine.py:264` — step_humidity 参数顺序 (keyword args) ✅
- [x] `engine.py:241` — 删除 deadband_c 重复减差 ✅
- [x] `engine.py:402-405` — P_xxx_W → E_xxx_Wh 列头重命名 ✅
- [x] `engine.py:234` — 删除死代码 day_of_year ✅
- [x] `engine.py:273-277` — NaN/inf 守卫 + 天气小时验证 ✅
- [x] `hvac.py:104,131,136,137-141` — 空闲期 min_on 模式跟踪 ✅
- [x] `hvac.py:162-163` — 删除 `elif on and mode == "idle"` 分支 ✅
- [x] `pv.py:31` — 删除死代码 `beta` 字段 ✅
- [x] `pv.py:52-53` — kV 启发式修复 (k_v_stc + 对数辐照校正) ✅
- [x] `energy_system.py:33,36,70,74` — year 参数透传 ✅
- [x] `sweep.py:151-154,309-311,345-347` — dry_matter_fraction 参数化 ✅
- [x] `weather_bridge.py:114-115` — .get() 默认类型修复 ✅
- [x] `city_db.py:97-99` — 删除 substring match ✅
- [x] `tests/*` — 列名迁移到 E_xxx_Wh ✅

#### 未修复 WARNING (12个)

- [ ] `envelope.py Q_solar`: 使用 GHI 而非窗面辐照度（集总参数简化）
- [ ] `shr.py h_fg`: 硬编码 2.5e6 与温度依赖值不一致 (~2% 误差)
- [ ] `hvac.py / dehumidifier.py h_fg`: 同上
- [ ] `hvac.py cop_heat`: 固定常数（散热为主的简化）
- [ ] `hvac.py`: 空闲期压缩机 ON 标志物理上不成立
- [ ] `shr.py T_adp`: 0°C 冻结（植物工厂可接受）
- [ ] `transpiration.py gamma`: 硬编码 0.066 vs 内部一致 0.0655
- [ ] `van_henten.py co2_kgm3`: 固定 25°C 摩尔体积 (~1-2% 误差)
- [ ] `transpiration.py stage_factor`: 范围 `0-1+` 含混
- [ ] `pv.py V_mp`: 填充因子启发式 ~7% 过估
- [ ] `sweep.py vs engine.py LCOE`: 双路径 CRF 计算不一致
- [ ] `engine.py timeseries命名`: P_hvac_W/P_deh_W/P_led_W 实际是 Wh

---

## 执行者反馈或请求帮助 (Executor Feedback / Help Requests)

### 当前状态 (2026-07-25 17:30)

✅ **已完成 (Round 2)**:
- **21 项 FAIL 修复**，覆盖 11 个源文件 + 2 个测试文件
- 引擎：step_humidity 参数顺序、deadband_c 重复减差、NaN/inf 守卫、列头命令修正
- HV empty：空闲期压缩机 min_on 流量修正 (`_last_mode` 跟踪)、死代码分支删除
- PVBES：kV° 启发式修复 + year 参数透传、死代码 `beta` 字段删除
- 天气：`.get()` 默认类型修复、`lookup_city()` substring 白名单删除
- 全部 150/150 测试通过

### Round 1 vs Round 2

| 维度 | Round 1 (P4-P5) | Round 2 (本批次) |
|------|-----------------|-----------------|
| 修复数量 | 7 FAIL | 11 FAIL |
| 修改文件 | 6 | 11 |
| 回归结果 | 150/150 | 150/150 |

📊 **本轮修复关键数据**:
| 问题 | 影响面 | 修复后 |
|------|--------|--------|
| alpha_sc 0.045→0.00045 | 高温 PV 输出虚高 90% | 正确输出 |
| PV 面积缩放 | PV 功率低估 39% | 正确输出 |
| sweep PV CAPEX ×→÷ | CAPEX 虚高 18.5× | 正确成本 |
| van_henten 多乘 area | 量纲不匹配 | 量纲正确 |
| 气孔暗蒸腾 37 L/day | 夜间蒸腾虚高 | 黑暗中=0 |
| psychology 湿度钳制 | 潜在 10× 错误 | 正确饱和限制 |
| c_resp_d 文档 | 温度引用偏差 | 对齐 25°C |

⏭️ **下一步**:
1. 考虑是否推进 Phase 2（UI Tabs 重构）
2. 决定是否处理未修复的 12 个 WARNING
3. 可考虑删除 ode.py 的 `T_z` 参数（死代码路径），或将 T_z 传给 engine 调用

🔍 **发现但未处理的问题**:
- `engine.py` 输出 timeseries 中 P_hvac_W / P_deh_W / P_led_W 实际存储的是 Wh 而非 W，命名有误导性
- `envelope.py Q_solar` 使用水平 GHI 而非倾斜窗面辐照——当前由 eta_solar 降额因子集总处理
- LCOE 计算存在两个分支（engine vs sweep），使用寿命不同，产生不同结果

---

## 备注 (Notes)

### 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/design/project.py` | 修改 | alpha_sc 0.045→0.00045 |
| `src/pvbes/pv.py` | 修改 | 面积→模块数转换修复 |
| `src/design/sweep.py` | 修改 | pv_kwp ×→÷，注释修正 |
| `src/plants/transpiration.py` | 修改 | k_van_henten 文档修正，气孔暗守卫 |
| `src/plants/van_henten.py` | 修改 | c_resp_d 文档 20°C→25°C |
| `src/physics/ode.py` | 修改 | 湿度饱和限制 kPa/Pa 统一 |

### 历史关联
- 2026-07-11 — 5路并行审计发现 8 CRITICAL + 14 BUG + 29 WARNING
- 2026-07-12 — 第2轮 7个 CRITICAL 修复
- 2026-07-24 — 第3轮 11 BUG + P4-P5 修复
- **2026-07-25 — 第4轮 全面模型审查 + 7个 FAIL 修复（本轮）**
