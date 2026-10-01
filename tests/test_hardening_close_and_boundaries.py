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
    # mypy reached zero errors for the first time in ARCH-030. Nothing enforced
    # it, so it would have rotted straight back; CI now holds the line.
    assert "mypy" in steps, "CI must enforce the type checker that is currently clean"


def test_dependency_constraints_are_pinned_and_installable() -> None:
    text = (REPO / "constraints.txt").read_text(encoding="utf-8")
    pins = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
    assert len(pins) > 20, "constraints file looks empty"
    for pin in pins:
        assert "==" in pin, f"{pin} is not an exact pin"


# ------------------------------------------------- database path anchoring
def test_every_database_resolves_to_one_location_whatever_the_cwd(tmp_path: Path) -> None:
    """DEFECT: ~20 modules default to db_path="data/sqlite/qts.db".

    sqlite3 resolves that against the process working directory, so the same
    SqliteAuditLog() opened a different file depending on where the CLI, the
    API or a test was launched from — silently splitting audit, kill-switch
    and journal state across several databases. qts.db.connect anchors every
    relative path to the canonical state root.
    """
    import os

    from qts.db import _anchored

    before = _anchored("data/sqlite/qts.db")
    cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        after = _anchored("data/sqlite/qts.db")
    finally:
        os.chdir(cwd)

    assert before == after, "the same database must not follow the working directory"
    assert Path(str(before)).is_absolute()


def test_anchoring_leaves_memory_and_absolute_paths_alone() -> None:
    from qts.db import _anchored

    assert _anchored(":memory:") == ":memory:"
    assert str(_anchored("/tmp/explicit.db")) == "/tmp/explicit.db"
    assert _anchored("file:x?mode=ro") == "file:x?mode=ro"


def test_a_path_shaped_memory_database_is_never_turned_into_a_real_file() -> None:
    """REGRESSION: the first version of the anchoring fix caused this.

    IdempotencyStore stores ``Path(":memory:")``, not the string. An
    ``isinstance(database, str)`` guard missed it, so the anchor resolved it
    to ``<state_root>/:memory:`` and sqlite created a real 12 KB file there.
    """
    from qts.db import _anchored

    assert str(_anchored(Path(":memory:"))) == ":memory:"


def test_no_stray_database_file_is_committed_at_the_repository_root() -> None:
    assert not (REPO / ":memory:").exists(), "a literal ':memory:' file was created at the repo root"


def test_operator_facing_text_never_calls_a_demo_connection_real() -> None:
    """DEFECT: startup health printed "MT5 REAL connected ... account=DEMO"."""
    health = (REPO / "src" / "qts" / "desktop" / "health.py").read_text(encoding="utf-8")
    body = "\n".join(ln for ln in health.splitlines() if not ln.lstrip().startswith("#"))
    assert "MT5 REAL connected" not in body
    assert "MT5 terminal attached" in body


def test_a_failed_broker_close_explains_itself_instead_of_crashing() -> None:
    """DEFECT (found by mypy, not by a test): the explainer failed OPEN.

    `POST /api/demo/close` builds a 502 naming `broker_state_unavailable` so an
    operator can tell "the venue rejected this" from "the server broke". It
    passed `blocked_by` as a LIST, matching the response payload convention,
    but the explainer uses that id as a dict key — so it raised
    `TypeError: unhashable type: 'list'` and the deliberate, named 502 became
    an opaque 500. The refusal explainer was the one component guaranteed to
    break precisely when a close had already failed at the broker.
    """
    from qts.execution.demo_refusal import REFUSAL_EXPLANATIONS, explain_refusal

    kwargs = {"reasons": ["broker close failed: terminal gone"], "state": "CLOSE_FAILED"}
    listed = explain_refusal(blocked_by=["broker_state_unavailable"], **kwargs)  # type: ignore[arg-type]

    assert listed["primary"]["id"] == "broker_state_unavailable"
    assert listed["primary"]["explained"] is True
    assert listed["primary"]["plain"] == REFUSAL_EXPLANATIONS["broker_state_unavailable"][0]
    # A list of one must stay byte-identical to the scalar form.
    assert listed == explain_refusal(blocked_by="broker_state_unavailable", **kwargs)  # type: ignore[arg-type]
    # Every id in a multi-blocker refusal keeps its own explanation.
    both = explain_refusal(blocked_by=["broker_state_unavailable", "stage_allows_order"], **kwargs)  # type: ignore[arg-type]
    assert both["blocker_ids"] == ["broker_state_unavailable", "stage_allows_order"]
    assert all(b["explained"] for b in both["blockers"])


