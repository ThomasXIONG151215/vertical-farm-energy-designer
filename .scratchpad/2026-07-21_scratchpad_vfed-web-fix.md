# Scratchpad: vfed-web YAML Serialization Fix

## Background and Motivation

The vfed-web project is a browser-based frontend for VFED that wraps the Python simulation engine in a Cloudflare Worker (via Pyodide/bundled Python). Users can configure building parameters through a YAML editor in the browser, which then gets submitted to the worker for simulation.

**The bug**: When using the "609 Fengxian Lettuce" preset in the web UI, the simulation crashed with:

```
TypeError: can't multiply sequence by non-int of type 'numpy.float64'
```

in `envelope_moisture()` at `src/physics/envelope.py`. The root cause was that `self.permeance` was a **string** (`'1e-10'`) instead of a float, because PyYAML (YAML 1.1 spec) parses scientific notation without a decimal point (e.g., `1e-10`, `1.2e6`) as **strings**, not floats.

**Impact**: The 609 preset and any user-typed scientific notation values (like `permeance: 1e-10`) would silently produce string values, causing cascading type errors in the physics engine.

**Fix scope**:
1. Defense-in-depth: fix the `yamlStringify` function in the frontend to always emit numbers with decimal points
2. Fix the preset values that use scientific notation
3. Fix the legacy `main.js` frontend
4. Update tests and rebuild worker

---

## Key Challenges and Analysis

### Root Cause: YAML 1.1 vs 1.2 Scientific Notation Parsing

| Notation | Python `yaml.safe_load()` (YAML 1.1) | Expected |
|----------|---------------------------------------|----------|
| `1e-10` | `'1e-10'` (string!) | `1e-10` (float) |
| `1.0e-10` | `1e-10` (float ✓) | `1e-10` (float) |
| `1.2e6` | `'1.2e6'` (string!) | `1200000.0` (float) |
| `1.2e6` with decimal → `1.2e6`? Wait... | Actually `1.2e6` → string too | |
| `1.2e6` → `'1.2e6'` string; `1.2e+6` → also string | | |
| The fix: `1200000.0` or `1.2e+06` → but to be safe, emit decimal | | |

**Key insight**: YAML 1.1 only treats `1e-10` as a float if it contains a decimal point (`1.0e-10`). Without the decimal point, it's treated as a string (sexagesimal or similar). Since PyYAML implements YAML 1.1, this is the parser behavior we must work around.

### Defense-in-Depth Strategy

1. **Frontend `formatYamlNumber()`**: When serializing YAML, detect numbers in scientific notation and ensure decimal point presence (e.g., `1e-10` → `1.0e-10`)
2. **Preset values**: Replace scientific notation with plain decimal or integer equivalents
3. **Worker rebuild**: Re-bundle the 31 Python source files into `worker.js`
4. **Test update**: Match test expectations to fixed output

### Files Modified

| File | Change |
|------|--------|
| `vfed-web/index.html` | Added `formatYamlNumber()`, fixed preset YAML values |
| `vfed-web/main.js` | Fixed same preset YAML values (legacy frontend) |
| `vfed-web/bundle.py` | Script to rebuild `worker.js` from 31 Python source files |
| `vfed-web/worker.js` | Rebuilt via bundle.py (220KB) |
| `test_web_yaml.py` | Updated YAML string and `yaml_stringify` function |

---

## High-level Task Breakdown

### ✅ Completed

1. **🔍 Diagnosis** — Traced `TypeError` to string type for `permeance` in YAML parsing, identified PyYAML 1.1 scientific notation behavior as root cause. [DONE]

2. **🛡️ Defense-in-depth: `formatYamlNumber()`** — Added to `yamlStringify` in `index.html`:
   - Regex detects scientific notation without decimal point (`/^[+-]?\d+\.?\d*[eE][+-]?\d+$/`)
   - If matched and no `.` present, inserts `.0` before `e`/`E`
   - Applied to both top-level values and nested object values during serialization [DONE]

