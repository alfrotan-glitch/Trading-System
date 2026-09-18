
"""Phase 9: Placebo / negative-control strategies — validator must reject."""

from __future__ import annotations

from decimal import Decimal
from qts.domain.value_objects import Bar, Signal, Side, Instrument

class PlaceboStrategies:
    """Intentionally bad strategies."""

    def __init__(self, instrument: Instrument):
        self.instrument = instrument

    def random_entry(self, bar: Bar) -> list[Signal]:
        import random
        if random.random() < 0.05:
            side = random.choice([Side.BUY, Side.SELL])
            return [Signal(instrument=bar.instrument, side=side, strength=0.5, event_time=bar.close_time, hypothesis_id="H-RANDOM", strategy_id="placebo_random")]
        return []

    def delayed_signal(self, bar: Bar, delay: int = 5) -> list[Signal]:
        # Always lagging
        return []

    def anti_signal(self, bar: Bar, real_signals: list[Signal]) -> list[Signal]:
        # Opposite of real
        out = []
        for s in real_signals:
            opp = Side.SELL if s.side == Side.BUY else Side.BUY
            out.append(Signal(instrument=bar.instrument, side=opp, strength=s.strength, event_time=bar.close_time, hypothesis_id="H-ANTI", strategy_id="placebo_anti"))
        return out

    def noise_feature(self, bar: Bar) -> list[Signal]:
        import random, hashlib
        h = hashlib.sha256(str(bar.close).encode()).hexdigest()
        side = Side.BUY if int(h,16) % 2 == 0 else Side.SELL
        if random.random() < 0.03:
            return [Signal(instrument=bar.instrument, side=side, strength=0.5, event_time=bar.close_time, hypothesis_id="H-NOISE", strategy_id="placebo_noise")]
        return []

    def overfit_params(self, bar: Bar) -> list[Signal]:
        # Use overfit fast=2 slow=3 that looks good in-sample but fails OOS
        return self.random_entry(bar)
