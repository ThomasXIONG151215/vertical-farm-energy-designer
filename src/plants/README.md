# Plants Module

Plant biology models — transpiration (moisture source for the room ODE) and carbon-balance growth.

## Files

| File | Purpose |
|------|---------|
| `transpiration.py` | Transpiration model with 6 configurable methods: constant, daily, per_plant (direct-set); vpd, stomatal (Penman-Monteith style), van_henten (model-calculated) |
| `van_henten.py` | Van Henten 2003 one-state carbon-balance growth model — dry weight driven by temperature, CO₂, and PAR |

## Dependencies

`transpiration.py` imports from `src/physics/psychrometrics` (VPD calculation). `van_henten.py` is self-contained.

## Usage

```python
from src.plants.transpiration import TranspirationModel
from src.plants.van_henten import VanHenten
```
