"""T5 gate: the EnergySystem ``dispatch_policy`` hook (pluggable dispatch).

Protocol under test (frozen; the C1 DispatchPolicy must align with it):
- ``dispatch_policy(obs) -> (charge_w, discharge_w)`` runs once per hourly
  timestep inside ``EnergySystem.simulate_performance``.
- obs fields (exactly these nine): t, hour, month, price, pv_w, load_w,
  soc_kwh, capacity_kwh, dt_h.
- Charging is NOT limited to the PV surplus (the policy may buy from the
  grid -- the deliberate difference from greedy); discharging IS clamped to
  the load deficit; every request is clamped by the same C-rate / SOC /
  efficiency limits as the greedy dispatch.
- charge_w and discharge_w both positive is a contract violation and must
  raise; so must negative requests and malformed actions.
- Object policies may expose ``reset(timesteps, capacity_kwh)`` which runs
  once before the first observation; plain functions skip it.
- ``dispatch_policy=None`` (the default) keeps the built-in greedy dispatch
  bit-identical to the pre-change formulas (gate a below recomputes the old
  pipeline from the same building blocks).

No external numeric anchors: every expected value is hand computed from
self-made synthetic data or recomputed with the legacy formulas.
"""

import numpy as np
import pytest

from vfed.pvbes.battery import BatterySystem
from vfed.pvbes.energy_system import EnergySystem
from vfed.pvbes.grid import Tariff
from vfed.pvbes.pv import PVSystem

# The pre-T5 perf key set (frozen; the policy path must not add keys).
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

# 24 hourly prices: valley h0-7 (0.10), mid h8-17 (0.45), peak h18-23 (0.80).
_TOU = [0.10] * 8 + [0.45] * 10 + [0.80] * 6


