"""Gold miners as a cross-market signal for gold itself.

Why this is new information
---------------------------
Every round so far read gold's own price or a macro series. This reads a *second
market* — listed gold mining equities — and uses it to time gold. That is a
different information set, not a different transform of the same one, which is the
standing rule from round 14.

The economic claim, stated before the result: miners are a levered, equity-market
claim on the gold price. Their operating leverage means their price embeds the
market's expectation of future gold revenue, and the *ratio* of miners to gold
mean-reverts because both are claims on the same underlying metal. When miners are
depressed relative to gold, the cross-market signal says gold is cheap.

The instrument stays XAUUSD@ — the signal is cross-market, the trade is not. That
matters for the product: a miners trade would need a different broker symbol, a
different liquidity profile and a different cost model, none of which this
environment can verify.

Power caveat
------------
The miners ETF starts 2006-05-22, giving 18 years. The detection floor at that
length is Sharpe ~0.59 for t = 2.5, so only a large effect is visible. The
2020-2024 window is spent (round 3's holdout) and is reported diagnostically only.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

MINERS_CSV = Path("data/raw/longgold/AU_MINERS_ETF.csv")


def _align_index(s: pd.Series, target: pd.Index) -> pd.Series:
    """Put ``s`` on ``target``'s timezone before any reindex.

    A tz-aware series reindexed against tz-naive bars does not raise — it returns an
    empty selection, so every signal silently becomes zero. That failure mode has
    now appeared three times in this codebase; it is handled once, here.
    """
    idx = pd.DatetimeIndex(target)
    src = pd.DatetimeIndex(s.index)
    if src.tz is None and idx.tz is not None:
        src = src.tz_localize("UTC").tz_convert(idx.tz)
    elif src.tz is not None and idx.tz is None:
        src = src.tz_localize(None)
    elif src.tz is not None and idx.tz is not None:
        src = src.tz_convert(idx.tz)
    out = s.copy()
    out.index = src
    return out


def load_miners(path: Path | None = None) -> pd.Series:
    """Daily close of the gold-miners ETF, tz-localised to UTC."""
    p = path or MINERS_CSV
    if not p.exists():
        raise FileNotFoundError(f"{p} missing — refetch the precious-metals price repository")
    df = pd.read_csv(p, parse_dates=["date"]).set_index("date").sort_index()
    if "close" not in df.columns:
        raise ValueError(f"unexpected miners columns: {list(df.columns)}")
    s = df["close"].astype(float)
    s = s[~s.index.duplicated(keep="first")].dropna()
    if (s <= 0).any():
        raise ValueError("non-positive miners price")
    return s.rename("miners")


def miners_ratio_z(bars: pd.DataFrame, window: int) -> pd.Series:
    """Z-score of miners/gold against its own trailing distribution.

    Both legs are close-of-day on the same calendar, so there is no snapshot
    mismatch here — unlike the macro drivers, which needed a publication lag.
    """
    miners = load_miners()
    gold = bars["close"].astype(float)
    miners = _align_index(miners, gold.index)
    joint = pd.concat([miners.rename("m"), gold.rename("g")], axis=1, sort=True).dropna()
    ratio = joint["m"] / joint["g"]
    mean = ratio.rolling(window, min_periods=window // 2).mean()
    std = ratio.rolling(window, min_periods=window // 2).std()
    return ((ratio - mean) / std.replace(0.0, np.nan)).rename("ratio_z")


def _binary(bars: pd.DataFrame, cond: pd.Series, name: str) -> pd.Series:
    out = _align_index(cond.astype(float), bars.index)
    aligned = out.reindex(bars.index)
    if aligned.notna().mean() < 0.05:
        raise ValueError(f"{name}: alignment produced {aligned.notna().mean():.1%} coverage — refusing to return zeros")
    return aligned.fillna(0.0).rename(name)


def miner_dip(bars: pd.DataFrame, window: int = 252, z: float = -0.5) -> pd.Series:
    """Long gold while miners are depressed relative to gold."""
    zs = miners_ratio_z(bars, window)
    return _binary(bars, (zs < z), "miner_dip")


def miner_stress(bars: pd.DataFrame, window: int = 252, z: float = -1.5) -> pd.Series:
    """The same idea at an extreme threshold — a genuinely different bet size."""
    zs = miners_ratio_z(bars, window)
    return _binary(bars, (zs < z), "miner_stress")


def miner_momentum(bars: pd.DataFrame, window: int = 252, z: float = 0.5) -> pd.Series:
    """Long gold while miners are *strong* relative to gold.

    The opposite sign to ``miner_dip``, declared in advance. If the mean-reversion
    reading is right this should lose; if the cross-market lead is real it should
    win. Including it prevents the round from being a one-sided bet on a sign.
    """
    zs = miners_ratio_z(bars, window)
    return _binary(bars, (zs > z), "miner_momentum")


def miner_specs() -> dict[str, object]:
    """The four pre-registered configurations of round 18."""
    return {
        "miner_dip": miner_dip,
        "miner_stress": miner_stress,
        "miner_momentum": miner_momentum,
        "miner_dip_fast": lambda bars: miner_dip(bars, window=126, z=-0.5),
    }
