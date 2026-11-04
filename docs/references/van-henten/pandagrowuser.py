'''
参数化X环境条件：
    def make_df(TestPeriod, X_co2=0.002, T_light=24.0, T_dark=22.0, radiation=70.0, X_d_initial=0.001)
算法比较
自定义C_Epsilon
'''

import pandas as pd
import numpy as np
from grow_two_state1994 import CarbonSimulator as CS64
from grow_one_state1994 import CarbonSimulator as CS32
from grow_one_state2003 import CarbonSimulator as CS0

BaselinePeriod = np.full(28, 20.0)

th_14d4 = np.array([10.00406635, 10.00427848, 10.0049988, 10.00677315, 10.01021057, 10.01569205,
                    10.02405301, 10.03963639, 10.07969943, 10.19110175, 10.46694795, 11.03857169,
                    12.0101625, 13.34814062, 14.8268089, 16.1305741, 17.04675322, 17.56227803,
                    17.79706962, 17.88548881, 17.91551872, 17.92831163, 17.93694525, 17.94281903,
                    17.94566288, 17.94626085, 17.94583545, 17.94534077])

th_18d4 = np.array([14.02317232, 14.02739387, 14.03334793, 14.0386495, 14.04273096, 14.04637188,
                    14.05121468, 14.06060116, 14.08615015, 14.16629243, 14.39435176, 14.9221184,
                    15.88624733, 17.26812498, 18.82047208, 20.18674149, 21.12772635, 21.63236266,
                    21.83972806, 21.90242528, 21.91584552, 21.91923322, 21.92222644, 21.92617477,
                    21.93188246, 21.93849645, 21.94370742, 21.94621045])

th_20d4 = np.array([16.01681558, 16.02370776, 16.03393351, 16.04181681, 16.04332258, 16.04123852,
                    16.04848814, 16.08902333, 16.19806036, 16.42128865, 16.81765366, 17.46427066,
                    18.42915031, 19.6847237, 21.04014626, 22.21592493, 23.02173146, 23.45135967,
                    23.62146044, 23.66200941, 23.66130159, 23.6632692, 23.67980366, 23.70464656,
                    23.72616016, 23.73595615, 23.73404423, 23.72869268])

th_14d6 = np.array([8.02265086, 8.0278732, 8.03536389, 8.04140479, 8.04395875, 8.04349024, 
                    8.04269296, 8.04826225, 8.08281438, 8.21154379, 8.57536231, 9.38823734, 
                    10.83430629, 12.87920869, 15.17129752, 17.20427496, 18.63154429, 19.42688513, 
                    19.78055455, 19.90696456, 19.94389398, 19.95377525, 19.95716052, 19.95762408, 
                    19.95480396, 19.94943468, 19.94395065, 19.94066617])

th_18d6 = np.array([12.0006064, 12.0006713, 12.00078326, 12.00095141, 12.0013417, 12.00306413, 
                    12.01055752, 12.0374719, 12.11963511, 12.33601505, 12.82724855, 13.77534055, 
                    15.30143755, 17.31535104, 19.4680394, 21.31889603, 22.59571839, 23.30424985, 
                    23.6247437, 23.74877727, 23.7958804, 23.81538871, 23.81874663, 23.8069353, 
                    23.78314133, 23.75364007, 23.72615939, 23.70920803])

EPSILON = 1e-12  # 防类型转换微小量
# EPSILON = 0.0  # 防类型转换微小量

def make_df(TestPeriod, X_co2=0.002, T_light=24.0, T_dark=22.0, radiation=70.0, X_d_initial=0.001):
    # 生成时间序列（精确浮点计算）
    total_days = len(TestPeriod)
    time_points = [i/144.0 for i in range(total_days * 144)]

    data = {
        "Time": [],
        "CO2 conc.": [],
        "Temp.": [],
        "Light intensity": [],
        "Dry weight": []  # 新增列
    }

    for idx, t in enumerate(time_points):  # 使用enumerate获取索引
        current_day = int(t)
        
        # 获取当日光照参数
        try:
            daylight_hours = TestPeriod[current_day]
        except IndexError:
            break
        
        # 计算精确光照结束时间
        total_minutes = daylight_hours * 60
        rounded_minutes = round(total_minutes / 10) * 10
        end_time = current_day + rounded_minutes/(24*60)
        
        # 原始光照判断
        light_value = radiation if t <= end_time else 0.0
        temp_value = T_light if light_value > 0 else T_dark
        
        # Dry weight逻辑（仅第一行有值）
        dry_weight = X_d_initial if idx == 0 else np.nan
        
        # 填充数据
        data["Time"].append(t)
        data["CO2 conc."].append(X_co2)
        data["Temp."].append(temp_value + EPSILON)
        data["Light intensity"].append(light_value + EPSILON)
        data["Dry weight"].append(dry_weight)  # 添加干重数据

    # 创建DataFrame并指定类型
    df = pd.DataFrame(data).astype({
        "Time": 'float64',
        "CO2 conc.": 'float64',
        "Temp.": 'float64',
        "Light intensity": 'float64',
        "Dry weight": 'float64'  # 确保列为浮点类型
    })

    return df

def result(fakedf, precision, C_Epsilon):
    if precision == 64:
        simulator = CS64(fakedf, C_Epsilon)
    elif precision == 32:
        simulator = CS32(fakedf, C_Epsilon)
    elif precision == 0:
        simulator = CS0(fakedf, C_Epsilon)
    results_df = simulator.run_simulation()
    return results_df

def MoveOn(fakedf):
    results_df = result(fakedf)
    
    # 返回干重结果
    XdArray =  results_df['My simulated dry weight'].values
    return XdArray[-1]

def save(dataframe, outputname = "lettuce_simulation.csv"):
    dataframe.to_csv(outputname, index=False)
    print(f"文件已生成到{outputname}")

def compare_cmd(Test, Baseline):
    df0011 = make_df(Test)
    Xd0011 = MoveOn(df0011)
    df16 = make_df(Baseline)
    Xd16 = MoveOn(df16)

    print(f'16H Biomass = {Xd16}\nTest Biomass = {Xd0011}\nRaise = {(Xd0011 - Xd16) / Xd16 * 100.}%')

def compare_file(test, Baseline, testname, basename):
    test_df = make_df(test)
    results_test = result(test_df, 0)
    save(results_test, testname)
    base_df = make_df(Baseline)
    results_base = result(base_df, 2)
    save(results_base, basename)

if __name__ == "__main__":
    # test = np.array([12.00061, 12.00067, 12.00078, 12.00095, 12.00134, 12.00306, 12.01056, 12.03747, 12.11964, 12.33602, 12.82725, 13.77534, 15.30144, 17.31535, 19.46804, 21.3189, 22.59572, 23.30425, 23.62474, 23.74878, 23.79588, 23.81539, 23.81875, 23.80694, 23.78314, 23.75364, 23.72616, 23.70921])

    MODEL = 64  # 0, 32, 64
    base_df = make_df(BaselinePeriod)
    results_base = result(base_df, MODEL, C_Epsilon=1e-8)
    test_df = make_df(th_20d4)
    results_test = result(test_df, MODEL, C_Epsilon=1e-8)

    save(results_base, 'user_base.csv')
    save(results_test, 'user_test.csv')

    # 打印最后一行最后一列的值乘以500
    # print(results_base.iloc[-1, -1] * 500)

    print((results_test.iloc[-1, -1] - results_base.iloc[-1, -1]) / results_base.iloc[-1, -1] * 100.0)