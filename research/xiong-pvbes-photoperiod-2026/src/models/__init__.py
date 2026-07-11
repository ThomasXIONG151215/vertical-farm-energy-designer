"""
OpenCROPS Models Package

This package provides an extensible model architecture for OpenCROPS.
Users can create custom models by inheriting from the base classes.

Example usage:

    from src.models.base import BasePVModel, BaseBatteryModel
    from src.models.pv_model import SimplePVModel
    
    # Use built-in model
    pv_model = SimplePVModel()
    
    # Create custom model
    class MyCustomPVModel(BasePVModel):
        name = "my_custom_pv"
        
        def calculate_pv_output(self, G, T_amb, area):
            # Your implementation
            pass
        
        def validate_inputs(self, inputs):
            return True

Available models:
    - SimplePVModel: Simple efficiency-based PV model
    - FlatPlatePVModel: Flat plate PV using single diode model

For more information, see docs/extensions/README.md
"""

from .base import (
    BaseModel,
    BasePVModel,
    BaseBatteryModel,
    BaseLoadModel,
    ModelConfig,
    MODEL_REGISTRY,
    get_registered_models
)

from .pv_model import SimplePVModel, FlatPlatePVModel

__all__ = [
    "BaseModel",
    "BasePVModel",
    "BaseBatteryModel", 
    "BaseLoadModel",
    "ModelConfig",
    "SimplePVModel",
    "FlatPlatePVModel",
    "MODEL_REGISTRY",
    "get_registered_models"
]
