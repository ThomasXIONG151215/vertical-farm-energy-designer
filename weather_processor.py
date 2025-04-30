"""
Main script for processing weather data for multiple cities
"""

import os
import json
import argparse
from pathlib import Path
from weather.weather_extractor import WeatherExtractor
from weather.epw_converter import EPWConverter
import logging
from typing import Optional, Dict, List
import shutil


def validate_weather_data(data):
    if not isinstance(data, dict):
        raise ValueError("Weather data must be a dictionary.")
    if 'temperature' not in data or 'humidity' not in data:
        raise ValueError("Weather data must contain 'temperature' and 'humidity' keys.")

class WeatherProcessor:
    def __init__(self, base_dir: str, coordinates_file: str = None):
        self.base_dir = Path(base_dir)
        self.weather_dir = self.base_dir / "weather"
        self.test_case_dir = self.base_dir / "test_case"
        self.template_epw = self.weather_dir / "template.epw"
        
        # Create weather directory if it doesn't exist
        self.weather_dir.mkdir(exist_ok=True)
        
        # Load city coordinates from JSON file
        if coordinates_file:
            self.coordinates_file = Path(coordinates_file)
        else:
            self.coordinates_file = self.weather_dir / "city_coordinates.json"
            
        if not self.coordinates_file.exists():
            raise FileNotFoundError(f"City coordinates file not found: {self.coordinates_file}")
            
        with open(self.coordinates_file, 'r') as f:
            self.city_coordinates = json.load(f)
        
        # Initialize components
        self.extractor = WeatherExtractor()
        self.converter = EPWConverter()
        
        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)

    def process_city(self, city_key: str) -> bool:
        """
        Process weather data for a single city
        """
        try:
            city_info = self.city_coordinates.get(city_key.lower())
            if not city_info:
                self.logger.error(f"City {city_key} not found in coordinates database")
                return False
            
            # Create city-specific directories
            city_weather_dir = self.weather_dir
            city_test_case_weather_dir = self.test_case_dir / city_key / "weather"
            city_test_case_weather_dir.mkdir(parents=True, exist_ok=True)
            
            # Generate filenames
            csv_filename = f"{city_key}_2024.csv"
            epw_filename = f"{city_key}_2024.epw"
            
            # Extract weather data
            weather_data = self.extractor.get_weather_data(
                latitude=city_info["latitude"],
                longitude=city_info["longitude"],
                timezone=city_info["timezone"],
                city_name=city_key,
                output_dir=city_weather_dir  # Pass the output directory to the extractor
            )
            
            if weather_data is None:
                return False
            
            # Convert to EPW
            weather_epw = city_weather_dir / epw_filename
            success = self.converter.modify_epw_with_data(
                self.template_epw,
                weather_data,
                weather_epw
            )
            
            if not success:
                return False
            
            # Copy files to test_case directory
            shutil.copy2(
                city_weather_dir / csv_filename,
                city_test_case_weather_dir / csv_filename
            )
            shutil.copy2(
                weather_epw,
                city_test_case_weather_dir / epw_filename
            )
            
            self.logger.info(f"Successfully processed weather data for {city_key}")
            self.logger.info(f"Files saved to:")
            self.logger.info(f"  - {city_weather_dir / csv_filename}")
            self.logger.info(f"  - {weather_epw}")
            self.logger.info(f"  - {city_test_case_weather_dir / csv_filename}")
            self.logger.info(f"  - {city_test_case_weather_dir / epw_filename}")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error processing city {city_key}: {str(e)}")
            return False

    def process_cities(self, city_keys: List[str] = None) -> Dict[str, bool]:
        """
        Process weather data for specified cities or all cities if none specified
        """
        results = {}
        
        if not city_keys:
            # Process all cities if none specified
            city_keys = list(self.city_coordinates.keys())
            
        for city_key in city_keys:
            self.logger.info(f"Processing {city_key}")
            results[city_key] = self.process_city(city_key)
            
        return results

if __name__ == "__main__":
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Process weather data for cities')
    parser.add_argument('--cities', type=str, nargs='+', 
                        help='List of cities to process (default: all cities)')
    parser.add_argument('--coordinates_file', type=str,
                        help='Path to custom city coordinates JSON file')
    args = parser.parse_args()
    
    try:
        processor = WeatherProcessor(".", args.coordinates_file)
        
        if args.cities:
            results = processor.process_cities(args.cities)
        else:
            results = processor.process_cities()
        
        # Print results
        print("\nProcessing Results:")
        for city, success in results.items():
            status = "Success" if success else "Failed"
            print(f"{city}: {status}")
            
    except FileNotFoundError as e:
        print(f"Error: {str(e)}")
        print("Make sure the city coordinates file exists and is properly formatted.")
    except Exception as e:
        print(f"Error: {str(e)}") 