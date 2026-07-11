"""
Test suite for OpenCROPS utils module
"""
import pytest
import numpy as np
import pandas as pd
import sys
from pathlib import Path
import tempfile
import os

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils import (
    load_schedule,
    prepare_weather_data,
    extract_schedule_info,
    calculate_daily_metrics
)


class TestLoadSchedule:
    """Test cases for load_schedule function"""

    def test_load_schedule_basic(self):
        """Test loading a valid schedule file"""
        # Create a temporary CSV file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("Power (kWh)\n")
            f.write("10.0\n")
            f.write("20.0\n")
            f.write("30.0\n")
            temp_path = f.name
        
        try:
            result = load_schedule(Path(temp_path))
            assert isinstance(result, np.ndarray)
            assert len(result) == 3
            assert np.allclose(result, [10.0, 20.0, 30.0])
        finally:
            os.unlink(temp_path)

    def test_load_schedule_empty_file_raises(self):
        """Test that empty file raises ValueError"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("Power (kWh)\n")
            temp_path = f.name
        
        try:
            with pytest.raises(ValueError, match="Empty power profile"):
                load_schedule(Path(temp_path))
        finally:
            os.unlink(temp_path)

    def test_load_schedule_nan_raises(self):
        """Test that NaN values raise ValueError"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("Power (kWh)\n")
            f.write("10.0\n")
            f.write("nan\n")
            f.write("30.0\n")
            temp_path = f.name
        
        try:
            with pytest.raises(ValueError, match="contains NaN"):
                load_schedule(Path(temp_path))
        finally:
            os.unlink(temp_path)

    def test_load_schedule_negative_raises(self):
        """Test that negative values raise ValueError"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("Power (kWh)\n")
            f.write("10.0\n")
            f.write("-5.0\n")
            f.write("30.0\n")
            temp_path = f.name
        
        try:
            with pytest.raises(ValueError, match="contains negative"):
                load_schedule(Path(temp_path))
        finally:
            os.unlink(temp_path)


class TestPrepareWeatherData:
    """Test cases for prepare_weather_data function"""

    def test_prepare_weather_data_synthetic(self):
        """Test generating synthetic weather data"""
        result = prepare_weather_data()
        
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 8760  # Full year of hourly data
        
        required_columns = ['temperature_2m', 'direct_radiation', 'diffuse_radiation', 'shortwave_radiation']
        for col in required_columns:
            assert col in result.columns

    def test_prepare_weather_data_temperature_range(self):
        """Test that synthetic temperature is in reasonable range"""
        result = prepare_weather_data()
        
        # Temperature should be roughly between -20 and 40 C for most locations
        assert result['temperature_2m'].min() > -30
        assert result['temperature_2m'].max() < 50

    def test_prepare_weather_data_radiation_non_negative(self):
        """Test that radiation values are non-negative"""
        result = prepare_weather_data()
        
        assert (result['direct_radiation'] >= 0).all()
        assert (result['diffuse_radiation'] >= 0).all()
        assert (result['shortwave_radiation'] >= 0).all()


class TestExtractScheduleInfo:
    """Test cases for extract_schedule_info function"""

    def test_extract_schedule_info_valid(self):
        """Test extracting info from valid filename"""
        result = extract_schedule_info("total_energy_schedule_08_16.csv")
        
        assert result['start_hour'] == 8
        assert result['end_hour'] == 16

    def test_extract_schedule_info_valid_edge_cases(self):
        """Test edge cases for schedule info extraction"""
        result = extract_schedule_info("total_energy_schedule_00_24.csv")
        
        assert result['start_hour'] == 0
        assert result['end_hour'] == 24

    def test_extract_schedule_info_invalid_raises(self):
        """Test that invalid filename raises ValueError"""
        with pytest.raises(ValueError, match="Invalid schedule filename"):
            extract_schedule_info("invalid_filename.csv")


class TestCalculateDailyMetrics:
    """Test cases for calculate_daily_metrics function"""

    def test_calculate_daily_metrics_basic(self):
        """Test calculating daily metrics"""
        # Create 48 hours of data (2 days)
        df = pd.DataFrame({
            'Power (kWh)': [10.0] * 24 + [20.0] * 24
        })
        
        result = calculate_daily_metrics(df)
        
        assert 'daily_mean' in result
        assert 'daily_max' in result
        assert 'daily_min' in result


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
