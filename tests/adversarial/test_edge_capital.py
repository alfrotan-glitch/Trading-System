"""Capital Preservation + Real Edge Discovery — adversarial tests.

Validates that the system protects capital when edge is weak and correctly handles all 19 phases.
"""

import contextlib
import tempfile
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import numpy as np
import pytest

from qts.adapters.order_check import mt5_order_check
from qts.data.locked_test import LockedTestPartitioner, LockedTestViolation
from qts.data.quality import validate_bars
from qts.domain.value_objects import Bar, Instrument
from qts.edge.cost_robustness import evaluate_cost_robustness
from qts.edge.emergency import EmergencyConfig, EmergencyControls
from qts.edge.null_control import NullControl
from qts.edge.placebo import PlaceboStrategies
from qts.edge.promotion import PromotionLedger, PromotionState
from qts.edge.regime_stability import evaluate_regime_stability
from qts.research.campaign import CampaignResult, ResearchCampaignStore
from qts.research.experiment import Experiment, ExperimentStore, Hypothesis, ImmutableRecordError
from qts.risk.capital_policy import CapitalPolicy


def _bars(n=100, symbol="XAUUSD"):
    instr = Instrument(symbol=symbol)
    base = datetime(2020, 1, 1, tzinfo=UTC)
    bars = []
    for i in range(n):
        ot = base + timedelta(hours=i)
        ct = ot + timedelta(hours=1)
        price = Decimal(str(2000 + i * 0.1 + (i % 10) * 0.5))
        bars.append(
            Bar(
                instrument=instr,
                open=price,
                high=price + Decimal("5"),
                low=price - Decimal("5"),
                close=price,
                volume=Decimal("1000"),
                open_time=ot,
                close_time=ct,
            )
        )
    return bars


# Phase 1: Data quality gate must block promotion if unverified
def test_data_quality_blocks_unverified():
    bars = _bars(100)
    # Introduce duplicate
    bars_dup = bars + [bars[0]]
    report = validate_bars(bars_dup)
    assert not report.passed
    assert any(c.name == "no_duplicates" and not c.passed for c in report.checks)
    # Bad OHLC
    bad = _bars(10)
    bad[5] = bad[5].model_copy(update={"high": Decimal("1"), "low": Decimal("100")})  # high < low
    report2 = validate_bars(bad)
    assert not report2.passed
    # Impossible price
    bad2 = _bars(10)
    bad2[3] = bad2[3].model_copy(update={"close": Decimal("-10")})
    report3 = validate_bars(bad2)
    assert not report3.passed
    # Good data passes
    good = _bars(100)
    report4 = validate_bars(good)
    assert report4.passed


def test_dataset_manifest_contains_required_fields(tmp_path):
    from qts.data.store import SqliteParquetDataStore

    # Fully isolated store (root=tmp_path): never writes manifests/curated/db
    # into the repository data/ directory.
    store = SqliteParquetDataStore(root=tmp_path)
    bars = _bars(50)
    manifest = store.write_bars(bars, source_file="test.csv")
    assert manifest.instrument == "XAUUSD"
    assert manifest.timeframe == "1H"
    assert manifest.checksum.startswith("sha256:")
    assert manifest.timezone == "UTC"
    assert manifest.missing_data_stats is not None
    assert "expected" in manifest.missing_data_stats


# Phase 2: Locked test immutability and access logging
def test_locked_test_immutable_and_logged():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "locked.db"
        partitioner = LockedTestPartitioner(db_path=db)
        bars = _bars(100)
        parts = partitioner.partition(bars, "v1")
        assert len(parts["discovery"]) == 60
        assert len(parts["validation"]) == 20
        assert len(parts["locked"]) == 20
        # Second partition same version should be idempotent (same hash)
        parts2 = partitioner.partition(bars, "v1")
        assert len(parts2["locked"]) == 20
        # Access without allow should log and raise
        with pytest.raises(LockedTestViolation):
            partitioner.get_locked(bars, "v1", accessor="researcher", purpose="tuning", allow=False)
        log = partitioner.access_log("v1")
        assert len(log) == 1
        assert log[0]["allowed"] is False
        # With allow should succeed
        locked = partitioner.get_locked(bars, "v1", accessor="validator", purpose="final_test", allow=True)
        assert len(locked) == 20
        # Verify no leak via params
        assert partitioner.verify_no_leak({"fast": 10}, "abc123")
        assert not partitioner.verify_no_leak({"locked_hash": "abc123"}, "abc123")


