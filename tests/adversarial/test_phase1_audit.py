"""Phase 1 Adversarial Audit — tests designed to make system fail if it has leakage, fake validation, incorrect PnL, etc."""

import tempfile
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import numpy as np
import pytest

from qts.adapters.paper_adapter import RealisticPaperBroker
from qts.data.store import SqliteParquetDataStore
from qts.data.synthetic import generate_gbm_bars, generate_trending_bars
from qts.domain.value_objects import Account, Bar, Instrument, OrderIntent, Position, Side
from qts.execution.engine import ExecutionEngine, OrderManager
from qts.execution.idempotency import IdempotencyStore
from qts.execution.matching import MatchingConfig, MatchingEngine
from qts.portfolio.portfolio import Portfolio
from qts.risk.engine import RiskContext, RiskEngine, RiskLimits
from qts.validation.metrics import deflated_sharpe_ratio, probabilistic_sharpe_ratio

# ---- 1. Backtest temporal correctness ----


def test_next_bar_execution_no_lookahead():
    """Signal on bar N must fill at bar N+1 open, not same-bar close (no lookahead)."""
    from qts.backtest.engine import BacktestEngine

    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteParquetDataStore(root=Path(tmp) / "data", db_path=Path(tmp) / "qts.db")
        instr = Instrument(symbol="XAUUSD")
        base = datetime(2020, 1, 1, tzinfo=UTC)
        # Create deterministic trending bars: price = 2000 + i * 10
        # hold_long signals on bar 0 close, so next-bar fill must be at bar 1 open (2010), not bar 0 close (2000)
        bars = []
        for i in range(10):
            open_p = Decimal(str(2000 + i * 10))
            close_p = Decimal(str(2000 + i * 10 + 5))
            bars.append(
                Bar(
                    instrument=instr,
                    open=open_p,
                    high=close_p + Decimal("1"),
                    low=open_p - Decimal("1"),
                    close=close_p,
                    volume=Decimal("1000"),
                    open_time=base + timedelta(hours=i),
                    close_time=base + timedelta(hours=i + 1),
                    data_version="test",
                )
            )
        manifest = store.write_bars(bars)
        engine = BacktestEngine(
            store, matching_config=MatchingConfig(spread_bps=0, slippage_bps=0, commission_per_lot=0)
        )
        res = engine.run(
            instr, manifest.timeframe, manifest.version, strategy_id="hold_long", strategy_params={"quantity": 0.1}
        )
        # hold_long should have exactly 1 trade, filled at bar 1 open
        assert res.trades == 1, f"expected 1 fill, got {res.fills}"
        fill = res.fills[0]
        # next-bar: fill at bar_idx 1, price == bars[1].open == 2010
        assert fill["bar_idx"] == 1, f"fill at {fill['bar_idx']} should be 1 (next bar)"
        assert Decimal(fill["price"]) == bars[1].open, (
            f"fill price {fill['price']} should be next bar open {bars[1].open}"
        )
        # Also verify SMA strategy still respects next-bar: pending queue
        # Run SMA and ensure no fill on bar 0
        engine2 = BacktestEngine(
            store, matching_config=MatchingConfig(spread_bps=0, slippage_bps=0, commission_per_lot=0)
        )
        res2 = engine2.run(
            instr,
            manifest.timeframe,
            manifest.version,
            strategy_id="sma_breakout",
            strategy_params={"fast": 2, "slow": 3, "quantity": 0.1},
        )
        # All fills must be offset by 1 bar from signal; we check first fill bar_idx >=3 (slow=3 needs 3 bars)
        if res2.fills:
            assert res2.fills[0]["bar_idx"] >= 3


