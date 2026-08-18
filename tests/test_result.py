"""Tests for SimulationResult serialisation and backward compat."""
import json
import os
import tempfile

import numpy as np

from vfed.design.result import SimulationResult, _ensure_json_safe


def make_sample_result():
    """Build a minimal SimulationResult matching current engine output."""
    r = SimulationResult(project_name="test_sample")
    r.summary = {
        "annual_harvest_kg": 100.0,
        "annual_harvest_fw_kg": 2000.0,
        "annual_energy_kwh": 50000.0,
        "specific_energy_kwh_per_kg": 25.0,
        "harvest_per_month_avg_kg": 166.67,
    }
    r.climate = {
        "city": "TestCity",
        "lat": 30.0, "lon": 120.0, "year": 2023,
        "annual_avg_temp_c": 18.0,
        "annual_avg_rh_pct": 70.0,
        "annual_ghi_kwh_m2": 1400.0,
        "monthly": {
            "month": list(range(1, 13)),
            "avg_temp_c": [5.0] * 12,
            "avg_rh_pct": [70.0] * 12,
            "ghi_kwh_m2": [100.0] * 12,
        },
    }
    r.timeseries = {
        "hour_of_year": list(range(24)),
        "T_z": [22.0] * 24,
        "RH_z": [65.0] * 24,
        "load_kw": [10.0] * 24,
        "E_hvac_Wh": [3000.0] * 24,
        "E_deh_Wh": [2000.0] * 24,
        "E_led_Wh": [5000.0] * 24,
        "E_misc_Wh": [1000.0] * 24,
    }
    r.monthly = {
        "month": list(range(1, 13)),
        "energy_kwh": {
            "total": [4000] * 12,
            "hvac": [1000] * 12,
            "deh": [500] * 12,
            "led": [2000] * 12,
            "misc": [500] * 12,
        },
        "harvest_kg": [166] * 12,
        "avg_T_z": [22.0] * 12,
        "avg_RH_z": [65.0] * 12,
    }
    r.energy_breakdown = {"hvac_pct": 0.3, "deh_pct": 0.15, "led_pct": 0.45, "misc_pct": 0.1}
    r.typical_daily = {
        "months": list(range(1, 13)),
        "hours": list(range(24)),
        "load_kw": [[5.0] * 24] * 12,
    }
    r._raw = {"load": [10.0] * 24, "weather": {"temperature_2m": [20.0] * 24}}
    return r


# ── JSON round-trip ─────────────────────────────────────────────────


def test_to_dict_is_json_serializable():
    r = make_sample_result()
    d = r.to_dict()
    assert d["version"] == "1.0"
    assert d["project_name"] == "test_sample"
    # ensure it serializes without error
    s = json.dumps(d)
    assert len(s) > 100


def test_json_round_trip():
    r = make_sample_result()
    d = r.to_dict()
    r2 = SimulationResult.from_dict(d)
    assert r2.project_name == r.project_name
    assert r2.summary["annual_harvest_kg"] == 100.0
    assert r2.climate["city"] == "TestCity"
    assert len(r2.timeseries["T_z"]) == 24


def test_save_and_load():
    r = make_sample_result()
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "result.json")
        r.save(path)
        assert os.path.exists(path)
        r2 = SimulationResult.load(path)
        assert r2.project_name == "test_sample"
        assert r2.summary["annual_energy_kwh"] == 50000.0
        assert r2.typical_daily["load_kw"][0][0] == 5.0


def test_save_timeseries_csv():
    r = make_sample_result()
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "ts.csv")
        r.save_timeseries_csv(path)
        assert os.path.exists(path)
        with open(path) as f:
            lines = f.readlines()
        assert len(lines) == 25  # header + 24 rows
        assert "T_z" in lines[0]


def test_save_monthly_csv():
    r = make_sample_result()
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "monthly.csv")
        r.save_monthly_csv(path)
        assert os.path.exists(path)
        with open(path) as f:
            lines = f.readlines()
        assert len(lines) == 13  # header + 12 months
        header = lines[0].strip().split(",")
        assert "energy_kwh__total" in header
        assert "energy_kwh__hvac" in header
        # first data row should have non-empty values
        first_row = lines[1].strip().split(",")
        energy_idx = header.index("energy_kwh__total")
        assert first_row[energy_idx] == "4000"


def test_save_summary_csv():
    r = make_sample_result()
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "summary.csv")
        r.save_summary_csv(path)
        assert os.path.exists(path)
        with open(path) as f:
            lines = f.readlines()
        header = lines[0].strip().split(",")
        row = lines[1].strip().split(",")
        assert "annual_harvest_kg" in header
        idx = header.index("annual_harvest_kg")
        assert row[idx] == "100.0"


# ── JSON / dict output ──────────────────────────────────────────────────


def test_json_methods():
    r = make_sample_result()
    jc = r.json()
    assert isinstance(jc, str)
    d = json.loads(jc)
    assert d["project_name"] == "test_sample"

    jp = r.json_pretty()
    assert isinstance(jp, str)
    assert "\n" in jp


def test_to_dict_excludes_raw():
    r = make_sample_result()
    d = r.to_dict()
    assert "_raw" not in d


# ── numpy type safety ────────────────────────────────────────────────


def test_ensure_json_safe_np_bool():
    assert _ensure_json_safe(np.bool_(True)) is True
    assert _ensure_json_safe(np.bool_(False)) is False


def test_ensure_json_safe_np_int():
    val = _ensure_json_safe(np.int32(42))
    assert val == 42
    assert isinstance(val, int)


def test_ensure_json_safe_np_float():
    val = _ensure_json_safe(np.float64(3.14))
    assert val == 3.14
    assert isinstance(val, float)


def test_ensure_json_safe_np_array():
    val = _ensure_json_safe(np.array([1.0, 2.0]))
    assert val == [1.0, 2.0]


def test_ensure_json_safe_nested():
    d = {"a": np.int32(1), "b": {"c": np.float64(2.0)}, "d": [np.bool_(True)]}
    safe = _ensure_json_safe(d)
    assert safe == {"a": 1, "b": {"c": 2.0}, "d": [True]}
    json.dumps(safe)  # should not raise


# ── backward compat ──────────────────────────────────────────────────


def test_backward_compat_load():
    r = make_sample_result()
    assert "load" in r
    load = r["load"]
    assert len(load) == 24


def test_backward_compat_weather():
    r = make_sample_result()
    w = r["weather"]
    assert "temperature_2m" in w


def test_backward_compat_kwh_per_kg_fresh():
    r = make_sample_result()
    val = r["kwh_per_kg_fresh"]
    assert val == 25.0


def test_backward_compat_annual_load_kwh():
    r = make_sample_result()
    val = r["annual_load_kwh"]
    assert val == 50000.0


def test_backward_compat_biomass_kg():
    r = make_sample_result()
    val = r["biomass_kg"]
    assert val == 100.0


def test_backward_compat_timeseries_dataframe():
    r = make_sample_result()
    ts = r["timeseries"]
    # should return a DataFrame
    assert hasattr(ts, "columns")
    assert "T_z" in ts.columns


def test_get_default():
    r = make_sample_result()
    assert r.get("nonexistent", 42) == 42


def test_missing_key_raises():
    r = make_sample_result()
    try:
        r["nonexistent"]
        assert False, "should have raised"
    except KeyError:
        pass
