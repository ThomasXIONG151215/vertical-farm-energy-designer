import os
import json
import numpy as np
from datetime import datetime
import time
import random
import argparse
from grow_two_state1994 import CarbonSimulator as CS64
from grow_one_state1994 import CarbonSimulator as CS32
from grow_one_state2003 import CarbonSimulator as CS0
import pandagrow

parser = argparse.ArgumentParser(description='Lettuce Growth Model Simulation')
parser.add_argument('-v', '--version', type=int, choices=[0, 32, 64], 
                    default=64, help='模拟器版本 (0,32,64)')
args = parser.parse_args()
version_map = {
    0: CS0,
    32: CS32,
    64: CS64
}
Simulator = version_map[args.version]
cs_name = f"CS{args.version}"

# 统一参数
Xd0 = 0.001
c_rad_phot = 1e-8

def panda_cal_biomass(period, X_co2, T_light, T_dark, radiation, X_d_initial):
    df = pandagrow.make_df(
        period, X_co2, T_light, T_dark, radiation, X_d_initial
    )
    simulator = Simulator(df, c_rad_phot)
    results_df = simulator.run_simulation()
    XdArray = results_df['Simulated Dry Weight'].values
    return XdArray[-1]

def objective_function(x_normalized, days, avg_hours, period_min, period_max, 
                      X_co2, T_light, T_dark, radiation, X_d_initial):
    """带约束的目标函数（归一化版本）"""
    # 反归一化到实际参数空间
    x = x_normalized * (period_max - period_min) + period_min
    total = days * avg_hours
    x_last = total - x.sum()
    
    # 约束检查
    if any(x < period_min) or any(x > period_max):
        return 1e6
    if x_last < period_min or x_last > period_max:
        return 1e6
    
    periods = np.append(x, x_last)
    
    return -panda_cal_biomass(periods, X_co2, T_light, T_dark, radiation, X_d_initial)