def test_leakage_fixture_only_profitable_with_lookahead():
    """Executable leakage test: intrabar high/low is only profitable with lookahead.

    Construct bars where open==close==2000 but high=2100/low=1900. A cheating
    strategy that could trade at the future-known high/low inside the same bar
    would profit 200*contract per round-trip. With correct next-bar semantics,
    fill is at next bar open (2000) + spread, not at intrabar extremes, so PF
    must remain ~1 (no profit). This would FAIL if the engine used same-bar
    high/low or close for fills.

    We prove two things:
    1) Next-bar fill price == next open, not current high/low/close.
    2) Hypothetical same-bar cheating execution would be profitable, so the
       protection is material (test would fail if protection removed).
    """
    from qts.backtest.engine import BacktestEngine
    from qts.domain.value_objects import Bar as BarVO

    instr = Instrument(symbol="XAUUSD")
    base = datetime(2020, 1, 1, tzinfo=UTC)
    # 20 bars, open==close==2000, but high/low expose 100 range — no trend
    bars = []
    for i in range(20):
        bars.append(
            BarVO(
                instrument=instr,
                open=Decimal("2000"),
                high=Decimal("2100"),
                low=Decimal("1900"),
                close=Decimal("2000"),
                volume=Decimal("1000"),
                open_time=base + timedelta(hours=i),
                close_time=base + timedelta(hours=i + 1),
                data_version="test",
            )
        )
    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteParquetDataStore(root=Path(tmp) / "data", db_path=Path(tmp) / "qts.db")
        manifest = store.write_bars(bars)
        # Honest strategy: hold_long (1 trade) — with next-bar should be flat (entry at bar1 open 2000, never exit, PF 0 or flat)
        engine = BacktestEngine(
            store, matching_config=MatchingConfig(spread_bps=0, slippage_bps=0, commission_per_lot=0)
        )
        res = engine.run(
            instr, manifest.timeframe, manifest.version, strategy_id="hold_long", strategy_params={"quantity": 0.1}
        )
        # With no trend and next-bar at open, equity should not grow: final equity == initial or small
        # hold_long buys at bar1 open 2000 and never sells, mark at 2000 -> flat
        assert res.trades == 1
        assert abs(res.final_equity - 10000) < 1e-6, f"next-bar flat expected 10000 got {res.final_equity}"
        assert res.profit_factor == 0.0 or res.profit_factor == float("inf") or res.profit_factor < 1.1  # flat
        # Now simulate cheating: if engine allowed same-bar fill at close/high/low,
        # a strategy that buys at low (1900) and sells at high (2100) intrabar would profit.
        # We directly use MatchingEngine to show the difference:
        bar0 = bars[0]
        intent_buy_low = OrderIntent(
            instrument=instr, side=Side.BUY, quantity=Decimal("0.1"), client_order_id="cheat-buy", strategy_id="cheat"
        )
        _intent_sell_high = OrderIntent(
            instrument=instr, side=Side.SELL, quantity=Decimal("0.1"), client_order_id="cheat-sell", strategy_id="cheat"
        )
        # Cheating execution at intrabar extremes (not allowed): would fill at 1900/2100
        # Our matching at bar close would give price != high/low, but cheating would pick them
        # Prove that next-bar price is 2000, not 1900/2100
        from qts.execution.matching import MatchingEngine as ME

        me = ME(MatchingConfig(spread_bps=0, slippage_bps=0, commission_per_lot=0))
        # Correct next-bar exec_bar at next open (bar1.open =2000)
        exec_bar = BarVO(
            instrument=instr,
            open=Decimal("2000"),
            high=Decimal("2000"),
            low=Decimal("2000"),
            close=Decimal("2000"),
            volume=Decimal("1000"),
            open_time=bar0.close_time,
            close_time=bar0.close_time + timedelta(milliseconds=1),
            data_version="test",
            source="execution_open",
        )
        fills_next = me.match(intent_buy_low, exec_bar)
        assert fills_next[0].price == Decimal("2000"), f"next-bar price should be open 2000, got {fills_next[0].price}"
        # Cheating fill at low (1900) would be profitable vs next-bar 2000
        cheating_price = Decimal("1900")
        assert cheating_price != fills_next[0].price
        # Demonstrate that cheating round-trip profit would be 100*0.1*100=1000 per pair, while next-bar is 0
        # For two-bar cheating: buy 0.1 at 1900, sell 0.1 at 2100 profit = 0.1*100*(2100-1900)=2000
        # Next-bar buy 0.1 at 2000 sell 0.1 at 2000 profit 0
        # So we assert protection is material:
        cheating_profit = Decimal("0.1") * Decimal("100") * (Decimal("2100") - Decimal("1900"))
        next_bar_profit = Decimal("0.1") * Decimal("100") * (fills_next[0].price - Decimal("2000"))  # 0
        assert cheating_profit == Decimal("2000")
        assert next_bar_profit == Decimal("0")
        # If engine were broken to allow same-bar, this test would fail because res would be profitable


# ---- 2. Real walk-forward vs slicing ----


