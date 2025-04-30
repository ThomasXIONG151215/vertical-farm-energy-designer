"""
Weather data extraction module using Open-Meteo API
"""

import openmeteo_requests
import requests_cache
import pandas as pd
import numpy as np
from retry_requests import retry
import logging
from typing import Dict, Optional, Tuple
from pathlib import Path
import pytz
from datetime import datetime, timedelta

class WeatherDataError(Exception):
    """Custom exception for weather data validation errors"""
    pass

class WeatherExtractor:
    def __init__(self):
        # Setup the Open-Meteo API client with cache and retry on error
        cache_session = requests_cache.CachedSession('.cache', expire_after=-1)
        retry_session = retry(cache_session, retries=5, backoff_factor=0.2)
        self.openmeteo = openmeteo_requests.Client(session=retry_session)
        
        # Setup logging
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)

    def _analyze_peak_radiation_hour(self, df: pd.DataFrame) -> int:
        """
        Analyze the dataset to find the average peak radiation hour.
        Returns the hour offset needed (relative to noon) to correct the data.
        """
        # Add date and hour columns
        df['date'] = df['time'].dt.date
        df['hour'] = df['time'].dt.hour
        
        # Group by date and find hour with max radiation for each day
        daily_peaks = df.groupby('date').apply(
            lambda x: x.loc[x['shortwave_radiation'].idxmax(), 'hour']
        ).values
        
        # Calculate the most common peak hour
        peak_hour = int(np.median(daily_peaks))
        self.logger.info(f"Detected most common peak radiation hour: {peak_hour}:00")
        
        # Calculate needed offset (assuming peak should be at 12:00)
        hour_offset = 12 - peak_hour
        self.logger.info(f"Calculated hour offset needed: {hour_offset}")
        
        return hour_offset

    def _adjust_time(self, df: pd.DataFrame, hour_offset: int) -> pd.DataFrame:
        """
        Adjust all timestamps in the DataFrame by the given hour offset
        """
        df['time'] = df['time'] + pd.Timedelta(hours=hour_offset)
        return df

    def _check_radiation_data(self, df: pd.DataFrame) -> Tuple[bool, str]:
        """
        Check radiation data for anomalies:
        - Detect non-zero radiation values during nighttime
        - Check for negative values
        
        Returns:
            Tuple[bool, str]: (is_valid, error_message)
        """
        radiation_columns = [
            'shortwave_radiation', 'direct_radiation', 'diffuse_radiation',
            'direct_normal_irradiance', 'global_tilted_irradiance', 'terrestrial_radiation'
        ]
        
        # Convert time to hour and calculate solar position
        df['hour'] = df['time'].dt.hour
        
        # Consider nighttime between 19:00 and 5:00
        night_mask = (df['hour'] >= 19) | (df['hour'] <= 5)
        
        error_messages = []
        
        for col in radiation_columns:
            if col in df.columns:
                # Check for nighttime radiation
                night_data = df[night_mask][col]
                if (night_data > 1).any():  # Using 1 W/m² threshold to account for small floating point values
                    problematic_times = df[night_mask & (df[col] > 1)]['time'].dt.strftime('%Y-%m-%d %H:%M:%S').tolist()
                    error_messages.append(
                        f"Detected significant {col} values during nighttime at times: {', '.join(problematic_times[:5])}"
                        f"{' and more...' if len(problematic_times) > 5 else ''}"
                    )
                
                # Check for negative values
                if (df[col] < 0).any():
                    negative_times = df[df[col] < 0]['time'].dt.strftime('%Y-%m-%d %H:%M:%S').tolist()
                    error_messages.append(
                        f"Detected negative {col} values at times: {', '.join(negative_times[:5])}"
                        f"{' and more...' if len(negative_times) > 5 else ''}"
                    )
        
        if error_messages:
            return False, "\n".join(error_messages)
        return True, ""

    def get_weather_data(self, 
                        latitude: float, 
                        longitude: float, 
                        timezone: str,
                        city_name: str,
                        output_dir: Path,
                        start_date: str = "2023-12-31",
                        end_date: str = "2025-01-02") -> Optional[pd.DataFrame]:
        """
        Extract weather data for given coordinates
        
        Args:
            latitude: Location latitude
            longitude: Location longitude
            timezone: Location timezone (e.g., 'Asia/Shanghai')
            city_name: Name of the city
            output_dir: Directory to save the CSV file
            start_date: Start date (default: "2023-12-31" to ensure we have complete data)
            end_date: End date (default: "2025-01-02" to ensure complete data)
            
        Returns:
            DataFrame with hourly weather data for the entire year 2024
            
        Raises:
            WeatherDataError: If radiation data validation fails
        """
        try:
            # Request more data to account for potential timezone adjustments
            api_start_date = (pd.to_datetime(start_date) - pd.Timedelta(days=2)).strftime('%Y-%m-%d')
            api_end_date = (pd.to_datetime(end_date) + pd.Timedelta(days=2)).strftime('%Y-%m-%d')
            
            params = {
                "latitude": latitude,
                "longitude": longitude,
                "start_date": api_start_date,
                "end_date": api_end_date,
                "hourly": [
                    "temperature_2m",
                    "relative_humidity_2m", 
                    "dew_point_2m",
                    "surface_pressure", 
                    "cloud_cover",
                    "snow_depth",
                    "wind_speed_10m", 
                    "wind_direction_10m",
                    "wind_gusts_10m",
                    "soil_moisture_100_to_255cm",
                    "shortwave_radiation",
                    "direct_radiation",
                    "diffuse_radiation",
                    "direct_normal_irradiance",
                    "global_tilted_irradiance",
                    "terrestrial_radiation",
                    "rain"
                ],
                "timezone": "UTC"
            }
            
            self.logger.info(f"Fetching weather data for {city_name}: {latitude}, {longitude}")
            responses = self.openmeteo.weather_api(
                "https://archive-api.open-meteo.com/v1/archive",
                params=params
            )
            
            response = responses[0]
            hourly = response.Hourly()
            
            # Create DataFrame with all variables
            hourly_data = {
                "time": pd.date_range(
                    start=pd.to_datetime(hourly.Time(), unit="s"),
                    end=pd.to_datetime(hourly.TimeEnd(), unit="s"),
                    freq=pd.Timedelta(seconds=hourly.Interval()),
                    inclusive="left"
                )
            }
            
            # Add all variables to the dataframe
            for idx, variable in enumerate(params["hourly"]):
                hourly_data[variable] = hourly.Variables(idx).ValuesAsNumpy()
            
            # Create initial DataFrame
            df = pd.DataFrame(hourly_data)
            
            # Analyze peak radiation hours and adjust time accordingly
            hour_offset = self._analyze_peak_radiation_hour(df)
            df = self._adjust_time(df, hour_offset)
            
            self.logger.info(f"Retrieved data range: {df['time'].min()} to {df['time'].max()}")
            
            # Filter to exact range we want (2024-01-01 00:00:00 to 2024-12-31 23:00:00)
            df_filtered = df[
                (df['time'] >= "2024-01-01 00:00:00") & 
                (df['time'] <= "2024-12-31 23:00:00")
            ].copy()
            
            # Verify we have exactly 8760 hours (non-leap year) or 8784 hours (leap year)
            expected_hours = 8784 if pd.Timestamp('2024').is_leap_year else 8760
            if len(df_filtered) != expected_hours:
                self.logger.warning(f"Unexpected number of hours: {len(df_filtered)}. Expected: {expected_hours}")
            
            self.logger.info(f"Filtered data range: {df_filtered['time'].min()} to {df_filtered['time'].max()}")
            self.logger.info(f"Number of hours in filtered data: {len(df_filtered)}")
            
            # Clean and save the DataFrame to a CSV file
            output_path = output_dir / f"{city_name}_2024.csv"
            
            # Save with only the necessary columns
            columns = [col for col in params["hourly"] if col in df_filtered.columns]
            columns.insert(0, 'time')  # Ensure time is the first column
            
            # Drop temporary columns
            for col in ['date', 'hour']:
                if col in df_filtered.columns:
                    df_filtered = df_filtered.drop(col, axis=1)
            
            # Ensure all columns exist and are in the correct order
            df_filtered = df_filtered[columns]
            
            # Save without excess rows, using clean formatting
            df_filtered.to_csv(output_path, index=False, float_format='%.6f')
            
            self.logger.info(f"Successfully saved weather data to {output_path}")
            
            return df_filtered
            
        except Exception as e:
            self.logger.error(f"Error fetching weather data: {str(e)}")
            return None 