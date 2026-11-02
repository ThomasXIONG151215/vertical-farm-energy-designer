"""Wave 1 gate: battery G10 (independent power rating) + G11 (chemistry and
calendar aging).

Provenance rule: every anchor number is read at test time from
``reference/pvbes-validation/anchors/battery_aging.yaml`` (Keil et al. 2016,
J. Electrochem. Soc. 163(9) A1872-A1880, DOI 10.1149/2.0411609jes); no
anchor value is inlined in this file.  Synthetic pure-formula tests (bitwise
legacy recomputation, G10 cap saturation) are exempt from the file rule per
the Wave 1 task brief.

Gates:
- legacy defaults (power_kw=None, chemistry='legacy') stay bit-identical to
  the pre-G10/G11 dispatch formulas (helper recomputes the old algebra);
- G10: hourly charge/discharge power <= min(c_rate*E_now, power_kw) on the
  PCS-binding and C-rate-binding sides, valley grid charging included; a
  huge power_kw degenerates to the legacy cap bitwise;
- G11: SOH monotonically non-increasing through dispatch; LFP annual
  calendar fade at 25 degC inside the anchor-derived envelope; 50 degC fades
  faster than 25 degC (Arrhenius monotone); sqrt(t) law (4x time -> 2x
  fade); invalid chemistry raises ValueError; NMC reports 'not implemented'
  honestly (anchor NMC data is to_follow).
"""

import math
from pathlib import Path

import numpy as np
import pytest
import yaml

from vfed.pvbes.battery import CALENDAR_MONTH_HOURS, BatterySystem

REPO_ROOT = Path(__file__).resolve().parents[1]
ANCHOR_PATH = REPO_ROOT / "reference" / "pvbes-validation" / "anchors" / "battery_aging.yaml"
KEIL_ENTRY = "keil2016_calendar_aging"

# E_bat used by the pure-storage probes below (kWh, synthetic).
PROBE_E_BAT = 10.0


# ---------------------------------------------------------------------------
# Anchor reading (no inline anchor numbers)
# ---------------------------------------------------------------------------
def _anchor() -> dict:
    assert ANCHOR_PATH.is_file(), f"calendar-aging anchor file missing: {ANCHOR_PATH}"
    return yaml.safe_load(ANCHOR_PATH.read_text(encoding="utf-8"))["entries"][KEIL_ENTRY]


def _lfp_anchor_sqrt_coeffs():
    """(k_25C, k_50C) derived from the anchor LFP fade-rate derivatives.

    The anchor stores the LFP capacity-fade derivative (percentage points
    per month) that Keil 2016 evaluated after 9 months of storage ("ca. 0.2
    pp per month at 25 degC and ca. 0.5 pp per month at 50 degC").  For the
    anchor's own model form SOH_cal(t) = k*sqrt(t_months) the derivative is
    k/(2*sqrt(t)), so at t = 9 months k = 2*sqrt(9)*rate.  The 9-month
    reference age is the derivation context quoted in the anchor note (the
    measurement itself -- the rate -- comes from the file).
    """
    entry = _anchor()
    deriv_ref_months = 9.0
    k25 = 2.0 * math.sqrt(deriv_ref_months) * float(entry["lfp_fade_rate_25c_pp_per_month"]) / 100.0
    k50 = 2.0 * math.sqrt(deriv_ref_months) * float(entry["lfp_fade_rate_50c_pp_per_month"]) / 100.0
    return k25, k50


