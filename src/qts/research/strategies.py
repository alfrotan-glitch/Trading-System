"""Interpretable strategy families — trend, breakout, mean-reversion, momentum, volatility, regime-conditioned."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Any

from qts.domain.value_objects import Bar, Instrument, Side, Signal, uuid7


class StrategyFamily(StrEnum):
    TREND = "trend"
    BREAKOUT = "breakout"
    MEAN_REVERSION = "mean_reversion"
    MOMENTUM = "momentum"
    VOLATILITY = "volatility"
    REGIME_CONDITIONED = "regime_conditioned"


# ---------- TREND FOLLOWING ----------
class TrendFollowingStrategy:
    """SMA/EMA crossover trend following — interpretable, bounded params."""

    def __init__(
        self,
        instrument: Instrument,
        fast: int = 10,
        slow: int = 20,
        ma_type: str = "sma",
        strategy_id: str = "trend_sma",
    ):
        if fast >= slow:
            raise ValueError("fast must be < slow")
        if fast < 2 or slow > 200:
            raise ValueError("params out of bounded range")
        self.instrument = instrument
        self.fast = fast
        self.slow = slow
        self.ma_type = ma_type
        self.strategy_id = strategy_id
        self._closes: list[Decimal] = []

    def _ma(self, n: int) -> Decimal:
        if self.ma_type == "ema":
            # simplified EMA approx as SMA for determinism
            return sum(self._closes[-n:]) / Decimal(n)
        return sum(self._closes[-n:]) / Decimal(n)

    def on_bar(self, bar: Bar) -> list[Signal]:
        self._closes.append(bar.close)
        if len(self._closes) < self.slow + 1:
            return []
        fast = self._ma(self.fast)
        slow = self._ma(self.slow)
        prev_fast = sum(self._closes[-self.fast - 1 : -1]) / Decimal(self.fast)
        prev_slow = sum(self._closes[-self.slow - 1 : -1]) / Decimal(self.slow)
        if prev_fast <= prev_slow and fast > slow:
            return [
                Signal(
                    instrument=bar.instrument,
                    side=Side.BUY,
                    strength=0.7,
                    event_time=bar.close_time,
                    hypothesis_id="H-TREND",
                    strategy_id=self.strategy_id,
                    features={"fast": float(fast), "slow": float(slow)},
                )
            ]
        if prev_fast >= prev_slow and fast < slow:
            return [
                Signal(
                    instrument=bar.instrument,
                    side=Side.SELL,
                    strength=0.7,
                    event_time=bar.close_time,
                    hypothesis_id="H-TREND",
                    strategy_id=self.strategy_id,
                    features={"fast": float(fast), "slow": float(slow)},
                )
            ]
        return []


# ---------- BREAKOUT ----------
class BreakoutStrategy:
    """Donchian channel breakout — buy when close > highest high(N), sell when close < lowest low(N)."""

    def __init__(self, instrument: Instrument, period: int = 20, strategy_id: str = "breakout_donchian"):
        if period < 5 or period > 100:
            raise ValueError("period out of bounded range 5-100")
        self.instrument = instrument
        self.period = period
        self.strategy_id = strategy_id
        self._bars: list[Bar] = []

    def on_bar(self, bar: Bar) -> list[Signal]:
        self._bars.append(bar)
        if len(self._bars) <= self.period:
            return []
        highs = [b.high for b in self._bars[-self.period - 1 : -1]]
        lows = [b.low for b in self._bars[-self.period - 1 : -1]]
        highest = max(highs)
        lowest = min(lows)
        if bar.close > highest:
            return [
                Signal(
                    instrument=bar.instrument,
                    side=Side.BUY,
                    strength=0.8,
                    event_time=bar.close_time,
                    hypothesis_id="H-BREAKOUT",
                    strategy_id=self.strategy_id,
                    features={"highest": float(highest), "close": float(bar.close)},
                )
            ]
        if bar.close < lowest:
            return [
                Signal(
                    instrument=bar.instrument,
                    side=Side.SELL,
                    strength=0.8,
                    event_time=bar.close_time,
                    hypothesis_id="H-BREAKOUT",
                    strategy_id=self.strategy_id,
                    features={"lowest": float(lowest), "close": float(bar.close)},
                )
            ]
        return []


# ---------- MEAN REVERSION ----------
class MeanReversionStrategy:
    """Bollinger-like mean reversion — sell when close > SMA+ k*std, buy when close < SMA - k*std."""

    def __init__(self, instrument: Instrument, period: int = 20, k: float = 2.0, strategy_id: str = "meanrev_bb"):
        if period < 5 or period > 100:
            raise ValueError("period out of range")
        if k < 0.5 or k > 3.0:
            raise ValueError("k out of range")
        self.instrument = instrument
        self.period = period
        self.k = k
        self.strategy_id = strategy_id
        self._closes: list[Decimal] = []

    def on_bar(self, bar: Bar) -> list[Signal]:
        self._closes.append(bar.close)
        if len(self._closes) < self.period:
            return []
        window = self._closes[-self.period :]
        sma = sum(window) / Decimal(self.period)
        # std
        vals = [float(c) for c in window]
        mean_f = float(sma)
        var = sum((x - mean_f) ** 2 for x in vals) / len(vals)
        std = var**0.5
        upper = float(sma) + self.k * std
        lower = float(sma) - self.k * std
        close_f = float(bar.close)
        if close_f > upper:
            return [
                Signal(
                    instrument=bar.instrument,
                    side=Side.SELL,
                    strength=0.6,
                    event_time=bar.close_time,
                    hypothesis_id="H-MEANREV",
                    strategy_id=self.strategy_id,
                    features={"sma": float(sma), "upper": upper, "lower": lower},
                )
            ]
        if close_f < lower:
            return [
                Signal(
                    instrument=bar.instrument,
                    side=Side.BUY,
                    strength=0.6,
                    event_time=bar.close_time,
                    hypothesis_id="H-MEANREV",
                    strategy_id=self.strategy_id,
                    features={"sma": float(sma), "upper": upper, "lower": lower},
                )
            ]
        return []


# ---------- MOMENTUM ----------
class MomentumStrategy:
    """Momentum — buy if close - close[N] > threshold, sell if < -threshold."""

    def __init__(
        self, instrument: Instrument, lookback: int = 10, threshold: float = 0.0, strategy_id: str = "momentum"
    ):
        if lookback < 5 or lookback > 50:
            raise ValueError("lookback out of range")
        self.instrument = instrument
        self.lookback = lookback
        self.threshold = threshold
        self.strategy_id = strategy_id
        self._closes: list[Decimal] = []

    def on_bar(self, bar: Bar) -> list[Signal]:
        self._closes.append(bar.close)
        if len(self._closes) <= self.lookback:
            return []
        mom = float(bar.close - self._closes[-self.lookback - 1])
        if mom > self.threshold:
            return [
                Signal(
                    instrument=bar.instrument,
                    side=Side.BUY,
                    strength=min(1.0, abs(mom) / 10),
                    event_time=bar.close_time,
                    hypothesis_id="H-MOM",
                    strategy_id=self.strategy_id,
                    features={"mom": mom},
                )
            ]
        if mom < -self.threshold:
            return [
                Signal(
                    instrument=bar.instrument,
                    side=Side.SELL,
                    strength=min(1.0, abs(mom) / 10),
                    event_time=bar.close_time,
                    hypothesis_id="H-MOM",
                    strategy_id=self.strategy_id,
                    features={"mom": mom},
                )
            ]
        return []


# ---------- VOLATILITY ----------
class VolatilityStrategy:
    """ATR-based volatility breakout — buy when range expands beyond ATR multiplier."""

    def __init__(
        self, instrument: Instrument, atr_period: int = 14, multiplier: float = 1.5, strategy_id: str = "vol_atr"
    ):
        if atr_period < 5 or atr_period > 50:
            raise ValueError("atr_period out of range")
        if multiplier < 0.5 or multiplier > 3.0:
            raise ValueError("multiplier out of range")
        self.instrument = instrument
        self.atr_period = atr_period
        self.multiplier = multiplier
        self.strategy_id = strategy_id
        self._bars: list[Bar] = []

    def on_bar(self, bar: Bar) -> list[Signal]:
        self._bars.append(bar)
        if len(self._bars) < self.atr_period + 1:
            return []
        # true range
        trs = []
        for i in range(1, len(self._bars)):
            prev_close = self._bars[i - 1].close
            cur = self._bars[i]
            tr = max(float(cur.high - cur.low), abs(float(cur.high - prev_close)), abs(float(cur.low - prev_close)))
            trs.append(tr)
        atr = sum(trs[-self.atr_period :]) / self.atr_period
        # signal if bar range > multiplier * ATR
        bar_range = float(bar.high - bar.low)
        if bar_range > self.multiplier * atr:
            # direction by close vs open
            side = Side.BUY if bar.close > bar.open else Side.SELL
            return [
                Signal(
                    instrument=bar.instrument,
                    side=side,
                    strength=0.65,
                    event_time=bar.close_time,
                    hypothesis_id="H-VOL",
                    strategy_id=self.strategy_id,
                    features={"atr": atr, "range": bar_range},
                )
            ]
        return []


# ---------- REGIME-CONDITIONED ----------
class RegimeConditionedStrategy:
    """Wraps base strategy, only signals if detector says regime matches allowed."""

    def __init__(self, base_strategy: Any, allowed_regimes: list[str] | None = None, strategy_id: str | None = None):
        self.base = base_strategy
        self.allowed = set(allowed_regimes or ["trend"])
        self.strategy_id = strategy_id or f"{base_strategy.strategy_id}_regime"
        # carry instrument for factory
        self.instrument = base_strategy.instrument

    def on_bar(self, bar: Bar) -> list[Signal]:
        # simple regime heuristic: if closes trending up -> trend, else range
        # For real pipeline, use qts.regime.detector; here simplified for unit determinism
        # If base would signal, check regime quickly: look at last 10 closes
        sigs = self.base.on_bar(bar)
        if not sigs:
            return []
        # heuristic regime: compute last 10 bar slope
        closes = getattr(self.base, "_closes", None) or getattr(self.base, "_bars", None)
        if closes is not None and isinstance(closes, list) and len(closes) >= 10:
            # take last 10 closes
            if hasattr(closes[0], "close"):
                vals = [float(b.close) for b in closes[-10:]]
            else:
                vals = [float(c) for c in closes[-10:]]  # type: ignore
            slope = vals[-1] - vals[0]
            regime = "trend" if abs(slope) > 5 else "range"
            # allow high_vol if std high
            if len(vals) >= 10:
                mean = sum(vals) / len(vals)
                var = sum((x - mean) ** 2 for x in vals) / len(vals)
                if var**0.5 > 10:
                    regime = "high_vol"
            if regime not in self.allowed:
                return []
        # rewrite strategy_id to wrapper
        out = []
        for s in sigs:
            out.append(s.model_copy(update={"strategy_id": self.strategy_id}))
        return out


# ---------- FACTORY ----------
STRATEGY_FAMILIES = {
    StrategyFamily.TREND: TrendFollowingStrategy,
    StrategyFamily.BREAKOUT: BreakoutStrategy,
    StrategyFamily.MEAN_REVERSION: MeanReversionStrategy,
    StrategyFamily.MOMENTUM: MomentumStrategy,
    StrategyFamily.VOLATILITY: VolatilityStrategy,
}

# Parameter spaces bounded — for campaign generation
BOUNDED_PARAM_SPACE: dict[StrategyFamily, dict[str, list]] = {
    StrategyFamily.TREND: {"fast": [5, 10, 15], "slow": [20, 30, 50], "ma_type": ["sma"]},
    StrategyFamily.BREAKOUT: {"period": [10, 20, 30]},
    StrategyFamily.MEAN_REVERSION: {"period": [10, 20, 30], "k": [1.5, 2.0, 2.5]},
    StrategyFamily.MOMENTUM: {"lookback": [5, 10, 20], "threshold": [0.0, 1.0]},
    StrategyFamily.VOLATILITY: {"atr_period": [7, 14, 21], "multiplier": [1.0, 1.5, 2.0]},
}


def create_strategy(
    family: StrategyFamily, instrument: Instrument, params: dict[str, Any], strategy_id: str | None = None
) -> Any:
    cls = STRATEGY_FAMILIES[family]
    sid = strategy_id or f"{family.value}_{uuid7()[:6]}"
    return cls(instrument=instrument, strategy_id=sid, **params)


def describe_features(family: StrategyFamily, params: dict[str, Any]) -> dict[str, Any]:
    """Feature definition for registry — interpretable, not black-box."""
    base = {"family": family.value, "params": params}
    if family == StrategyFamily.TREND:
        base["features"] = {
            "sma_fast": params.get("fast"),
            "sma_slow": params.get("slow"),
            "crossover": "fast crosses slow",
        }
    elif family == StrategyFamily.BREAKOUT:
        base["features"] = {"donchian_period": params.get("period"), "breakout": "close > highest high or < lowest low"}
    elif family == StrategyFamily.MEAN_REVERSION:
        base["features"] = {
            "bb_period": params.get("period"),
            "k": params.get("k"),
            "reversion": "close outside Bollinger",
        }
    elif family == StrategyFamily.MOMENTUM:
        base["features"] = {"lookback": params.get("lookback"), "momentum": "close - close_n"}
    elif family == StrategyFamily.VOLATILITY:
        base["features"] = {
            "atr_period": params.get("atr_period"),
            "multiplier": params.get("multiplier"),
            "volatility_breakout": "range > mult*ATR",
        }
    return base
