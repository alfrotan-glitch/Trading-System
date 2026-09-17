"""Adversarial: fabrication must be IMPOSSIBLE in safety-critical paths.

Pins the audit findings as structural regressions:

* No fabricated account equity (``10000`` fallback) anywhere in src/.
* No fabricated broker metadata defaults in the MT5 adapter.
* A market order without an authoritative price can NEVER pass order_check.
* Risk vetoes on unknown equity (ACCOUNT_STATE_UNAVAILABLE).
* Comparison metrics are UNAVAILABLE, never placeholder zeros.
* Provenance: ambiguous records are UNVERIFIED, never REAL.
"""

from __future__ import annotations

import ast
import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

from qts.adapters.mt5_adapter import MT5Adapter
from qts.adapters.order_check import mt5_order_check
from qts.domain.provenance import EvidenceProvenance, MetricValue, classify_record_provenance
from qts.domain.value_objects import Instrument, OrderIntent, Side
from qts.execution.demo_comparison import compare_paper_shadow_demo
from qts.risk.engine import RiskContext, RiskEngine, RiskLimits, RiskVetoReason

SRC = Path(__file__).resolve().parents[2] / "src" / "qts"


def _src_files():
    return list(SRC.rglob("*.py"))


# ---------------------------------------------------------------------------
# Structural: fabricated fallbacks must not reappear
# ---------------------------------------------------------------------------


def test_no_fabricated_equity_fallback_in_source():
    """The old `equity = ... else Decimal("10000")` fallback is banned."""
    offenders: list[str] = []
    for f in _src_files():
        text = f.read_text(encoding="utf-8")
        if "else Decimal(" in text and '"10000"' in text and "risk" in str(f).lower():
            # flag only the fabrication pattern: assigning 10000 in a fallback branch
            for line in text.splitlines():
                if "else" in line and 'Decimal("10000")' in line:
                    offenders.append(f"{f}:{line.strip()}")
    assert offenders == [], f"fabricated equity fallbacks reappeared: {offenders}"


def test_broker_adapter_account_default_is_fail_closed():
    """BrokerAdapter.account() must NOT return a fabricated account."""
    from qts.execution.engine import BrokerAdapter

    try:
        BrokerAdapter().account()
    except NotImplementedError:
        return
    raise AssertionError("BrokerAdapter.account() returned a fabricated account instead of failing closed")


