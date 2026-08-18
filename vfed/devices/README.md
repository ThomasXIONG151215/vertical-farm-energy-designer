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

Imports from `vfed/physics/` (psychrometrics, SHR). No other internal dependencies.

## Usage

```python
from vfed.devices.hvac import HVACDevice, COPModel
from vfed.devices.dehumidifier import DEHDevice
from vfed.devices.led import LEDDevice
from vfed.devices.compressor import CompressorState
from vfed.devices.lag import FirstOrderLag
```