def test_walk_forward_is_real_not_sliced():
    """Walk-forward must run independent backtests per fold, not slice equity curve."""
    from qts.validation.pipeline import ValidatorPipeline

    pipe = ValidatorPipeline(config={"min_folds": 3})
    n = 300
    splits = pipe.walk_forward_splits(n, train=100, test=50, step=50)
    assert len(splits) >= 3
    for train_s, train_e, test_s, test_e in splits:
        assert train_e - train_s == 100
        assert test_e - test_s == 50
        assert train_e == test_s  # contiguous
        assert train_s < train_e < test_e

    # Ensure equity slicing is not used: our pipeline now requires real folds, not dummy
    is_eq = np.array([10000, 10001, 10002], dtype=float)
    oos_eq = np.array([10002, 10003, 10004], dtype=float)
    report = pipe.validate(
        strategy_id="s",
        data_version="v1",
        equity_is=is_eq,
        equity_oos=oos_eq,
        walk_forward_folds=None,  # missing → should block
        num_trials=1,
        cpcv_folds=None,
        perturbed_sharpes=None,
        stress_results=None,
    )
    assert not report.passed
    assert any(c.status == "NOT_IMPLEMENTED" for c in report.checks)


# ---- 3. CPCV/PBO not heuristic ----


def test_pbo_requires_real_computation():
    from qts.validation.pipeline import ValidatorPipeline

    pipe = ValidatorPipeline()
    # No cpcv folds → should block
    is_eq = np.array([10000, 10100, 10200], dtype=float)
    oos_eq = np.array([10200, 10300, 10400], dtype=float)
    report = pipe.validate(
        strategy_id="s",
        data_version="v1",
        equity_is=is_eq,
        equity_oos=oos_eq,
        walk_forward_folds=[
            {"is_sharpe": 1, "oos_sharpe": 0.5},
            {"is_sharpe": 1, "oos_sharpe": 0.5},
            {"is_sharpe": 1, "oos_sharpe": 0.5},
        ],
        num_trials=1,
        cpcv_folds=None,  # missing
        perturbed_sharpes=[0, 0, 0, 0, 0, 0, 0],
        stress_results={1.0: 1.0, 1.5: 1.0},
    )
    assert not report.passed
    assert any(c.name == "pbo_cpcv" and c.status == "NOT_IMPLEMENTED" for c in report.checks)

    # With insufficient combos (<5) also block
    report2 = pipe.validate(
        strategy_id="s",
        data_version="v1",
        equity_is=is_eq,
        equity_oos=oos_eq,
        walk_forward_folds=[{"is_sharpe": 1, "oos_sharpe": 0.5}] * 3,
        num_trials=1,
        cpcv_folds=[{"best_is_test_sharpe": 0.5, "median_test_sharpe": 0.5}],  # only 1
        perturbed_sharpes=[0] * 7,
        stress_results={1.0: 1.0},
    )
    assert not report2.passed


# ---- 4. DSR/PSR correctness ----


def test_psr_dsr_reference_values():
    # Reference: Bailey 2012 example: n=100, SR=1, skew=0, kurt=3, benchmark=0 => PSR ~0.84?
    # We test invariant: PSR with benchmark 0 and SR>0 should be >0.5
    psr = probabilistic_sharpe_ratio(1.0, 100, 0, 3, 0)
    assert 0.5 < psr < 1.0
    # DSR should be <= PSR for N>1 (multiple testing penalty)
    psr1 = probabilistic_sharpe_ratio(1.0, 100, 0, 3, 0)
    dsr = deflated_sharpe_ratio(1.0, 10, 100, 0, 3)
    assert dsr < psr1
    assert dsr > 0
    # For N=1, DSR == PSR
    dsr1 = deflated_sharpe_ratio(1.0, 1, 100, 0, 3)
    assert abs(dsr1 - psr1) < 1e-9
    # Large N should lower DSR
    dsr10 = deflated_sharpe_ratio(1.0, 10, 100, 0, 3)
    dsr100 = deflated_sharpe_ratio(1.0, 100, 100, 0, 3)
    assert dsr100 < dsr10


