# 取数清单（需人工浏览器下载的 datasheet）

背景：三家官网在建模网络不可达（JS 渲染页面 / TLS 断），webfetch 无法
取到 datasheet PDF。2026-11-02 用户人工提供了 8 份文件，已移入
`reference/pvbes-validation/raw/datasheets/`（git-ignored，提取结果在
`modules/*.yaml`）。录入结果：**huasun_himalaya 与 longi_himo9_670m
两个预设已补全 STC 五点并可仿真**（Himalaya 用 HSN-210-B132 DS730
邻档；LONGi 用 Hi-MO 9 670 档，预设由 X10 改名 himo9）。

## 1. Huasun Himalaya —— 已解决（邻档），顶档仍可选补

- 已用：HSN-210-B132（700-730 W，中文版 PDF，七档表全录
  huasun_himalaya.yaml context_from_source）。预设取 DS730 档。
- 可选补：HSN-212-B132 顶档 770 W 的 V_mp/I_mp（仅当想用 212 顶档时
  才需要；210 邻档已可仿真）。顺带 datasheet "低辐照行"（200 W/m2
  出力）可换算 Marion k 供 G4 弱光曲线。

## 2. LONGi —— 已解决（Hi-MO 9），X10 仍可选补

- 已用：Hi-MO 9 Edge LR8-66HYD 630-670 M（EN，九档表全录
  longi_himo9_670m.yaml）。预设取 670 档，双面率 75%。
- 可选补：Hi-MO X10（580-630 W 抗燃版，108 半片）官方 STC 表——
  旧预设目标型号，数据退存 yaml context_from_source，优先级低。

## 3. JinkoSolar Tiger Neo JKM580N-78HL4-BDV（默认模块）—— 仍需直接复核

- 现状：主条目 6 数仍是"调研来源、规格表未确认"（partial）。
  旁证两条：CEC 库 72HL4 邻档（V_oc 52.5）+ 用户 datasheet 66HL4M
  邻档（JKM625-650N，V_oc 49.28-50.28、gamma -0.29%/degC）——
  均在 jinko_jkm580n.yaml context_from_source。
- 目标：78HL4-BDV 官方规格表确认 6 数 + 面积（eta_stc/area_to_power）。

## 4. Huasun HSN-210R（600-630 W）—— 缺有效文件

- 已提供的是 pdf.js 查看器 HTML 壳（2KB，无数据）。若需要此型号，
  请在浏览器打印为 PDF 后替换。

录入任何新数后需同步：`vfed/pvbes/modules.py` 预设 +
`tests/test_32_pv_modules.py`（Agent A 留注记）。
