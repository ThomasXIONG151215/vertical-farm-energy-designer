# Plants Module

Plant biology models — transpiration (moisture source for the room ODE) and carbon-balance growth.

## Files

| File | Purpose |
|------|---------|
| `transpiration.py` | Transpiration model with 4 configurable methods: constant, VPD-driven, stomatal (Penman-Monteith), Van Henten |
| `van_henten.py` | Van Henten 2003 one-state carbon-balance growth model — dry weight driven by temperature, CO₂, and PAR |

## Dependencies

`transpiration.py` imports from `src/physics/psychrometrics` (VPD calculation). `van_henten.py` is self-contained.

## Usage

```python
from src.plants.transpiration import TranspirationModel
from src.plants.van_henten import VanHenten
```
