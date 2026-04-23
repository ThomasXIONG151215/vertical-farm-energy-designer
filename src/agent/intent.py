"""
Intent Parser
=============

Parses natural language intents into structured configuration.

Two-mode approach:
1. Regex patterns for simple, deterministic intents (fast path)
2. LLM fallback for complex or ambiguous intents (slow path)
"""

import re
import os
from typing import Dict, Any, Optional, Tuple, List
from dataclasses import dataclass


# Intent pattern definitions
INTENT_PATTERNS = {
    # Goal patterns
    "goal": [
        (r"minimize.*energy|reduce.*energy|节能|省电", "minimize_energy"),
        (r"minimize.*cost|reduce.*cost|省钱|降低成本", "minimize_cost"),
        (r"maximize.*self.*suffic|自给自足|自给", "maximize_self_sufficiency"),
        (r"minimize.*payback|快速回本|缩短回本", "minimize_payback"),
        (r"maximize.*savings|最大化收益|多赚钱", "maximize_savings"),
        (r"optimize|优化", "optimize"),
    ],

    # Crop patterns
    "crop": [
        (r"lettuce|生菜|莴苣", "lettuce"),
        (r"tomato|番茄|西红柿", "tomato"),
        (r"strawberry|草莓", "strawberry"),
        (r"herb|香草|草药", "herb"),
        (r"leaf.*green|叶菜", "leaf_green"),
    ],

    # Season patterns
    "season": [
        (r"summer|夏季|夏天", "summer"),
        (r"winter|冬季|冬天", "winter"),
        (r"spring|春季|春天", "spring"),
        (r"autumn|秋季|秋天", "autumn"),
        (r"transition|过渡季节", "transition"),
    ],

    # Weather patterns
    "weather": [
        (r"cloudy|阴天|多云", "cloudy"),
        (r"rainy|雨天|下雨", "rainy"),
        (r"sunny|晴天|阳光", "sunny"),
        (r"hot|炎热|高温", "hot"),
        (r"cold|寒冷|低温", "cold"),
    ],

    # Action patterns
    "action": [
        (r"evaluate|评估", "evaluate"),
        (r"optimize|优化", "optimize"),
        (r"calibrate|校准", "calibrate"),
        (r"analyze|分析", "analyze"),
        (r"compare|对比|比较", "compare"),
        (r"simulate|模拟", "simulate"),
        (r"build.*idf|生成idf", "build_idf"),
        (r"run.*simul|运行模拟", "run_simulation"),
    ],

    # Parameter hints
    "pv_area_hint": [
        (r"pv.*(\d+)\s*m2?|(\d+)\s*m2.*pv|pv.*area.*(\d+)", "pv_area"),
        (r"(\d+)\s*m2|(\d+)\s*平方米", "pv_area"),
    ],

    "battery_hint": [
        (r"battery.*(\d+)\s*kwh|(\d+)\s*kwh.*battery|battery.*capacity.*(\d+)", "battery"),
        (r"(\d+)\s*kwh|(\d+)\s*度", "battery"),
    ],
}


@dataclass
class ParsedIntent:
    """Structured representation of parsed intent"""
    action: Optional[str] = None
    goal: Optional[str] = None
    crop: Optional[str] = None
    season: Optional[str] = None
    weather: Optional[str] = None
    city: Optional[str] = None
    pv_area: Optional[float] = None
    battery_capacity: Optional[float] = None
    start_hour: Optional[int] = None
    confidence: float = 1.0
    matched_patterns: List[str] = None

    def __post_init__(self):
        if self.matched_patterns is None:
            self.matched_patterns = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "goal": self.goal,
            "crop": self.crop,
            "season": self.season,
            "weather": self.weather,
            "city": self.city,
            "pv_area": self.pv_area,
            "battery_capacity": self.battery_capacity,
            "start_hour": self.start_hour,
            "confidence": self.confidence,
            "matched_patterns": self.matched_patterns,
        }


