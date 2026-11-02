"""G12 (Wave 1): tariff feed-in cap (export_limit_kw) + demand charge.

Two opt-in Tariff features, both default-OFF:

* ``export_limit_kw`` -- EnergySystem.simulate_performance clips the hourly
  feed-in at the grid interface to this kW value; the clipped surplus is
  curtailed PV energy (never sold, never redirected to load/battery) and is
  reported as metrics['pv_curtailed_kwh'] ONLY while a cap is configured.
* ``demand_charge_per_kw`` -- Tariff.annual_cost bills the monthly maximum
  of the hourly grid-import POWER (kW, no dt factor) at the per-kW rate,
  summed over the months of the series (12 terms for a full year), folded
  into net_grid_cost / annual_grid_cost; reported as
  metrics['annual_demand_charge'] ONLY while the rate is active.  Requires
  month labels (EnergySystem reads weather['month']; fail fast if absent).

Gate: with both features off (the defaults) the perf/metrics key sets and
every value must equal the pre-G12 formulas exactly (first test class).

No external numeric anchors are used: every expected value is either hand
computed from self-made synthetic data or recomputed with the legacy
formulas on the same building blocks.
"""

import numpy as np
import pytest

from vfed.pvbes.battery import BatterySystem
from vfed.pvbes.energy_system import EnergySystem
from vfed.pvbes.grid import Tariff
from vfed.pvbes.pv import PVSystem

# The exact pre-G12 key sets (frozen; the default-path runs must match them).
LEGACY_PERF_KEYS = {
    "pv_power",
    "battery_discharge",
    "battery_charge",
    "battery_soc",
    "battery_cycles",
    "battery_recon_grid_kwh",
    "grid_import",
    "grid_export",
    "load",
    "power_deficit",
}
LEGACY_METRIC_KEYS = {
    "grid_dependency_pct",
    "tlps",
    "lpsp_pct",
    "pv_self_consumption_rate",
    "battery_life_years",
    "battery_replacement_annual",
    "capital_cost",
    "annual_om",
    "annual_grid_cost",
    "annual_savings",
    "payback_period",
    "annual_pv_generation",
    "annual_grid_import",
    "annual_grid_export",
    "annual_load",
    "battery_cycles",
    "peak_power_kwp",
}

_TOU = [0.30] * 8 + [0.80] * 8 + [0.45] * 8  # 24 hourly prices


def _synth_case(n=72):
    """Deterministic synthetic weather + load (midday PV surplus, evening
    peak) with no month labels -- the pre-G12 weather-dict shape."""
    hours = np.arange(n) % 24
    weather = {
        "hour": hours,
        "direct_radiation": np.where((hours >= 8) & (hours < 16), 800.0, 0.0),
        "diffuse_radiation": np.where((hours >= 8) & (hours < 16), 60.0, 0.0),
        "temperature_2m": np.full(n, 22.0),
    }
    load = np.where((hours >= 18) & (hours < 23), 5.0, 1.2)
    return weather, load


def _legacy_run(es, x, weather, load):
    """Recompute the pre-G12 pipeline from the same building blocks (the
    formulas exactly as they were before the G12 fields existed)."""
    A_pv, E_bat = float(x[0]), float(x[1])
    pv = es.pv.calculate_pv_output(weather, A_pv)
    bat = es.battery.calculate_battery_flows(pv - load, load, E_bat)
    dis = np.array(bat["battery_discharge"])
    chg = np.array(bat["battery_charge"])
    imp = np.maximum(0.0, load - pv - dis)
    exp = np.maximum(0.0, pv - chg - load)
    recon = float(bat.get("recon_grid_kwh", 0.0))
    if recon > 0.0:
        chg[-1] += recon
        imp[-1] += recon
    elif recon < 0.0:
        dis[-1] += -recon
        exp[-1] += -recon
    hours = np.asarray(weather.get("hour", np.zeros(len(load))), dtype=int)
    tcost = Tariff(
        hourly_prices=list(es.tariff.hourly_prices), export_price=es.tariff.export_price
    ).annual_cost(imp, exp, hours)
    return {
        "pv": pv,
        "dis": dis,
        "chg": chg,
        "imp": imp,
        "exp": exp,
        "tcost": tcost,
        "hours": hours,
    }


