#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GA 多进程加速版（共享计数器修复）
"""
import os
import json
import numpy as np
import time
import random
import argparse
import functools
from datetime import datetime
from multiprocessing import Pool, cpu_count, Manager
from tqdm import tqdm

# ---------- 1. 导入模拟器 ----------
from grow_two_state1994 import CarbonSimulator as CS64
from grow_one_state1994 import CarbonSimulator as CS32
from grow_one_state2003 import CarbonSimulator as CS0
import pandagrow

parser = argparse.ArgumentParser()
parser.add_argument('-v', '--version', type=int, choices=[0, 32, 64], default=64)
args = parser.parse_args()

version_map = {0: CS0, 32: CS32, 64: CS64}
Simulator = version_map[args.version]
cs_name = f'CS{args.version}'

# ---------- 2. 共享计数器 ----------
mgr = Manager()
_SIM_COUNT = mgr.Value('i', 0)

def count_calls(func):
    @functools.wraps(func)
    def _wrapper(*a, **kw):
        _SIM_COUNT.value += 1
        return func(*a, **kw)
    return _wrapper

# 主进程先装饰一次
Simulator.run_simulation = count_calls(Simulator.run_simulation)

# ---------- 3. 统一参数 ----------
Xd0 = 0.001
c_rad_phot = 1e-8

def panda_cal_biomass(period, X_co2, T_light, T_dark, radiation, X_d_initial):
    df = pandagrow.make_df(period, X_co2, T_light, T_dark, radiation, X_d_initial)
    return Simulator(df, c_rad_phot).run_simulation()['Simulated Dry Weight'].values[-1]

def objective_function(x_normalized, days, avg_hours, period_min, period_max,
                      X_co2, T_light, T_dark, radiation, X_d_initial):
    x = x_normalized * (period_max - period_min) + period_min
    total = days * avg_hours
    x_last = total - x.sum()
    if any(x < period_min) or any(x > period_max):
        return 1e6
    if x_last < period_min or x_last > period_max:
        return 1e6
    periods = np.append(x, x_last)
    return -panda_cal_biomass(periods, X_co2, T_light, T_dark, radiation, X_d_initial)

# ---------- 4. 子进程初始化钩子 ----------
def _init_worker():
    """子进程启动时再次装饰，确保+1生效"""
    global Simulator
    Simulator.run_simulation = count_calls(Simulator.run_simulation)

# ---------- 5. 纯函数：单个体评估（可 pickle） ----------
def _eval_one(individual, config):
    return objective_function(individual,
                             config['days'], config['avg_hours'],
                             config['period_min'], config['period_max'],
                             config['X_co2'], config['T_light'],
                             config['T_dark'], config['radiation'],
                             config['X_d_initial'])

# ---------- 6. 遗传操作 ----------
def tournament_selection(pop, fitness, k=3):
    selected = []
    for _ in range(len(pop)):
        candidates = random.sample(list(zip(pop, fitness)), k)
        winner = min(candidates, key=lambda x: x[1])
        selected.append(winner[0])
    return selected

def crossover(parent1, parent2):
    child = np.zeros_like(parent1)
    for i in range(len(parent1)):
        child[i] = parent1[i] if random.random() < 0.5 else parent2[i]
    return child

def mutate(individual, MUT_RATE=0.1):
    mutated = individual.copy()
    for i in range(len(mutated)):
        if random.random() < MUT_RATE:
            mutated[i] = np.clip(mutated[i] + random.gauss(0, 0.1), 0, 1)
    return mutated

# ---------- 7. 主优化包装 ----------
def genetic_optimizer_wrapper(args):
    start_datetime = datetime.now()
    start_time = time.time()
    config = args
    output_dir = f"outga/{cs_name}_{config['avg_hours']}_{config['period_min']}{config['period_max']}_{start_datetime.strftime('%Y%m%d_%H%M%S')}"
    os.makedirs(output_dir, exist_ok=True)
    with open(f"{output_dir}/params.json", "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4)

    POP_SIZE = 40
    GENERATIONS = 2000
    MUT_RATE = 0.1
    ELITE_COUNT = 2

    # 初始化种群
    norm_init = (config['avg_hours'] - config['period_min']) / (config['period_max'] - config['period_min'])
    population = [np.clip(np.random.normal(norm_init, 0.1, config['days']-1), 0, 1)
                 for _ in range(POP_SIZE)]

    best_fitness = float('inf')
    best_individual = None

    # 多进程评估
    with Pool(processes=cpu_count(), initializer=_init_worker) as pool, \
         open(f"{output_dir}/best_individuals.csv", "w", encoding="utf-8") as f:

        f.write("generation,fitness,params\n")
        pbar = tqdm(range(GENERATIONS), desc="GA")
        for gen in pbar:

            # 1. 并行评估
            fitness = list(pool.map(functools.partial(_eval_one, config=config), population))

            # 2. 选择
            selected = tournament_selection(population, fitness)

            # 3. 交叉
            offspring = []
            for i in range(0, len(selected), 2):
                if i+1 < len(selected):
                    offspring.extend([crossover(selected[i], selected[i+1]),
                                     crossover(selected[i+1], selected[i])])

            # 4. 变异
            mutated = [mutate(ind, MUT_RATE) for ind in offspring]

            # 5. 精英保留（不重算）
            combined = population + mutated
            elite_idx = np.argsort(fitness)[:ELITE_COUNT]
            new_pop = [combined[i] for i in elite_idx]
            remain = POP_SIZE - ELITE_COUNT
            new_pop += random.sample(combined, remain)
            population = new_pop

            # 6. 记录最优
            best_idx = np.argmin(fitness)
            if fitness[best_idx] < best_fitness:
                best_fitness = fitness[best_idx]
                best_individual = population[best_idx]

            x_actual = best_individual * (config['period_max'] - config['period_min']) + config['period_min']
            f.write(f"{gen},{best_fitness},{','.join(map(str, x_actual))}\n")

            pbar.set_postfix({'best': f'{best_fitness:.4f}', 'calls': _SIM_COUNT.value})

    # 结果汇总
    optimized_periods = np.append(best_individual,
                                 config['days']*config['avg_hours'] - sum(best_individual))
    optimized_biomass = -best_fitness
    baseline_biomass = config['baseline_biomass']
    improvement = ((optimized_biomass - baseline_biomass) / baseline_biomass * 100
                  if baseline_biomass > 0 else 0)
    elapsed = time.time() - start_time
    minutes, seconds = divmod(elapsed, 60)

    report_content = f"""生长模型版本: {Simulator.__module__}
