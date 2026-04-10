"""
Base model interface for OpenCROPS extensible architecture.

This module provides abstract base classes for creating custom models
that can be integrated with the OpenCROPS optimization framework.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Any, Optional
import numpy as np
import pandas as pd


@dataclass
class ModelConfig:
    """Configuration parameters for a model."""
    name: str
    enabled: bool = True
    params: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.params is None:
            self.params = {}


class BaseModel(ABC):
    """
    Abstract base class for OpenCROPS models.
    
    All custom models should inherit from this class and implement
    the required methods.
    
    Attributes:
        name: Model identifier
        config: Model configuration
        metadata: Model metadata (author, version, description)
    """
    
    name: str = "base_model"
    version: str = "1.0.0"
    
    def __init__(self, config: Optional[ModelConfig] = None):
        """
        Initialize the model.
        
        Args:
            config: Optional configuration parameters
        """
        self.config = config or ModelConfig(name=self.name)
        self.metadata = {
            "name": self.name,
            "version": self.version,
            "author": "Unknown",
            "description": ""
        }
    
    @abstractmethod
    def calculate_output(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calculate model output given inputs.
        
        Args:
            inputs: Dictionary of input parameters
            
        Returns:
            Dictionary of output values
            
        Raises:
            NotImplementedError: Must be implemented by subclass
        """
        raise NotImplementedError
    
    @abstractmethod
    def validate_inputs(self, inputs: Dict[str, Any]) -> bool:
        """
        Validate input parameters.
        
        Args:
            inputs: Dictionary of input parameters to validate
            
        Returns:
            True if inputs are valid, False otherwise
        """
        raise NotImplementedError
    
    def get_parameters(self) -> Dict[str, Any]:
        """
        Get model parameters.
        
        Returns:
            Dictionary of model parameters
        """
        return self.config.params if self.config else {}
    
    def set_parameters(self, params: Dict[str, Any]) -> None:
        """
        Set model parameters.
        
        Args:
            params: Dictionary of parameters to set
        """
        if self.config:
            self.config.params.update(params)
    
    def get_metadata(self) -> Dict[str, Any]:
        """
        Get model metadata.
        
        Returns:
            Dictionary of metadata
        """
        return self.metadata.copy()
    
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name='{self.name}', version='{self.version}')"


class BasePVModel(BaseModel):
    """
    Base class for photovoltaic models.
    
    Inherit from this class to create custom PV models.
    """
    
    name: str = "base_pv_model"
    
    @abstractmethod
    def calculate_pv_output(
        self,
        G: np.ndarray,
        T_amb: np.ndarray,
        area: float
    ) -> np.ndarray:
        """
        Calculate PV output power.
        
        Args:
            G: Solar irradiance (W/m²)
            T_amb: Ambient temperature (°C)
            area: PV panel area (m²)
            
        Returns:
            PV output power (W)
        """
        raise NotImplementedError


class BaseBatteryModel(BaseModel):
    """
    Base class for battery energy storage models.
    
    Inherit from this class to create custom battery models.
    """
    
    name: str = "base_battery_model"
    
    @abstractmethod
    def calculate_power_flows(
        self,
        P_load: np.ndarray,
        P_pv: np.ndarray,
        soc_initial: float,
        capacity: float
    ) -> Dict[str, np.ndarray]:
        """
        Calculate battery power flows.
        
        Args:
            P_load: Load power (W)
            P_pv: PV power (W)
            soc_initial: Initial state of charge (0-1)
            capacity: Battery capacity (Wh)
            
        Returns:
            Dictionary with 'p_charge', 'p_discharge', 'soc' arrays
        """
        raise NotImplementedError


class BaseLoadModel(BaseModel):
    """
    Base class for load profile models.
    
    Inherit from this class to create custom load models.
    """
    
    name: str = "base_load_model"
    
    @abstractmethod
    def calculate_load_profile(
        self,
        schedule: np.ndarray,
        weather_data: Optional[pd.DataFrame] = None
    ) -> np.ndarray:
        """
        Calculate load profile.
        
        Args:
            schedule: Operation schedule (hourly)
            weather_data: Optional weather data for temperature-dependent loads
            
        Returns:
            Load power profile (W)
        """
        raise NotImplementedError


def register_model(model_class: type, model_registry: Dict[str, type]) -> None:
    """
    Register a model class in the global registry.
    
    Args:
        model_class: Model class to register
        model_registry: Dictionary to register in
    """
    if issubclass(model_class, BaseModel):
        model_registry[model_class.name] = model_class


# Global model registry
MODEL_REGISTRY: Dict[str, type] = {}


def get_registered_models() -> Dict[str, type]:
    """
    Get all registered model classes.
    
    Returns:
        Dictionary of registered models
    """
    return MODEL_REGISTRY.copy()
