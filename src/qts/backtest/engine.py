"""Deterministic backtest engine — event-driven, sorted by time.

Execution convention (explicit, documented):
  Signal generated on bar N's close (event_time = close_time) uses ONLY information
  available at N's close. Order is created at close_time of N. Fill is at
  bar N+1's open (or with delay), using N+1's market data (open + spread/slippage).
  This eliminates look-ahead: same-bar close cannot be used to fill at same close.

  For tick-based replay, ticks are replayed in time order and fill uses tick at fill_time.

Tick replay not yet; bar-based only. For stress tests, matching engine is swapped
with different spread/slippage configs and strategy re-run (not PF multiplied).

Portfolio is single source of truth for PnL (lots canonical, contract_size, fees).
"""

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
from qts.execution.idempotency import IdempotencyStore
from qts.execution.matching import MatchingConfig, MatchingEngine
from qts.observability.audit import AuditLog, InMemoryAuditLog
from qts.portfolio.portfolio import Portfolio
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
    config_hash: str = ""

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
        bars = sorted(bars, key=lambda b: b.open_time)

        # strategy factory
        if strategy_id == "sma_breakout":
            strat = SmaBreakoutStrategy(
                instrument,
                fast=strategy_params.get("fast", 10),
                slow=strategy_params.get("slow", 20),
                strategy_id=strategy_id,
            )
        elif strategy_id == "hold_long":
            # simple hold for testing P&L
            from qts.research.strategy import Signal as Sig
            from qts.domain.value_objects import Side

            class HoldLong:
                strategy_id = "hold_long"

                def on_bar(self, bar):
                    if len(getattr(self, "_seen", [])) == 0:
                        self._seen = [1]
                        return [
                            Sig(
                                instrument=bar.instrument,
                                side=Side.BUY,
                                strength=1.0,
                                event_time=bar.close_time,
                                hypothesis_id="H-HOLD",
                                strategy_id="hold_long",
                            )
                        ]
                    return []

            strat = HoldLong()  # type: ignore
        else:
            raise ValueError(f"unknown strategy {strategy_id}")

        matching = MatchingEngine(self.matching_config)
        # use temp db for idempotency to keep backtests isolated but persistent check works
        # use same db_path but with unique prefix via temp? For determinism use same path but clear
        risk = RiskEngine(self.risk_limits, db_path=self.data_store.db_path)
        risk.reset_kill()
        # idempotency store per backtest run (cleared)
        idemp = IdempotencyStore(db_path=self.data_store.db_path)
        # clear previous idempotency for deterministic replay? We want each backtest to be independent,
        # so clear before run
        idemp.clear()
        om = OrderManager(audit=self.audit, idempotency=idemp)
        broker = PaperBrokerAdapter(matching=matching)
        portfolio = Portfolio(initial_balance=Decimal(str(self.initial_balance)), currency="USD")
        exec_engine = ExecutionEngine(om, risk, broker, matching, portfolio, audit=self.audit)

        equity: list[float] = []
        fills_out: list[dict[str, Any]] = []

        # Execution convention: next-bar open
        # We maintain pending intents to be executed on next bar
        pending_intents: list[Any] = []  # OrderIntent list

        for idx, bar in enumerate(bars):
            # 1) execute pending intents from previous bar at this bar's open
            if pending_intents:
                # For each pending intent, create a synthetic execution bar at this bar's open
                # Use current bar's open as execution price basis (open ± spread)
                # For more realism we could use open, but we use bar's open as price for matching
                # MatchingEngine.price_for uses bar.close; for execution at open we need to treat
                # bar.open as the price. So we create a execution_bar with open=close=open
                from qts.domain.value_objects import Bar as BarVO
                from datetime import timedelta

                exec_bar = BarVO(
                    instrument=bar.instrument,
                    open=bar.open,
                    high=bar.open,
                    low=bar.open,
                    close=bar.open,
                    volume=bar.volume,
                    open_time=bar.open_time,
                    close_time=bar.open_time + timedelta(milliseconds=1),
                    data_version=bar.data_version,
                    source="execution_open",
                )
                for intent in pending_intents:
                    # idempotency already handled via OrderManager
                    order, fills = exec_engine.submit_intent(intent, bar=exec_bar)
                    for fill in fills:
                        fills_out.append(
                            {
                                "price": str(fill.price),
                                "qty": str(fill.quantity),
                                "side": fill.side.value,
                                "time": fill.event_time.isoformat(),
                                "bar_open": str(bar.open),
                                "bar_idx": idx,
                            }
                        )
                pending_intents = []

            # 2) mark to market at bar close before signal? Position unrealized at close
            # But signal is generated after close, so mark at close first
            exec_engine.mark_price(bar.instrument.symbol, bar.close)
            eq = float(portfolio.equity())
            equity.append(eq)

            # 3) strategy sees bar (with only information up to this close)
            # Ensure strategy never sees future bars — it only receives current bar
            signals = strat.on_bar(bar)
            for sig in signals:
                intent = signal_to_intent(sig, quantity=Decimal(str(strategy_params.get("quantity", "0.1"))))
                # deterministic id: strategy:bar_time:seq
                intent = intent.model_copy(
                    update={"client_order_id": f"{strategy_id}:{bar.close_time.isoformat()}:{len(fills_out) + len(pending_intents)}"}
                )
                # queue for next bar execution
                pending_intents.append(intent)

            # if this is last bar, pending intents would not be executed (no next bar) — they expire

        # after loop, equity already includes last bar's mark
        # final equity is last equity after mark
        if not equity:
            equity = [float(self.initial_balance)]

        eq_arr = np.array(equity, dtype=float)
        rets = np.diff(eq_arr) / np.where(eq_arr[:-1] == 0, 1, eq_arr[:-1])
        rets = rets[np.isfinite(rets)]
        from qts.validation.metrics import max_drawdown, profit_factor, sharpe_ratio

        sharpe = sharpe_ratio(rets) if len(rets) else 0.0
        dd = max_drawdown(eq_arr)
        pf = profit_factor(rets) if len(rets) else 0.0
        payload = json.dumps(
            {
                "strategy_id": strategy_id,
                "params": strategy_params,
                "data_version": data_version,
                "seed": seed,
                "bars": len(bars),
                "execution": "next_bar_open",
            },
            sort_keys=True,
        )
        manifest_hash = hashlib.sha256(payload.encode()).hexdigest()[:12]
        config_hash = hashlib.sha256(json.dumps({"matching": self.matching_config.__dict__}, sort_keys=True, default=str).encode()).hexdigest()[:8]
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
            config_hash=config_hash,
        )

    def run_stress(
        self, instrument: Instrument, timeframe: str, data_version: str, strategy_id: str, strategy_params: dict[str, Any] | None, spreads: list[float]
    ) -> dict[float, float]:
        """Re-run strategy under different spread stress (real trades, not PF multiplication)."""
        results: dict[float, float] = {}
        for spread in spreads:
            cfg = MatchingConfig(
                spread_bps=spread * 3.0,  # base 3 bps * multiplier? For stress, multiplier applied
                slippage_bps=self.matching_config.slippage_bps,
                execution_delay_ms=self.matching_config.execution_delay_ms,
                commission_per_lot=self.matching_config.commission_per_lot,
            )
            # For stress, we treat spread input as multiplier? Actually caller passes [1.0, 1.5, 2.0] multipliers.
            # We need to map multiplier to spread_bps.
            # If spreads are multipliers, convert.
            if spread in (1.0, 1.5, 2.0, 3.0):
                # multiplier
                stress_cfg = MatchingConfig(
                    spread_bps=self.matching_config.spread_bps * spread,
                    slippage_bps=self.matching_config.slippage_bps * spread,
                    execution_delay_ms=self.matching_config.execution_delay_ms,
                    commission_per_lot=self.matching_config.commission_per_lot,
                )
            else:
                stress_cfg = cfg
            engine = BacktestEngine(self.data_store, self.risk_limits, stress_cfg, initial_balance=self.initial_balance)
            res = engine.run(instrument, timeframe, data_version, strategy_id, strategy_params)
            # use PF as stress metric (or sharpe)
            results[spread] = res.profit_factor
        return results