def _demand_case():
    """12 synthetic months x 2 h, no PV: grid_import == load with a known
    5 kW peak in every month (hand-computable demand charge)."""
    n = 24
    weather = {
        "hour": np.tile([10, 19], 12),
        "direct_radiation": np.zeros(n),
        "diffuse_radiation": np.zeros(n),
        "temperature_2m": np.full(n, 20.0),
        "month": np.repeat(np.arange(1, 13), 2),
    }
    load = np.full(n, 3.0)
    load[0::2] = 5.0  # the monthly peak hour
    return weather, load


# ---------------------------------------------------------------------------
# Gate 1: default (both features off) is bit-identical to the legacy path
# ---------------------------------------------------------------------------


def test_default_perf_keys_are_the_legacy_set():
    weather, load = _synth_case()
    es = EnergySystem(pv=PVSystem(), battery=BatterySystem(), tariff=Tariff(hourly_prices=list(_TOU)))
    perf = es.simulate_performance([40.0, 4.0], weather, load)
    assert set(perf) == LEGACY_PERF_KEYS


def test_default_metrics_keys_are_the_legacy_set():
    weather, load = _synth_case()
    es = EnergySystem(tariff=Tariff(hourly_prices=list(_TOU)))
    m = es.calculate_metrics([40.0, 4.0], weather, load)
    assert set(m) == LEGACY_METRIC_KEYS


def test_explicit_none_fields_bit_identical():
    """Explicitly passing the None sentinels must reproduce the untouched
    default exactly (dict equality compares floats exactly)."""
    weather, load = _synth_case()
    es_default = EnergySystem(tariff=Tariff(hourly_prices=list(_TOU)))
    es_none = EnergySystem(
        tariff=Tariff(
            hourly_prices=list(_TOU), export_limit_kw=None, demand_charge_per_kw=None
        )
    )
    x = [40.0, 4.0]
    assert es_default.calculate_metrics(x, weather, load) == es_none.calculate_metrics(
        x, weather, load
    )
    p1 = es_default.simulate_performance(x, weather, load)
    p2 = es_none.simulate_performance(x, weather, load)
    assert set(p1) == set(p2) == LEGACY_PERF_KEYS
    for k in LEGACY_PERF_KEYS:
        if isinstance(p1[k], np.ndarray):
            assert np.array_equal(p1[k], p2[k]), k
        else:
            assert p1[k] == p2[k], k


def test_default_path_bit_identical_to_legacy_formulas():
    """Default run vs the recomputed pre-G12 pipeline: array-exact dispatch
    and exact-float cost metrics."""
    weather, load = _synth_case()
    es = EnergySystem(pv=PVSystem(), battery=BatterySystem(), tariff=Tariff(hourly_prices=list(_TOU)))
    x = [40.0, 4.0]
    perf = es.simulate_performance(x, weather, load)
    m = es.calculate_metrics(x, weather, load)
    leg = _legacy_run(es, x, weather, load)
    assert np.array_equal(perf["pv_power"], leg["pv"])
    assert np.array_equal(perf["grid_import"], leg["imp"])
    assert np.array_equal(perf["grid_export"], leg["exp"])
    assert np.array_equal(perf["battery_charge"], leg["chg"])
    assert np.array_equal(perf["battery_discharge"], leg["dis"])
    # dispatch conservation (legacy identity, no curtailment key)
    lhs = float(np.sum(perf["pv_power"]) + np.sum(perf["grid_import"]) + np.sum(perf["battery_discharge"]))
    rhs = float(
        np.sum(perf["load"])
        + np.sum(perf["battery_charge"])
        + np.sum(perf["grid_export"])
    )
    assert lhs == pytest.approx(rhs, abs=1e-6)
    # exact-float cost metrics vs the legacy formula recompute
    assert m["annual_grid_cost"] == leg["tcost"]["net_grid_cost"]
    assert m["annual_grid_import"] == float(np.sum(leg["imp"]))
    assert m["annual_grid_export"] == float(np.sum(leg["exp"]))
    assert m["annual_pv_generation"] == float(np.sum(leg["pv"]))
    baseline = float(
        np.sum(
            np.asarray(load, dtype=float)
            * Tariff(hourly_prices=list(_TOU)).price_array(leg["hours"])
        )
    )
    assert m["annual_savings"] == baseline - leg["tcost"]["net_grid_cost"]
    assert m["grid_dependency_pct"] == float(np.mean(leg["imp"] > 0.0)) * 100.0


