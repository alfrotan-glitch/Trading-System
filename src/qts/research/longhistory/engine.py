"""Daily execution engine with explicit fills, stops and costs.

Event order within a bar ``i`` (all fills are conservative):

1. gap: an open position marks from the previous close to this open;
2. a decision taken at the close of bar ``i-1`` (a :class:`Plan` row) executes at
   the OPEN of bar ``i``: exit, entry, or rebalance, each paying the side cost;
3. the protective stop, if any, is checked against this bar's high/low. A stop
   fills at the stop price, or at the open when the open has already gapped
   through it (a stop is an order, not a guarantee). The engine then blocks
   re-entry in the same direction until the signal state changes;
4. an open position marks from the open to the close and pays financing;
5. equity is recorded; the close-bar decision is stored for bar ``i+1``.

Costs are charged on notional traded at the fill price:

``side_rate = (spread/2 + slippage) + commission_per_lot / (100 * price)``

Every cost is ASSUMED unless a caller supplies a measured basis. The engine
never estimates a cost from the price path.

Accounting identity (tested): ``final_equity - initial_equity`` equals the sum
of the trade ledger ``net_usd`` values plus any financing not attributed to a
trade. Financing is booked into the trade it accrued on.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from qts.research.longhistory.signals import MAX_FRACTION, Plan

OUNCES_PER_LOT = 100.0


@dataclass(frozen=True)
class CostModel:
    """Round-trip cost assumptions. ``basis`` is recorded in every output."""

    spread_bps: float = 3.0
    slippage_bps: float = 1.0
    commission_usd_per_lot_side: float = 7.0
    financing_bps_per_day: float = 0.0
    multiplier: float = 1.0
    basis: str = "ASSUMED"

    def side_rate(self, price: float) -> float:
        half_spread = self.spread_bps / 2.0 / 1e4
        slip = self.slippage_bps / 1e4
        commission = self.commission_usd_per_lot_side / (OUNCES_PER_LOT * price)
        return self.multiplier * (half_spread + slip + commission)

    def scaled(self, multiplier: float) -> CostModel:
        return CostModel(
            spread_bps=self.spread_bps,
            slippage_bps=self.slippage_bps,
            commission_usd_per_lot_side=self.commission_usd_per_lot_side,
            financing_bps_per_day=self.financing_bps_per_day,
            multiplier=self.multiplier * multiplier,
            basis=self.basis,
        )

    def describe(self) -> dict[str, float | str]:
        return {
            "basis": self.basis,
            "spread_bps_full": self.spread_bps,
            "slippage_bps_per_side": self.slippage_bps,
            "commission_usd_per_lot_side": self.commission_usd_per_lot_side,
            "financing_bps_per_day": self.financing_bps_per_day,
            "cost_multiplier": self.multiplier,
            "round_turn_bps_at_1300": round(2 * self.side_rate(1300.0) * 1e4, 3),
        }


@dataclass
class Trade:
    direction: int
    entry_day: pd.Timestamp
    exit_day: pd.Timestamp
    entry_price: float
    exit_price: float
    gross_usd: float
    cost_usd: float
    bars_held: int
    stopped: bool
    forced_exit: bool
    entry_frac: float

    @property
    def net_usd(self) -> float:
        return self.gross_usd - self.cost_usd


@dataclass
class RunResult:
    days: pd.DatetimeIndex
    equity: np.ndarray
    returns: np.ndarray
    held: np.ndarray
    trades: list[Trade] = field(default_factory=list)
    initial_equity: float = 10_000.0
    turnover_fraction: float = 0.0  # sum of |change in position fraction| over the run
    financing_usd: float = 0.0
    cost_usd: float = 0.0  # all fill costs, excluding financing
    gross_usd: float = 0.0  # price P&L before costs and financing
    cost_basis: str = "ASSUMED"

    @property
    def final_equity(self) -> float:
        return float(self.equity[-1]) if len(self.equity) else self.initial_equity

    @property
    def net_usd(self) -> float:
        return self.final_equity - self.initial_equity

    @property
    def exposure(self) -> float:
        return float(np.mean(self.held)) if len(self.held) else 0.0


def run_plan(
    bars: pd.DataFrame,
    plan: Plan,
    start: int,
    end: int,
    costs: CostModel,
    initial_equity: float = 10_000.0,
    force_close_end: bool = True,
    cap: float = MAX_FRACTION,
) -> RunResult:
    """Execute ``plan`` over bar positions ``[start, end)`` of ``bars``.

    The run starts flat. A decision at bar ``end-1`` cannot execute inside the
    window; when ``force_close_end`` is set, an open position is closed at the
    final close and the trade is marked ``forced_exit`` so window results are
    self-contained.
    """
    n = len(bars)
    if not (0 <= start < end <= n):
        raise ValueError(f"invalid window [{start}, {end}) for {n} bars")
    opens = bars["open"].to_numpy(dtype=float)
    highs = bars["high"].to_numpy(dtype=float)
    lows = bars["low"].to_numpy(dtype=float)
    closes = bars["close"].to_numpy(dtype=float)
    days = pd.DatetimeIndex(bars.index[start:end])
    m = end - start

    E = float(initial_equity)
    pos = 0
    frac = 0.0
    stop_px = np.nan
    blocked = 0
    entry_idx = -1
    entry_px = np.nan
    entry_frac = 0.0
    tr_gross = 0.0
    tr_cost = 0.0
    trades: list[Trade] = []
    equity = np.empty(m)
    held = np.zeros(m, dtype=bool)
    turnover = 0.0
    financing = 0.0
    cost_total = 0.0
    gross_total = 0.0
    pending: tuple[float, float, float, bool] | None = None
    prev_close = np.nan

    def close_trade(idx: int, exit_px: float, forced: bool, stopped: bool) -> None:
        nonlocal tr_gross, tr_cost, pos, frac, stop_px, entry_idx
        trades.append(
            Trade(
                direction=pos,
                entry_day=pd.Timestamp(bars.index[entry_idx]),
                exit_day=pd.Timestamp(bars.index[idx]),
                entry_price=entry_px,
                exit_price=exit_px,
                gross_usd=tr_gross,
                cost_usd=tr_cost,
                bars_held=idx - entry_idx,
                stopped=stopped,
                forced_exit=forced,
                entry_frac=entry_frac,
            )
        )
        tr_gross = 0.0
        tr_cost = 0.0
        pos = 0
        frac = 0.0
        stop_px = np.nan
        entry_idx = -1

    for i in range(start, end):
        k = i - start
        o, h, lo, c = opens[i], highs[i], lows[i], closes[i]
        # 1. gap from previous close to this open
        if pos != 0 and i > start:
            pnl = pos * frac * E * (o / prev_close - 1.0)
            E += pnl
            tr_gross += pnl
            gross_total += pnl
        # 2. execute the decision taken at the previous close, at this open
        if pending is not None:
            tgt, sz, sd, reb = pending
            if np.isfinite(tgt):
                if tgt != blocked:
                    blocked = 0
                if tgt != pos:
                    if pos != 0:
                        cost = frac * E * costs.side_rate(o)
                        E -= cost
                        tr_cost += cost
                        cost_total += cost
                        turnover += frac
                        close_trade(i, o, forced=False, stopped=False)
                    if tgt != 0 and tgt != blocked and np.isfinite(sz) and sz > 0:
                        f = min(float(sz), cap)
                        cost = f * E * costs.side_rate(o)
                        E -= cost
                        pos = int(tgt)
                        frac = f
                        entry_frac = f
                        entry_px = o
                        entry_idx = i
                        stop_px = o - pos * sd if np.isfinite(sd) else np.nan
                        tr_gross = 0.0
                        tr_cost = cost
                        cost_total += cost
                        turnover += f
                        blocked = 0
                elif reb and pos != 0 and np.isfinite(sz):
                    new_f = min(float(sz), cap)
                    delta = new_f - frac
                    if abs(delta) > 1e-12:
                        cost = abs(delta) * E * costs.side_rate(o)
                        E -= cost
                        tr_cost += cost
                        cost_total += cost
                        turnover += abs(delta)
                        frac = new_f
        # 3. protective stop against this bar's range
        if pos != 0 and np.isfinite(stop_px):
            hit = (pos > 0 and lo <= stop_px) or (pos < 0 and h >= stop_px)
            if hit:
                x = min(o, stop_px) if pos > 0 else max(o, stop_px)
                pnl = pos * frac * E * (x / o - 1.0)
                E += pnl
                tr_gross += pnl
                gross_total += pnl
                cost = frac * E * costs.side_rate(x)
                E -= cost
                tr_cost += cost
                cost_total += cost
                turnover += frac
                blocked = pos
                close_trade(i, x, forced=False, stopped=True)
        # 4. mark an open position from open to close, then financing
        if pos != 0:
            pnl = pos * frac * E * (c / o - 1.0)
            E += pnl
            tr_gross += pnl
            gross_total += pnl
            fin = frac * E * costs.financing_bps_per_day * costs.multiplier / 1e4
            E -= fin
            tr_cost += fin
            financing += fin
            held[k] = True
        # 5. forced exit at the end of the window
        if i == end - 1 and force_close_end and pos != 0:
            cost = frac * E * costs.side_rate(c)
            E -= cost
            tr_cost += cost
            cost_total += cost
            turnover += frac
            close_trade(i, c, forced=True, stopped=False)
            held[k] = False
        equity[k] = E
        prev_close = c
        # 6. decision for the next bar, from information available at this close
        if i + 1 < end:
            pending = (
                float(plan.target[i]),
                float(plan.size[i]),
                float(plan.stop_dist[i]),
                bool(plan.rebalance[i]),
            )
        else:
            pending = None

    prev = np.concatenate([[initial_equity], equity[:-1]])
    returns = equity / prev - 1.0
    return RunResult(
        days=days,
        equity=equity,
        returns=returns,
        held=held,
        trades=trades,
        initial_equity=float(initial_equity),
        turnover_fraction=float(turnover),
        financing_usd=float(financing),
        cost_usd=float(cost_total),
        gross_usd=float(gross_total),
        cost_basis=costs.basis,
    )
