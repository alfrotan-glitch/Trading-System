"""Regression cover for the hardening pass: close path, CORS, live gate, paths, CI.

Each test below pins one defect that was real in this tree and is now fixed.
The defect it pins is named in the test's docstring, so a future change that
reintroduces it fails with an explanation rather than a diff.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------- close
class _StubAdapter:
    """Minimal broker double: only what close_position actually touches."""

    def __init__(self, positions: Any = None, *, raise_on_positions: bool = False) -> None:
        self._positions = positions if positions is not None else []
        self._raise = raise_on_positions
        self.close_calls: list[dict[str, Any]] = []

    def position_details(self) -> list[dict[str, Any]]:
        if self._raise:
            raise ConnectionError("MT5 positions_get failed: (-10004, 'IPC timeout')")
        return list(self._positions)

    def close_position(self, ticket: int, *, volume: Any = None, comment: str = "") -> dict[str, Any]:
        self.close_calls.append({"ticket": ticket, "volume": volume, "comment": comment})
        return {
            "retcode": 10009,
            "broker_order_id": "555",
            "broker_position_id": "777",
            "executed_price": "2000.0",
            "executed_volume": str(volume or "0"),
            "comment": "ok",
        }

    def get_symbol_spec(self, symbol: str) -> Any:
        class _Spec:
            volume_min = Decimal("0.01")
            volume_max = Decimal("50")
            volume_step = Decimal("0.01")

        return _Spec()

    def history_deals(self, *a: Any, **k: Any) -> list[Any]:
        return []


def _session_with(monkeypatch: pytest.MonkeyPatch, adapter: _StubAdapter, *, authorized: bool = True) -> Any:
    """A DemoSession whose broker is the stub and whose authority is forced."""
    from qts.execution.demo_session import DemoSession

    session = DemoSession.__new__(DemoSession)
    # `adapter` is a lazy property backed by `_adapter`; set the backing field
    # so the real property returns the stub without constructing MT5Adapter.
    session._adapter = adapter  # type: ignore[attr-defined]
    if authorized:
        monkeypatch.setattr(DemoSession, "authorize_close", lambda self, **kw: (True, [], []))
    else:
        monkeypatch.setattr(
            DemoSession,
            "authorize_close",
            lambda self, **kw: (False, ["account_is_demo: account type REAL"], ["account_is_demo"]),
        )
    return session


def test_a_broker_state_error_refuses_the_close_instead_of_inventing_an_empty_position(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DEFECT: `except Exception: pass` turned a broker failure into "no positions".

    The close was then submitted anyway, against a ticket whose size, symbol
    and account were unknown.
    """
    adapter = _StubAdapter(raise_on_positions=True)
    session = _session_with(monkeypatch, adapter)

    result = session.close_position(12345)

    assert result["success"] is False
    assert result["blocked_by"] == ["broker_state_unavailable"]
    assert "position state unavailable" in result["error"]
    assert adapter.close_calls == [], "no close may be sent while broker state is unknown"
    assert result["refusal"]["explanation_available"] is True


def test_closing_a_ticket_the_broker_does_not_report_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """DEFECT: no ticket-ownership check — a close was sent for any ticket."""
    adapter = _StubAdapter(positions=[{"ticket": 111, "symbol": "XAUUSD", "volume": "0.10"}])
    session = _session_with(monkeypatch, adapter)

    result = session.close_position(999)

    assert result["success"] is False
    assert result["blocked_by"] == ["ticket_not_owned"]
    assert adapter.close_calls == []


def test_an_unauthorized_close_never_reaches_the_broker(monkeypatch: pytest.MonkeyPatch) -> None:
    """DEFECT: the close path had NO authorization boundary at all.

    The route trusted two booleans in the request body; nothing checked the
    account, the broker identity or the instrument.
    """
    adapter = _StubAdapter(positions=[{"ticket": 111, "symbol": "XAUUSD", "volume": "0.10"}])
    session = _session_with(monkeypatch, adapter, authorized=False)

    result = session.close_position(111)

    assert result["success"] is False
    assert result["blocked_by"] == ["account_is_demo"]
    assert adapter.close_calls == [], "authority is decided before the broker is contacted"


@pytest.mark.parametrize(
    ("requested", "why"),
    [
        (Decimal("0"), "zero volume"),
        (Decimal("-1"), "negative volume"),
        (Decimal("5"), "more than the open volume"),
        (Decimal("0.095"), "not a multiple of the broker step"),
        (Decimal("0.095001"), "leaves a residue below the broker minimum"),
    ],
)
def test_close_volume_must_fit_the_position_and_the_broker_rules(
    monkeypatch: pytest.MonkeyPatch, requested: Decimal, why: str
) -> None:
    """DEFECT: the close volume was passed through unvalidated."""
    adapter = _StubAdapter(positions=[{"ticket": 111, "symbol": "XAUUSD", "volume": "0.10"}])
    session = _session_with(monkeypatch, adapter)

    result = session.close_position(111, volume=requested)

    assert result["success"] is False, f"{why} must be refused"
    assert result["blocked_by"] == ["close_volume_invalid"]
    assert adapter.close_calls == []


