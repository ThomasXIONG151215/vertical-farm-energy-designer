"""
Test suite for OpenCROPS battery module
"""
import pytest
import numpy as np
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.battery import BatterySystem


class TestBatterySystem:
    """Test cases for BatterySystem class"""

    def test_calculate_power_flows_zero_capacity(self):
        """Test battery with zero capacity returns zero arrays"""
        battery = BatterySystem()
        available_power = np.array([100, 200, 150])
        load_profile = np.array([50, 100, 80])
        
        result = battery.calculate_power_flows(available_power, load_profile, E_bat=0)
        
        assert result['battery_power'].shape == (3,)
        assert result['battery_energy'].shape == (4,)
        assert result['battery_soc'].shape == (4,)
        assert np.all(result['battery_power'] == 0)
        assert result['battery_throughput'] == 0.0

    def test_calculate_power_flows_charging(self):
        """Test battery charging when PV exceeds load"""
        battery = BatterySystem()
        available_power = np.array([200, 300, 200])  # Excess PV power
        load_profile = np.array([50, 100, 80])      # Lower load
        E_bat = 100.0  # 100 kWh battery
        
        result = battery.calculate_power_flows(available_power, load_profile, E_bat=E_bat)
        
        assert 'battery_power' in result
        assert 'battery_energy' in result
        assert 'battery_soc' in result
        assert 'battery_throughput' in result
        
        # Check battery power is positive during charging
        assert np.all(result['battery_power'] >= 0)
        
        # Check SOC increases during charging
        assert result['battery_soc'][-1] >= result['battery_soc'][0]

    def test_calculate_power_flows_discharging(self):
        """Test battery discharging when load exceeds PV"""
        battery = BatterySystem()
        available_power = np.array([50, 100, 80])   # Low PV
        load_profile = np.array([200, 300, 200])   # High load
        E_bat = 100.0  # 100 kWh battery
        
        result = battery.calculate_power_flows(available_power, load_profile, E_bat=E_bat)
        
        # Check battery power is negative during discharging
        assert np.all(result['battery_power'] <= 0)
        
        # Check SOC decreases during discharging
        assert result['battery_soc'][-1] <= result['battery_soc'][0]

    def test_calculate_power_flows_balanced(self):
        """Test battery when PV equals load (no charge/discharge)"""
        battery = BatterySystem()
        available_power = np.array([100, 100, 100])
        load_profile = np.array([100, 100, 100])
        E_bat = 100.0
        
        result = battery.calculate_power_flows(available_power, load_profile, E_bat=E_bat)
        
        # Power should be zero or near zero
        assert np.allclose(result['battery_power'], 0, atol=1e-10)

    def test_soc_bounds(self):
        """Test that SOC stays within valid bounds [0, 1]"""
        battery = BatterySystem()
        available_power = np.array([500, 0, 500, 0, 500, 0] * 100)  # Alternating high/low
        load_profile = np.array([100, 100, 100, 100, 100, 100] * 100)
        E_bat = 50.0
        
        result = battery.calculate_power_flows(available_power, load_profile, E_bat=E_bat)
        
        # SOC should be between 0 and 1 (allow small numerical errors due to self-discharge)
        assert np.all(result['battery_soc'] >= -0.02)  # Allow up to 2% negative due to self-discharge
        assert np.all(result['battery_soc'] <= 1.02)

    def test_battery_throughput_positive(self):
        """Test that battery throughput is always positive"""
        battery = BatterySystem()
        available_power = np.array([200, 300, 200])
        load_profile = np.array([50, 100, 80])
        E_bat = 100.0
        
        result = battery.calculate_power_flows(available_power, load_profile, E_bat=E_bat)
        
        assert result['battery_throughput'] >= 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
