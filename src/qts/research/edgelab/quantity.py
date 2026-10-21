"""Quantity-based macro signals for gold: money stock, labour market, fiscal.

Why this module exists
----------------------
Rounds 1-12 used the *price* of money (real and nominal yields, inflation,
inflation expectations) and the *price* of risk (credit and volatility). Not one of
them used the *quantity* of money, or the quantity of labour slack. Round 3's
inflation family tested CPI; M2 was never loaded by any script in this repository
before this file.

That distinction is the whole justification for a new family under spent windows.
Gold-versus-money-stock is not a faster version of a real-yield rule: the real
yield is a forward-looking price cleared in a bond market, while M2 is a backward
looking accounting aggregate published with a multi-week lag. They can diverge for
years, which is exactly what happened in 2020-2021.

Two things this module refuses to do
------------------------------------
1. **Look ahead.** M2 is published roughly four weeks after the month closes, so
   the monthly value is stamped two months forward. Weekly claims are stamped one
   week forward. The Sahm rule is published a month after the labour report it
   consumes, so it gets a two-month stamp too. Every stamp is conservative by
   construction: it can only understate a real-time signal.
2. **Trade often.** These are monthly signals resampled onto daily bars, so a
   position changes at most ~12 times a year. The round-7 turnover law (9.1%/yr
   per daily flip) does not bind here at all.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from qts.research.edgelab.stress import load_fred

#: First date each input must reach, so a truncated mirror fails loudly.
REQUIRED_COVERAGE = {
    "us_m2": "1969-01-01",
    "initial_claims_4wk": "1969-01-01",
    "unemployment_rate": "1969-01-01",
    "sahm_realtime": "1969-01-01",
    "cpi": "1969-01-01",
}

#: Publication stamps, in months, applied by moving each observation forward.
LAG_MONTHS = {
    "us_m2": 2,
    "cpi": 2,
    "unemployment_rate": 1,
    "sahm_realtime": 2,
}

#: Weekly series are stamped forward in days rather than months.
LAG_DAYS = {"initial_claims_4wk": 7}


def _require(name: str) -> pd.Series:
    if name not in REQUIRED_COVERAGE:
        raise KeyError(f"{name} is not a declared input")
    s = load_fred(name)
    first_ok = pd.Timestamp(REQUIRED_COVERAGE[name], tz="UTC")
    if s.index.min() > first_ok:
        raise ValueError(
            f"{name} starts {s.index.min().date()}, needs to start by {first_ok.date()}; "
            "the mirror is probably serving a rolling window"
        )
    return s


def monthly(name: str) -> pd.Series:
    """One monthly input, stamped at its publication month-end.

    FRED stamps a monthly observation with the first day of the month; this
    re-stamps it to the *end* of the month plus the declared publication lag, so a
    value cannot be used before it is printed.
    """
    s = _require(name)
    s = s.copy()
    s.index = pd.DatetimeIndex(s.index).tz_convert(None)
    # Collapse any intra-month duplicates, then anchor on month-end.
    periods = pd.PeriodIndex(s.index.to_period("M"))
    s = s.groupby(periods).last()
    end = pd.PeriodIndex(s.index).to_timestamp(how="end").normalize()
    s.index = end + pd.DateOffset(months=LAG_MONTHS[name])
    return s.sort_index()


def weekly(name: str) -> pd.Series:
    """One weekly input, stamped ``LAG_DAYS`` after its observation date."""
    s = _require(name).copy()
    s.index = pd.DatetimeIndex(s.index).tz_convert(None)
    s.index = s.index + pd.Timedelta(days=LAG_DAYS[name])
    return s.sort_index()


def _to_bars(s: pd.Series, index: pd.Index, name: str) -> pd.Series:
    """Forward-fill a stamped series onto the bar calendar, without look-ahead.

    The result is re-indexed with the *caller's own index object*. Returning a
    tz-naive index against tz-aware bars does not raise — pandas reindexes to an
    empty selection, so every position becomes zero and the strategy silently
    reports a flat, zero-alpha history. That failure mode is why the final line
    copies ``index`` rather than using the reconstructed ``idx``.
    """
    idx = pd.DatetimeIndex(index)
    src = pd.DatetimeIndex(s.index)
    if src.tz is None and idx.tz is not None:
        src = src.tz_localize("UTC").tz_convert(idx.tz)
    elif src.tz is not None and idx.tz is None:
        src = src.tz_localize(None)
    elif src.tz is not None and idx.tz is not None:
        src = src.tz_convert(idx.tz)
    s = s.copy()
    s.index = src
    s = s[~s.index.duplicated(keep="last")].sort_index()
    out = s.reindex(s.index.union(idx)).ffill().reindex(idx)
    out.index = index
    return out.rename(name)


def _gold_monthly(bars: pd.DataFrame) -> pd.Series:
    """Month-end gold close, for ratio constructions."""
    close = bars["close"].astype(float).copy()
    idx = pd.DatetimeIndex(close.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_convert(None)
    close.index = idx
    periods = idx.to_period("M")
    monthly_last = close.groupby(periods).last().dropna()
    monthly_last.index = pd.PeriodIndex(monthly_last.index).to_timestamp(how="end").normalize()
    return monthly_last


# ---------------------------------------------------------------- signals


def gold_m2_ratio(bars: pd.DataFrame, window_years: int = 10) -> pd.Series:
    """+1 while gold is cheap relative to the money stock, 0 otherwise.

    The construction is a z-score of ``gold / M2`` against its own trailing
    history, so it is a *valuation* statement rather than a trend statement. The
    direction is fixed before the result: gold below its long-run level relative to
    money is the "cheap" side.
    """
    months = window_years * 12
    gold = _gold_monthly(bars)
    m2 = monthly("us_m2")
    ratio = (gold / m2.reindex(gold.index, method="ffill")).dropna()
    z = (ratio - ratio.rolling(months, min_periods=months // 2).mean()) / ratio.rolling(
        months, min_periods=months // 2
    ).std()
    sig = pd.Series(np.where(z < 0, 1.0, 0.0), index=z.index).where(z.notna(), np.nan)
    return _to_bars(sig, bars.index, "gold_m2_ratio").fillna(0.0)


def m2_growth(bars: pd.DataFrame, months: int = 12, window_months: int = 60) -> pd.Series:
    """+1 while money growth is above its own trailing median."""
    m2 = monthly("us_m2")
    g = (m2 / m2.shift(months) - 1.0).dropna()
    med = g.rolling(window_months, min_periods=window_months // 2).median()
    sig = pd.Series(np.where(g > med, 1.0, 0.0), index=g.index).where(med.notna(), np.nan)
    return _to_bars(sig, bars.index, "m2_growth").fillna(0.0)


def excess_money_growth(bars: pd.DataFrame, months: int = 12) -> pd.Series:
    """+1 while money growth outruns consumer-price inflation."""
    m2 = monthly("us_m2")
    cpi = monthly("cpi")
    mg = m2 / m2.shift(months) - 1.0
    cg = cpi / cpi.shift(months) - 1.0
    joint = pd.concat([mg.rename("m2"), cg.rename("cpi")], axis=1, sort=True).dropna()
    excess = joint["m2"] - joint["cpi"]
    sig = pd.Series(np.where(excess > 0, 1.0, 0.0), index=excess.index)
    return _to_bars(sig, bars.index, "excess_money_growth").fillna(0.0)


def claims_trend(bars: pd.DataFrame, weeks: int = 52) -> pd.Series:
    """+1 while initial claims are rising year on year (labour market weakening)."""
    cl = weekly("initial_claims_4wk")
    ch = cl - cl.shift(weeks)
    sig = pd.Series(np.where(ch > 0, 1.0, 0.0), index=ch.index).where(ch.notna(), np.nan)
    return _to_bars(sig, bars.index, "claims_trend").fillna(0.0)


def sahm_signal(bars: pd.DataFrame) -> pd.Series:
    """+1 while the Sahm recession indicator is triggered (>= 0.50pp)."""
    s = monthly("sahm_realtime")
    sig = pd.Series(np.where(s >= 0.50, 1.0, 0.0), index=s.index)
    return _to_bars(sig, bars.index, "sahm_signal").fillna(0.0)


def quantity_specs() -> dict[str, callable]:  # type: ignore[valid-type]
    """The five pre-registered configurations of round 13."""
    return {
        "gold_m2_ratio": lambda bars: gold_m2_ratio(bars, window_years=10),
        "m2_growth": m2_growth,
        "excess_money_growth": excess_money_growth,
        "claims_trend": claims_trend,
        "sahm_signal": sahm_signal,
    }


def available() -> dict[str, bool]:
    """Which inputs are present, for a fast environment check."""
    out = {}
    for name in REQUIRED_COVERAGE:
        out[name] = Path("data/raw/longgold/fred").joinpath(f"{name}.csv").exists()
    return out
