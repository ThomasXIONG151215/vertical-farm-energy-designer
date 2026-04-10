import pandas as pd
import numpy as np
import os

# Define season date ranges
SEASON_DATES = {
    'winter': ('2024-01-01', '2024-01-15'),  # January 1-15
    'spring': ('2024-04-14', '2024-04-28'),  # April 14-28
    'summer': ('2024-07-01', '2024-07-15'),  # July 1-15
    'fall': ('2024-10-07', '2024-10-21')     # October 7-21
}

# Define season mapping for month-only checks
SEASON_MONTHS = {
    'winter': [1, 2, 12],  # January, February, December
    'spring': [3, 4, 5],   # March, April, May
    'summer': [6, 7, 8],   # June, July, August
    'fall': [9, 10, 11]    # September, October, November
}

def get_season(month):
    """Get season name from month number"""
    for season, months in SEASON_MONTHS.items():
        if month in months:
            return season
    return None

def process_fau_schedules():
    """Process FAU data to create typical seasonal operation schedules."""
    
    # Read the hourly energy consumption data
    # Try new location first, then fall back to old location for compatibility
    data_paths = [
        'data/raw/BW_data.csv',
        'BW_data.csv'  # Legacy fallback
    ]
    
    df = None
    for path in data_paths:
        if os.path.exists(path):
            df = pd.read_csv(path)
            print(f"Loaded data from: {path}")
            break
    
    if df is None:
        raise FileNotFoundError("Could not find BW_data.csv in any expected location")
    
    # Create datetime column from Date and Hour columns
    df['time'] = pd.to_datetime(df['Date'] + ' ' + df['Hour'].astype(str) + ':00:00')
    
    # Extract month, day, and hour
    df['month'] = df['time'].dt.month
    df['day'] = df['time'].dt.day
    df['hour'] = df['time'].dt.hour
    
    # Create binary schedule (0 if FAU is off, 1 if on)
    # In the new format, the FAU column is named 'FAU'
    df['fau_status'] = (df['FAU'] > 0).astype(int)
    
    # Calculate typical schedule for each season
    seasonal_schedules = {}
    for season, (start_date, end_date) in SEASON_DATES.items():
        # Convert dates to datetime for comparison
        start = pd.to_datetime(start_date)
        end = pd.to_datetime(end_date)
        
        # Filter data for this season's date range
        season_data = df[
            (df['time'].dt.month == start.month) & 
            (df['time'].dt.day >= start.day) & 
            (df['time'].dt.day <= end.day)
        ]
        
        if season_data.empty:
            print(f"Warning: No data found for {season} ({start_date} to {end_date})")
            # Use a default schedule (all zeros) if no data
            schedule = [0] * 24
        else:
            schedule = []
            for hour in range(24):
                hour_data = season_data[season_data['hour'] == hour]
                status = 1 if hour_data['fau_status'].mean() > 0.5 else 0
                schedule.append(status)
        
        seasonal_schedules[season] = schedule
    
    # Create schedule files for each season
    os.makedirs('schedules', exist_ok=True)
    
    for season, schedule in seasonal_schedules.items():
        # Create full year schedule with the pattern repeating
        full_schedule = []
        days_in_year = 365
        
        for day in range(days_in_year):
            full_schedule.extend(schedule)
        
        # Save to file
        filename = os.path.join('schedules', f'fau_schedule_{season}.txt')
        with open(filename, 'w') as f:
            for value in full_schedule:
                f.write(f"{value:.1f}\n")
        
        print(f"\nCreated schedule for {season} ({SEASON_DATES[season][0]} to {SEASON_DATES[season][1]})")
        print(f"Hourly pattern: {schedule}")
        print(f"Hours active: {sum(schedule)} of 24")

if __name__ == "__main__":
    process_fau_schedules() 