# ---------------------------------------------------------------------------
# Gate 2: feed-in cap and curtailment
# ---------------------------------------------------------------------------


def _cap_case(cap, A_pv=30.0):
    weather, load = _synth_case(48)
    es = EnergySystem(tariff=Tariff(hourly_prices=list(_TOU), export_limit_kw=cap))
    return es, [A_pv, 0.0], weather, load


def test_export_capped_hourly_and_exact_accounting():
    es, x, weather, load = _cap_case(2.0)
    perf = es.simulate_performance(x, weather, load)
    m = es.calculate_metrics(x, weather, load)
    pv = es.pv.calculate_pv_output(weather, x[0])
    uncapped = np.maximum(0.0, pv - load)  # E_bat = 0 -> no charge/discharge
    # hourly cap respected, and the clip is exactly min(uncapped, cap)
    assert (perf["grid_export"] <= 2.0 + 1e-12).all()
    assert np.array_equal(perf["grid_export"], np.minimum(uncapped, 2.0))
    assert np.array_equal(perf["pv_curtailed"], np.maximum(0.0, uncapped - 2.0))
    assert float(np.sum(perf["pv_curtailed"])) > 0.0
    # conservation: pv = self-use + feed-in + curtailed (per hour and summed)
    self_use = np.minimum(pv, load)
    assert np.allclose(pv, self_use + perf["grid_export"] + perf["pv_curtailed"], atol=1e-9)
    assert float(np.sum(pv)) == pytest.approx(
        float(np.sum(self_use))
        + float(np.sum(perf["grid_export"]))
        + float(np.sum(perf["pv_curtailed"])),
        rel=1e-12,
    )
    # metrics bookkeeping: exactly one new key, exact annual sum
    assert set(m) == LEGACY_METRIC_KEYS | {"pv_curtailed_kwh"}
    assert m["pv_curtailed_kwh"] == float(np.sum(perf["pv_curtailed"]))
    # curtailed kWh earn no credit: the bill equals the legacy pricing of
    # the CAPPED arrays, and exceeds the uncapped legacy bill
    ref = Tariff(hourly_prices=list(_TOU), export_price=0.05).annual_cost(
        perf["grid_import"], perf["grid_export"], weather["hour"]
    )
    assert m["annual_grid_cost"] == ref["net_grid_cost"]
    uncapped_bill = Tariff(hourly_prices=list(_TOU), export_price=0.05).annual_cost(
        np.maximum(0.0, load - pv), uncapped, weather["hour"]
    )["net_grid_cost"]
    assert m["annual_grid_cost"] > uncapped_bill


def test_large_limit_degrades_to_legacy_behavior():
    weather, load = _synth_case()
    es_leg = EnergySystem(tariff=Tariff(hourly_prices=list(_TOU)))
    es_cap = EnergySystem(tariff=Tariff(hourly_prices=list(_TOU), export_limit_kw=1.0e9))
    x = [40.0, 4.0]
    m_leg = es_leg.calculate_metrics(x, weather, load)
    m_cap = es_cap.calculate_metrics(x, weather, load)
    assert set(m_cap) - set(m_leg) == {"pv_curtailed_kwh"}
    for k, v in m_leg.items():
        assert m_cap[k] == v, k
    assert m_cap["pv_curtailed_kwh"] == 0.0


def test_zero_limit_blocks_all_feed_in():
    es, x, weather, load = _cap_case(0.0)
    perf = es.simulate_performance(x, weather, load)
    m = es.calculate_metrics(x, weather, load)
    pv = es.pv.calculate_pv_output(weather, x[0])
    uncapped = np.maximum(0.0, pv - load)
    assert (perf["grid_export"] == 0.0).all()
    assert np.array_equal(perf["pv_curtailed"], uncapped)
    assert m["annual_grid_export"] == 0.0
    assert m["pv_curtailed_kwh"] == float(np.sum(uncapped))
    # no feed-in credit at all: net cost = pure import cost
    ref = Tariff(hourly_prices=list(_TOU), export_price=0.05).annual_cost(
        perf["grid_import"], np.zeros(len(load)), weather["hour"]
    )
    assert m["annual_grid_cost"] == ref["net_grid_cost"]


