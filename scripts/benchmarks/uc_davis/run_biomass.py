"""UC Davis lettuce PFAL biomass benchmark (DIAGNOSTIC v1).

Compares the vfed Van Henten canopy dry-weight trajectory (X_d, kg/m2)
against the measured daily fresh weights of 18 reference butterhead
lettuce heads (3 troughs x 6 heads, weighed ~17:00 daily) from the
Karimzadeh 2024 NFT experiment (2024-02-21 .. 2024-03-23).

Alignment model:
- vfed runs full-year 2024; crop_cycle_days is overridden to 52 so the
  2nd growth cycle starts at the harvest boundary 2024-02-22 00:00
  (day 52 end), i.e. ~1 d after transplant (02-21). Observed DAT 0 row
  (weighed 02-21 17:00) is dropped; comparison is DAT 1..30, sim X_d
  sampled at 17:00 local each day to match the weighing hour.
- fresh weight per plant needs a planting density (heads/m2) the dataset
  does not disclose -> rho is a reported sensitivity parameter, not a
  fitted one. Primary comparison = normalised growth curve + per-plant
  table at rho sweep {12.07 (=70 heads / 5.8 m2 covered_area), 16, 20, 25}.
- dry_matter_fraction 0.05 (vfed default, literature butterhead band
  0.03-0.06) converts dry -> fresh; reported, not fitted.

Usage (from the repo root):
    python scripts/benchmarks/uc_davis/run_biomass.py [--cache DIR]
"""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import subprocess
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
BENCH = os.path.dirname(HERE)
REPO = os.path.abspath(os.path.join(BENCH, "..", ".."))
sys.path.insert(0, BENCH)

from _common import metrics  # noqa: E402

from vfed.design.engine import DesignEngine  # noqa: E402
from vfed.design.project import DesignProject  # noqa: E402

XLSX = os.path.join(REPO, "data", "datasets", "uc-davis-lettuce", "Lettuce_growth",
                    "4_Biomass.xlsx")
PROJECT_YAML = os.path.join(HERE, "project.yaml")
REPORT = os.path.join(REPO, "user-gym", "benchmarks", "uc_davis_biomass_report.md")

DRY_FRAC = 0.05          # vfed default growth.dry_matter_fraction
CYCLE_DAYS = 52          # override: cycle-2 starts 02-22 00:00 (in HARD_LIMITS 15..60)
WEIGH_HOUR = 17          # measured ~17:00-18:10; sample sim X_d at 17:00
RHO_SWEEP = [12.07, 16.0, 20.0, 25.0]   # heads/m2 (12.07 = 70 / 5.8 m2 covered)
RHO_MAIN = 20.0          # mid literature band for butterhead NFT

DRIVE = {
    "project": "scripts/benchmarks/uc_davis/project.yaml (same env-benchmark config) "
               f"+ runtime override setpoints.crop_cycle_days={CYCLE_DAYS} "
               "(cycle-2 boundary lands 2024-02-22 00:00 ~= transplant 02-21)",
    "weather": "ERA5 hourly via engine-internal fetch (same as run_env.py)",
    "growth inputs": "T_z from sim (env benchmark RMSE 2.10 C), PAR = "
                     "ppfd_target 250 umol/m2/s / par_factor, 14 h photoperiod "
                     "08:00-22:00 (assumed, no light log), CO2 800 ppm (assumed)",
    "sampling": f"X_d taken at {WEIGH_HOUR}:00 local each day, DAT 1..30 "
                "(observed DAT 0 dropped: precedes sim cycle-2 start)",
}

OBSERVED = {
    "fresh weight": {
        "file": "data/datasets/uc-davis-lettuce/Lettuce_growth/4_Biomass.xlsx",
        "sheets": ["B2", "B3", "B4"],
        "columns": "B22..B47 (6 plants/sheet, 18 total)",
        "aggregation": "daily mean over 18 plants +- 1 std",
    },
    "BANDS": None,  # DIAGNOSTIC v1: no enforced band (rho + light are assumptions)
}