Start time: {start_datetime.strftime('%Y-%m-%d %H:%M:%S')}
c_rad_phot = {c_rad_phot}
Xd0 = {Xd0}
Baseline_biomass = {baseline_biomass}
最终优化结果: 提升{improvement:.2f}%
End time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Total time elapsed: {int(minutes)}分{seconds:.2f}秒
--------------------------------------------------
总个体评估次数 = {POP_SIZE * GENERATIONS}
CarbonSimulator.run_simulation() 被调用次数 = {_SIM_COUNT.value}
--------------------------------------------------
"""
    with open(f"{output_dir}/report.txt", "w", encoding="utf-8") as f:
        f.write(report_content)

    return {
        'params': config,
        'optimized_periods': optimized_periods,
        'optimized_biomass': np.float64(optimized_biomass),
        'baseline_biomass': np.float64(baseline_biomass),
        'improvement_pct': np.float64(improvement),
        'calls': POP_SIZE * GENERATIONS,
        'epoch_num': GENERATIONS,
        'output_dir': output_dir
    }

# ---------- 8. 主程序 ----------
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

    result = genetic_optimizer_wrapper(config)
    print(f"✅ 完成！提升 {result['improvement_pct']:.2f}% "
         f"耗时 {(time.time()-start)/60:.1f} min "
         f"调用 {result['calls']} 次")