# ---------------------------------------------------------------------------
# Synthetic helpers (formula recomputation -- exempt from the file rule)
# ---------------------------------------------------------------------------
def _reference_legacy_dispatch(balance, E_bat, dt=1.0, soc0=0.5):
    """Verbatim recomputation of the pre-G10/G11 dispatch formulas.

    Written from the original battery.py algebra: c_rate*E_now caps (no
    power_kw), linear cycle fade only (no calendar term), defaults
    c_rate=1.0, eta_ch=eta_dis=0.91, soc 0.10/0.90, soh_eol=0.80,
    cycle_life=4000, self_discharge=0, allow_grid_charging=False.
    """
    c_rate, eta_ch, eta_dis = 1.0, 0.91, 0.91
    soc_min, soc_max = 0.10, 0.90
    soh_k = (1.0 - 0.80) / 4000
    n = len(balance)
    battery_power = np.zeros(n)
    battery_discharge = np.zeros(n)
    battery_charge = np.zeros(n)
    battery_soc = np.zeros(n)
    soc = float(soc0)
    total_charged = 0.0
    total_discharged = 0.0
    cycles_now = 0.0
    E_now = E_bat
    for i in range(n):
        net = balance[i]
        if E_bat <= 0:
            battery_soc[i] = 0.0
            continue
        p_charge_max = min(c_rate * E_now, (soc_max - soc) * E_now / dt)
        p_discharge_max = min(c_rate * E_now, (soc - soc_min) * E_now / dt) * eta_dis
        if net >= 0:
            ch = min(net, max(0.0, p_charge_max))
            soc += ch * eta_ch * dt / E_now
            battery_charge[i] = ch
            battery_power[i] = -ch
            total_charged += ch * dt
        else:
            deficit = -net
            dch = min(deficit, max(0.0, p_discharge_max))
            soc -= dch * dt / (eta_dis * E_now)
            battery_discharge[i] = dch
            battery_power[i] = dch
            total_discharged += dch * dt
        soc = min(soc_max, max(soc_min, soc))
        battery_soc[i] = soc
        cycles_now += (
            battery_charge[i] * eta_ch + battery_discharge[i] / max(eta_dis, 0.01)
        ) * dt / (2.0 * E_bat)
        E_now = E_bat * max(1.0 - soh_k * cycles_now, 1e-3)
    soc_end = float(soc)
    soc_target = min(soc_max, max(soc_min, float(soc0)))
    recon_grid_kwh = 0.0
    if E_bat > 0 and n > 0:
        need_stored = E_now * (soc_target - soc_end)
        if need_stored > 0.0:
            recon_grid_kwh = need_stored / eta_ch
            total_charged += recon_grid_kwh
        elif need_stored < 0.0:
            recon_grid_kwh = -(-need_stored) * eta_dis
            total_discharged += -recon_grid_kwh
        battery_soc[-1] = soc_target
    battery_cycles = (
        total_charged * eta_ch + total_discharged / max(eta_dis, 0.01)
    ) / (2.0 * E_bat)
    return {
        "battery_power": battery_power,
        "battery_discharge": battery_discharge,
        "battery_charge": battery_charge,
        "battery_soc": battery_soc,
        "grid_charged": np.zeros(n),
        "total_charged": total_charged,
        "total_discharged": total_discharged,
        "battery_cycles": battery_cycles,
        "soc_end": soc_end,
        "recon_grid_kwh": recon_grid_kwh,
    }


def _pure_storage_probe(chemistry, temperature_c, n_steps):
    """Isolate calendar aging inside a real dispatch run.

    ``n_steps - 1`` idle hours (zero power balance -> zero throughput, so
    the cycle fade stays at 0) followed by one huge-surplus step.  With
    soc0 pinned at soc_min and c_rate = 1.0 > soc_max - soc_min = 0.8, the
    final charge step is headroom-limited at exactly
    (soc_max - soc_min)*E_now, so ``battery_charge[-1]`` reads the faded
    E_now.  The reading reflects aging accumulated through the end of step
    n_steps - 2, i.e. (n_steps - 1)*dt hours of calendar time.

    Returns (fade_fraction, elapsed_hours_at_reading).
    """
    bal = np.zeros(n_steps)
    bal[-1] = 1e6  # far above any cap -> the binding cap is read exactly
    bat = BatterySystem(chemistry=chemistry, temperature_c=temperature_c)
    out = bat.calculate_battery_flows(bal, np.zeros(n_steps), PROBE_E_BAT, dt=1.0, soc0=0.10)
    ch = float(out["battery_charge"][-1])
    assert ch > 0.0, "probe step did not charge -- headroom-limited read failed"
    e_now = ch / 0.8
    return 1.0 - e_now / PROBE_E_BAT, float(n_steps - 1)


def _cycling_soh_readings(chemistry, temperature_c, n_steps):
    """E_now/E_bat readings from headroom-limited charge steps under
    cycling: alternating huge surplus / huge deficit pins SOC back to
    soc_min before every charge step, so every even-index step reads
    0.8*E_now exactly (charge path) while aging accumulates."""
    bal = np.where(np.arange(n_steps) % 2 == 0, 100.0, -100.0)
    bat = BatterySystem(chemistry=chemistry, temperature_c=temperature_c)
    out = bat.calculate_battery_flows(bal, np.zeros(n_steps), PROBE_E_BAT, dt=1.0, soc0=0.10)
    charge = out["battery_charge"]
    readings = charge[0::2] / 0.8 / PROBE_E_BAT
    assert (readings > 0.0).all()
    return readings


