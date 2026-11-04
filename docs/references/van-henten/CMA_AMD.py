#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
版本信息：统一参数，准备定稿（Windows 安全多进程版）
"""
# ---------- 0. 必须放最顶部 ----------
import os
import json
import numpy as np
import cma
import time
import argparse
import functools
from tqdm import tqdm
from datetime import datetime
# ---------- 0. 顶部额外 import ----------
from multiprocessing import Pool, cpu_count, Manager, freeze_support
import functools

# ---------- 1. 共享计数器（主进程里再真正实例化） ----------
_SHARED_COUNT = None          # 真实模拟次数（装饰器）
_REQUEST_COUNT = None         # 请求评估次数（evaluator入口）
_POOL = None                  # 单例Pool

# ---------- 2. 装饰器 & 子进程初始化钩子 ----------
def _counting_wrapper(func, counter):
    @functools.wraps(func)
    def _wrapper(*a, **kw):
        counter.value += 1
        return func(*a, **kw)
    return _wrapper

def _init_worker(sim_counter):
    """每个子进程启动时执行一次"""
    global _SHARED_COUNT
    _SHARED_COUNT = sim_counter
    # 把装饰器打到类方法上（只统计真实求解）
    Simulator.run_simulation = _counting_wrapper(Simulator.run_simulation, sim_counter)

# ---------- 2. 解析命令行，决定用哪个模拟器 ----------
from grow_two_state1994 import CarbonSimulator as CS64
from grow_one_state1994 import CarbonSimulator as CS32
from grow_one_state2003 import CarbonSimulator as CS0
import pandagrow

parser = argparse.ArgumentParser(description='Lettuce Growth Model Simulation')
parser.add_argument('-v', '--version', type=int, choices=[0, 32, 64],
                    default=64, help='模拟器版本 (0,32,64)')
args = parser.parse_args()

version_map = {0: CS0, 32: CS32, 64: CS64}
Simulator = version_map[args.version]
cs_name = f'CS{args.version}'

# ---------- 3. 统一参数 ----------
Xd0 = 0.001
c_rad_phot = 1e-8

# ---------- 4. 业务函数 ----------
def panda_cal_biomass(period, X_co2, T_light, T_dark, radiation, X_d_initial):
    df = pandagrow.make_df(period, X_co2, T_light, T_dark, radiation, X_d_initial)
    results_df = Simulator(df, c_rad_phot).run_simulation()
    return results_df['Simulated Dry Weight'].values[-1]

def objective_function(x_normalized, params, days, avg_hours, period_min, period_max):
    x = x_normalized * (period_max - period_min) + period_min
    total = days * avg_hours
    x_last = total - x.sum()
    if any(x < period_min) or any(x > period_max):
        return 1e6
    if x_last < period_min or x_last > period_max:
        return 1e6
    periods = np.append(x, x_last)
    return -panda_cal_biomass(periods, params['X_co2'], params['T_light'],
                              params['T_dark'], params['radiation'], params['X_d_initial'])

# ---------- 3. 创建评估器（不建 Pool，只返回映射函数） ----------
def create_evaluator(params, config, sim_counter):
    from functools import partial
    bound_objective = partial(objective_function, params=params,
                            days=config['days'], avg_hours=config['avg_hours'],
                            period_min=config['period_min'], period_max=config['period_max'])
    def evaluator(points):
        # ★★★ 请求计数（含被约束挡掉的）
        _REQUEST_COUNT.value += len(points)
        # 使用全局单例 Pool
        return _POOL.map(bound_objective, points)
    return evaluator
# ---------- 5. 优化包装 ----------
def cma_optimizer_wrapper(args, folder_name, counter):
    start_time = time.time()
    config = args
    start_datetime = datetime.now()
    output_dir = (f"{folder_name}/{cs_name}_{config['avg_hours']}_"
                  f"{config['period_min']}{config['period_max']}_"
                  f"{start_datetime.strftime('%Y%m%d_%H%M%S')}")
    os.makedirs(output_dir, exist_ok=True)

    with open(f"{output_dir}/params.json", "w", encoding='utf-8') as f:
        json.dump(config, f, indent=4)

    # ----------------  tqdm 包装器 ----------------
    class TqdmCMA:
        def __init__(self, total):
            self.bar = tqdm(total=total, desc='CMA', unit='gen')

        def update(self, es):
            gen = es.countiter
            best = es.best
            # 每代均写 csv
            x_actual = best.x * (config['period_max'] - config['period_min']) + config['period_min']
            with open(f"{output_dir}/best_individuals.csv", "a", encoding='utf-8') as f:
                f.write(f"{gen},{np.float64(best.f)},"
                        f"{','.join(map(str, np.float64(x_actual)))}\n")
            # 更新进度条
            self.bar.update(1)
            self.bar.set_postfix({'best': f'{best.f:.4f}',
                                 'calls': counter.value})

        def close(self):
            self.bar.close()

    # 提前写 csv 表头
    with open(f"{output_dir}/best_individuals.csv", "w", encoding='utf-8') as f:
        f.write("generation,fitness,parameters\n")

    norm_init = (config['avg_hours'] - config['period_min']) / (config['period_max'] - config['period_min'])
    auto_init = np.full(config['days'] - 1, norm_init)

    # 包装回调
    MaxIter = 2000
    tqdm_wrap = TqdmCMA(MaxIter)
    global _POOL
    _POOL = Pool(processes=cpu_count(), initializer=_init_worker, initargs=(counter,))
    try:
        result = cma.fmin(
            lambda x: 0,
            auto_init,
            0.1,
            options={
                'bounds': [0, 1],
                'BoundaryHandler': cma.BoundTransform,
                'maxiter': MaxIter,
                'popsize': 40,
                'verbose': -9,
                'tolfun': 1e-7,
                'tolx': 1e-7,
                'tolstagnation': 300,
                'CMA_active': True,
                'CMA_mirrors': 0.3,
                'CMA_diagonal': 100,
                'CMA_elitist': True,
                'verb_filenameprefix': output_dir + '/'
            },
            restarts=3,
            callback=tqdm_wrap.update,
            parallel_objective=create_evaluator(config, config, counter)
        )
    finally:
        tqdm_wrap.close()
        _POOL.close()
        _POOL.join()

    # ---------------- 结果汇总 ----------------
    optimized_periods = np.append(result[0],
                                 config['days'] * config['avg_hours'] - sum(result[0]))
    optimized_biomass = -result[1]
    baseline_biomass = config['baseline_biomass']
    improvement = ((optimized_biomass - baseline_biomass) / baseline_biomass * 100
                  if baseline_biomass > 0 else 0)
    elapsed_time = time.time() - start_time
    minutes, seconds = divmod(elapsed_time, 60)
    real_solve = _SHARED_COUNT.value
    request_total = _REQUEST_COUNT.value
    # 与 GA 完全一致的 txt 格式
    report_content = f"""生长模型版本：{Simulator.__module__}
