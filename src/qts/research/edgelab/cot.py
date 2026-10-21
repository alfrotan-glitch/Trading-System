"""CFTC Commitments of Traders for gold — positioning as information.

The last classical dataset the programme has not touched. Every earlier round used
prices, macro aggregates or financial conditions; none used *who is positioned
where*. That is the only channel left that is genuinely new information rather
than a new transform of something already in hand.

Source
------
``data/raw/longgold/cot/gold_cot_merged.xlsx``, 374 weekly reports from
2018-03-13 to 2025-05-06, with commercial, non-commercial and non-reportable
long/short interest. Fetched from ``yoseph-zemede/gold-cot-scraper`` via
``codeload``. The file is sorted lexically by ``MM-DD-YY`` string, not
chronologically, so the loader parses the date and re-sorts — reading the rows in
file order would silently scramble seven years of data.

**Power caveat, stated up front.** Seven point two years of weekly data puts the
detection floor at Sharpe ≈ 0.93 for t = 2.5. That is far above any effect a
positioning signal plausibly has, so this dataset *cannot* support a gate-level
verdict. It is used to measure the effect size and its confidence interval, and the
runner says so rather than manufacturing a pass/fail from an unpowered sample.

Release timing
--------------
The report describes Tuesday's positions and is published the following Friday
afternoon, so a value is stamped four calendar days forward before it is allowed
onto a bar.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

XLSX = Path("data/raw/longgold/cot/gold_cot_merged.xlsx")

#: Tuesday observation -> Friday release -> next usable bar.
RELEASE_LAG_DAYS = 4

#: The sample this dataset can support, for the runner's windows.
SAMPLE = ("2018-03-13", "2025-05-06")

COLUMNS = ["date", "comm_long", "comm_short", "spec_long", "spec_short", "nr_long", "nr_short"]


def load_cot(path: Path | None = None) -> pd.DataFrame:
    """Weekly gold positioning, sorted by date, with net series and a release stamp."""
    p = path or XLSX
    if not p.exists():
        raise FileNotFoundError(f"{p} missing — refetch the gold COT mirror")
    df = pd.read_excel(p)
    if len(df.columns) != len(COLUMNS):
        raise ValueError(f"unexpected COT columns: {list(df.columns)}")
    df.columns = COLUMNS
    df["date"] = pd.to_datetime(df["date"], format="%m-%d-%y", errors="coerce")
    if df["date"].isna().any():
        raise ValueError("unparseable COT dates")
    df = df.sort_values("date").drop_duplicates("date").reset_index(drop=True)
    gaps = df["date"].diff().dt.days.dropna()
    # Reports are weekly but the CFTC shifts the reference date around holidays
    # (3-6 day gaps observed), so only a sub-3-day gap means a corrupted file.
    if (gaps < 3).any():
        raise ValueError(f"COT reports {gaps.min():.0f} days apart — refusing")
    if (gaps > 14).any():
        raise ValueError(f"COT gap of {gaps.max():.0f} days — refusing")
    df["spec_net"] = df["spec_long"] - df["spec_short"]
    df["comm_net"] = df["comm_long"] - df["comm_short"]
    df["oi"] = df["comm_long"] + df["comm_short"] + df["nr_long"] + df["nr_short"]
    df["pub_date"] = df["date"] + pd.Timedelta(days=RELEASE_LAG_DAYS)
    return df.set_index("pub_date")


def _to_bars(s: pd.Series, index: pd.Index, name: str) -> pd.Series:
    """Forward-fill a release-stamped series onto the bar calendar."""
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


# ---------------------------------------------------------------- signals


def spec_contrarian(bars: pd.DataFrame, window: int = 52, q: float = 0.25) -> pd.Series:
    """Long gold when speculative net length is in the bottom quartile of a year.

    The classic reading: when the speculative crowd is already long, there is nobody
    left to buy; when it has been flushed out, the path of least resistance is up.
    """
    cot = load_cot()
    s = cot["spec_net"]
    lo = s.rolling(window, min_periods=window // 2).quantile(q)
    sig = pd.Series(np.where(s < lo, 1.0, 0.0), index=s.index).where(lo.notna(), np.nan)
    return _to_bars(sig, bars.index, "spec_contrarian").fillna(0.0)


def spec_momentum(bars: pd.DataFrame, weeks: int = 4) -> pd.Series:
    """Long gold while speculators have been *adding* net length."""
    s = load_cot()["spec_net"]
    ch = s - s.shift(weeks)
    sig = pd.Series(np.where(ch > 0, 1.0, 0.0), index=s.index).where(ch.notna(), np.nan)
    return _to_bars(sig, bars.index, "spec_momentum").fillna(0.0)


def commercial_contrarian(bars: pd.DataFrame, window: int = 52, q: float = 0.75) -> pd.Series:
    """Long gold when commercial net length is high relative to its own year.

    Commercials are structurally net short (they hedge), so "high" here means
    "least short" — the hedgers stepping back, which is the bullish side of the
    same statistic.
    """
    s = load_cot()["comm_net"]
    hi = s.rolling(window, min_periods=window // 2).quantile(q)
    sig = pd.Series(np.where(s > hi, 1.0, 0.0), index=s.index).where(hi.notna(), np.nan)
    return _to_bars(sig, bars.index, "commercial_contrarian").fillna(0.0)


def spec_oi_ratio(bars: pd.DataFrame, window: int = 52) -> pd.Series:
    """Long gold when speculators' share of open interest is low.

    Normalising by open interest removes the level drift in contract counts, so a
    fixed number of contracts means something different in 2018 and 2025.
    """
    cot = load_cot()
    share = (cot["spec_long"] + cot["spec_short"]) / cot["oi"]
    med = share.rolling(window, min_periods=window // 2).median()
    sig = pd.Series(np.where(share < med, 1.0, 0.0), index=share.index).where(med.notna(), np.nan)
    return _to_bars(sig, bars.index, "spec_oi_ratio").fillna(0.0)


def cot_specs() -> dict[str, object]:
    """The four pre-registered configurations of round 15."""
    return {
        "spec_contrarian": spec_contrarian,
        "spec_momentum": spec_momentum,
        "commercial_contrarian": commercial_contrarian,
        "spec_oi_ratio": spec_oi_ratio,
    }
