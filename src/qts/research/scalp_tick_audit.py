"""Audit first observable MT5 quote crossing an existing simulated stop.

Diagnostic only: unchanged bar-replay trade sequence, no proven broker fill.
This is NOT a full tick strategy backtest or permission to submit orders.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import numpy as np

MINUTE_MS = 60_000
BPS = Decimal("10000")


@dataclass(frozen=True)
class _StopWindow:
    start: int
    end: int
    side: str
    stop: Decimal
    entry: Decimal
    stress_bps: Decimal
    trigger_bps: Decimal


def _stop_windows(trades: list[dict[str, Any]]) -> list[_StopWindow]:
    windows: list[_StopWindow] = []
    for trade in trades:
        if trade.get("exit_reason") != "intrabar_stop_touch_uncertain":
            continue
        try:
            start = int(trade["entry_time_msc"])
            end = int(trade["exit_time_msc"]) + MINUTE_MS
            side = str(trade["side"])
            stop = Decimal(str(trade["stop_price"]))
            entry = Decimal(str(trade["entry_price"]))
            stress = Decimal(str(trade["net_bps"]))
            trigger = Decimal(str(trade["net_bps_if_stop_at_trigger"]))
        except (KeyError, ValueError, TypeError, InvalidOperation) as exc:
            raise ValueError("incomplete scalp stop-trade record") from exc
        if (
            start < 0 or end <= start or start % MINUTE_MS or end % MINUTE_MS
            or side not in ("BUY", "SELL")
            or not all(v.is_finite() for v in (stop, entry, stress, trigger))
            or min(stop, entry) <= 0
        ):
            raise ValueError("invalid simulated stop-trade timestamps or prices")
        windows.append(_StopWindow(start, end, side, stop, entry, stress, trigger))
    windows.sort(key=lambda w: w.start)
    for first, second in zip(windows, windows[1:], strict=False):
        if first.end > second.start:
            raise ValueError("overlapping stop-trade intervals cannot be audited independently")
    return windows


class TickStopAuditor:
    """One-pass bounded-memory first-stop-touch quotation auditor."""

    def __init__(
        self,
        trades: list[dict[str, Any]],
        *,
        exit_slippage_bps: Decimal,
        round_trip_commission_bps: Decimal,
    ) -> None:
        self.windows = _stop_windows(trades)
        for name, value in (
            ("exit_slippage_bps", exit_slippage_bps),
            ("round_trip_commission_bps", round_trip_commission_bps),
        ):
            if not value.is_finite() or value < 0:
                raise ValueError(f"invalid {name} for tick audit")
        self.slippage = exit_slippage_bps
        self.commission = round_trip_commission_bps
        self.position = 0
        self.last_stamp: int | None = None
        self.rows = 0
        self.matches: list[tuple[Decimal, Decimal, Decimal]] = []

    def consume(self, time_msc: np.ndarray, bid: np.ndarray, ask: np.ndarray) -> None:
        """Preserve raw chronology and observe BID for BUY / ASK for SELL."""
        stamps = np.asarray(time_msc, dtype=np.int64)
        bids = np.asarray(bid, dtype=np.float64)
        asks = np.asarray(ask, dtype=np.float64)
        if stamps.ndim != 1 or bids.shape != stamps.shape or asks.shape != stamps.shape:
            raise ValueError("invalid raw MT5 tick array shapes")
        if not len(stamps):
            return
        if (
            np.any(stamps < 0) or np.any(np.diff(stamps) < 0)
            or (self.last_stamp is not None and int(stamps[0]) < self.last_stamp)
        ):
            raise ValueError("raw MT5 tick order changed; audit refused")
        if (
            not np.isfinite(bids).all() or not np.isfinite(asks).all()
            or np.any(bids <= 0) or np.any(asks < bids)
        ):
            raise ValueError("invalid raw MT5 bid/ask quote; audit refused")
        self.last_stamp = int(stamps[-1])
        self.rows += len(stamps)
        while self.position < len(self.windows):
            stop = self.windows[self.position]
            if stop.start > int(stamps[-1]):
                break
            if stop.end <= int(stamps[0]):
                self.position += 1
                continue
            lo = int(np.searchsorted(stamps, stop.start, side="left"))
            hi = int(np.searchsorted(stamps, stop.end, side="left"))
            if lo < hi:
                liquidations = bids[lo:hi] if stop.side == "BUY" else asks[lo:hi]
                meets = (
                    liquidations <= float(stop.stop) if stop.side == "BUY"
                    else liquidations >= float(stop.stop)
                )
                hits = np.flatnonzero(meets)
                if hits.size:
                    quote = Decimal(str(float(liquidations[int(hits[0])])))
                    extra = quote * self.slippage / BPS
                    fill = quote - extra if stop.side == "BUY" else quote + extra
                    move = fill - stop.entry if stop.side == "BUY" else stop.entry - fill
                    estimate = move * BPS / stop.entry - self.commission
                    self.matches.append((stop.stress_bps, stop.trigger_bps, estimate))
                    self.position += 1
                    continue
            if stop.end <= int(stamps[-1]):
                self.position += 1
                continue
            break

    def report(self) -> dict[str, Any]:
        def mean(idx: int) -> float | None:
            return float(sum(row[idx] for row in self.matches) / len(self.matches)) if self.matches else None

        return {
            "schema": "qts.scalp_first_stop_touch_tick_audit.v1",
            "status": "DIAGNOSTIC_ONLY_NOT_STRATEGY_PNL",
            "stop_trades_in_bar_replay": len(self.windows),
            "stops_with_observed_first_touch": len(self.matches),
            "missing_stop_touches": len(self.windows) - len(self.matches),
            "quote_rows_checked": self.rows,
            "mean_bar_worst_net_bps_on_matched_stops": mean(0),
            "mean_hypothetical_trigger_net_bps_on_matched_stops": mean(1),
            "mean_first_touch_quote_net_bps_on_matched_stops": mean(2),
            "note": (
                "First raw quote crossing stop is not an actual broker fill; "
                "strategy entries/exits stay unchanged, therefore not strategy PnL. "
                "Commission and slippage remain assumed."
            ),
            "orders_submitted": 0,
            "strategy_promoted": False,
            "LIVE": "LOCKED",
        }
