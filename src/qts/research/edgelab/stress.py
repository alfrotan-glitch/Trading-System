"""Gold and the stress complex: volatility and credit spreads.

A genuinely new information set. Every family tested so far used gold's own price,
the dollar, nominal or real yields, the gold/silver ratio, or the intraday clock.
None used the **credit and volatility complex**, which is the market's own measure
of how much insurance it wants.

The prior, stated before any result: gold is a zero-coupon reserve asset bought as
protection. When the price of protection rises — implied volatility expanding,
credit spreads widening — the marginal buyer of gold is more likely to be someone
hedging than someone chasing yield. That predicts gold outperforming while stress
**deteriorates**, not while it is high: a high but stable VIX is a priced regime,
whereas a rising one is news.

Two well-known traps this design avoids:

* **Level versus change.** "Buy gold when VIX is high" is a regime bet that mostly
  re-states gold's own realised volatility. The tradable claim is about the
  *direction of travel*, matching the framing used for the dollar and yields.
* **Contemporaneity.** Stress and gold move together within a day. Every signal
  here is computed from data knowable at the previous close and is lagged one
  further bar by the caller, so nothing is credited with a move it caused.

Data is the FRED mirror and gold futures closes from 2000. Neither has been used
by any earlier round.

**Series selection is a data-availability decision, and it is recorded rather than
quietly made.** The high-yield and investment-grade OAS files in this mirror only
carry a rolling 2023-onward window (850 observations), which is far too short to
test anything, so the credit leg uses `BAA10Y` — Moody's BAA yield minus the
10-year Treasury, the same "price of default risk" quantity with history back to
1986. The VIX (1990+), the Chicago Fed NFCI (1971+, weekly) and the St Louis Fed
Financial Stress Index (1993+) are available in full and are used. `MOVE` starts in
2016 and is excluded for the same reason as the OAS files.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

FRED_DIR = Path("data/raw/longgold/fred")

#: Change windows, in trading days, for the trend-style indicators.
LOOKBACK_DAYS = {"short": 21, "medium": 63, "long": 126}

#: Level windows for the regime-style indicators.
LEVEL_WINDOW = 126


def _as_utc(idx: pd.Index) -> pd.DatetimeIndex:
    """Return ``idx`` as a UTC-aware DatetimeIndex.

    A tz-naive index does not raise against a tz-aware one — it produces an empty
    join — so every series that enters a signal has to be pinned here first.
    """
    out = pd.DatetimeIndex(idx)
    if out.tz is None:
        out = out.tz_localize("UTC")
    return out


def load_fred(name: str, *, positive: bool = False) -> pd.Series:
    """Load one mirrored FRED series, tz-localised to UTC."""
    path = FRED_DIR / f"{name}.csv"
    if not path.exists():
        raise FileNotFoundError(f"{path} missing — refresh the FRED mirror (scripts/edgelab_collect_observations.py)")
    df = pd.read_csv(path, parse_dates=["date"])
    s = df.set_index("date")["value"].astype(float).sort_index()
    s = s[~s.index.duplicated(keep="first")].dropna()
    if positive and (s <= 0).any():
        raise ValueError(f"{name} contains non-positive values")
    s.index = _as_utc(s.index)
    return s.rename(name)


def _on_calendar(s: pd.Series, index: pd.DatetimeIndex) -> pd.Series:
    idx = _as_utc(index)
    s = s.copy()
    s.index = _as_utc(s.index)
    s = s.sort_index()
    s = s[~s.index.duplicated(keep="first")]
    return s.reindex(s.index.union(idx)).ffill().reindex(idx)


#: The series this module relies on, and the first date each is usable, so a
#: truncated mirror shows up as a failure rather than as a short backtest.
REQUIRED_COVERAGE = {
    "vix": "1990-01-15",
    "baa10y": "1990-01-15",
    "chicago_fed_nfci": "1990-01-15",
    "stl_fed_stress_index": "1995-01-15",
}


def stress_frame(index: pd.DatetimeIndex) -> pd.DataFrame:
    """Every stress indicator this module uses, aligned onto the bar calendar.

    Missing series raise rather than being skipped: a composite that silently drops
    one of its legs is a different hypothesis wearing the same name. Coverage is
    checked against ``REQUIRED_COVERAGE`` for the same reason — an OAS file that
    only ships a rolling window would otherwise turn a 25-year test into a 2-year
    one with no error.
    """
    cols = {
        "vix": load_fred("vix", positive=True),
        "baa10y": load_fred("baa10y"),
        "nfci": load_fred("chicago_fed_nfci"),
        "stress": load_fred("stl_fed_stress_index"),
    }
    # Keys here are the FRED file names; `cols` is keyed by short name.
    short = {"vix": "vix", "baa10y": "baa10y", "chicago_fed_nfci": "nfci", "stl_fed_stress_index": "stress"}
    for name, first_ok in REQUIRED_COVERAGE.items():
        if cols[short[name]].index.min() > pd.Timestamp(first_ok, tz="UTC"):
            raise ValueError(
                f"{name} starts {cols[name].index.min().date()}, needs to start by {first_ok}; "
                "the mirror is probably serving a rolling window"
            )
    out = pd.DataFrame({k: _on_calendar(v, index) for k, v in cols.items()}, index=index)
    return out


def _trend(series: pd.Series, days: int) -> pd.Series:
    """+1 when the indicator is rising (stress worsening), 0 otherwise."""
    ch = series - series.shift(days)
    return pd.Series(np.where(ch > 0, 1.0, 0.0), index=series.index).where(ch.notna(), np.nan)


def _regime(series: pd.Series, window: int = LEVEL_WINDOW) -> pd.Series:
    """+1 when the indicator is above its own trailing median."""
    med = series.rolling(window, min_periods=window // 2).median()
    return pd.Series(np.where(series > med, 1.0, 0.0), index=series.index).where(med.notna(), np.nan)


def vix_trend(index: pd.DatetimeIndex, days: int = LOOKBACK_DAYS["short"]) -> pd.Series:
    """Long gold while implied volatility is expanding."""
    return _trend(stress_frame(index)["vix"], days).fillna(0.0).rename("vix_trend")


def vix_regime(index: pd.DatetimeIndex) -> pd.Series:
    """Long gold while implied volatility is above its own trailing median."""
    return _regime(stress_frame(index)["vix"]).fillna(0.0).rename("vix_regime")


def credit_trend(index: pd.DatetimeIndex, days: int = LOOKBACK_DAYS["medium"]) -> pd.Series:
    """Long gold while the default-risk premium is widening.

    BAA10Y is the BAA corporate yield minus the 10-year Treasury: the compensation
    demanded for default risk, with history back to 1986.
    """
    return _trend(stress_frame(index)["baa10y"], days).fillna(0.0).rename("credit_trend")


def credit_regime(index: pd.DatetimeIndex) -> pd.Series:
    """Long gold while the default-risk premium sits above its trailing median."""
    return _regime(stress_frame(index)["baa10y"]).fillna(0.0).rename("credit_regime")


def stress_composite(index: pd.DatetimeIndex) -> pd.Series:
    """Mean of four orthogonal-ish stress indicators, each in {0, 1}.

    Averaging is the same construction that was reasoned out for XL-001 — several
    noisy measurements of one factor — and it is justified here by the same
    argument, fixed before the result: implied equity volatility, the default-risk
    premium, the Chicago Fed financial-conditions index and the St Louis Fed stress
    index measure the same underlying quantity with different noise. A composite has
    a better signal-to-noise ratio than any leg if the factor is real, and no better
    than the best leg if it is not. Given that XL-001's average was later found to
    be riding a timing artifact, this composite is treated with corresponding
    suspicion and reported at the executable lag only.
    """
    f = stress_frame(index)
    legs = pd.concat(
        [
            _trend(f["vix"], LOOKBACK_DAYS["short"]),
            _trend(f["baa10y"], LOOKBACK_DAYS["medium"]),
            _trend(f["nfci"], LOOKBACK_DAYS["medium"]),
            _trend(f["stress"], LOOKBACK_DAYS["medium"]),
        ],
        axis=1,
    )
    return legs.mean(axis=1).fillna(0.0).clip(0.0, 1.0).rename("stress_composite")


def tradable_gold() -> pd.Series:
    """Gold at a 24-hour tradable close, 2000-08-30 onward.

    Futures closes cover 2000-08 to 2024-05; the M15 feed covers 2004-06 to 2025-09.
    They are the same market (0.87 daily-return correlation, $0.25 mean level gap),
    and the splice is placed where the futures series ends.
    """
    from qts.research.edgelab.intraday import daily_bars

    fut_path = Path("data/raw/longgold/AU_FUTURES.csv")
    fut = pd.read_csv(fut_path, parse_dates=["date"]).set_index("date")["close"].astype(float)
    fut.index = _as_utc(fut.index)

    m15_path = Path("data/research/xauusd_m15_basemax.parquet")
    if not m15_path.exists():
        out = fut.rename("gold")
        out.attrs["splice_at"] = None
        out.attrs["sources"] = "AU_FUTURES only (M15 store absent)"
        return out
    m15 = daily_bars(pd.read_parquet(m15_path))["close"].astype(float)

    combined = pd.concat([fut.loc[: m15.index.min() - pd.Timedelta(days=1)], m15]).sort_index()
    combined = combined[~combined.index.duplicated(keep="first")]
    combined.attrs["splice_at"] = str(m15.index.min().date())
    combined.attrs["sources"] = "AU_FUTURES (2000-08-30+) then M15 24h close (2004-06-11+)"
    return combined.rename("gold")
