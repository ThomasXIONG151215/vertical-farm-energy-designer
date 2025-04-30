import os
import time
import psutil
import pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import numpy as np
from typing import Optional, Dict, Tuple

from energy_data_utils import (
    validate_directory_structure,
    get_all_dates,
    get_html_path,
    check_file_exists,
    DEVICE_DIRS,
    create_output_dirs,
    DEVICE_PATTERNS
)

def extract_energy_data(html_file_path: str, date_str: str) -> Optional[pd.DataFrame]:
    """
    Extract energy consumption data from a single HTML file.
    
    Args:
        html_file_path: Path to HTML file
        date_str: Date string in format 'MM-DD'
    
    Returns:
        Optional[pd.DataFrame]: DataFrame with hourly consumption data or None if file doesn't exist
    """
    # Validate date format
    try:
        month, day = map(int, date_str.split('-'))
        if month < 1 or month > 12 or day < 1 or day > 31:
            raise ValueError(f"Invalid date format: {date_str}")
    except (ValueError, AttributeError):
        raise ValueError(f"Invalid date format: {date_str}")

    # For missing files, return DataFrame with zeros
    if not os.path.exists(html_file_path):
        start_date = datetime.strptime(f"2024-{month:02d}-{day:02d}", "%Y-%m-%d")
        date_range = pd.date_range(start_date, start_date + timedelta(days=1), freq='H', inclusive='left')
        return pd.DataFrame(0, index=date_range, columns=['consumption'])

    try:
        print(f"\nProcessing: {os.path.basename(html_file_path)}")

        # Read and parse HTML file
        with open(html_file_path, 'r', encoding='utf-8') as file:
            soup = BeautifulSoup(file, 'html.parser')

        # Initialize list to store data
        data = []
        
        # Find all hourly consumption records
        records = soup.find_all('div', class_='drawerTitle', style=lambda value: value and 'margin-bottom: 10px' in value)
        
        for record in records:
            try:
                # Extract time
                time_span = record.find('span', style=lambda s: s and 'color: rgb(116, 127, 147)' in s)
                if not time_span:
                    continue
                time = time_span.text.strip()
                
                # Extract consumption
                consumption_div = record.find_all('div', class_='li')[1]
                consumption_spans = consumption_div.find_all('span')
                
                # Get consumption value (用电量)
                for span in consumption_spans:
                    if '用电量(度)：' in span.text:
                        consumption = round(float(span.text.split('：')[1].replace('度', '')), 3)
                        
                        # Parse date and time with 2024 as year
                        timestamp = datetime.strptime(f"2024-{month:02d}-{day:02d} {time}", '%Y-%m-%d %H:%M:%S')
                        
                        # Round timestamp to nearest hour
                        timestamp = timestamp.replace(minute=0, second=0)
                        data.append({
                            'timestamp': timestamp,
                            'consumption': consumption
                        })
                        break
                
            except (ValueError, AttributeError, IndexError) as e:
                continue

        # Create DataFrame with all hours
        start_date = datetime.strptime(f"2024-{month:02d}-{day:02d}", "%Y-%m-%d")
        date_range = pd.date_range(start_date, start_date + timedelta(days=1), freq='H', inclusive='left')
        
        # Create DataFrame and fill missing hours with zeros
        if data:
            df = pd.DataFrame(data)
            df = df.groupby('timestamp')['consumption'].sum().round(3)
            full_df = pd.DataFrame(index=date_range, columns=['consumption'])
            full_df['consumption'] = df.reindex(date_range, fill_value=0)
            return full_df
        else:
            return pd.DataFrame(0, index=date_range, columns=['consumption'])

    except Exception as e:
        print(f"Error processing {os.path.basename(html_file_path)}: {e}")
        return None