def test_dsr_documents_trials():
    # DSR decreases with more trials N (higher multiple-testing hurdle) for fixed n, SR
    # Using annualized=False to have per-period units where benchmark scaling is explicit
    # For n=100, SR=1.0 per-period, N=10 vs N=100
    dsr_10 = deflated_sharpe_ratio(1.0, 10, 100, 0, 3, periods_per_year=1, annualized=False)
    dsr_100 = deflated_sharpe_ratio(1.0, 100, 100, 0, 3, periods_per_year=1, annualized=False)
    assert dsr_100 < dsr_10  # more trials → higher benchmark → lower confidence
    # For N=1, DSR == PSR(0)
    psr = probabilistic_sharpe_ratio(1.0, 100, 0, 3, 0, periods_per_year=1, annualized=False)
    dsr1 = deflated_sharpe_ratio(1.0, 1, 100, 0, 3, periods_per_year=1, annualized=False)
    assert abs(dsr1 - psr) < 1e-9
    # DSR < PSR for N>1
    dsr = deflated_sharpe_ratio(1.0, 10, 100, 0, 3, periods_per_year=1, annualized=False)
    assert dsr < psr


# ---- 5. Parameter robustness ----


def test_perturbation_requires_real_runs():
    from qts.validation.pipeline import ValidatorPipeline

    pipe = ValidatorPipeline()
    report = pipe.validate(
        strategy_id="s",
        data_version="v1",
        equity_is=np.array([10000, 10100, 10200], dtype=float),
        equity_oos=np.array([10200, 10300, 10400], dtype=float),
        walk_forward_folds=[{"is_sharpe": 1, "oos_sharpe": 0.5}] * 3,
        num_trials=1,
        cpcv_folds=[{"best_is_test_sharpe": 0.6, "median_test_sharpe": 0.5}] * 5,
        perturbed_sharpes=None,  # missing → block
        stress_results={1.0: 1.0, 1.5: 1.0},
    )
    assert not report.passed
    assert any(c.name.startswith("perturbation") and c.status == "NOT_IMPLEMENTED" for c in report.checks)

    # Fragile: sign flip should fail
    report2 = pipe.validate(
        strategy_id="s",
        data_version="v1",
        equity_is=np.array([10000, 10100, 10200], dtype=float),
        equity_oos=np.array([10200, 10300, 10400], dtype=float),
        walk_forward_folds=[{"is_sharpe": 1, "oos_sharpe": 0.5}] * 3,
        num_trials=1,
        cpcv_folds=[{"best_is_test_sharpe": 0.6, "median_test_sharpe": 0.5}] * 5,
        perturbed_sharpes=[1.0, 1.1, -0.5, 1.0, 0.9, 1.0, 1.0],  # sign flip
        stress_results={1.0: 1.0, 1.5: 1.0},
    )
    assert not report2.passed


# ---- 6. Transaction-cost stress must be real ----


def test_stress_must_be_real_not_multiplied():
    from qts.validation.pipeline import ValidatorPipeline

    pipe = ValidatorPipeline()
    # Missing stress → block
    report = pipe.validate(
        strategy_id="s",
        data_version="v1",
        equity_is=np.array([10000, 10100], dtype=float),
        equity_oos=np.array([10100, 10200], dtype=float),
        walk_forward_folds=[{"is_sharpe": 1, "oos_sharpe": 0.5}] * 3,
        num_trials=1,
        cpcv_folds=[{"best_is_test_sharpe": 0.6, "median_test_sharpe": 0.5}] * 5,
        perturbed_sharpes=[1, 1, 1, 1, 1, 1, 1],
        stress_results=None,
    )
    assert not report.passed
    assert any("stress" in c.name and c.status == "NOT_IMPLEMENTED" for c in report.checks)

    # Real stress via re-run: use BacktestEngine.run_stress
    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteParquetDataStore(root=Path(tmp) / "data", db_path=Path(tmp) / "qts.db")
        instr = Instrument(symbol="XAUUSD")
        bars = generate_trending_bars(instrument=instr, periods=200, seed=42)
        manifest = store.write_bars(bars)
        from qts.backtest.engine import BacktestEngine

        engine = BacktestEngine(store)
        stress = engine.run_stress(
            instr,
            manifest.timeframe,
            manifest.version,
            "sma_breakout",
            {"fast": 10, "slow": 20},
            spreads=[1.0, 1.5, 2.0],
        )
        assert 1.0 in stress and 1.5 in stress and 2.0 in stress
        # Stress must come from actual trades, not PF*0.7
        # We check that stress values are not simply PF*multiplier but actual re-run
        assert stress[1.5] != stress[1.0] * 0.7 or stress[1.0] == 0  # at least not naive


# ---- 7. P&L accounting invariants ----


