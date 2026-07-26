"""
Layer 3: Numerical guardrails — DIV/0, CRF, transpiration fallback.

Tests that numerical edge cases produce errors (not silent wrong values).
"""
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from src.design.sweep import _crf


# ---------------------------------------------------------------------------
# 3.1  CRF — zero interest rate
# ---------------------------------------------------------------------------
class TestCRF:
    def test_zero_interest(self):
        """CRF(i=0, n) = 1/n."""
        assert _crf(0.0, 25.0) == pytest.approx(1.0 / 25, rel=0.01)

    def test_near_zero_interest(self):
        """CRF should not explode for tiny i."""
        crf = _crf(1e-10, 15.0)
        assert crf == pytest.approx(1.0 / 15, rel=1e-6)

    def test_normal_interest(self):
        """CRF(i=0.06, n=25) ≈ 0.0782."""
        crf = _crf(0.06, 25.0)
        assert crf == pytest.approx(0.0782, rel=1e-3)

    def test_one_year(self):
        """CRF for 1-year = 1 + i."""
        assert _crf(0.05, 1.0) == pytest.approx(1.05, rel=0.01)

    def test_negative_interest_returns_finite(self):
        """CRF with negative interest should still return a finite number."""
        crf = _crf(-0.01, 25.0)
        assert np.isfinite(crf)


# ---------------------------------------------------------------------------
# 3.2  kwh_per_kg — zero biomass guard
# ---------------------------------------------------------------------------
class TestKwhPerKg:
    def test_kwh_per_kg_finite(self, sim_609):
        """kwh_per_kg must be finite (not inf/nan)."""
        assert np.isfinite(sim_609["kwh_per_kg"]), \
            f"kwh_per_kg is {sim_609['kwh_per_kg']}"

    def test_kwh_per_kg_fresh_finite(self, sim_609):
        """kwh_per_kg_fresh must be finite."""
        assert np.isfinite(sim_609["kwh_per_kg_fresh"]), \
            f"kwh_per_kg_fresh is {sim_609['kwh_per_kg_fresh']}"

    def test_kwh_per_kg_ratio(self):
        """Dry / fresh should be roughly 20:1 (5% DM convention)."""
        from src.design.engine import DesignEngine
        from src.design.presets import preset_609

        p = preset_609()
        engine = DesignEngine()
        sim = engine.run(p)
        ratio = sim["kwh_per_kg"] / max(sim["kwh_per_kg_fresh"], 1e-9)
        assert ratio == pytest.approx(20.0, rel=0.05), \
            f"dry/fresh ratio = {ratio} (expected ~20)"


# ---------------------------------------------------------------------------
# 3.3  Transpiration — unknown method
# ---------------------------------------------------------------------------
def test_transpiration_unknown_method_returns_zero():
    """Unknown transpiration method should silently return 0.0 (current behaviour)."""
    from src.plants.transpiration import TranspirationModel

    tm = TranspirationModel(method="flute_serenade", area_m2=45.0)
    result = tm.step(T_z=22.0, RH_z=65.0, is_light=True, dt=600.0)
    assert result == 0.0