def _synth_case(n=48, with_month=False):
    """Deterministic synthetic weather + load (midday PV surplus, evening
    peak).  Month labels are optional because the pre-T5 weather dict did
    not carry them."""
    hours = np.arange(n) % 24
    weather = {
        "hour": hours,
        "direct_radiation": np.where((hours >= 8) & (hours < 16), 800.0, 0.0),
        "diffuse_radiation": np.where((hours >= 8) & (hours < 16), 60.0, 0.0),
        "temperature_2m": np.full(n, 22.0),
    }
    if with_month:
        weather["month"] = (hours // 24) % 12 + 1
    load = np.where((hours >= 18) & (hours < 23), 5.0, 1.0)
    return weather, load


def _legacy_perf(es, x, weather, load):
    """The pre-T5 ``simulate_performance`` recomputed from the same building
    blocks -- the formulas exactly as they were before the dispatch hook
    existed (both the plain and the grid-charging branch)."""
    A_pv, E_bat = float(x[0]), float(x[1])
    pv = es.pv.calculate_pv_output(weather, A_pv)
    if es.battery.allow_grid_charging:
        bat = es.battery.calculate_battery_flows(
            pv - load,
            load,
            E_bat,
            dt=1.0,
            hourly_prices=es.tariff.hourly_prices,
            hours=np.asarray(weather.get("hour", np.zeros(len(load))), dtype=int),
        )
    else:
        bat = es.battery.calculate_battery_flows(pv - load, load, E_bat, dt=1.0)
    dis = np.array(bat["battery_discharge"])
    chg = np.array(bat["battery_charge"])
    imp = np.maximum(0.0, load - pv - dis)
    exp = np.maximum(0.0, pv - chg - load)
    gch = np.asarray(bat.get("grid_charged", np.zeros_like(imp)))
    if np.any(gch != 0.0):
        imp = imp + gch
        exp = np.maximum(0.0, pv - (chg - gch) - load)
    recon = float(bat.get("recon_grid_kwh", 0.0))
    if recon > 0.0:
        chg[-1] += recon
        imp[-1] += recon
    elif recon < 0.0:
        dis[-1] += -recon
        exp[-1] += -recon
    return {
        "pv": pv,
        "dis": dis,
        "chg": chg,
        "imp": imp,
        "exp": exp,
        "soc": np.array(bat["battery_soc"]),
        "cycles": bat["battery_cycles"],
        "recon": recon,
    }


def _assert_perf_bitwise(perf, leg):
    """Bitwise (== / array_equal) comparison of a perf dict against the
    legacy recompute -- no tolerances anywhere."""
    assert np.array_equal(perf["pv_power"], leg["pv"])
    assert np.array_equal(perf["battery_discharge"], leg["dis"])
    assert np.array_equal(perf["battery_charge"], leg["chg"])
    assert np.array_equal(perf["grid_import"], leg["imp"])
    assert np.array_equal(perf["grid_export"], leg["exp"])
    assert np.array_equal(perf["battery_soc"], leg["soc"])
    assert perf["battery_cycles"] == leg["cycles"]
    assert perf["battery_recon_grid_kwh"] == leg["recon"]


def _toy_valley_charge_peak_discharge(obs):
    """Toy TOU-arbitrage policy: fill from any source while the price is at
    the valley and the SOC fraction is below 0.85; discharge while the price
    is at the peak and the SOC fraction is above 0.15; idle otherwise.

    Requests are deliberately oversized (1e6) so the engine's clamps, not
    the policy, set the real powers."""
    frac = obs["soc_kwh"] / obs["capacity_kwh"]
    if obs["price"] <= 0.10 + 1e-12 and frac < 0.85:
        return (1e6, 0.0)
    if obs["price"] >= 0.80 - 1e-12 and frac > 0.15:
        return (0.0, 1e6)
    return (0.0, 0.0)


# ---------------------------------------------------------------------------
# Gate (a): dispatch_policy=None keeps the pre-change output bit-identical
# ---------------------------------------------------------------------------
def test_none_path_bit_identical_to_pre_change_formulas():
    weather, load = _synth_case()
    es = EnergySystem(
        pv=PVSystem(), battery=BatterySystem(), tariff=Tariff(hourly_prices=list(_TOU))
    )
    x = [40.0, 4.0]
    perf_default = es.simulate_performance(x, weather, load)
    perf_none = es.simulate_performance(x, weather, load, dispatch_policy=None)
    leg = _legacy_perf(es, x, weather, load)
    # explicit None == untouched default == pre-change recompute, bitwise
    for k in LEGACY_PERF_KEYS:
        if isinstance(perf_default[k], np.ndarray):
            assert np.array_equal(perf_default[k], perf_none[k]), k
        else:
            assert perf_default[k] == perf_none[k], k
    _assert_perf_bitwise(perf_default, leg)
    _assert_perf_bitwise(perf_none, leg)


def test_none_path_with_grid_charging_bit_identical():
    weather, load = _synth_case()
    es = EnergySystem(
        battery=BatterySystem(allow_grid_charging=True),
        tariff=Tariff(hourly_prices=list(_TOU)),
    )
    x = [40.0, 4.0]
    perf_default = es.simulate_performance(x, weather, load)
    perf_none = es.simulate_performance(x, weather, load, dispatch_policy=None)
    leg = _legacy_perf(es, x, weather, load)
    assert np.any(leg["chg"] > 0.0), "fixture degenerate: no valley charging happened"
    _assert_perf_bitwise(perf_default, leg)
    _assert_perf_bitwise(perf_none, leg)


def test_metrics_none_passthrough_identical():
    weather, load = _synth_case()
    es = EnergySystem(tariff=Tariff(hourly_prices=list(_TOU)))
    x = [40.0, 4.0]
    m_default = es.calculate_metrics(x, weather, load)
    m_none = es.calculate_metrics(x, weather, load, dispatch_policy=None)
    assert m_default == m_none  # exact dict equality: no value drift, no keys


# ---------------------------------------------------------------------------
# Gate (b): a toy policy deterministically changes the dispatch
# ---------------------------------------------------------------------------
def test_toy_valley_charge_peak_discharge_differs_from_greedy():
    """No PV at all: greedy discharges its initial SOC into the first
    deficits and then stays empty, while the toy policy buys valley power
    into the battery every day and discharges it in peak hours, so the
    import series must differ with exact, hand-checkable values."""
    weather, load = _synth_case()
    es = EnergySystem(tariff=Tariff(hourly_prices=list(_TOU)))
    x = [0.0, 10.0]  # zero PV area, 10 kWh battery (soc0 = 0.5)
    perf_greedy = es.simulate_performance(x, weather, load)
    perf_toy = es.simulate_performance(x, weather, load, dispatch_policy=_toy_valley_charge_peak_discharge)

    # fixture sanity: greedy with no PV never charges during the year (no
    # surplus anywhere); the only charge entry is the P4-18 year-end recon
    # top-up at the last timestep (it drained below soc0)
    assert perf_greedy["battery_charge"][:-1].sum() == 0.0
    assert perf_greedy["battery_discharge"].sum() > 0.0
    assert perf_greedy["battery_recon_grid_kwh"] > 0.0

    # direction: the annual import series is deterministically different
    assert not np.array_equal(perf_toy["grid_import"], perf_greedy["grid_import"])

    # numeric: t=0 is a valley hour with no PV, so the first charge is
    # purely grid-bought and headroom-limited at (soc_max - soc0)*E_bat.
    headroom = min(10.0, (0.9 - 0.5) * 10.0)  # c_rate*E_now not binding
    assert perf_toy["battery_charge"][0] == headroom
    assert perf_toy["grid_import"][0] == load[0] + headroom  # 1.0 + 4.0 = 5.0

    # numeric: t=18 is a peak hour; SOC is above soc_min after the valley
    # charge and the terminal cap does not bind, so the full 5 kW deficit is
    # served from the battery and the import is exactly zero.
    assert perf_toy["grid_import"][18] == 0.0
    assert perf_toy["battery_discharge"][18] == 5.0

    # direction with numbers: valley imports rise (bought charging energy),
    # peak imports fall (displaced by the battery).
    hours = weather["hour"]
    valley = hours <= 7
    peak = hours >= 18
    assert float(np.sum(perf_toy["grid_import"][valley])) > float(
        np.sum(perf_greedy["grid_import"][valley])
    )
    assert float(np.sum(perf_toy["grid_import"][peak])) < float(
        np.sum(perf_greedy["grid_import"][peak])
    )

    # the annual balance closes: pv + import + discharge = load + charge + export
    lhs = float(
        np.sum(perf_toy["pv_power"])
        + np.sum(perf_toy["grid_import"])
        + np.sum(perf_toy["battery_discharge"])
    )
    rhs = float(
        np.sum(perf_toy["load"])
        + np.sum(perf_toy["battery_charge"])
        + np.sum(perf_toy["grid_export"])
    )
    assert lhs == pytest.approx(rhs, abs=1e-9)
    # key parity: the policy path must not add or drop perf keys
    assert set(perf_toy) == LEGACY_PERF_KEYS


def test_policy_owns_dispatch_over_greedy_grid_charging():
    """A do-nothing policy must bypass the greedy P1-2 valley charging: the
    policy owns the dispatch, not the allow_grid_charging flag."""
    weather, load = _synth_case()
    es = EnergySystem(
        battery=BatterySystem(allow_grid_charging=True),
        tariff=Tariff(hourly_prices=list(_TOU)),
    )
    x = [40.0, 4.0]
    perf = es.simulate_performance(x, weather, load, dispatch_policy=lambda obs: (0.0, 0.0))
    leg = _legacy_perf(es, x, weather, load)
    assert leg["chg"].sum() > 0.0, "fixture degenerate: greedy did not valley-charge"
    assert perf["battery_charge"].sum() == 0.0
    assert perf["battery_discharge"].sum() == 0.0


# ---------------------------------------------------------------------------
# Gate (c): oversized requests are clamped to the battery limits
# ---------------------------------------------------------------------------
def test_oversized_charge_request_clamped():
    """A 1e9 kW charge request must land exactly on the headroom cap
    min(c_rate*E_now, (soc_max - soc)*E_now/dt), step after step, including
    the P2-4 usable-capacity fade after the first step's throughput."""
    n = 3
    weather = {
        "hour": np.arange(n),
        "direct_radiation": np.zeros(n),
        "diffuse_radiation": np.zeros(n),
        "temperature_2m": np.full(n, 20.0),
    }
    load = np.ones(n)
    es = EnergySystem(tariff=Tariff(hourly_prices=list(_TOU)))
    perf = es.simulate_performance(
        [0.0, 10.0], weather, load, dispatch_policy=lambda obs: (1e9, 0.0)
    )
    charge = perf["battery_charge"]
    # mirrored battery.py state (defaults: c_rate 1.0, eta 0.91, soc 0.10/0.90,
    # soh_eol 0.80, cycle_life 4000, no calendar fade, no self-discharge)
    soh_k = (1.0 - 0.80) / 4000
    E_now = 10.0
    soc = 0.5
    cap0 = min(1.0 * E_now, (0.9 - soc) * E_now / 1.0)
    assert charge[0] == cap0
    # advance the state exactly like the dispatch loop does
    soc = soc + cap0 * 0.91 * 1.0 / E_now
    cycles = cap0 * 0.91 * 1.0 / (2.0 * 10.0)
    E_now = 10.0 * max(1.0 - soh_k * cycles, 1e-3)
    cap1 = min(1.0 * E_now, (0.9 - soc) * E_now / 1.0)
    assert charge[1] == cap1
    # every step stays inside the C-rate terminal cap
    assert (charge <= 10.0 + 1e-12).all()


def test_oversized_discharge_request_clamped():
    """A 1e9 kW discharge request must land exactly on
    min(deficit, min(c_rate*E_now, (soc - soc_min)*E_now/dt)*eta_dis), and a
    discharge request in a surplus hour must clamp to zero (deficit = 0)."""
    n = 3
    weather = {
        "hour": np.arange(n),
        "direct_radiation": np.zeros(n),
        "diffuse_radiation": np.zeros(n),
        "temperature_2m": np.full(n, 20.0),
    }
    # deficit case: no PV, 5 kW load -> deficit binds against the terminal cap
    es = EnergySystem(tariff=Tariff(hourly_prices=list(_TOU)))
    perf_def = es.simulate_performance(
        [0.0, 10.0], weather, np.full(n, 5.0), dispatch_policy=lambda obs: (0.0, 1e9)
    )
    expected = min(5.0, min(10.0, (0.5 - 0.1) * 10.0) * 0.91)
    assert perf_def["battery_discharge"][0] == expected
    assert perf_def["grid_import"][0] == 5.0 - expected

    # surplus case: pv 6 kW vs load 1 kW -> deficit is 0 -> discharge clamped off
    pv_override = np.full(n, 6.0)
    perf_sur = es.simulate_performance(
        [0.0, 10.0],
        weather,
        np.ones(n),
        pv_power_override=pv_override,
        dispatch_policy=lambda obs: (0.0, 1e9),
    )
    assert (perf_sur["battery_discharge"] == 0.0).all()
    assert np.array_equal(perf_sur["grid_export"], np.full(n, 5.0))


# ---------------------------------------------------------------------------
# Gate (d): contract violations raise (fail fast)
# ---------------------------------------------------------------------------
def test_charge_and_discharge_both_positive_raises():
    weather, load = _synth_case(4)
    es = EnergySystem(tariff=Tariff(hourly_prices=list(_TOU)))
    with pytest.raises(ValueError, match="both positive") as ei:
        es.simulate_performance(
            [0.0, 10.0], weather, load, dispatch_policy=lambda obs: (5.0, 5.0)
        )
    assert str(ei.value).isascii()


def test_negative_power_request_raises():
    weather, load = _synth_case(4)
    es = EnergySystem(tariff=Tariff(hourly_prices=list(_TOU)))
    with pytest.raises(ValueError, match="non-negative") as ei:
        es.simulate_performance(
            [0.0, 10.0], weather, load, dispatch_policy=lambda obs: (-1.0, 0.0)
        )
    assert str(ei.value).isascii()


def test_malformed_action_raises():
    weather, load = _synth_case(4)
    es = EnergySystem(tariff=Tariff(hourly_prices=list(_TOU)))
    with pytest.raises(ValueError, match="pair of two numbers") as ei:
        es.simulate_performance(
            [0.0, 10.0], weather, load, dispatch_policy=lambda obs: (5.0,)
        )
    assert str(ei.value).isascii()


# ---------------------------------------------------------------------------
# Gate (e): object policies get reset(timesteps, capacity_kwh)
# ---------------------------------------------------------------------------
class _RecordingPolicy:
    """Callable object policy that logs the reset call, every observation
    and the call order, and always requests nothing."""

    def __init__(self):
        self.reset_calls = []
        self.obs_log = []
        self.order = []

    def reset(self, timesteps, capacity_kwh):
        self.reset_calls.append((timesteps, capacity_kwh))
        self.order.append("reset")

    def __call__(self, obs):
        self.obs_log.append(obs)
        self.order.append("obs")
        return (0.0, 0.0)


def test_object_policy_reset_called_with_horizon_and_capacity():
    n = 6
    weather, load = _synth_case(n, with_month=True)
    es = EnergySystem(tariff=Tariff(hourly_prices=list(_TOU)))
    pol = _RecordingPolicy()
    perf = es.simulate_performance([0.0, 10.0], weather, load, dispatch_policy=pol)

    # reset ran exactly once, before the first observation
    assert pol.reset_calls == [(n, 10.0)]
    assert pol.order[0] == "reset"
    assert len(pol.obs_log) == n
    assert pol.order[1:] == ["obs"] * n

    # observation contract: exactly the nine protocol fields, correct values
    for i, obs in enumerate(pol.obs_log):
        assert set(obs) == {
            "t", "hour", "month", "price", "pv_w", "load_w",
            "soc_kwh", "capacity_kwh", "dt_h",
        }
        assert obs["t"] == i
        assert obs["hour"] == int(weather["hour"][i])
        assert obs["month"] == int(weather["month"][i])
        assert obs["price"] == es.tariff.price_for_hour(int(weather["hour"][i]))
        assert obs["pv_w"] == 0.0  # zero PV area
        assert obs["load_w"] == float(load[i])
        assert obs["dt_h"] == 1.0
        assert isinstance(obs["t"], int)
        assert isinstance(obs["hour"], int)
        assert isinstance(obs["month"], int)
        assert isinstance(obs["price"], float)
        assert isinstance(obs["dt_h"], float)
        # idle policy: no throughput, no fade -- capacity stays nameplate and
        # the stored energy stays at soc0 * E_bat
        assert obs["capacity_kwh"] == 10.0
        assert obs["soc_kwh"] == 5.0
    # an idle policy leaves the dispatch exactly empty (recon is 0 too)
    assert perf["battery_charge"].sum() == 0.0
    assert perf["battery_discharge"].sum() == 0.0
    assert perf["battery_recon_grid_kwh"] == 0.0


def test_month_defaults_to_one_without_labels():
    n = 4
    weather, load = _synth_case(n)  # no 'month' key
    es = EnergySystem(tariff=Tariff(hourly_prices=list(_TOU)))
    pol = _RecordingPolicy()
    es.simulate_performance([0.0, 10.0], weather, load, dispatch_policy=pol)
    assert len(pol.obs_log) == n
    assert all(obs["month"] == 1 for obs in pol.obs_log)


def test_policy_not_called_when_no_battery():
    """E_bat = 0: there is nothing to dispatch, so the policy sees no
    observations (reset still reports the horizon and the zero capacity),
    and the grid accounting degenerates to the no-battery formulas."""
    n = 4
    weather, load = _synth_case(n)
    es = EnergySystem(tariff=Tariff(hourly_prices=list(_TOU)))
    pol = _RecordingPolicy()
    perf = es.simulate_performance([40.0, 0.0], weather, load, dispatch_policy=pol)
    assert pol.reset_calls == [(n, 0.0)]
    assert pol.obs_log == []
    pv = es.pv.calculate_pv_output(weather, 40.0)
    assert np.array_equal(perf["grid_import"], np.maximum(0.0, load - pv))
    assert np.array_equal(perf["grid_export"], np.maximum(0.0, pv - load))
    assert perf["battery_recon_grid_kwh"] == 0.0
