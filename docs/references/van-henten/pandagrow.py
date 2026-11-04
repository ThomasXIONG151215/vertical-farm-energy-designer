'''
仅调用，不执行
'''

import pandas as pd
import numpy as np
# from grow_two_state1994 import CarbonSimulator

EPSILON = 1e-12  # 防类型转换微小量
EPSILON = 0.0  # 防类型转换微小量

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