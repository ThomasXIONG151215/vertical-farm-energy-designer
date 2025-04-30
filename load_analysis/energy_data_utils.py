import os
from typing import Tuple, List, Dict
from datetime import datetime, timedelta

# Constants
BASE_DIR = "bw_data/hourly"
DEVICE_DIRS = ["LED1", "LED2", "LED3", "HVAC", "FFU", "FAU"]

# Date ranges for each season
SEASON_DATES = {
    'winter': ['11', '12', '13', '14', '15', '16', '17', '18', '19', '110', '111', '112', '113', '114', '115'],  # 1月1号-1月15号
    'spring': ['414', '415', '416', '417', '418', '419', '420', '421', '422', '423', '424', '425', '426', '427', '428'],  # 4月14号-4月28号
    'summer': ['71', '72', '73', '74', '75', '76', '77', '78', '79', '710', '711', '712', '713', '714', '715'],  # 7月1号-7月15号
    'fall': ['107', '108', '109', '1010', '1011', '1012', '1013', '1014', '1015', '1016', '1017', '1018', '1019', '1020', '1021']  # 10月7号-10月21号
}

# Special file patterns
DEVICE_PATTERNS = {
    'FFU': {
        'type': 'single',
        'file': '11.html'
    },
    'FAU': {
        'type': 'monthly',
        'files': {
            '1': '11.html',    # January file
            '4': '414.html',   # April file
            '7': '71.html',    # July file
            '10': '1010.html'   # October file
        }
    }
}

def validate_directory_structure() -> Tuple[bool, str]:
    """
    Validate that all required directories and critical files exist.
    
    Returns:
        Tuple[bool, str]: (is_valid, message)
    """
    if not os.path.exists(BASE_DIR):
        return False, f"Base directory {BASE_DIR} not found"
    
    # Check device directories
    for device in DEVICE_DIRS:
        device_path = os.path.join(BASE_DIR, device)
        if not os.path.exists(device_path):
            return False, f"Device directory {device_path} not found"
        
        # Check critical files for FFU and FAU
        if device == 'FFU':
            ffu_file = os.path.join(device_path, DEVICE_PATTERNS['FFU']['file'])
            if not os.path.exists(ffu_file):
                return False, f"Critical FFU file {ffu_file} not found"
        elif device == 'FAU':
            for month_file in DEVICE_PATTERNS['FAU']['files'].values():
                fau_file = os.path.join(device_path, month_file)
                if not os.path.exists(fau_file):
                    return False, f"Critical FAU file {fau_file} not found"
    
    return True, "Directory structure and critical files are valid"

def get_actual_file_path(device: str, date_str: str) -> str:
    """
    Get the actual file path considering device patterns.
    
    Args:
        device: Device directory name
        date_str: Date string (e.g., '71', '1021')
    
    Returns:
        str: Path to the actual HTML file to read
    """
    if device == 'FFU':
        return os.path.join(BASE_DIR, device, DEVICE_PATTERNS['FFU']['file'])
    elif device == 'FAU':
        month = date_str[:1] if len(date_str) <= 3 else date_str[:2]
        return os.path.join(BASE_DIR, device, DEVICE_PATTERNS['FAU']['files'][month])
    else:
        return os.path.join(BASE_DIR, device, f"{date_str}.html")

def get_html_path(device: str, date_str: str) -> str:
    """
    Get the full path to an HTML file.
    
    Args:
        device: Device directory name
        date_str: Date string (e.g., '71', '1021')
    
    Returns:
        str: Full path to HTML file
    """
    return get_actual_file_path(device, date_str)

def check_file_exists(device: str, date_str: str) -> bool:
    """
    Check if an HTML file exists for the given device and date.
    
    Args:
        device: Device directory name
        date_str: Date string (e.g., '71', '1021')
    
    Returns:
        bool: True if file exists, False otherwise
    """
    file_path = get_actual_file_path(device, date_str)
    return os.path.exists(file_path)

def get_all_dates() -> List[str]:
    """
    Get all dates to process across all seasons.
    
    Returns:
        List[str]: List of date strings
    """
    all_dates = []
    for dates in SEASON_DATES.values():
        all_dates.extend(dates)
    return sorted(all_dates)

def create_output_dirs():
    """Create output directories if they don't exist."""
    os.makedirs('output', exist_ok=True)

def get_required_files() -> Dict[str, List[str]]:
    """
    Get a list of all required files for each device.
    
    Returns:
        Dict[str, List[str]]: Dictionary mapping devices to their required files
    """
    files = {}
    
    # Regular devices
    for device in ['LED1', 'LED2', 'LED3', 'HVAC']:
        files[device] = [f"{date}.html" for date in get_all_dates()]
    
    # FFU - single file
    files['FFU'] = [DEVICE_PATTERNS['FFU']['file']]
    
    # FAU - monthly files
    files['FAU'] = list(DEVICE_PATTERNS['FAU']['files'].values())
    
    return files 