def test_the_close_route_passes_an_id_the_explainer_can_resolve() -> None:
    """Pin the call site itself, not just the explainer's tolerance of it."""
    import ast

    source = (REPO / "src" / "qts" / "api" / "routes" / "demo.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "explain_refusal"
    ]
    assert calls, "close route no longer explains its refusals"
    for call in calls:
        for kw in call.keywords:
            if kw.arg == "blocked_by":
                assert not isinstance(kw.value, ast.List), (
                    f"explain_refusal(blocked_by=[...]) at line {call.lineno}: pass the id, not the payload list"
                )


def test_operator_docs_point_at_this_branch_not_a_stale_session_branch() -> None:
    """DEFECT: the Quickstart told users to clone a DIFFERENT session branch.

    `README.md` and the control document's DESKTOP CLONE section both said
    `git clone --branch arena/01a0ce9f-trading-system`, the ancestor this
    branch was cut from. Anyone following the documented install got a build
    without any of the hardening committed here and had no way to tell.

    Historical entries naming other branches are evidence and must survive;
    only INSTRUCTIONS — the lines inside a clone command — are pinned.
    """
    import re

    this_branch = "arena/01a0f151-trading-system"
    clone = re.compile(r"git clone\s+--branch\s+(\S+)")
    fence = re.compile(r"^```", re.MULTILINE)
    checked = 0
    for name in ("README.md", "QTS_PROJECT_CONTROL.md"):
        text = (REPO / name).read_text(encoding="utf-8")
        # Only FENCED blocks are instructions. Prose that quotes an old command
        # while explaining a past defect is historical evidence and must
        # survive -- including this repository's own change log, which names
        # the stale branch precisely because it records removing it.
        blocks = text.split("```")[1::2]
        assert fence.search(text), f"{name} has no code blocks to check"
        for block in blocks:
            for match in clone.finditer(block):
                checked += 1
                assert match.group(1) == this_branch, (
                    f"{name} instructs cloning {match.group(1)}, not {this_branch}"
                )
    assert checked >= 2, "the documented clone command disappeared"


