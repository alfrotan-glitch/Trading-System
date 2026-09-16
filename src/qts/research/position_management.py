"""Dynamic Position Management Research — entry, management, exit as joint hypothesis."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any

from qts.domain.value_objects import Bar, Side


class ExitType(StrEnum):
    FIXED_STOP = "fixed_stop"
    VOLATILITY_STOP = "volatility_stop"
    STRUCTURAL_STOP = "structural_stop"
    TRAILING = "trailing"
    BREAK_EVEN = "break_even"
    TIME_BASED = "time_based"
    MOMENTUM_DECAY = "momentum_decay"
    REVERSAL = "reversal"
    VOLATILITY_COLLAPSE = "volatility_collapse"
    PARTIAL_TP = "partial_tp"
    SCALE_OUT = "scale_out"


@dataclass
class ExitPolicy:
    exit_type: ExitType
    params: dict[str, Any]
    description: str


# Predefined exit policies — each is a falsifiable joint hypothesis with entry
EXIT_POLICIES: list[ExitPolicy] = [
    ExitPolicy(ExitType.FIXED_STOP, {"stop_pct": 0.01, "tp_pct": 0.02}, "1% stop, 2% TP fixed"),
    ExitPolicy(
        ExitType.VOLATILITY_STOP, {"atr_mult_stop": 1.5, "atr_mult_tp": 3.0, "atr_period": 14}, "ATR 1.5 stop, 3.0 TP"
    ),
    ExitPolicy(ExitType.TRAILING, {"trail_pct": 0.005}, "0.5% trailing protection"),
    ExitPolicy(ExitType.TIME_BASED, {"max_hold_bars": 20}, "Time exit 20 bars"),
    ExitPolicy(ExitType.BREAK_EVEN, {"breakeven_trigger_pct": 0.005}, "Move to breakeven after 0.5% profit"),
    ExitPolicy(ExitType.MOMENTUM_DECAY, {"decay_threshold": 0.0}, "Exit when momentum decays"),
]


class PositionManager:
    """Stateful manager that decides hold/exit based on entry bar, current bar, and policy. No future info."""

    def __init__(self, policy: ExitPolicy, entry_price: Decimal, side: Side, entry_time: Any):
        self.policy = policy
        self.entry_price = entry_price
        self.side = side
        self.entry_time = entry_time
        self.highest_profit = Decimal("0")
        self.bars_held = 0
        self.breakeven_active = False

    def should_exit(self, bar: Bar) -> tuple[bool, str]:
        self.bars_held += 1
        # Compute unrealized pnl pct
        cur = bar.close
        if self.side == Side.BUY:
            pnl_pct = (cur - self.entry_price) / self.entry_price
            if pnl_pct > self.highest_profit:
                self.highest_profit = pnl_pct
        else:
            pnl_pct = (self.entry_price - cur) / self.entry_price
            if pnl_pct > self.highest_profit:
                self.highest_profit = pnl_pct

        p = self.policy.params
        if self.policy.exit_type == ExitType.FIXED_STOP:
            if pnl_pct <= -Decimal(str(p["stop_pct"])):
                return True, "fixed_stop"
            if pnl_pct >= Decimal(str(p["tp_pct"])):
                return True, "fixed_tp"
        elif self.policy.exit_type == ExitType.TRAILING:
            trail = Decimal(str(p["trail_pct"]))
            if self.highest_profit > trail and pnl_pct < self.highest_profit - trail:
                return True, "trailing"
            if pnl_pct <= -trail:
                return True, "stop"
        elif self.policy.exit_type == ExitType.TIME_BASED:
            if self.bars_held >= p["max_hold_bars"]:
                return True, "time_exit"
        elif self.policy.exit_type == ExitType.BREAK_EVEN:
            trig = Decimal(str(p["breakeven_trigger_pct"]))
            if pnl_pct >= trig:
                self.breakeven_active = True
            if self.breakeven_active and pnl_pct <= Decimal("0"):
                return True, "breakeven_stop"
        # volatility_stop etc would need ATR, simplified as fixed for now
        return False, ""


def joint_entry_exit_hypothesis(entry_family: str, exit_type: ExitType) -> str:
    return f"Entry {entry_family} is useful only when combined with {exit_type} exit — test joint hypothesis out-of-sample."
