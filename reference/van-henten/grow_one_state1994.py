'''
c_lar_d需要审查
没有numba
'''

import pandas as pd
import numpy as np

class CarbonSimulator:
    def __init__(self, env_df, C_Epsilon = 1e-8):
        self.env_df = env_df
        self.time_points = env_df['Time'].values
        self.X_c_points = env_df['CO2 conc.'].values
        self.X_t_points = env_df['Temp.'].values
        self.V1_points = env_df['Light intensity'].values
        self.initial_dry_weight = env_df['Dry weight'].iloc[0]
        
        # 初始化所有常数参数
        self.c_alpha = 0.68
        self.c_beta = 0.8
        self.c_bnd = 0.004
        self.c_car_1 = -1.32e-5
        self.c_car_2 = 5.94e-4
        self.c_car_3 = -2.64e-3
        self.c_epsilon = C_Epsilon   # 继承
        self.c_Gamma = 7.32e-5
        self.c_k = 0.9
        self.c_lar_d = 62.5     # 需审查
        self.c_par = 1.0
        self.c_Q10_Gamma = 2.0
        self.c_Q10_resp = 2.0
        self.c_rad_rf = 1.0
        self.c_resp_s = 3.47e-7
        self.c_resp_r = 1.16e-7
        self.c_stm = 0.007
        self.c_tau = 0.07

    def _compute_derivative(self, X_d, X_c, X_t, V1):
        """计算dX_d/dt的核心函数"""
        # 计算sigma_car
        sigma_car = (
            self.c_car_1 * (X_t**2) +
            self.c_car_2 * X_t +
            self.c_car_3
        )
        
        # 计算sigma_co2
        sigma_co2 = 1 / (
            1/self.c_bnd +
            1/self.c_stm +
            1/sigma_car
        )
        
        # 计算Gamma
        Gamma = self.c_Gamma * (self.c_Q10_Gamma ** ((X_t - 20.0)/10.0))
        
        # 计算epsilon
        epsilon = self.c_epsilon * (X_c - Gamma) / (X_c + 2*Gamma)
        
        # 计算phi_phot_max
        numerator = epsilon * self.c_par * self.c_rad_rf * V1 * sigma_co2 * (X_c - Gamma)
        denominator = epsilon * self.c_par * self.c_rad_rf * V1 + sigma_co2 * (X_c - Gamma)
        phi_phot_max = numerator / denominator if denominator != 0 else 0.0
        
        # 计算phi_phot
        exponent = -self.c_k * self.c_lar_d * (1 - self.c_tau) * X_d
        phi_phot = phi_phot_max * (1 - np.exp(exponent))
        
        # 计算phi_resp
        Q10_factor = self.c_Q10_resp ** ((X_t - 25.0)/10.0)
        phi_resp = (
            (self.c_resp_s*(1 - self.c_tau) + self.c_resp_r*self.c_tau) *
            X_d *
            Q10_factor
        )
        
        # 计算最终导数
        return self.c_beta * (self.c_alpha * phi_phot - phi_resp)

    def run_simulation(self):
        """执行模拟计算"""
        n = len(self.time_points)
        simulated_dry_weight = np.zeros(n)
        simulated_dry_weight[0] = self.initial_dry_weight

        for i in range(n-1):
            # 获取当前状态
            current_X_d = simulated_dry_weight[i]
            current_X_c = self.X_c_points[i]
            current_X_t = self.X_t_points[i]
            current_V1 = self.V1_points[i]
            
            # 计算时间步长（转换为秒）
            delta_t = (self.time_points[i+1] - self.time_points[i]) * 86400  # 天转秒
            
            # 计算导数
            dX_d_dt = self._compute_derivative(
                current_X_d, current_X_c, current_X_t, current_V1
            )
            
            # 欧拉法更新
            simulated_dry_weight[i+1] = current_X_d + dX_d_dt * delta_t
            self.env_df['Simulated Dry Weight'] = simulated_dry_weight


        return self.env_df

    def save_results(self, results, output_path):
        """保存结果到Excel"""
        self.env_df.to_excel(output_path, index=False)

if __name__ == "__main__":
    # 读取输入数据
    env_data = pd.read_excel("OriginGrow.xlsx")
    
    # 创建模拟器并运行
    simulator = CarbonSimulator(env_data)
    simulation_results = simulator.run_simulation()
    
    # 保存结果
    simulator.save_results(simulation_results, "Simulated_Results.xlsx")