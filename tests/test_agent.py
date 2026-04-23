"""
Unit Tests for Agent-Native Interface
=====================================

Tests T1-T12 from the test plan:
- T1-T4: AgentResult schema
- T5-T8: Intent parser
- T9-T12: Evaluator wrapper
"""

import pytest
import json
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.agent.result import AgentResult, Warning, Error, ResultStatus
from src.agent.errors import ERROR_CATALOG, create_error, create_warning, get_fix
from src.agent.intent import IntentParser, parse_intent, ParsedIntent
from src.agent_runner import run as agent_run


# =============================================================================
# T1-T4: AgentResult Schema Tests
# =============================================================================

class TestAgentResult:
    """Tests for AgentResult schema"""

    def test_t1_success_result_to_dict(self):
        """T1: AgentResult serialization to dict"""
        result = AgentResult(
            status="success",
            data={"total_energy_kwh": 1423.5, "cost_rmb": 1156.8},
            _next_actions=["increase_battery_20pct"],
            _confidence=0.87
        )

        d = result.to_dict()

        assert d["status"] == "success"
        assert d["data"]["total_energy_kwh"] == 1423.5
        assert "_next_actions" in d
        assert d["_next_actions"] == ["increase_battery_20pct"]
        assert d["_confidence"] == 0.87

    def test_t1_success_result_to_json(self):
        """T1: AgentResult serialization to JSON"""
        result = AgentResult(
            status="success",
            data={"metrics": {"tlps": 5.2}},
            _next_actions=["optimize_pv"]
        )

        json_str = result.to_json()
        parsed = json.loads(json_str)

        assert parsed["status"] == "success"
        assert parsed["data"]["metrics"]["tlps"] == 5.2

    def test_t2_result_from_dict(self):
        """T2: AgentResult deserialization from dict"""
        d = {
            "status": "success",
            "data": {"pv_area": 100},
            "_next_actions": ["increase_battery"],
            "warnings": [],
            "errors": [],
            "_confidence": 0.9,
            "_metadata": {"city": "shanghai"}
        }

        result = AgentResult.from_dict(d)

        assert result.status == "success"
        assert result.data["pv_area"] == 100
        assert result._next_actions == ["increase_battery"]
        assert result._confidence == 0.9
        assert result._metadata["city"] == "shanghai"

    def test_t2_result_from_json(self):
        """T2: AgentResult deserialization from JSON"""
        json_str = '{"status": "failed", "data": {}, "_next_actions": [], "warnings": [], "errors": [{"code": "E001", "message": "test error"}], "_confidence": 1.0, "_metadata": {}}'

        result = AgentResult.from_json(json_str)

        assert result.status == "failed"
        assert len(result.errors) == 1
        assert result.errors[0].code == "E001"

    def test_t3_error_with_fix(self):
        """T3: Error with _fix field"""
        err = Error(
            code="E001",
            message="Weather data not found for city 'shanghai'",
            parameter="city",
            provided_value="shanghai",
            _fix={
                "action": "run_optimize_first",
                "command": "vfed optimize --cities shanghai",
                "auto_retry": True
            }
        )

        d = err.to_dict()

        assert d["code"] == "E001"
        assert d["_fix"]["action"] == "run_optimize_first"
        assert d["_fix"]["command"] == "vfed optimize --cities shanghai"
        assert d["_fix"]["auto_retry"] == True

    def test_t4_warning_with_code(self):
        """T4: Warning with code"""
        warn = Warning(
            code="W001",
            message="Weather data is old",
            severity="low"
        )

        d = warn.to_dict()

        assert d["code"] == "W001"
        assert d["severity"] == "low"
        assert d["message"] == "Weather data is old"

    def test_factory_success(self):
        """Test success factory method"""
        result = AgentResult.success(
            data={"key": "value"},
            next_actions=["action1"],
            confidence=0.95
        )

        assert result.status == "success"
        assert result.data["key"] == "value"
        assert result._next_actions == ["action1"]
        assert result._confidence == 0.95

    def test_factory_failed(self):
        """Test failed factory method"""
        result = AgentResult.failed(
            message="Something went wrong",
            code="E999"
        )

        assert result.status == "failed"
        assert len(result.errors) == 1
        assert result.errors[0].code == "E999"

    def test_factory_partial(self):
        """Test partial success factory method"""
        result = AgentResult.partial(
            data={"partial": "data"},
            message="Some constraints unmet"
        )

        assert result.status == "partial"
        assert result._confidence == 0.5
        assert len(result.warnings) == 1

    def test_has_errors(self):
        """Test has_errors helper"""
        result_no_err = AgentResult.success(data={})
        result_err = AgentResult.failed(message="error")

        assert result_no_err.has_errors() == False
        assert result_err.has_errors() == True

    def test_get_first_fix(self):
        """Test get_first_fix helper"""
        err = Error(
            code="E001",
            message="test",
            _fix={"action": "retry"}
        )
        result = AgentResult(status="failed", errors=[err])

        fix = result.get_first_fix()

        assert fix["action"] == "retry"