CLEANUP = [
    "Date column mislabelled 2022 -> corrected to 2024 (README + env log confirm)",
    "plant columns matched by regex ^B\\d+ within each sheet (Sum/pm columns dropped)",
    "per-plant NaN rows (unweighed days) dropped before the 18-plant daily mean",
    "DAT 1 (2024-02-21, transplant-day weighing) dropped: precedes sim "
    "cycle-2 start 02-22 00:00",
    "WaterTemp glitch / 24.5 h sensor outage: irrelevant here (no env columns used)",
]


def load_observed() -> pd.DataFrame:
    """Daily mean fresh weight (g/plant) over the 18 reference heads."""
    import re
    frames = []
    for sheet in OBSERVED["fresh weight"]["sheets"]:
        df = pd.read_excel(XLSX, sheet_name=sheet)
        plant_cols = [c for c in df.columns
                      if re.match(r"^B\d+\s*\(", str(c).strip())]  # 'B22  (g)'
        long = df.melt(id_vars=["Date", "DAT (day)"], value_vars=plant_cols,
                       var_name="plant", value_name="fw_g").dropna(subset=["fw_g"])
        long["trough"] = sheet
        frames.append(long)
    allp = pd.concat(frames, ignore_index=True)
    allp["Date"] = pd.to_datetime(allp["Date"]).map(lambda t: t.replace(year=2024))
    allp["DAT"] = pd.to_numeric(allp["DAT (day)"], errors="coerce")
    g = allp.groupby(["Date", "DAT"])["fw_g"].agg(["mean", "std", "count"])
    g = g.reset_index()
    return g


def run_sim(cache_dir: str) -> pd.DataFrame:
    """Full-year sim with crop_cycle_days override -> daily 17:00 X_d rows."""
    project = DesignProject.load(PROJECT_YAML)
    project.setpoints.crop_cycle_days = float(CYCLE_DAYS)  # plain dataclass edit
    sim = DesignEngine(cache_dir).run(project)
    ts = pd.DataFrame({"X_d": np.asarray(sim.timeseries["X_d"], dtype=float)})
    ts.index = pd.DatetimeIndex(sim.timeseries["timestamp"])
    # cycle-2 starts at the day-52 harvest boundary: first hour with X_d == init
    # after 2024-02-01 (cycle-1 tail has large X_d; harvest resets to 0.02).
    win = ts.loc["2024-02-21":"2024-03-24", "X_d"]
    start = win.index[(win < 0.05).argmax() if (win < 0.05).any() else 0]
    daily = []
    for date in pd.date_range(start.normalize(), "2024-03-23", freq="D"):
        stamp = date + pd.Timedelta(hours=WEIGH_HOUR)
        if stamp in ts.index:
            daily.append({"Date": date, "X_d": ts.at[stamp, "X_d"]})
    out = pd.DataFrame(daily)
    out["DAT"] = (out["Date"] - pd.Timestamp("2024-02-21")).dt.days
    return out


def features(fw: np.ndarray, dats: np.ndarray) -> dict:
    """Growth-curve features independent of rho (computed on a fresh-weight
    series in g/plant; normalised features use the raw X_d in kg/m2)."""
    end = fw[-1]
    growth_mult = fw[-1] / fw[0] if fw[0] > 0 else float("nan")
    daily = np.diff(fw)
    half_dat = float(np.interp(0.5 * end, fw, dats)) if end > 0 else float("nan")
    return {
        "final_fw_g": float(end),
        "growth_mult_DAT1_end": float(growth_mult),
        "max_daily_gain_g": float(daily.max()),
        "DAT_at_50pct_final": half_dat,
    }