# ---------------------------------------------------------------------------
# 34.1  Legacy bitwise identity (gate: default path unchanged)
# ---------------------------------------------------------------------------
def test_legacy_dispatch_bitwise_against_pre_change_formulas():
    """power_kw=None + chemistry='legacy' must reproduce the pre-G10/G11
    formulas bit-for-bit on a synthetic PV/load series."""
    rng = np.random.default_rng(7)
    n = 24 * 14
    pv = np.clip(rng.normal(1.5, 1.0, n), 0.0, None)
    load = np.clip(rng.normal(1.0, 0.3, n), 0.0, None)
    balance = pv - load
    E_bat = 20.0

    out = BatterySystem().calculate_battery_flows(balance, load, E_bat, dt=1.0, soc0=0.5)
    ref = _reference_legacy_dispatch(balance, E_bat, dt=1.0, soc0=0.5)

    for key in ("battery_power", "battery_discharge", "battery_charge", "battery_soc"):
        assert np.array_equal(out[key], ref[key]), f"{key} drifted from the legacy formulas"
    for key in ("total_charged", "total_discharged", "battery_cycles", "soc_end", "recon_grid_kwh"):
        assert out[key] == ref[key], f"{key} drifted from the legacy formulas"
    assert np.array_equal(out["grid_charged"], ref["grid_charged"])


# ---------------------------------------------------------------------------
# 34.2  G10 — independent power rating
# ---------------------------------------------------------------------------
def test_power_kw_caps_terminal_power():
    """power_kw=5 with c_rate*E_now ~ 50 kW: every charge step <= 5 kW, every
    discharge step <= 5*eta_dis, and the cap saturates exactly when the
    surplus/deficit far exceeds it."""
    n = 16
    bal = np.concatenate([np.full(8, 20.0), np.full(8, -20.0)])
    bat = BatterySystem(power_kw=5.0)
    out = bat.calculate_battery_flows(bal, np.zeros(n), 50.0, dt=1.0, soc0=0.5)

    assert out["battery_charge"].max() <= 5.0 + 1e-9
    assert out["battery_discharge"].max() <= 5.0 * 0.91 + 1e-9
    # first steps: SOC headroom not binding (soc ~ 0.5 -> 0.8), net 20 >> 5
    # -> charge pins at exactly the PCS cap
    assert (out["battery_charge"][:4] == 5.0).all()
    assert out["battery_discharge"][8] == pytest.approx(5.0 * 0.91, abs=1e-12)


def test_power_kw_crate_side_still_binds():
    """With power_kw above c_rate*E_now the cell C-rate stays the effective
    cap: min(c_rate*E_now, power_kw) = c_rate*E_now."""
    bal = np.concatenate([np.full(8, 20.0), np.full(8, -20.0)])
    out = BatterySystem(power_kw=50.0, c_rate=0.05).calculate_battery_flows(
        bal, np.zeros(16), 50.0, dt=1.0, soc0=0.5
    )
    # c_rate*E_now = 2.5 kW < power_kw = 50 -> charge <= 2.5, saturating
    assert out["battery_charge"].max() <= 2.5 + 1e-9
    assert out["battery_charge"][0] == 2.5  # exact cap before any fade
    assert out["battery_discharge"].max() <= 2.5 * 0.91 + 1e-9


def test_power_kw_huge_degrades_to_legacy_bitwise():
    """A power_kw far above c_rate*E_now is a no-op: dispatch output is
    bitwise equal to the power_kw=None run."""
    rng = np.random.default_rng(11)
    n = 24 * 10
    balance = rng.normal(0.0, 2.0, n)
    a = BatterySystem(power_kw=1e9).calculate_battery_flows(balance, np.zeros(n), 15.0, dt=1.0, soc0=0.5)
    b = BatterySystem().calculate_battery_flows(balance, np.zeros(n), 15.0, dt=1.0, soc0=0.5)
    for key in ("battery_power", "battery_discharge", "battery_charge", "battery_soc"):
        assert np.array_equal(a[key], b[key]), f"{key} changed under a huge power_kw"
    for key in ("total_charged", "total_discharged", "battery_cycles", "soc_end", "recon_grid_kwh"):
        assert a[key] == b[key]


