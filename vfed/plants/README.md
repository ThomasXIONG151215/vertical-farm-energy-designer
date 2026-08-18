# Plants Module

Plant biology models — transpiration (moisture source for the room ODE) and carbon-balance growth.

## Files

| File | Purpose |
|------|---------|
| `transpiration.py` | Transpiration model with 5 configurable methods: van_henten (model-coupled); daily, per_plant, daily_per_period, per_plant_per_period (direct-set) |
| `van_henten.py` | Van Henten 2003 one-state carbon-balance growth model — dry weight driven by temperature, CO₂, and PAR |

## Dependencies

`transpiration.py` imports from `vfed/physics/psychrometrics` (VPD calculation). `van_henten.py` is self-contained.

## Usage

```python
from vfed.plants.transpiration import TranspirationModel
from vfed.plants.van_henten import VanHenten
```