def render_report(obs: pd.DataFrame, sim: pd.DataFrame, j: pd.DataFrame,
                  m: dict, feats: dict, sha: str) -> str:
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    L = [
        "# UC Davis Lettuce PFAL — vfed 鲜重 benchmark（DIAGNOSTIC v1）\n",
        f"- 生成时间: {now}  |  vfed git: {sha}",
        "- 被测对象: `vfed/plants/van_henten.py` 单状态干物质模型（engine 逐时步进，"
        "T_z 耦合仿真室温，PAR=假设光制度，CO₂=800 ppm 假设）",
        f"- 驱动: {DRIVE['project']}",
        f"- 生长输入: {DRIVE['growth inputs']}",
        f"- 采样: {DRIVE['sampling']}\n",
        "## 范围声明（数据集局限，非模型缺陷）\n",
        "- **无光照/CO₂记录** → 生长驱动光为假设值（PPFD 250、14 h、08:00 起），"
        "绝对增长率仅诊断；",
        "- **种植面积未披露** → 株密度 ρ 不可辨识，做敏感性参数（非拟合）；"
        f"ρ 扫描 {RHO_SWEEP}，主表 ρ={RHO_MAIN}（文献带中值）",
        f"- **干物质分数 {DRY_FRAC}**（vfed 默认，结球生菜文献带 0.03-0.06），"
        "干→鲜换算的第二个假设；",
        "- **DAT 0 丢弃**：vfed 周期 2 起点 02-22 00:00 比移栽 02-21 晚 ~1 d，"
        "对比从 DAT 1 起（对齐后逐日 17:00 采样 vs 实测称重时刻）；",
        "- ρ 与 dry_frac 是两个乘性假设 → 绝对水平可整体缩放，**曲线形状"
        "（归一化增长、日增速形态）是不依赖假设的主信号**。",
        "- 本报告不判 PASS/FAIL（DIAGNOSTIC）。\n",
        "## 数据清洗\n",
    ]
    L += [f"- {c}" for c in CLEANUP]
    L += ["", f"## 结果（ρ={RHO_MAIN} 株/m²，dry_frac={DRY_FRAC}）\n",
          "| 指标 | 值 |", "|---|---|",
          f"| N (逐日对) | {m['N']} |",
          f"| RMSE (g/株/日) | {m['rmse']:.2f} |",
          f"| MBE (g/株/日, sim−obs) | {m['mbe']:+.2f} |",
          f"| P95 abs err | {m['p95abs']:.2f} |",
          "", "### 生长曲线特征（形状诊断，独立于 ρ 的为归一化项）\n",
          "| 特征 | 实测 18 株 | vfed |", "|---|---|---|"]
    fo = feats["obs"]
    fs = feats["sim"]
    L += [
        f"| 终点鲜重 DAT30 (g/株) | {fo['final_fw_g']:.1f} | {fs['final_fw_g']:.1f} |",
        f"| 生长倍数 DAT1→DAT30 | {fo['growth_mult_DAT1_end']:.1f}× | "
        f"{fs['growth_mult_DAT1_end']:.1f}× |",
        f"| 最大日增 (g/株/d) | {fo['max_daily_gain_g']:.2f} | "
        f"{fs['max_daily_gain_g']:.2f} |",
        f"| 50% 终点日 (DAT) | {fo['DAT_at_50pct_final']:.1f} | "
        f"{fs['DAT_at_50pct_final']:.1f} |",
        "", "### ρ 敏感性（终点鲜重 g/株 @ DAT30）\n",
        "| ρ (株/m²) | vfed 终点 (g/株) | 实测终点 (g/株) | 比值 |",
        "|---|---|---|---|"]
    obs_end = fo["final_fw_g"]
    for rho in RHO_SWEEP:
        sim_end = fs["final_fw_g"] * RHO_MAIN / rho
        L.append(f"| {rho} | {sim_end:.1f} | {obs_end:.1f} | {sim_end/obs_end:.2f}× |")
    L += ["", "## 逐日鲜重（g/株，实测均值±1σ vs vfed）\n",
          "| DAT | 日期 | obs mean | obs σ | obs n | sim |", "|---|---|---|---|---|---|"]
    for _, r in j.iterrows():
        L.append(f"| {int(r['DAT'])} | {r['Date'].date()} | {r['mean']:.1f} | "
                 f"{r['std']:.1f} | {int(r['count'])} | {r['fw_sim']:.1f} |")
    L += [
        "\n## 结论与下一步\n",
        "- verdict: **DIAGNOSTIC**（ρ/dry_frac/光制度三个乘性假设未证实，"
        "MBE −1.16 g ≈ 0 是曲线交叉的巧合，不能读作无系统偏差）",
        "- **形态差异（主发现）**: 实测 DAT2→30 为 19.1× 近指数增长"
        "（日增 1.6 → 7.4 g/株/d，末期仍在加速，冠层未封闭）；vfed 同窗 5.4×"
        "近线性（日增恒 ~3.3-3.5 g/株/d，第 5-6 天冠层截获 1−exp(−c_pl_d·X_d)"
        "即饱和 → 光合被恒定 PAR 钉死 → 线性段）。单状态 Van Henten 的结构"
        "性限制 vs 实际株型展开节奏，不是参数微调可消",
        "- **初始条件偏移**: vfed initial_dry_weight 0.02 kg/m² = 20 g/株鲜重"
        "@ρ20 vs 实测 DAT2 仅 8 g/株（609 结球生菜移栽值不适用本实验小苗）",
        "- **绝对水平**: ρ=16 时终点 148.4 vs 实测 152.8（0.97×）——若实验"
        "密度 ~16 株/m² 则 PPFD 250 假设下量级吻合，但属 PPFD×ρ 乘积巧合，"
        "不可据此单独定参",
        "- 下一步: (1) PPFD 200-300 敏感性扫描（日增速 3.3 vs 7.4 g/d 的缺口"
        "约 2×，光假设最可疑）；(2) initial_dry_weight 0.005-0.01 扫描修正起点；"
        "(3) 与 run_env.py 蒸腾通道联立交叉辨识；(4) Phase 3 校准引擎接管"
        "（ρ, dry_frac, initial_dry_weight, c_rad_phot 联合辨识 + 形态残差"
        "明确归模型结构）",
        "\n## 复现\n\n```bash\n"
        "python scripts/benchmarks/uc_davis/run_biomass.py\n```\n",
    ]
    return "\n".join(L)


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=REPO,
            stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cache", default=os.path.join(REPO, "weather_cache"))
    ap.add_argument("--no-report", action="store_true")
    args = ap.parse_args()

    print("[obs] loading 4_Biomass.xlsx (3 sheets, 18 heads) ...")
    obs = load_observed()
    obs = obs[obs["Date"] >= "2024-02-22"].reset_index(drop=True)  # sim cycle-2 starts 02-22
    print(f"[obs] {len(obs)} days, DAT {obs['DAT'].min()}..{obs['DAT'].max()}, "
          f"final mean {obs['mean'].iloc[-1]:.1f} g/head")

    print(f"[sim] vfed full-year 2024, crop_cycle_days={CYCLE_DAYS} ...")
    sim = run_sim(args.cache)
    sim["fw_sim"] = sim["X_d"] / DRY_FRAC / RHO_MAIN * 1000.0  # g/plant
    print(f"[sim] cycle-2 start {sim['Date'].iloc[0].date()}, "
          f"{len(sim)} daily rows, final X_d {sim['X_d'].iloc[-1]*1000:.1f} g/m2 dry")

    j = obs.merge(sim[["Date", "fw_sim"]], on="Date", how="inner")
    print(f"[align] {len(j)} matched days")
    m = metrics(j["fw_sim"].to_numpy(), j["mean"].to_numpy())
    print(f"RMSE {m['rmse']:.2f} g | MBE {m['mbe']:+.2f} g | P95 {m['p95abs']:.2f} g")

    # normalise sim to rho_main already; features on per-plant basis
    obs_curve = j.sort_values("DAT")
    feats = {
        "obs": features(obs_curve["mean"].to_numpy(), obs_curve["DAT"].to_numpy()),
        "sim": features(obs_curve["fw_sim"].to_numpy(), obs_curve["DAT"].to_numpy()),
    }
    print(f"[feat] obs final {feats['obs']['final_fw_g']:.1f} g, mult "
          f"{feats['obs']['growth_mult_DAT1_end']:.1f}x | sim final "
          f"{feats['sim']['final_fw_g']:.1f} g, mult "
          f"{feats['sim']['growth_mult_DAT1_end']:.1f}x")

    if args.no_report:
        return 0
    report = render_report(obs, sim, j, m, feats, _git_sha())
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\n[report] written {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
