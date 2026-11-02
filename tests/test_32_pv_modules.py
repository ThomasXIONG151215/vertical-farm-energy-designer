"""Wave 1 (Agent A): PV module library (G3), low-irradiance curve (G4),
per-module degradation (G13).

Scope of this file (numbering starts at 32 to avoid Wave-1 collisions):

* G3 — ``vfed/pvbes/modules.py`` registry resolves the five presets; every
  registry number is cross-checked against the reference-anchor YAMLs in
  ``reference/pvbes-validation/modules/`` (per readme.md, tests read the
  science values from there, never inline them); unknown names fail fast;
  default ``PVSystem`` construction is bit-identical to the legacy inline
  parameter set (cross-checked through ``PVConfig``, the config contract
  that mirrors the pre-G3 pv.py defaults); engine-style explicit
  construction stays equal; partial-reference modules fail fast.
* G4 — the identity curve (every current preset: anchor data inaccessible,
  see anchors/low_irradiance.yaml) reproduces the legacy MPP formula
  bit-exactly; a synthetic node table injected in-test drives the
  piecewise-linear interpolation, the exact (1000, 1.0) STC anchor and the
  200-600 W/m2 validation envelope [0.9, 1.05].
* G13 — degradation comes from the module spec with unchanged
  ``(1 - degradation) ** year`` semantics; year-t output equals year-0
  output times the exact factor, elementwise bit-identical.
"""

import dataclasses
import math
from pathlib import Path

import numpy as np
import pytest
import yaml

from vfed.design.project import PVConfig
from vfed.pvbes.modules import MODULES, ModuleSpec, resolve_module
from vfed.pvbes.pv import PVSystem

REF_MODULES = (
    Path(__file__).resolve().parents[1] / "reference" / "pvbes-validation" / "modules"
)

# The legacy pre-G3 PVSystem inline set, mirrored field-for-field by the
# PVConfig contract (project.py) — the honest source for "old pv.py values".
LEGACY_FIELDS = (
    "eta_pv",
    "area_to_power",
    "N_s",
    "I_sc_stc",
    "V_oc_stc",
    "I_mp_stc",
    "V_mp_stc",
    "gamma_pmp",
    "NOCT",
    "degradation",
)

NON_DEFAULT_MODULES = (
    "huasun_himalaya",
    "longi_himo9_670m",
    "microquanta_bipv",
    "onyx_asi_glass",
)

# 2026-11-02 datasheet entry: huasun (HSN-210-B132 DS730) and longi
# (Hi-MO 9 670 M) now carry complete SDM point sets; the remaining two
# are still anchor-pending and must fail fast on construction.
SDM_COMPLETE_NON_DEFAULT = ("huasun_himalaya", "longi_himo9_670m")
SDM_INCOMPLETE_MODULES = ("microquanta_bipv", "onyx_asi_glass")


def _ref_yaml(name: str) -> dict:
    path = REF_MODULES / f"{name}.yaml"
    assert path.is_file(), f"missing reference anchor file: {path}"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _synthetic_weather() -> dict:
    """Deterministic pseudo-weather spanning the curve's G range."""
    rng = np.random.default_rng(32)
    n = 240
    g_total = rng.uniform(0.0, 1200.0, n)
    return {
        "direct_radiation": g_total * 0.7,
        "diffuse_radiation": g_total * 0.3,
        "temperature_2m": rng.uniform(-5.0, 40.0, n),
    }


# ---------------------------------------------------------------------------
# G3: registry
# ---------------------------------------------------------------------------
class TestModuleRegistry:
    def test_registry_has_exactly_the_five_presets(self):
        assert set(MODULES) == {
            "jinko_jkm580n",
            *NON_DEFAULT_MODULES,
        }

    def test_resolve_module_returns_registry_entries(self):
        for name, spec in MODULES.items():
            assert resolve_module(name) is spec
            assert isinstance(spec, ModuleSpec)

    def test_all_registered_numeric_fields_finite(self):
        for name, spec in MODULES.items():
            for f in dataclasses.fields(ModuleSpec):
                v = getattr(spec, f.name)
                if isinstance(v, tuple):  # eta_rel_nodes node table
                    for g, e in v:
                        assert math.isfinite(g) and math.isfinite(e), (name, f.name)
                elif isinstance(v, (int, float)) and not isinstance(v, bool):
                    assert math.isfinite(v), (name, f.name)

    def test_unknown_module_fails_fast_ascii(self):
        with pytest.raises(ValueError) as ei:
            resolve_module("no_such_module")
        msg = str(ei.value)
        assert msg.isascii()
        for known in MODULES:
            assert known in msg

    def test_jinko_spec_equals_legacy_pvconfig_field_by_field(self):
        spec = resolve_module("jinko_jkm580n")
        cfg = PVConfig()
        for f in LEGACY_FIELDS:
            assert getattr(spec, f) == getattr(cfg, f), f


