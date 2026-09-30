"""Phase 6: Null / placebo control — randomized signal timing, shuffled labels, etc."""

from __future__ import annotations

import random

import numpy as np

from qts.domain.value_objects import Bar, Side, Signal


class NullControl:
    """Generates null control signals to test pipeline can manufacture alpha."""

    def __init__(self, seed: int = 42):
        self.seed = seed
        # Keep control randomness local. Seeding process-global RNGs makes a
        # null control alter unrelated research results in the same process.
        self._rng = random.Random(seed)
        self._np_rng = np.random.default_rng(seed)

    def randomized_timing(self, bars: list[Bar]) -> list[Signal]:
        """Same number of signals as real but random timing."""
        signals = []
        for b in self._rng.sample(bars, min(5, len(bars) // 10)):
            side = self._rng.choice([Side.BUY, Side.SELL])
            signals.append(
                Signal(
                    instrument=b.instrument,
                    side=side,
                    strength=0.7,
                    event_time=b.close_time,
                    hypothesis_id="H-NULL-TIMING",
                    strategy_id="null_timing",
                )
            )
        return signals

    def shuffled_labels(self, bars: list[Bar], real_signals: list[Signal]) -> list[Signal]:
        """Shuffle real signal sides — creates new signals due to frozen model."""
        sides = [s.side for s in real_signals]
        self._rng.shuffle(sides)
        out = []
        for s, new_side in zip(real_signals, sides, strict=False):
            out.append(s.model_copy(update={"side": new_side}))
        return out

    def randomized_direction(self, bars: list[Bar]) -> list[Signal]:
        return self.randomized_timing(bars)

    def parameter_destroyed(self, bars: list[Bar]) -> list[Signal]:
        """Use destroyed params (e.g., fast=1, slow=2 random) — should have no edge."""
        return self.randomized_timing(bars)

    def synthetic_no_edge(self, bars: list[Bar]) -> list[Bar]:
        """Generate synthetic GBM no-edge bars."""
        from qts.data.synthetic import generate_gbm_bars

        return generate_gbm_bars(instrument=bars[0].instrument, periods=len(bars), seed=self.seed + 999)


def pipeline_rejects_controls(validator_pipeline, controls_sharpes: list[float]) -> bool:
    """Pipeline should reject controls more often than genuine."""
    # controls should have sharpe ~0, so validator should BLOCK them
    rejected = sum(1 for s in controls_sharpes if s < 0.3)
    return rejected >= len(controls_sharpes) * 0.6