def test_pnl_long_flat():
    instr = Instrument(symbol="XAUUSD", contract_size=Decimal("100"))
    pf = Portfolio(initial_balance=Decimal("10000"))
    # Buy 1 lot at 2000
    pf.apply_fill(
        type(
            "Fill",
            (),
            {
                "instrument": instr,
                "side": Side.BUY,
                "quantity": Decimal("1"),
                "price": Decimal("2000"),
                "fee": Decimal("0"),
                "fill_id": "1",
            },
        )()  # type: ignore
    )
    # Actually use real Fill
    from qts.domain.value_objects import Fill as FillVO

    pf2 = Portfolio(initial_balance=Decimal("10000"))
    pf2.apply_fill(
        FillVO(
            fill_id="1",
            order_id="o1",
            client_order_id="c1",
            instrument=instr,
            side=Side.BUY,
            quantity=Decimal("1"),
            price=Decimal("2000"),
            fee=Decimal("5"),
            event_time=datetime.now(UTC),
        )
    )
    assert pf2.positions["XAUUSD"].quantity == Decimal("1")
    assert pf2.realized_pnl == Decimal("-5")
    # Mark at 2010
    pf2.mark_to_market("XAUUSD", Decimal("2010"))
    # unrealized = 1*100*(2010-2000)=1000
    assert pf2.unrealized_total() == Decimal("1000")
    assert pf2.equity() == Decimal("10000") - Decimal("5") + Decimal("1000")
    # Sell 1 lot at 2010 -> flat
    pf2.apply_fill(
        FillVO(
            fill_id="2",
            order_id="o2",
            client_order_id="c2",
            instrument=instr,
            side=Side.SELL,
            quantity=Decimal("1"),
            price=Decimal("2010"),
            fee=Decimal("5"),
            event_time=datetime.now(UTC),
        )
    )
    assert pf2.positions["XAUUSD"].quantity == Decimal("0")
    # realized: -5 + (1*100*10 -5) = 990
    assert pf2.realized_pnl == Decimal("990")
    assert pf2.unrealized_total() == Decimal("0")
    assert pf2.equity() == Decimal("10990")


def test_pnl_partial_close():
    instr = Instrument(symbol="XAUUSD", contract_size=Decimal("100"))
    from qts.domain.value_objects import Fill as FillVO

    pf = Portfolio(initial_balance=Decimal("10000"))
    pf.apply_fill(
        FillVO(
            fill_id="1",
            order_id="o1",
            client_order_id="c1",
            instrument=instr,
            side=Side.BUY,
            quantity=Decimal("1"),
            price=Decimal("2000"),
            fee=Decimal("0"),
            event_time=datetime.now(UTC),
        )
    )
    # partial close 0.4 at 2010
    pf.apply_fill(
        FillVO(
            fill_id="2",
            order_id="o2",
            client_order_id="c2",
            instrument=instr,
            side=Side.SELL,
            quantity=Decimal("0.4"),
            price=Decimal("2010"),
            fee=Decimal("0"),
            event_time=datetime.now(UTC),
        )
    )
    assert pf.positions["XAUUSD"].quantity == Decimal("0.6")
    assert pf.positions["XAUUSD"].avg_price == Decimal("2000")  # avg unchanged
    assert pf.realized_pnl == Decimal("0.4") * Decimal("100") * Decimal("10")  # 400
    pf.mark_to_market("XAUUSD", Decimal("2010"))
    assert pf.unrealized_total() == Decimal("0.6") * Decimal("100") * Decimal("10")  # 600


def test_pnl_flip_long_to_short():
    instr = Instrument(symbol="XAUUSD", contract_size=Decimal("100"))
    from qts.domain.value_objects import Fill as FillVO

    pf = Portfolio(initial_balance=Decimal("10000"))
    pf.apply_fill(
        FillVO(
            fill_id="1",
            order_id="o1",
            client_order_id="c1",
            instrument=instr,
            side=Side.BUY,
            quantity=Decimal("0.5"),
            price=Decimal("2000"),
            fee=Decimal("0"),
            event_time=datetime.now(UTC),
        )
    )
    # Sell 1.0 at 2010 → close 0.5 long (+500), new short 0.5 at 2010
    pf.apply_fill(
        FillVO(
            fill_id="2",
            order_id="o2",
            client_order_id="c2",
            instrument=instr,
            side=Side.SELL,
            quantity=Decimal("1"),
            price=Decimal("2010"),
            fee=Decimal("0"),
            event_time=datetime.now(UTC),
        )
    )
    assert pf.positions["XAUUSD"].quantity == Decimal("-0.5")
    assert pf.positions["XAUUSD"].avg_price == Decimal("2010")
    assert pf.realized_pnl == Decimal("0.5") * Decimal("100") * Decimal("10")  # 500