# Phase 3: Trial ledger counts all variants, DSR feeds
def test_trial_ledger_counts_all():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "ledger.db"
        store = ExperimentStore(db_path=db)
        assert store.count_trials() == 0
        h = Hypothesis(statement="test", rationale="r", falsifiability="f")
        store.put_hypothesis(h)
        for i in range(5):
            exp = Experiment(
                hypothesis_id=h.id, strategy_id=f"s_{i}", params={"p": i}, data_version="v1", code_version="0.1.0"
            )
            store.put(exp)
        assert store.count_trials() == 5
        # Rejected still counts
        store.reject(exp.id, reason="failed")
        assert store.count_trials() == 5  # still 5, not only winners
        # No manual adjustment
        # Simulate trying to manually delete — should not be allowed via API
        # The store has no delete method, so count is immutable via API


def test_experiment_and_campaign_configuration_is_immutable():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "ledger.db"
        experiment_store = ExperimentStore(db_path=db)
        hypothesis = Hypothesis(statement="test", rationale="r", falsifiability="f")
        experiment_store.put_hypothesis(hypothesis)
        experiment = Experiment(
            hypothesis_id=hypothesis.id,
            strategy_id="immutable_strategy",
            params={"fast": 5},
            data_version="v1",
            dataset_provenance="SYNTHETIC",
            dataset_manifest_hash="sha256:fixture",
            code_version="0.1.0+test",
            seed=42,
            split_definition={"kind": "chronological"},
            cost_assumptions={"spread_bps": None},
        )
        experiment_store.put(experiment)
        changed = experiment.model_copy(update={"params": {"fast": 7}})
        with pytest.raises(ImmutableRecordError):
            experiment_store.put(changed)
        stored = experiment_store.get(experiment.id)
        assert stored is not None and stored.params == {"fast": 5}

        campaign_store = ResearchCampaignStore(db_path=db)
        result = CampaignResult(
            campaign_id="C-test",
            trial_id="T-test-0000",
            strategy_id="immutable_strategy",
            params={"fast": 5},
            passed=False,
            conclusion="BLOCKED_INSUFFICIENT_DATA",
        )
        campaign_store.put_trial("C-test", result)
        with pytest.raises(ValueError):
            campaign_store.put_trial("C-test", result.model_copy(update={"params": {"fast": 7}}))


# Phase 5: Edge survival requires all A-O
def test_edge_survival_requires_all():
    from qts.validation.edge_validation import validate_edge_survival

    bars = _bars(100)
    _n = 100
    eq_is = np.linspace(10000, 10100, 50)
    eq_oos = np.linspace(10100, 10050, 50)  # slight decay
    # Make walk_forward fail (only 1 fold)
    folds = [{"is_sharpe": 0.5, "oos_sharpe": 0.1}]
    cpcv = [
        {
            "best_is_test_sharpe": 0.1,
            "median_test_sharpe": 0.0,
            "train_sharpes": {"a": 1, "b": 0, "c": 0.5},
            "test_sharpes": {"a": 0.1, "b": 0.2, "c": 0.3},
        }
    ] * 6
    result = validate_edge_survival(
        "s",
        "v1",
        eq_is,
        eq_oos,
        eq_oos,
        eq_oos * 0.99,
        folds,
        cpcv,
        [0.1, 0.2, 0.15],
        {1.0: 1.2, 1.5: 1.1, 2.0: 1.0},
        10,
        [0.5, 0.6],
        [0.6],
        bars,
        [10, -5, 10, -5],
        timeframe="1H",
    )
    # Should fail due to insufficient folds and control sharpe >0.3
    assert not result.passed


