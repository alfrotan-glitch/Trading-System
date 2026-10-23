"""Research-only causal replay for QTS's frozen one-minute scalp candidates.

This is a *bar approximation*, not a production execution simulator. Stop
touches have unknown bid/ask sequence and are filled conservatively at the
worse of the configured stop and observed closing liquidation quote. All such
fills are marked uncertain; no result from this module can promote a strategy.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

import numpy as np

from qts.execution.scalp_exit import ScalpExitPlan, decide_scalp_exit
from qts.research.demo_scalp_provider import DEFAULT_PARAMS
from qts.research.scalp_regimes import (
    ScalpIdea,
    propose_anticipatory_entry,
    propose_scalp_entry,
)
from qts.research.xauusd_broker_ml import BrokerBars

MINUTE_MS = 60_000
BPS = Decimal("10000")


@dataclass(frozen=True)
class ReplayAssumptions:
    """Conservative named assumptions, never observed broker fill statistics."""

    entry_slippage_bps: Decimal = Decimal("0.5")
    exit_slippage_bps: Decimal = Decimal("0.5")
    round_trip_commission_bps: Decimal = Decimal("1")
    stop_distance_price: Decimal = Decimal("3")
    max_hold_bars: int = 15
    max_entry_spread_bps: Decimal = Decimal("3")
    extra_cost_reserve_bps: Decimal = Decimal("2")
    minimum_movement_margin_bps: Decimal = Decimal("1")

    def __post_init__(self) -> None:
        for name in (
            "entry_slippage_bps", "exit_slippage_bps", "round_trip_commission_bps",
            "stop_distance_price", "max_hold_bars", "max_entry_spread_bps",
            "extra_cost_reserve_bps", "minimum_movement_margin_bps",
        ):
            value = Decimal(str(getattr(self, name)))
            if not value.is_finite() or value < 0 or (name in (
                "stop_distance_price", "max_hold_bars", "max_entry_spread_bps",
                "extra_cost_reserve_bps", "minimum_movement_margin_bps",
            ) and value == 0):
                raise ValueError(f"{name} must be a finite nonnegative replay assumption")
        if int(self.max_hold_bars) != self.max_hold_bars:
            raise ValueError("max_hold_bars must be a positive integer")


def _validate_bars(bars: BrokerBars) -> None:
    columns = (
        "time_msc", "open_bid", "open_ask", "high_mid", "low_mid",
        "close_bid", "close_ask",
    )
    arrays = [np.asarray(getattr(bars, name)) for name in columns]
    if any(v.ndim != 1 or len(v) != len(arrays[0]) for v in arrays):
        raise ValueError("replay requires equal-length one-dimensional broker bars")
    if len(arrays[0]) < 2 or not np.isfinite(arrays[0]).all():
        raise ValueError("replay requires at least two bars with finite timestamps")
    if np.any(arrays[0] % MINUTE_MS != 0) or np.any(np.diff(arrays[0]) <= 0):
        raise ValueError("replay bars must be strictly ordered, minute-aligned and unique")
    for v in arrays[1:]:
        if not np.isfinite(v).all() or np.any(v <= 0):
            raise ValueError("replay requires finite positive broker quotes")
    if np.any(arrays[2] <= arrays[1]) or np.any(arrays[6] <= arrays[5]):
        raise ValueError("replay requires positive open/close bid-ask spreads")
    if np.any(arrays[3] < arrays[4]):
        raise ValueError("replay has inverted within-minute high/low")
    if (bars.low_bid is None) != (bars.high_ask is None):
        raise ValueError("replay requires both broker-side extrema or neither")
    if bars.low_bid is not None and bars.high_ask is not None:
        lowest = np.asarray(bars.low_bid)
        highest = np.asarray(bars.high_ask)
        if (
            lowest.shape != arrays[0].shape or highest.shape != arrays[0].shape
            or not np.isfinite(lowest).all() or not np.isfinite(highest).all()
            or np.any(lowest <= 0) or np.any(lowest > np.minimum(arrays[1], arrays[5]))
            or np.any(highest < np.maximum(arrays[2], arrays[6]))
        ):
            raise ValueError("replay has invalid broker-side quote extrema")


def _spread_bps(bid: Decimal, ask: Decimal) -> Decimal:
    return (ask - bid) * BPS / ((bid + ask) / 2)


def _summarize(trades: list[dict[str, Any]]) -> dict[str, Any]:
    if not trades:
        return {
            "trades": 0, "win_rate": None, "mean_net_bps": None,
            "total_net_bps_additive": None, "max_drawdown_bps_additive": None,
            "uncertain_intrabar_stop_count": 0, "uncertain_exit_count": 0, "by_family": {},
        }
    nets = [Decimal(t["net_bps"]) for t in trades]
    cumulative = Decimal(0)
    peak = Decimal(0)
    max_drawdown = Decimal(0)
    for value in nets:
        cumulative += value
        peak = max(peak, cumulative)
        max_drawdown = max(max_drawdown, peak - cumulative)
    families: dict[str, list[Decimal]] = {}
    for t, n in zip(trades, nets, strict=True):
        families.setdefault(str(t["family"]), []).append(n)
    return {
        "trades": len(trades),
        "win_rate": sum(n > 0 for n in nets) / len(nets),
        "mean_net_bps": float(sum(nets) / len(nets)),
        "total_net_bps_additive": float(cumulative),
        "max_drawdown_bps_additive": float(max_drawdown),
        "uncertain_intrabar_stop_count": sum(
            t["exit_reason"] == "intrabar_stop_touch_uncertain" for t in trades
        ),
        "uncertain_exit_count": sum(t["intrabar_fill_uncertain"] for t in trades),
        "by_family": {
            name: {"trades": len(ns), "mean_net_bps": float(sum(ns) / len(ns)),
                   "win_rate": sum(n > 0 for n in ns) / len(ns)}
            for name, ns in sorted(families.items())
        },
    }


def replay_scalp_bars(
    bars: BrokerBars,
    *,
    exit_plan: ScalpExitPlan,
    assumptions: ReplayAssumptions | None = None,
    end_exclusive_time_msc: int | None = None,
    entry_mode: Literal["confirmed", "anticipatory"] = "confirmed",
) -> dict[str, Any]:
    """Backtest one position at a time, signal at close, enter at NEXT open.

    Defaults to discovery-only evaluation when passed an explicit cutoff.
    An uncut replay is still research, never promotion-grade validation.
    No same-bar signal/entry, future mid fills, gap interpolation or silent
    broker-fault repairs are permitted.
    """
    if entry_mode not in ("confirmed", "anticipatory"):
        raise ValueError("replay entry_mode must be confirmed or anticipatory")
    _validate_bars(bars)
    assumptions = ReplayAssumptions() if assumptions is None else assumptions
    proposer = propose_scalp_entry if entry_mode == "confirmed" else propose_anticipatory_entry
    allowed = len(bars.time_msc)
    if end_exclusive_time_msc is not None:
        allowed = int(np.searchsorted(bars.time_msc, end_exclusive_time_msc, side="left"))
    if allowed < 2:
        raise ValueError("replay window contains fewer than two complete broker bars")

    # These are the same fixed cost/feasibility fields as the unregistered
    # DEMO provider; never optimize them from the replay result.
    if (
        assumptions.max_entry_spread_bps != Decimal(str(DEFAULT_PARAMS["max_spread_bps"]))
        or assumptions.extra_cost_reserve_bps != Decimal(str(DEFAULT_PARAMS["extra_cost_reserve_bps"]))
        or assumptions.minimum_movement_margin_bps !=
        Decimal(str(DEFAULT_PARAMS["min_price_movement_after_cost_bps"]))
        or assumptions.stop_distance_price != Decimal(str(DEFAULT_PARAMS["stop_distance_price"]))
        or assumptions.max_hold_bars != int(DEFAULT_PARAMS["max_hold_seconds"] // 60)
    ):
        raise ValueError("replay strategy thresholds must match frozen DEMO provider parameters")

    closes: deque[Decimal] = deque(maxlen=34)
    pending: ScalpIdea | None = None
    position: dict[str, Any] | None = None
    trades: list[dict[str, Any]] = []
    gaps = 0
    entry_refusals = 0
    signals = 0
    exact_quote_extrema = bars.low_bid is not None and bars.high_ask is not None

    def finish(pos: dict[str, Any], index: int, *, price: Decimal, reason: str,
               uncertain: bool = False) -> None:
        entry = Decimal(pos["entry_price"])
        entry_index = int(pos["entry_index"])
        side = str(pos["side"])
        exit_slip = price * assumptions.exit_slippage_bps / BPS
        liquidation = price - exit_slip if side == "BUY" else price + exit_slip
        signed = liquidation - entry if side == "BUY" else entry - liquidation
        pnl_bps = signed * BPS / entry - assumptions.round_trip_commission_bps
        trades.append({
            "signal_time_msc": int(pos["signal_time_msc"]),
            "entry_time_msc": int(bars.time_msc[entry_index]),
            "exit_time_msc": int(bars.time_msc[index]),
            "side": side, "family": pos["family"], "regime": pos["regime"],
            "entry_price": str(entry), "exit_price_after_slippage": str(liquidation),
            "net_bps": str(pnl_bps), "exit_reason": reason,
            "hold_bars": index - entry_index + 1,
            "intrabar_fill_uncertain": uncertain,
        })

    for i in range(allowed):
        stamp = int(bars.time_msc[i])
        gap = i > 0 and stamp - int(bars.time_msc[i - 1]) != MINUTE_MS
        obid, oask, cbid, cask, high, low = (
            Decimal(str(float(getattr(bars, col)[i]))) for col in
            ("open_bid", "open_ask", "close_bid", "close_ask", "high_mid", "low_mid")
        )
        if gap:
            gaps += 1
            pending = None
            closes.clear()
            if position is not None:
                # Only the first price AFTER a gap is known. Never claim a
                # profitable gap fill or assume the stop was filled at its level.
                observed = obid if position["side"] == "BUY" else oask
                finish(position, i, price=observed, reason="gap_exit_at_first_quote",
                       uncertain=True)
                position = None

        # A completed-bar signal from minute i-1 may enter no earlier than
        # the first observed quote of minute i.
        if pending is not None and position is None and not gap:
            spread = _spread_bps(obid, oask)
            proxy = pending.movement_proxy_price * BPS / ((obid + oask) / 2)
            required = spread + assumptions.extra_cost_reserve_bps + assumptions.minimum_movement_margin_bps
            if spread <= assumptions.max_entry_spread_bps and proxy > required:
                side = pending.side
                market_entry = oask if side == "BUY" else obid
                entry_slip = market_entry * assumptions.entry_slippage_bps / BPS
                entry_price = market_entry + entry_slip if side == "BUY" else market_entry - entry_slip
                stop = (market_entry - assumptions.stop_distance_price if side == "BUY"
                        else market_entry + assumptions.stop_distance_price)
                position = {
                    "side": side, "family": pending.family, "regime": pending.regime,
                    "entry_price": str(entry_price), "stop": stop,
                    "entry_index": i, "signal_time_msc": int(bars.time_msc[i - 1]),
                }
            else:
                entry_refusals += 1
        pending = None

        if position is not None:
            side = str(position["side"])
            stop = Decimal(position["stop"])
            # Only mid high/low are available; the bid/ask at the exact
            # intrabar extreme and order of TP/SL touches are unknowable.
            # Treat a possible stop as a conservative, explicitly uncertain
            # close, never as a proven broker execution at the stop.
            biggest_spread = max(oask - obid, cask - cbid)
            if bars.low_bid is not None and bars.high_ask is not None:
                low_bid = Decimal(str(float(bars.low_bid[i])))
                high_ask = Decimal(str(float(bars.high_ask[i])))
                possible_stop = low_bid <= stop if side == "BUY" else high_ask >= stop
            else:
                # Legacy synthetic bars have no quote-side extrema. This is
                # only a proxy, not evidence of exact broker-side stop touches.
                low_bid = low - biggest_spread / 2
                high_ask = high + biggest_spread / 2
                possible_stop = low_bid <= stop if side == "BUY" else high_ask >= stop
            close_quote = cbid if side == "BUY" else cask
            if possible_stop:
                # Use the worst observed closing-side quote as a downside
                # stress bound. A real stop fill is NOT proven by this bound.
                conservative = min(close_quote, stop, low_bid) if side == "BUY" else max(
                    close_quote, stop, high_ask
                )
                finish(position, i, price=conservative, reason="intrabar_stop_touch_uncertain",
                       uncertain=True)
                position = None
            else:
                decision = decide_scalp_exit(
                    exit_plan, side=side, entry_price=position["entry_price"],
                    bid=cbid, ask=cask, tick_age_s=0,
                )
                held = i - int(position["entry_index"]) + 1
                reason = decision.reason if decision.close else (
                    "time_exit" if held >= assumptions.max_hold_bars else None
                )
                if reason:
                    finish(position, i, price=close_quote, reason=reason)
                    position = None

        # At bar close we know this bar, but NOT the next bar's opening quote.
        closes.append((cbid + cask) / 2)
        if position is None:
            pending = proposer(closes)
            if pending is not None:
                signals += 1

    # Do not infer a favorable exit after research data ends.
    if position is not None:
        end = allowed - 1
        quote = (Decimal(str(float(bars.close_bid[end]))) if position["side"] == "BUY"
                 else Decimal(str(float(bars.close_ask[end]))))
        finish(position, end, price=quote, reason="end_of_data_liquidation", uncertain=True)

    return {
        "schema": "qts.regime_scalp_causal_replay.v1",
        "status": "RESEARCH_ONLY_NOT_VALIDATED",
        "entry_mode": entry_mode,
        "dataset_bars": allowed, "signals": signals,
        "entry_refusals_cost_gate": entry_refusals, "observed_bar_gaps": gaps,
        "stop_detection_basis": "BROKER_BID_ASK_EXTREMA" if exact_quote_extrema else "MID_PRICE_PROXY",
        "cost_assumptions": {
            "entry_slippage_bps": str(assumptions.entry_slippage_bps),
            "exit_slippage_bps": str(assumptions.exit_slippage_bps),
            "round_trip_commission_bps": str(assumptions.round_trip_commission_bps),
            "extra_cost_reserve_bps": str(assumptions.extra_cost_reserve_bps),
        },
        "limitations": [
            "one-minute-bar approximation; unknown order of intrabar events",
            "bid/ask extrema detect possible broker-side stop touches when available; fill price and sequence remain uncertain",
            "no observed execution fills, latency, or true commission",
            "no independent unseen validation; never authorizes DEMO or LIVE",
            "basis-point trade sums are not compounded portfolio returns",
        ],
        "metrics": _summarize(trades),
        "trades": trades,
        "strategy_promoted": False,
        "orders_submitted": 0,
        "LIVE": "LOCKED",
    }
