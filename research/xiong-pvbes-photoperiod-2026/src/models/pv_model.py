"""
Example PV model implementations for OpenCROPS.

This module provides example implementations of BasePVModel
that demonstrate how to create custom models.
"""

import numpy as np
from typing import Dict, Any

from .base import BasePVModel, ModelConfig


class SimplePVModel(BasePVModel):
    """
    Simple PV model using rated power and derating factors.
    
    This is a simplified model suitable for quick calculations
    without detailed panel specifications.
    """
    
    name: str = "simple_pv"
    version: str = "1.0.0"
    
    def __init__(self, config: ModelConfig = None):
        super().__init__(config)
        self.metadata.update({
            "author": "OpenCROPS Team",
            "description": "Simple PV model with temperature derating"
        })
        
        self.params = {
            "eta_pv": 0.20,
            "beta": -0.004,
            "T_ref": 25.0,
            "T_noct": 45.0
        }
        if config and config.params:
            self.params.update(config.params)
    
    def calculate_pv_output(
        self,
        G: np.ndarray,
        T_amb: np.ndarray,
        area: float
    ) -> np.ndarray:
        """
        Calculate PV output using simple efficiency model.
        
        Args:
            G: Solar irradiance (W/m²)
            T_amb: Ambient temperature (°C)
            area: PV panel area (m²)
            
        Returns:
            PV output power (W)
        """
        eta_pv = self.params["eta_pv"]
        beta = self.params["beta"]
        T_ref = self.params["T_ref"]
        
        T_cell = T_amb + G * (self.params["T_noct"] - 20) / 800
        
        eta_actual = eta_pv * (1 + beta * (T_cell - T_ref))
        eta_actual = np.maximum(eta_actual, 0)
        
        P_pv = G * area * eta_actual
        return np.maximum(P_pv, 0)
    
    def validate_inputs(self, inputs: Dict[str, Any]) -> bool:
        """Validate input parameters."""
        required = ["G", "T_amb", "area"]
        return all(key in inputs for key in required)


class FlatPlatePVModel(BasePVModel):
    """
    Flat plate PV model based on equivalent circuit parameters.
    
    This model uses the single diode equation approach
    with parameters from the Jinko 78HL4 module.
    """
    
    name: str = "flat_plate_pv"
    version: str = "1.0.0"
    
    def __init__(self, config: ModelConfig = None):
        super().__init__(config)
        self.metadata.update({
            "author": "OpenCROPS Team",
            "description": "Flat plate PV model using single diode equation"
        })
        
        self.params = {
            "P_rated": 640.11,
            "eta_inv": 0.97,
            "beta": -0.0029,
            "T_ref": 25.0,
            "G_stc": 1000.0
        }
        if config and config.params:
            self.params.update(config.params)
    
    def calculate_pv_output(
        self,
        G: np.ndarray,
        T_amb: np.ndarray,
        area: float
    ) -> np.ndarray:
        """
        Calculate PV output using flat plate model.
        
        Args:
            G: Solar irradiance (W/m²)
            T_amb: Ambient temperature (°C)
            area: PV panel area (m²)
            
        Returns:
            PV output power (W)
        """
        P_rated = self.params["P_rated"]
        eta_inv = self.params["eta_inv"]
        beta = self.params["beta"]
        T_ref = self.params["T_ref"]
        G_stc = self.params["G_stc"]
        
        G = np.asarray(G)
        T_amb = np.asarray(T_amb)
        
        T_cell = T_amb + G * (45 - 20) / 800
        
        derating = 1 + beta * (T_cell - T_ref)
        
        P_dc = P_rated * (G / G_stc) * derating
        P_dc = np.maximum(P_dc, 0)
        
        P_ac = P_dc * eta_inv
        return P_ac
    
    def validate_inputs(self, inputs: Dict[str, Any]) -> bool:
        """Validate input parameters."""
        required = ["G", "T_amb", "area"]
        return all(key in inputs for key in required)
