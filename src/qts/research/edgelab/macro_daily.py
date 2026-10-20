"""Daily macro drivers: the US dollar and the 10-year yield.

Gold is quoted in dollars, so the dollar is its numeraire, and it competes with
nominal bonds, so the 10-year yield is its relative price. These are the two
canonical drivers, and daily data exists for both far back: DXY from 1971-01-04,
the 10-year constant-maturity yield from 1962-01-02.

Why this is a genuinely new information set rather than another price variant:
every rule tested so far used gold's own history or a monthly macro proxy. These
use daily *external* series with their own dynamics.

The hypotheses are about **direction of travel**, not level — the same framing that
makes the real-yield tests falsifiable. A level relationship between gold and the
dollar is a well-known contemporaneous correlation; it is not tradable because it
is not predictive.

Signals take a negative change as bullish for gold: a falling dollar makes gold
cheaper in other currencies, and falling nominal yields lower the opportunity cost
of holding a zero-coupon asset.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from qts.research.edgelab import StrategySpec

MACRO_DIR = Path("data/raw/longgold/macro_daily")
BARS_PER_MONTH = 21


def load_macro_daily(macro_dir: Path | None = None) -> pd.DataFrame:
    """Daily DXY and 10-year yield, forward-filled onto a common calendar."""
    d = macro_dir or MACRO_DIR
    dxy = pd.read_csv(d / "DXY.csv", parse_dates=["date"]).set_index("date")["close"]
    y10 = pd.read_csv(d / "US_10Y_TREASURY_YIELD.csv", parse_dates=["date"]).set_index("date")["yield"]
    df = pd.concat([dxy.rename("dxy"), y10.rename("y10")], axis=1, sort=True).ffill().dropna()
    df = df[~df.index.duplicated(keep="first")].sort_index()
    if (df[["dxy", "y10"]] <= 0).to_numpy().any():
        raise ValueError("non-positive macro series")
    return df


def attach_macro_daily(bars: pd.DataFrame, df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Attach DXY and the 10-year yield to gold bars, forward-filled.

    Forward fill is correct here: a missing observation on a holiday carries no
    new information, and dropping the bar would shift the alignment.
    """
    m = load_macro_daily() if df is None else df
    out = bars.copy()
    for col in ("dxy", "y10"):
        out[col] = m[col].reindex(out.index.union(m.index)).ffill().reindex(out.index)
    return out


def _falling(series: pd.Series, months: int) -> pd.Series:
    ch = series - series.shift(months * BARS_PER_MONTH)
    return pd.Series(np.where(ch < 0, 1.0, 0.0), index=series.index).where(ch.notna(), 0.0)


def usd_trend(bars: pd.DataFrame, months: int = 6) -> pd.Series:
    """Long gold while the dollar is falling."""
    if "dxy" not in bars.columns:
        raise ValueError("bars must carry 'dxy' — use attach_macro_daily() first")
    return _falling(bars["dxy"], months)


def yield_trend(bars: pd.DataFrame, months: int = 6) -> pd.Series:
    """Long gold while nominal yields are falling."""
    if "y10" not in bars.columns:
        raise ValueError("bars must carry 'y10' — use attach_macro_daily() first")
    return _falling(bars["y10"], months)


def macro_daily_specs() -> list[StrategySpec]:
    """Four configurations: two drivers, two horizons each."""
    return [
        StrategySpec("usd_falling_6m", "usd", {"months": 6}, usd_trend,
                     "A falling dollar lowers gold's price in every other currency."),
        StrategySpec("usd_falling_12m", "usd", {"months": 12}, usd_trend,
                     "Slower dollar trend; tests horizon sensitivity."),
        StrategySpec("yield_falling_6m", "yield", {"months": 6}, yield_trend,
                     "Falling nominal yields lower the opportunity cost of a zero-coupon asset."),
        StrategySpec("yield_falling_12m", "yield", {"months": 12}, yield_trend,
                     "Slower yield trend; tests horizon sensitivity."),
    ]
