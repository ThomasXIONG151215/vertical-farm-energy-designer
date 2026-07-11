import os
import json
import numpy as np
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from my_pyswarm.pso import pso
# from pyswarm import pso
from datetime import datetime
import time
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

cs_name = f"CS{args.version}"

# 统一参数
Xd0 = 0.001
c_rad_phot = 1e-8

SwarmSize = 50  # 粒子群规模

def panda_cal_biomass(period, X_co2, T_light, T_dark, radiation, X_d_initial, Simulator):
    df = pandagrow.make_df(
        period, X_co2, T_light, T_dark, radiation, X_d_initial
    )
    results_df = Simulator(df, c_rad_phot).run_simulation()
    XdArray = results_df['Simulated Dry Weight'].values
    return XdArray[-1]

def generate_parameters():
    days = 28
    avg_hours = 16.0
    p = {
        'radiation': 70,  # 光强范围：25-100 W/m²       取60~80
        'period_max': 24,  # 最大光周期固定为24小时
        'period_min': 12,   # 最小光周期固定为12小时
        'avg_hours': avg_hours,  # 平均光周期在8到24小时之间随机生成
        'days': days,  # 实验天数：18-30天
        'T_light': 24,  # 光期温度：20-30°C
        'T_dark': 22,   # 暗期温度：15-25°C
        'X_co2': 0.002,  # CO2浓度：10^-3到10^-2.5 kg/m³
        'X_d_initial': Xd0,  # 初始干重：10^-3到10^-1.5 kg/m²
        'Simulator': version_map[args.version]
    }
    TestPeriod = np.full(days, avg_hours)
    p['baseline_biomass'] = panda_cal_biomass(TestPeriod, p['X_co2'], p['T_light'], p['T_dark'], p['radiation'], p['X_d_initial'], p['Simulator'])
    print(f"Baseline_biomass = {p['baseline_biomass']}")
    return p

def iteration_tracker(func):
    """目标函数迭代追踪装饰器"""
    def wrapper(x, *args, **kwargs):
        wrapper.eval_count += 1
        result = func(x, *args, **kwargs)
        
        # 记录当前粒子评估结果
        wrapper.current_swarm.append((x.copy(), result))
        
        # 每swarmsize次评估完成一代
        if wrapper.eval_count % wrapper.swarmsize == 0:
            current_iter = wrapper.eval_count // wrapper.swarmsize
            
            # 找本代最优
            best_in_gen = min(wrapper.current_swarm, key=lambda item: item[1])
            
            # 格式化参数为全精度
            params_str = ','.join(f"{xi:.20f}" for xi in best_in_gen[0])
            
            # 写入本代记录
            with open(wrapper.output_file, 'a', encoding="utf-8") as f:
                f.write(f"{current_iter},{best_in_gen[1]:.15f},{params_str}\n")
            
            # 清空当前代记录
            wrapper.current_swarm = []
            
        return result
    
    # 初始化装饰器属性
    wrapper.eval_count = 0
    wrapper.current_swarm = []
    wrapper.swarmsize = SwarmSize  # 与pso()调用中的swarmsize参数一致
    wrapper.output_file = ''
    return wrapper

@iteration_tracker
def objective_function(x, config):
    """带约束的目标函数"""
    days = config['days']
    avg_hours = config['avg_hours']
    period_min = config['period_min']
    period_max = config['period_max']
    simulator = config['Simulator']
    
    total = days * avg_hours
    x_last = total - x.sum()
    # 约束检查
    if any(x < period_min) or any(x > period_max):
        return 1e6
    if x_last < period_min or x_last > period_max:
        return 1e6
    
    periods = np.append(x, x_last)
    return -panda_cal_biomass(
        periods, 
        config['X_co2'], 
        config['T_light'], 
        config['T_dark'], 
        config['radiation'], 
        config['X_d_initial'], 
        simulator
    )

def pso_optimizer_wrapper(config):
    try:
        start_time = time.time()
        start_datetime = datetime.fromtimestamp(start_time)
        
        # 创建输出目录
        output_dir = f"outpso/{cs_name}_{config['avg_hours']}_{config['period_min']}{config['period_max']}_{start_datetime.strftime('%Y%m%d_%H%M%S')}"
        os.makedirs(output_dir, exist_ok=True)
        
        # 保存参数配置
        config_copy = config.copy()
        del config_copy['Simulator']

        # 保存到 JSON
        with open(f"{output_dir}/params.json", "w", encoding="utf-8") as f:
            json.dump(config_copy, f, indent=4)

        # 参数边界
        n_vars = config['days'] - 1
        lb = [config['period_min']] * n_vars
        ub = [config['period_max']] * n_vars

        # 优化回调函数
        best_f = float('inf')
        def log_iteration(swarm, iteration):
            nonlocal best_f
            current_best = np.min(swarm.current_cost)
            if current_best < best_f:
                best_f = current_best
                with open(f"{output_dir}/best_individuals.csv", "a", encoding="utf-8") as f:
                    f.write(f"{iteration},{best_f},{','.join(map(str, swarm.best_pos))}\n")

        # 初始化迭代追踪 
        objective_function.eval_count = 0
        objective_function.swarmsize = SwarmSize
        objective_function.current_swarm = []
        objective_function.output_file = f"{output_dir}/best_individuals.csv"
        
        # 清空或创建新记录文件
        with open(objective_function.output_file, 'w', encoding="utf-8") as f:
            f.write("generation,fitness,parameters\n")

        # 执行PSO优化
        optimal_x, optimal_f = pso(
            lambda x: objective_function(x, config),
            lb, ub,
            swarmsize=SwarmSize,
            maxiter=2000,
            debug=False,
            phip=1.8,
            phig=2.2,
            omega=0.5,
            minstep=1e-10,
            minfunc=1e-10,
            center=np.full(n_vars, config['avg_hours'])
        )

        # 保存最终最优解
        if optimal_x is not None and len(optimal_x) > 0:
            final_periods = np.append(optimal_x, 
                                    config['days']*config['avg_hours'] - sum(optimal_x))
            np.savetxt(f"{output_dir}/final_best_individual.txt", final_periods)

        # 处理优化结果
        optimized_periods = np.append(optimal_x, config['days']*config['avg_hours'] - sum(optimal_x))
        optimized_biomass = -optimal_f
        baseline_biomass = config['baseline_biomass']
        improvement = ((optimized_biomass - baseline_biomass) / baseline_biomass * 100 
                      if baseline_biomass > 0 else 0)

        # 生成报告
        elapsed_time = time.time() - start_time
        minutes, seconds = divmod(elapsed_time, 60)
        
        report_content = f"""生长模型版本：{config['Simulator'].__module__}
    
Start time: {start_datetime.strftime('%Y-%m-%d %H:%M:%S')}

Xd0 = {Xd0}  # 初始干重 kg/m²

c_rad_phot = {c_rad_phot}  # 光合有效辐射常数

Total function evaluations: {objective_function.eval_count}

Baseline_biomass = {baseline_biomass}

最终优化结果：提升{improvement:.2f}%

End time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Total time elapsed: {int(minutes)}分{seconds:.2f}秒"""

        with open(f"{output_dir}/report.txt", "w", encoding="utf-8") as f:
            f.write(report_content)

        return {
            'optimized_periods': optimized_periods,
            'improvement_pct': improvement,
            'output_dir': output_dir
        }
    except Exception as e:
        raise

if __name__ == "__main__":
    config = generate_parameters()
    pso_optimizer_wrapper(config)