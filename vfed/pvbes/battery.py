"""
Battery energy storage model (Zhao et al. 2024 parametric formulation).

Pure-Python, vectorised timestep loop. Power balance ``pv - load`` (kW) is
balanced by the battery within C-rate and SOC limits; the residual is exported
to / imported from the grid by ``EnergySystem``.

    charge   : surplus <= P_charge_max, soc rises by P*eta_ch*dt/E_bat
    discharge: deficit  <= P_discharge_max*eta_dis, soc falls accordingly

P1-2: with ``allow_grid_charging=True`` the battery additionally buys grid
power in valley-price hours (price == tariff minimum) to top up SOC, so the
stored energy can later be discharged into higher-priced hours (TOU
arbitrage).  Simple greedy, no optimisation: arbitrage is enabled only when
the tariff's peak price exceeds the round-trip breakeven
    ``valley / (eta_ch * eta_dis)`` — flat tariffs never qualify, so the default
    ``False`` (PV charging only) dispatch path is bitwise unchanged.

P2-4: usable capacity fades linearly with accumulated equivalent cycles
(``soh_eol`` = capacity fraction at ``cycle_life`` cycles, default 0.80).
The fade applies inside the dispatch loop (C-rate limit, SOC headroom, SOC
update denominators); ``battery_cycles`` keeps its nameplate-capacity
definition so replacement timing (P4-15) is unchanged.  ``soh_eol = 1.0``
disables the fade (bitwise legacy dispatch).

G10 (independent power rating): ``power_kw`` optionally decouples the PCS
rated charge/discharge power from the energy capacity.  ``None`` (default)
keeps the legacy cell-side cap ``c_rate * E_now`` bitwise; a number makes the
per-step terminal cap ``min(c_rate * E_now, power_kw)`` so the cell C-rate
and the PCS converter rating constrain simultaneously.  The cap applies to
the charge path, the discharge path and the P1-2 valley grid-charging
headroom (same battery terminals).

G11 (chemistry + calendar aging): ``chemistry`` selects ``legacy`` (linear
cycle fade only, bitwise default), ``lfp`` or ``nmc``.  lfp/nmc add calendar
aging on top of the cycle fade, both in [0, 1] degradation fractions::

    SOH_total = k_cycle * cycles_now + k_cal(T) * sqrt(t_months)
    E_now     = E_bat * max(1 - SOH_total, 1e-3)     (existing clamp kept)

The sqrt-of-time law and its coefficients follow Keil et al. 2016,
"Calendar Aging of Lithium-Ion Batteries I", J. Electrochem. Soc. 163(9)
A1872-A1880, DOI 10.1149/2.0411609jes: calendar fade is SEI-growth driven
and grows linearly with the square root of storage time.  The open-data
anchor file ``docs/references/pvbes-validation/anchors/battery_aging.yaml`` (entry
``keil2016_calendar_aging``, status verified) stores the LFP fade-rate
derivatives measured after 9 months of storage -- ca. 0.2 percentage points
per month at 25 degC and ca. 0.5 pp per month at 50 degC.  For
SOH_cal(t) = k*sqrt(t) the derivative k/(2*sqrt(t)) at t = 9 months gives
k_cal = 2*sqrt(9)*rate, i.e. the coefficient is derived, never guessed.
Between the two anchor temperatures k_cal(T) uses a two-point Arrhenius fit
k = A*exp(-Ea/(R*T)); the anchor pair implies an effective Ea of about
29 kJ/mol, inside the band typical of SEI-growth kinetics that Keil 2016
identify as the calendar-fade driver -- hence Arrhenius rather than a fit
linear in T.  Temperatures outside [25, 50] degC (``temperature_c``, default
25, stands in for the battery temperature) are clamped to the nearest
anchor; the coefficients are not extrapolated beyond the measured range.
NMC coefficients come from the digitized Keil 2016 Fig. 2b 50%-SoC points
(anchor keys nmc_fade_rate_*); if the anchor file lacks them,
``chemistry='nmc'`` raises NotImplementedError instead of inventing numbers.
The legacy calendar clock convention matches the cycle counter: each
``calculate_battery_flows`` call starts from a fresh cell at t = 0.
"""

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

