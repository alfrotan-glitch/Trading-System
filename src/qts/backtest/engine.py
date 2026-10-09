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

from qts.adapters.matching import MatchingConfig, MatchingEngine
from qts.adapters.paper_adapter import RealisticPaperBroker
from qts.data.store import SqliteParquetDataStore
from qts.domain.value_objects import Instrument
from qts.execution.engine import ExecutionEngine, OrderManager
from qts.execution.idempotency import IdempotencyStore
from qts.observability.audit import AuditLog, InMemoryAuditLog
from qts.portfolio.portfolio import Portfolio
from qts.research.strategy import SmaBreakoutStrategy, signal_to_intent
from qts.risk.engine import RiskEngine, RiskLimits


def _parse_exit_rules(exit_rules: dict[str, Any] | None) -> tuple[float | None, int | None]:
    """Validate declared exit rules. A malformed rule is refused, not ignored."""
    if not exit_rules:
        return None, None
    stop_raw = exit_rules.get("stop_distance_usd")
    hold_raw = exit_rules.get("max_hold_bars")

    stop_distance: float | None = None
    if stop_raw is not None:
        stop_distance = float(stop_raw)
        if stop_distance != stop_distance or stop_distance in (float("inf"), float("-inf")):
            raise ValueError("exit_rules.stop_distance_usd must be finite")
        if stop_distance <= 0:
            raise ValueError(f"exit_rules.stop_distance_usd must be > 0 (got {stop_distance})")

    max_hold: int | None = None
    if hold_raw is not None:
        max_hold = int(hold_raw)
        if max_hold < 1:
            raise ValueError(f"exit_rules.max_hold_bars must be >= 1 (got {max_hold})")

    if stop_distance is None and max_hold is None:
        raise ValueError(
            f"exit_rules declared no usable rule: {sorted(exit_rules)} — "
            "expected stop_distance_usd and/or max_hold_bars"
        )
    return stop_distance, max_hold


#: Parameters the backtest engine consumes itself. They are never forwarded to
#: a strategy constructor — a strategy has no business knowing the order size.
_HARNESS_PARAM_KEYS = frozenset({"quantity"})


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
    # This is the immutable checksum from the selected dataset manifest, not a
    # hash of the run configuration.  Keep the field name for compatibility.
    manifest_hash: str = ""
    final_equity: float = 10000.0
    sharpe: float = 0.0
    max_dd: float = 0.0
    profit_factor: float = 0.0
    # Full run configuration identity (strategy, parameters, seed, data,
    # matching/risk settings, and code version).
    config_hash: str = ""
    code_version: str = ""

    def hash(self) -> str:
        payload = json.dumps({"equity": self.equity_curve, "fills": self.fills}, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:12]


