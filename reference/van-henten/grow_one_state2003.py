import pandas as pd
import numpy as np

class CarbonSimulator:
    def __init__(self, env_df, C_Epsilon=1e-8):
        self.env_df = env_df.copy()
        self.params = {
            'c_alpha_beta': 0.544,     # 无量纲
            'c_resp_d': 2.65e-7,       # s^-1 (保持不变)
            'c_pl_d': 53,              # m²/kg
            'c_rad_phot': C_Epsilon,        # kg/J
            'c_co2_1': 5.11e-6,        # m/(s·°C²)
            'c_co2_2': 2.3e-4,         # m/(s·°C)
            'c_co2_3': 6.29e-4,        # m/s
            'c_Gamma': 5.2e-5          # kg/m³
        }  # 所有参数保持原始国际单位

    def _calculate_phi_phot_c(self, X_d, X_c, X_T, V_rad):
        """计算光合作用通量（kg/(m²·s)）"""
        co2_term = (-self.params['c_co2_1'] * X_T**2 
                   + self.params['c_co2_2'] * X_T 
                   - self.params['c_co2_3'])
        
        numerator = self.params['c_rad_phot'] * V_rad * co2_term * (X_c - self.params['c_Gamma'])
        denominator = self.params['c_rad_phot'] * V_rad + co2_term * (X_c - self.params['c_Gamma'])
        
        # 处理分母接近零的情况
        if abs(denominator) < 1e-10:
            return 0.0
        
        light_response = (1 - np.exp(-self.params['c_pl_d'] * X_d))
        return light_response * numerator / denominator

    def run_simulation(self):
        time_days = self.env_df['Time'].values
        X_c = self.env_df['CO2 conc.'].values
        X_T = self.env_df['Temp.'].values
        V_rad = self.env_df['Light intensity'].values
        
        # 初始化干重数组（kg/m²）
        X_d = np.zeros_like(time_days)
        X_d[0] = self.env_df['Dry weight'].iloc[0]  # 初始值
        
        # 数值积分（前向欧拉法）
        for i in range(len(time_days)-1):
            dt_days = time_days[i+1] - time_days[i]
            dt_seconds = dt_days * 86400  # 天转秒
            
            # 计算当前时刻的微分项
            phi = self._calculate_phi_phot_c(X_d[i], X_c[i], X_T[i], V_rad[i])
            respiration = self.params['c_resp_d'] * X_d[i] * (2 ** (0.1 * X_T[i] - 2.5))
            
            # 更新干重
            X_d[i+1] = X_d[i] + dt_seconds * (self.params['c_alpha_beta'] * phi - respiration)
        
        self.env_df['Simulated Dry Weight'] = X_d
        return self.env_df

    def save_results(self, filename):
        self.env_df.to_excel(filename, index=False)

if __name__ == "__main__":
    env_data = pd.read_excel("OriginGrow.xlsx")
    simulator = CarbonSimulator(env_data)
    results = simulator.run_simulation()
    simulator.save_results("Simulated_Results.xlsx")