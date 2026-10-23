"""Causal tick-sequenced scalp research, fully recomputing subsequent trades.

Signal: previous completed M1 mid close. Entry: first quote of the next
observed minute. Exit: first eligible chronological broker-side quote.
This is NOT real broker execution, latency measurement, a strategy optimizer,
or permission for DEMO/LIVE orders. Uses fixed preregistered logic only.
"""

from __future__ import annotations

from collections import deque
from decimal import Decimal
from typing import Any, Literal

import numpy as np

from qts.execution.scalp_exit import ScalpExitPlan
from qts.research.demo_scalp_provider import DEFAULT_PARAMS
from qts.research.scalp_regimes import (
    ScalpIdea,
    early_entry_still_has_room,
    propose_anticipatory_entry,
    propose_scalp_entry,
)
from qts.research.scalp_replay import ReplayAssumptions

MINUTE_MS = 60_000
BPS = Decimal("10000")
MODE = Literal["confirmed", "anticipatory"]


def _check_assumptions(values: ReplayAssumptions) -> None:
    params = DEFAULT_PARAMS
    if (
        values.max_entry_spread_bps != Decimal(str(params["max_spread_bps"]))
        or values.extra_cost_reserve_bps != Decimal(str(params["extra_cost_reserve_bps"]))
        or values.minimum_movement_margin_bps != Decimal(
            str(params["min_price_movement_after_cost_bps"])
        )
        or values.stop_distance_price != Decimal(str(params["stop_distance_price"]))
        or values.max_hold_bars != int(params["max_hold_seconds"] // 60)
    ):
        raise ValueError("tick replay thresholds must match frozen scalp strategy parameters")


def _numbers(trades: list[dict[str, Any]]) -> dict[str, Any]:
    if not trades:
        return {
            "trades": 0, "mean_net_bps": None, "median_net_bps": None,
            "win_rate": None, "total_net_bps_additive": None,
            "max_drawdown_bps_additive": None, "by_family": {}, "exit_reasons": {},
        }
    nets = np.array([float(t["net_bps"]) for t in trades], dtype=np.float64)
    running = np.cumsum(nets)
    max_drawdown = max(0.0, float(np.max(np.maximum.accumulate(np.r_[0.0, running])[1:] - running)))
    by_family: dict[str, dict[str, Any]] = {}
    families = sorted({str(t["family"]) for t in trades})
    for family in families:
        values = np.array([float(t["net_bps"]) for t in trades if t["family"] == family])
        by_family[family] = {
            "trades": len(values),
            "mean_net_bps": float(values.mean()),
            "win_rate": float(np.mean(values > 0)),
        }
    reasons: dict[str, int] = {}
    for t in trades:
        key = str(t["exit_reason"])
        reasons[key] = reasons.get(key, 0) + 1
    return {
        "trades": len(trades),
        "mean_net_bps": float(nets.mean()),
        "median_net_bps": float(np.median(nets)),
        "win_rate": float(np.mean(nets > 0)),
        "total_net_bps_additive": float(nets.sum()),
        "max_drawdown_bps_additive": max_drawdown,
        "by_family": by_family,
        "exit_reasons": reasons,
    }


class TickScalpReplay:
    """One chronological stream, one position, decisions recomputed after exits."""

    def __init__(
        self,
        *,
        mode: MODE,
        exit_plan: ScalpExitPlan,
        assumptions: ReplayAssumptions | None = None,
        end_exclusive_time_msc: int,
    ) -> None:
        if mode not in ("confirmed", "anticipatory"):
            raise ValueError("unknown tick scalp entry mode")
        if end_exclusive_time_msc <= 0 or end_exclusive_time_msc % MINUTE_MS:
            raise ValueError("research cutoff must be positive and minute-aligned")
        self.mode = mode
        self.plan = exit_plan
        self.assumptions = ReplayAssumptions() if assumptions is None else assumptions
        _check_assumptions(self.assumptions)
        self.cutoff = end_exclusive_time_msc
        self.closes: deque[Decimal] = deque(maxlen=34)
        self.minute: int | None = None
        self.previous_close_mid: Decimal | None = None
        self.position: dict[str, Any] | None = None
        self.trades: list[dict[str, Any]] = []
        self.quote_rows = 0
        self.completed_bars = 0
        self.minute_gaps = 0
        self.signals = 0
        self.cost_refusals = 0
        self.chase_refusals = 0
        self.last_timestamp: int | None = None
        self.last_bid: Decimal | None = None
        self.last_ask: Decimal | None = None
        self.first_stamp: int | None = None

    def _liquidate(
        self,
        *,
        stamp: int,
        price: Decimal,
        reason: str,
        uncertain: bool = False,
    ) -> None:
        pos = self.position
        if pos is None:
            return
        assumed = self.assumptions
        entry = Decimal(pos["entry_price"])
        slip = price * assumed.exit_slippage_bps / BPS
        fill = price - slip if pos["side"] == "BUY" else price + slip
        move = fill - entry if pos["side"] == "BUY" else entry - fill
        net = move * BPS / entry - assumed.round_trip_commission_bps
        self.trades.append({
            "signal_time_msc": pos["signal_time_msc"],
            "entry_time_msc": pos["entry_time_msc"],
            "exit_time_msc": stamp,
            "entry_price": str(entry),
            "stop_price": str(pos["stop"]),
            "exit_price_after_slippage": str(fill),
            "net_bps": str(net),
            "side": pos["side"],
            "family": pos["family"],
            "regime": pos["regime"],
            "exit_reason": reason,
            "exit_quote_uncertain": uncertain,
        })
        self.position = None

    def _entry(
        self,
        candidate: ScalpIdea | None,
        *,
        stamp: int,
        bid: Decimal,
        ask: Decimal,
        source_bar_start: int,
    ) -> None:
        if candidate is None or self.position is not None:
            return
        mid = (bid + ask) / 2
        if bid <= 0 or ask <= bid:
            self.cost_refusals += 1
            return
        spread = (ask - bid) * BPS / mid
        proxy = candidate.movement_proxy_price * BPS / mid
        a = self.assumptions
        required = spread + a.extra_cost_reserve_bps + a.minimum_movement_margin_bps
        if spread > a.max_entry_spread_bps or proxy <= required:
            self.cost_refusals += 1
            return
        if not early_entry_still_has_room(
            candidate, bid=bid, ask=ask, reserve_bps=a.extra_cost_reserve_bps,
            margin_bps=a.minimum_movement_margin_bps,
        ):
            self.chase_refusals += 1
            return
        quote = ask if candidate.side == "BUY" else bid
        slip = quote * a.entry_slippage_bps / BPS
        entry = quote + slip if candidate.side == "BUY" else quote - slip
        stop = quote - a.stop_distance_price if candidate.side == "BUY" else quote + a.stop_distance_price
        if stop <= 0:
            self.cost_refusals += 1
            return
        self.position = {
            "entry_time_msc": stamp,
            "signal_time_msc": source_bar_start,
            "entry_price": str(entry),
            "side": candidate.side,
            "stop": str(stop),
            "family": candidate.family,
            "regime": candidate.regime,
        }

    def _scan_exits(
        self, stamps: np.ndarray, bids: np.ndarray, asks: np.ndarray
    ) -> None:
        position = self.position
        if position is None or len(stamps) == 0:
            return
        side = str(position["side"])
        entry = float(position["entry_price"])
        stop = float(position["stop"])
        liquidation = bids if side == "BUY" else asks
        opposite = asks if side == "BUY" else bids
        adverse_stop = liquidation <= stop if side == "BUY" else liquidation >= stop
        quote_bps = (liquidation - entry) * 10000 / entry if side == "BUY" else (
            entry - liquidation
        ) * 10000 / entry
        reserved = quote_bps - float(self.plan.extra_cost_reserve_bps)
        max_loss = reserved <= -float(self.plan.max_loss_net_bps)
        spreads = asks - bids
        mids = (asks + bids) / 2
        allowed_profit = (
            (reserved >= float(self.plan.take_profit_net_bps))
            & (spreads * 10000 / mids <= float(self.plan.max_spread_bps))
            & (opposite > liquidation if side == "BUY" else liquidation > opposite)
        )
        expiry = stamps - int(position["entry_time_msc"]) >= self.assumptions.max_hold_bars * MINUTE_MS
        available = adverse_stop | max_loss | allowed_profit | expiry
        hits = np.flatnonzero(available)
        if hits.size == 0:
            return
        index = int(hits[0])
        if adverse_stop[index]:
            reason = "tick_stop_quote_crossing"
        elif max_loss[index]:
            reason = "scalp_max_loss"
        elif allowed_profit[index]:
            reason = "scalp_take_profit"
        else:
            reason = "tick_time_exit"
        self._liquidate(
            stamp=int(stamps[index]),
            price=Decimal(str(float(liquidation[index]))),
            reason=reason,
        )

    def _minute_quotes(
        self, minute: int, stamps: np.ndarray, bids: np.ndarray, asks: np.ndarray
    ) -> None:
        first_bid = Decimal(str(float(bids[0])))
        first_ask = Decimal(str(float(asks[0])))
        candidate: ScalpIdea | None = None
        if self.minute is None:
            self.minute = minute
        elif minute != self.minute:
            if minute - self.minute == 1 and self.previous_close_mid is not None:
                self.closes.append(self.previous_close_mid)
                self.completed_bars += 1
                if self.position is None:
                    if self.mode == "confirmed":
                        candidate = propose_scalp_entry(self.closes)
                    else:
                        candidate = propose_anticipatory_entry(self.closes)
                    if candidate is not None:
                        self.signals += 1
            else:
                self.minute_gaps += 1
                if self.position is not None:
                    price = first_bid if self.position["side"] == "BUY" else first_ask
                    self._liquidate(
                        stamp=int(stamps[0]), price=price,
                        reason="gap_first_available_quote", uncertain=True,
                    )
                self.closes.clear()
            self.minute = minute
        if candidate is not None:
            self._entry(
                candidate, stamp=int(stamps[0]), bid=first_bid, ask=first_ask,
                source_bar_start=(minute - 1) * MINUTE_MS,
            )
        self._scan_exits(stamps, bids, asks)
        self.previous_close_mid = (
            Decimal(str(float(bids[-1]))) + Decimal(str(float(asks[-1])))
        ) / 2
        self.last_bid = Decimal(str(float(bids[-1])))
        self.last_ask = Decimal(str(float(asks[-1])))

    def consume(self, time_msc: np.ndarray, bid: np.ndarray, ask: np.ndarray) -> None:
        stamps = np.asarray(time_msc, dtype=np.int64)
        bids = np.asarray(bid, dtype=np.float64)
        asks = np.asarray(ask, dtype=np.float64)
        if stamps.ndim != 1 or bids.shape != stamps.shape or asks.shape != stamps.shape:
            raise ValueError("invalid tick replay batch dimensions")
        size = int(np.searchsorted(stamps, self.cutoff, side="left"))
        stamps, bids, asks = stamps[:size], bids[:size], asks[:size]
        if not len(stamps):
            return
        if (
            np.any(stamps < 0) or np.any(stamps[1:] < stamps[:-1])
            or (self.last_timestamp is not None and int(stamps[0]) < self.last_timestamp)
        ):
            raise ValueError("raw tick ordering changed; replay refused")
        if (
            not np.isfinite(bids).all() or not np.isfinite(asks).all()
            or np.any(bids <= 0) or np.any(asks < bids)
        ):
            raise ValueError("invalid raw executable quote; replay refused")
        if self.first_stamp is None:
            self.first_stamp = int(stamps[0])
        self.quote_rows += len(stamps)
        self.last_timestamp = int(stamps[-1])
        # Batches are intentionally small. Find minute seams without
        # materializing a second array of all minute IDs for each batch.
        left = 0
        while left < len(stamps):
            minute = int(stamps[left]) // MINUTE_MS
            right = int(np.searchsorted(stamps, (minute + 1) * MINUTE_MS, side="left"))
            self._minute_quotes(minute, stamps[left:right], bids[left:right], asks[left:right])
            left = right

    def report(self) -> dict[str, Any]:
        if self.position is not None:
            if self.last_timestamp is None or self.last_bid is None or self.last_ask is None:
                raise ValueError("cannot liquidate remaining position without a quote")
            value = self.last_bid if self.position["side"] == "BUY" else self.last_ask
            self._liquidate(
                stamp=self.last_timestamp, price=value,
                reason="end_of_discovery_liquidation", uncertain=True,
            )
        return {
            "schema": "qts.scalp_tick_sequenced_replay.v1",
            "status": "RESEARCH_ONLY_QUOTE_EXECUTION_ASSUMED",
            "entry_mode": self.mode,
            "raw_quote_rows": self.quote_rows,
            "completed_contiguous_bars": self.completed_bars,
            "minute_gaps": self.minute_gaps,
            "signals": self.signals,
            "entry_refusals_cost": self.cost_refusals,
            "entry_refusals_chase": self.chase_refusals,
            "metrics": _numbers(self.trades),
            "trades": self.trades,
            "limitations": [
                "first observed quote is not a broker execution fill",
                "entry and exit slippage and commissions are explicit assumptions",
                "no recorded order latency, market impact, queue priority or broker deal matching",
                "discovery period only, repeatedly inspected; not independent validation",
                "quote-based exit decisions evaluated at zero acquisition latency",
            ],
            "strategy_promoted": False,
            "orders_submitted": 0,
            "LIVE": "LOCKED",
        }