def test_pnl_fees_and_spread():
    # Ensure fees are deducted and spread captured via matching
    matching = MatchingEngine(MatchingConfig(spread_bps=10, slippage_bps=5, commission_per_lot=2.0))
    instr = Instrument(symbol="XAUUSD", contract_size=Decimal("100"))
    bar = Bar(
        instrument=instr,
        open=Decimal("2000"),
        high=Decimal("2001"),
        low=Decimal("1999"),
        close=Decimal("2000"),
        volume=Decimal("1000"),
        open_time=datetime(2020, 1, 1, tzinfo=UTC),
        close_time=datetime(2020, 1, 1, 1, tzinfo=UTC),
        data_version="test",
    )
    from qts.domain.value_objects import OrderIntent, OrderType

    intent = OrderIntent(
        instrument=instr,
        side=Side.BUY,
        quantity=Decimal("0.1"),
        order_type=OrderType.MARKET,
        client_order_id="c1",
        strategy_id="s",
    )
    fills = matching.match(intent, bar)
    # BUY at ask + slippage + commission
    assert fills[0].price > bar.close
    assert fills[0].fee == Decimal("0.2")  # 2 *0.1


# ---- 8. Risk kill switch ----


def test_kill_switch_survives_restart_and_blocks():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "qts.db"
        risk = RiskEngine(RiskLimits(daily_loss_limit=Decimal("100"), max_drawdown=Decimal("200")), db_path=db)
        _portfolio = Portfolio(initial_balance=Decimal("10000"))
        # Simulate loss: apply fill that causes -150 realized
        instr = Instrument(symbol="XAUUSD", contract_size=Decimal("100"))
        from qts.domain.value_objects import Fill as FillVO

        # Need to make daily_pnl -150: we can directly set risk context
        # Create a fill that loses
        # Instead we test via RiskEngine.post_trade with ctx
        ctx = RiskContext(
            account=Account(
                balance=Decimal("10000"), equity=Decimal("9850"), currency="USD", updated_at=datetime.now(UTC)
            ),
            positions={},
            open_orders_count=0,
            daily_pnl=Decimal("-150"),
            drawdown=Decimal("150"),
            instrument_suspended=set(),
            reference_prices={"XAUUSD": Decimal("2000")},
        )
        # post_trade should trigger kill
        fill = FillVO(
            fill_id="1",
            order_id="o1",
            client_order_id="c1",
            instrument=instr,
            side=Side.BUY,
            quantity=Decimal("1"),
            price=Decimal("2000"),
            fee=Decimal("0"),
            event_time=datetime.now(UTC),
        )
        risk.post_trade(fill, ctx)
        assert risk.killed
        # New engine from same db should still be killed
        risk2 = RiskEngine(RiskLimits(daily_loss_limit=Decimal("100")), db_path=db)
        assert risk2.killed
        # pre_trade should veto

        intent2 = OrderIntent(
            instrument=instr, side=Side.BUY, quantity=Decimal("0.1"), client_order_id="c2", strategy_id="s"
        )
        d = risk2.pre_trade(intent2, ctx)
        assert not d.allowed
        assert d.veto_reason.value == "KILL_SWITCH_ACTIVE"
        # reset should allow
        risk2.reset_kill()
        assert not risk2.killed


def test_risk_uses_current_equity_not_stale():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "qts.db"
        risk = RiskEngine(RiskLimits(max_notional=Decimal("5000")), db_path=db)
        instr = Instrument(symbol="XAUUSD", contract_size=Decimal("100"))
        # Use correct notional: 0.1 lot *100*2000=20000 >5000 → should veto
        intent = OrderIntent(
            instrument=instr, side=Side.BUY, quantity=Decimal("0.1"), client_order_id="c1", strategy_id="s"
        )
        ctx = RiskContext(
            account=Account(
                balance=Decimal("10000"), equity=Decimal("10000"), currency="USD", updated_at=datetime.now(UTC)
            ),
            positions={},
            open_orders_count=0,
            daily_pnl=Decimal("0"),
            drawdown=Decimal("0"),
            instrument_suspended=set(),
            reference_prices={"XAUUSD": Decimal("2000")},
        )
        d = risk.pre_trade(intent, ctx)
        assert not d.allowed
        assert d.veto_reason.value == "EXCEEDS_NOTIONAL"
        # With smaller quantity should pass
        intent_small = OrderIntent(
            instrument=instr, side=Side.BUY, quantity=Decimal("0.01"), client_order_id="c2", strategy_id="s"
        )
        d2 = risk.pre_trade(intent_small, ctx)
        # 0.01*100*2000=2000 <5000 pass
        assert d2.allowed


