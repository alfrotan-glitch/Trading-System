"""Precious-metals relative value: the gold/silver ratio.

Gold and silver are both monetary metals with a shared demand base, so their
ratio has oscillated between roughly 14 and 123 over 56 years. That makes two
opposite predictions plausible *a priori*:

* **mean reversion** — an extreme ratio resolves, so gold is cheap when the ratio
  is high;
* **stress momentum** — a high ratio marks a monetary-stress regime in which gold
  keeps outperforming silver.

Both are tested as declared alternatives rather than picking the winner after the
fact. Testing both and reporting both is the difference between a hypothesis and a
fitted result.

The series (`AU.csv`, `AG.csv`, 1968-01-02 to 2024-05-17) is the same LBMA data
the long gold study uses — verified here, not assumed: daily returns correlate
0.999999 with the FRED gold fix and the median price difference is $0.00. It is
therefore *not* an independent check of the gold level; its value is the silver
cross-section and the extra five years.

Silver's 81.6% single-day move on 1980-01-07 is the Hunt brothers corner and is
left in place. Removing the largest move in the sample because it is inconvenient
is how a backtest acquires an edge it never had.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from qts.research.edgelab import StrategySpec

METALS_DIR = Path("data/raw/longgold/metals")
BARS_PER_YEAR = 252.0
BARS_PER_MONTH = 21


def load_metals(metals_dir: Path | None = None) -> pd.DataFrame:
    """Daily gold and silver prices, inner-joined on date."""
    d = metals_dir or METALS_DIR
    au = pd.read_csv(d / "AU.csv", parse_dates=["date"]).set_index("date")["price"]
    ag = pd.read_csv(d / "AG.csv", parse_dates=["date"]).set_index("date")["price"]
    df = pd.concat([au.rename("gold"), ag.rename("silver")], axis=1, sort=True).dropna()
    df = df[~df.index.duplicated(keep="first")].sort_index()
    if (df <= 0).to_numpy().any():
        raise ValueError("non-positive metal price")
    return df


def gold_silver_ratio(df: pd.DataFrame) -> pd.Series:
    return df["gold"] / df["silver"]


def gold_bars(df: pd.DataFrame) -> pd.DataFrame:
    """Gold-only OHLC from a single daily price (no intraday high/low available)."""
    g = df["gold"]
    bars = pd.DataFrame({"open": g, "high": g, "low": g, "close": g})
    bars["volume"] = 0.0
    return bars


def _rolling_median(gsr: pd.Series, years: int) -> pd.Series:
    n = years * 12 * BARS_PER_MONTH
    return gsr.rolling(n, min_periods=3 * 12 * BARS_PER_MONTH).median()


def _rolling_z(gsr: pd.Series, years: int) -> pd.Series:
    n = years * 12 * BARS_PER_MONTH
    mu = gsr.rolling(n, min_periods=2 * 12 * BARS_PER_MONTH).mean()
    sd = gsr.rolling(n, min_periods=2 * 12 * BARS_PER_MONTH).std()
    return (gsr - mu) / sd.replace(0.0, float("nan"))


def _require_ratio(bars: pd.DataFrame) -> pd.Series:
    if "gsr" not in bars.columns:
        raise ValueError("bars must carry a 'gsr' column — build it with attach_ratio()")
    return bars["gsr"]


def attach_ratio(bars: pd.DataFrame, df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Return a copy of ``bars`` carrying the gold/silver ratio, aligned on date."""
    metals = load_metals() if df is None else df
    gsr = gold_silver_ratio(metals)
    out = bars.copy()
    out["gsr"] = gsr.reindex(out.index)
    return out


def gsr_mean_reversion(bars: pd.DataFrame, years: int = 10) -> pd.Series:
    """Long gold when the ratio is below its long median (gold cheap vs silver)."""
    gsr = _require_ratio(bars)
    med = _rolling_median(gsr, years)
    return pd.Series((gsr < med).to_numpy().astype(float), index=bars.index).fillna(0.0)


def gsr_stress_momentum(bars: pd.DataFrame, years: int = 10) -> pd.Series:
    """Long gold when the ratio is above its long median (stress regime persists)."""
    gsr = _require_ratio(bars)
    med = _rolling_median(gsr, years)
    return pd.Series((gsr > med).to_numpy().astype(float), index=bars.index).fillna(0.0)


def gsr_extreme(bars: pd.DataFrame, years: int = 5, z: float = -1.0) -> pd.Series:
    """Long gold only when the ratio is an extreme low (strong relative value)."""
    gsr = _require_ratio(bars)
    zz = _rolling_z(gsr, years)
    return pd.Series((zz < z).to_numpy().astype(float), index=bars.index).fillna(0.0)


def gsr_specs() -> list[StrategySpec]:
    """The three declared ratio hypotheses."""
    return [
        StrategySpec("gsr_meanrev_10y", "gsr", {"years": 10}, gsr_mean_reversion,
                     "Ratio extremes resolve; gold is cheap when the ratio is high."),
        StrategySpec("gsr_stress_10y", "gsr", {"years": 10}, gsr_stress_momentum,
                     "A high ratio marks monetary stress in which gold keeps outperforming."),
        StrategySpec("gsr_extreme_z1", "gsr", {"years": 5, "z": -1.0}, gsr_extreme,
                     "Only strong relative-value signals, not a persistent tilt."),
    ]
