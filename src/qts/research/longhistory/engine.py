"""Daily execution engine with explicit fills, stops and costs.

Event order within a bar ``i`` (all fills are conservative):

1. gap: an open position marks from the previous close to this open;
2. a decision taken at the close of bar ``i-1`` (a :class:`Plan` row) executes at
   the OPEN of bar ``i``: exit, entry, or rebalance, each paying the side cost;
3. the protective stop, if any, is checked against this bar's high/low. A stop
   fills at the stop price, or at the open when the open has already gapped
   through it (a stop is an order, not a guarantee). The engine then blocks
   re-entry in the same direction until the signal state changes;
4. an open position marks from the open to the close and pays time-prorated
   financing on the marked notional for the elapsed bar interval;
5. equity is recorded and the close-bar decision is stored for bar ``i+1``.

A fill converts the target fraction of equity to a signed number of XAU ounces.
That quantity stays fixed until a later entry, exit, stop, or explicit
``rebalance=True`` decision changes it. Mark-to-market never silently resizes a
position. Every quantity change is charged as a fill at the applicable cost
rate; only an explicit signal rebalance can resize a still-open position.

Costs are charged on notional traded at the fill price:

``side_rate = (spread/2 + slippage) + commission_per_lot / (100 * price)``

Financing is an explicitly simplified, symmetric bps-per-calendar-day charge,
prorated by elapsed timestamp duration. It is not a broker's directional swap
schedule or triple-rollover model. Every cost basis is recorded, and all frozen
research protocols still mark their zero financing as ASSUMED.

Accounting identity (tested for closed runs): when all positions are closed,
``final_equity - initial_equity`` equals the sum of trade-ledger ``net_usd``
values. Financing is booked into the trade it accrued on.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from qts.research.longhistory.signals import MAX_FRACTION, Plan

OUNCES_PER_LOT = 100.0
ACCOUNTING_MODEL_VERSION = "fixed_units.v2"
FINANCING_CONVENTION = "symmetric_time_prorated_bps_per_calendar_day"
SECONDS_PER_DAY = 86_400.0


@dataclass(frozen=True)
class CostModel:
    """Non-negative execution/carry costs; ``basis`` is recorded in every output.

    Financing is a simple symmetric, time-proportional bps-per-calendar-day
    charge. It is not a broker-specific swap schedule (which can be directional
    and apply a multi-day rollover on particular weekdays); such costs require
    measured per-side/per-night evidence in the claim-grade cost ledger.
    """

    spread_bps: float = 3.0
    slippage_bps: float = 1.0
    commission_usd_per_lot_side: float = 7.0
    financing_bps_per_day: float = 0.0
    multiplier: float = 1.0
    basis: str = "ASSUMED"
    spread_usd_per_oz: float = 0.0
    slippage_usd_per_oz_side: float = 0.0
    financing_long_bps_per_day: float | None = None
    financing_short_bps_per_day: float | None = None

    def __post_init__(self) -> None:
        components = {
            "spread_bps": self.spread_bps,
            "slippage_bps": self.slippage_bps,
            "commission_usd_per_lot_side": self.commission_usd_per_lot_side,
            "financing_bps_per_day": self.financing_bps_per_day,
            "multiplier": self.multiplier,
            "spread_usd_per_oz": self.spread_usd_per_oz,
            "slippage_usd_per_oz_side": self.slippage_usd_per_oz_side,
        }
        for name, value in components.items():
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be finite and non-negative")
        for dir_name, dir_val in (
            ("financing_long_bps_per_day", self.financing_long_bps_per_day),
            ("financing_short_bps_per_day", self.financing_short_bps_per_day),
        ):
            if dir_val is not None and not math.isfinite(dir_val):
                raise ValueError(f"{dir_name} must be finite when provided")
        if not isinstance(self.basis, str) or not self.basis.strip():
            raise ValueError("basis must be a non-empty string")

    def daily_financing_bps(self, direction: int) -> float:
        """Signed daily financing cost in bps of notional (+ = charge, - = credit)."""
        if direction > 0 and self.financing_long_bps_per_day is not None:
            return self.financing_long_bps_per_day
        if direction < 0 and self.financing_short_bps_per_day is not None:
            return self.financing_short_bps_per_day
        return self.financing_bps_per_day

    @classmethod
    def from_price_units(
        cls,
        *,
        spread_usd_per_oz: float,
        slippage_usd_per_oz_side: float,
        commission_usd_per_lot_side: float = 0.0,
        financing_bps_per_day: float = 0.0,
        multiplier: float = 1.0,
        basis: str = "ASSUMED",
    ) -> CostModel:
        """Construct a fixed-dollar ($/oz) cost model matching MT5 quote/deal units."""
        if spread_usd_per_oz < 0 or slippage_usd_per_oz_side < 0 or commission_usd_per_lot_side < 0:
            raise ValueError("Cost components must be non-negative")
        return cls(
            spread_bps=0.0,
            slippage_bps=0.0,
            commission_usd_per_lot_side=commission_usd_per_lot_side,
            financing_bps_per_day=financing_bps_per_day,
            multiplier=multiplier,
            basis=basis,
            spread_usd_per_oz=spread_usd_per_oz,
            slippage_usd_per_oz_side=slippage_usd_per_oz_side,
        )

    def side_rate(self, price: float) -> float:
        if not math.isfinite(price) or price <= 0.0:
            raise ValueError("fill price must be finite and positive")
        half_spread = (self.spread_bps / 2.0 / 1e4) + (self.spread_usd_per_oz / (2.0 * price))
        slip = (self.slippage_bps / 1e4) + (self.slippage_usd_per_oz_side / price)
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
            spread_usd_per_oz=self.spread_usd_per_oz,
            slippage_usd_per_oz_side=self.slippage_usd_per_oz_side,
            financing_long_bps_per_day=self.financing_long_bps_per_day,
            financing_short_bps_per_day=self.financing_short_bps_per_day,
        )

    def describe(self) -> dict[str, float | str]:
        directional = (
            self.financing_long_bps_per_day is not None
            or self.financing_short_bps_per_day is not None
        )
        out: dict[str, float | str] = {
            "basis": self.basis,
            "spread_bps_full": self.spread_bps,
            "slippage_bps_per_side": self.slippage_bps,
            "commission_usd_per_lot_side": self.commission_usd_per_lot_side,
            "financing_bps_per_day": self.financing_bps_per_day,
            "financing_convention": (
                "directional_time_prorated_bps_per_calendar_day"
                if directional
                else FINANCING_CONVENTION
            ),
            "cost_multiplier": self.multiplier,
            "round_turn_bps_at_1300": round(2 * self.side_rate(1300.0) * 1e4, 3),
        }
        if directional:
            out["financing_long_bps_per_day"] = (
                self.financing_long_bps_per_day
                if self.financing_long_bps_per_day is not None
                else self.financing_bps_per_day
            )
            out["financing_short_bps_per_day"] = (
                self.financing_short_bps_per_day
                if self.financing_short_bps_per_day is not None
                else self.financing_bps_per_day
            )
        if self.spread_usd_per_oz != 0.0 or self.slippage_usd_per_oz_side != 0.0:
            out["spread_usd_per_oz"] = self.spread_usd_per_oz
            out["slippage_usd_per_oz_side"] = self.slippage_usd_per_oz_side
            out["round_turn_bps_at_2000"] = round(2 * self.side_rate(2000.0) * 1e4, 3)
        return out


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
    turnover_fraction: float = 0.0  # fill notional divided by pre-fill equity, summed across sides
    financing_usd: float = 0.0
    cost_usd: float = 0.0  # all fill costs, excluding financing
    gross_usd: float = 0.0  # price P&L before costs and financing
    cost_basis: str = "ASSUMED"
    accounting_model_version: str = ACCOUNTING_MODEL_VERSION

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
    self-contained. Position quantities are fixed between fills. ``cap`` is a
    no-leverage ceiling on the target notional fraction, not an instruction to
    rebalance an open position on every bar.
    """
    n = len(bars)
    if not isinstance(start, (int, np.integer)) or not isinstance(end, (int, np.integer)):
        raise ValueError("window bounds must be integer bar positions")
    if not (0 <= start < end <= n):
        raise ValueError(f"invalid window [{start}, {end}) for {n} bars")
    if not math.isfinite(initial_equity) or initial_equity <= 0.0:
        raise ValueError("initial_equity must be finite and positive")
    if not math.isfinite(cap) or not 0.0 <= cap <= MAX_FRACTION:
        raise ValueError(f"cap must be finite and in [0, {MAX_FRACTION}] (no leverage)")
    if not isinstance(costs, CostModel):
        raise TypeError("costs must be a validated CostModel")
    if not isinstance(bars.index, pd.DatetimeIndex):
        raise ValueError("bars must use a DatetimeIndex")
    if bars.index.hasnans or bars.index.has_duplicates or not bars.index.is_monotonic_increasing:
        raise ValueError("bar timestamps must be valid, unique, and strictly increasing")
    required = ("open", "high", "low", "close")
    missing = [column for column in required if column not in bars.columns]
    if missing:
        raise ValueError(f"bars are missing required OHLC columns: {', '.join(missing)}")

    for name in ("target", "size", "stop_dist", "rebalance"):
        if len(getattr(plan, name)) != n:
            raise ValueError(f"plan field {name} length {len(getattr(plan, name))} != bar count {n}")
    opens = bars["open"].to_numpy(dtype=float)
    highs = bars["high"].to_numpy(dtype=float)
    lows = bars["low"].to_numpy(dtype=float)
    closes = bars["close"].to_numpy(dtype=float)
    window_prices = np.column_stack((opens[start:end], highs[start:end], lows[start:end], closes[start:end]))
    if not np.isfinite(window_prices).all() or (window_prices <= 0.0).any():
        raise ValueError("window OHLC prices must be finite and positive")
    bad_ohlc = (highs[start:end] < np.maximum(opens[start:end], closes[start:end])) | (
        lows[start:end] > np.minimum(opens[start:end], closes[start:end])
    ) | (highs[start:end] < lows[start:end])
    if bad_ohlc.any():
        raise ValueError("window OHLC ranges are inconsistent")

    target = np.asarray(plan.target, dtype=float)
    size = np.asarray(plan.size, dtype=float)
    stop_dist = np.asarray(plan.stop_dist, dtype=float)
    rebalance = np.asarray(plan.rebalance, dtype=bool)
    window_target = target[start:end]
    window_size = size[start:end]
    window_stop = stop_dist[start:end]
    if np.isinf(window_target).any() or not np.isin(window_target[np.isfinite(window_target)], (-1.0, 0.0, 1.0)).all():
        raise ValueError("finite plan targets must be -1, 0, or 1")
    if np.isinf(window_size).any() or (window_size[np.isfinite(window_size)] < 0.0).any():
        raise ValueError("finite plan sizes must be non-negative")
    if np.isinf(window_stop).any() or (window_stop[np.isfinite(window_stop)] <= 0.0).any():
        raise ValueError("finite stop distances must be positive")

    index = bars.index
    # Pandas 3 preserves lower-resolution datetime dtypes (for example us),
    # whereas the cost-rate conversion below is explicitly nanosecond-based.
    # Normalise first so elapsed time is independent of the input dtype's unit.
    timestamps_ns = index.as_unit("ns").astype("int64").to_numpy()
    durations_ns = np.diff(timestamps_ns)
    if (durations_ns <= 0).any():
        raise ValueError("bar timestamps must contain positive intervals")
    # A single-bar input has no inferable elapsed interval, so it accrues no
    # modelled carry rather than inventing a duration.
    # Estimate a terminal interval only from timestamps inside this run window;
    # later observations must not influence the final in-window carry charge.
    window_durations_ns = durations_ns[start : end - 1]
    typical_duration_days = (
        float(np.median(window_durations_ns)) / 1e9 / SECONDS_PER_DAY
        if window_durations_ns.size
        else 0.0
    )

    E = float(initial_equity)
    pos = 0
    units = 0.0  # signed ounces, fixed between fills
    stop_px = np.nan
    blocked = 0
    entry_idx = -1
    entry_px = np.nan
    entry_frac = 0.0
    tr_gross = 0.0
    tr_cost = 0.0
    trades: list[Trade] = []
    equity = np.empty(end - start)
    held = np.zeros(end - start, dtype=bool)
    turnover = 0.0
    financing = 0.0
    cost_total = 0.0
    gross_total = 0.0
    pending: tuple[float, float, float, bool] | None = None
    prev_close = np.nan

    def fill_cost(notional_usd: float, price: float) -> float:
        return abs(notional_usd) * costs.side_rate(price)

    def record_turnover(notional_usd: float, equity_before_fill: float) -> float:
        return abs(notional_usd) / equity_before_fill if equity_before_fill > 0.0 else 0.0

    def close_trade(idx: int, exit_px: float, forced: bool, stopped: bool) -> None:
        nonlocal tr_gross, tr_cost, pos, units, stop_px, entry_idx
        trades.append(
            Trade(
                direction=pos,
                entry_day=pd.Timestamp(index[entry_idx]),
                exit_day=pd.Timestamp(index[idx]),
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
        units = 0.0
        stop_px = np.nan
        entry_idx = -1

    for i in range(start, end):
        k = i - start
        o, h, lo, c = opens[i], highs[i], lows[i], closes[i]
        # 1. Mark the fixed signed quantity across the gap to this bar's open.
        if pos != 0 and i > start:
            pnl = units * (o - prev_close)
            E += pnl
            tr_gross += pnl
            gross_total += pnl
        # 2. Execute the decision taken at the previous close, at this open.
        if pending is not None:
            tgt, sz, sd, reb = pending
            if np.isfinite(tgt):
                if tgt != blocked:
                    blocked = 0
                if tgt != pos:
                    if pos != 0:
                        notional = abs(units * o)
                        equity_before_fill = E
                        cost = fill_cost(notional, o)
                        E -= cost
                        tr_cost += cost
                        cost_total += cost
                        turnover += record_turnover(notional, equity_before_fill)
                        close_trade(i, o, forced=False, stopped=False)
                    if tgt != 0 and tgt != blocked and np.isfinite(sz) and sz > 0.0 and cap > 0.0 and E > 0.0:
                        f = min(float(sz), cap)
                        notional = f * E
                        cost = fill_cost(notional, o)
                        equity_before_fill = E
                        E -= cost
                        pos = int(tgt)
                        units = pos * notional / o
                        entry_frac = f
                        entry_px = o
                        entry_idx = i
                        stop_px = o - pos * sd if np.isfinite(sd) else np.nan
                        tr_gross = 0.0
                        tr_cost = cost
                        cost_total += cost
                        turnover += record_turnover(notional, equity_before_fill)
                        blocked = 0
                elif reb and pos != 0 and np.isfinite(sz) and E > 0.0:
                    new_f = min(float(sz), cap)
                    target_notional = new_f * E
                    target_units = pos * target_notional / o
                    delta_units = target_units - units
                    delta_notional = abs(delta_units * o)
                    if abs(delta_units) > 1e-12:
                        equity_before_fill = E
                        cost = fill_cost(delta_notional, o)
                        E -= cost
                        tr_cost += cost
                        cost_total += cost
                        turnover += record_turnover(delta_notional, equity_before_fill)
                        units = target_units
                        if new_f == 0.0:
                            blocked = pos
                            close_trade(i, o, forced=False, stopped=False)
        # 3. Protective stop against this bar's range.
        if pos != 0 and units != 0.0 and np.isfinite(stop_px):
            hit = (pos > 0 and lo <= stop_px) or (pos < 0 and h >= stop_px)
            if hit:
                x = min(o, stop_px) if pos > 0 else max(o, stop_px)
                pnl = units * (x - o)
                E += pnl
                tr_gross += pnl
                gross_total += pnl
                notional = abs(units * x)
                equity_before_fill = E
                cost = fill_cost(notional, x)
                E -= cost
                tr_cost += cost
                cost_total += cost
                turnover += record_turnover(notional, equity_before_fill)
                blocked = pos
                close_trade(i, x, forced=False, stopped=True)
        # 4. Mark open exposure to the close; carry is prorated by elapsed time.
        if pos != 0 and units != 0.0:
            pnl = units * (c - o)
            E += pnl
            tr_gross += pnl
            gross_total += pnl
            if i + 1 < end:
                interval_days = float(durations_ns[i]) / 1e9 / SECONDS_PER_DAY
            else:
                # The position is closed at this bar's close (or the run stops
                # here). Do not charge a later weekend/data gap outside the run.
                interval_days = typical_duration_days
            notional = abs(units * c)
            fin_bps = costs.daily_financing_bps(pos)
            fin = notional * fin_bps * costs.multiplier * interval_days / 1e4
            E -= fin
            tr_cost += fin
            financing += fin
            held[k] = True
        # 5. A forced close is priced at the final close, with a normal side cost.
        if i == end - 1 and force_close_end and pos != 0:
            notional = abs(units * c)
            equity_before_fill = E
            cost = fill_cost(notional, c)
            E -= cost
            tr_cost += cost
            cost_total += cost
            turnover += record_turnover(notional, equity_before_fill)
            close_trade(i, c, forced=True, stopped=False)
            held[k] = False
        equity[k] = E
        prev_close = c
        # 6. Store the close-time decision for execution at the next open.
        pending = (
            (
                float(target[i]),
                float(size[i]),
                float(stop_dist[i]),
                bool(rebalance[i]),
            )
            if i + 1 < end
            else None
        )

    prev = np.concatenate([[initial_equity], equity[:-1]])
    returns = equity / prev - 1.0
    return RunResult(
        days=pd.DatetimeIndex(index[start:end]),
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
        accounting_model_version=ACCOUNTING_MODEL_VERSION,
    )
