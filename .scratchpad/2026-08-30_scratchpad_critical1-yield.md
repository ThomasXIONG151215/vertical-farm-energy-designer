# Scratchpad — CRITICAL-1 修复 + Van Henten 产量高估溯源 + Calibrate 规划

日期：2026-08-30 · 主题：CLI 易用性地雷修复、产量模型校准缺口、参数拟合落地评估
状态：任务① ✅ 完成（已修复并全量验证）；任务② ✅ 完成（定量归因）；任务③ ⏳ 评估完成（规划见下）

---

## 1. Background and Motivation

四线易用性分析（见 2026-08-30 分析报告）发现：
- CLI 层存在 **CRITICAL-1**：`vfed design new <name> --preset 609 --lat N --lon N` 中 lat/lon 被 preset 硬编码的 `site.city=Shanghai` 静默覆盖，导致用户指定的任何坐标都取上海天气，无任何报错。
- 物理层存在 **Van Henten 生长模型产量高估 ~2×**：模型输出 ~109–113 kg FW/m²/yr vs 真实 PFAL 生菜 30–60 kg FW/m²/yr。
- calibrate（参数拟合）为 greenfield，需评估可落地范围。

## 2. Key Challenges and Analysis

### 2.1 CRITICAL-1 根因链
- `preset_default()` / `preset_609()` 硬编码 `site.city="Shanghai"`（presets.py:28, 59）——刻意为之：离线天气走 `data/weather/Shanghai_2025.csv`。
- `_cmd_design_new`（cli.py:219-267）：`--city` 分支设置 city+坐标；`--lat/--lon` 分支只覆盖坐标、**从不清除 city**。
- `fetch_weather`（weather_bridge.py:242-259）**优先 city 文件** → 指定任意坐标仍返回上海天气（年均 18.8°C vs 纽约 ~11°C）。
- 这正是 AGENTS.md 文档化的唯一 `design new` 调用方式 → 静默错误气候项目，比崩溃更糟。

### 2.2 修复方案（已实施）
`vfed/cli.py` `_cmd_design_new` 中，在原 `if args.lat is not None:` 之前插入：

```python
latlon_given = args.lat is not None or args.lon is not None
if latlon_given:
    # CRITICAL-1 fix: fetch_weather() 给 city 文件优先权；给了坐标就必须放弃 city
    if args.city is not None:
        print("[ERROR] --city cannot be combined with --lat/--lon; use a single location source.", file=sys.stderr)
        sys.exit(1)
    if preset.site.city is not None:
        print(f"[WARN] clearing preset city='{preset.site.city}'; weather will follow the given lat/lon instead. Remember tz_hours still uses the preset value ({preset.site.tz_hours:+.1f} h) unless edited.", file=sys.stderr)
        preset.site.city = None
```

行为契约：
- `--lat/--lon` + `--city` 同给 → fail fast（退出码 1，E 风格错误消息）。
- 仅 `--lat/--lon` → 清除 preset 的 city + WARN（提醒 tz_hours 仍为 preset 值，时区不随坐标自动变化）。
- `--city` 单独使用 → 原逻辑不变。

### 2.3 回归测试（tests/test_07_cli.py，新增 2 例）
- `test_design_new_latlon_clears_preset_city`：`--preset 609 --lat 40.71 --lon -74.01 --year 2025` → rc==0；load 后 `site.city is None`、lat/lon 正确、stderr 含 "clearing preset city"。
- `test_design_new_latlon_conflicts_city`：`--city Shanghai --lat 40.71` → SystemExit code 1、stderr 含 "cannot be combined"。

### 2.4 产量高估 2× 归因（定量）
**根因：`c_rad_phot`（RUE，辐射利用效率）默认 `1e-8 kg/J` 是 Van Henten 2003 番茄文献值，从未对 609 生菜再标定。**
- 代码注释自证（van_henten.py:39-44、project.py:254-260）："CALIBRATION BASIS (C-fix, 2026-08-16): Van Henten 2003 tomato literature default, NOT recalibrated for 609 lettuce. Reference calibration band is 25-100 W/m² PAR (nominal 70); engine feeds ~87.5 W/m², inside the band. Model yields ~109 kg FW/m²/yr vs 30-60 real PFAL (~2x high)."

**609 preset 实测（上海 2025 天气，45 m²，PPFD 400，白光谱）：**

| 配置 | 产量 (kg FW/m²/yr) |
|---|---|
| 当前默认（番茄 RUE=1e-8，PAR 87.5 W/m²） | **113.4** |
| 生菜 RUE=3e-9 | 38.8 ✅ 落真实带内 |
| 生菜 RUE=2.5e-9 | 32.3 ✅ |
| 番茄 RUE 但 PAR 43.7 W/m²（PPFD 200） | 65.0 （仍高估）|
| 生菜 RUE=3e-9 + 降光 | 31.4 ✅ |

**结论**：高估主要来自 **RUE 用错作物**（番茄 1e-8 → 生菜实际约 2.5–3e-9，差 ~3×）；光强（87.5 W/m² 在标定带内但偏上限）只贡献少量。注释里的 "~2x" 是相对 30–60 中间值 45 的保守说法（实际相对带内为 1.9×~3.8×）。
**校准抓手**：`c_rad_phot` 已在 YAML（`growth.c_rad_phot`，注释标注 calibratable）——正好是 calibrate 功能的首选生长通道参数。

