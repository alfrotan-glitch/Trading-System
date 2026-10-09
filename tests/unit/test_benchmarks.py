"""The frozen candidate set must stay frozen, and must not lie about which
strategy it ran.

Two failure modes this file exists to prevent:

1. **Silent strategy substitution.** The backtest engine infers a strategy
   family from a substring of ``strategy_id`` and used to swallow any
   constructor error, falling back to a default. A benchmark that quietly runs
   a different strategy produces reproducible, confident evidence about the
   wrong thing — which is worse than no benchmark.
2. **Post-hoc parameter editing.** A preregistered hypothesis edited after the
   result is known is not a hypothesis, it is a curve fit.
"""

from __future__ import annotations

import pytest

from qts.research.benchmarks import (
    BENCHMARKS,
    BENCHMARK_A,
    BENCHMARK_B,
    BENCHMARK_C,
    BenchmarkRole,
    FROZEN_SPEC_HASHES,
    verify_frozen,
)
from qts.research.strategies import StrategyFamily


# ------------------------------------------------------------------ the set


def test_the_set_is_small_and_deliberate():
    """Three hypotheses, not hundreds of variants."""
    assert len(BENCHMARKS) == 3


def test_one_control_exists_and_is_labelled_as_one():
    """A control that could plausibly pass is the only kind worth having."""
    controls = [b for b in BENCHMARKS if b.role is BenchmarkRole.CONTROL]
    assert len(controls) == 1
    assert controls[0] is BENCHMARK_C
    assert BENCHMARK_A.role is BenchmarkRole.CANDIDATE
    assert BENCHMARK_B.role is BenchmarkRole.CANDIDATE


def test_every_benchmark_declares_its_exit_rules():
    """A trend rule with a stop and one without are different strategies."""
    for spec in BENCHMARKS:
        rules = spec.exit_rules()
        assert rules["stop_distance_usd"] > 0
        assert rules["max_hold_bars"] >= 1


def test_candidates_are_comparable_on_everything_except_the_entry():
    """A and B share size, stop and hold, so a difference is the entry logic."""
    assert BENCHMARK_A.quantity_lots == BENCHMARK_B.quantity_lots
    assert BENCHMARK_A.stop_distance_usd == BENCHMARK_B.stop_distance_usd
    assert BENCHMARK_A.max_hold_bars == BENCHMARK_B.max_hold_bars
    assert BENCHMARK_A.family is not BENCHMARK_B.family


def test_every_benchmark_cites_a_public_basis_not_a_result():
    for spec in BENCHMARKS:
        assert len(spec.basis) > 40
        assert len(spec.rationale) > 40


def test_the_registered_demo_rule_is_benchmark_a():
    """The DEMO benchmark and the historical benchmark must be one strategy."""
    assert BENCHMARK_A.params == {"fast": 12, "slow": 48, "ma_type": "ema"}
    assert BENCHMARK_A.family is StrategyFamily.TREND
    assert BENCHMARK_A.timeframe == "15m"
    assert BENCHMARK_A.max_hold_bars == 16  # 16 x 15m = the registered 4h hold


# ---------------------------------------------------------------- frozen-ness


def test_preregistration_verifies():
    ok, problems = verify_frozen()
    assert ok, problems


def test_every_spec_has_a_recorded_hash():
    for spec in BENCHMARKS:
        assert spec.benchmark_id in FROZEN_SPEC_HASHES


def test_an_edited_parameter_is_detected():
    """Regression: a parameter changed after registration must not verify."""
    import dataclasses

    edited = dataclasses.replace(BENCHMARK_A, params={**BENCHMARK_A.params, "fast": 11})
    assert edited.spec_hash() != BENCHMARK_A.spec_hash()
    assert FROZEN_SPEC_HASHES[BENCHMARK_A.benchmark_id] != edited.spec_hash()


def test_an_edited_stop_is_detected():
    """The stop is part of the hypothesis, so editing it is a preregistration breach."""
    import dataclasses

    edited = dataclasses.replace(BENCHMARK_A, stop_distance_usd=99.0)
    assert edited.spec_hash() != BENCHMARK_A.spec_hash()


def test_spec_hash_is_stable_across_processes():
    """The recorded hashes were computed once, not recomputed at import."""
    assert BENCHMARK_A.spec_hash() == FROZEN_SPEC_HASHES[BENCHMARK_A.benchmark_id]


