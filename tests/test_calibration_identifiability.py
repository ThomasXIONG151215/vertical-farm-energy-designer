"""Identifiability rule engine over dataset capability signatures."""
from vfed.calibration import (AssessmentStatus, DataSignature,
                              ParameterLabel, analyze_signature,
                              CalibrationResult)


def test_bjaaf_like_signature_fully_identifiable():
    rep = analyze_signature(DataSignature.bjaaf_like())
    assert rep.find("c_pl_d").status is AssessmentStatus.IDENTIFIABLE
    assert rep.find("c_pl_d").label is ParameterLabel.ANCHORED
    assert rep.find("c_rad_phot").status is AssessmentStatus.IDENTIFIABLE
    assert rep.find("c_rad_phot").label is ParameterLabel.FITTED
    assert rep.find("rho").status is AssessmentStatus.IDENTIFIABLE


def test_uc_davis_like_signature_pending_adapter_and_degenerate():
    rep = analyze_signature(DataSignature.uc_davis_like())
    # canopy images exist but adapter B is not implemented
    assert rep.find("c_pl_d").status is AssessmentStatus.PENDING_ADAPTER
    # plant biomass without measured density -> 1/rho joins K_eff degeneracy
    assert rep.find("c_rad_phot").status is AssessmentStatus.DEGENERATE
    assert rep.find("rho").status is AssessmentStatus.DEGENERATE


def test_ppfd_recipe_with_density_is_conditional():
    sig = DataSignature(ppfd_recipe=True, plant_biomass=True, density=True)
    rep = analyze_signature(sig)
    assert rep.find("c_rad_phot").status is AssessmentStatus.CONDITIONAL
    assert rep.find("c_rad_phot").label is ParameterLabel.FITTED
    assert rep.find("rho").status is AssessmentStatus.IDENTIFIABLE


def test_measured_par_makes_efficiency_identifiable():
    sig = DataSignature(par_series=True, plant_biomass=True, density=True)
    rep = analyze_signature(sig)
    assert rep.find("c_rad_phot").status is AssessmentStatus.IDENTIFIABLE


def test_empty_signature_all_not_identifiable():
    rep = analyze_signature(DataSignature())
    for name in ("c_pl_d", "c_rad_phot", "rho"):
        assert rep.find(name).status is AssessmentStatus.NOT_IDENTIFIABLE


def test_result_markdown_carries_labels():
    r = CalibrationResult(dataset="synthetic")
    r.add_param("c_pl_d", 32.7, ParameterLabel.ANCHORED, "test note")
    r.add_param("c_rad_phot", 5.17e-9, ParameterLabel.FITTED)
    md = r.to_markdown()
    assert "直接锚定" in md and "拟合" in md
    assert "32.7" in md and "5.17e-09" in md
    assert "test note" in md