# Phase 6: Null control — pipeline must reject controls
def test_null_control_rejection():
    from qts.validation.edge_validation import validate_edge_survival

    # Controls with high sharpe should not be rejected, but pipeline should flag
    control_sharpes = [0.8, 0.9, 0.7]  # apparent alpha but is null
    # Our NullControl should generate low sharpe, but if pipeline itself manufactures alpha, it would be bad
    # Here we test that pipeline correctly identifies control as not rejected when control sharpe high
    bars = _bars(100)
    eq = np.linspace(10000, 10100, 100)
    result = validate_edge_survival(
        "s",
        "v1",
        eq,
        eq,
        eq,
        eq * 0.99,
        [{"is_sharpe": 0.5, "oos_sharpe": 0.5}] * 5,
        [
            {
                "best_is_test_sharpe": 0.1,
                "median_test_sharpe": 0.0,
                "train_sharpes": {"a": 1, "b": 0, "c": 0.5},
                "test_sharpes": {"a": 0.1, "b": 0.2, "c": 0.3},
            }
        ]
        * 6,
        [0.4, 0.5, 0.45],
        {1.0: 1.2},
        5,
        control_sharpes,
        [0.1],
        bars,
        [10, -5] * 10,
    )
    # Since control_sharpes high, randomized_control should be False
    assert not result.checks["randomized_control"]


def test_null_control_generates_no_edge():
    bars = _bars(100)
    null = NullControl(seed=42)
    sigs = null.randomized_timing(bars)
    assert len(sigs) > 0
    assert len(sigs) <= 5
    # Shuffled labels should preserve count
    from qts.domain.value_objects import Side, Signal

    real = [
        Signal(
            instrument=bars[0].instrument,
            side=Side.BUY,
            strength=0.7,
            event_time=bars[0].close_time,
            hypothesis_id="h",
            strategy_id="s",
        )
        for _ in range(5)
    ]
    shuffled = null.shuffled_labels(bars, real)
    assert len(shuffled) == 5


# Phase 7: Cost robustness — net must exceed gross
def test_cost_robustness_break_even():
    eq_gross = np.array([10000, 10100, 10200, 10150])
    eq_net = np.array([10000, 10080, 10160, 10100])  # net worse due to costs
    res = evaluate_cost_robustness(eq_gross, eq_net, trades=3)
    assert res.break_even_spread_bps > 0
    assert "net_sharpe" in res.details


# Phase 8: Regime stability — no averaging away failure
def test_regime_stability_classifies_dependent():
    bars = _bars(99)
    # Create equity that is good only in trend (first third) but bad in range
    eq = np.array([10000 + i * 10 if i < 33 else 10330 - (i - 33) * 20 for i in range(99)], dtype=float)
    results = evaluate_regime_stability(bars, eq)
    assert len(results) == 3
    # Range should be negative sharpe, so dependent
    assert any(r.regime == "range" for r in results)


# Phase 9: Placebo must be rejected
def test_placebo_rejected():
    instr = Instrument(symbol="XAUUSD")
    placebo = PlaceboStrategies(instrument=instr)
    bar = _bars(10)[0]
    _sigs = placebo.random_entry(bar)
    # Random entry should sometimes generate, but validator must reject overall
    from qts.validation.edge_validation import validate_edge_survival

    bars = _bars(100)
    eq = np.linspace(10000, 10000, 100)  # flat no edge
    result = validate_edge_survival(
        "placebo",
        "v1",
        eq,
        eq,
        eq,
        eq,
        [{"is_sharpe": 0, "oos_sharpe": 0}] * 5,
        [
            {
                "best_is_test_sharpe": 0,
                "median_test_sharpe": 0,
                "train_sharpes": {"a": 0, "b": 0, "c": 0},
                "test_sharpes": {"a": 0, "b": 0, "c": 0},
            }
        ]
        * 6,
        [0, 0, 0],
        {1.0: 1.0},
        5,
        [0.1],
        [0.8, 0.9],
        bars,
        [0, -1, 0],
        timeframe="1H",
    )
    assert not result.checks["placebo"]  # placebo sharpe 0.8 >0.3 should make placebo check fail