def test_cap_with_battery_keeps_annual_balance():
    """With a battery in the loop the capped identity closes:
    pv + import + discharge = load + charge + export + curtailed."""
    weather, load = _synth_case()
    es = EnergySystem(tariff=Tariff(hourly_prices=list(_TOU), export_limit_kw=1.5))
    perf = es.simulate_performance([40.0, 3.0], weather, load)
    assert (perf["grid_export"] <= 1.5 + 1e-12).all()
    assert float(np.sum(perf["pv_curtailed"])) > 0.0
    lhs = float(
        np.sum(perf["pv_power"])
        + np.sum(perf["grid_import"])
        + np.sum(perf["battery_discharge"])
    )
    rhs = float(
        np.sum(perf["load"])
        + np.sum(perf["battery_charge"])
        + np.sum(perf["grid_export"])
        + np.sum(perf["pv_curtailed"])
    )
    assert lhs == pytest.approx(rhs, abs=1e-6)


def test_cap_with_grid_charging_still_consistent():
    """The cap applies after the P1-2 grid-charging export recompute, so
    feed-in stays PV-only AND under the limit."""
    prices = [0.70] * 10 + [0.30] * 4 + [0.70] * 10  # valley h10-13
    hours = np.arange(48) % 24
    weather = {
        "hour": hours,
        "direct_radiation": np.where((hours >= 8) & (hours < 17), 800.0, 0.0),
        "diffuse_radiation": np.zeros(48),
        "temperature_2m": np.full(48, 20.0),
    }
    load = np.where(np.isin(hours, [18, 19, 20, 21]), 5.0, 1.0)
    es = EnergySystem(
        battery=BatterySystem(allow_grid_charging=True, c_rate=1.0),
        tariff=Tariff(hourly_prices=prices, export_limit_kw=1.0),
    )
    perf = es.simulate_performance([10.0, 2.0], weather, load)
    assert (perf["grid_export"] <= 1.0 + 1e-12).all()
    lhs = float(
        np.sum(perf["pv_power"])
        + np.sum(perf["grid_import"])
        + np.sum(perf["battery_discharge"])
    )
    rhs = float(
        np.sum(perf["load"])
        + np.sum(perf["battery_charge"])
        + np.sum(perf["grid_export"])
        + np.sum(perf.get("pv_curtailed", np.zeros(48)))
    )
    assert lhs == pytest.approx(rhs, abs=1e-6)


# ---------------------------------------------------------------------------
# Gate 3: demand charge
# ---------------------------------------------------------------------------


def test_demand_charge_hand_computed_varying_peaks():
    """12 synthetic months, month m peaking at m kW, rate 2.0:
    annual demand charge = (1+2+...+12) kW x 2.0 = 156.0 exactly."""
    months = np.repeat(np.arange(1, 13), 4)
    hours = np.tile(np.arange(4), 12)
    imp = np.zeros(48)
    for mo in range(1, 13):
        imp[(mo - 1) * 4 + 1] = float(mo)
    t = Tariff(demand_charge_per_kw=2.0)
    cost = t.annual_cost(imp, np.zeros(48), hours, months=months)
    assert cost["demand_charge"] == 156.0
    assert cost["net_grid_cost"] == (
        cost["grid_import_cost"] - cost["grid_export_credit"] + cost["demand_charge"]
    )


def test_demand_charge_hand_computed_flat_peak():
    """The task's hand case: 5 kW monthly peak x 12.0/kW x 12 months = 720.
    Also: the charge bills POWER, so dt must not scale it."""
    months = np.repeat(np.arange(1, 13), 4)
    hours = np.tile(np.arange(4), 12)
    imp = np.zeros(48)
    imp[1::4] = 5.0
    t = Tariff(demand_charge_per_kw=12.0)
    cost = t.annual_cost(imp, np.zeros(48), hours, months=months)
    assert cost["demand_charge"] == 720.0
    cost_dt = t.annual_cost(imp, np.zeros(48), hours, dt=0.5, months=months)
    assert cost_dt["demand_charge"] == cost["demand_charge"]