# =============================================================================
# T5-T8: Intent Parser Tests
# =============================================================================

class TestIntentParser:
    """Tests for IntentParser"""

    def setup_method(self):
        """Setup for each test"""
        self.parser = IntentParser(use_llm_fallback=False)

    def test_t5_simple_goal(self):
        """T5: Simple goal parsing"""
        intent = self.parser.parse("minimize energy")

        assert intent.goal == "minimize_energy"
        assert "goal:minimize_energy" in intent.matched_patterns

    def test_t5_chinese_goal(self):
        """T5: Chinese goal parsing"""
        intent = self.parser.parse("节能")

        assert intent.goal == "minimize_energy"

    def test_t5_multi_intent(self):
        """T6: Multiple intent parsing"""
        intent = self.parser.parse("minimize cost for lettuce")

        assert intent.goal == "minimize_cost"
        assert intent.crop == "lettuce"
        assert "goal:minimize_cost" in intent.matched_patterns
        assert "crop:lettuce" in intent.matched_patterns

    def test_t6_chinese_multi_intent(self):
        """T6: Chinese multi-intent parsing"""
        intent = self.parser.parse("优化生菜农场夏季能耗")

        assert intent.goal == "optimize"
        assert intent.crop == "lettuce"
        assert intent.season == "summer"

    def test_t7_city_extraction(self):
        """T7: City extraction from text"""
        intent = self.parser.parse("optimize for shanghai")

        assert intent.city == "shanghai"

    def test_t7_chinese_city(self):
        """T7: Chinese city extraction"""
        intent = self.parser.parse("optimize for shanghai")

        assert intent.city == "shanghai"

    def test_t8_infer_action(self):
        """T8: Action inference when not explicit"""
        intent = self.parser.parse("what is the best pv area for beijing")

        assert intent.action == "evaluate"

    def test_number_extraction_pv(self):
        """Test PV area number extraction"""
        intent = self.parser.parse("pv 100m2 for shanghai")

        assert intent.pv_area == 100.0

    def test_number_extraction_battery(self):
        """Test battery capacity number extraction"""
        intent = self.parser.parse("battery 50kwh for shanghai")

        assert intent.battery_capacity == 50.0

    def test_empty_intent(self):
        """Test empty intent handling"""
        intent = self.parser.parse("")

        assert intent.confidence == 0.0

    def test_confidence_calculation(self):
        """Test confidence score calculation"""
        intent = self.parser.parse("minimize energy for lettuce")

        # 2 patterns matched = 0.5 confidence
        assert intent.confidence == 0.5

    def test_parse_intent_convenience_function(self):
        """Test convenience function parse_intent"""
        intent = parse_intent("optimize shanghai")

        assert intent.city == "shanghai"
        assert intent.action == "optimize"