def test_a_partial_close_keeps_the_remaining_exposure_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """DEFECT: a partial close marked the journal row CLOSED.

    The broker still held the remainder, so the journal reported flat while
    real exposure was open.
    """
    adapter = _StubAdapter(positions=[{"ticket": 111, "symbol": "XAUUSD", "volume": "0.10", "profit": "3.0"}])
    session = _session_with(monkeypatch, adapter)

    outcomes: list[dict[str, Any]] = []

    class _Journal:
        def open_orders(self) -> list[dict[str, Any]]:
            return [{"journal_id": 7, "broker_position_id": "111", "broker_symbol": "XAUUSD", "side": "BUY"}]

        def mark_outcome(self, journal_id: int, **kw: Any) -> None:
            outcomes.append({"journal_id": journal_id, **kw})

    session.journal = _Journal()  # type: ignore[attr-defined]
    session.config = type("C", (), {"actor": "test"})()  # type: ignore[attr-defined]
    monkeypatch.setattr(type(session), "sync_fills", lambda self: 0)
    monkeypatch.setattr(type(session), "reconcile", lambda self: {"requires_suspend": False})

    result = session.close_position(111, volume=Decimal("0.04"))

    assert result["success"] is True
    assert result["partial"] is True
    assert result["remaining_volume"] == "0.06"
    assert len(outcomes) == 1
    assert outcomes[0]["state"] == "OPEN", "a partially closed position is still open"
    assert outcomes[0]["market_state_exit"]["remaining_volume"] == "0.06"