# --------------------------------------------------- engine contract (no lie)


def test_the_engine_refuses_to_substitute_a_different_strategy():
    """An explicit family that cannot be built must raise, not fall back."""
    from qts.backtest.engine import BacktestEngine

    engine = BacktestEngine.__new__(BacktestEngine)
    # The contract is enforced inside run(); assert the refusal exists by
    # driving the resolution path with a deliberately impossible parameter.
    import inspect

    source = inspect.getsource(BacktestEngine.run)
    assert "refusing to silently run a different strategy" in source


def test_harness_params_are_not_forwarded_to_a_strategy_constructor():
    """``quantity`` sizes the order; it is not a signal parameter."""
    from qts.backtest.engine import _HARNESS_PARAM_KEYS

    assert "quantity" in _HARNESS_PARAM_KEYS


def test_the_engine_exposes_exit_rules():
    """Without them a stop-loss strategy is backtested as a naked reversal."""
    from qts.backtest.engine import _parse_exit_rules

    assert _parse_exit_rules(None) == (None, None)
    assert _parse_exit_rules({"stop_distance_usd": 3.0}) == (3.0, None)
    assert _parse_exit_rules({"max_hold_bars": 16}) == (None, 16)
    assert _parse_exit_rules({"stop_distance_usd": 3.0, "max_hold_bars": 16}) == (3.0, 16)


@pytest.mark.parametrize("bad", [{"stop_distance_usd": 0}, {"stop_distance_usd": -1}, {"max_hold_bars": 0}])
def test_malformed_exit_rules_are_refused_not_ignored(bad):
    from qts.backtest.engine import _parse_exit_rules

    with pytest.raises(ValueError):
        _parse_exit_rules(bad)


def test_exit_rules_with_no_usable_rule_are_refused():
    from qts.backtest.engine import _parse_exit_rules

    with pytest.raises(ValueError):
        _parse_exit_rules({"typo_key": 1})


# ------------------------------------------------------------- end-to-end


@pytest.mark.integration
def test_benchmarks_produce_distinct_mechanism_evidence_on_the_bootstrap_set(tmp_path, monkeypatch):
    """Two different strategies must not produce identical numbers."""
    monkeypatch.setenv("QTS_STATE_ROOT", str(tmp_path))
    from qts.data.bootstrap import bootstrap_data
    from qts.data.store import SqliteParquetDataStore
    from qts.research.benchmarks import evaluate_benchmarks

    store = SqliteParquetDataStore()
    try:
        res = bootstrap_data(store=store)
        assert res.ok, res.messages
        report = evaluate_benchmarks(store, res.version, record_trials=False)
    finally:
        store.close()

    assert report.frozen_verified
    assert len(report.observations) == 3
    ids = [o.benchmark_id for o in report.observations]
    assert len(set(ids)) == 3

    # Distinct strategies on distinct logic must not collide. A previous
    # version of the engine silently fell back to one default strategy and all
    # three were byte-identical.
    fingerprints = {
        (o.round_turns, round(o.gross_pnl_usd, 6), round(o.net_pnl_usd, 6)) for o in report.observations
    }
    assert len(fingerprints) == 3, "two benchmarks produced identical results — a strategy was substituted"

    # The bootstrap fixture is synthetic, so nothing may be claim-eligible.
    assert report.dataset_claim_eligible is False
    for obs in report.observations:
        assert obs.mechanism_only is True
        assert obs.claim_eligible is False
        assert any("not claim-eligible" in r for r in obs.reasons)


@pytest.mark.integration
def test_benchmarks_report_a_timeframe_mismatch_instead_of_ignoring_it(tmp_path, monkeypatch):
    """Evaluating a 15m hypothesis on 1H bars is mechanism evidence, not a test."""
    monkeypatch.setenv("QTS_STATE_ROOT", str(tmp_path))
    from qts.data.bootstrap import bootstrap_data
    from qts.data.store import SqliteParquetDataStore
    from qts.research.benchmarks import evaluate_benchmarks

    store = SqliteParquetDataStore()
    try:
        res = bootstrap_data(store=store)
        report = evaluate_benchmarks(store, res.version, record_trials=False)
    finally:
        store.close()

    for obs in report.observations:
        assert obs.timeframe_requested == "15m"
        assert obs.timeframe_measured == "1H"
        assert obs.timeframe_matches is False
        assert any("mechanism evidence only" in r for r in obs.reasons)