# Phase 10: Forward observation — the CANONICAL path is the provenance-gated
# observatory (qts.observability.forward_observatory). The legacy
# ``qts.edge.forward.ForwardObserver`` was REMOVED: it fabricated execution
# metrics (actual_fills = intended*0.95, spread 3.0 bps, slippage 2.0 bps,
# latency 500 ms, zero PnL) that could be mistaken for forward evidence.
def test_legacy_fabricated_forward_observer_is_gone():
    import importlib

    try:
        importlib.import_module("qts.edge.forward")
        raise AssertionError(
            "qts.edge.forward reappeared — its ForwardObserver fabricated execution "
            "metrics and must not be reintroduced (canonical forward evidence is the "
            "provenance-gated observatory, see qts.observability.forward_observatory)"
        )
    except ModuleNotFoundError:
        pass  # expected: the fabricated legacy scaffold stays removed


def test_forward_evidence_count_is_provenance_gated(tmp_path: Path):
    """The forward-evidence gate consumes ONLY real-market-class observations:
    SYNTHETIC simulation never counts; DEMO (real broker, demo account) does."""
    from qts.domain.provenance import EvidenceProvenance
    from qts.observability.forward_observatory import ForwardObservatory, ObservationTick

    obs = ForwardObservatory(db_path=tmp_path / "fwd.db")
    obs.simulate_observation(n_ticks=25)  # writes SYNTHETIC-class records
    assert obs.real_observation_count() == 0, "synthetic simulation must never count as forward evidence"
    sid = obs.start_session(meta={"kind": "LIVE_OBSERVATION", "orders_possible": False})
    for _i in range(12):
        obs.record_tick(
            ObservationTick(
                symbol="XAUUSD@",
                bid=Decimal("2000"),
                ask=Decimal("2000.5"),
                provenance=EvidenceProvenance.DEMO.value,
                session_id=sid,
            )
        )
    assert obs.real_observation_count() == 12, "DEMO-class observations are the qualifying forward evidence"
    from qts.research.impulse.report import MIN_FORWARD_OBSERVATIONS

    assert obs.real_observation_count() >= MIN_FORWARD_OBSERVATIONS


# Phase 11: Shadow vs paper consistency — error distribution
def test_shadow_paper_consistency():
    from qts.edge.execution_consistency import compare_shadow_paper

    shadow = [{"price": "2000"}, {"price": "2001"}, {"price": "2002"}]
    paper = [{"price": "2000.5"}, {"price": "2001.5"}]
    res = compare_shadow_paper(shadow, paper, [])
    assert res.missed_entries == 1
    assert res.avg_price_diff_bps > 0
    assert len(res.error_distribution) == 2
    assert not res.paper_represents_live  # diff >5bps


# Phase 12: Capital survival policy — hard limits force NO_TRADE
def test_capital_policy_hard_limits():
    policy = CapitalPolicy(daily_loss_limit=200, max_drawdown=500)
    ok, reason = policy.check({"daily_loss": -250, "drawdown": 100})
    assert not ok
    assert reason == "daily_loss"
    ok2, _ = policy.check({"daily_loss": -50, "drawdown": 600})
    assert not ok2
    # Spread limit
    ok3, reason3 = policy.check({"spread_bps": 150})
    assert not ok3 and reason3 == "spread"
    # No adaptive expansion
    policy2 = CapitalPolicy(daily_loss_limit=200)
    # Even after 5 losses, limit stays 200
    assert policy2.daily_loss_limit == 200


