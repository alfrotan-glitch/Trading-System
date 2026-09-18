"""Placebo / negative-control strategy generators.

These controls are deliberately labelled and deterministic.  They may be run
against a real measured bar population, but their outputs are never evidence
for a positive strategy and they are never replaced by random score lists.
"""

from __future__ import annotations

import hashlib
import random

from qts.domain.value_objects import Bar, Instrument, Side, Signal


class PlaceboStrategies:
    """Intentionally negative controls with a reproducible local RNG."""

    def __init__(self, instrument: Instrument, seed: int = 42):
        self.instrument = instrument
        self.seed = seed
        self._rng = random.Random(seed)

    def random_entry(self, bar: Bar) -> list[Signal]:
        if self._rng.random() < 0.05:
            side = self._rng.choice([Side.BUY, Side.SELL])
            return [
                Signal(
                    instrument=bar.instrument,
                    side=side,
                    strength=0.5,
                    event_time=bar.close_time,
                    hypothesis_id=f"H-PLACEBO-RANDOM-{self.seed}",
                    strategy_id="placebo_random",
                )
            ]
        return []

    def delayed_signal(self, bar: Bar, delay: int = 5) -> list[Signal]:
        # A delayed control is intentionally empty at the current decision
        # point; a caller must construct the delayed event population itself.
        if delay < 0:
            raise ValueError("delay must be non-negative")
        return []

    def anti_signal(self, bar: Bar, real_signals: list[Signal]) -> list[Signal]:
        """Opposite-side control, preserving the original event identity fields."""
        out: list[Signal] = []
        for signal in real_signals:
            opposite = Side.SELL if signal.side == Side.BUY else Side.BUY
            out.append(
                Signal(
                    instrument=bar.instrument,
                    side=opposite,
                    strength=signal.strength,
                    event_time=bar.close_time,
                    hypothesis_id="H-PLACEBO-ANTI",
                    strategy_id="placebo_anti",
                )
            )
        return out

    def noise_feature(self, bar: Bar) -> list[Signal]:
        # Derive a deterministic draw from the declared seed and event identity;
        # no process-global random state and no hidden stochastic rerun.
        digest = hashlib.sha256(f"{self.seed}:{bar.instrument.symbol}:{bar.close_time.isoformat()}".encode()).digest()
        draw = int.from_bytes(digest[:8], "big") / 2**64
        if draw < 0.03:
            side = Side.BUY if digest[8] % 2 == 0 else Side.SELL
            return [
                Signal(
                    instrument=bar.instrument,
                    side=side,
                    strength=0.5,
                    event_time=bar.close_time,
                    hypothesis_id=f"H-PLACEBO-NOISE-{self.seed}",
                    strategy_id="placebo_noise",
                )
            ]
        return []

    def overfit_params(self, bar: Bar) -> list[Signal]:
        """A declared overfit-parameter control, using the deterministic random entry."""
        return self.random_entry(bar)