def test_mt5_adapter_source_has_no_metadata_defaults():
    """AST-level: no getattr(spec_field, numeric_default) in the MT5 adapter.

    Docstrings may describe history; executable code must not fabricate.
    """
    text = (SRC / "adapters" / "mt5_adapter.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    #: Broker metadata fields that must NEVER carry a literal default — a
    #: default here would fabricate contract geometry, permissions, or capital.
    #: (Enum lookups like getattr(mt5, "ORDER_FILLING_IOC", 1) and neutral
    #: position-field reads are deliberately NOT in this set.)
    BANNED_FIELDS = {
        "trade_contract_size",
        "contract_size",
        "volume_min",
        "volume_max",
        "volume_step",
        "digits",
        "point",
        "trade_tick_size",
        "trade_tick_value",
        "trade_mode",
        "filling_mode",
        "trade_exemode",
        "execution_mode",
        "leverage",
        "margin_leverage",
        "balance",
        "equity",
        "currency",
    }
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "getattr":
            args = node.args
            if len(args) == 3 and isinstance(args[1], ast.Constant) and isinstance(args[1].value, str):
                field, default = args[1].value, args[2]
                # A default of None means UNAVAILABLE (honest). A literal
                # number/string default would fabricate broker truth.
                if field in BANNED_FIELDS and isinstance(default, ast.Constant) and isinstance(
                    default.value, (int, float)
                ) or (
                    field in BANNED_FIELDS
                    and isinstance(default, ast.Constant)
                    and isinstance(default.value, str)
                    and default.value != ""
                ):
                    offenders.append(f'getattr(x, "{field}", {default.value!r})')
    assert offenders == [], f"fabricated metadata defaults reappeared: {offenders}"


# ---------------------------------------------------------------------------
# Broker metadata: fail-closed resolution
# ---------------------------------------------------------------------------


class _PartialInfo:
    """SymbolInfo missing volume_min — a real-shaped but broken response."""

    trade_contract_size = 100.0
    volume_max = 100.0
    volume_step = 0.01
    digits = 2
    point = 0.01
    trade_tick_size = 0.01
    trade_mode = 4
    trade_allowed = True
    filling_mode = 1
    trade_exemode = 2
    trade_stops_level = 0
    trade_freeze_level = 0


class _NaNContractInfo(_PartialInfo):
    volume_min = 0.01
    trade_contract_size = float("nan")


class _CompleteInfo(_PartialInfo):
    """All required fields present — for tests of OTHER failure modes."""

    volume_min = 0.01


def _adapter_with(info: object, tmp_path: Path) -> MT5Adapter:
    mock = MagicMock()
    mock.symbol_info.return_value = info
    mock.symbol_select.return_value = True
    mock.last_error.return_value = (1, "ok")
    return MT5Adapter(mt5_module=mock, db_path=tmp_path / "t.db")


def test_missing_volume_min_fails_closed(tmp_path: Path):
    import pytest

    with pytest.raises(RuntimeError, match="volume_min"):
        _adapter_with(_PartialInfo(), tmp_path).get_symbol_spec("XAUUSD")


def test_nan_contract_size_fails_closed(tmp_path: Path):
    import pytest

    with pytest.raises(RuntimeError, match="contract_size"):
        _adapter_with(_NaNContractInfo(), tmp_path).get_symbol_spec("XAUUSD")


def test_contradictory_volume_geometry_fails_closed(tmp_path: Path):
    import pytest

    class Inverted(_PartialInfo):
        volume_min = 0.01
        volume_max = 0.001  # min > max: contradictory broker state

    with pytest.raises(RuntimeError, match="contradictory"):
        _adapter_with(Inverted(), tmp_path).get_symbol_spec("XAUUSD")


# ---------------------------------------------------------------------------
# Order check: no price fabrication, no leverage guessing
# ---------------------------------------------------------------------------


def _intent() -> OrderIntent:
    return OrderIntent(
        instrument=Instrument(symbol="XAUUSD"),
        side=Side.BUY,
        quantity=Decimal("0.01"),
        client_order_id="nf1",
        strategy_id="s",
    )


def test_order_check_market_order_without_price_is_refused(tmp_path: Path):
    adapter = _adapter_with(_CompleteInfo(), tmp_path)
    result = mt5_order_check(adapter, _intent())
    assert not result.ok
    assert "MISSING_MARKET_PRICE" in result.comment


def test_order_check_unknown_leverage_is_refused(tmp_path: Path):
    adapter = _adapter_with(_CompleteInfo(), tmp_path)
    acct = MagicMock(balance=10000, equity=10000, margin=0, margin_free=10000, leverage=None, currency="USD")
    adapter.account = lambda: acct  # type: ignore[method-assign]
    result = mt5_order_check(adapter, _intent(), market_price=Decimal("2000"))
    assert not result.ok
    assert "leverage unknown" in result.comment


# ---------------------------------------------------------------------------
# Risk: unknown equity vetoes (UNKNOWN -> BLOCK, never UNKNOWN -> GUESS)
# ---------------------------------------------------------------------------


def _ctx(equity: Decimal) -> RiskContext:
    from datetime import UTC, datetime

    from qts.domain.value_objects import Account

    acct = Account(
        balance=equity,
        equity=equity,
        source="TEST",
        updated_at=datetime.now(UTC),
    )
    return RiskContext(
        account=acct,
        positions={},
        open_orders_count=0,
        daily_pnl=Decimal("0"),
        drawdown=Decimal("0"),
        instrument_suspended=set(),
        reference_prices={"XAUUSD": Decimal("2000")},
    )


def test_zero_equity_vetoes_with_account_state_unavailable(tmp_path: Path):
    eng = RiskEngine(RiskLimits(), db_path=tmp_path / "r.db")
    intent = _intent()
    decision = eng.pre_trade(intent, _ctx(Decimal("0")))
    assert not decision.allowed
    assert decision.veto_reason == RiskVetoReason.ACCOUNT_STATE_UNAVAILABLE


def test_real_equity_allows_risk_pass(tmp_path: Path):
    eng = RiskEngine(RiskLimits(), db_path=tmp_path / "r.db")
    decision = eng.pre_trade(_intent(), _ctx(Decimal("10000")))
    assert decision.allowed


# ---------------------------------------------------------------------------
# Comparison metrics: UNAVAILABLE, never placeholder zero
# ---------------------------------------------------------------------------


def test_comparison_metrics_are_unavailable_without_data():
    res = compare_paper_shadow_demo(paper_fills=[], shadow_intents=[], demo_observations=[])
    for key in (
        "expected_entry_difference_bps",
        "actual_entry_difference_bps",
        "spread_difference_bps",
        "slippage_demo_bps",
        "latency_demo_ms",
    ):
        m = res[key]
        assert m["status"] in ("UNAVAILABLE", "INSUFFICIENT_EVIDENCE"), f"{key} fabricated: {m}"
        assert m["value"] is None
        assert m.get("reason")
    exit_diff = res["exit_differences"]
    assert exit_diff["status"] == "UNAVAILABLE"


def test_signal_agreement_uses_event_alignment_not_count_ratio():
    # 2 shadow intents, 1 paper fill for the SAME event, 1 paper fill for
    # another event -> alignment 1/2. A count ratio would give min/max = 1/2
    # coincidentally, so also verify NO match when events don't align.
    shadow = [
        {"client_order_id": "s:XAUUSD:2020-01-01T21:00:00+00:00:0"},
        {"client_order_id": "s:XAUUSD:2020-01-03T14:00:00+00:00:1"},
    ]
    paper_same_event = [{"time": "2020-01-01T22:00:00.5+00:00"}]  # next-bar-open of intent 0
    res = compare_paper_shadow_demo(paper_fills=paper_same_event, shadow_intents=shadow, demo_observations=[])
    ag = res["signal_agreement"]
    assert ag["status"] == "MEASURED"
    assert abs(ag["value"] - 0.5) < 1e-9

    paper_unrelated = [{"time": "2021-06-05T10:00:00+00:00"}]
    res2 = compare_paper_shadow_demo(paper_fills=paper_unrelated, shadow_intents=shadow, demo_observations=[])
    assert res2["signal_agreement"]["value"] == 0.0  # genuinely zero: no aligned events
    # count ratio would have said 0.5 for this case — proving it's real alignment


# ---------------------------------------------------------------------------
# Provenance: ambiguity is never promoted to REAL
# ---------------------------------------------------------------------------


def test_unknown_provenance_string_is_unverified():
    assert classify_record_provenance(
        recorded_provenance="SOMETHING_ELSE",
        symbol_ok=True,
        timestamps_fresh_and_ordered=True,
        lineage_bound=True,
    ) is EvidenceProvenance.UNVERIFIED


def test_none_provenance_is_unverified():
    assert classify_record_provenance(
        recorded_provenance=None,
        symbol_ok=True,
        timestamps_fresh_and_ordered=True,
        lineage_bound=True,
    ) is EvidenceProvenance.UNVERIFIED


def test_broken_lineage_downgrades_real_to_unverified():
    assert classify_record_provenance(
        recorded_provenance="REAL",
        symbol_ok=False,
        timestamps_fresh_and_ordered=True,
        lineage_bound=True,
    ) is EvidenceProvenance.UNVERIFIED


def test_real_only_supports_real_claims():
    assert EvidenceProvenance.REAL.supports(EvidenceProvenance.REAL)
    assert EvidenceProvenance.DEMO.supports(EvidenceProvenance.DEMO)
    assert not EvidenceProvenance.DEMO.supports(EvidenceProvenance.REAL)
    assert not EvidenceProvenance.SYNTHETIC.supports(EvidenceProvenance.DEMO)
    assert not EvidenceProvenance.UNVERIFIED.supports(EvidenceProvenance.SYNTHETIC)


def test_metric_value_never_serializes_placeholder_zero():
    m = MetricValue.unavailable("NO_DATA", "nothing")
    d = m.as_dict()
    assert d == {"status": "UNAVAILABLE", "value": None, "reason": "NO_DATA: nothing"}
    ok = MetricValue.ok(0.0).as_dict()  # a MEASURED zero is legitimate and distinct
    assert ok == {"status": "MEASURED", "value": 0.0}


# ---------------------------------------------------------------------------
# Quarantine: fabricated evidence must not be readable as current evidence
# ---------------------------------------------------------------------------


def test_fabricated_demo_observations_are_quarantined():
    live = Path("data/evidence/demo_forward_observations.json")
    assert not live.exists(), "fabricated demo observations returned to the live evidence directory"
    q = Path("data/evidence/quarantine/demo_forward_observations.json")
    assert q.exists(), "quarantined artifact missing"
    readme = Path("data/evidence/quarantine/README.md").read_text(encoding="utf-8")
    assert "UNVERIFIED" in readme or "FABRICATED" in readme.upper()


def test_impulse_forward_gate_reads_canonical_store_not_json(tmp_path, monkeypatch):
    """The forward-evidence gate must count DEMO/REAL provenance in the
    canonical store; a JSON file with 100 fabricated rows satisfies nothing."""
    import tempfile

    from qts.observability.forward_observatory import ForwardObservatory
    from qts.research.impulse.report import _forward_evidence_available

    monkeypatch.chdir(tempfile.mkdtemp())
    # Empty canonical store: NOT available even if a rich JSON existed
    evidence_dir = Path("data/evidence")
    evidence_dir.mkdir(parents=True)
    (evidence_dir / "demo_forward_observations.json").write_text(
        json.dumps({"observations": [{"fake": i} for i in range(50)]}), encoding="utf-8"
    )
    assert _forward_evidence_available(evidence_dir) is False

    # 10 SYNTHETIC ticks still don't count (provenance gate)
    fo = ForwardObservatory(db_path="data/sqlite/forward_observatory.db")
    fo.simulate_observation("XAUUSD", n_ticks=10)
    assert _forward_evidence_available(evidence_dir) is False