def process_device_data(device: str, date_str: str, device_cache: Dict[str, pd.DataFrame]) -> Optional[pd.DataFrame]:
    """
    Process data for a specific device and date, handling special patterns.
    
    Args:
        device: Device name
        date_str: Date string
        device_cache: Cache of already processed data
    
    Returns:
        Optional[pd.DataFrame]: DataFrame with hourly data or None if error
    """
    # Validate device name
    if device not in DEVICE_DIRS:
        raise ValueError(f"Invalid device name: {device}")
    
    # Convert filename date to MM-DD format
    if len(date_str) == 4:  # e.g., "1021"
        mm_dd = f"{date_str[:2]}-{date_str[2:]}"
    else:  # e.g., "71"
        mm_dd = f"0{date_str[0]}-{date_str[1:]}"
    
    html_path = get_html_path(device, date_str)
    print(f"Processing path: {html_path}")
    
    # Handle FAU (all days in a month have identical data)
    if device == 'FAU':
        month = date_str[:1] if len(date_str) <= 3 else date_str[:2]
        print(f"FAU month: {month}")
        cache_key = f"FAU_{month}"
        print(f"FAU cache key: {cache_key}")
        
        # Try to find any existing file for this month
        if cache_key not in device_cache:
            print(f"Cache miss for {cache_key}, searching for month files...")
            month_files = [f for f in os.listdir(os.path.dirname(html_path)) 
                         if f.startswith(str(month)) and f.endswith('.html')]
            print(f"Found month files: {month_files}")
            
            if month_files:
                # Use the first available file for this month
                alt_path = os.path.join(os.path.dirname(html_path), month_files[0])
                print(f"Using alternative path: {alt_path}")
                # Use the first day of the month as reference
                first_day_mm_dd = f"{int(month):02d}-01"
                print(f"Using reference date: {first_day_mm_dd}")
                device_cache[cache_key] = extract_energy_data(alt_path, first_day_mm_dd)
            else:
                print(f"No files found for month {month}, creating zero data")
                device_cache[cache_key] = extract_energy_data(html_path, mm_dd)
        else:
            print(f"Using cached data for {cache_key}")
        
        df = device_cache[cache_key]
        if df is not None:
            print("Creating new index for target date")
            # Create new index for target date while preserving hour values
            target_date = datetime.strptime(f"2024-{mm_dd}", "%Y-%m-%d")
            print(f"Target date: {target_date}")
            new_index = [dt.replace(month=target_date.month, day=target_date.day) for dt in df.index]
            return pd.DataFrame({'consumption': df['consumption'].values}, index=new_index)
        else:
            print(f"No data available for {cache_key}")
    
    # Handle other devices (missing files or hours are treated as zeros)
    else:
        df = extract_energy_data(html_path, mm_dd)
    
    return df

def process_all_data() -> pd.DataFrame:
    """
    Process all devices and dates to create a unified DataFrame.
    
    Returns:
        pd.DataFrame: Combined hourly consumption data for all devices
    """
    # Initialize memory monitoring
    start_mem = psutil.Process().memory_info().rss
    
    # Add timestamp for performance monitoring
    start_time = time.time()
    
    # Validate directory structure
    is_valid, message = validate_directory_structure()
    if not is_valid:
        raise ValueError(message)
    
    # Create output directories
    create_output_dirs()
    
    # Get all dates to process
    all_dates = get_all_dates()
    print(f"\nProcessing dates: {all_dates}")
    
    # Initialize empty DataFrames dictionary and cache
    device_dfs = {}
    device_cache = {}
    
    # Reorder devices to process FAU first
    devices = ['FAU'] + [d for d in DEVICE_DIRS if d != 'FAU']
    
    # Process each device
    for device in devices:
        print(f"\n{'='*50}")
        print(f"Processing device: {device}")
        print(f"{'='*50}")
        
        try:
            # Initialize device data
            device_data = pd.DataFrame()
            
            # Process each date
            for date_str in all_dates:
                try:
                    print(f"\nProcessing {device} for date: {date_str}")
                    df = process_device_data(device, date_str, device_cache)
                    
                    if df is not None:
                        # Concatenate and handle any overlapping timestamps
                        device_data = pd.concat([device_data, df])
                        if not device_data.index.is_unique:
                            device_data = device_data.groupby(device_data.index)['consumption'].sum().round(3).to_frame()
                    else:
                        print(f"Warning: No data returned for {device} on {date_str}")
                
                except Exception as e:
                    print(f"Error processing {device} for date {date_str}:")
                    print(f"Error type: {type(e).__name__}")
                    print(f"Error message: {str(e)}")
                    import traceback
                    print("Traceback:")
                    print(traceback.format_exc())
                    continue
            
            print(f"\nDevice {device} summary:")
            print(f"Total records: {len(device_data)}")
            device_dfs[device] = device_data
            
        except Exception as e:
            print(f"Error processing device {device}:")
            print(f"Error type: {type(e).__name__}")
            print(f"Error message: {str(e)}")
            import traceback
            print("Traceback:")
            print(traceback.format_exc())
            continue
    
    # Get the full date range across all devices
    all_timestamps = pd.DatetimeIndex([])
    for df in device_dfs.values():
        all_timestamps = all_timestamps.union(df.index)
    all_timestamps = all_timestamps.sort_values()
    
    # Create the final DataFrame with all timestamps
    result_df = pd.DataFrame(index=all_timestamps)
    
    # Add each device's data
    for device, df in device_dfs.items():
        result_df[device] = df['consumption'].reindex(all_timestamps, fill_value=0).round(3)
    
    print("\nFinal DataFrame summary:")
    print(f"Total timestamps: {len(result_df)}")
    
    return result_df

def main():
    """Main function to run the data extraction process."""
    try:
        print("Starting energy data extraction...")
        
        # Process all data
        result_df = process_all_data()
        
        # Save to CSV
        output_file = 'BW_hourly_energy_consumption.csv'
        result_df.to_csv(output_file)
        
        print(f"\nData extraction completed successfully!")
        print(f"Output saved to: {output_file}")
        print(f"Total records: {len(result_df)}")
        
    except Exception as e:
        print(f"Error during data extraction: {e}")

if __name__ == "__main__":
    main()
