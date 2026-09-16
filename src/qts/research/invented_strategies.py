"""Invented Strategies — beyond classic indicators: event-driven, state-machine, multi-timeframe, etc."""

from __future__ import annotations

from decimal import Decimal

from qts.domain.value_objects import Bar, Instrument, Side, Signal


class StateMachineStrategy:
    """State-machine: tracks compression→expansion, exhaustion→reversion, pullback→continuation."""

    def __init__(
        self,
        instrument: Instrument,
        strategy_id: str = "state_machine",
        compression_lookback: int = 10,
        expansion_threshold: float = 1.5,
    ):
        self.instrument = instrument
        self.strategy_id = strategy_id
        self.compression_lookback = compression_lookback
        self.expansion_threshold = expansion_threshold
        self._bars: list[Bar] = []
        self.state = "idle"  # idle, compressed, expanding

    def on_bar(self, bar: Bar) -> list[Signal]:
        self._bars.append(bar)
        if len(self._bars) < self.compression_lookback + 5:
            return []
        # compression: range over lookback small
        recent = self._bars[-self.compression_lookback :]
        ranges = [float(b.high - b.low) for b in recent]
        avg_range = sum(ranges) / len(ranges)
        long_range = sum(float(b.high - b.low) for b in self._bars[-20:]) / 20 if len(self._bars) >= 20 else avg_range
        # Detect compression
        if avg_range < long_range * 0.5:
            self.state = "compressed"
        # Expansion: current bar range large and close direction
        cur_range = float(bar.high - bar.low)
        if self.state == "compressed" and cur_range > avg_range * self.expansion_threshold:
            self.state = "expanding"
            side = Side.BUY if bar.close > bar.open else Side.SELL
            return [
                Signal(
                    instrument=bar.instrument,
                    side=side,
                    strength=0.6,
                    event_time=bar.close_time,
                    hypothesis_id="H-STATE",
                    strategy_id=self.strategy_id,
                    features={"state": self.state, "avg_range": avg_range},
                )
            ]
        if self.state == "expanding":
            self.state = "idle"
        return []


class EventDrivenStrategy:
    """Event-driven: reacts to unusually large moves (shock) — asymmetric response."""

    def __init__(self, instrument: Instrument, strategy_id: str = "event_shock", shock_threshold: float = 2.0):
        self.instrument = instrument
        self.strategy_id = strategy_id
        self.shock_threshold = shock_threshold
        self._closes: list[Decimal] = []

    def on_bar(self, bar: Bar) -> list[Signal]:
        self._closes.append(bar.close)
        if len(self._closes) < 20:
            return []
        # Compute rolling vol
        import numpy as np

        closes = [float(c) for c in self._closes[-20:]]
        rets = np.diff(closes) / np.array(closes[:-1])
        vol = np.std(rets)
        last_ret = (
            (float(bar.close) - float(self._closes[-2])) / float(self._closes[-2]) if float(self._closes[-2]) else 0.0
        )
        # Shock if |ret| > threshold * vol
        if vol > 0 and abs(last_ret) > self.shock_threshold * vol:
            # Asymmetric: after large up shock, expect exhaustion → mean reversion
            side = Side.SELL if last_ret > 0 else Side.BUY
            return [
                Signal(
                    instrument=bar.instrument,
                    side=side,
                    strength=0.55,
                    event_time=bar.close_time,
                    hypothesis_id="H-EVENT",
                    strategy_id=self.strategy_id,
                    features={"shock_ret": last_ret, "vol": vol},
                )
            ]
        return []


class MultiTimeframeStrategy:
    """Multi-timeframe: aggregates 1H into 4H structure (synthetic) — no future leakage."""

    def __init__(self, instrument: Instrument, strategy_id: str = "mtf_structure", fast: int = 5, slow: int = 20):
        self.instrument = instrument
        self.strategy_id = strategy_id
        self.fast = fast
        self.slow = slow
        self._bars: list[Bar] = []

    def on_bar(self, bar: Bar) -> list[Signal]:
        self._bars.append(bar)
        if len(self._bars) < self.slow + 4:
            return []
        # Higher timeframe: compress every 4 bars into 4H bar (close only)
        # Use only closed 4H bars (no future)
        htf_closes = []
        for i in range(0, len(self._bars) - 3, 4):
            htf_closes.append(self._bars[i + 3].close)
        if len(htf_closes) < self.slow:
            return []
        # 1H SMA
        fast_sma = sum(self._bars[-self.fast :][i].close for i in range(self.fast)) / Decimal(self.fast)
        # 4H SMA
        slow_sma = sum(htf_closes[-self.slow :]) / Decimal(self.slow) if len(htf_closes) >= self.slow else fast_sma
        # Signal if 1H fast > 4H slow and recent htf trending
        if fast_sma > slow_sma * Decimal("1.002"):
            return [
                Signal(
                    instrument=bar.instrument,
                    side=Side.BUY,
                    strength=0.6,
                    event_time=bar.close_time,
                    hypothesis_id="H-MTF",
                    strategy_id=self.strategy_id,
                    features={"fast": float(fast_sma), "htf_slow": float(slow_sma)},
                )
            ]
        if fast_sma < slow_sma * Decimal("0.998"):
            return [
                Signal(
                    instrument=bar.instrument,
                    side=Side.SELL,
                    strength=0.6,
                    event_time=bar.close_time,
                    hypothesis_id="H-MTF",
                    strategy_id=self.strategy_id,
                    features={"fast": float(fast_sma), "htf_slow": float(slow_sma)},
                )
            ]
        return []


class VolatilityNormalizedStrategy:
    """Volatility-normalized: entry threshold scaled by recent ATR."""

    def __init__(
        self, instrument: Instrument, strategy_id: str = "vol_norm", atr_period: int = 14, threshold_mult: float = 1.0
    ):
        self.instrument = instrument
        self.strategy_id = strategy_id
        self.atr_period = atr_period
        self.threshold_mult = threshold_mult
        self._bars: list[Bar] = []

    def on_bar(self, bar: Bar) -> list[Signal]:
        self._bars.append(bar)
        if len(self._bars) < self.atr_period + 1:
            return []
        # ATR
        trs = []
        for i in range(1, len(self._bars)):
            prev_close = self._bars[i - 1].close
            cur = self._bars[i]
            tr = max(float(cur.high - cur.low), abs(float(cur.high - prev_close)), abs(float(cur.low - prev_close)))
            trs.append(tr)
        atr = sum(trs[-self.atr_period :]) / self.atr_period
        # Normalized move: close - open > mult*ATR
        move = float(bar.close - bar.open)
        if move > self.threshold_mult * atr:
            return [
                Signal(
                    instrument=bar.instrument,
                    side=Side.BUY,
                    strength=0.6,
                    event_time=bar.close_time,
                    hypothesis_id="H-VOLNORM",
                    strategy_id=self.strategy_id,
                    features={"atr": atr, "move": move},
                )
            ]
        if move < -self.threshold_mult * atr:
            return [
                Signal(
                    instrument=bar.instrument,
                    side=Side.SELL,
                    strength=0.6,
                    event_time=bar.close_time,
                    hypothesis_id="H-VOLNORM",
                    strategy_id=self.strategy_id,
                    features={"atr": atr, "move": move},
                )
            ]
        return []