# ---------------------------------------------------------------------------
# G3: registry numbers transcribed from the reference YAMLs
# ---------------------------------------------------------------------------
class TestRegistryMatchesReferenceYaml:
    @pytest.mark.parametrize("name", sorted(MODULES))
    def test_entry_matches_reference_yaml(self, name):
        y = _ref_yaml(name)
        spec = MODULES[name]
        legacy_cfg = PVConfig()
        is_legacy = name == "jinko_jkm580n"

        direct = [
            ("i_sc_a", "I_sc_stc"),
            ("v_oc_v", "V_oc_stc"),
            ("i_mp_a", "I_mp_stc"),
            ("v_mp_v", "V_mp_stc"),
            ("n_s", "N_s"),
            ("gamma_pmp_per_kelvin", "gamma_pmp"),
            ("eta_stc", "eta_pv"),
        ]
        for yk, sk in direct:
            yv = y[yk]
            sv = getattr(spec, sk)
            if yv is None:
                if not is_legacy:
                    # yaml null -> spec None (never fabricated)
                    assert sv is None, (name, sk)
            else:
                assert sv == pytest.approx(yv, rel=1e-12), (name, sk)

        # degradation: yaml publishes %/yr, the spec carries the fraction
        if y["degradation_annual_pct"] is None:
            if is_legacy:
                # legacy VFED modeling default (yaml null), NOT a datasheet no.
                assert spec.degradation == legacy_cfg.degradation
            else:
                assert spec.degradation is None
        else:
            assert spec.degradation == pytest.approx(
                y["degradation_annual_pct"] / 100.0, rel=1e-12
            )

        # area_to_power: readme-permitted pure arithmetic.  Where area and
        # p_mp are published: m2 / kWp.  Otherwise the STC identity
        # 1/eta_stc (eta_pv = P/(G*area) at STC implies area_to_power =
        # 1/eta for every kWp); the legacy preset keeps the modeling value.
        if y["area_m2"] is not None and y["p_mp_w"] is not None:
            expected = y["area_m2"] / (y["p_mp_w"] / 1000.0)
            assert spec.area_to_power == pytest.approx(expected, rel=1e-9)
        elif is_legacy:
            assert spec.area_to_power == legacy_cfg.area_to_power
            assert spec.eta_pv == legacy_cfg.eta_pv
        else:
            assert spec.area_to_power == pytest.approx(1.0 / y["eta_stc"], rel=1e-9)

        # NOCT: datasheet value where the yaml publishes one (noct_c,
        # e.g. huasun 44 +/-2 C); otherwise the VFED modeling default
        # carried by the legacy PVConfig.
        if y.get("noct_c") is not None:
            assert spec.NOCT == pytest.approx(y["noct_c"], rel=1e-12), name
        else:
            assert spec.NOCT == legacy_cfg.NOCT
        # G4: datasheet-derived node tables (huasun / longi, generated
        # offline by scripts/generate_eta_rel.py) mirror the yaml; null or
        # absent yaml field -> identity curve (spec None).
        y_nodes = y.get("eta_rel_nodes")
        if y_nodes is None:
            assert spec.eta_rel_nodes is None, name
        else:
            assert spec.eta_rel_nodes is not None, name
            assert tuple(map(tuple, y_nodes)) == tuple(spec.eta_rel_nodes), name
        # G5 reserved field: spec mirrors the yaml (datasheet bifaciality
        # for huasun 0.90 / longi 0.75; null = not published).
        y_bif = y["bifaciality"]
        if y_bif is None:
            assert spec.bifaciality is None
        else:
            assert spec.bifaciality == pytest.approx(y_bif, rel=1e-12), name