__all__ = ["BatterySystem", "CALENDAR_MONTH_HOURS"]


# ── G11: calendar-aging anchor (open data, Keil 2016) ─────────────────────
CALENDAR_MONTH_HOURS = 365.25 * 24.0 / 12.0  # hours per average month (730.5)

_CAL_ANCHOR_RELPATH = ("docs", "references", "pvbes-validation", "anchors", "battery_aging.yaml")
_CAL_DERIV_REF_MONTHS = 9.0  # Keil 2016 evaluated the LFP fade-rate
# derivative after 9 months of storage (anchor note quotes the paper).
_CAL_T_COLD_C = 25.0  # cold anchor temperature (degC)
_CAL_T_HOT_C = 50.0  # hot anchor temperature (degC)
_KELVIN = 273.15
_CAL_ANCHOR_CACHE: Dict[str, Dict[str, float]] = {}

_NMC_TO_FOLLOW_MSG = (
    "battery chemistry 'nmc' needs anchor data: the calendar-aging anchor "
    "file docs/references/pvbes-validation/anchors/battery_aging.yaml does not "
    "carry the 'nmc_fade_rate_25c_pp_per_month' / "
    "'nmc_fade_rate_50c_pp_per_month' keys (Keil 2016 Fig. 2b digitization, "
    "DOI 10.1149/2.0411609jes). Do not guess numbers."
)


def _cal_anchor_candidates() -> List[Path]:
    """Candidate anchor-file paths: repo root next to this file, then cwd."""
    here = Path(__file__).resolve()
    roots = [here.parents[2], Path.cwd()]
    return [root.joinpath(*_CAL_ANCHOR_RELPATH) for root in roots]


def _load_calendar_coeffs() -> Dict[str, Dict[str, float]]:
    """Per-chemistry sqrt-law calendar coefficients from the anchor yaml.

    Only chemistries with verified anchor data are returned (currently lfp).
    Provenance rule: the numbers come exclusively from
    ``docs/references/pvbes-validation/anchors/battery_aging.yaml`` entry
    ``keil2016_calendar_aging`` (status verified).  The anchor stores the LFP
    fade-rate derivatives (percentage points per month) measured after 9
    months of storage at 25 degC and 50 degC; for SOH_cal(t) = k*sqrt(t)
    (t in months) the derivative k/(2*sqrt(t)) at t = 9 months gives
    k = 2*sqrt(9)*rate.  Loaded once per process.
    """
    if _CAL_ANCHOR_CACHE:
        return _CAL_ANCHOR_CACHE
    candidates = _cal_anchor_candidates()
    path = next((p for p in candidates if p.is_file()), None)
    if path is None:
        tried = ", ".join(str(p) for p in candidates)
        raise FileNotFoundError(
            "battery chemistry 'lfp'/'nmc' needs the calendar-aging anchor "
            f"file; none of the candidate paths exist: {tried}"
        )
    import yaml  # core dependency, imported lazily: the legacy path never reads files

    entry = yaml.safe_load(path.read_text(encoding="utf-8"))["entries"]["keil2016_calendar_aging"]
    k_cold = (
        2.0
        * math.sqrt(_CAL_DERIV_REF_MONTHS)
        * float(entry["lfp_fade_rate_25c_pp_per_month"])
        / 100.0
    )
    k_hot = (
        2.0
        * math.sqrt(_CAL_DERIV_REF_MONTHS)
        * float(entry["lfp_fade_rate_50c_pp_per_month"])
        / 100.0
    )
    if not (math.isfinite(k_cold) and math.isfinite(k_hot) and 0.0 < k_cold < k_hot):
        raise ValueError(
            "calendar-aging anchor data is inconsistent (expected "
            f"0 < k_25C < k_50C, got k_25C={k_cold!r}, k_50C={k_hot!r}) from {path}"
        )
    _CAL_ANCHOR_CACHE["lfp"] = {"k_cold": k_cold, "k_hot": k_hot}
    # G11 (2026-11): NMC branch from the digitized Fig. 2b 50%-SoC points
    # (end-of-storage derivative after 10 months; same sqrt(t) semantics as
    # the LFP keys but t_ref comes from 'nmc_deriv_ref_months').
    if entry.get("nmc_fade_rate_25c_pp_per_month") is not None:
        t_ref_nmc = float(entry.get("nmc_deriv_ref_months", 10.0))
        k_cold_nmc = (
            2.0 * math.sqrt(t_ref_nmc) * float(entry["nmc_fade_rate_25c_pp_per_month"]) / 100.0
        )
        k_hot_nmc = (
            2.0 * math.sqrt(t_ref_nmc) * float(entry["nmc_fade_rate_50c_pp_per_month"]) / 100.0
        )
        if not (
            math.isfinite(k_cold_nmc) and math.isfinite(k_hot_nmc) and 0.0 < k_cold_nmc < k_hot_nmc
        ):
            raise ValueError(
                "calendar-aging anchor data is inconsistent (expected "
                f"0 < k_25C < k_50C for nmc, got k_25C={k_cold_nmc!r}, "
                f"k_50C={k_hot_nmc!r}) from {path}"
            )
        _CAL_ANCHOR_CACHE["nmc"] = {"k_cold": k_cold_nmc, "k_hot": k_hot_nmc}
    return _CAL_ANCHOR_CACHE