def test_realized_pnl_is_labelled_and_never_silently_the_pre_close_mark(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DEFECT: realized P&L was the pre-close unrealized `profit` snapshot.

    That figure excludes the closing spread, slippage, commission and swap.
    Deal history is authoritative; when it is unavailable the fallback is
    explicitly labelled rather than passed off as a realized result.
    """
    from qts.execution.demo_session import DemoSession

    session = DemoSession.__new__(DemoSession)

    class _Deal:
        position_id = 111
        ticket = "777"
        profit = "12.50"
        commission = "-0.70"
        swap = "-0.30"

    session._adapter = type("A", (), {"history_deals": lambda self, *a, **k: [_Deal()]})()  # type: ignore[attr-defined]
    realized, source = session._realized_pnl_for_close(111, {"broker_position_id": "777"}, {"profit": "99.0"})
    assert source == "broker_deal_history"
    assert realized == Decimal("11.50"), "commission and swap are part of the realized result"

    session._adapter = type("A", (), {"history_deals": lambda self, *a, **k: []})()  # type: ignore[attr-defined]
    realized, source = session._realized_pnl_for_close(111, {}, {"profit": "99.0"})
    assert source == "pre_close_snapshot_unverified", "an unverified mark must say so"


def test_the_close_journal_match_requires_the_broker_position_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """DEFECT: journal matching fell back to symbol+side.

    Two open orders on the same instrument and side meant the close — and its
    P&L — could be attached to the wrong row.
    """
    adapter = _StubAdapter(positions=[{"ticket": 111, "symbol": "XAUUSD", "volume": "0.10", "profit": "1.0"}])
    session = _session_with(monkeypatch, adapter)
    outcomes: list[int] = []

    class _Journal:
        def open_orders(self) -> list[dict[str, Any]]:
            # same symbol and side, but a DIFFERENT position: must not match
            return [{"journal_id": 42, "broker_position_id": "222", "broker_symbol": "XAUUSD", "side": "BUY"}]

        def mark_outcome(self, journal_id: int, **kw: Any) -> None:
            outcomes.append(journal_id)

    session.journal = _Journal()  # type: ignore[attr-defined]
    session.config = type("C", (), {"actor": "test"})()  # type: ignore[attr-defined]
    monkeypatch.setattr(type(session), "sync_fills", lambda self: 0)
    monkeypatch.setattr(type(session), "reconcile", lambda self: {"requires_suspend": False})

    result = session.close_position(111)

    assert result["success"] is True
    assert outcomes == [], "an unrelated order on the same symbol/side must never be marked closed"
    assert result["journal_id"] is None


def test_close_authority_predicates_are_real_gate_predicates() -> None:
    """The close boundary must reuse the canonical gate, not invent predicates."""
    from qts.execution.demo_refusal import REFUSAL_EXPLANATIONS
    from qts.execution.demo_session import DemoSession

    for name in DemoSession.CLOSE_AUTHORITY_PREDICATES:
        assert name in REFUSAL_EXPLANATIONS, f"{name} has no operator-facing explanation"


def test_an_authority_predicate_the_gate_skipped_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A predicate the gate did not evaluate is unproven, not passed."""
    from qts.execution import demo_session as ds

    session = ds.DemoSession.__new__(ds.DemoSession)
    monkeypatch.setattr(ds.DemoSession, "build_context", lambda self, **kw: ds.DemoPretradeContext())
    monkeypatch.setattr(ds, "run_pretrade_gate", lambda ctx: type("V", (), {"checks": {}})())

    ok, reasons, blocked = session.authorize_close()

    assert ok is False
    assert set(blocked) == set(ds.DemoSession.CLOSE_AUTHORITY_PREDICATES)
    assert all("cannot prove authority" in r for r in reasons)


# ---------------------------------------------------------------------- CORS
def test_cors_rejects_null_and_untrusted_origins() -> None:
    """DEFECT: QTS_CORS_WILDCARD=1 set allow_origins=["*"] on a trading API."""
    from fastapi.testclient import TestClient

    from qts.api.server import app

    client = TestClient(app)
    for origin in ("null", "https://evil.example", "http://attacker.localhost.evil.com"):
        resp = client.get("/api/health", headers={"Origin": origin})
        assert resp.headers.get("access-control-allow-origin") is None, f"{origin} must not be allowed"

    allowed = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_there_is_no_cors_wildcard_escape_hatch() -> None:
    source = (REPO / "src" / "qts" / "api" / "server.py").read_text(encoding="utf-8")
    body = "\n".join(ln for ln in source.splitlines() if not ln.lstrip().startswith("#"))
    assert 'allow_origins=["*"]' not in body
    assert "QTS_CORS_WILDCARD" not in body


# ----------------------------------------------------------------- live gate
def test_no_validated_edge_blocks_live_eligibility() -> None:
    """DEFECT: CURRENT_EDGE_STATUS was consulted by the API and the UI, but by
    no live check — the readiness report could reach ready=true with no edge."""
    from qts.lifecycle.live_gate import check_validated_edge, live_readiness_report
    from qts.research.catalog import CURRENT_EDGE_STATUS

    assert CURRENT_EDGE_STATUS == "NO_VALIDATED_EDGE"
    ok, detail = check_validated_edge()
    assert ok is False
    assert "NO_VALIDATED_EDGE" in detail

    report = live_readiness_report()
    assert report["ready"] is False
    assert "validated_edge" in report["blocked_reasons"]
    assert report["validated_edge"]["proof_tier"] == "research"


def test_an_empty_edge_status_also_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    import qts.research.catalog as catalog
    from qts.lifecycle.live_gate import check_validated_edge

    monkeypatch.setattr(catalog, "CURRENT_EDGE_STATUS", "")
    ok, detail = check_validated_edge()
    assert ok is False
    assert "fail closed" in detail


# --------------------------------------------------------------------- paths
def test_cli_artifacts_resolve_independently_of_the_working_directory(tmp_path: Path) -> None:
    """DEFECT: edge/ops CLIs wrote data/evidence and data/sqlite relative to cwd."""
    import os

    from qts.config.paths import artifact_path

    keys = ("edge_validation", "dry_run", "paper_cli_db", "paper_cli_idempotency_db", "paper_cli_risk_db")
    before = {k: artifact_path(k) for k in keys}
    cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        after = {k: artifact_path(k) for k in keys}
    finally:
        os.chdir(cwd)

    assert before == after, "artifact locations must not follow the process working directory"
    for path in before.values():
        assert path.is_absolute()


def test_the_cli_modules_no_longer_hardcode_cwd_relative_state() -> None:
    for rel in ("src/qts/cli/edge.py", "src/qts/cli/ops.py"):
        source = (REPO / rel).read_text(encoding="utf-8")
        body = "\n".join(ln for ln in source.splitlines() if not ln.lstrip().startswith("#"))
        assert 'Path("data/evidence' not in body, f"{rel} still writes evidence relative to cwd"
        assert 'Path("data/sqlite' not in body, f"{rel} still opens a database relative to cwd"
        assert '_Path("data/' not in body, f"{rel} still uses a cwd-relative state path"


# ------------------------------------------------------------------------ CI
def test_ci_covers_this_branch_and_pull_requests_with_least_privilege() -> None:
    """DEFECT: 16 workflows, all triggered only by another session's branch.

    Nothing linted or tested this branch, and no pull request was checked.
    """
    import yaml

    ci = yaml.safe_load((REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    triggers = ci.get("on") or ci.get(True)
    assert "pull_request" in triggers, "pull requests must be checked"
    assert "arena/01a0f151-trading-system" in triggers["push"]["branches"]
    assert ci["permissions"] == {"contents": "read"}, "CI must not hold write scope"

    steps = " ".join(str(s.get("run", "")) for s in ci["jobs"]["checks"]["steps"])
    assert "ruff check" in steps
    assert "pytest" in steps
    assert "|| true" not in steps, "CI must report the real test state"
    assert "-c constraints.txt" in steps, "CI must install against pinned constraints"


def test_dependency_constraints_are_pinned_and_installable() -> None:
    text = (REPO / "constraints.txt").read_text(encoding="utf-8")
    pins = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
    assert len(pins) > 20, "constraints file looks empty"
    for pin in pins:
        assert "==" in pin, f"{pin} is not an exact pin"