class IntentParser:
    """
    Parses natural language intent into structured configuration.

    Usage:
        parser = IntentParser()
        intent = parser.parse("minimize energy for lettuce farm in summer")
        # intent.action = "optimize"
        # intent.goal = "minimize_energy"
        # intent.crop = "lettuce"
        # intent.season = "summer"
    """

    def __init__(self, use_llm_fallback: bool = True):
        """
        Initialize intent parser.

        Args:
            use_llm_fallback: If True, use LLM for complex/unmatched intents
        """
        self.use_llm_fallback = use_llm_fallback
        self._compile_patterns()

    def _compile_patterns(self):
        """Pre-compile all regex patterns for performance"""
        self._compiled: Dict[str, List[Tuple[re.Pattern, str]]] = {}

        for category, patterns in INTENT_PATTERNS.items():
            compiled_list = []
            for pattern, result in patterns:
                compiled_list.append((re.compile(pattern, re.IGNORECASE), result))
            self._compiled[category] = compiled_list

    def parse(self, text: str) -> ParsedIntent:
        """
        Parse natural language text into structured intent.

        Args:
            text: Natural language input

        Returns:
            ParsedIntent with extracted parameters
        """
        if not text or not text.strip():
            return ParsedIntent(confidence=0.0)

        text = text.strip()
        intent = ParsedIntent()
        matched_any = False

        # Try regex matching for each category
        for category, patterns in self._compiled.items():
            for pattern, result in patterns:
                match = pattern.search(text)
                if match:
                    self._apply_match(intent, category, result, match)
                    intent.matched_patterns.append(f"{category}:{result}")
                    matched_any = True
                    break  # Only use first match per category

        # Extract city if mentioned
        intent.city = self._extract_city(text)

        # Extract numbers for pv_area and battery
        pv, batt = self._extract_numbers(text)
        if pv is not None:
            intent.pv_area = pv
        if batt is not None:
            intent.battery_capacity = batt

        # Determine action if not specified
        if intent.action is None:
            intent.action = self._infer_action(text)

        # Calculate confidence based on matched patterns
        intent.confidence = min(1.0, len(intent.matched_patterns) * 0.25)

        # If low confidence and LLM fallback enabled, try LLM
        if intent.confidence < 0.5 and self.use_llm_fallback:
            return self._llm_fallback(text, intent)

        return intent

    def _apply_match(self, intent: ParsedIntent, category: str, value: str, match: re.Match):
        """Apply a matched pattern to the intent"""
        if category == "goal":
            intent.goal = value
        elif category == "crop":
            intent.crop = value
        elif category == "season":
            intent.season = value
        elif category == "weather":
            intent.weather = value
        elif category == "action":
            intent.action = value

    def _extract_city(self, text: str) -> Optional[str]:
        """Extract city name from text"""
        # Simple city name extraction
        try:
            from weather.city_coordinates import CITY_COORDINATES
        except ImportError:
            # When running from tests, add project root to path
            import sys
            from pathlib import Path
            project_root = Path(__file__).resolve().parent.parent.parent
            sys.path.insert(0, str(project_root))
            from weather.city_coordinates import CITY_COORDINATES

        available_cities = {c.lower(): c for c in CITY_COORDINATES.keys()}
        text_lower = text.lower()

        for name, key in available_cities.items():
            if name in text_lower or key in text_lower:
                return key

        return None

    def _extract_numbers(self, text: str) -> Tuple[Optional[float], Optional[float]]:
        """Extract PV area and battery capacity numbers from text"""
        pv_area = None
        battery = None

        # PV area patterns
        pv_patterns = [
            r"pv.*?(\d+(?:\.\d+)?)\s*(?:m2|平方米|平)",
            r"(\d+(?:\.\d+)?)\s*(?:m2|平方米|平).*?pv",
            r"光伏.*?(\d+(?:\.\d+)?)",
            r"(\d+(?:\.\d+)?)\s*平.*?光伏",
        ]

        for pattern in pv_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    pv_area = float(match.group(1))
                    break
                except (ValueError, IndexError):
                    pass

        # Battery patterns
        batt_patterns = [
            r"battery.*?(\d+(?:\.\d+)?)\s*(?:kwh|度)",
            r"(\d+(?:\.\d+)?)\s*(?:kwh|度).*?battery",
            r"电池.*?(\d+(?:\.\d+)?)",
            r"(\d+(?:\.\d+)?)\s*度.*?电池",
        ]

        for pattern in batt_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    battery = float(match.group(1))
                    break
                except (ValueError, IndexError):
                    pass

        return pv_area, battery

    def _infer_action(self, text: str) -> str:
        """Infer action from text if not explicitly specified"""
        text_lower = text.lower()

        if any(kw in text_lower for kw in ["what", "how", "多少", "什么"]):
            return "evaluate"

        if any(kw in text_lower for kw in ["find", "best", "optimal", "最佳", "最优"]):
            return "optimize"

        if any(kw in text_lower for kw in ["compare", "difference", "对比", "比较"]):
            return "compare"

        # Default to evaluate
        return "evaluate"

    def _llm_fallback(self, text: str, fallback_intent: ParsedIntent) -> ParsedIntent:
        """
        Use LLM to parse complex or ambiguous intents.

        This is a placeholder - in production, you would call an LLM API here.
        """
        # Check for LLM API availability
        api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")

        if not api_key:
            # No LLM available, return regex result with low confidence
            fallback_intent.confidence = 0.3
            return fallback_intent

        # In production, you would call the LLM here:
        # prompt = f"Parse this intent: {text}"
        # response = call_llm(prompt)
        # return parse_llm_response(response)

        fallback_intent.confidence = 0.3
        return fallback_intent


# Convenience function
def parse_intent(text: str) -> ParsedIntent:
    """
    Parse natural language intent into structured configuration.

    Usage:
        intent = parse_intent("minimize energy for lettuce farm in summer")
    """
    parser = IntentParser()
    return parser.parse(text)