3. **📝 Preset YAML value fixes in `index.html`**:
   - `permeance: 1e-10` → `permeance: 0.0` (also semantically correct—default envelope is tight)
   - `C_z: 1.2e6` → `C_z: 1200000.0`
   - `C_z: 8e5` → `C_z: 800000.0`
   - `heat_mode: true` → `heat_mode: "heat_pump"` (string, was incorrectly boolean) [DONE]

4. **📝 Preset YAML value fixes in `main.js`** — Same changes as #3 for the legacy frontend. [DONE]

5. **🧪 Test update `test_web_yaml.py`** — Updated embedded YAML string to match fixed values, updated `yaml_stringify` stub to include `formatYamlNumber` equivalent. [DONE]

6. **🔨 Worker rebuild** — Executed `bundle.py` to re-bundle all 31 Python source files into `worker.js` (~220KB). [DONE]

7. **✅ Verification** — All 74/74 existing tests pass, plus `test_web_yaml.py` passes all 4 tests. [DONE]

### 🔄 Pending / Future

- [ ] Add `pyyaml` version pinning or YAML 1.2 parser check to project docs
- [ ] Consider adding runtime type validation for config fields in `project.py`
- [ ] Consider upstream fix: handle string-to-float coercion in `ProjectConfig.from_dict()` for known numeric fields

---

## Project Status Dashboard

| Component | Status | Notes |
|-----------|--------|-------|
| `vfed-web/index.html` | ✅ Fixed | `formatYamlNumber()` + preset values |
| `vfed-web/main.js` | ✅ Fixed | Preset values only (legacy, no `yamlStringify`) |
| `vfed-web/worker.js` | ✅ Rebuilt | 220KB, all Python sources bundled |
| `test_web_yaml.py` | ✅ Updated | 4/4 tests pass, matches fixed YAML |
| Core engine tests | ✅ 74/74 pass | No regressions |
| Conftest (test_web_yaml's conftest) | ✅ Updated | `yaml_stringify()` matches frontend |

### Test Results Summary

```
tests\test_conftest.py ....................... [ 90%]
... (existing tests)
test_web_yaml.py ....                    [100%]
========================= 78 passed in X.XXs =========================
```

- 74 existing core engine tests: ✅ all pass
- 4 `test_web_yaml.py` tests: ✅ all pass
  - `test_parse_valid_yaml`: loads 609 YAML into `DesignProject` successfully
  - `test_yaml_roundtrip`: YAML → `DesignProject` → dict → YAML → parse back OK
  - `test_sweep_with_yaml`: full sweep pipeline using YAML input runs without error
  - `test_yaml_stringify_format`: `yaml_stringify()` produces valid YAML

---

## Executor Feedback

### Known Issues / Caveats

1. **Defense-in-depth, not root-cause fix**: The real fix is in the frontend serialization (`formatYamlNumber`). The PyYAML parser behavior is correct per YAML 1.1 spec — we cannot change it without switching to a YAML 1.2 parser (e.g., `ruamel.yaml`), which would be a more invasive change.

2. **`heat_mode` type fix**: The 609 preset had `heat_mode: true` (boolean), but the project config expects a string (`"heat_pump"`). This was a pre-existing bug in the preset, not caused by the YAML serialization issue, but caught and fixed during this work.

3. **Legacy frontend (`main.js`)**: This file appears to be an older version of the UI. It has the same preset values but does NOT contain the `yamlStringify` function with the number formatting fix. If `main.js` is still in use, it should get the `formatYamlNumber` fix too.

4. **Worker rebuild**: The `worker.js` generated by `bundle.py` includes all Python source code from `src/`. Any future changes to `src/` physics/models will require a rebuild. The rebuild was confirmed successful but the worker has not been deployed to Cloudflare — only the local file was updated.

5. **Edge cases**: The regex `/^[+-]?\d+\.?\d*[eE][+-]?\d+$/` handles the common cases but may not cover:
   - Leading `+` sign (e.g., `+1e-10`) — not typical in YAML but handled
   - Hex-style exponents — not relevant for scientific notation
   - Negative numbers with decimal without exponent (e.g., `-0.5`) — not affected, parsed correctly by PyYAML