def test_power_kw_caps_valley_grid_charging():
    """The P1-2 valley grid top-up flows through the same terminals, so
    power_kw caps it too."""
    n = 48
    hours = np.arange(n) % 24
    prices = [0.1] * 8 + [1.2] * 16  # valleys = hours 0-7, peak 1.2 > 0.1/0.8281
    load = np.full(n, 0.5)
    pv = np.zeros(n)  # night valleys: no PV surplus in valley hours
    bat = BatterySystem(allow_grid_charging=True, power_kw=3.0)
    out = bat.calculate_battery_flows(
        pv - load, load, 50.0, dt=1.0, soc0=0.5, hourly_prices=prices, hours=hours
    )
    assert out["grid_charged"].sum() > 0.0, "valley charging did not activate"
    assert out["grid_charged"].max() <= 3.0 + 1e-9
    assert out["battery_charge"].max() <= 3.0 + 1e-9
    # first valley step: SOC mid-range -> headroom not binding -> exact cap
    assert out["grid_charged"][0] == 3.0


def test_power_kw_and_temperature_contract_raise():
    with pytest.raises(ValueError, match="power_kw"):
        BatterySystem(power_kw=0.0)
    with pytest.raises(ValueError, match="power_kw"):
        BatterySystem(power_kw=-5.0)
    with pytest.raises(ValueError, match="temperature_c"):
        BatterySystem(temperature_c=-300.0)
    BatterySystem(power_kw=1.0, temperature_c=-10.0)  # valid: above 0 K


# ---------------------------------------------------------------------------
# 34.3  G11 — chemistry validation + calendar aging
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("bad", ["NMC", "LFP", "Legacy", "lfp ", "nca", "lead_acid", ""])
def test_invalid_chemistry_raises(bad):
    with pytest.raises(ValueError, match="chemistry"):
        BatterySystem(chemistry=bad)


def test_legacy_has_no_calendar_aging():
    bat = BatterySystem()
    assert bat.calendar_sqrt_coeff() == 0.0
    assert bat.calendar_fade(8760.0) == 0.0


def test_soh_monotone_nondecreasing_fade():
    """Under cycling at 50 degC (fast calendar fade) the usable capacity
    read through headroom-limited charge steps never increases."""
    readings = _cycling_soh_readings(chemistry="lfp", temperature_c=50.0, n_steps=24 * 60)
    assert np.all(np.diff(readings) <= 1e-12), "usable capacity increased at some step"
    assert readings[-1] < readings[0], "no aging accumulated over the run"
    assert readings[-1] > 1e-3, "capacity collapsed to the clamp prematurely"


def test_lfp_annual_calendar_fade_inside_anchor_envelope():
    """LFP stored one year at 25 degC: the dispatch-integrated calendar fade
    must land inside the envelope implied by the anchor-derived coefficient
    k_25C*sqrt(t_months).  The +/-10% band covers the uncertainty of the
    derivative->coefficient extraction (the anchor warns the derivative is
    a local rate, not a long-term linear slope)."""
    n = 8760  # idle storage, then one probe step -> reading age n-1 hours
    bat = BatterySystem(chemistry="lfp", temperature_c=25.0)
    assert bat.calendar_sqrt_coeff() > 0.0
    fade, t_hours = _pure_storage_probe("lfp", 25.0, n)
    k25, _ = _lfp_anchor_sqrt_coeffs()
    expected = k25 * math.sqrt(t_hours / CALENDAR_MONTH_HOURS)
    assert 0.0 < expected < 0.08, f"anchor-derived annual fade is unphysical: {expected!r}"
    assert fade == pytest.approx(expected, rel=0.10)
    assert 0.0 < fade < 0.10  # a few percent per year, never catastrophic


def test_sqrt_t_law_quadruple_time_doubles_fade():
    """4x storage time -> exactly 2x calendar fade (sqrt-of-time law)."""
    fade_short, t_short = _pure_storage_probe("lfp", 25.0, 2191)  # reading at 2190 h
    fade_long, t_long = _pure_storage_probe("lfp", 25.0, 8761)  # reading at 8760 h
    assert t_long == 4 * t_short
    assert fade_long == pytest.approx(2.0 * fade_short, rel=1e-9)
    # closed-form helper agrees with the dispatch-integrated reading
    bat = BatterySystem(chemistry="lfp", temperature_c=25.0)
    assert bat.calendar_fade(4.0 * t_short) == pytest.approx(2.0 * bat.calendar_fade(t_short), rel=1e-9)
    assert bat.calendar_fade(t_long) == pytest.approx(fade_long, rel=1e-9)


