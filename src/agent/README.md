# Agent Module

Evaluation surface for the CLI — structured success/error-code payload preserving the agent-cli contract.

## Files

| File | Purpose |
|------|---------|
| `evaluator.py` | `agent_evaluate()` — full pipeline: load YAML config → run building simulation → sweep PVBES → return best design |

## Usage

```python
from src.agent.evaluator import agent_evaluate

result = agent_evaluate("my_farm.yaml", cache_dir="weather_cache")
```
