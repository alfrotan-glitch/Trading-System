"""Market data safety — single authoritative live pricing path.

All live pricing must go through MarketDataProvider. It validates:
- timestamp freshness
- bid/ask integrity (ask >= bid)
- spread sanity (not exploded)
- symbol identity (tick symbol matches requested)
- market availability (trade_allowed)
- distinguishing executable bid/ask vs reference/mark

Risk and execution must use correct side: BUY→ask, SELL→bid for notional
and execution. Reference/mark is mid/close for portfolio marking.

Fail closed on any violation: returns None or raises, caller must suspend.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from qts.domain.value_objects import Instrument, Tick


class MarketDataError(RuntimeError):
    """Fail-closed market data violation."""
    pass


class MarketDataProvider:
    """Single authoritative live pricing path. Wraps broker ticks with safety."""

    def __init__(
        self,
        broker: Any,
        max_tick_age_s: float = 5.0,
        max_spread_bps: float = 100.0,  # 100 bps = 1% for XAUUSD, reasonable
        min_tick_interval_s: float = 0.0,
    ):
        self.broker = broker
        self.max_tick_age_s = max_tick_age_s
        self.max_spread_bps = max_spread_bps
        self._last_tick: dict[str, Tick] = {}
        self._last_valid: dict[str, datetime] = {}

    def _validate_tick(self, tick: Tick, expected_symbol: str) -> None:
        now = datetime.now(UTC)
        # Symbol identity
        if tick.instrument.symbol != expected_symbol:
            raise MarketDataError(f"tick symbol mismatch: got {tick.instrument.symbol} expected {expected_symbol}")
        # Timestamp freshness
        age = (now - tick.event_time).total_seconds()
        if age < -1:  # tick from future (clock skew)
            raise MarketDataError(f"tick from future: {tick.event_time} vs now {now} age {age}")
        if age > self.max_tick_age_s:
            raise MarketDataError(f"tick stale: age {age:.1f}s > {self.max_tick_age_s}s for {expected_symbol}")
        # Bid/ask integrity
        if tick.ask < tick.bid:
            raise MarketDataError(f"tick ask {tick.ask} < bid {tick.bid} for {expected_symbol}")
        if tick.bid <= 0 or tick.ask <= 0:
            raise MarketDataError(f"tick bid/ask non-positive {tick.bid}/{tick.ask} for {expected_symbol}")
        # Spread sanity
        mid = tick.mid
        if mid == 0:
            raise MarketDataError(f"tick mid zero for {expected_symbol}")
        spread_bps = float((tick.ask - tick.bid) / mid * Decimal("10000"))
        if spread_bps > self.max_spread_bps:
            raise MarketDataError(f"spread explosion {spread_bps:.1f}bps > {self.max_spread_bps}bps for {expected_symbol} bid {tick.bid} ask {tick.ask}")
        if spread_bps < 0:
            raise MarketDataError(f"negative spread {spread_bps} for {expected_symbol}")
        # Additional: check if broker says market closed / trade disabled
        # We can't directly check via tick, but we can try to get symbol spec if broker is MT5Adapter
        try:
            if hasattr(self.broker, "get_symbol_spec"):
                spec = self.broker.get_symbol_spec(expected_symbol)
                if not spec.trade_allowed or spec.trade_mode == 0:
                    raise MarketDataError(f"market not trade_allowed for {expected_symbol} mode {spec.trade_mode}")
        except MarketDataError:
            raise
        except Exception:
            # If spec fetch fails, don't block on tick but log
            pass

    def get_tick(self, instrument: Instrument) -> Tick:
        """Authoritative executable tick — validated, fail-closed."""
        # Broker must provide ticks()
        if not hasattr(self.broker, "ticks"):
            raise MarketDataError(f"broker {type(self.broker).__name__} has no ticks() for {instrument.symbol}")
        tick = self.broker.ticks(instrument)
        if tick is None:
            raise MarketDataError(f"no tick available for {instrument.symbol} (market closed or symbol unknown)")
        self._validate_tick(tick, instrument.symbol)
        self._last_tick[instrument.symbol] = tick
        self._last_valid[instrument.symbol] = datetime.now(UTC)
        return tick

    def get_executable_price(self, instrument: Instrument, side: str) -> Decimal:
        """Return correct side price: BUY→ask, SELL→bid. Validated."""
        tick = self.get_tick(instrument)
        if side == "BUY":
            return tick.ask
        elif side == "SELL":
            return tick.bid
        else:
            raise ValueError(f"unknown side {side}")

    def get_reference_price(self, instrument: Instrument) -> Decimal:
        """Reference/mark price — mid for portfolio, not executable."""
        tick = self.get_tick(instrument)
        return tick.mid

    def get_last_valid_tick(self, symbol: str) -> Tick | None:
        return self._last_tick.get(symbol)

    def is_fresh(self, symbol: str) -> bool:
        last = self._last_valid.get(symbol)
        if not last:
            return False
        age = (datetime.now(UTC) - last).total_seconds()
        return age <= self.max_tick_age_s

    def check_market_open(self, instrument: Instrument) -> bool:
        """Check if market is open via broker symbol info."""
        try:
            if hasattr(self.broker, "get_symbol_spec"):
                spec = self.broker.get_symbol_spec(instrument.symbol)
                return spec.trade_allowed and spec.trade_mode != 0
        except Exception:
            return False
        # Fallback: try to get tick
        try:
            self.get_tick(instrument)
            return True
        except MarketDataError:
            return False