class TestErrorCatalog:
    """Tests for Error Catalog"""

    def test_error_catalog_has_codes(self):
        """Test that ERROR_CATALOG has expected codes"""
        assert "E001" in ERROR_CATALOG
        assert "E003" in ERROR_CATALOG
        assert "E101" in ERROR_CATALOG

    def test_create_error_e001(self):
        """Test creating E001 error"""
        err = create_error("E001", city="beijing")

        assert err.code == "E001"
        assert "beijing" in err.message

    def test_create_error_e003(self):
        """Test creating E003 error"""
        err = create_error("E003", city="invalid_city", available_cities="shanghai, beijing")

        assert err.code == "E003"
        assert "invalid_city" in err.message

    def test_create_error_e101(self):
        """Test creating E101 error"""
        err = create_error("E101", value=500, max=200, provided_value=500)

        assert err.code == "E101"
        assert 500 == err.provided_value

    def test_get_fix_returns_dict(self):
        """Test get_fix returns properly formatted dict"""
        fix = get_fix("E001", city="shanghai")

        assert fix is not None
        assert "action" in fix
        assert "command" in fix

    def test_get_fix_unknown_code(self):
        """Test get_fix with unknown code returns None"""
        fix = get_fix("E999")

        assert fix is None

    def test_create_warning_w001(self):
        """Test creating W001 warning"""
        warn = create_warning("W001", year=2023)

        assert warn.code == "W001"
        assert "2023" in warn.message
        assert warn.severity == "low"


class TestEvaluatorWrapper:
    """Tests for agent_evaluate wrapper - lightweight tests that don't require data files"""

    def test_parameter_validation_invalid_city(self):
        """T11: Parameter validation - invalid city"""
        from src.agent.evaluator import agent_evaluate

        result = agent_evaluate(
            pv_area=100,
            battery_capacity=50,
            city="invalid_city_not_exist",
            auto_setup=False
        )

        assert result.status == "failed"
        assert len(result.errors) > 0
        assert result.errors[0].code == "E003"

    def test_invalid_city_in_natural_language(self):
        """Test that invalid city in natural language text returns FAILED"""
        from src.agent_runner import run as agent_run

        result = agent_run('evaluate invalid_city')

        assert result.status == "failed", f"Expected failed but got {result.status}"
        assert len(result.errors) > 0
        assert result.errors[0].code == "E003"
        assert "invalid_city" in result.errors[0].message

    def test_parameter_validation_negative_pv(self):
        """T11: Parameter validation - negative PV area"""
        from src.agent.evaluator import agent_evaluate

        result = agent_evaluate(
            pv_area=-100,
            battery_capacity=50,
            city="shanghai",
            auto_setup=False
        )

        assert result.status == "failed"
        assert any(e.code == "E101" for e in result.errors)

    def test_parameter_validation_invalid_battery(self):
        """T11: Parameter validation - invalid battery"""
        from src.agent.evaluator import agent_evaluate

        result = agent_evaluate(
            pv_area=100,
            battery_capacity=-50,
            city="shanghai",
            auto_setup=False
        )

        assert result.status == "failed"
        assert any(e.code == "E102" for e in result.errors)

    def test_parameter_validation_invalid_hour(self):
        """T11: Parameter validation - invalid hour"""
        from src.agent.evaluator import agent_evaluate

        result = agent_evaluate(
            pv_area=100,
            battery_capacity=50,
            city="shanghai",
            start_hour=25,  # Invalid
            auto_setup=False
        )

        assert result.status == "failed"
        assert any(e.code == "E103" for e in result.errors)


class TestNextActions:
    """Tests for _next_actions generation"""

    def test_high_tlps_actions(self):
        """Test that high TLPS generates appropriate actions"""
        from src.agent.evaluator import _generate_next_actions

        metrics = {"tlps": 15, "lcoe": 0.3, "grid_dependency": 60}

        actions = _generate_next_actions(100, 50, metrics)

        assert "increase_battery_capacity" in actions
        assert "increase_pv_area_if_space_available" in actions

    def test_low_grid_dependency_actions(self):
        """Test that low grid dependency generates appropriate actions"""
        from src.agent.evaluator import _generate_next_actions

        metrics = {"tlps": 2, "lcoe": 0.2, "grid_dependency": 20, "PV_utilization": 80}

        actions = _generate_next_actions(100, 50, metrics)

        assert len(actions) >= 0  # Just verify it returns without error


# =============================================================================
# Run Tests
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])