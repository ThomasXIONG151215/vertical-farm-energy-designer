"""
OpenCROPS Agent Module
=====================

Agent-Native interface for OpenCROPS, designed for AI agent consumption.

Key Principles:
1. Single entry point: agent.run(intent)
2. Self-contained: all context in, actionable results out
3. Structured returns: AgentResult with _next_actions
4. Error self-healing: errors include _fix suggestions

Usage:
    from src.agent import AgentResult
    from src.agent.result import Warning, Error

    # Import the main run function
    from src.agent import agent  # agent.run(intent)

    # Simple usage
    result = agent.run("minimize energy for shanghai")

    # Structured usage
    if result.status == "success":
        print(result.data["metrics"])
        print(result._next_actions)
"""

from .result import AgentResult, Warning, Error, ResultStatus
from .errors import ERROR_CATALOG, get_fix, create_error, create_warning
from .intent import IntentParser, parse_intent, ParsedIntent
from .evaluator import agent_evaluate

# Note: To use agent.run(), import it directly:
#   from src.agent import agent
#   result = agent.run("...")
# Or:
#   from src.agent.agent import run
#   result = run("...")

__all__ = [
    # Schema classes
    "AgentResult",
    "Warning",
    "Error",
    "ResultStatus",

    # Utilities
    "ERROR_CATALOG",
    "get_fix",
    "create_error",
    "create_warning",

    # Intent parsing
    "IntentParser",
    "parse_intent",
    "ParsedIntent",

    # Core functions
    "agent_evaluate",
]