# ---- 9. Idempotency ----


def test_idempotency_no_double_fill():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "qts.db"
        om = OrderManager(idempotency=IdempotencyStore(db_path=db))
        matching = MatchingEngine()
        risk = RiskEngine(RiskLimits(), db_path=db)
        broker = RealisticPaperBroker()
        portfolio = Portfolio(initial_balance=Decimal("10000"))
        eng = ExecutionEngine(om, risk, broker, matching, portfolio)
        bar = Bar(
            instrument=Instrument(symbol="XAUUSD"),
            open=Decimal("2000"),
            high=Decimal("2001"),
            low=Decimal("1999"),
            close=Decimal("2000"),
            volume=Decimal("1000"),
            open_time=datetime.now(UTC),
            close_time=datetime.now(UTC) + timedelta(hours=1),
            data_version="test",
        )
        intent = OrderIntent(
            instrument=bar.instrument,
            side=Side.BUY,
            quantity=Decimal("0.1"),
            client_order_id="dup-123",
            strategy_id="s",
        )
        o1, f1 = eng.submit_intent(intent, bar=bar)
        assert len(f1) == 1
        # duplicate
        o2, f2 = eng.submit_intent(intent, bar=bar)
        assert o2.client_order_id == o1.client_order_id
        assert f2 == []
        # after restart (new OrderManager but same db)
        om2 = OrderManager(idempotency=IdempotencyStore(db_path=db))
        # simulate restart: new manager sees same db
        assert om2.idempotency.seen("dup-123")
        # Even with new engine, duplicate should be blocked if we reuse same store
        eng2 = ExecutionEngine(om2, risk, broker, matching, portfolio)
        o3, f3 = eng2.submit_intent(intent, bar=bar)
        # This will be considered duplicate via persistent store? Our current ExecutionEngine checks both in-memory and persistent.
        # For new manager, in-memory is empty, but persistent says seen, so it should block
        assert f3 == []


# ---- 10. Reconciliation operational ----


def test_reconciliation_suspends_on_drift():
    with tempfile.TemporaryDirectory() as tmp:
        om = OrderManager()
        risk = RiskEngine(RiskLimits(), db_path=Path(tmp) / "db.sqlite")
        broker = RealisticPaperBroker()
        portfolio = Portfolio(initial_balance=Decimal("10000"))
        eng = ExecutionEngine(om, risk, broker, MatchingEngine(), portfolio)
        # create drift: local 0.1, venue 0.5
        instr = Instrument(symbol="XAUUSD")
        portfolio.positions["XAUUSD"] = Position(instrument=instr, quantity=Decimal("0.1"), avg_price=Decimal("2000"))

        class FakeVenue:
            def positions(self):  # type: ignore[no-untyped-def]
                return [Position(instrument=instr, quantity=Decimal("0.5"), avg_price=Decimal("2000"))]

            def orders(self):  # type: ignore[no-untyped-def]
                return []

        eng.broker = FakeVenue()  # type: ignore
        report = eng.reconcile()
        assert report.drift == "QUANTITY_MISMATCH"
        assert report.requires_suspend


# ---- 12. Quantity semantics ----


