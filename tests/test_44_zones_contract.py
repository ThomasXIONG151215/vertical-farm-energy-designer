"""Zones override-delta contract (multi-room v1, step 2).

``DesignProject`` gained a ``zones`` mapping: zone_id -> {section ->
{field: value}}.  Each zone is one room that writes ONLY the fields
differing from the global project; sections are restricted to
ZONE_OVERRIDABLE and merging is field-level
(``{**global_section, **delta_section}``).  A project WITHOUT a ``zones``
key must behave bitwise as before (zero drift).
"""

import copy

import pytest

from vfed.design.project import (
    DesignProject,
    ZONE_OVERRIDABLE,
    ZONE_RESERVED_IDS,
)
from vfed.design.presets import preset_609


def _base_dict() -> dict:
    """A valid, fully-materialised project dict (zero-drift oracle base)."""
    return preset_609().to_dict()


# ── zero drift: no zones key written ───────────────────────────────────


class TestNoZonesZeroDrift:
    def test_default_project_omits_zones_key(self):
        assert "zones" not in DesignProject().to_dict()

    def test_preset_omits_zones_key_and_field_is_empty(self):
        p = preset_609()
        assert p.zones == {}
        assert "zones" not in p.to_dict()

    def test_roundtrip_without_zones_is_bitwise_identical(self):
        d1 = _base_dict()
        p = DesignProject.from_dict(d1)
        assert p.zones == {}
        assert p.to_dict() == d1

    def test_empty_zones_dict_roundtrips_to_no_key(self):
        d = _base_dict()
        d["zones"] = {}
        p = DesignProject.from_dict(d)
        assert p.zones == {}
        assert "zones" not in p.to_dict()
        assert p.to_dict() == _base_dict()


# ── basic merge semantics ──────────────────────────────────────────────


class TestZoneViewMerge:
    def test_override_merges_field_level_and_leaves_rest_global(self):
        d = _base_dict()
        d["zones"] = {
            "nursery": {
                "led": {"ppfd_target": 200},
                "setpoints": {"T_light": 20},
            }
        }
        p = DesignProject.from_dict(d)
        view = p.zone_view("nursery")
        assert view["led"]["ppfd_target"] == 200
        # untouched led fields keep the global values
        global_led = _base_dict()["led"]
        for k, v in global_led.items():
            if k != "ppfd_target":
                assert view["led"][k] == v
        assert view["setpoints"]["T_light"] == 20
        # non-overridden sections are the global sections verbatim
        assert view["hvac"] == _base_dict()["hvac"]
        assert view["tariff"] == _base_dict()["tariff"]

    def test_zone_views_returns_all_zones(self):
        d = _base_dict()
        d["zones"] = {
            "nursery": {"led": {"ppfd_target": 200}},
            "room_b": {"envelope": {"ach": 0.5}},
        }
        p = DesignProject.from_dict(d)
        views = p.zone_views()
        assert set(views) == {"nursery", "room_b"}
        assert views["nursery"]["led"]["ppfd_target"] == 200
        assert views["room_b"]["envelope"]["ach"] == 0.5

    def test_envelope_override_takes_effect(self):
        d = _base_dict()
        d["zones"] = {"room_b": {"envelope": {"ach": 0.5}}}
        p = DesignProject.from_dict(d)
        view = p.zone_view("room_b")
        assert view["envelope"]["ach"] == 0.5
        for k, v in _base_dict()["envelope"].items():
            if k != "ach":
                assert view["envelope"][k] == v

    def test_unknown_zone_id_raises(self):
        p = DesignProject.from_dict(_base_dict())
        with pytest.raises(ValueError, match="unknown zone id 'nope'"):
            p.zone_view("nope")


# ── round-trip with zones ──────────────────────────────────────────────


