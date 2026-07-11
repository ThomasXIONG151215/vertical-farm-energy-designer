"""
Module for converting weather data to EPW format
"""

import pandas as pd
import os
from typing import Optional
import logging

class EPWConverter:
    def __init__(self):
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)

    def modify_epw_with_data(self,
                            epw_template: str,
                            weather_data: pd.DataFrame,
                            output_epw: str) -> bool:
        """
        Modify EPW file using weather data from DataFrame
        """
        try:
            # Read the EPW file
            header_lines = []
            data_lines = []
            
            with open(epw_template, 'r') as f:
                # Store header (first 8 lines)
                for i in range(8):
                    header_lines.append(f.readline())
                
                # Store data lines
                data_lines = f.readlines()
            
            # Modify the data lines as needed
            modified_data = []
            for idx, line in enumerate(data_lines):
                values = line.strip().split(',')
                
                if idx < len(weather_data):
                    row = weather_data.iloc[idx]
                    
                    # Update values with weather data
                    values[6] = f"{row['temperature_2m']:.1f}"  # Dry Bulb Temperature
                    values[7] = f"{row['dew_point_2m']:.1f}"  # Dew Point Temperature
                    values[8] = f"{row['relative_humidity_2m']:.0f}"  # Relative Humidity
                    values[9] = f"{float(row['surface_pressure']) * 100:.0f}"  # Atmospheric Pressure
                    values[13] = f"{row['shortwave_radiation']:.0f}"  # Global Horizontal Radiation
                    values[14] = f"{row['direct_radiation']:.0f}"  # Direct Normal Radiation
                    values[15] = f"{row['diffuse_radiation']:.0f}"  # Diffuse Horizontal Radiation
                    values[20] = f"{row['wind_direction_10m']:.0f}"  # Wind Direction
                    values[21] = f"{float(row['wind_speed_10m']) / 3.6:.1f}"  # Wind Speed
                    values[22] = f"{row['cloud_cover']:.0f}"  # Total Sky Cover
                    values[33] = f"{row['rain']:.1f}"  # Liquid Precipitation Depth
                    values[34] = "1"  # Liquid Precipitation Quantity
                
                modified_data.append(','.join(values) + '\n')
            
            # Write the modified EPW file
            os.makedirs(os.path.dirname(output_epw), exist_ok=True)
            with open(output_epw, 'w') as f:
                f.writelines(header_lines)
                f.writelines(modified_data)
                
            return True
            
        except Exception as e:
            self.logger.error(f"Error converting to EPW: {str(e)}")
            return False 