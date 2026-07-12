# Devices Module

Physical device models for the plant factory: air conditioning, dehumidification, LED lighting, compressor hysteresis, and first-order thermal lag.

## Files

| File | Purpose |
|------|---------|
| `hvac.py` | Fixed-speed AC with hysteresis thermostat, COP vs outdoor temp, SHR-based latent removal |
| `dehumidifier.py` | Parametric dehumidifier — polynomial power model, ASHRAE saturation efficiency, RH hysteresis |
| `led.py` | LED growth light — auto-deduces power from PPFD/efficacy; dominant internal heat load |
| `compressor.py` | Hysteresis (deadband) compressor state machine with minimum run/stop times |
| `lag.py` | First-order exponential transient for device thermal/moisture dynamics |

## Dependencies

Imports from `src/physics/` (psychrometrics, SHR). No other internal dependencies.

## Usage

```python
from src.devices.hvac import HVACDevice, COPModel
from src.devices.dehumidifier import DEHDevice
from src.devices.led import LEDDevice
from src.devices.compressor import CompressorState
from src.devices.lag import FirstOrderLag
```
