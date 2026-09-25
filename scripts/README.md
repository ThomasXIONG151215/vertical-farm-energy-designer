# scripts / 脚本

Utility scripts for maintaining repository data. / 维护仓库数据的实用脚本。

## download_weather_db.py

One-shot script: downloads **2025 hourly weather for every city** in the city DB from the Open-Meteo archive API and writes CSVs to `data/weather/`. Run it once and commit the resulting files; `fetch_weather(city=...)` then consumes them at design time **without any API call**.

> Note: the script writes **only** to `data/weather/`. The web frontend does not read `vfed-web/data/weather/` (a legacy leftover — the worker uses the bundled `weather_cache/` instead); the script's former `WEB_DIR` mirror copy has been removed.

一次性脚本：从 Open-Meteo archive API 下载城市库中**所有城市的 2025 年逐时天气**，写入 `data/weather/`。运行一次并提交生成的文件；之后 `fetch_weather(city=...)` 在设计时直接使用这些文件，**无需任何 API 调用**。

> 注意：脚本现在**只**写入 `data/weather/`。网页前端不读取 `vfed-web/data/weather/`（该目录是历史遗留，worker 使用的是 bundle 打包的 `weather_cache/`）；脚本原有的 `WEB_DIR` 镜像副本已移除。

### Usage / 用法

```bash
python scripts/download_weather_db.py           # skip cities whose CSV already exists（已存在则跳过）
python scripts/download_weather_db.py --force   # re-download everything（全部重新下载）
```

### Notes / 说明

- Requires `requests` and `pandas` (already core deps). / 依赖 `requests` 和 `pandas`（均为核心依赖）。
- Files are named `{City}_2025.csv`; the year is pinned by the `YEAR` constant in the script.
  文件名为 `{City}_2025.csv`；年份由脚本内 `YEAR` 常量固定。
- Adding a city: extend `vfed/weather/city_db.py` (`AVAILABLE_CITIES` + `_COORDS`), then re-run with `--force` (or delete that city's CSV first).
  新增城市：扩展 `vfed/weather/city_db.py`（`AVAILABLE_CITIES` + `_COORDS`），然后用 `--force` 重跑（或先删除该城市的 CSV）。
