"""Architecture audit regressions: one execution authority, one strategy authority.

Each test pins a defect that was real in this tree and is now fixed.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from qts.domain.value_objects import Account, OrderIntent, OrderState, Side

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src" / "qts"


# ------------------------------------------- broker outcome classification
def _engine_with(broker_exc: Exception):
    """An engine whose broker raises `broker_exc` from submit()."""
    from qts.adapters.base import BrokerAdapter
    from tests.adversarial.test_mt5_boundary import _make_engine  # reuse the canonical harness

    class _Raiser(BrokerAdapter):
        is_live = True

        def submit(self, intent):
            raise broker_exc

        def account(self):
            return Account(
                balance=Decimal("10000"), equity=Decimal("10000"), currency="USD", updated_at=datetime.now(UTC)
            )

    return _make_engine(broker=_Raiser())


def _submit(engine, coid: str):
    from tests.adversarial.test_mt5_boundary import _bar

    bar = _bar()
    intent = OrderIntent(
        instrument=bar.instrument,
        side=Side.BUY,
        quantity=Decimal("0.01"),
        client_order_id=coid,
        strategy_id="s",
    )
    engine.submit_intent(intent, bar=bar)
    return engine.om.get(coid).state


def test_an_unrecognised_broker_exception_fails_closed_as_ambiguous() -> None:
    """DEFECT: the text fallback defaulted to REJECTED — fail OPEN.

    An adapter failure whose message matched none of the keywords was recorded
    as a definitive rejection, so the system carried on as though the order
    could not exist, while the broker might have been holding it. That is the
    duplicate-order hazard qts.adapters.broker_outcome exists to prevent.
    """
    eng, _, _, _ = _engine_with(RuntimeError("venue returned an unmapped status 9917"))
    state = _submit(eng, "unrecognised-1")

    assert state == OrderState.AMBIGUOUS, "an unrecognised broker failure must never be assumed rejected"
    assert eng.is_suspended, "an unknown outcome must fail closed"


def test_a_pre_send_validation_error_is_not_ambiguous_even_if_its_cause_mentions_connection() -> None:
    """DEFECT: the text fallback matched the interpolated cause.

    mt5_adapter raises `ValueError(f"tick unavailable for {sym} ... : {exc}")`
    BEFORE order_send. When the interpolated cause mentioned a connection, the
    keyword scan turned a request that was provably never transmitted into a
    durable reconciliation suspension.
    """
    eng, _, _, _ = _engine_with(ValueError("tick unavailable for XAUUSD — stop distance not verifiable: connection reset"))
    state = _submit(eng, "presend-1")

    assert state == OrderState.REJECTED, "a request refused before transmission is definitive"
    assert not eng.is_suspended, "nothing was transmitted, so nothing needs reconciling"


def test_the_typed_contract_still_holds_in_both_directions() -> None:
    from qts.adapters.broker_outcome import BrokerOutcomeUnknown, BrokerRequestRejected

    eng_r, _, _, _ = _engine_with(BrokerRequestRejected("contract violation — refusing to send"))
    assert _submit(eng_r, "typed-rejected") == OrderState.REJECTED
    assert not eng_r.is_suspended

    eng_u, _, _, _ = _engine_with(BrokerOutcomeUnknown("send failed, outcome unknown"))
    assert _submit(eng_u, "typed-unknown") == OrderState.AMBIGUOUS
    assert eng_u.is_suspended


def test_no_text_matching_classifier_remains_in_the_engine() -> None:
    source = (SRC / "execution" / "engine.py").read_text(encoding="utf-8")
    body = "\n".join(ln for ln in source.splitlines() if not ln.lstrip().startswith("#"))
    for keyword_scan in ('"timeout", "connection"', '"ambiguous", "unknown"', "err_msg"):
        assert keyword_scan not in body, f"the text heuristic is back: {keyword_scan}"


# ----------------------------------------------------- strategy authority
def _tiny_dataset(tmp: Path):
    """Ten deterministic bars in an isolated store — enough to run a backtest."""
    from datetime import timedelta

    from qts.data.store import SqliteParquetDataStore
    from qts.domain.value_objects import Bar, Instrument

    store = SqliteParquetDataStore(root=tmp / "data", db_path=tmp / "qts.db")
    instr = Instrument(symbol="XAUUSD")
    base = datetime(2020, 1, 1, tzinfo=UTC)
    bars = [
        Bar(
            instrument=instr,
            open=Decimal(str(2000 + i * 10)),
            high=Decimal(str(2000 + i * 10 + 6)),
            low=Decimal(str(2000 + i * 10 - 1)),
            close=Decimal(str(2000 + i * 10 + 5)),
            volume=Decimal("1000"),
            open_time=base + timedelta(hours=i),
            close_time=base + timedelta(hours=i + 1),
            data_version="test",
        )
        for i in range(10)
    ]
    manifest = store.write_bars(bars)
    return store, instr, manifest


def test_an_unknown_strategy_id_is_refused_not_silently_substituted(tmp_path: Path) -> None:
    """DEFECT: unknown ids were backtested as SMA breakout under the requested id.

    The run produced a complete, plausible result set attributed to a strategy
    whose logic never executed — evidence of something that did not happen.
    Behavioural, not a source scan: run the real backtest and demand a refusal.
    """
    from qts.adapters.matching import MatchingConfig
    from qts.backtest.engine import BacktestEngine

    store, instr, manifest = _tiny_dataset(tmp_path)
    engine = BacktestEngine(store, matching_config=MatchingConfig(spread_bps=0, slippage_bps=0, commission_per_lot=0))

    with pytest.raises(ValueError, match="unknown strategy_id"):
        engine.run(
            instr,
            manifest.timeframe,
            manifest.version,
            strategy_id="totally_unregistered_xyz",
            strategy_params={"quantity": 0.1},
        )


def test_a_known_strategy_still_backtests_normally(tmp_path: Path) -> None:
    """The refusal must not have broken legitimate runs."""
    from qts.adapters.matching import MatchingConfig
    from qts.backtest.engine import BacktestEngine

    store, instr, manifest = _tiny_dataset(tmp_path)
    engine = BacktestEngine(store, matching_config=MatchingConfig(spread_bps=0, slippage_bps=0, commission_per_lot=0))

    result = engine.run(
        instr,
        manifest.timeframe,
        manifest.version,
        strategy_id="sma_breakout",
        strategy_params={"fast": 2, "slow": 3, "quantity": 0.1},
    )
    assert result is not None


def test_execution_never_imports_a_research_strategy_prototype() -> None:
    """The execution path answers to the registry, never to a research prototype."""
    offenders: list[str] = []
    for module in sorted((SRC / "execution").glob("*.py")):
        text = module.read_text(encoding="utf-8")
        for banned in ("qts.research.strategy", "qts.research.strategies", "SmaBreakoutStrategy"):
            if banned in text:
                offenders.append(f"{module.name} imports {banned}")
    assert offenders == [], (
        "execution must resolve strategies through the forward-validation registry "
        f"(qts.lifecycle.demo_registry), not a research prototype: {offenders}"
    )


def test_research_strategy_modules_declare_their_quarantine() -> None:
    for rel in ("research/strategy.py", "research/strategies.py"):
        doc = ast.get_docstring(ast.parse((SRC / rel).read_text(encoding="utf-8"))) or ""
        assert "not an execution authority" in doc, f"{rel} does not declare its quarantine"
        assert "demo_registry" in doc, f"{rel} does not name the canonical authority"


# ------------------------------------------------------------- dead code
def test_the_legacy_lot_sizing_helper_is_gone() -> None:
    """DEFECT: `lots_to_mt5_volume` claimed to delegate to validate_and_normalize
    but duplicated the quantization inline, and had zero callers."""
    source = (SRC / "adapters" / "mt5_adapter.py").read_text(encoding="utf-8")
    assert "lots_to_mt5_volume" not in source


def test_no_second_freshness_authority_survives_on_the_market_data_adapter() -> None:
    """DEFECT: a dead `is_fresh()` judged freshness on local receipt wall-clock.

    The canonical answer is evaluate_tick_epoch_freshness, which judges on the
    broker's server-clock basis. A second, weaker answer sitting unused on the
    adapter is a trap for the next caller.
    """
    source = (SRC / "adapters" / "market_data.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "is_fresh" not in names
    assert "self._last_valid" not in source, "orphaned freshness bookkeeping remains"

    gate = (SRC / "lifecycle" / "demo_gate.py").read_text(encoding="utf-8")
    assert "def evaluate_tick_epoch_freshness" in gate, "the canonical freshness authority must still exist"


@pytest.mark.parametrize("module", ["qts.adapters.market_data", "qts.adapters.mt5_adapter"])
def test_trimmed_modules_still_import(module: str) -> None:
    __import__(module)