def test_demand_charge_off_states_bit_identical():
    imp = np.array([1.0, 2.0, 3.0, 2.0])
    exp = np.array([0.5, 0.0, 0.0, 0.25])
    hours = np.array([1, 2, 3, 4])
    c_none = Tariff().annual_cost(imp, exp, hours)
    c_zero = Tariff(demand_charge_per_kw=0.0).annual_cost(imp, exp, hours)
    assert c_none == c_zero
    assert set(c_none) == {"grid_import_cost", "grid_export_credit", "net_grid_cost"}
    # months are never read while the charge is off (EnergySystem always
    # passes weather['month'] through) and are not even required
    c_zero_m = Tariff(demand_charge_per_kw=0.0).annual_cost(
        imp, exp, hours, months=np.ones(4, dtype=int)
    )
    assert c_zero_m == c_none


def test_demand_charge_requires_months_fail_fast():
    t = Tariff(demand_charge_per_kw=2.0)
    with pytest.raises(ValueError, match="month") as ei:
        t.annual_cost(np.ones(6), np.zeros(6), np.arange(6))
    assert str(ei.value).isascii()


def test_demand_charge_months_length_mismatch_raises():
    t = Tariff(demand_charge_per_kw=1.0)
    with pytest.raises(ValueError, match="length") as ei:
        t.annual_cost(np.ones(5), np.zeros(5), np.arange(5), months=np.ones(4, dtype=int))
    assert str(ei.value).isascii()


def test_energy_system_demand_charge_integration():
    """No PV: import == load, every month peaks at 5 kW -> annual demand
    charge = 5 x 12.0 x 12 = 720; folded into annual_grid_cost and savings."""
    weather, load = _demand_case()
    x = [0.0, 0.0]
    m_base = EnergySystem(tariff=Tariff(hourly_prices=list(_TOU))).calculate_metrics(
        x, weather, load
    )
    m_on = EnergySystem(
        tariff=Tariff(hourly_prices=list(_TOU), demand_charge_per_kw=12.0)
    ).calculate_metrics(x, weather, load)
    assert set(m_base) == LEGACY_METRIC_KEYS  # off -> no key drift
    assert set(m_on) - set(m_base) == {"annual_demand_charge"}
    assert m_on["annual_demand_charge"] == 720.0
    assert m_on["annual_grid_cost"] == m_base["annual_grid_cost"] + 720.0
    assert m_on["annual_savings"] == m_base["annual_savings"] - 720.0


def test_energy_system_demand_charge_missing_month_raises():
    """Active charge + weather without month labels -> fail fast (ASCII)."""
    weather, load = _synth_case()  # no 'month' key
    es = EnergySystem(tariff=Tariff(hourly_prices=list(_TOU), demand_charge_per_kw=12.0))
    with pytest.raises(ValueError, match="month") as ei:
        es.calculate_metrics([0.0, 0.0], weather, load)
    assert str(ei.value).isascii()


def test_rate_zero_equals_default_exactly():
    weather, load = _demand_case()
    x = [0.0, 0.0]
    m_none = EnergySystem(tariff=Tariff(hourly_prices=list(_TOU))).calculate_metrics(
        x, weather, load
    )
    m_zero = EnergySystem(
        tariff=Tariff(hourly_prices=list(_TOU), demand_charge_per_kw=0.0)
    ).calculate_metrics(x, weather, load)
    assert m_none == m_zero  # exact dict equality: no value drift, no keys
    assert "annual_demand_charge" not in m_zero
    assert set(m_none) == LEGACY_METRIC_KEYS


# ---------------------------------------------------------------------------
# Gate 4: fail-fast validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [-0.1, -1.0, -100.0])
def test_negative_export_limit_raises(bad):
    with pytest.raises(ValueError, match="non-negative") as ei:
        Tariff(export_limit_kw=bad)
    assert str(ei.value).isascii()


@pytest.mark.parametrize("bad", [-0.01, -5.0])
def test_negative_demand_charge_raises(bad):
    with pytest.raises(ValueError, match="non-negative") as ei:
        Tariff(demand_charge_per_kw=bad)
    assert str(ei.value).isascii()
