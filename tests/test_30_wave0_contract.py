"""Wave 0 contract tests: G1-G13 program config fields (2026-11).

Layer 0 of the two-gate validation system:

* the new dataclass fields exist and their defaults reproduce the legacy
  behavior bit-for-bit (default = the hard-coded value the code uses
  today);
* a legacy YAML (no new keys) loads unchanged;
* out-of-band values fail fast at load time;
* Wave 1 wired the fields end-to-end (G2 weather_bridge, G3 module
  library, G10/G11 battery, G12 grid), so non-default values are ACCEPTED
  and validated: albedo band, transposition enum, module resolution with
  fail-fast on incomplete STC specs, positive power_kw, chemistry enum,
  non-negative export limit and demand charge.
"""

import pytest

from vfed.design.presets import preset_609
from vfed.design.project import (
    HARD_LIMITS,
    PARAM_PATH_MAP,
    PARAM_TOPLEVEL_MAP,
    BatteryConfig,
    DesignProject,
    PVConfig,
    SiteConfig,
    TariffConfig,
)


# ---------------------------------------------------------------------------
# Layer 0a: the fields exist with legacy-preserving defaults
# ---------------------------------------------------------------------------


class TestContractDefaults:
    def test_site_defaults_are_legacy_values(self):
        s = SiteConfig()
        assert s.albedo == 0.2  # = the value hard-coded in add_poa today
        assert s.transposition == "isotropic"  # = the only sky model today

    def test_pv_default_module_names_legacy_parameter_set(self):
        assert PVConfig().module == "jinko_jkm580n"

    def test_battery_defaults(self):
        b = BatteryConfig()
        assert b.power_kw is None  # None = legacy c_rate x E_now limit
        assert b.chemistry == "legacy"  # linear-cycle fade only

    def test_tariff_defaults(self):
        t = TariffConfig()
        assert t.export_limit_kw is None  # None = unlimited (legacy)
        assert t.demand_charge_per_kw is None  # None = off (legacy)

    def test_albedo_registered_in_hard_limit_tables(self):
        assert "albedo" in HARD_LIMITS
        assert HARD_LIMITS["albedo"] == (0, 1)
        assert PARAM_PATH_MAP.get("albedo") == ("site", "albedo")
        # the unified consistency invariant (same assertion family as
        # test_17) still holds with the new entry
        assert set(PARAM_PATH_MAP) | set(PARAM_TOPLEVEL_MAP) == set(HARD_LIMITS)


# ---------------------------------------------------------------------------
# Layer 0b: legacy YAML round-trip is untouched
# ---------------------------------------------------------------------------


def _preset_dict():
    return preset_609().to_dict()


class TestLegacyRoundTrip:
    def test_preset_to_dict_round_trip_keeps_defaults(self):
        p = DesignProject.from_dict(_preset_dict())
        assert p.site.albedo == 0.2
        assert p.site.transposition == "isotropic"
        assert p.pv.module == "jinko_jkm580n"
        assert p.battery.power_kw is None
        assert p.battery.chemistry == "legacy"
        assert p.tariff.export_limit_kw is None
        assert p.tariff.demand_charge_per_kw is None

    def test_yaml_without_new_keys_loads_unchanged(self):
        """A pre-Wave-0 YAML file (no new keys) must load exactly as before."""
        d = _preset_dict()
        d["site"].pop("albedo", None)
        d["site"].pop("transposition", None)
        d["pv"].pop("module", None)
        d["battery"].pop("power_kw", None)
        d["battery"].pop("chemistry", None)
        d["tariff"].pop("export_limit_kw", None)
        d["tariff"].pop("demand_charge_per_kw", None)
        p = DesignProject.from_dict(d)
        # absent keys fall back to the legacy defaults
        assert p.site.albedo == 0.2
        assert p.site.transposition == "isotropic"
        assert p.pv.module == "jinko_jkm580n"
        assert p.battery.power_kw is None
        assert p.battery.chemistry == "legacy"
        assert p.tariff.export_limit_kw is None
        assert p.tariff.demand_charge_per_kw is None


# ---------------------------------------------------------------------------
# Layer 0c: wired non-default values load; bad values fail fast
# ---------------------------------------------------------------------------


def _load_with(section, key, value):
    d = _preset_dict()
    d[section][key] = value
    return DesignProject.from_dict(d)