# ---------------------------------------------------------------------------
# G3: PVSystem construction compatibility + fail-fast
# ---------------------------------------------------------------------------
class TestPVSystemModuleResolution:
    def test_default_construction_bit_identical_to_legacy(self):
        pv = PVSystem()
        cfg = PVConfig()
        for f in LEGACY_FIELDS:
            assert getattr(pv, f) == getattr(cfg, f), f
        assert pv.module == "jinko_jkm580n"
        assert pv.eta_rel_nodes is None

    def test_engine_style_explicit_constructor_equals_default(self):
        """engine.py / sweep.py pass every legacy field explicitly; that
        call style must produce exactly the default-constructed object."""
        cfg = PVConfig()
        engine_style = PVSystem(
            eta_pv=cfg.eta_pv,
            area_to_power=cfg.area_to_power,
            N_s=cfg.N_s,
            I_sc_stc=cfg.I_sc_stc,
            V_oc_stc=cfg.V_oc_stc,
            I_mp_stc=cfg.I_mp_stc,
            V_mp_stc=cfg.V_mp_stc,
            alpha_sc=cfg.alpha_sc,
            beta_voc=cfg.beta_voc,
            gamma_pmp=cfg.gamma_pmp,
            NOCT=cfg.NOCT,
            eta_inv=cfg.eta_inv,
            degradation=cfg.degradation,
            eta_system=cfg.eta_system,
        )
        assert engine_style == PVSystem()

    def test_explicit_fields_beat_module_spec(self):
        pv = PVSystem(V_mp_stc=44.0, degradation=0.005)
        cfg = PVConfig()
        assert pv.V_mp_stc == 44.0
        assert pv.degradation == 0.005
        # untouched fields still resolve from the default module spec
        assert pv.I_mp_stc == cfg.I_mp_stc
        assert pv.gamma_pmp == cfg.gamma_pmp

    def test_explicit_default_module_name_bit_identical_output(self):
        w = _synthetic_weather()
        a = PVSystem().calculate_pv_output(w, 100.0)
        b = PVSystem(module="jinko_jkm580n").calculate_pv_output(w, 100.0)
        assert np.array_equal(a, b)

    @pytest.mark.parametrize("name", SDM_INCOMPLETE_MODULES)
    def test_partial_reference_modules_fail_fast(self, name):
        """Modules whose reference YAML still has null STC electrical
        points (microquanta make-to-order, onyx power-density-only) must
        fail fast on construction instead of silently mixing leftover
        values.  Update alongside the YAMLs when the missing anchors
        land."""
        with pytest.raises(ValueError) as ei:
            PVSystem(module=name)
        msg = str(ei.value)
        assert msg.isascii()
        assert name in msg

    @pytest.mark.parametrize("name", SDM_COMPLETE_NON_DEFAULT)
    def test_complete_reference_modules_construct_and_produce(self, name):
        """2026-11-02 datasheet entry: huasun / longi presets now carry a
        full SDM point set and must construct and produce finite,
        non-negative output over synthetic weather."""
        pv = PVSystem(module=name)
        spec = resolve_module(name)
        assert pv.I_mp_stc == spec.I_mp_stc
        assert pv.V_mp_stc == spec.V_mp_stc
        out = pv.calculate_pv_output(_synthetic_weather(), 100.0)
        assert np.all(np.isfinite(out))
        assert np.all(out >= 0.0)
        assert out.sum() > 0.0


# ---------------------------------------------------------------------------
# G3: physics sanity of the registry (eta_pv <-> area_to_power, fill factor)
# ---------------------------------------------------------------------------
class TestRegistryPhysicsSanity:
    @pytest.mark.parametrize("name", sorted(MODULES))
    def test_eta_pv_matches_area_to_power_identity(self, name):
        """At STC a module of power P occupies area_to_power*(P/1000) m^2
        and receives 1000 W/m2, so eta = P/(1000*area_to_power*P/1000)
        = 1/area_to_power exactly; eta_pv must agree within 0.5 %."""
        spec = MODULES[name]
        implied = 1.0 / spec.area_to_power
        assert abs(spec.eta_pv - implied) / implied < 0.005

    def test_fill_factor_within_band(self):
        checked = 0
        for name, spec in MODULES.items():
            vals = (spec.V_mp_stc, spec.I_mp_stc, spec.V_oc_stc, spec.I_sc_stc)
            if any(v is None for v in vals):
                continue  # partial STC data: FF not computable
            ff = (spec.V_mp_stc * spec.I_mp_stc) / (spec.V_oc_stc * spec.I_sc_stc)
            assert 0.6 <= ff <= 0.9, (name, ff)
            checked += 1
        assert checked >= 1  # the jinko baseline at minimum


# ---------------------------------------------------------------------------
# G4: low-irradiance relative efficiency
# ---------------------------------------------------------------------------
_SYNTH_NODES = ((0.0, 1.0), (500.0, 0.95), (1000.0, 1.0))


