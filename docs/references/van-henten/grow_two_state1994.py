'''
终极版本，独立生成，等同于grow05040800two.py
'''

import pandas as pd
import numpy as np

class CarbonSimulator:
    def __init__(self, env_data, C_Epsilon=1e-8):
        self.env_data = env_data
        self.params = {
            # 模型参数表（带单位注释）
            'c_α': 0.68,          # 无量纲
            'c_β': 0.8,           # 无量纲
            'c_gr_max': 5e-6,     # s^-1
            'c_Q10_gr': 1.6,      # 无量纲
            'c_mu': 0.07,         # 无量纲
            'c_resp_rt': 1.16e-7, # s^-1
            'c_resp_sht': 3.47e-7,# s^-1
            'c_k': 0.9,           # 无量纲
            'c_lar': 75,       # m²/kg
            'c_ε': C_Epsilon,         # kg/J
            'c_Γ': 40,            # PPM
            'c_Q10_Γ': 2,          # 无量纲
            'c_stm': 0.004,       # m/s
            'c_bnd': 0.007,       # m/s
            'c_car1': -1.32e-5,   # m/(s·°C²)
            'c_car2': 5.94e-4,    # m/(s·°C)
            'c_car3': -2.64e-3,   # m/s
            'c_Q10_resp': 2        # 无量纲
        }
        
        # 初始化状态变量
        self.X_nsdw = []
        self.X_sdw = []
        
        # 从初始数据获取初始值
        initial_dw = env_data['Dry weight'].iloc[0]  # kg/m²
        self.X_nsdw.append(0.16 * initial_dw)
        self.X_sdw.append(0.84 * initial_dw)
    
    def _convert_co2(self, co2_kgm3, temp):
        """将CO2浓度从kg/m³转换为PPM"""
        # 摩尔质量转换 (kg/m³ -> mol/m³)
        molar_mass = 0.044  # CO2摩尔质量 kg/mol
        mol_per_m3 = co2_kgm3 / molar_mass
        
        # 理想气体定律转换
        return mol_per_m3 * 22.4e-3 * (273.15 + temp) / 273.15 * 1e6
    
    def _calculate_phot_max(self, u_par, u_co2, temp):
        """计算φ_phot_max"""
        # 计算Γ
        Γ = self.params['c_Γ'] * (self.params['c_Q10_Γ'] ** ((temp - 20)/10))
        
        # 计算ε
        ε = self.params['c_ε'] * (u_co2 - Γ) / (u_co2 + 2*Γ)
        
        # 计算σ_car
        σ_car = (self.params['c_car1'] * temp**2 + 
                self.params['c_car2'] * temp + 
                self.params['c_car3'])
        
        # 计算总导度
        σ = 1 / (1/self.params['c_stm'] + 1/self.params['c_bnd'] + 1/σ_car)
        
        # 计算φ_phot_max
        numerator = ε * u_par * σ * (u_co2 - Γ)
        denominator = ε * u_par + σ * (u_co2 - Γ)
        return numerator / denominator if denominator != 0 else 0
    
    def run_simulation(self):
        """执行模拟计算"""
        df = self.env_data.copy()
        
        for i in range(len(df)-1):
            # 获取当前环境参数
            current = df.iloc[i]
            # dt_days = df.iloc[i+1]['Time'] - current['Time']  # 时间步长（天）
            # dt = dt_days * 86400  # 转换为秒
            dt = 600
            
            # CO2单位转换
            u_co2 = self._convert_co2(current['CO2 conc.'], current['Temp.'])
            
            # 计算各中间变量
            X_total = self.X_nsdw[i] + self.X_sdw[i]
            
            # 计算生长速率
            r_gr = (self.params['c_gr_max'] * 
                   (self.X_nsdw[i] / X_total) * 
                   (self.params['c_Q10_gr'] ** ((current['Temp.'] - 20)/10)))
            
            # 计算呼吸作用
            φ_resp = ((self.params['c_resp_sht'] * (1 - self.params['c_mu']) * self.X_sdw[i] +
                      self.params['c_resp_rt'] * self.params['c_mu'] * self.X_sdw[i]) * 
                     self.params['c_Q10_resp'] ** ((current['Temp.'] - 25)/10))
            
            # 计算光合作用
            φ_phot_max = self._calculate_phot_max(current['Light intensity'], u_co2, current['Temp.'])
            φ_phot = (1 - np.exp(-self.params['c_k'] * self.params['c_lar'] * 
                     (1 - self.params['c_mu']) * self.X_sdw[i])) * φ_phot_max
            
            # 计算微分方程
            dXnsdw = (self.params['c_α'] * φ_phot - 
                      r_gr * self.X_sdw[i] - 
                      φ_resp - 
                      (1 - self.params['c_β'])/self.params['c_β'] * r_gr * self.X_sdw[i])
            
            dXsdw = r_gr * self.X_sdw[i]
            
            # 更新状态变量
            self.X_nsdw.append(self.X_nsdw[i] + dXnsdw * dt)
            self.X_sdw.append(self.X_sdw[i] + dXsdw * dt)
        
        # 将结果添加到DataFrame
        df['X_nsdw'] = self.X_nsdw
        df['X_sdw'] = self.X_sdw
        df['Simulated Dry Weight'] = df['X_nsdw'] + df['X_sdw']
        return df
    
    def save_results(self, filename):
        """保存结果到Excel文件"""
        results = self.env_data.copy()
        results['X_nsdw'] = self.X_nsdw
        results['X_sdw'] = self.X_sdw
        results['Simulated Dry Weight'] = results['X_nsdw'] + results['X_sdw']
        results.to_excel(filename, index=False)

if __name__ == "__main__":
    env = pd.read_excel("OriginGrow.xlsx")
    simulator = CarbonSimulator(env)
    results = simulator.run_simulation()
    simulator.save_results("Simulated_Results.xlsx")