class TestZonesRoundTrip:
    def test_zones_survive_roundtrip_verbatim(self):
        d = _base_dict()
        zones = {
            "nursery": {"led": {"ppfd_target": 200}, "setpoints": {"T_light": 20}},
            "room_b": {"envelope": {"ach": 0.5}},
        }
        d["zones"] = copy.deepcopy(zones)
        p = DesignProject.from_dict(d)
        assert p.to_dict() == d  # full dict, zones included, bitwise
        assert p.to_dict()["zones"] == zones

    def test_view_isolation_mutating_view_never_touches_project(self):
        d = _base_dict()
        d["zones"] = {"nursery": {"led": {"ppfd_target": 200}}}
        p = DesignProject.from_dict(d)
        before = p.to_dict()
        view = p.zone_view("nursery")
        view["led"]["ppfd_target"] = 9999
        view["hvac"]["cop_mode"] = "sabotage"
        view["zones"] = {"evil": {"led": {}}}
        assert p.to_dict() == before
        assert p.zones == {"nursery": {"led": {"ppfd_target": 200}}}


# ── rejection paths ────────────────────────────────────────────────────


class TestZoneRejections:
    def test_non_overridable_section_rejected(self):
        d = _base_dict()
        d["zones"] = {"a": {"tariff": {"export_price": 0.9}}}
        with pytest.raises(ValueError, match="zones.a") as ei:
            DesignProject.from_dict(d)
        assert "tariff" in str(ei.value)
        for sec in ZONE_OVERRIDABLE:
            assert sec in str(ei.value)  # allowed set is listed

    def test_bad_field_rejected_with_zone_context(self):
        d = _base_dict()
        d["zones"] = {"a": {"led": {"no_such_field": 1}}}
        with pytest.raises(ValueError, match="zones.a"):
            DesignProject.from_dict(d)
        with pytest.raises(ValueError, match="no_such_field"):
            DesignProject.from_dict(d)

    def test_hard_limit_enforced_through_zone_view(self):
        d = _base_dict()
        d["zones"] = {"a": {"led": {"ppfd_target": 9999}}}
        with pytest.raises(ValueError, match="zones.a"):
            DesignProject.from_dict(d)
        with pytest.raises(ValueError, match="ppfd_target"):
            DesignProject.from_dict(d)

    def test_reserved_zone_ids_rejected(self):
        for zid in sorted(ZONE_RESERVED_IDS):
            d = _base_dict()
            d["zones"] = {zid: {"led": {"ppfd_target": 200}}}
            with pytest.raises(ValueError, match="reserved"):
                DesignProject.from_dict(d)

    def test_invalid_zone_ids_rejected(self):
        for zid in ("1room", "room x", "", "room.x", "房"):
            d = _base_dict()
            d["zones"] = {zid: {"led": {"ppfd_target": 200}}}
            with pytest.raises(ValueError, match="zone id"):
                DesignProject.from_dict(d)

    def test_valid_zone_id_charset_accepted(self):
        d = _base_dict()
        d["zones"] = {
            "Zone_9": {"led": {"ppfd_target": 200}},
            "_service": {"deh": {}},
            "room-b": {"co2": {}},
        }
        p = DesignProject.from_dict(d)
        assert set(p.zones) == {"Zone_9", "_service", "room-b"}

    def test_zones_not_a_mapping_rejected(self):
        d = _base_dict()
        d["zones"] = ["nursery"]
        with pytest.raises(ValueError, match="zones must be a mapping"):
            DesignProject.from_dict(d)

    def test_zone_delta_not_a_mapping_rejected(self):
        d = _base_dict()
        d["zones"] = {"a": ["led"]}
        with pytest.raises(ValueError, match="zones.a must be a mapping"):
            DesignProject.from_dict(d)

    def test_zone_section_not_a_mapping_rejected(self):
        d = _base_dict()
        d["zones"] = {"a": {"led": 3}}
        with pytest.raises(ValueError, match=r"zones.a.led"):
            DesignProject.from_dict(d)