class TestG4IdentityCurve:
    def test_identity_curve_bit_exact_legacy_formula(self):
        """eta_rel_nodes=None (every current preset) reproduces the pre-G4
        MPP formula bit-for-bit (formula replicated from the instance's own
        resolved parameters)."""
        pv = PVSystem()
        w = _synthetic_weather()
        G = np.clip(
            np.asarray(w["direct_radiation"], dtype=float)
            + np.asarray(w["diffuse_radiation"], dtype=float),
            0.0,
            None,
        )
        T_cell = pv.cell_temperature(G, np.asarray(w["temperature_2m"], dtype=float))
        I_mp = np.clip(pv.I_mp_stc * (G / 1000.0), 0.0, None)
        k_v = np.clip(
            (pv.V_mp_stc / pv.V_oc_stc)
            * (1.0 + 0.03 * np.log(np.maximum(G, 1.0) / 1000.0)),
            0.5,
            0.95,
        )
        V_mp = pv.V_oc_stc * k_v
        p_temp = np.clip(1.0 + pv.gamma_pmp * (T_cell - pv.T_stc), 0.0, None)
        legacy = I_mp * V_mp * p_temp
        assert np.array_equal(pv._sd_mpp(G, T_cell), legacy)

    def test_default_curve_is_identity_everywhere(self):
        pv = PVSystem()
        assert pv.eta_rel_nodes is None
        G = np.array([0.0, 1.0, 200.0, 400.0, 600.0, 999.0, 1000.0, 1500.0])
        eta = pv._eta_rel(G)
        assert np.array_equal(eta, np.ones_like(G))
        assert eta[-2] == 1.0  # eta_rel(1000) == 1 exactly


class TestG4SyntheticCurve:
    def test_interpolation_follows_node_table(self):
        pv = PVSystem(eta_rel_nodes=_SYNTH_NODES)
        G = np.array([0.0, 250.0, 500.0, 750.0, 1000.0])
        eta = pv._eta_rel(G)
        xs = tuple(g for g, _ in _SYNTH_NODES)
        ys = tuple(e for _, e in _SYNTH_NODES)
        assert np.array_equal(eta, np.interp(G, xs, ys))
        assert eta[2] == 0.95  # exact node hit at 500 W/m2
        assert eta[4] == 1.0  # exact STC anchor at 1000 W/m2
        # midpoint sanity: 250 W/m2 lies halfway between 1.0 and 0.95
        assert eta[1] == pytest.approx(0.975)

    def test_curve_scales_mpp_exactly(self):
        plain = PVSystem()
        curved = PVSystem(eta_rel_nodes=_SYNTH_NODES)
        w = _synthetic_weather()
        G = np.clip(
            np.asarray(w["direct_radiation"], dtype=float)
            + np.asarray(w["diffuse_radiation"], dtype=float),
            0.0,
            None,
        )
        T_cell = plain.cell_temperature(G, np.asarray(w["temperature_2m"], dtype=float))
        expected = plain._sd_mpp(G, T_cell) * curved._eta_rel(G)
        assert np.array_equal(curved._sd_mpp(G, T_cell), expected)

    def test_curve_stays_in_validation_envelope(self):
        """The 200-600 W/m2 band must stay inside eta in [0.9, 1.05] for a
        plausible synthetic curve (validation envelope, not a default)."""
        nodes = (
            (0.0, 1.0),
            (200.0, 1.02),
            (400.0, 0.97),
            (600.0, 1.01),
            (1000.0, 1.0),
        )
        pv = PVSystem(eta_rel_nodes=nodes)
        band = pv._eta_rel(np.linspace(200.0, 600.0, 41))
        assert np.all(band >= 0.9)
        assert np.all(band <= 1.05)
        assert pv._eta_rel(np.array([1000.0]))[0] == 1.0


