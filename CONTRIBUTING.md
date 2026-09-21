# Contributing to VFED / VFED 贡献指南

Thanks for helping improve the Vertical Farm Energy Designer! This guide covers the essentials; architecture details live in the [README](README.md) and the review checklist in [REVIEW.md](REVIEW.md).

感谢参与改进 Vertical Farm Energy Designer！本指南只讲要点；架构细节见 [README_zh.md](README_zh.md)，审查清单见 [REVIEW.md](REVIEW.md)。

---

## Dev setup / 开发环境

```bash
pip install -e ".[dev]"    # core deps + pytest/black/flake8
pytest                     # run the test suite
```

Requirements: **Python >= 3.8**, `numpy`, `pandas`, `pyyaml`, `requests`. There is **no EnergyPlus dependency** — the building model is a pure-Python ODE solver.

环境要求：**Python >= 3.8**，依赖 `numpy`、`pandas`、`pyyaml`、`requests`。**不依赖 EnergyPlus**——建筑模型是纯 Python ODE 求解器。

## Tests / 测试约定

- Run `pytest` before committing; CI runs black + flake8 + pytest.
- New physics/devices/plants/pvbes behaviour needs a test. Consult `REVIEW.md` (heat & mass transfer + energy dispatch checklist) when touching those modules.
- Keep the web UI (`vfed-web/`) consistent: after changing `vfed/`, run `npm run build` inside `vfed-web/` to rebundle `worker.js`.

- 提交前运行 `pytest`；CI 会跑 black + flake8 + pytest。
- 新增 physics/devices/plants/pvbes 行为需要配套测试；改动这些模块时请对照 `REVIEW.md`（传热传质 + 能源调度清单）。
- 保持 Web 端一致：改完 `vfed/` 后，在 `vfed-web/` 内执行 `npm run build` 重新打包 `worker.js`。

## Config contract / YAML 配置契约

**All parameters live in YAML.** `vfed/design/project.py` is the config contract:

- Adding or renaming a config field requires updating **both** `vfed/design/project.py` (the `DesignProject` dataclasses) and `vfed/design/presets.py`.
- Use the `DesignProject` dataclasses — never raw dicts — when touching config code.
- Hardware datasheet vocabulary is mapped via `HARDWARE_ALIASES` (project.py); validity bounds live in `HARD_LIMITS` (project.py).
- Error-code contract: `E001` config, `E003` weather, `E101` simulation, `E103` zero load (see `vfed/agent/evaluator.py`). New failure modes should reuse or extend these codes.

**所有参数都在 YAML 里。** `vfed/design/project.py` 是配置契约：

- 新增或重命名配置字段，必须**同时**更新 `vfed/design/project.py`（`DesignProject` 数据类）和 `vfed/design/presets.py`。
- 改配置相关代码时使用 `DesignProject` 数据类——不要用裸字典。
- 硬件 datasheet 词汇通过 `HARDWARE_ALIASES`（project.py）映射；取值边界在 `HARD_LIMITS`（project.py）。
- 错误码契约：`E001` 配置、`E003` 天气、`E101` 仿真、`E103` 零负荷（见 `vfed/agent/evaluator.py`）。新失败模式应复用或扩展这些错误码。

## Documentation / 文档双语同步

`README.md` (English) and `README_zh.md` (中文) must stay in sync: any user-visible feature, config field, CLI flag, or output change should be documented in **both** files. Keep section order parallel so future diffs stay easy.

`README.md`（英文）与 `README_zh.md`（中文）必须保持同步：任何用户可见的功能、配置字段、CLI 参数或输出变更，都要**同时**写入两个文件。章节顺序保持一致，便于日后对照。

## Boundaries / 边界

- **Never** hardcode weather data — always use `fetch_weather` or the `data/weather/` cache.
- **Never** import from `research/` into `vfed/`, and don't modify `research/` — it is archived for reproducibility.
- No hardcoded science: thermodynamic/fluid values must come from equations or cited literature.
- Ask first before adding new dependencies — keep the footprint small.

- **禁止**硬编码天气数据——一律使用 `fetch_weather` 或 `data/weather/` 缓存。
- **禁止**从 `research/` 导入到 `vfed/`，也不要修改 `research/`——它是为可复现性保留的归档。
- 不硬编码科学常数：热力学/流体数值必须来自公式或文献引用。
- 新增依赖请先讨论——尽量控制依赖规模。

## PR checklist / 提交清单

1. `pytest` passes / 测试通过
2. Config fields registered in `project.py` + `presets.py` / 配置字段已登记
3. Both READMEs updated / 两个 README 已同步
4. `vfed-web/worker.js` rebundled if `vfed/` changed / 改过引擎则已重打包
5. No secrets or generated caches committed / 未提交密钥或生成缓存（`weather_cache/` 已 git-ignore）
