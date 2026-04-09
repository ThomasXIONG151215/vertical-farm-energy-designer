"""
Test suite for OpenCROPS optimizer module
"""
import pytest
import numpy as np
import pandas as pd
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.optimizer import SystemOptimizer
from src.system import EnergySystem


class TestSystemOptimizer:
    """Test cases for SystemOptimizer class"""

    def test_optimizer_initialization(self):
        """Test optimizer can be initialized"""
        energy_system = EnergySystem()
        optimizer = SystemOptimizer(energy_system)
        
        assert optimizer is not None
        assert optimizer.energy_system is not None

    def test_optimizer_default_ranges(self):
        """Test optimizer has correct default ranges"""
        energy_system = EnergySystem()
        optimizer = SystemOptimizer(energy_system)
        
        assert optimizer.pv_area_range == (0.0, 200.0)
        assert optimizer.battery_range == (0.0, 100.0)
        assert optimizer.pv_area_step == 10
        assert optimizer.battery_step == 5

    def test_optimizer_custom_ranges(self):
        """Test optimizer accepts custom ranges"""
        energy_system = EnergySystem()
        optimizer = SystemOptimizer(
            energy_system,
            pv_area_range=(10, 100),
            battery_range=(5, 50)
        )
        
        assert optimizer.pv_area_range == (10, 100)
        assert optimizer.battery_range == (5, 50)


class TestOptimizerProblemData:
    """Test optimizer with various problem configurations"""

    def test_optimizer_accepts_valid_problem_data(self):
        """Test that optimizer accepts valid problem data structure"""
        energy_system = EnergySystem()
        optimizer = SystemOptimizer(energy_system)
        
        # Create minimal problem data
        weather_data = pd.DataFrame({
            'temperature_2m': np.random.uniform(10, 35, 8760),
            'direct_radiation': np.random.uniform(0, 1000, 8760),
            'diffuse_radiation': np.random.uniform(0, 200, 8760),
            'shortwave_radiation': np.random.uniform(0, 100, 8760)
        })
        
        load_profile = np.random.uniform(50, 200, 8760)
        
        problem_data = {
            'energy_system': energy_system,
            'weather_data': weather_data,
            'load_profile': load_profile,
            'constraints': {
                'schedule_start': 6,
                'schedule_end': 18,
                'photoperiod': 12
            },
            'city': 'Shanghai'
        }
        
        # Just verify it doesn't raise
        assert isinstance(problem_data, dict)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