Start time: {start_datetime.strftime('%Y-%m-%d %H:%M:%S')}
c_rad_phot = {c_rad_phot}  # 光合有效辐射常数
Xd0 = {Xd0}  # 初始干重 kg/m²
Baseline_biomass = {baseline_biomass}
运行的参数配置：{config}
最终优化结果：提升{improvement:.2f}%
End time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Total time elapsed: {int(minutes)}分{seconds:.2f}秒
--------------------------------------------------
总个体评估次数 = {request_total}
CarbonSimulator.run_simulation() 被调用次数 = {real_solve}
--------------------------------------------------
"""
    with open(f"{output_dir}/report.txt", "w", encoding="utf-8") as f:
        f.write(report_content)

    np.savetxt(f"{output_dir}/final_best_individual.txt", optimized_periods)

    return {
        'optimized_periods': optimized_periods,
        'improvement_pct': np.float64(improvement),
        'output_dir': output_dir
    }

# ---------- 6. 主程序入口（Windows 安全） ----------
if __name__ == '__main__':
    freeze_support()
    mgr = Manager()
    _SHARED_COUNT  = mgr.Value('i', 0)   # 真实求解
    _REQUEST_COUNT = mgr.Value('i', 0)   # 请求评估（新增）
    Simulator.run_simulation = _counting_wrapper(Simulator.run_simulation, _SHARED_COUNT)

    start_datetime = datetime.now()
    print(f"Start time: {start_datetime.strftime('%Y-%m-%d %H:%M:%S')}")

    param_configs = {
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
    # 计算 baseline
    param_configs['baseline_biomass'] = panda_cal_biomass(
        np.full(param_configs['days'], param_configs['avg_hours']),
        param_configs['X_co2'], param_configs['T_light'], param_configs['T_dark'],
        param_configs['radiation'], param_configs['X_d_initial'])
    print(f"Baseline_biomass = {param_configs['baseline_biomass']}")

    result = cma_optimizer_wrapper(param_configs, 'outcmaes', _SHARED_COUNT)
    print(f"最终优化结果：提升{result['improvement_pct']:.2f}%")
    print(f"run_simulation 被调用 {_SHARED_COUNT.value} 次")