def test_hotter_temperature_fades_faster():
    """50 degC fades strictly faster than 25 degC, with the same ratio the
    two anchor coefficients imply (Arrhenius fit through both anchors)."""
    fade25, _ = _pure_storage_probe("lfp", 25.0, 2000)
    fade50, _ = _pure_storage_probe("lfp", 50.0, 2000)
    assert fade50 > fade25
    k25, k50 = _lfp_anchor_sqrt_coeffs()
    assert fade50 / fade25 == pytest.approx(k50 / k25, rel=1e-9)


def test_temperature_clamped_to_anchor_range():
    """k_cal(T) is exact at both anchors and clamped outside [25, 50] degC
    (no extrapolation beyond the validated range)."""
    below = BatterySystem(chemistry="lfp", temperature_c=10.0).calendar_sqrt_coeff()
    at25 = BatterySystem(chemistry="lfp", temperature_c=25.0).calendar_sqrt_coeff()
    mid = BatterySystem(chemistry="lfp", temperature_c=40.0).calendar_sqrt_coeff()
    at50 = BatterySystem(chemistry="lfp", temperature_c=50.0).calendar_sqrt_coeff()
    above = BatterySystem(chemistry="lfp", temperature_c=90.0).calendar_sqrt_coeff()
    assert below == at25  # clamped to the cold anchor, bitwise
    assert above == at50  # clamped to the hot anchor, bitwise
    assert at25 < mid < at50  # strictly increasing inside the range
    k25, k50 = _lfp_anchor_sqrt_coeffs()
    assert at25 == k25  # Arrhenius fit reproduces the anchor exactly
    assert at50 == pytest.approx(k50, rel=1e-12)


def test_nmc_dispatch_runs_with_digitized_anchor():
    """NMC dispatches with calendar aging from the digitized Fig. 2b anchor
    (end-of-storage derivative keys); no numbers are invented in code."""
    entry = _anchor()
    if entry.get("nmc_fade_rate_25c_pp_per_month") is None:
        pytest.fail(
            "anchor no longer carries the digitized NMC rates but this test "
            "expects them -- reconcile battery.py with battery_aging.yaml"
        )
    bat = BatterySystem(chemistry="nmc")
    assert bat.calculate_costs(10.0)["capital_cost"] == 10.0 * bat.c_energy
    # dispatch runs end to end and applies a nonzero calendar fade
    out = bat.calculate_battery_flows(np.zeros(10), np.zeros(10), 5.0)
    assert out is not None
    assert bat.calendar_sqrt_coeff() > 0.0


def test_nmc_vs_lfp_matches_digitized_physics():
    """Digitized Keil 2016 physics: at 50 degC NMC calendar fade exceeds LFP
    (NMC mid/high-SoC fade is among the highest); at 25 degC the two are
    comparable (digitized 2.7% vs 2.9% over the storage period -- NMC does
    NOT dominate at room temperature)."""
    entry = _anchor()
    if entry.get("nmc_fade_rate_25c_pp_per_month") is None:
        pytest.skip("NMC digitized rates absent from the anchor")
    k_nmc_50 = BatterySystem(chemistry="nmc", temperature_c=50.0).calendar_sqrt_coeff()
    k_lfp_50 = BatterySystem(chemistry="lfp", temperature_c=50.0).calendar_sqrt_coeff()
    assert k_nmc_50 > k_lfp_50
    k_nmc_25 = BatterySystem(chemistry="nmc", temperature_c=25.0).calendar_sqrt_coeff()
    k_lfp_25 = BatterySystem(chemistry="lfp", temperature_c=25.0).calendar_sqrt_coeff()
    # comparable within digitization uncertainty (no ordering imposed at 25C)
    assert 0.5 < k_nmc_25 / k_lfp_25 < 1.5
    # temperature monotonicity holds for both chemistries
    assert k_nmc_25 < k_nmc_50
    assert k_lfp_25 < k_lfp_50
