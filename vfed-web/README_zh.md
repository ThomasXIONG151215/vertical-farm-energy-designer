# vfed-web — 浏览器前端

VFED 网页版**完全在浏览器中运行**：Pyodide Web Worker 内嵌 `vfed/` 引擎，无需后端服务器，客户端也不需要安装 Python。天气数据来自预下载的 CSV（`data/weather/`），并支持浏览器端 Open-Meteo 在线获取作为补充。

> English version: [README.md](README.md)。

## 本地运行

```bash
cd vfed-web
npm start          # 启动 http://localhost:8000/（python -m http.server 8000）
```

然后用现代浏览器打开 <http://localhost:8000/>。

- **不要**直接双击 `index.html`（`file://` 协议）——Web Worker 和 CSV 请求需要 HTTP 源。
- **首次加载需要联网**：Pyodide（v0.27.0）从 CDN（jsdelivr）拉取。Chart.js 由本地 `public/libs/` 提供，带 CDN 回退。
- Worker 就绪后，选择预设（**609 — 奉贤生菜植物工厂** 或 **生菜 — 标准植物工厂**），调整参数，点击 **运行仿真**。

## 重新打包 Worker（`worker.js`）

`worker.js` 由脚本内嵌 `vfed/` 源码生成：

```bash
cd vfed-web
npm run build      # 执行 python bundle.py
```

修改 `vfed/` 下任何代码或刷新 `data/weather/` 之后，**必须重新打包**——浏览器不会直接读取你的工作目录。

## 部署（Cloudflare Pages）

```bash
cd vfed-web
npm run deploy     # 先构建，再执行 wrangler pages deploy --project-name vfed-web
```

## 仿真链路

1. 界面根据表单生成项目 YAML（`generateYaml`）。
2. YAML 通过 `postMessage` 发给 Pyodide Web Worker（`worker.js`）。
3. Worker 在浏览器内运行 `vfed` 引擎，返回结果 JSON（含 `weather_attrs` 天气来源信息）。
4. 图表用 Chart.js 渲染；结果面板显示天气来源行。

## 冒烟测试（Playwright，仅开发用）

`test.js` 和 `test_comprehensive.js` 用无头 Chromium 驱动本地服务实例：

```bash
npm start                                   # 终端 1
node test.js                                # 终端 2（注意：脚本访问 8080 端口）
node test_comprehensive.js                  # 完整交互测试
```

两个脚本都会等待 Worker 初始化（首次加载 Pyodide + 依赖包约 1 分钟），点击 **运行仿真**，并打印控制台/Worker 输出。它们是临时开发工具，不进入 CI——权威测试套件是仓库根目录的 `pytest`。