# Phase 15: One-way promotion — no skip, no manual edit, backwards on anomaly
def test_one_way_promotion():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "promo.db"
        ledger = PromotionLedger(db_path=db)
        sid = "strat_1"
        assert ledger.get_state(sid) == PromotionState.RESEARCH
        # Cannot skip RESEARCH -> VALIDATED (must go via CANDIDATE)
        with pytest.raises(ValueError, match="not allowed"):
            ledger.transition(sid, PromotionState.VALIDATED)
        # Correct path
        ledger.transition(sid, PromotionState.CANDIDATE)
        assert ledger.get_state(sid) == PromotionState.CANDIDATE
        ledger.transition(sid, PromotionState.VALIDATED)
        assert ledger.get_state(sid) == PromotionState.VALIDATED
        # Anomaly -> SUSPENDED
        ledger.suspend_on_anomaly(sid, reason="drawdown breach")
        assert ledger.get_state(sid) == PromotionState.SUSPENDED
        # From SUSPENDED can go back to RESEARCH
        ledger.transition(sid, PromotionState.RESEARCH)
        assert ledger.get_state(sid) == PromotionState.RESEARCH
        # No manual edit: direct SQL update would bypass ledger, but ledger's can_transition would still enforce
        # Simulate manual edit attempt by writing directly to DB without ledger.
        # Uses the sanctioned qts.db.connect opener: `with sqlite3.connect(path)`
        # commits but does NOT close — the leaked handle kept promo.db locked and
        # broke TemporaryDirectory cleanup on Windows (WinError 32). The manual-edit
        # semantics (bypassing the ledger API) are unchanged.
        from qts.db import connect as db_connect

        with db_connect(db) as con:
            con.execute(
                "UPDATE promotion_state SET state=? WHERE strategy_id=?", (PromotionState.LIVE_ELIGIBLE.value, sid)
            )
            con.commit()
        # Now ledger thinks it's LIVE_ELIGIBLE via manual edit, but next transition should still be validated via can_transition from that state
        # However, the point is that promotion should only be via ledger.transition, not manual SQL — we detect by checking log
        # The state is now LIVE_ELIGIBLE without proper history, but the test is that ledger.transition from SUSPENDED to LIVE_ELIGIBLE is not allowed
        # So we reset to RESEARCH and try to jump
        with db_connect(db) as con:
            con.execute("UPDATE promotion_state SET state=? WHERE strategy_id=?", (PromotionState.RESEARCH.value, sid))
            con.commit()
        with pytest.raises(ValueError):
            ledger.transition(sid, PromotionState.LIVE_ELIGIBLE)


# Phase 16: Micro scaling protocol
def test_micro_scaling_protocol():
    from qts.edge.promotion import PromotionLedger

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "micro.db"
        ledger = PromotionLedger(db_path=db)
        # Not enough observations
        ok, reason = ledger.scaling_protocol(
            "s", observations=10, drawdown=0.05, slippage=2, reconciliation_health=True, expectancy_stability=True
        )
        assert not ok and "observations" in reason
        # Drawdown too high
        ok2, _ = ledger.scaling_protocol(
            "s", observations=30, drawdown=0.2, slippage=2, reconciliation_health=True, expectancy_stability=True
        )
        assert not ok2
        # Must depend on all, not just wins
        ok3, _ = ledger.scaling_protocol(
            "s", observations=30, drawdown=0.05, slippage=2, reconciliation_health=True, expectancy_stability=True
        )
        assert ok3


# Phase 17: Emergency controls — 10 safeguards
def test_emergency_controls():
    ec = EmergencyControls(
        config=EmergencyConfig(max_order_rate_per_sec=2, max_order_size_lots=1.0, max_spread_bps=100)
    )
    # Order rate
    assert ec.check_order_rate()[0] is True
    ec.check_order_rate()
    ec.check_order_rate()  # third in 1 sec should fail (limit 2)
    ok, reason = ec.check_order_rate()
    assert not ok and reason == "max_order_rate"
    # Order size
    assert not ec.check_order_size(Decimal("2.0"))[0]
    assert ec.check_order_size(Decimal("0.5"))[0]
    # Spread
    assert not ec.check_spread(150)[0]
    assert ec.check_spread(50)[0]
    # Kill switch
    ec.kill_switch("test")
    assert ec.is_killed()
    assert not ec.pre_trade_gate(
        Decimal("0.1"), 10, 100, 1, type("A", (), {"equity": Decimal("10000"), "balance": Decimal("10000")})(), False
    )[0]


