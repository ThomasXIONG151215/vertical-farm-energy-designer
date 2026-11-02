# 取数清单 —— 需要人工浏览器下载的 datasheet（2026-11-01）

以下三份官方规格表在建库网络上不可达（JS 渲染页面或 TLS 阻断），webfetch
无法获取。请用桌面浏览器访问，下载 PDF（或另存页面），放入本目录
`reference/pvbes-validation/raw/`，并按下面"目标字段"逐项录入对应
`modules/*.yaml`。录入后同步更新 `vfed/pvbes/modules.py` 预设与
`tests/test_32_pv_modules.py`（Agent A 已留注记）。

## 1. Huasun Himalaya HSN-212-B132（最高优先，只差 2 个数）

- 入口：https://www.huasunsolar.com/ （产品页 → Himalaya 系列 → G12 组件）
- 已有：V_oc 50.46 / I_sc 19.33 / N_s 132 / gamma -0.24%/°C / eta 24.8% / 衰减 1%+0.3%/yr
- **目标字段：V_mp_stc（V）、I_mp_stc（A）**（770W 顶档；如表格分档请抄全部八档）
- 顺带：datasheet 如有"low-light performance / NOCT 行"，抄 200 W/m² 输出（算 Marion k 用）

## 2. LONGi Hi-MO X10（580-630 W 抗燃 108 半片变体）

- 入口：https://www.longi.com/en/products/ （Hi-MO X10 → firefighting/roof 版）
- 已有：eta 24.8% / gamma -0.26%/°C / N_s 108 / 衰减 1%+0.35%/yr（系列级）
- **目标字段：V_oc_stc、I_sc_stc、V_mp_stc、I_mp_stc、组件尺寸（长×宽 mm）**
- 注意：官网另有 640-670 W 144 半片变体（其 V_oc 53.70-54.30 / I_sc 15.13-15.60 已存档于
  longi_himo_x10.yaml 的 context_from_source，不要混淆——我们要的是 108 半片版）

## 3. JinkoSolar Tiger Neo JKM580N-78HL4-BDV（现用默认模块，复核性质）

- 入口：https://www.jinkosolar.com/en/site/module （Tiger Neo 系列 → 580W n-type）
- 待复核（我们现值，来源=先期调研未确认）：V_oc 57.34 / I_sc 13.98 / V_mp 45.85 / I_mp 12.66 / N_s 156 / gamma -0.30%/°C
- **目标：确认上述 6 个数 + 组件面积（算 eta_stc 与 area_to_power）**
- 旁证已有：CEC 库中 72HL4 邻档（V_oc 52.5 等，见 jinko_jkm580n.yaml context_from_source）

## 通用注意事项

- 录入时保留 datasheet 原文档名与下载日期，更新对应 yaml 的 source 块
  （method: datasheet，status 可升 verified）。
- 任何字段若 datasheet 也没有，保持 null，不要估。
- Marion k（弱光）需要 P200：三家里任何一家 datasheet 给出低光行都可以启用 G4 曲线。
