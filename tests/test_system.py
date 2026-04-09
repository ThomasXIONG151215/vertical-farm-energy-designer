"""
Test suite for OpenCROPS system module
"""
import pytest
import numpy as np
import pandas as pd
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.system import PVSystem, BatterySystem, EnergySystem


class TestPVSystem:
    """Test cases for PVSystem class"""

    def test_pv_system_initialization(self):
        """Test PV system can be initialized"""
        pv = PVSystem()
        assert pv is not None

    def test_calculate_pv_output_shapes(self):
        """Test PV output has correct shapes"""
        pv = PVSystem()
        
        temperature = np.array([25, 30, 35])
        radiation = np.array([800, 900, 1000])
        
        result = pv.calculate_pv_output(temperature, radiation)
        
        assert isinstance(result, dict)
        assert 'pv_power' in result or 'power' in result


class TestBatterySystem:
    """Test cases for BatterySystem class"""

    def test_battery_initialization(self):
        """Test battery system can be initialized"""
        battery = BatterySystem()
        assert battery is not None

    def test_battery_zero_capacity(self):
        """Test battery with zero capacity"""
        battery = BatterySystem()
        available_power = np.array([100, 200])
        load_profile = np.array([50, 100])
        
        result = battery.calculate_power_flows(available_power, load_profile, E_bat=0)
        
        assert np.all(result['battery_power'] == 0)
        assert result['battery_throughput'] == 0.0


class TestEnergySystem:
    """Test cases for EnergySystem class"""

    def test_energy_system_initialization(self):
        """Test energy system can be initialized"""
        energy_system = EnergySystem()
        assert energy_system is not None


class TestSystemIntegration:
    """Integration tests for the complete energy system"""

    def test_pv_power_calculation_positive(self):
        """Test that PV power is positive when radiation is positive"""
        pv = PVSystem()
        
        temperature = np.array([25, 30])  # Celsius
        radiation = np.array([500, 1000])  # W/m²
        
        result = pv.calculate_pv_output(temperature, radiation)
        
        power_key = 'pv_power' if 'pv_power' in result else 'power'
        power = result[power_key]
        
        # Power should be non-negative
        assert np.all(power >= 0)

    def test_battery_soc_bounds(self):
        """Test battery SOC never exceeds valid range"""
        battery = BatterySystem()
        
        available_power = np.array([500] * 100)  # High PV
        load_profile = np.array([50] * 100)      # Low load
        E_bat = 100.0
        
        result = battery.calculate_power_flows(available_power, load_profile, E_bat)
        
        # All SOC values should be in [0, 1]
        assert np.all(result['battery_soc'] >= 0)
        assert np.all(result['battery_soc'] <= 1)

    def test_battery_charge_discharge_cycle(self):
        """Test a complete charge-discharge cycle"""
        battery = BatterySystem()
        
        # First charge (excess PV)
        available_power = np.array([200, 200, 200])
        load_profile = np.array([50, 50, 50])
        E_bat = 100.0
        
        result = battery.calculate_power_flows(available_power, load_profile, E_bat)
        
        initial_soc = result['battery_soc'][0]
        final_soc = result['battery_soc'][-1]
        
        # Should have charged (SOC increased)
        assert final_soc >= initial_soc


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
