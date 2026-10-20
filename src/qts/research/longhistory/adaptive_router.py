"""Causal regime-aware strategy routing for XAUUSD research.

The router selects among precomputed candidate position-state plans using only
net returns observed strictly before the current decision bar. It is a research
component, not a live execution or risk authority. Candidate return columns must
be net of the applicable costs and aligned to the bar on which those returns
were realized.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class AdaptiveRoutingConfig:
    lookback: int = 252
    min_observations: int = 30
    min_score: float = 0.0
    min_mean_return: float = 0.0

    def __post_init__(self) -> None:
        if self.lookback < 2:
            raise ValueError("lookback must be >= 2")
        if self.min_observations < 2 or self.min_observations > self.lookback:
            raise ValueError("min_observations must be between 2 and lookback")
        if not np.isfinite(self.min_score):
            raise ValueError("min_score must be finite")
        if not np.isfinite(self.min_mean_return):
            raise ValueError("min_mean_return must be finite")


def classify_market_regime(
    bars: pd.DataFrame,
    *,
    trend_lookback: int = 20,
    trend_threshold: float = 0.30,
    range_threshold: float = 0.20,
    atr_lookback: int = 14,
    volatility_window: int = 60,
    high_volatility_ratio: float = 1.50,
) -> pd.Series:
    """Label trend direction, range, transition, and relative volatility causally.

    Labels at t use only OHLC data through t. The volatility reference is the
    median ATR from bars strictly before t, avoiding self-normalization by the
    current bar. Warm-up rows are labeled explicitly so the router can remain
    flat until enough same-regime history exists.
    """
    if not isinstance(bars, pd.DataFrame):
        raise TypeError("bars must be a pandas DataFrame")
    if not isinstance(bars.index, pd.DatetimeIndex):
        raise ValueError("bars must use a DatetimeIndex")
    if bars.index.hasnans or bars.index.has_duplicates or not bars.index.is_monotonic_increasing:
        raise ValueError("bar index must be unique, non-null, and increasing")
    required = ("high", "low", "close")
    missing = [column for column in required if column not in bars.columns]
    if missing:
        raise ValueError(f"bars are missing required columns: {', '.join(missing)}")
    if trend_lookback < 2 or atr_lookback < 2 or volatility_window < 2:
        raise ValueError("lookback windows must be >= 2")
    if not 0.0 <= range_threshold < trend_threshold <= 1.0:
        raise ValueError("thresholds must satisfy 0 <= range_threshold < trend_threshold <= 1")
    if not np.isfinite(high_volatility_ratio) or high_volatility_ratio <= 0.0:
        raise ValueError("high_volatility_ratio must be finite and positive")

    high = bars["high"].astype(float)
    low = bars["low"].astype(float)
    close = bars["close"].astype(float)
    if not np.isfinite(bars[list(required)].to_numpy(dtype=float)).all():
        raise ValueError("OHLC values must be finite")
    if (bars[list(required)].to_numpy(dtype=float) <= 0.0).any():
        raise ValueError("OHLC values must be positive")

    prior_close = close.shift(1)
    true_range = pd.concat(
        [(high - low), (high - prior_close).abs(), (low - prior_close).abs()], axis=1
    ).max(axis=1)
    atr = true_range.ewm(alpha=1.0 / atr_lookback, adjust=False, min_periods=atr_lookback).mean()
    prior_atr_median = atr.shift(1).rolling(volatility_window, min_periods=volatility_window).median()
    net_move = (close - close.shift(trend_lookback)).abs()
    path = close.diff().abs().rolling(trend_lookback, min_periods=trend_lookback).sum()
    efficiency = net_move / path.replace(0.0, np.nan)
    direction = np.sign(close - close.shift(trend_lookback))

    labels: list[str] = []
    for i in range(len(bars)):
        er = efficiency.iloc[i]
        baseline = prior_atr_median.iloc[i]
        current_atr = atr.iloc[i]
        move = direction.iloc[i]
        if not np.isfinite(er) or not np.isfinite(baseline) or not np.isfinite(current_atr):
            labels.append("warming_up")
            continue
        if er >= trend_threshold:
            state = "trend_up" if move > 0 else "trend_down" if move < 0 else "transition"
        elif er <= range_threshold:
            state = "range"
        else:
            state = "transition"
        volatility = "high_vol" if current_atr > baseline * high_volatility_ratio else "normal_vol"
        labels.append(f"{state}_{volatility}")
    return pd.Series(labels, index=bars.index, name="regime", dtype="object")


def route_by_regime(
    regimes: pd.Series,
    net_returns: pd.DataFrame,
    targets: pd.DataFrame,
    config: AdaptiveRoutingConfig | None = None,
) -> pd.DataFrame:
    """Route to the strongest eligible candidate using past returns in this regime.

    At decision row t, scoring uses at most the previous lookback rows and
    only rows whose regime equals the current regime. The current row's return
    is never used for its own decision. If no candidate has enough history and
    positive net mean return, the router stays flat (selected_strategy=None).

    targets contains causal position states (-1, 0, +1, or NaN) generated by
    existing signal builders. NaN targets are treated as unavailable and
    force the routed position flat. net_returns must already reflect the
    intended spread, slippage, commission, and financing assumptions.
    """
    if config is None:
        config = AdaptiveRoutingConfig()
    if not isinstance(regimes, pd.Series):
        raise TypeError("regimes must be a pandas Series")
    if not isinstance(net_returns, pd.DataFrame) or not isinstance(targets, pd.DataFrame):
        raise TypeError("net_returns and targets must be pandas DataFrames")
    for name, frame in (("net_returns", net_returns), ("targets", targets)):
        if not isinstance(frame.index, pd.DatetimeIndex):
            raise ValueError(f"{name} must use a DatetimeIndex")
        if frame.index.hasnans or frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
            raise ValueError(f"{name} index must be unique, non-null, and increasing")
    if not isinstance(regimes.index, pd.DatetimeIndex) or regimes.index.has_duplicates:
        raise ValueError("regimes must use a unique DatetimeIndex")
    if not regimes.index.equals(net_returns.index) or not targets.index.equals(net_returns.index):
        raise ValueError("regimes, net_returns, and targets must have identical indexes")
    if net_returns.columns.empty or not net_returns.columns.equals(targets.columns):
        raise ValueError("net_returns and targets must have the same non-empty columns")
    if regimes.isna().any():
        raise ValueError("regimes cannot contain missing labels")
    returns = net_returns.to_numpy(dtype=float)
    position_targets = targets.to_numpy(dtype=float)
    if np.isinf(returns).any():
        raise ValueError("net_returns cannot contain infinite values")
    valid_targets = np.isnan(position_targets) | np.isin(position_targets, (-1.0, 0.0, 1.0))
    if not valid_targets.all():
        raise ValueError("targets must contain only -1, 0, +1, or NaN")

    labels = regimes.to_numpy()
    names = list(net_returns.columns)
    selected: list[str | None] = []
    routed = np.zeros(len(regimes), dtype=float)

    for t, regime in enumerate(labels):
        start = max(0, t - config.lookback)
        prior = np.arange(start, t)
        if len(prior):
            prior = prior[labels[prior] == regime]
        best_name: str | None = None
        best_score = -np.inf
        for j, name in enumerate(names):
            history = returns[prior, j] if len(prior) else np.array([], dtype=float)
            history = history[np.isfinite(history)]
            if len(history) < config.min_observations:
                continue
            mean = float(np.mean(history))
            std = float(np.std(history, ddof=1))
            score = mean / std if std > 1e-12 else (np.inf if mean > 0 else -np.inf)
            if mean <= config.min_mean_return or score < config.min_score:
                continue
            if score > best_score:
                best_name, best_score = name, score
        selected.append(best_name)
        if best_name is not None:
            target = position_targets[t, names.index(best_name)]
            routed[t] = target if np.isfinite(target) else 0.0

    return pd.DataFrame(
        {
            "selected_strategy": pd.Series(selected, index=regimes.index, dtype="object"),
            "target": routed,
            "regime": regimes,
        },
        index=regimes.index,
    )