# ====================== 优化模块 ======================
def genetic_optimizer_wrapper(args):
    """遗传算法优化器（单线程版本）"""
    try:
        start_datetime = datetime.now()
        start_time = time.time()
        config = args

        # 创建输出目录
        output_dir = f"outga/{cs_name}_{config['avg_hours']}_{config['period_min']}{config['period_max']}_{start_datetime.strftime('%Y%m%d_%H%M%S')}"
        os.makedirs(output_dir, exist_ok=True)
        
        # 保存参数配置
        with open(f"{output_dir}/params.json", "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4)

        # 遗传算法参数
        POP_SIZE = 64   # 2的幂次有利于遗传操作
        GENERATIONS = 2000
        CX_RATE = 0.8
        MUT_RATE = 0.1
        ELITE_COUNT = 2

        # 初始化种群
        def init_population():
            pop = []
            norm_init = (config['avg_hours'] - config['period_min']) / (config['period_max'] - config['period_min'])
            
            for _ in range(POP_SIZE):
                # 生成以norm_init为中心的随机个体
                individual = np.random.normal(norm_init, 0.1, config['days']-1)  # 标准差设为0.1
                individual = np.clip(individual, 0, 1)  # 确保在[0,1]范围内
                pop.append(individual)
            return pop

        # 适应度评估（单线程）
        def evaluate(individual):
            return objective_function(
                individual, 
                config['days'], config['avg_hours'], 
                config['period_min'], config['period_max'],
                config['X_co2'], config['T_light'], 
                config['T_dark'], config['radiation'], 
                config['X_d_initial']
            )

        # 锦标赛选择
        def tournament_selection(pop, fitness, k=3):
            selected = []
            for _ in range(len(pop)):
                candidates = random.sample(list(zip(pop, fitness)), k)
                winner = min(candidates, key=lambda x: x[1])
                selected.append(winner[0])
            return selected

        # 均匀交叉
        def crossover(parent1, parent2):
            child = np.zeros_like(parent1)
            for i in range(len(parent1)):
                if random.random() < 0.5:
                    child[i] = parent1[i]
                else:
                    child[i] = parent2[i]
            return child

        # 高斯变异
        def mutate(individual):
            mutated = individual.copy()
            for i in range(len(mutated)):
                if random.random() < MUT_RATE:
                    mutated[i] = np.clip(mutated[i] + random.gauss(0, 0.1), 0, 1)
            return mutated

        # 主优化循环
        population = init_population()
        best_fitness = float('inf')
        best_individual = None

        # 打开结果记录文件
        with open(f"{output_dir}/best_individuals.csv", "w", encoding="utf-8") as f:
            f.write("generation,fitness,params\n")
            f.flush()

            for gen in range(GENERATIONS):

                # 单线程评估适应度
                fitness = [evaluate(ind) for ind in population]
                
                # 选择
                selected = tournament_selection(population, fitness)
                
                # 交叉
                offspring = []
                for i in range(0, len(selected), 2):
                    if i+1 < len(selected):
                        child1 = crossover(selected[i], selected[i+1])
                        child2 = crossover(selected[i+1], selected[i])
                        offspring.extend([child1, child2])
                
                # 变异
                mutated = [mutate(ind) for ind in offspring]
                
                # 精英保留
                combined = population + mutated
                combined_fitness = [evaluate(ind) for ind in combined]
                elite_indices = np.argsort(combined_fitness)[:ELITE_COUNT]
                population = [combined[i] for i in elite_indices]
                population += random.sample(combined, POP_SIZE - ELITE_COUNT)
                
                # 记录最佳个体
                current_best = min(fitness)
                if current_best < best_fitness:
                    best_fitness = current_best
                    best_individual = population[np.argmin(fitness)]
                    
                # 保存当前代结果
                x_actual = best_individual * (config['period_max'] - config['period_min']) + config['period_min']
                f.write(f"{gen},{best_fitness},{','.join(map(str, x_actual))}\n")
                f.flush()

        # 计算最终结果
        optimized_periods = np.append(best_individual, 
                                    config['days']*config['avg_hours'] - sum(best_individual))
        optimized_biomass = -best_fitness
        baseline_biomass = config['baseline_biomass']
        improvement = ((optimized_biomass - baseline_biomass) / baseline_biomass * 100 
                     if baseline_biomass > 0 else 0)

        # 生成报告
        elapsed_time = time.time() - start_time
        minutes, seconds = divmod(elapsed_time, 60)
        report_content = f"""Start time: {start_datetime.strftime('%Y-%m-%d %H:%M:%S')}

Baseline_biomass = {baseline_biomass}

运行的参数配置：{config}

最终优化结果：提升{improvement:.2f}%

End time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Total time elapsed: {int(minutes)}分{seconds:.2f}秒
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
        
    except Exception as e:
        raise

# ====================== 参数生成与保存 ======================
def generate_parameters():
    days = 28
    avg_hours = 16.0
    p = {
        'radiation': 70,  # 光强
        'period_max': 24,  # 最大光周期
        'period_min': 12,   # 最小光周期
        'avg_hours': avg_hours,
        'days': days,
        'T_light': 24,  # 光期温度
        'T_dark': 22,   # 暗期温度
        'X_co2': 0.002,  # CO2浓度
        'X_d_initial': Xd0  # 初始干重
    }
    TestPeriod = np.full(days, avg_hours)
    p['baseline_biomass'] = panda_cal_biomass(
        TestPeriod, p['X_co2'], p['T_light'], 
        p['T_dark'], p['radiation'], p['X_d_initial']
    )
    print(f'Baseline_biomass = {p["baseline_biomass"]}')
    return p

# ====================== 修改后的主程序 ====================== 
if __name__ == "__main__":
    # 记录开始时间戳
    start_time = time.time()
    start_datetime = datetime.now()
    print(f"Start time: {start_datetime.strftime('%Y-%m-%d %H:%M:%S')}")

    # 主程序逻辑
    param_configs = generate_parameters()
    print(f"运行的参数配置：{param_configs}")

    # 执行单个优化任务
    result = genetic_optimizer_wrapper(param_configs)
    print(f"最终优化结果：提升{result['improvement_pct']:.2f}%")

    # 计算总耗时并生成报告
    end_time = time.time()
    end_datetime = datetime.now()
    elapsed_time = end_time - start_time
    minutes, seconds = divmod(elapsed_time, 60)
    
    # 生成报告内容
    report_content = f"""生长模型版本: {Simulator.__module__}
    
Start time: {start_datetime.strftime('%Y-%m-%d %H:%M:%S')}

c_rad_phot = {c_rad_phot}  # 光合有效辐射常数

Xd0 = {Xd0}  # 初始干重 kg/m²

Baseline_biomass = {param_configs['baseline_biomass']}

运行的参数配置: {param_configs}

最终优化结果: 提升{result['improvement_pct']:.2f}%

End time: {end_datetime.strftime('%Y-%m-%d %H:%M:%S')}

Total time elapsed: {int(minutes)}分{seconds:.2f}秒"""

    # 保存报告文件
    with open(f"{result['output_dir']}/report.txt", "w", encoding="utf-8") as f:
        f.write(report_content)

    print(f"End time: {end_datetime.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Total time elapsed: {int(minutes)}分{seconds:.2f}秒")