class TestWiredNonDefaultValues:
    def test_albedo_non_default_accepted(self):
        p = _load_with("site", "albedo", 0.15)
        assert p.site.albedo == 0.15

    def test_albedo_out_of_band_rejected_as_hard_limit(self):
        with pytest.raises(ValueError, match="hard limit"):
            _load_with("site", "albedo", 1.5)

    def test_transposition_hay_davies_accepted(self):
        p = _load_with("site", "transposition", "hay_davies")
        assert p.site.transposition == "hay_davies"

    def test_transposition_unknown_model_rejected(self):
        with pytest.raises(ValueError, match="site.transposition must be one of"):
            _load_with("site", "transposition", "perez")

    def test_module_unknown_name_rejected(self):
        with pytest.raises(ValueError, match="unknown PV module"):
            _load_with("pv", "module", "canadian_solar_600w")

    def test_module_incomplete_spec_fails_fast(self):
        # A user YAML that names a module without STC points (realistic
        # hand-written YAML; presets carry no pv section at all) must fail
        # fast instead of mixing in the legacy jinko defaults.
        # 2026-11-02: huasun/longi presets are datasheet-complete now, so
        # microquanta (make-to-order, no published points) is the
        # remaining incomplete case.
        d = _preset_dict()
        d["pv"] = {"module": "microquanta_bipv"}
        with pytest.raises(ValueError, match="refusing to mix"):
            DesignProject.from_dict(d)

    def test_module_complete_override_combination_accepted(self):
        # Explicit user-supplied STC points override the huasun spec;
        # the remaining spec-sourced fields materialize (compared against
        # the library, not inline numbers), user-supplied points win.
        from vfed.pvbes.modules import resolve_module

        spec = resolve_module("huasun_himalaya")
        d = _preset_dict()
        d["pv"] = {
            "module": "huasun_himalaya",
            "I_mp_stc": 18.63,
            "V_mp_stc": 41.38,
        }
        p = DesignProject.from_dict(d)
        assert p.pv.module == "huasun_himalaya"
        assert p.pv.gamma_pmp == spec.gamma_pmp
        assert p.pv.eta_pv == spec.eta_pv
        assert p.pv.area_to_power == spec.area_to_power
        assert p.pv.I_sc_stc == spec.I_sc_stc
        assert p.pv.V_oc_stc == spec.V_oc_stc
        assert p.pv.I_mp_stc == 18.63  # explicit user value wins
        assert p.pv.V_mp_stc == 41.38

    def test_module_datasheet_complete_preset_materializes_all_points(self):
        # 2026-11-02 datasheet entry: naming the now-complete huasun
        # preset with NO other pv keys materializes the full SDM point
        # set from the library (no refusal, no jinko leftovers).
        from vfed.pvbes.modules import resolve_module

        spec = resolve_module("huasun_himalaya")
        d = _preset_dict()
        d["pv"] = {"module": "huasun_himalaya"}
        p = DesignProject.from_dict(d)
        for f in (
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
        ):
            assert getattr(p.pv, f) == getattr(spec, f), f

    def test_module_swap_in_full_round_trip_dump_keeps_explicit_values(self):
        # to_dict() emits the full electrical field set as explicit values,
        # so swapping ONLY the module key in a round-trip dump keeps those
        # values (explicit wins -- same semantic as engine construction).
        # This documents the boundary: materialization fills only ABSENT
        # fields, it never overrides present ones.
        d = _preset_dict()
        d["pv"]["module"] = "huasun_himalaya"
        p = DesignProject.from_dict(d)  # must not raise: all points present
        assert p.pv.module == "huasun_himalaya"
        assert p.pv.eta_pv == PVConfig().eta_pv  # explicit dump value kept

    def test_power_kw_accepted(self):
        p = _load_with("battery", "power_kw", 30.0)
        assert p.battery.power_kw == 30.0

    def test_power_kw_must_be_positive(self):
        with pytest.raises(ValueError, match="positive number"):
            _load_with("battery", "power_kw", -5.0)

    def test_chemistry_lfp_accepted(self):
        p = _load_with("battery", "chemistry", "lfp")
        assert p.battery.chemistry == "lfp"

    def test_chemistry_unknown_rejected(self):
        with pytest.raises(ValueError, match="battery.chemistry must be one of"):
            _load_with("battery", "chemistry", "lead_acid")

    def test_export_limit_accepted(self):
        p = _load_with("tariff", "export_limit_kw", 20.0)
        assert p.tariff.export_limit_kw == 20.0

    def test_export_limit_must_be_non_negative(self):
        with pytest.raises(ValueError, match="non-negative"):
            _load_with("tariff", "export_limit_kw", -1.0)

    def test_demand_charge_accepted(self):
        p = _load_with("tariff", "demand_charge_per_kw", 12.0)
        assert p.tariff.demand_charge_per_kw == 12.0

    def test_demand_charge_must_be_non_negative(self):
        with pytest.raises(ValueError, match="non-negative"):
            _load_with("tariff", "demand_charge_per_kw", -3.0)

    def test_demand_charge_zero_is_the_legacy_off_state(self):
        # explicit 0.0 = off = legacy behavior -> accepted
        p = _load_with("tariff", "demand_charge_per_kw", 0.0)
        assert p.tariff.demand_charge_per_kw == 0.0