class TestG4DatasheetCurves:
    """Offline-generated eta_rel tables (scripts/generate_eta_rel.py,
    2026-11-02) now ship with two presets.  The default jinko baseline
    stays identity (golden zero-drift contract)."""

    CURVED = ("huasun_himalaya", "longi_himo9_670m")

    def test_default_module_keeps_identity_curve(self):
        assert resolve_module("jinko_jkm580n").eta_rel_nodes is None

    def test_curved_presets_pass_gate_band(self):
        for name in self.CURVED:
            nodes = resolve_module(name).eta_rel_nodes
            assert nodes is not None, name
            eta_200_600 = [e for g, e in nodes if 200.0 <= g <= 600.0]
            assert 0.9 <= min(eta_200_600), name
            assert max(eta_200_600) <= 1.05, name
            assert nodes[-1] == (1000.0, 1.0), name  # STC anchor

    def test_curve_scales_module_mpp_at_low_g(self):
        for name in self.CURVED:
            spec = resolve_module(name)
            curved = PVSystem(module=name)
            plain = PVSystem(module=name, eta_rel_nodes=None)
            G = np.array([200.0, 1000.0])
            T = np.array([25.0, 25.0])
            ratio = curved._sd_mpp(G, T) / plain._sd_mpp(G, T)
            assert ratio[0] == pytest.approx(
                spec.eta_rel_nodes[1][1], rel=1e-9
            ), name  # 200 W/m2 node value
            assert ratio[1] == pytest.approx(1.0, abs=1e-12), name


class TestG4NodeValidation:
    _BASE_KWARGS = {"eta_pv": 0.23, "area_to_power": 4.3}

    def test_nodes_require_stc_anchor(self):
        nodes = ((0.0, 1.0), (500.0, 0.95))
        with pytest.raises(ValueError, match="anchor"):
            ModuleSpec(**self._BASE_KWARGS, eta_rel_nodes=nodes)
        with pytest.raises(ValueError, match="anchor"):
            PVSystem(eta_rel_nodes=nodes)

    def test_nodes_must_be_strictly_increasing(self):
        nodes = ((0.0, 1.0), (500.0, 0.95), (500.0, 0.9), (1000.0, 1.0))
        with pytest.raises(ValueError, match="increasing"):
            ModuleSpec(**self._BASE_KWARGS, eta_rel_nodes=nodes)
        with pytest.raises(ValueError, match="increasing"):
            PVSystem(eta_rel_nodes=nodes)

    def test_nodes_eta_must_be_positive(self):
        nodes = ((0.0, 1.0), (500.0, 0.0), (1000.0, 1.0))
        with pytest.raises(ValueError, match="eta"):
            ModuleSpec(**self._BASE_KWARGS, eta_rel_nodes=nodes)
        with pytest.raises(ValueError, match="eta"):
            PVSystem(eta_rel_nodes=nodes)

    def test_nonfinite_spec_numbers_rejected(self):
        base = resolve_module("jinko_jkm580n")
        with pytest.raises(ValueError, match="finite"):
            dataclasses.replace(base, eta_pv=float("nan"))
        with pytest.raises(ValueError, match="finite"):
            dataclasses.replace(base, V_oc_stc=float("inf"))

    def test_complete_stc_set_requires_degradation(self):
        base = resolve_module("jinko_jkm580n")
        with pytest.raises(ValueError, match="degradation"):
            dataclasses.replace(base, degradation=None)

    def test_nonpositive_eta_or_area_rejected(self):
        base = resolve_module("jinko_jkm580n")
        with pytest.raises(ValueError, match="eta_pv"):
            dataclasses.replace(base, eta_pv=0.0)
        with pytest.raises(ValueError, match="area_to_power"):
            dataclasses.replace(base, area_to_power=-1.0)


# ---------------------------------------------------------------------------
# G13: per-module degradation
# ---------------------------------------------------------------------------
class TestG13PerModuleDegradation:
    def test_jinko_degradation_factor_exact(self):
        """deg = 0.004 (legacy), t = 13: expected computed from the math
        expression (1-deg)**t, never a hard-coded long decimal."""
        spec = resolve_module("jinko_jkm580n")
        cfg = PVConfig()
        assert spec.degradation == cfg.degradation
        t = 13
        assert (1.0 - spec.degradation) ** t == (1.0 - cfg.degradation) ** t

    def test_annual_output_exact_exponential_bit_drift_free(self):
        """year-t output == year-0 output * (1-deg)**t elementwise, exactly
        (the pre-G13 code applied the same single multiplication)."""
        pv = PVSystem()
        w = _synthetic_weather()
        base = pv.calculate_pv_output(w, 100.0, year=0)
        for t in (1, 5, 13):
            out = pv.calculate_pv_output(w, 100.0, year=t)
            factor = (1.0 - pv.degradation) ** t
            assert np.array_equal(out, base * factor)
            assert np.all(out <= base)

    def test_spec_degradation_resolves_and_explicit_wins(self):
        # default: resolved from the jinko spec (legacy value)
        assert PVSystem().degradation == resolve_module("jinko_jkm580n").degradation
        # explicit value wins over the spec (compat contract)
        assert PVSystem(degradation=0.02).degradation == 0.02
