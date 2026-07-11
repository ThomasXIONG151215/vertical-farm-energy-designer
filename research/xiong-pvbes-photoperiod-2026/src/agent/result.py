"""
AgentResult Schema
=================

Standardized return type for all Agent-Native operations.
Compatible with existing metrics but adds agent-friendly features:
- _next_actions: list of suggested next actions
- _confidence: confidence score
- Structured error/warning with _fix suggestions
"""

from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any, Literal
from enum import Enum
import json


class ResultStatus(Enum):
    """Result status enumeration"""
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"  # Some constraints unmet, partial success


@dataclass
class Warning:
    """Warning with code, message, and severity"""
    code: str
    message: str
    severity: Literal["low", "medium", "high"] = "low"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Warning":
        return cls(**d)


@dataclass
class Error:
    """Error with code, message, and _fix suggestion"""
    code: str
    message: str
    parameter: Optional[str] = None
    provided_value: Optional[Any] = None
    valid_range: Optional[List[Any]] = None
    _fix: Optional[Dict[str, Any]] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        # Remove None values for cleaner output
        return {k: v for k, v in d.items() if v is not None}

    @classmethod
    def from_dict(cls, d: dict) -> "Error":
        return cls(**d)


@dataclass
class AgentResult:
    """
    Standardized result for all agent operations.

    Attributes:
        status: Operation status (success/failed/partial)
        data: Core result data (metrics, configuration, etc.)
        _next_actions: Suggested next actions for the agent
        warnings: List of warnings encountered
        errors: List of errors (if any)
        _confidence: Confidence score (0.0-1.0)
        _metadata: Additional metadata

    Example:
        >>> result = AgentResult(
        ...     status=ResultStatus.SUCCESS,
        ...     data={"total_energy_kwh": 1423.5, "cost_rmb": 1156.8},
        ...     _next_actions=["increase_battery_20pct", "reduce_pv_area"],
        ...     _confidence=0.87
        ... )
        >>> print(result.to_json())
    """

    status: Literal["success", "failed", "partial"]
    data: Dict[str, Any] = field(default_factory=dict)
    _next_actions: List[str] = field(default_factory=list)
    warnings: List[Warning] = field(default_factory=list)
    errors: List[Error] = field(default_factory=list)
    _confidence: float = 1.0
    _metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Convert dicts to Warning/Error objects"""
        if self.warnings and isinstance(self.warnings[0], dict):
            self.warnings = [Warning.from_dict(w) for w in self.warnings]
        if self.errors and isinstance(self.errors[0], dict):
            self.errors = [Error.from_dict(e) for e in self.errors]

    def to_dict(self) -> dict:
        """Convert to dictionary with snake_case keys"""
        d = {
            "status": self.status,
            "data": self.data,
            "_next_actions": self._next_actions,
            "warnings": [w.to_dict() if isinstance(w, Warning) else w for w in self.warnings],
            "errors": [e.to_dict() if isinstance(e, Error) else e for e in self.errors],
            "_confidence": self._confidence,
            "_metadata": self._metadata,
        }
        return d

    def to_json(self, indent: Optional[int] = None) -> str:
        """Convert to JSON string"""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: dict) -> "AgentResult":
        """Create AgentResult from dictionary"""
        return cls(
            status=d["status"],
            data=d.get("data", {}),
            _next_actions=d.get("_next_actions", []),
            warnings=[Warning.from_dict(w) for w in d.get("warnings", [])],
            errors=[Error.from_dict(e) for e in d.get("errors", [])],
            _confidence=d.get("_confidence", 1.0),
            _metadata=d.get("_metadata", {}),
        )

    @classmethod
    def from_json(cls, json_str: str) -> "AgentResult":
        """Create AgentResult from JSON string"""
        return cls.from_dict(json.loads(json_str))

    @classmethod
    def success(
        cls,
        data: Dict[str, Any],
        next_actions: Optional[List[str]] = None,
        warnings: Optional[List[Warning]] = None,
        confidence: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "AgentResult":
        """Factory method for success results"""
        return cls(
            status=ResultStatus.SUCCESS.value,
            data=data,
            _next_actions=next_actions or [],
            warnings=warnings or [],
            _confidence=confidence,
            _metadata=metadata or {},
        )

    @classmethod
    def failed(
        cls,
        message: str,
        code: str = "E_UNKNOWN",
        errors: Optional[List[Error]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "AgentResult":
        """Factory method for failed results"""
        err = Error(code=code, message=message)
        return cls(
            status=ResultStatus.FAILED.value,
            errors=[err] if errors is None else errors,
            _metadata=metadata or {},
        )

    @classmethod
    def partial(
        cls,
        data: Dict[str, Any],
        message: str,
        next_actions: Optional[List[str]] = None,
        warnings: Optional[List[Warning]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "AgentResult":
        """Factory method for partial success (some constraints unmet)"""
        warn = Warning(code="W_PARTIAL", message=message, severity="medium")
        return cls(
            status=ResultStatus.PARTIAL.value,
            data=data,
            _next_actions=next_actions or [],
            warnings=[warn] if warnings is None else warnings,
            _confidence=0.5,
            _metadata=metadata or {},
        )

    def has_errors(self) -> bool:
        """Check if result has errors"""
        return len(self.errors) > 0

    def has_warnings(self) -> bool:
        """Check if result has warnings"""
        return len(self.warnings) > 0

    def get_first_error(self) -> Optional[Error]:
        """Get first error if any"""
        return self.errors[0] if self.errors else None

    def get_first_fix(self) -> Optional[Dict[str, Any]]:
        """Get _fix from first error if any"""
        err = self.get_first_error()
        return err._fix if err else None