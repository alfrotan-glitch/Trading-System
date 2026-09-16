"""Deterministic backtest engine — event-driven, sorted by time."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

import numpy as np

from qts.data.store import SqliteParquetDataStore
from qts.domain.value_objects import Instrument
from qts.execution.engine import ExecutionEngine, OrderManager, PaperBrokerAdapter
from qts.execution.matching import MatchingConfig, MatchingEngine
from qts.observability.audit import AuditLog, InMemoryAuditLog
from qts.research.strategy import SmaBreakoutStrategy, signal_to_intent
from qts.risk.engine import RiskEngine, RiskLimits


@dataclass
class BacktestResult:
    strategy_id: str
    data_version: str
    seed: int
    bars: int
    trades: int
    equity_curve: list[float] = field(default_factory=list)
    returns: list[float] = field(default_factory=list)
    fills: list[dict[str, Any]] = field(default_factory=list)
    manifest_hash: str = ""
    final_equity: float = 10000.0
    sharpe: float = 0.0
    max_dd: float = 0.0
    profit_factor: float = 0.0

    def hash(self) -> str:
        payload = json.dumps({"equity": self.equity_curve, "fills": self.fills}, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:12]


class BacktestEngine:
    def __init__(
        self,
        data_store: SqliteParquetDataStore,
        risk_limits: RiskLimits | None = None,
        matching_config: MatchingConfig | None = None,
        audit: AuditLog | None = None,
        initial_balance: float = 10000.0,
    ):
        self.data_store = data_store
        self.risk_limits = risk_limits or RiskLimits()
        self.matching_config = matching_config or MatchingConfig()
        self.audit = audit or InMemoryAuditLog()
        self.initial_balance = initial_balance

    def run(
        self,
        instrument: Instrument,
        timeframe: str,
        data_version: str,
        strategy_id: str = "sma_breakout",
        strategy_params: dict[str, Any] | None = None,
        seed: int = 42,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> BacktestResult:
        strategy_params = strategy_params or {}
        bars = self.data_store.read_bars(instrument, timeframe, start, end, version=data_version)
        if not bars:
            raise ValueError(f"no bars for {instrument.symbol} {timeframe} version {data_version}")
        # deterministic: sort by open_time
        bars = sorted(bars, key=lambda b: b.open_time)
        # strategy
        if strategy_id == "sma_breakout":
            strat = SmaBreakoutStrategy(
                instrument,
                fast=strategy_params.get("fast", 10),
                slow=strategy_params.get("slow", 20),
                strategy_id=strategy_id,
            )
        else:
            raise ValueError(f"unknown strategy {strategy_id}")
        # engines
        matching = MatchingEngine(self.matching_config)
        risk = RiskEngine(self.risk_limits, db_path=self.data_store.db_path)
        # ensure kill not persisted across backtests
        risk.reset_kill()
        om = OrderManager(audit=self.audit)
        broker = PaperBrokerAdapter(matching=matching)
        from qts.domain.value_objects import Account

        account = Account(
            balance=Decimal(str(self.initial_balance)),
            equity=Decimal(str(self.initial_balance)),
            currency="USD",
        )
        exec_engine = ExecutionEngine(om, risk, broker, matching, audit=self.audit, account=account)
        # run
        equity = [float(self.initial_balance)]
        fills_out: list[dict[str, Any]] = []
        # position tracking for PnL
        # For backtest PnL, simulate mark-to-market on close
        # Simplify: equity changes only on fill realized? Use trade PnL approximation:
        # We'll compute equity as initial + cumulative trade PnL (long/short closed on opposite signal)
        # For determinism and simplicity, compute returns from equity curve as 0 for now and update equity via fill PnL
        # Better: track position and close on opposite signal
        # We'll implement simple long/short flat logic: each signal closes opposite and opens new
        # For metrics, we need equity curve — hack: treat each bar's return as 0 then jumps on fills
        # Instead compute equity curve as step function: equity stays flat exceptfills add fee
        # To get meaningful Sharpe, we generate synthetic returns from fills
        # For proper backtest, we should compute PnL from price moves while holding
        # Let's do FIFO: hold position, equity = initial + unrealized + realized
        position_qty = Decimal("0")
        avg_price = Decimal("0")
        realized = Decimal("0")
        for bar in bars:
            signals = strat.on_bar(bar)
            for sig in signals:
                intent = signal_to_intent(sig, quantity=Decimal(str(strategy_params.get("quantity", "0.1"))))
                # ensure deterministic client_order_id includes bar time
                intent = intent.model_copy(
                    update={"client_order_id": f"{strategy_id}:{bar.open_time.isoformat()}:{len(fills_out)}"}
                )
                order, fills = exec_engine.submit_intent(intent, bar=bar)
                for fill in fills:
                    # update position and realized
                    qty_delta = fill.quantity if fill.side.value == "BUY" else -fill.quantity
                    # if flipping, realize
                    if position_qty != 0 and (position_qty > 0) != (qty_delta > 0):
                        # closing portion
                        close_qty = min(abs(position_qty), abs(qty_delta))
                        # PnL = (fill_price - avg_price) * close_qty * direction
                        # long: sell higher -> profit
                        if position_qty > 0:
                            pnl = (fill.price - avg_price) * close_qty
                        else:
                            pnl = (avg_price - fill.price) * close_qty
                        realized += pnl - fill.fee
                        # remaining
                        remaining_qty = position_qty + qty_delta
                        if remaining_qty == 0:
                            avg_price = Decimal("0")
                        elif (remaining_qty > 0) == (position_qty > 0):
                            # partial close
                            pass
                        else:
                            # flip
                            avg_price = fill.price
                        position_qty = remaining_qty
                    else:
                        # adding
                        total_cost = avg_price * abs(position_qty) + fill.price * abs(qty_delta)
                        total_qty = abs(position_qty) + abs(qty_delta)
                        avg_price = total_cost / total_qty if total_qty != 0 else Decimal("0")
                        position_qty = position_qty + qty_delta
                        realized -= fill.fee
                    fills_out.append(
                        {
                            "price": str(fill.price),
                            "qty": str(fill.quantity),
                            "side": fill.side.value,
                            "time": fill.event_time.isoformat(),
                        }
                    )
            # mark-to-market equity at bar close
            if position_qty != 0:
                unrealized = (
                    (bar.close - avg_price) * position_qty
                    if position_qty > 0
                    else (avg_price - bar.close) * abs(position_qty)
                )
            else:
                unrealized = Decimal("0")
            eq = float(Decimal(str(self.initial_balance)) + realized + unrealized)
            equity.append(eq)
        # metrics
        eq_arr = np.array(equity, dtype=float)
        rets = np.diff(eq_arr) / np.where(eq_arr[:-1] == 0, 1, eq_arr[:-1])
        # remove nan
        rets = rets[np.isfinite(rets)]
        from qts.validation.metrics import max_drawdown, profit_factor, sharpe_ratio

        sharpe = sharpe_ratio(rets) if len(rets) else 0.0
        dd = max_drawdown(eq_arr)
        pf = profit_factor(rets) if len(rets) else 0.0
        # manifest hash
        payload = json.dumps(
            {
                "strategy_id": strategy_id,
                "params": strategy_params,
                "data_version": data_version,
                "seed": seed,
                "bars": len(bars),
            },
            sort_keys=True,
        )
        manifest_hash = hashlib.sha256(payload.encode()).hexdigest()[:12]
        return BacktestResult(
            strategy_id=strategy_id,
            data_version=data_version,
            seed=seed,
            bars=len(bars),
            trades=len(fills_out),
            equity_curve=equity,
            returns=rets.tolist(),
            fills=fills_out,
            manifest_hash=manifest_hash,
            final_equity=float(equity[-1]) if equity else self.initial_balance,
            sharpe=float(sharpe),
            max_dd=float(dd),
            profit_factor=float(pf),
        )
