#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PSO 多进程并行版（Linux 专用）
每代均写 csv，与 GA 保持一致
"""
import os
import json
import numpy as np
import sys
import argparse
import time
from datetime import datetime
from multiprocessing import Pool, cpu_count, Manager
import functools
from tqdm import tqdm

# ---------- 1. 导入模拟器 ----------
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from grow_two_state1994 import CarbonSimulator as CS64
from grow_one_state1994 import CarbonSimulator as CS32
from grow_one_state2003 import CarbonSimulator as CS0
import pandagrow

parser = argparse.ArgumentParser()
parser.add_argument('-v', '--version', type=int, choices=[0, 32, 64], default=64)
args = parser.parse_args()
version_map = {0: CS0, 32: CS32, 64: CS64}
Simulator = version_map[args.version]
cs_name = f"CS{args.version}"

# ---------- 2. 常数 ----------
Xd0 = 0.001
c_rad_phot = 1e-8
SwarmSize = 40
MaxIter = 2000

# ---------- 3. 共享计数器 ----------
mgr = Manager()
_SIM_COUNT = mgr.Value('i', 0)

def count_calls(func):
    @functools.wraps(func)
    def _wrapper(*a, **kw):
        _SIM_COUNT.value += 1
        return func(*a, **kw)
    return _wrapper

Simulator.run_simulation = count_calls(Simulator.run_simulation)

# ---------- 4. worker 钩子 ----------
def _init_worker():
    Simulator.run_simulation = count_calls(Simulator.run_simulation)

# ---------- 5. 业务 ----------
def panda_cal_biomass(period, X_co2, T_light, T_dark, radiation, X_d_initial):
    df = pandagrow.make_df(period, X_co2, T_light, T_dark, radiation, X_d_initial)
    return Simulator(df, c_rad_phot).run_simulation()['Simulated Dry Weight'].values[-1]

def objective_function(x_norm, config):
    days = config['days']
    avg_hours = config['avg_hours']
    pmin, pmax = config['period_min'], config['period_max']
    x = x_norm * (pmax - pmin) + pmin
    total = days * avg_hours
    x_last = total - x.sum()
    if any(x < pmin) or any(x > pmax) or x_last < pmin or x_last > pmax:
        return 1e6
    periods = np.append(x, x_last)
    return -panda_cal_biomass(periods, config['X_co2'], config['T_light'],
                              config['T_dark'], config['radiation'],
                              config['X_d_initial'])

def _eval_one(particle, config):
    return objective_function(particle, config)

# ---------- 6. PSO 主循环 ----------
def pso_parallel(config):
    start_datetime = datetime.now()
    start_time = time.time()

    output_dir = (f"outpso/{cs_name}_{config['avg_hours']}_"
                  f"{config['period_min']}{config['period_max']}_"
                  f"{start_datetime.strftime('%Y%m%d_%H%M%S')}")
    os.makedirs(output_dir, exist_ok=True)
    with open(f"{output_dir}/params.json", "w", encoding='utf-8') as f:
        json.dump({k: v for k, v in config.items() if k != 'Simulator'}, f, indent=4)

    days = config['days']
    avg_hours = config['avg_hours']
    pmin, pmax = config['period_min'], config['period_max']
    dim = days - 1
    norm_center = (avg_hours - pmin) / (pmax - pmin)

    rand = np.random.rand
    S = SwarmSize
    x = np.clip(rand(S, dim), 0, 1)
    v = (rand(S, dim) - 0.5) * 0.2
    p = x.copy()
    fp = np.full(S, np.inf)
    g = p[0].copy()
    fg = np.inf

    log_path = f"{output_dir}/best_individuals.csv"
    with open(log_path, "w", encoding='utf-8') as f:
        f.write("generation,fitness,parameters\n")

    with Pool(processes=cpu_count(), initializer=_init_worker) as pool:
        for it in tqdm(range(MaxIter), desc="PSO", unit="gen"):
            # 下面原样
            fitness = np.array(pool.map(functools.partial(_eval_one, config=config), x))
            # 1) 并行评估
            fitness = np.array(pool.map(functools.partial(_eval_one, config=config), x))
            # 2) 更新个体最优
            better = fitness < fp
            p[better] = x[better]
            fp[better] = fitness[better]
            # 3) 更新全局最优
            if fitness.min() < fg:
                fg = fitness.min()
                g = x[fitness.argmin()].copy()
            # 4) 每代均写 csv（无论是否刷新全局最优）
            best_idx = np.argmin(fitness)          # 本代最优
            best_in_gen = x[best_idx]
            x_actual = best_in_gen * (pmax - pmin) + pmin
            with open(log_path, "a", encoding='utf-8') as f:
                f.write(f"{it},{fitness[best_idx]},{','.join(map(str, x_actual))}\n")
            # 5) 速度/位置更新
            omega = 0.5
            phip = 1.8
            phig = 2.2
            rp = rand(S, dim)
            rg = rand(S, dim)
            v = omega * v + phip * rp * (p - x) + phig * rg * (g - x)
            x = np.clip(x + v, 0, 1)

    # 结果汇总
    optimized_periods = np.append(g, days * avg_hours - g.sum()) * (pmax - pmin) + pmin
    optimized_biomass = -fg
    baseline_biomass = config['baseline_biomass']
    improvement = ((optimized_biomass - baseline_biomass) / baseline_biomass * 100
                   if baseline_biomass > 0 else 0)
    elapsed = time.time() - start_time
    minutes, seconds = divmod(elapsed, 60)

    report = f"""生长模型版本: {Simulator.__module__}
Start time: {start_datetime.strftime('%Y-%m-%d %H:%M:%S')}
c_rad_phot = {c_rad_phot}
Xd0 = {Xd0}
Baseline_biomass = {baseline_biomass}
最终优化结果: 提升{improvement:.2f}%
End time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Total time elapsed: {int(minutes)}分{seconds:.2f}秒
--------------------------------------------------
总粒子评估次数 = {MaxIter * SwarmSize}
CarbonSimulator.run_simulation() 被调用次数 = {_SIM_COUNT.value}
--------------------------------------------------
"""
    with open(f"{output_dir}/report.txt", "w", encoding='utf-8') as f:
        f.write(report)

    np.savetxt(f"{output_dir}/final_best_individual.txt", optimized_periods)

    return {
        'optimized_periods': optimized_periods,
        'improvement_pct': improvement,
        'calls': MaxIter * SwarmSize,
        'output_dir': output_dir
    }

# ---------- 7. 主入口 ----------
if __name__ == "__main__":
    start = time.time()
    config = {
        'days': 28,
        'avg_hours': 16.0,
        'period_max': 24,
        'period_min': 12,
        'radiation': 70,
        'T_light': 24,
        'T_dark': 22,
        'X_co2': 0.002,
        'X_d_initial': Xd0,
        'baseline_biomass': None
    }
    config['baseline_biomass'] = panda_cal_biomass(
        np.full(config['days'], config['avg_hours']),
        config['X_co2'], config['T_light'], config['T_dark'],
        config['radiation'], config['X_d_initial'])
    print(f"Baseline_biomass = {config['baseline_biomass']}")

    result = pso_parallel(config)
    print(f"✅ 完成！提升 {result['improvement_pct']:.2f}% "
         f"耗时 {(time.time()-start)/60:.1f} min "
         f"调用 {result['calls']} 次")