def test_no_status_line_calls_a_demo_terminal_REAL() -> None:
    """DEFECT: the LIVE gate reported "REAL MT5 terminal connected".

    It meant "a genuine terminal, not a mock", but on a LIVE checklist an
    operator reads it as "a real-money account is connected" — and the check
    passes with a DEMO account. ARCH-027 removed exactly this confusion from
    startup health; the live gate kept it. Operator-facing status text must
    never pair REAL with a connection that may be a demo account.
    """
    import re

    offenders: list[str] = []
    for module in sorted((REPO / "src" / "qts").rglob("*.py")):
        for number, line in enumerate(module.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            for literal in re.findall(r'f?"([^"]{10,})"', line):
                # The defect is narrow and specific: SHOUTED "REAL" asserting a
                # live connection. Lowercase "a real terminal is required" is
                # plain English about infrastructure and is not confusing;
                # "REAL (attached terminal)" documents the QTS_MT5_MODE
                # vocabulary. Neither claims an account is real-money.
                if not re.search(r"\bREAL\b", literal):
                    continue
                if "real money" in literal.lower() or "REAL CAPITAL" in literal:
                    continue  # naming the account class is the FIX
                if re.search(r"\bconnect", literal, re.IGNORECASE):
                    offenders.append(f"{module.relative_to(REPO)}:{number}: {literal[:70]}")
    assert offenders == [], "operator-facing text conflates a REAL terminal with a real-money account:\n" + "\n".join(
        offenders
    )


def test_the_live_gate_connectivity_detail_names_the_account_class() -> None:
    """Connectivity passing on a DEMO account must SAY it is a demo account."""
    import sys
    import types
    from unittest.mock import MagicMock, patch

    import qts.lifecycle.live_gate as live_gate

    fake_identity = types.SimpleNamespace(is_demo=True, account_type="DEMO", login=12345, server="Broker-Demo")
    adapter = MagicMock()
    adapter.health_check.return_value = {"connected": True, "account": {"login": 12345}}
    adapter.broker_identity.return_value = fake_identity

    stub = types.ModuleType("MetaTrader5")
    saved = sys.modules.get("MetaTrader5")
    sys.modules["MetaTrader5"] = stub
    try:
        with patch("qts.adapters.mt5_adapter.MT5Adapter", return_value=adapter):
            ok, detail = live_gate.check_mt5_connectivity()
    finally:
        if saved is None:
            sys.modules.pop("MetaTrader5", None)
        else:
            sys.modules["MetaTrader5"] = saved

    assert ok is True, detail
    assert "DEMO account" in detail and "no real money" in detail, detail
    assert "REAL MT5 terminal" not in detail


# ------------------------------- one classification, not two hand-made lists
def _gate_predicate_ids() -> set[str]:
    """Every registry id the pre-trade gate can actually record.

    Derived, not hand-listed: the intersection of the canonical refusal
    registry with the string literals in the gate module. Some predicates are
    produced by helpers that RETURN ``(name, status, detail)`` rather than
    calling ``record()``, so matching on call sites alone silently misses them
    (it missed ``symbol_mapping_canonical``, which is a close-authority
    predicate — exactly the kind of omission this test must not have).
    """
    import ast

    from qts.execution.demo_refusal import REFUSAL_EXPLANATIONS

    source = (REPO / "src" / "qts" / "execution" / "demo_pretrade.py").read_text(encoding="utf-8")
    literals = {
        node.value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    return set(REFUSAL_EXPLANATIONS) & literals


def test_every_gate_predicate_is_classified_authority_or_entry_quality() -> None:
    """A new predicate must be classified on purpose, not default to "entry".

    DEFECT: the close path's authority subset was a tuple hand-copied into
    `demo_session`, disconnected from the gate. Adding an authority predicate
    to the gate would silently NOT apply it to closes, and a duplicate like
    that can only ever drift toward permitting more.
    """
    from qts.execution.demo_pretrade import ENTRY_QUALITY_PREDICATES, MUTATION_AUTHORITY_PREDICATES

    authority = set(MUTATION_AUTHORITY_PREDICATES)
    entry = set(ENTRY_QUALITY_PREDICATES)
    predicates = _gate_predicate_ids()

    assert not (authority & entry), f"classified as both: {sorted(authority & entry)}"
    unclassified = predicates - authority - entry
    assert unclassified == set(), (
        "new gate predicate(s) are unclassified — decide whether each governs CLOSES "
        f"(MUTATION_AUTHORITY_PREDICATES) or only opening (ENTRY_QUALITY_PREDICATES): {sorted(unclassified)}"
    )
    stale = (authority | entry) - predicates
    assert stale == set(), f"classified predicate(s) the gate no longer records: {sorted(stale)}"


def test_the_close_path_uses_the_declared_authority_subset() -> None:
    """One declaration, no second copy that could drift."""
    from qts.execution.demo_pretrade import MUTATION_AUTHORITY_PREDICATES
    from qts.execution.demo_session import DemoSession

    assert DemoSession.CLOSE_AUTHORITY_PREDICATES is MUTATION_AUTHORITY_PREDICATES

    source = (REPO / "src" / "qts" / "execution" / "demo_session.py").read_text(encoding="utf-8")
    assert '"authorization_valid",' not in source, (
        "the close-authority list is hand-copied again; derive it from the gate's declaration"
    )


def test_exposure_reducing_closes_are_not_blocked_by_entry_quality() -> None:
    """The asymmetry IS the safety property, so pin it.

    Refusing a close on a wide spread, a stale quote, an exhausted loss budget
    or a closed session would trap the operator in a position exactly when
    exiting matters most. Fail closed on the way in, never on the way out.
    """
    from qts.execution.demo_pretrade import MUTATION_AUTHORITY_PREDICATES

    must_never_block_a_close = {
        "market_data_fresh",
        "spread_available",
        "max_daily_loss",
        "max_drawdown_within_policy",
        "max_total_exposure",
        "max_simultaneous_positions",
        "trading_hours_allowed",
        "stop_loss_present",
        "order_frequency_within_policy",
        "duplicate_order_protection",
    }
    overlap = must_never_block_a_close & set(MUTATION_AUTHORITY_PREDICATES)
    assert overlap == set(), (
        f"{sorted(overlap)} would refuse an exposure-REDUCING close and trap the operator in the position"
    )


def test_close_authority_still_demands_the_account_and_symbol_facts() -> None:
    """The asymmetry must not become "closes check nothing"."""
    from qts.execution.demo_pretrade import MUTATION_AUTHORITY_PREDICATES

    for required in (
        "authorization_valid",
        "execution_permission",
        "mode_is_demo_execution",
        "account_is_demo",
        "broker_identity_verified",
        "broker_symbol_matches_registry",
    ):
        assert required in MUTATION_AUTHORITY_PREDICATES, f"{required} must gate every mutation, closes included"


# ------------------------------------- an unknown result is not a zero result
def test_an_unestablished_realized_pnl_is_not_recorded_as_zero(tmp_path: Path) -> None:
    """DEFECT: unknown P&L became a definite 0.00 in the journal.

    `_realized_pnl_for_close` returned `Decimal("0")` when broker deal history
    could not be read, and `daily_realized_pnl()` summed every non-NULL row —
    so a loss the broker could not be asked about was counted as "this trade
    made exactly nothing". That number feeds the `max_daily_loss` predicate,
    which therefore passed on a fabricated figure and left the day's remaining
    loss budget looking larger than it was: fail OPEN, on a risk limit.
    """
    from qts.execution.order_truth import open_demo_journal

    journal = open_demo_journal(tmp_path / "journal.db")
    assert journal.daily_realized_pnl() == Decimal("0"), "no closes today means a known zero"


def test_a_day_containing_an_unresolved_close_reports_unknown_not_a_total(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    from qts.db import connect as db_connect
    from qts.execution.order_truth import open_demo_journal

    journal = open_demo_journal(tmp_path / "journal.db")
    today = datetime.now(UTC).isoformat()

    def insert(cid: str, pnl: str | None) -> None:
        with db_connect(journal.db_path) as con:
            con.execute(
                "INSERT INTO demo_order_journal"
                " (label, client_order_id, state, created_at, updated_at, closed_at, realized_pnl)"
                " VALUES ('demo', ?, 'CLOSED', ?, ?, ?, ?)",
                (cid, today, today, today, pnl),
            )
            con.commit()

    insert("known-loss", "-25")
    assert journal.daily_realized_pnl() == Decimal("-25")

    insert("unresolved", None)
    assert journal.daily_realized_pnl() is None, (
        "a close whose realized result was never established must make the day's total UNKNOWN, "
        "not silently drop out of the sum"
    )


def test_unknown_daily_pnl_fails_the_daily_loss_predicate_closed() -> None:
    """The gate already had the right branch; the fabricated zero bypassed it."""
    import inspect

    from qts.execution import demo_pretrade

    source = inspect.getsource(demo_pretrade.run_pretrade_gate)
    assert 'record("max_daily_loss", CHECK_UNKNOWN' in source, (
        "max_daily_loss must report UNKNOWN (fail closed) when the day's realized P&L is not known"
    )
    assert "max_daily_loss" in demo_pretrade.ENTRY_QUALITY_PREDICATES


# ----------------------------- a broken control must stop the autopilot loop
def test_autopilot_halts_on_every_authority_failure_not_just_some() -> None:
    """DEFECT: the loop's "a control is broken" list was hand-copied and short.

    `_is_control_failure` decides whether a gate refusal halts the autopilot
    (and the stage machine) or is shrugged off as a routine market limit and
    retried next poll. Its marker list was a third hand-copied set of
    predicate names, and it omitted every symbol-identity authority check. So
    if the broker's symbol stopped mapping canonically to the registry symbol
    — the exact "broker renamed the instrument" drift the authority checks
    exist to catch — the loop treated it as "spread too wide", kept polling
    forever and never halted. No unsafe order could be submitted (the gate
    still refused), but a broken identity control was reported to the operator
    as a running system.
    """
    from qts.execution.demo_autopilot import _CONTROL_FAILURE_MARKERS, _is_control_failure
    from qts.execution.demo_pretrade import MUTATION_AUTHORITY_PREDICATES

    missing = set(MUTATION_AUTHORITY_PREDICATES) - set(_CONTROL_FAILURE_MARKERS)
    assert not missing, (
        "these authority predicates can fail without halting the autopilot, so the loop would retry "
        f"forever against a broken control: {sorted(missing)}"
    )

    class _Result:
        reasons: list[str] = []

        def __init__(self, failed: list[str]) -> None:
            self.verdict = {"failed": failed}

    for predicate in MUTATION_AUTHORITY_PREDICATES:
        assert _is_control_failure(_Result([predicate])), f"{predicate} must halt the loop"
    assert not _is_control_failure(_Result(["spread_within_limit"])), "a wide spread is not a broken control"
    assert not _is_control_failure(_Result([])), "a clean verdict is not a broken control"


def test_control_failure_markers_are_not_a_fourth_hand_copied_list() -> None:
    import pathlib

    from qts.execution.demo_autopilot import _CONTROL_FAILURE_MARKERS
    from qts.execution.demo_pretrade import CONTROL_FAILURE_PREDICATES

    assert _CONTROL_FAILURE_MARKERS is CONTROL_FAILURE_PREDICATES, (
        "the autopilot must use the canonical classification, not its own copy"
    )
    source = pathlib.Path("src/qts/execution/demo_autopilot.py").read_text(encoding="utf-8")
    assert '"broker_identity_verified",' not in source, "predicate names re-listed in demo_autopilot.py"


def test_every_declared_kill_condition_maps_to_a_real_gate_predicate() -> None:
    """A kill condition enforced by a misspelled predicate is a comment."""
    from qts.execution.demo_pretrade import ENTRY_QUALITY_PREDICATES, MUTATION_AUTHORITY_PREDICATES
    from qts.lifecycle.demo_policy import KILL_CONDITION_CHECKS

    known = set(MUTATION_AUTHORITY_PREDICATES) | set(ENTRY_QUALITY_PREDICATES)
    for condition, predicates in KILL_CONDITION_CHECKS.items():
        assert predicates, f"kill condition {condition!r} is enforced by nothing"
        unknown = set(predicates) - known
        assert not unknown, (
            f"kill condition {condition!r} names predicates the gate does not evaluate: {sorted(unknown)} — "
            "rename it to a live predicate or the condition is unenforced"
        )
