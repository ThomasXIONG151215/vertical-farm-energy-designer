"""CO2 supplement M1: unit conversions.

Contract under test (proposal §2.1):
  * ppm (mole fraction) <-> mixing ratio (kg/kg) roundtrip, and ppm ->
    density (kg/m3) <-> ppm roundtrip, at 22/25 degC x 101.325/95 kPa,
    relative error < 1e-9;
  * mixing-ratio and density conversions are mutually consistent with the
    ideal-gas dry-air density (X = c * rho_ideal(T, P) exactly);
  * literature reference values from the proposal (800 ppm ~ 1.454 g/m3 at
    22 degC; 420 ppm ~ 0.763 g/m3; 800 ppm -> ~1.216e-3 kg/kg);
  * the respiration dry-matter -> CO2 mass ratio 44.01/30.03 ~ 1.465.
"""

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "vfed"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from vfed.devices.co2 import (
    DM_TO_CO2,
    G_PER_H_TO_KG_PER_S,
    M_AIR,
    M_CO2,
    mixing_ratio_to_ppm,
    ppm_to_density,
    ppm_to_mixing_ratio,
)

R_UNIVERSAL = 8.314462618  # J/(mol*K) (CODATA 2018)

_TP_GRID = [
    (22.0, 101.325),
    (25.0, 101.325),
    (22.0, 95.0),
    (25.0, 95.0),
]

_PPM_GRID = [30.0, 420.0, 800.0, 1200.0, 2000.0]


@pytest.mark.parametrize("T_c,P_kpa", _TP_GRID)
@pytest.mark.parametrize("ppm", _PPM_GRID)
class TestRoundtrips:
    def test_ppm_mixing_ratio_roundtrip(self, ppm, T_c, P_kpa):
        """ppm -> c -> ppm closes to < 1e-9 relative (temperature-free)."""
        c = ppm_to_mixing_ratio(ppm)
        assert c > 0.0
        back = mixing_ratio_to_ppm(c)
        assert abs(back - ppm) / ppm < 1e-9

    def test_ppm_density_roundtrip(self, ppm, T_c, P_kpa):
        """ppm -> X(T,P) -> (X, T, P) -> ppm closes to < 1e-9 relative."""
        X = ppm_to_density(ppm, T_c, P_kpa)
        assert X > 0.0
        # invert ppm_to_density analytically: X = ppm*1e-6*M/v_m
        v_m = 22.414 * (T_c + 273.15) / 273.15 * (101.325 / P_kpa)
        back = X * v_m / (1e-6 * M_CO2)
        assert abs(back - ppm) / ppm < 1e-9

    def test_mixing_ratio_density_consistency(self, ppm, T_c, P_kpa):
        """X/c == rho_dry_air on the SAME ideal-gas constant basis for
        every ppm (the two conversion families share one thermodynamic
        basis), and matches the CODATA-R dry-air density to within the
        22.414 L/mol rounding of the shared molar-volume constant."""
        c = ppm_to_mixing_ratio(ppm)
        X = ppm_to_density(ppm, T_c, P_kpa)
        rho = X / c  # kg dry air / m3, ppm-independent by construction
        # exact identity against the same 22.414 L/mol basis
        v_m = 22.414 * (T_c + 273.15) / 273.15 * (101.325 / P_kpa)  # L/mol
        assert rho == pytest.approx(M_AIR / v_m, rel=1e-12)
        # cross-check vs CODATA R (22.414 carries ~1.4e-6 rounding)
        rho_ideal = P_kpa * 1000.0 * (M_AIR / 1000.0) / (R_UNIVERSAL * (T_c + 273.15))
        assert abs(rho - rho_ideal) / rho_ideal < 1e-5


class TestReferenceValues:
    def test_proposal_reference_densities(self):
        """800 ppm ~ 1.454 g/m3 and 420 ppm ~ 0.763 g/m3 at 22 degC /
        101.325 kPa (proposal §2.1 reference numbers)."""
        assert ppm_to_density(800.0, 22.0) == pytest.approx(1.454e-3, rel=1e-3)
        assert ppm_to_density(420.0, 22.0) == pytest.approx(0.763e-3, rel=1e-3)

    def test_proposal_reference_mixing_ratio(self):
        """800 ppm -> ~1.216e-3 kg/kg mixing ratio (proposal §2.1)."""
        assert ppm_to_mixing_ratio(800.0) == pytest.approx(1.216e-3, rel=1e-3)

    def test_one_ppm_at_25c_reference(self):
        """1 ppm ~ 1.8 mg/m3 at 25 degC / 101.325 kPa (van Henten note)."""
        assert ppm_to_density(1.0, 25.0) == pytest.approx(1.8e-6, rel=5e-3)

    def test_gamma_mixing_ratio_form(self):
        """Growth c_Gamma 5.2e-5 kg/m3 -> ~4.3e-5 kg/kg via /rho_air (1.2):
        the step_co2 floor derivation documented in ode.py."""
        gamma_mass = 5.2e-5 / 1.2
        assert gamma_mass == pytest.approx(4.3e-5, rel=5e-2)
        # and it corresponds to roughly the 30 ppm compensation point
        assert 25.0 <= mixing_ratio_to_ppm(gamma_mass) <= 35.0


class TestMassRatios:
    def test_dm_to_co2_ratio(self):
        """44.01/30.03 ~ 1.465 (Thornley & Johnson 2000)."""
        assert DM_TO_CO2 == pytest.approx(44.01 / 30.03, rel=1e-12)
        assert DM_TO_CO2 == pytest.approx(1.465, abs=1e-3)

    def test_molar_masses(self):
        assert M_CO2 == 44.01
        assert M_AIR == 28.965

    def test_gh_to_kgs(self):
        """1 g/h = 2.778e-7 kg/s (proposal unit table); 200 g/h capacity."""
        assert G_PER_H_TO_KG_PER_S == pytest.approx(2.778e-7, rel=1e-3)
        assert 200.0 * G_PER_H_TO_KG_PER_S == pytest.approx(5.556e-5, rel=1e-3)