def _fill_record(fill: Any, bar: Any, idx: int, strategy_id: str, role: str) -> dict[str, Any]:
    """One serialised fill.

    ``bar_open`` is the reference price the fill was priced against and ``fee``
    is what the matching engine charged; together they let a trade ledger
    separate the frictionless P&L from the cost the simulation really took.
    ``role`` records WHY the fill happened: ``signal``, ``exit_stop`` or
    ``exit_time`` — an exit a stop produced is not an exit a signal produced.
    """
    return {
        "price": str(fill.price),
        "qty": str(fill.quantity),
        "side": fill.side.value,
        "time": fill.event_time.isoformat(),
        "bar_open": str(bar.open),
        "bar_idx": idx,
        "fee": str(getattr(fill, "fee", Decimal("0")) or Decimal("0")),
        "role": role,
        "strategy_id": strategy_id,
    }


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
        exit_rules: dict[str, Any] | None = None,
    ) -> BacktestResult:
        """Run a strategy over bars.

        ``exit_rules`` declares how an open position is CLOSED, independently of
        the signal that opened it:

        * ``stop_distance_usd`` — protective stop, measured in price units from
          the position's average entry price. Evaluated intrabar.
        * ``max_hold_bars`` — deterministic time exit.

        Without them a position can only be closed by an opposite signal, which
        means a stop-loss strategy is backtested as a naked always-in reversal
        system — a different strategy wearing the same name. Exit rules are part
        of the run configuration and therefore part of ``config_hash``.
        """
        strategy_params = strategy_params or {}
        stop_distance, max_hold = _parse_exit_rules(exit_rules)
        dataset_manifest = self.data_store.manifest(data_version)
        if dataset_manifest is None:
            raise ValueError(f"dataset manifest unavailable for version {data_version}")
        if dataset_manifest.instrument != instrument.symbol or dataset_manifest.timeframe != timeframe:
            raise ValueError(
                "dataset manifest does not match requested instrument/timeframe: "
                f"manifest={dataset_manifest.instrument}/{dataset_manifest.timeframe}, "
                f"requested={instrument.symbol}/{timeframe}"
            )
        bars = self.data_store.read_bars(instrument, timeframe, start, end, version=data_version)
        if not bars:
            raise ValueError(f"no bars for {instrument.symbol} {timeframe} version {data_version}")
        bars = sorted(bars, key=lambda b: b.open_time)

        # strategy factory — supports legacy sma_breakout and all families via StrategyFactory
        # Attempt family-based creation first
        strat = None
        # Map strategy_id prefix to family for campaign strategies like trend_XXXX, breakout_XXXX etc.
        family_prefix_map = {
            "trend": "trend",
            "breakout": "breakout",
            "mean_reversion": "mean_reversion",
            "meanrev": "mean_reversion",
            "momentum": "momentum",
            "volatility": "volatility",
            "vol_": "volatility",
        }
        # If strategy_id looks like family trial (contains family name), try to instantiate via strategies.py
        try:
            from qts.research.strategies import StrategyFamily, create_strategy

            # infer family from strategy_params hint or id
            inferred_family = None
            if strategy_params.get("_family"):
                inferred_family = strategy_params.get("_family")
            else:
                for prefix, fam in family_prefix_map.items():
                    if strategy_id.startswith(prefix) or prefix in strategy_id:
                        inferred_family = fam
                        break
            if inferred_family:
                fam_enum = StrategyFamily(inferred_family)
                # Filter params to only those the strategy constructor accepts:
                # internal keys are never forwarded, and harness keys belong to
                # the engine (``quantity`` sizes the order, it is not a signal
                # parameter). Forwarding either used to raise a TypeError that
                # was swallowed below, silently running a DIFFERENT strategy.
                clean_params = {
                    k: v for k, v in strategy_params.items() if k not in _HARNESS_PARAM_KEYS and not k.startswith("_")
                }
                try:
                    strat = create_strategy(fam_enum, instrument, clean_params, strategy_id=strategy_id)
                except Exception:
                    strat = None
        except Exception:
            strat = None

        # An explicit family is a contract, not a hint. If it cannot be built,
        # refuse: falling through to a different strategy would produce
        # confident, reproducible evidence about the wrong thing.
        explicit_family = strategy_params.get("_family")
        if explicit_family and strat is None:
            raise ValueError(
                f"strategy {strategy_id!r}: explicit family {explicit_family!r} could not be instantiated "
                "from the supplied parameters — refusing to silently run a different strategy"
            )

        if strat is None:
            if strategy_id == "sma_breakout":
                strat = SmaBreakoutStrategy(
                    instrument,
                    fast=strategy_params.get("fast", 10),
                    slow=strategy_params.get("slow", 20),
                    strategy_id=strategy_id,
                )
            elif strategy_id == "hold_long":
                # simple hold for testing P&L
                from qts.domain.value_objects import Side
                from qts.research.strategy import Signal as Sig

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
                # Generic fallback: treat unknown as sma_breakout with given params (for research campaign placeholder)
                # This ensures bounded campaigns never crash on unknown strategy_id, but still produce deterministic backtest
                try:
                    strat = SmaBreakoutStrategy(
                        instrument,
                        fast=int(strategy_params.get("fast", 10)),
                        slow=int(strategy_params.get("slow", 20)),
                        strategy_id=strategy_id,
                    )
                except Exception as e:
                    raise ValueError(f"unknown strategy {strategy_id}: {e}") from e

        matching = MatchingEngine(self.matching_config)
        # Isolated idempotency: backtest must NOT mutate live/shared lineage (G2)
        # Use isolated in-memory store (or per-run temp file) so live records remain untouched
        # Previously this cleared the shared DB (idemp.clear()) which destroyed live lineage.
        # Research/simulation state must not mutate the durable risk authority
        # or reconciliation state used by paper/shadow/live.  Idempotency was
        # already isolated; the kill switch and suspend state are isolated here
        # as well.  A backtest therefore cannot clear a production kill switch.
        risk = RiskEngine(self.risk_limits, db_path=self.data_store.db_path, persist_kill=False)
        idemp = IdempotencyStore(db_path=":memory:")
        om = OrderManager(audit=self.audit, idempotency=idemp)
        broker = RealisticPaperBroker(matching=matching)
        portfolio = Portfolio(initial_balance=Decimal(str(self.initial_balance)), currency="USD")
        exec_engine = ExecutionEngine(
            om,
            risk,
            broker,
            matching,
            portfolio,
            audit=self.audit,
            persist_reconcile_state=False,
        )

        equity: list[float] = []
        fills_out: list[dict[str, Any]] = []

        # Execution convention: next-bar open
        # We maintain pending intents to be executed on next bar
        pending_intents: list[Any] = []  # OrderIntent list
        #: symbol -> (bar index the current position was opened on).
        entry_index: dict[str, int] = {}

        for idx, bar in enumerate(bars):
            # 1) execute pending intents from previous bar at this bar's open
            if pending_intents:
                # For each pending intent, create a synthetic execution bar at this bar's open
                # Use current bar's open as execution price basis (open ± spread)
                # For more realism we could use open, but we use bar's open as price for matching
                # MatchingEngine.price_for uses bar.close; for execution at open we need to treat
                # bar.open as the price. So we create a execution_bar with open=close=open
                from datetime import timedelta

                from qts.domain.value_objects import Bar as BarVO

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
                        fills_out.append(_fill_record(fill, bar, idx, strategy_id, "signal"))
                pending_intents = []

            # 1b) declared exits — stop and time. These close a position WITHOUT
            # waiting for an opposite signal, which is what a stop-loss strategy
            # actually does. Order is deterministic: time at this bar's open,
            # then the intrabar stop.
            if stop_distance is not None or max_hold is not None:
                for order_intent, reason, exit_bar in self._exit_intents(
                    bar=bar,
                    idx=idx,
                    portfolio=portfolio,
                    entry_index=entry_index,
                    stop_distance=stop_distance,
                    max_hold=max_hold,
                    strategy_id=strategy_id,
                    seq=len(fills_out),
                ):
                    _order, fills = exec_engine.submit_intent(order_intent, bar=exit_bar)
                    for fill in fills:
                        fills_out.append(_fill_record(fill, exit_bar, idx, strategy_id, reason))
                    # A position that just closed (or flipped) restarts the clock.
                    self._sync_entry_index(portfolio, entry_index, idx)

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
                    update={
                        "client_order_id": f"{strategy_id}:{bar.close_time.isoformat()}:{len(fills_out) + len(pending_intents)}"
                    }
                )
                # queue for next bar execution
                pending_intents.append(intent)

            # The position that exists after this bar's own exits is the one the
            # clock is kept for; a queued signal has not changed anything yet.
            self._sync_entry_index(portfolio, entry_index, idx)

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
        from qts.observability.lineage import code_version

        run_code_version = code_version()
        run_configuration = {
            "strategy_id": strategy_id,
            "params": strategy_params,
            "data_version": data_version,
            "dataset_manifest_hash": dataset_manifest.checksum,
            "seed": seed,
            "start": start.isoformat() if start else None,
            "end": end.isoformat() if end else None,
            "bars": len(bars),
            "execution": "next_bar_open",
            "exit_rules": exit_rules or {},
            "matching": self.matching_config.__dict__,
            "risk_limits": self.risk_limits.model_dump(mode="json"),
            "initial_balance": str(self.initial_balance),
            "code_version": run_code_version,
        }
        config_hash = hashlib.sha256(
            json.dumps(run_configuration, sort_keys=True, default=str, separators=(",", ":")).encode()
        ).hexdigest()[:12]
        return BacktestResult(
            strategy_id=strategy_id,
            data_version=data_version,
            seed=seed,
            bars=len(bars),
            trades=len(fills_out),
            equity_curve=equity,
            returns=rets.tolist(),
            fills=fills_out,
            manifest_hash=dataset_manifest.checksum,
            final_equity=float(equity[-1]) if equity else self.initial_balance,
            sharpe=float(sharpe),
            max_dd=float(dd),
            profit_factor=float(pf),
            config_hash=config_hash,
            code_version=run_code_version,
        )

    # ------------------------------------------------------------ exit rules
    @staticmethod
    def _sync_entry_index(portfolio: Any, entry_index: dict, idx: int) -> None:
        """Record when each currently-open position was opened.

        A position that has flipped direction is a NEW position for the clock's
        purposes: the stop distance and the holding clock are both measured from
        the price and the bar of the position that exists now, not from a lot
        that has already been closed.
        """
        for symbol, position in portfolio.positions.items():
            quantity = position.quantity
            if quantity == 0:
                entry_index.pop(symbol, None)
                continue
            direction = 1 if quantity > 0 else -1
            previous = entry_index.get(symbol)
            if not isinstance(previous, tuple) or previous[1] != direction:
                entry_index[symbol] = (idx, direction)

    def _exit_intents(
        self,
        *,
        bar: Any,
        idx: int,
        portfolio: Any,
        entry_index: dict,
        stop_distance: float | None,
        max_hold: int | None,
        strategy_id: str,
        seq: int,
    ) -> list[tuple]:
        """Exit orders a declared stop or time limit produces on this bar.

        Conventions, all deliberately conservative:

        * **Time exit fills at this bar's open.** Deterministic, and it is the
          first exit considered, so a bar that triggers both is settled by the
          clock.
        * **Stop exit fills at the stop price — or worse if the bar gapped
          through it.** A stop is not a guarantee; it is an order. If the bar
          opens beyond the stop level the fill takes the open, because that is
          the first price at which the order could trade.
        * Both are then priced by the matching engine, so an exit pays spread
          and slippage exactly like an entry. Exits are not free.
        """
        from datetime import timedelta

        from qts.domain.value_objects import Bar as BarVO
        from qts.domain.value_objects import OrderIntent, OrderType, Side

        out: list[tuple] = []
        for _symbol, position in list(portfolio.positions.items()):
            quantity = position.quantity
            if quantity == 0:
                continue
            long = quantity > 0
            entry = entry_index.get(position.instrument.symbol)
            entry_idx = entry[0] if isinstance(entry, tuple) else idx
            reference: Decimal | None = None
            reason = ""

            if max_hold is not None and (idx - int(entry_idx)) >= max_hold:
                reference = bar.open
                reason = "exit_time"
            elif stop_distance is not None:
                stop = Decimal(str(stop_distance))
                level = position.avg_price - stop if long else position.avg_price + stop
                triggered = bar.low <= level if long else bar.high >= level
                if triggered:
                    # Gap through the stop -> the open is the achievable price.
                    reference = min(bar.open, level) if long else max(bar.open, level)
                    reason = "exit_stop"
            if reference is None:
                continue

            exit_bar = BarVO(
                instrument=bar.instrument,
                open=reference,
                high=reference,
                low=reference,
                close=reference,
                volume=bar.volume,
                open_time=bar.open_time,
                close_time=bar.open_time + timedelta(milliseconds=1),
                data_version=bar.data_version,
                source=f"execution_{reason}",
            )
            intent = OrderIntent(
                instrument=position.instrument,
                side=Side.SELL if long else Side.BUY,
                quantity=abs(quantity),
                order_type=OrderType.MARKET,
                client_order_id=f"{strategy_id}:{bar.open_time.isoformat()}:{reason}:{seq}",
                strategy_id=strategy_id,
            )
            out.append((intent, reason, exit_bar))
        return out

    def run_stress(
        self,
        instrument: Instrument,
        timeframe: str,
        data_version: str,
        strategy_id: str,
        strategy_params: dict[str, Any] | None,
        spreads: list[float],
        exit_rules: dict[str, Any] | None = None,
    ) -> dict[float, float]:
        """Re-run strategy under different spread stress (real trades, not PF multiplication).

        ``exit_rules`` must be the same rules as the baseline: stressing the
        spread of a strategy with a stop while the baseline had no stop would
        compare two different strategies.
        """
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
            res = engine.run(
                instrument, timeframe, data_version, strategy_id, strategy_params, exit_rules=exit_rules
            )
            # use PF as stress metric (or sharpe)
            results[spread] = res.profit_factor
        return results
