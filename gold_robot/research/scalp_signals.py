"""Causal M5 closed-candle XAUUSD research signals. No order submissions.

Signal time is the *end* of the completed candle. Any realistic execution
must use a subsequent tick's actual executable bid/ask, never the close.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class Bar:
    time: int
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class Signal:
    decision_time: int
    family: str
    side: int
    atr: float
    reference_stop: float


def generate_signals(
    bars: list[Bar], *, bar_seconds: int = 300,
    fast_period: int = 8, slow_period: int = 21,
    atr_period: int = 14, lookback: int = 12,
    start_hour: int = 6, end_hour: int = 22,
) -> list[Signal]:
    """Breakout, trend-pullback and liquidity-sweep candidates.

    Weekend/history gaps reset every indicator and lookback window. Trading
    hours are on the timestamp's broker/server clock, not the local PC.
    """
    if not (bar_seconds > 0 and 2 <= fast_period < slow_period and
            atr_period >= 2 and lookback >= 3 and
            0 <= start_hour < end_hour <= 24):
        raise ValueError("invalid signal configuration")
    out: list[Signal] = []
    ema_fast = ema_slow = atr = prev_close = None
    segment: list[Bar] = []
    previous_time = None
    for bar in bars:
        if not (all(isfinite(x) for x in
                    (bar.open, bar.high, bar.low, bar.close))
                and 0 < bar.low <= min(bar.open, bar.close)
                and max(bar.open, bar.close) <= bar.high):
            raise ValueError("invalid price bar")
        if previous_time is not None and bar.time <= previous_time:
            raise ValueError("unsorted or duplicate candle")
        if previous_time is not None and bar.time - previous_time != bar_seconds:
            segment = []
            ema_fast = ema_slow = atr = prev_close = None
        previous_time = bar.time
        prior = segment[-lookback:]
        tr = bar.high - bar.low if prev_close is None else max(
            bar.high-bar.low, abs(bar.high-prev_close), abs(bar.low-prev_close)
        )
        old_fast = ema_fast
        ema_fast = bar.close if ema_fast is None else (
            ema_fast + (bar.close-ema_fast)*2/(fast_period+1))
        ema_slow = bar.close if ema_slow is None else (
            ema_slow + (bar.close-ema_slow)*2/(slow_period+1))
        atr = tr if atr is None else atr + (tr-atr)/atr_period
        segment.append(bar)
        prev_close = bar.close
        if (len(segment) < max(2*slow_period, lookback+2)
                or len(prior) < lookback or atr <= 0):
            continue
        decision = bar.time + bar_seconds
        hour = (decision % 86400)//3600
        if not start_hour <= hour < end_hour:
            continue
        hi = max(b.high for b in prior)
        lo = min(b.low for b in prior)
        trend = 1 if ema_fast > ema_slow else -1 if ema_fast < ema_slow else 0
        if trend > 0 and bar.close > hi + 0.05*atr:
            out.append(Signal(decision, "breakout", 1, atr, lo))
        elif trend < 0 and bar.close < lo - 0.05*atr:
            out.append(Signal(decision, "breakout", -1, atr, hi))
        before = prior[-1]
        if (old_fast is not None and trend > 0
                and before.close <= old_fast and bar.close > ema_fast):
            out.append(Signal(decision, "trend_pullback", 1, atr, lo))
        elif (old_fast is not None and trend < 0
                and before.close >= old_fast and bar.close < ema_fast):
            out.append(Signal(decision, "trend_pullback", -1, atr, hi))
        if bar.low < lo - 0.10*atr and bar.close > lo + 0.05*atr:
            out.append(Signal(decision, "liquidity_sweep", 1, atr, bar.low))
        elif bar.high > hi + 0.10*atr and bar.close < hi - 0.05*atr:
            out.append(Signal(decision, "liquidity_sweep", -1, atr, bar.high))
    return out