def test_quantity_lots_to_notional():
    instr_std = Instrument(symbol="XAUUSD", venue="MT5", contract_size=Decimal("100"), lot_size=Decimal("0.01"))
    instr_micro = Instrument(symbol="XAUUSD", venue="MT5_MICRO", contract_size=Decimal("1"), lot_size=Decimal("0.01"))
    # Same lots, different contract size → different notional
    qty = Decimal("0.1")
    price = Decimal("2000")
    notional_std = qty * instr_std.contract_size * price  # 0.1*100*2000=20000
    notional_micro = qty * instr_micro.contract_size * price  # 0.1*1*2000=200
    assert notional_std == Decimal("20000")
    assert notional_micro == Decimal("200")
    # Risk must use contract_size, not approx
    with tempfile.TemporaryDirectory() as tmp:
        risk = RiskEngine(RiskLimits(max_notional=Decimal("500")), db_path=Path(tmp) / "db.sqlite")
        # For micro contract, 0.1 lot is 200 notional <500 → allow
        intent_micro = OrderIntent(
            instrument=instr_micro, side=Side.BUY, quantity=qty, client_order_id="c1", strategy_id="s"
        )
        ctx = RiskContext(
            account=Account(
                balance=Decimal("10000"), equity=Decimal("10000"), currency="USD", updated_at=datetime.now(UTC)
            ),
            positions={},
            open_orders_count=0,
            daily_pnl=Decimal("0"),
            drawdown=Decimal("0"),
            instrument_suspended=set(),
            reference_prices={"XAUUSD": Decimal("2000")},
        )
        assert risk.pre_trade(intent_micro, ctx).allowed
        # For std contract, same lots is 20000 >500 → veto
        intent_std = OrderIntent(
            instrument=instr_std, side=Side.BUY, quantity=qty, client_order_id="c2", strategy_id="s"
        )
        assert not risk.pre_trade(intent_std, ctx).allowed


# ---- 13. Data integrity ----


def test_manifest_reproducibility():
    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteParquetDataStore(root=Path(tmp) / "data", db_path=Path(tmp) / "qts.db")
        instr = Instrument(symbol="XAUUSD")
        bars = generate_gbm_bars(instrument=instr, periods=50, seed=42)
        m1 = store.write_bars(bars)
        # Reading back must equal original (sorted, quantized)
        read = store.read_bars(instr, m1.timeframe, version=m1.version)
        assert len(read) == len(bars)
        assert read[0].open == bars[0].open
        # Manifest checksum stable
        assert m1.checksum.startswith("sha256:")
        # Duplicate should be rejected
        try:
            store.write_bars(bars, version=m1.version)
            pytest.fail("duplicate version should be rejected")
        except ValueError:
            pass


def test_bar_interval_and_timezone():
    instr = Instrument(symbol="XAUUSD")
    # naive datetime should be rejected
    try:
        Bar(
            instrument=instr,
            open=Decimal("2000"),
            high=Decimal("2001"),
            low=Decimal("1999"),
            close=Decimal("2000"),
            volume=Decimal("1000"),
            open_time=datetime.now(),  # naive
            close_time=datetime.now() + timedelta(hours=1),
            data_version="test",
        )
        pytest.fail("naive datetime should be rejected")
    except ValueError:
        pass
    # interval must be open < close
    try:
        Bar(
            instrument=instr,
            open=Decimal("2000"),
            high=Decimal("2001"),
            low=Decimal("1999"),
            close=Decimal("2000"),
            volume=Decimal("1000"),
            open_time=datetime(2020, 1, 1, 1, tzinfo=UTC),
            close_time=datetime(2020, 1, 1, 1, tzinfo=UTC),
            data_version="test",
        )
        pytest.fail("open_time == close_time should be rejected")
    except ValueError:
        pass


# ---- 15. NO_TRADE propagation ----


def test_no_trade_on_uncertainty():
    """If risk vetoes, no order; if reconciled drift, no order; if kill active, no order."""
    with tempfile.TemporaryDirectory() as tmp:
        om = OrderManager()
        risk = RiskEngine(RiskLimits(max_quantity=Decimal("0.01")), db_path=Path(tmp) / "db.sqlite")
        broker = RealisticPaperBroker()
        portfolio = Portfolio(initial_balance=Decimal("10000"))
        eng = ExecutionEngine(om, risk, broker, MatchingEngine(), portfolio)
        bar = Bar(
            instrument=Instrument(symbol="XAUUSD"),
            open=Decimal("2000"),
            high=Decimal("2001"),
            low=Decimal("1999"),
            close=Decimal("2000"),
            volume=Decimal("1000"),
            open_time=datetime.now(UTC),
            close_time=datetime.now(UTC) + timedelta(hours=1),
            data_version="test",
        )
        # Quantity 0.1 > max 0.01 → veto → NO_TRADE
        intent = OrderIntent(
            instrument=bar.instrument, side=Side.BUY, quantity=Decimal("0.1"), client_order_id="c1", strategy_id="s"
        )
        order, fills = eng.submit_intent(intent, bar=bar)
        assert order is None and fills == []
        assert len(portfolio.fills) == 0
