"""Explicit, auditable transaction-cost model for impulse research.

Every number here is a DECLARED ASSUMPTION (class=ESTIMATED), not a broker
observation. Nothing in this module fabricates market data: costs are applied
to measured bar returns and every scenario is recorded in the evidence so a
reviewer can recompute net expectancy by hand.

Conventions
-----------
* All costs are expressed in basis points (bps) of notional, per round turn
  unless stated otherwise.
* ``latency_bars`` models execution delay: the position is entered at the
  CLOSE of the bar ``latency_bars`` after the detection bar (bar-close
  execution is the only fill model this research layer claims; we never
  assume an order was filled because it was submitted).
* The half-spread convention: entering and exiting at bar closes straddles
  the spread once per side => total spread cost = ``spread_bps``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

# 1 bp = 0.01% of notional.
BPS = 1e-4


@dataclass(frozen=True)
class CostAssumptions:
    """Declared cost assumptions (ESTIMATED — audit trail, not broker data).

    Defaults are conservative placeholders for XAUUSD CFD-style execution and
    are explicitly labeled as assumptions. They MUST be overridden with
    broker-observed values before any claim about real-market tradability.
    """

    spread_bps: float = 2.0  # ASSUMPTION: ~$0.40 on $2000 gold, round turn
    commission_bps_round_turn: float = 0.4  # ASSUMPTION: ~$7/lot on $200k notional
    slippage_bps_per_side: float = 0.5  # ASSUMPTION: half-spread-style impact per side
    latency_bars: int = 1  # ASSUMPTION: one bar of decision+execution delay

    provenance: str = "ESTIMATED:declared_assumption"

    def round_turn_cost_bps(self) -> float:
        """Total cost in bps charged against each event's gross return."""
        return self.spread_bps + self.commission_bps_round_turn + 2.0 * self.slippage_bps_per_side

    def net_bps(self, gross_bps: float) -> float:
        return gross_bps - self.round_turn_cost_bps()

    def with_cost_multiplier(self, multiplier: float) -> CostAssumptions:
        if multiplier <= 0:
            raise ValueError("cost multiplier must be > 0")
        return replace(
            self,
            spread_bps=self.spread_bps * multiplier,
            commission_bps_round_turn=self.commission_bps_round_turn * multiplier,
            slippage_bps_per_side=self.slippage_bps_per_side * multiplier,
        )

    def with_spread_multiplier(self, multiplier: float) -> CostAssumptions:
        if multiplier <= 0:
            raise ValueError("spread multiplier must be > 0")
        return replace(self, spread_bps=self.spread_bps * multiplier)

    def with_latency(self, latency_bars: int) -> CostAssumptions:
        if latency_bars < 0:
            raise ValueError("latency_bars must be >= 0")
        return replace(self, latency_bars=latency_bars)

    def as_dict(self) -> dict[str, object]:
        return {
            "spread_bps": self.spread_bps,
            "commission_bps_round_turn": self.commission_bps_round_turn,
            "slippage_bps_per_side": self.slippage_bps_per_side,
            "latency_bars": self.latency_bars,
            "round_turn_cost_bps": self.round_turn_cost_bps(),
            "provenance": self.provenance,
        }


# Pre-registered sensitivity axes (deliberately small — no arbitrary grids).
COST_MULTIPLIERS: tuple[float, ...] = (0.5, 1.0, 1.5, 2.0)
SPREAD_MULTIPLIERS: tuple[float, ...] = (0.5, 1.0, 1.5, 2.0)
LATENCY_BARS: tuple[int, ...] = (0, 1, 2)

BASE_COSTS = CostAssumptions()
