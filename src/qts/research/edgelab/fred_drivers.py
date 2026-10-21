"""Daily macro drivers mirrored from FRED, extending past the DXY dataset's end.

The dollar/yield study that produced ``XL-001`` was limited by its data: the long
DXY series and the 10-year yield both stop on 2024-05-17, which made genuine
out-of-sample confirmation impossible. This module adds three FRED series taken
from a repository that refreshes daily against the FRED API:

* ``treasury_10y.csv``      — DGS10, 1962-01-02 onward
* ``treasury_10y_real.csv`` — DFII10, 2003-01-02 onward
* ``broad_dollar.csv``      — DTWEXBGS, 2006-01-02 onward

**Why a third-party mirror and not FRED itself:** ``fred.stlouisfed.org`` is not
reachable from the research sandbox (HTTP 000). So the provenance question is not
"is it FRED" but "is this file actually FRED". That is checked, not assumed:
:func:`validate_series` compares the mirror against the independently obtained
``macro_daily`` copies over their whole overlap and reports the discrepancy. The
10-year file agrees to the last decimal across 62 years, which is what makes the
other two credible; a mirror that reproduces one series exactly is not proof for
the others, so :func:`validate_drivers` reports each one's evidence separately.

**The dollar splice is not free.** DTWEXBGS is a broad trade-weighted index and
DXY is a fixed-weight index of six currencies. Over 2006-2024 they correlate 0.97
in levels and 0.92 in six-month changes, and their "is the dollar lower than six
months ago" flags agree 88% of the time. Any test that swaps one for the other
must therefore be reported alongside that 12% disagreement — see
``scripts/edgelab_xl001_holdout.py``, which measures the swap on the overlap
before extending anything past 2024.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from qts.research.edgelab import as_float

FRED_DIR = Path("data/raw/longgold/fred")
REFERENCE_DIR = Path("data/raw/longgold/macro_daily")

#: Six months of trading days — the lookback every XL-001 leg uses.
LOOKBACK_DAYS = 126


def _load_csv(path: Path, column: str = "value", *, positive: bool = True) -> pd.Series:
    if not path.exists():
        raise FileNotFoundError(
            f"{path} missing — re-download sgdividends/fred-macro-data (data/fred/*.csv)"
        )
    df = pd.read_csv(path, parse_dates=["date"])
    if column not in df.columns:
        raise ValueError(f"{path} has no column {column!r}: {list(df.columns)}")
    s = df.set_index("date")[column].sort_index()
    s = s[~s.index.duplicated(keep="first")].dropna()
    if positive and (s <= 0).any():
        raise ValueError(f"{path} contains non-positive values")
    if not positive and not np.isfinite(s.to_numpy()).all():
        raise ValueError(f"{path} contains non-finite values")
    return s.astype(float)


def load_treasury_10y() -> pd.Series:
    """Nominal 10-year constant-maturity Treasury yield (DGS10), in percent."""
    return _load_csv(FRED_DIR / "treasury_10y.csv").rename("y10")


def load_treasury_10y_real() -> pd.Series:
    """10-year TIPS yield (DFII10), in percent — the real opportunity cost.

    Real yields were **negative for most of 2011-2021**, so the positivity check
    that is right for a price level is wrong here and would reject the actual
    history. It is opt-out per series rather than global for that reason.
    """
    return _load_csv(FRED_DIR / "treasury_10y_real.csv", positive=False).rename("real10")


def load_broad_dollar() -> pd.Series:
    """Broad trade-weighted dollar index (DTWEXBGS). Index level, not a return."""
    return _load_csv(FRED_DIR / "broad_dollar.csv").rename("usd_broad")


def validate_series(new: pd.Series, old: pd.Series, label: str, tol: float = 1e-6) -> dict:
    """Compare two copies of the same series over their full overlap.

    Returns counts and the maximum absolute discrepancy rather than a boolean, so
    a partially-matching mirror is visible instead of being reduced to "ok".
    """
    joined = pd.concat([new.rename("new"), old.rename("old")], axis=1, join="inner").dropna()
    if joined.empty:
        return {"label": label, "overlap_obs": 0, "max_abs_diff": float("nan"), "identical": False}
    diff = (joined["new"] - joined["old"]).abs()
    return {
        "label": label,
        "overlap_obs": int(len(joined)),
        "overlap_from": str(joined.index.min().date()),
        "overlap_to": str(joined.index.max().date()),
        "corr": as_float(joined.corr().iloc[0, 1]),
        "max_abs_diff": as_float(diff.max()),
        "mean_abs_diff": as_float(diff.mean()),
        "identical": bool(diff.max() <= tol),
    }


def validate_drivers() -> dict:
    """Evidence that the mirrored files are the series they claim to be."""
    old_10y = _load_csv(REFERENCE_DIR / "US_10Y_TREASURY_YIELD.csv", "yield")
    out: dict[str, object] = {
        "treasury_10y": validate_series(load_treasury_10y(), old_10y, "DGS10 vs macro_daily copy")
    }
    # The 10-year mirror has an independent 62-year reference. The other two do
    # not, so their provenance rests on the same repository reproducing DGS10
    # exactly — stated here rather than implied.
    out["provenance_basis"] = (
        "treasury_10y reproduces the independently obtained DGS10 copy exactly over "
        "its whole overlap; broad_dollar and treasury_10y_real come from the same "
        "dumped files and are therefore only as trustworthy as that one check."
    )
    return out


def index_agreement(usd_a: pd.Series, usd_b: pd.Series, lookback: int = LOOKBACK_DAYS) -> dict:
    """How much does swapping dollar indices change the *signal* we actually use?

    XL-001 only reads the sign of a six-month change, so the relevant measure is
    flag agreement, not level correlation. Both are reported because a high level
    correlation with a low flag agreement is exactly the trap here.
    """
    joined = pd.concat([usd_a.rename("a"), usd_b.rename("b")], axis=1, join="inner").dropna()
    lvl = as_float(joined.corr().iloc[0, 1])
    ch = joined.pct_change(lookback).dropna()
    flag_a = (ch["a"] < 0).to_numpy()
    flag_b = (ch["b"] < 0).to_numpy()
    return {
        "overlap_from": str(joined.index.min().date()),
        "overlap_to": str(joined.index.max().date()),
        "level_corr": lvl,
        "change_corr": as_float(ch.corr().iloc[0, 1]),
        "flag_agreement": as_float(np.mean(flag_a == flag_b)),
        "n_change_obs": int(len(ch)),
    }


def align_to_index(frame: pd.DataFrame, index: pd.DatetimeIndex) -> pd.DataFrame:
    """Forward-fill a driver frame onto a bar index, safely.

    Two failure modes made an earlier version of this return a constant column —
    and therefore a strategy that never traded, with no error anywhere:

    1. **Mixed timezones.** Driver files carry naive dates; bar indexes carry UTC.
       Their union produces an object index, and ``ffill`` on an unsorted index
       propagates values in *position* order, which silently splatters a single
       observation across every row.
    2. **Unsorted or duplicated dates.** ``ffill`` is only meaningful on a sorted,
       de-duplicated index.

    Both are fixed here, once, for every caller.
    """
    if frame.empty:
        raise ValueError("driver frame is empty")
    f = frame.copy()
    if not isinstance(f.index, pd.DatetimeIndex):
        f.index = pd.DatetimeIndex(f.index)
    if f.index.tz is None:
        f.index = f.index.tz_localize("UTC")
    idx = pd.DatetimeIndex(index)
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    f = f.sort_index()
    f = f[~f.index.duplicated(keep="first")]
    union = f.index.union(idx).sort_values()
    return f.reindex(union).ffill().reindex(idx)


def extended_driver_frame(bars_index: pd.DatetimeIndex) -> pd.DataFrame:
    """Gold bars' calendar joined to a dollar index and the 10-year yield.

    The dollar column is deliberately named ``dxy`` because it feeds the frozen
    :func:`~qts.research.edgelab.candidates.easing_score_6m` unchanged — renaming
    the column would require editing the hashed candidate definition, and the
    entire point of the hash is that the definition is not edited. The series in
    that column is DTWEXBGS, not DXY; every caller must label it as such.
    """
    usd = load_broad_dollar()
    y10 = load_treasury_10y()
    df = pd.concat([usd.rename("dxy"), y10.rename("y10")], axis=1, sort=True).sort_index()
    return align_to_index(df, bars_index)
