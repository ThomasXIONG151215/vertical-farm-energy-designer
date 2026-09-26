"""
USD-baseline default prices and the currency-conversion helper (round 26).

Currency model (decided in m0479/m0484, one rule, no exceptions):

* An EXPLICIT price written in the project YAML is a literal value in the
  project's own currency.  It is NEVER converted, whatever ``currency`` and
  ``exchange_rate`` say.
* An OMITTED price (the ``None`` sentinel, same pattern as the round-21
  ``capital.cost`` F2 sentinel) falls back to the built-in USD-baseline
  default below.  ``DesignProject.from_dict`` materializes that default into
  the project currency by multiplying it with ``exchange_rate``
  (``usd_base_to_project``).  USD projects (or ``exchange_rate: 1.0``) get
  the raw constant back -- bitwise zero drift.
* ``exchange_rate`` is user-set in the YAML (reproducible, offline): it is
  the number of project-currency units per 1 USD (7.2 = CNY).  The built-in
  reference snapshot below is printed by ``vfed design fx``; it is a
  convenience, never an automatic lookup.

``maintenance_pct`` is a fraction of capital (unitless) and is deliberately
NOT part of the currency engine.
"""

__all__ = [
    "FX_SNAPSHOT",
    "FX_SNAPSHOT_DATE",
    "FX_SOURCE_NOTE",
    "USD_C_PV",
    "USD_C_ENERGY",
    "USD_TARIFF",
    "USD_EXPORT",
    "USD_LABOR",
    "USD_MISC",
    "USD_WATER",
    "USD_RATE_PER_WATT",
    "fx_multiplier",
    "usd_base_to_project",
    "resolve_unit_price",
]

# Built-in reference snapshot (``vfed design fx``).  Mid-market rates,
# project-currency units per 1 USD.  Reference values only -- check live
# rates before setting ``exchange_rate`` in a real project.
FX_SNAPSHOT_DATE = "2026-09-26"
FX_SOURCE_NOTE = "reference mid-market rates (open.er-api.com); verify live rates"

FX_SNAPSHOT = {
    "USD": 1.0,
    "CNY": 6.7246,
    "EUR": 0.8773,
    "GBP": 0.7554,
    "JPY": 157.54,
    "HKD": 7.8445,
    "AUD": 1.4234,
    "CAD": 1.4133,
    "SGD": 1.2778,
    "KRW": 1357.41,
    "INR": 95.92,
}

# ---------------------------------------------------------------------------
# USD-baseline default prices (the single source of truth for every price a
# project YAML may omit).  Legacy homes of the same numbers, kept in sync:
#   USD_C_PV        pv.C_pv / PVSystem default (500 currency/kWp)
#   USD_C_ENERGY    battery.c_energy / BatterySystem default (220 currency/kWh)
#   USD_TARIFF      TariffConfig hourly default (0.10 currency/kWh)
#   USD_EXPORT      TariffConfig export default (0.05 currency/kWh)
#   USD_LABOR       OpexConfig labor default (30000 currency/yr, P1-7)
#   USD_MISC        OpexConfig misc default (5000 currency/yr, P1-7)
#   USD_WATER       OpexConfig water default (2.0 currency/m3)
#   USD_RATE_PER_WATT  CapitalCostConfig.rate_per_watt default (1.0 currency/W)
# ---------------------------------------------------------------------------
USD_C_PV = 500.0  # currency/kWp (legacy fallback when pv.capital absent)
USD_C_ENERGY = 220.0  # currency/kWh (legacy fallback when battery.capital absent)
USD_TARIFF = 0.10  # currency/kWh, flat default hourly price
USD_EXPORT = 0.05  # currency/kWh, feed-in credit default
USD_LABOR = 30000.0  # currency/yr
USD_MISC = 5000.0  # currency/yr
USD_WATER = 2.0  # currency/m3
USD_RATE_PER_WATT = 1.0  # currency per rated W (LED/HVAC/DEH per_watt mode)


def fx_multiplier(currency: str, exchange_rate: float) -> float:
    """Multiplier applied to USD-baseline defaults for *currency*.

    1.0 whenever no conversion is in play (``currency == "USD"`` or the
    user kept ``exchange_rate == 1.0``); otherwise the rate itself.
    """
    if currency == "USD" or exchange_rate == 1.0:
        return 1.0
    return float(exchange_rate)


def usd_base_to_project(usd_value: float, currency: str, exchange_rate: float) -> float:
    """Convert a USD-baseline default price into the project currency.

    Zero-overhead passthrough (returns *usd_value* unchanged) when
    ``currency == "USD"`` or ``exchange_rate == 1.0`` -- so USD projects are
    bitwise identical to the pre-round-26 literals.  Non-USD projects with a
    real rate get ``usd_value * exchange_rate``.

    This helper is the ONLY conversion choke point: every default-price
    consumer (``from_dict`` materialization, sweep legacy fallbacks, engine
    PV/battery device pricing) funnels through it so no site can forget the
    rate.
    """
    if currency == "USD" or exchange_rate == 1.0:
        return usd_value
    return usd_value * exchange_rate


def resolve_unit_price(
    value, usd_base: float, currency: str, exchange_rate: float
) -> float:
    """Materialize a possibly-still-``None`` legacy unit price.

    ``from_dict`` materializes the sentinel unit prices (``pv.C_pv``,
    ``battery.c_energy``) right after construction; this defense covers
    programmatically constructed configs that bypass ``from_dict`` (raw
    dataclass defaults stay ``None``).  An explicit value passes through
    untouched, exactly like the YAML path.
    """
    if value is None:
        return usd_base_to_project(usd_base, currency, exchange_rate)
    return value
