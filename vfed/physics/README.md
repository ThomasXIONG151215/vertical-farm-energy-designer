# Physics Module

Building physics core — wet-air thermodynamics, envelope heat & mass transfer, room ODE solver, and sensible heat ratio model.

## Files

| File | Purpose |
|------|---------|
| `psychrometrics.py` | Magnus-formula psychrometrics: saturation VP, absolute humidity, dew point, wet bulb, enthalpy, VPD |
| `envelope.py` | Building envelope model: UA conduction, solar gain, infiltration (sensible + latent), vapour permeance |
| `ode.py` | Euler-integrated room heat (dT/dt) and moisture (dW/dt) balance ODE solver |
| `shr.py` | Dynamic sensible heat ratio (bypass-factor / apparatus-dewpoint coil method) |

## Dependencies

**Leaf module** — no internal `vfed/` imports. Uses only `math`, `dataclasses`, `typing`.

## Usage

```python
from vfed.physics.psychrometrics import temp_rh_to_ah, saturation_vapor_pressure
from vfed.physics.envelope import Envelope
from vfed.physics.ode import RoomODESolver
from vfed.physics.shr import DynamicSHR
```