> ⚠️ **2026-08-30 更正（用户质疑面积口径后复核）**：上述"2× 高估"结论**基于错误的对照口径**，需撤销。
> - **VFED 的收获面积基准 = LED 受光冠层面积（栽培面积）**：engine.py:429 `crop_area = p.led.covered_area`，单层，模型**无层数/占地面积概念**（cli.py:105 注释："covered_area - lit canopy area (m2) — set to YOUR grow area!"）。
> - **模型按栽培面积的口径**：113.4 kg/m²/yr ÷ 365 = **0.31 kg 鲜/m²/day**，与用户提供的高产上限 **0.34 kg/m²/day** 仅差 ~9%——**按栽培面积看模型其实接近现实上限，并非高估**。
> - 内禀自洽证据：transpiration.py:90 注释 `k_van_henten=1e-4 按 ACTUAL 30-day-cycle harvest X_d≈0.45 kg/m² 标定` → 0.43 kg 干/m²/30d ÷0.05 DM = 0.287 kg 鲜/m²/day，与 0.31 运行值一致。
> - **代码注释里的 "30-60 kg/m²/yr 真实 PFAL" 是不同口径**（很可能是建筑占地面积 footprint 或低光强工况），与模型的"每 m² 栽培面积"不可直接比较 → 原"~2x high"注释本身口径可疑。
> - **真正的结构性问题不是高估，而是模型无法表达多层**：真实 PFAL 占地 A、N 层层架、占空比 f → 栽培面积 N·f·A。若用户把 `covered_area` 设为占地，则模型**严重低估**整厂产出（单层）；若设为单层栽培面积，则整厂 KPIs（LCOE/kWh/kg）无法按占地核算。这才是 calibrate/设计自由度的真缺口。

## 3. High-level Task Breakdown

- [x] ① 定位并修复 CRITICAL-1（cli.py lat/lon 与 city 冲突）
- [x] ① 验证：手动端到端 + pytest（229 passed）
- [x] ① 录入 scratchpad（本文）
- [x] ② 产量高估归因：609 基准 113.4 kg/m²/yr + c_rad_phot 灵敏度扫描
- [x] ③ 评估 calibrate 可落地范围（见 §5）
- [ ] git commit（等用户指示）

## 4. Project Status Dashboard

| 子任务 | 状态 | 备注 |
|---|---|---|
| CRITICAL-1 修复（cli.py） | ✅ | WARN + fail-fast + 测试 |
| 验证（229 passed） | ✅ | test_07_cli 20 / 全量 199 / numerical 30 |
| 产量溯源 | ✅ | 主因 RUE 用错作物，非公式错误 |
| calibrate 规划 | ✅ | 见 §5 |
| commit | ⏳ | 未提交（工作区有修复+测试改动） |

工作区改动（未 commit）：`vfed/cli.py`（修复）、`tests/test_07_cli.py`（+2 测试）、`.scratchpad/2026-08-30_scratchpad_calibration-design.md`（已存在）、`plant-factory-game/`（无关）。

## 5. Calibrate 可落地范围评估与规划（任务③）

已有设计提案（.scratchpad/2026-08-30_scratchpad_calibration-design.md，状态 DESIGN PROPOSAL ONLY，内容见 b1 块 Subagent C 结果）。结合本次定量发现，评估如下：

### 5.1 可直接落地（Low effort / High value）
1. **`fit:` YAML 配置节 + FitConfig dataclass**（project.py）——纯配置契约扩展，preset 无需改动，符合"所有参数在 YAML"约束。
2. **`vfed/calibrate/` 包骨架**：registry.py（点路径 + 边界，复用 sweep._PARAM_PATH_MAP / HARD_LIMITS 模式）、data.py（CSV 摄入 + 小时重采样）、residual.py（deepcopy + 关 auto_size + 窗口化 engine.run）。
3. **`c_rad_phot` 校准通道**（本次扫描已给出先验：边界 [1e-9, 1e-8]、默认起点 3e-9 附近）——生长通道用收获称重约束（kg FW/m²），本次 609 实测数据可直接作为合成验证集。
4. **聚合残差优先**（总 kWh / 平均 T / 平均 RH）→ 先实现不带时序的聚合版，对噪声稳健、最快见效。

### 5.2 需注意的坑（设计必须内置）
- `engine.run()` 会把 auto-size 铭牌写回 project（engine.py:266-305）→ 拟合必须 `deepcopy` + 关 auto_size。
- 输出仅小时级 → 亚小时参数（deadband/tau/min_on）不可辨识，固定之。
- 闭环仿真 → setpoints 必须设成真实控制计划，不能回放实测功率。
- scipy 作为 optional extra（`[project.optional-dependencies] fit = ["scipy>=1.7"]`），无 scipy 时 numpy 有界坐标下降兜底。

### 5.3 建议实施顺序
```
Phase A（本轮可做）：FitConfig + fit: 配置节 + vfed/calibrate 骨架 + c_rad_phot 单参数拟合（收获数据）
Phase B：u_wall_a/c_z/eta_ii 等围护-HVAC 通道（需现场天气 CSV）
Phase C：full least_squares + holdout 报告（scipy optional）
```

## 6. Executor Feedback or Help Requests

- 无阻塞。提醒：CRITICAL-1 修复 + 测试改动**尚未 commit**，待用户确认后提交（建议消息：`fix(cli): clear preset city when --lat/--lon given (CRITICAL-1)`）。
- 产量扫描脚本暂存于 `C:\Users\ADMINI~1\AppData\Local\Temp\opencode\yield_scan.py`（可复用做回归）；609 上海天气已缓存。
