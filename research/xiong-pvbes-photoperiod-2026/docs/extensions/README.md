# OpenCROPS Extension Guide

This guide explains how to extend OpenCROPS with custom models for PV systems, batteries, and load profiles.

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Creating a Custom PV Model](#creating-a-custom-pv-model)
3. [Creating a Custom Battery Model](#creating-a-custom-battery-model)
4. [Creating a Custom Load Model](#creating-a-custom-load-model)
5. [Registering and Using Custom Models](#registering-and-using-custom-models)
6. [Best Practices](#best-practices)

---

## Architecture Overview

OpenCROPS uses an abstract base class pattern for extensibility:

```
BaseModel (ABC)
├── BasePVModel (ABC)
│   └── Your custom PV model
├── BaseBatteryModel (ABC)
│   └── Your custom battery model
└── BaseLoadModel (ABC)
    └── Your custom load model
```

All models inherit from `BaseModel` and implement:
- `calculate_output(inputs)` - Main calculation method
- `validate_inputs(inputs)` - Input validation

---

## Creating a Custom PV Model

### Step 1: Import Base Class

```python
from src.models.base import BasePVModel, ModelConfig
import numpy as np
```

### Step 2: Define Your Model

```python
class MyCustomPVModel(BasePVModel):
    name = "my_custom_pv"  # Unique identifier
    version = "1.0.0"
    
    def __init__(self, config=None):
        super().__init__(config)
        
        # Set model parameters
        self.params = {
            "eta_pv": 0.22,      # Panel efficiency
            "beta": -0.004,      # Temperature coefficient
            "T_ref": 25.0,       # Reference temperature
        }
        
        # Update with custom parameters
        if config and config.params:
            self.params.update(config.params)
        
        # Set metadata
        self.metadata.update({
            "author": "Your Name",
            "description": "Custom PV model for XXX panel type"
        })
    
    def calculate_pv_output(self, G, T_amb, area):
        """
        Calculate PV output power.
        
        Args:
            G: Solar irradiance (W/m²), numpy array
            T_amb: Ambient temperature (°C), numpy array
            area: PV panel area (m²), float
            
        Returns:
            PV output power (W), numpy array
        """
        # Your physics-based calculation here
        eta_pv = self.params["eta_pv"]
        beta = self.params["beta"]
        T_ref = self.params["T_ref"]
        
        # Calculate cell temperature
        T_cell = T_amb + G * (45 - 20) / 800
        
        # Calculate efficiency with temperature derating
        eta_actual = eta_pv * (1 + beta * (T_cell - T_ref))
        eta_actual = np.maximum(eta_actual, 0)
        
        # Calculate power output
        P_pv = G * area * eta_actual
        return np.maximum(P_pv, 0)
    
    def validate_inputs(self, inputs):
        """Validate input parameters."""
        required_keys = ["G", "T_amb", "area"]
        return all(key in inputs for key in required_keys)
```

### Step 3: Use Your Model

```python
# Create model instance
pv_model = MyCustomPVModel()

# Create input data
G = np.array([800, 900, 1000])  # Irradiance W/m²
T_amb = np.array([25, 30, 35])  # Temperature °C
area = 50  # m²

# Calculate output
P_pv = pv_model.calculate_pv_output(G, T_amb, area)
print(f"PV Output: {P_pv} W")
```

---

## Creating a Custom Battery Model

### Step 1: Define Battery Model

```python
from src.models.base import BaseBatteryModel, ModelConfig
import numpy as np

class MyCustomBatteryModel(BaseBatteryModel):
    name = "my_custom_battery"
    version = "1.0.0"
    
    def __init__(self, config=None):
        super().__init__(config)
        
        self.params = {
            "max_charge_rate": 0.5,   # C-rate for charging
            "max_discharge_rate": 1.0, # C-rate for discharging
            "efficiency": 0.95,        # Round-trip efficiency
            "soc_min": 0.2,           # Minimum SOC
            "soc_max": 0.95,          # Maximum SOC
            "self_discharge": 0.001    # Daily self-discharge rate
        }
        
        if config and config.params:
            self.params.update(config.params)
    
    def calculate_power_flows(self, P_load, P_pv, soc_initial, capacity):
        """
        Calculate battery power flows.
        
        Args:
            P_load: Load power (W), numpy array
            P_pv: PV power (W), numpy array
            soc_initial: Initial state of charge (0-1)
            capacity: Battery capacity (Wh)
            
        Returns:
            Dictionary with:
                - p_charge: Charging power array
                - p_discharge: Discharging power array
                - soc: State of charge array
        """
        n = len(P_load)
        
        p_charge = np.zeros(n)
        p_discharge = np.zeros(n)
        soc = np.zeros(n)
        
        soc[0] = soc_initial
        
        max_charge = capacity * self.params["max_charge_rate"]
        max_discharge = capacity * self.params["max_discharge_rate"]
        efficiency = self.params["efficiency"]
        
        for i in range(1, n):
            net_power = P_pv[i-1] - P_load[i-1]
            
            if net_power > 0:  # Excess PV power, charge battery
                p_charge[i] = min(net_power * efficiency, max_charge)
                soc[i] = soc[i-1] + p_charge[i] / capacity
            else:  # Power deficit, discharge battery
                p_discharge[i] = min(-net_power / efficiency, max_discharge)
                soc[i] = soc[i-1] - p_discharge[i] / capacity
            
            # Apply SOC bounds
            soc[i] = np.clip(
                soc[i],
                self.params["soc_min"],
                self.params["soc_max"]
            )
        
        return {
            "p_charge": p_charge,
            "p_discharge": p_discharge,
            "soc": soc
        }
    
    def validate_inputs(self, inputs):
        required = ["P_load", "P_pv", "soc_initial", "capacity"]
        return all(key in inputs for key in required)
```

---

## Creating a Custom Load Model

### Step 1: Define Load Model

```python
from src.models.base import BaseLoadModel, ModelConfig
import numpy as np
import pandas as pd

class MyCustomLoadModel(BaseLoadModel):
    name = "my_custom_load"
    version = "1.0.0"
    
    def __init__(self, config=None):
        super().__init__(config)
        
        self.params = {
            "base_load": 5000,      # Base load (W)
            "lighting_power": 3000,  # Lighting power (W)
            "ac_cop": 3.0,          # AC COP
            "schedule": None         # Custom schedule
        }
        
        if config and config.params:
            self.params.update(config.params)
    
    def calculate_load_profile(self, schedule, weather_data=None):
        """
        Calculate load profile based on schedule.
        
        Args:
            schedule: Operation schedule (0/1 for each hour)
            weather_data: Optional DataFrame with temperature
            
        Returns:
            Load power profile (W)
        """
        n = len(schedule)
        load = np.zeros(n)
        
        base = self.params["base_load"]
        lighting = self.params["lighting_power"]
        
        for i in range(n):
            if schedule[i] == 1:  # Light on
                load[i] += lighting
                
                # Temperature-dependent AC load
                if weather_data is not None:
                    T = weather_data.iloc[i]["temperature"]
                    if T > 25:
                        ac_load = (T - 25) * 100 / self.params["ac_cop"]
                        load[i] += ac_load
        
        return load + base
    
    def validate_inputs(self, inputs):
        return "schedule" in inputs
```

---

## Registering and Using Custom Models

### Option 1: Direct Instantiation

```python
from src.models.base import BasePVModel

class MyPVModel(BasePVModel):
    # ... implementation

# Use directly
model = MyPVModel()
output = model.calculate_output(inputs)
```

### Option 2: Model Registry

```python
from src.models.base import register_model, get_registered_models

# Register your model
register_model(MyPVModel, get_registered_models())

# Get all registered models
models = get_registered_models()
print(models.keys())  # ['simple_pv', 'flat_plate_pv', 'my_pv_model']
```

### Option 3: Configuration-Based Loading

```python
from src.models.base import MODEL_REGISTRY

# Load model from configuration
config = {"model_type": "my_custom_pv", "params": {...}}

if config["model_type"] in MODEL_REGISTRY:
    model_class = MODEL_REGISTRY[config["model_type"]]
    model = model_class(ModelConfig(**config))
```

---

## Best Practices

### 1. Use Type Hints

```python
def calculate_pv_output(
    self,
    G: np.ndarray,
    T_amb: np.ndarray,
    area: float
) -> np.ndarray:
    ...
```

### 2. Document Parameters

```python
def calculate_pv_output(self, G, T_amb, area):
    """
    Calculate PV output power.
    
    Args:
        G: Solar irradiance (W/m²). Shape: (n,) where n is hours
        T_amb: Ambient temperature (°C). Shape: (n,)
        area: PV panel area (m²)
        
    Returns:
        PV output power (W). Shape: (n,)
    """
```

### 3. Validate Inputs

```python
def validate_inputs(self, inputs):
    if not isinstance(inputs, dict):
        return False
    required = ["G", "T_amb", "area"]
    return all(key in inputs for key in required)
```

### 4. Handle Edge Cases

```python
def calculate_pv_output(self, G, T_amb, area):
    G = np.asarray(G)
    T_amb = np.asarray(T_amb)
    
    # Handle edge cases
    G = np.maximum(G, 0)
    T_amb = np.clip(T_amb, -40, 60)  # Reasonable temperature range
    
    # ... rest of calculation
```

### 5. Follow Naming Conventions

- Class names: `PascalCase` (e.g., `MyCustomPVModel`)
- Method names: `snake_case` (e.g., `calculate_pv_output`)
- Parameter names: `snake_case` (e.g., `soc_initial`)
- Constants: `UPPER_SNAKE_CASE` (e.g., `MAX_SOC`)

---

## Example: Complete Custom PV Model

See [`src/models/pv_model.py`](pv_model.md) for a complete example implementation.

---

## Getting Help

- **Issues**: https://github.com/ThomasXIONG151215/OpenCROPS/issues
- **Discussions**: https://github.com/ThomasXIONG151215/OpenCROPS/discussions