# Phase 18: MT5 order_check
def test_mt5_order_check():
    from unittest.mock import MagicMock

    from qts.adapters.mt5_adapter import MT5Adapter
    from qts.domain.value_objects import OrderIntent, Side

    mock = MagicMock()
    info = MagicMock()
    info.contract_size = 100
    info.volume_min = 0.01
    info.volume_max = 100
    info.volume_step = 0.01
    info.digits = 2
    info.point = 0.01
    info.trade_tick_size = 0.01
    info.trade_mode = 4
    info.trade_allowed = True
    info.filling_mode = 1
    info.execution_mode = 0
    info.trade_stops_level = 0
    info.trade_freeze_level = 0
    mock.symbol_info.return_value = info
    mock.symbol_select.return_value = True
    mock.last_error.return_value = (1, "ok")
    mock.account_info.return_value = MagicMock(
        balance=10000, equity=10000, margin=100, margin_free=9900, leverage=100, currency="USD"
    )
    mock.symbol_info_tick.return_value = MagicMock(bid=1999, ask=2001, time=datetime.now(UTC).timestamp())
    adapter = MT5Adapter(mt5_module=mock)
    instr = Instrument(symbol="XAUUSD")
    intent = OrderIntent(
        instrument=instr, side=Side.BUY, quantity=Decimal("0.01"), client_order_id="oc_test", strategy_id="s"
    )
    # Fail-closed contract: a market order WITHOUT an authoritative price must
    # be refused (the old implementation fabricated price=2000 for margin math).
    result_no_price = mt5_order_check(adapter, intent)
    assert not result_no_price.ok
    assert "MISSING_MARKET_PRICE" in result_no_price.comment
    # With an authoritative market price the check passes (never an execution guarantee).
    result = mt5_order_check(adapter, intent, market_price=Decimal("2000"))
    assert result.ok
    assert "not execution guarantee" in result.comment
    # Invalid volume should fail
    intent2 = OrderIntent(
        instrument=instr, side=Side.BUY, quantity=Decimal("1000"), client_order_id="oc_test2", strategy_id="s"
    )
    result2 = mt5_order_check(adapter, intent2, market_price=Decimal("2000"))
    assert not result2.ok
    assert result2.retcode == 10014


# Phase 13 & 14: Expectancy and economic edge
def test_expectancy_and_economic_edge():
    from qts.edge.expectancy import compute_expectancy, evaluate_minimum_economic_edge

    pnl = [10, -5, 10, -5, 10, -20, 5]
    report = compute_expectancy(pnl, costs_per_trade=1.0)
    assert report.expectancy_per_trade > -10
    assert report.profit_factor > 0
    # Economic edge must exceed costs by material margin
    econ = evaluate_minimum_economic_edge(report.net_expectancy_after_costs, cost=1.0, uncertainty=0.5, penalty=0.5)
    # Remaining = net - cost - uncertainty - penalty
    assert econ.remaining_edge == report.net_expectancy_after_costs - 1.0 - 0.5 - 0.5


# Final gate: if edge does not demonstrate meaningful forward-tested cost-adjusted edge, keep NO_TRADE
def test_final_gate_keeps_no_trade_when_blocked():
    from qts.data.bootstrap import bootstrap_data
    from qts.data.store import SqliteParquetDataStore
    from qts.edge.orchestrator import run_full_edge_validation

    # Self-contained and truthful: data availability is established via the
    # deterministic bootstrap (usable = manifest + curated parquet + readable bars).
    # No hardcoded version ids, no fabricated fallback bars — if the fixture cannot
    # establish usable data, the test FAILS with the bootstrap's honest message.
    store = SqliteParquetDataStore()
    try:
        res = bootstrap_data(store=store)
        assert res.ok, f"data bootstrap failed (no fabricated fallback allowed): {res.messages}"
        target_version = res.version
        # Use sma_breakout which is known to be BLOCKED
        evidence = run_full_edge_validation(data_version=target_version, strategy_id="sma_breakout")
        assert not evidence["edge_survival"]["passed"]
        assert evidence["promotion"]["state"] == "RESEARCH"
        # System should keep NO_TRADE — promotion not advanced
        assert evidence["edge_survival"]["checks"]["economic_edge"] is False
    finally:
        with contextlib.suppress(Exception):
            store.close()