def _arrhenius_interp(temperature_c: float, k_cold: float, k_hot: float) -> float:
    """Two-point Arrhenius interpolation of k_cal between the 25/50 degC
    anchors, clamped to the validated range.

    k(T) = A*exp(-Ea/(R*T)) fitted through (25 degC, k_cold) and
    (50 degC, k_hot).  The anchor pair implies an effective Ea of roughly
    29 kJ/mol, consistent with the SEI-growth kinetics Keil 2016 identify as
    the calendar-fade driver -- hence Arrhenius rather than linear in T.
    Outside [25, 50] degC the nearest anchor value is used (no extrapolation
    beyond the measured range).
    """
    t_c = min(_CAL_T_HOT_C, max(_CAL_T_COLD_C, float(temperature_c)))
    t_cold_k = _CAL_T_COLD_C + _KELVIN
    t_hot_k = _CAL_T_HOT_C + _KELVIN
    t_k = t_c + _KELVIN
    ea_over_r = math.log(k_hot / k_cold) / (1.0 / t_cold_k - 1.0 / t_hot_k)
    return k_cold * math.exp(ea_over_r * (1.0 / t_cold_k - 1.0 / t_k))


@dataclass
class BatterySystem:
    c_energy: float = 220.0  # $/kWh
    c_rate: float = 1.0  # max C-rate (1/h)
    eta_ch: float = 0.91
    eta_dis: float = 0.91
    soc_min: float = 0.10
    soc_max: float = 0.90
    cycle_life: int = 4000  # full (dis)charge cycles to end-of-life.
    # P4-15: equivalent life years = cycle_life /
    # battery_cycles; if < system lifetime a
    # mid-life replacement is due (computed in
    # EnergySystem.calculate_metrics).
    soh_eol: float = 0.80  # P2-4: usable-capacity fraction at end of life
    # (cycle_life equivalent cycles). Linear fade per
    # equivalent cycle: k = (1 - soh_eol) / cycle_life;
    # usable capacity = E_bat * max(1 - k*cycles_so_far,
    # 1e-3). 0.80 = industry-standard EOL criterion (80%
    # of initial capacity); 1.0 disables the fade (k = 0,
    # bitwise legacy dispatch). Cycles are counted against
    # NAMEPLATE capacity (EFC convention), matching the
    # battery_cycles return; replacement year (P4-15) is
    # therefore unchanged. layerD B4: a no-fade model
    # implied 11.0 yr life vs Sandia 6.7-10 yr @ 1 cyc/d.
    self_discharge: float = 0.0  # per hour (fraction)
    maintenance: float = 0.01  # LEGACY (P4-15/P5): config field removed,
    # never read anywhere; kept for interface
    # stability only.
    allow_grid_charging: bool = False  # P1-2: TOU arbitrage — buy grid power
    # in valley-price hours (price == tariff min) to displace peak-price
    # imports later.  Gated on peak > valley/(eta_ch*eta_dis) (round-trip
    # breakeven); flat tariffs are a no-op.  Default False = legacy
    # PV-charging-only dispatch, bitwise unchanged.
    power_kw: Optional[float] = None  # G10: PCS rated charge/discharge power
    # (kW).  None = legacy cap c_rate*E_now (bitwise); a positive number
    # makes the per-step charge AND discharge terminal cap
    # min(c_rate*E_now, power_kw) — the cell C-rate and the PCS converter
    # rating both apply.  Also caps the P1-2 valley grid-charging headroom.
    chemistry: str = "legacy"  # G11: 'legacy' | 'lfp' | 'nmc' (exact,
    # case-sensitive, pure ASCII).  legacy = linear cycle fade only
    # (bitwise default, no calendar term).  lfp adds the sqrt(t) calendar
    # fade from the Keil 2016 anchor.  nmc is structurally wired but raises
    # NotImplementedError until the anchor file carries the digitized
    # Keil 2016 NMC coefficients (anchor status: to_follow).
    temperature_c: float = 25.0  # G11: battery/ambient temperature (degC)
    # driving k_cal(T) when calendar aging is on; clamped to the validated
    # [25, 50] degC anchor range.

    def __post_init__(self) -> None:
        # G10/G11 fail-fast contract checks (pure ASCII messages).
        if self.power_kw is not None and (not math.isfinite(self.power_kw) or self.power_kw <= 0.0):
            raise ValueError(
                "battery power_kw must be a positive finite number (kW), " f"got {self.power_kw!r}"
            )
        if self.chemistry not in ("legacy", "lfp", "nmc"):
            raise ValueError(
                f"battery chemistry {self.chemistry!r} is not one of " "'legacy', 'lfp', 'nmc'"
            )
        if not math.isfinite(self.temperature_c) or self.temperature_c <= -_KELVIN:
            raise ValueError(
                "battery temperature_c must be finite and above absolute "
                f"zero (degC), got {self.temperature_c!r}"
            )

    def calendar_sqrt_coeff(self) -> float:
        """k_cal(T) — calendar-fade fraction per sqrt(month) for this chemistry.

        Returns 0.0 for 'legacy' (calendar aging off).  For 'lfp' and 'nmc'
        the two anchor coefficients (25 degC, 50 degC, Keil 2016; NMC from
        the digitized Fig. 2b 50%-SoC points) are combined with the
        two-point Arrhenius fit at ``self.temperature_c`` (clamped to
        [25, 50] degC).  'nmc' raises NotImplementedError only when the
        anchor file does not carry its digitized rates.
        """
        if self.chemistry == "legacy":
            return 0.0
        coeffs = _load_calendar_coeffs().get(self.chemistry)
        if coeffs is None:
            raise NotImplementedError(_NMC_TO_FOLLOW_MSG)
        return _arrhenius_interp(self.temperature_c, coeffs["k_cold"], coeffs["k_hot"])

    def calendar_fade(self, elapsed_hours: float) -> float:
        """Capacity fraction lost to calendar aging after ``elapsed_hours``
        of storage from new: k_cal(T) * sqrt(t_months) (Keil 2016
        sqrt-of-time SEI growth law).  Zero for 'legacy'.
        """
        if self.chemistry == "legacy" or elapsed_hours <= 0.0:
            return 0.0
        return self.calendar_sqrt_coeff() * math.sqrt(elapsed_hours / CALENDAR_MONTH_HOURS)

    def calculate_battery_flows(
        self,
        power_balance: np.ndarray,  # pv - load (kW)
        load_profile: np.ndarray,  # kW (used only for shape)
        E_bat: float,
        dt: float = 1.0,
        soc0: float = 0.5,
        hourly_prices: Optional[List[float]] = None,  # P1-2: tariff table
        hours: Optional[np.ndarray] = None,  # hour-of-day per timestep
    ) -> Dict[str, np.ndarray]:
        n = len(power_balance)

        # ── P1-2: TOU grid-charging setup (fail-fast, no silent fallback) ──
        if self.allow_grid_charging and (hourly_prices is None or hours is None):
            raise ValueError(
                "battery.allow_grid_charging=True requires the tariff "
                "hourly_prices and the hour-of-day array; EnergySystem "
                "supplies both automatically."
            )
        grid_charged = np.zeros(n)  # kW bought from the grid for charging
        grid_charging_on = False
        valley_set: frozenset = frozenset()
        n_p = 0
        if self.allow_grid_charging and E_bat > 0 and n > 0:
            prices = np.asarray(hourly_prices, dtype=float)
            if prices.size == 0:
                raise ValueError("hourly_prices must be non-empty when allow_grid_charging=True")
            if len(hours) != n:
                raise ValueError(
                    f"hours length {len(hours)} != power_balance length {n} "
                    "(allow_grid_charging=True)"
                )
            n_p = int(prices.size)
            p_min = float(prices.min())
            p_max = float(prices.max())
            # Arbitrage pays only if some hour repays the round-trip loss:
            # 1 kWh bought at valley returns eta_ch*eta_dis kWh, so it must
            # displace a price > valley/(eta_ch*eta_dis).  A flat tariff
            # (p_max == p_min) never qualifies -> exact no-op.
            if p_max > p_min / max(self.eta_ch * self.eta_dis, 1e-9) + 1e-12:
                grid_charging_on = True
                valley_set = frozenset(h for h in range(n_p) if float(prices[h]) <= p_min + 1e-12)

        battery_power = np.zeros(n)  # signed: + discharge, - charge
        battery_discharge = np.zeros(n)  # kW delivered to load
        battery_charge = np.zeros(n)  # kW into battery
        battery_soc = np.zeros(n)
        soc = float(soc0)
        total_charged = 0.0
        total_discharged = 0.0
        # ── P2-4: linear SOH fade setup ──────────────────────────────────
        # Usable capacity fades with accumulated equivalent cycles: SOH =
        # 1 - k * cycles_now, k = (1 - soh_eol) / cycle_life.  soh_eol = 1.0
        # -> k = 0 -> E_now == E_bat for every step (bitwise legacy
        # dispatch).  cycles_now counts storage-side throughput against
        # NAMEPLATE capacity, i.e. exactly the running sum behind the
        # battery_cycles return.
        soh_k = (1.0 - self.soh_eol) / max(int(self.cycle_life), 1)
        cycles_now = 0.0
        E_now = E_bat
        # ── G11: calendar-aging coefficient.  0.0 for legacy (the term
        # never enters the dispatch); 'nmc' raises NotImplementedError here,
        # before any work is done (anchor data to_follow). ────────────────
        k_cal = self.calendar_sqrt_coeff()
        for i in range(n):
            net = power_balance[i]
            soc *= 1.0 - self.self_discharge * dt
            if E_bat <= 0:
                battery_soc[i] = 0.0
                continue
            # ── G10: effective terminal power cap.  None keeps the legacy
            # cell-side limit c_rate*E_now bitwise; a power_kw rating makes
            # the PCS and the cell C-rate constrain simultaneously. ────────
            if self.power_kw is None:
                p_crate_cap = self.c_rate * E_now
            else:
                p_crate_cap = min(self.c_rate * E_now, self.power_kw)
            p_charge_max = min(p_crate_cap, (self.soc_max - soc) * E_now / dt)
            p_discharge_max = min(p_crate_cap, (soc - self.soc_min) * E_now / dt) * self.eta_dis
            if net >= 0:  # surplus -> charge
                ch = min(net, max(0.0, p_charge_max))
                soc += ch * self.eta_ch * dt / E_now
                battery_charge[i] = ch
                battery_power[i] = -ch
                total_charged += ch * dt
            else:  # deficit -> discharge
                deficit = -net
                dch = min(deficit, max(0.0, p_discharge_max))
                soc -= dch * dt / (self.eta_dis * E_now)
                battery_discharge[i] = dch
                battery_power[i] = dch
                total_discharged += dch * dt
            soc = min(self.soc_max, max(self.soc_min, soc))
            battery_soc[i] = soc

            # ── P1-2: valley-hour grid top-up (after the normal PV step) ──
            # Greedy: fill remaining headroom at the valley price; the extra
            # SOC is discharged by the existing deficit path into (on
            # average) higher-priced hours.  Skipped entirely unless the
            # tariff passed the round-trip breakeven check above.
            if grid_charging_on and int(hours[i]) % n_p in valley_set:
                headroom = min(p_crate_cap, (self.soc_max - soc) * E_now / dt)
                g = max(0.0, headroom)
                if g > 0.0:
                    soc += g * self.eta_ch * dt / E_now
                    battery_charge[i] += g
                    grid_charged[i] = g
                    total_charged += g * dt
                    soc = min(self.soc_max, max(self.soc_min, soc))
                    battery_soc[i] = soc

            # ── P2-4: age the cell by this step's throughput (nameplate
            # EFC), then refresh the usable capacity for the next step.
            # G11: calendar aging (lfp) adds k_cal*sqrt(t_months) on top of
            # the linear cycle fade; the combined degradation keeps the
            # existing 1e-3 clamp.  Legacy (k_cal == 0) never enters the
            # calendar branch — the fade expression stays bitwise identical.
            cycles_now += (
                (battery_charge[i] * self.eta_ch + battery_discharge[i] / max(self.eta_dis, 0.01))
                * dt
                / (2.0 * E_bat)
            )
            fade = soh_k * cycles_now
            if k_cal > 0.0:
                fade += k_cal * math.sqrt((i + 1) * dt / CALENDAR_MONTH_HOURS)
            E_now = E_bat * max(1.0 - fade, 1e-3)

        # ── Year-end periodic reconciliation (P4-18) ──────────────────────
        # Dispatch starts at soc0 but is not guaranteed to end there, leaving
        # E_now*(soc_end - soc0) of stored energy unaccounted in the annual
        # balance.  P2-4: the stored energy at year end sits in the FADED
        # capacity E_now (== E_bat when the fade is off), so the correction
        # must use E_now, not nameplate, to keep the annual identity exact.
        # Restore the periodic SOC boundary and report the electrical energy
        # that must cross the grid interface so that
        # pv + import + discharge = load + charge + export closes exactly.
        # EnergySystem applies it to both the battery and grid sides at the
        # last timestep (signed: + import / top-up, - export / dump).
        soc_end = float(soc)
        soc_target = min(self.soc_max, max(self.soc_min, float(soc0)))
        recon_grid_kwh = 0.0
        if E_bat > 0 and n > 0:
            need_stored = E_now * (soc_target - soc_end)
            if need_stored > 0.0:
                recon_grid_kwh = need_stored / self.eta_ch  # grid top-up (import)
                total_charged += recon_grid_kwh
            elif need_stored < 0.0:
                recon_grid_kwh = -(-need_stored) * self.eta_dis  # dump (export)
                total_discharged += -recon_grid_kwh
            battery_soc[-1] = soc_target
        return {
            "battery_power": battery_power,
            "battery_discharge": battery_discharge,
            "battery_charge": battery_charge,
            "battery_soc": battery_soc,
            # P1-2: grid power bought for valley charging (kW).  Zero array
            # unless allow_grid_charging=True and the tariff qualifies;
            # EnergySystem routes it into grid_import (never against export).
            "grid_charged": grid_charged,
            "total_charged": total_charged,
            "total_discharged": total_discharged,
            "battery_cycles": (
                total_charged * self.eta_ch + total_discharged / max(self.eta_dis, 0.01)
            )
            / (2.0 * E_bat)
            if E_bat > 0
            else 0.0,
            "soc_end": soc_end,
            "recon_grid_kwh": recon_grid_kwh,
        }

    def calculate_costs(self, E_bat: float) -> Dict[str, float]:
        return {
            "energy_capacity_kwh": E_bat,
            "capital_cost": E_bat * self.c_energy,
        }
