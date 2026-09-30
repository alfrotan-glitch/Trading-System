"""Durable suspension / kill-switch RECOVERY lifecycle.

The defect this file pins was observed on the Windows DEMO host: MetaTrader 5
connected, ``trade_allowed=True``, a live XAUUSD@ quote classified FRESH,
``run_reconciliation: PASS``, ``POST /api/demo/guide/resume`` answering
``200 OK`` — and QTS still reporting ``status=Suspended`` with every
``POST /api/demo/order`` refused ``409``.

Two DURABLE records can suspend trading and they are written by different
components:

============================  ===========================  ==================
record                        authority                    enforced by
============================  ===========================  ==================
``risk_state.killed``         :class:`RiskEngine`          ``pre_trade`` /
                                                           ``kill_switch_functional``
``reconcile_state.suspended`` :class:`ExecutionEngine`     ``reconciliation_ready``
============================  ===========================  ==================

Recovery only ever cleared the FIRST one. The second had no recovery edge
reachable from any product surface (``heal_reconcile`` existed but nothing
called it), so it stayed active forever — and because the registered policy
maps ``reconciliation_ready`` onto the kill conditions
``reconciliation_suspension`` / ``reconciliation_drift``, the very next order
attempt re-raised the kill switch. A cleared stop resurrected itself on the
next click, deterministically.

These tests walk the whole lifecycle against the simulated terminal:

    HEALTHY → FAULT → SUSPENDED (durable) → RESTART → RECOVERY VERIFIED
            → RESUMED (durable cleared) → RESTART → still recovered

No broker is contacted: every terminal is ``tests/fakes_mt5_demo.FakeTerminal``
and every test asserts ``terminal.requests == []`` — not a single order request
leaves the gate anywhere in this file.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from demo_harness import authorization_doc
from fakes_mt5_demo import FakeTerminal

# The canonical arming helper and the registered diagnostic policy are reused
# from the lifecycle-audit suite rather than re-implemented: a recovery test
# that armed the system its own way would not be testing the real lifecycle.
from test_demo_lifecycle_audit import _arm_to_stage_2, _registry_doc, _session

from qts.db import connect as db_connect
from qts.execution.engine import load_reconcile_suspension
from qts.lifecycle.demo_stage import ORDER_STAGES, DemoStage

SYMBOL_MAP = {"XAUUSD": "XAUUSD@"}


class AgeableTerminal(FakeTerminal):
    """A FakeTerminal whose quote age the test controls.

    ``quote_age_s`` is how old the broker says its last tick is. Above the
    60 s freshness contract the canonical market-data provider rejects it, so
    the gate sees the REAL stale-quote path — no check is stubbed out.
    """

    def __init__(self, *args, quote_age_s: float = 0.0, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.quote_age_s = quote_age_s

    def symbol_info_tick(self, name):
        stamp = time.time() - float(self.quote_age_s)
        return SimpleNamespace(
            time=int(stamp),
            time_msc=int(stamp * 1000),
            bid=2000.00,
            ask=2000.20,
            last=2000.00,
            volume=1,
            flags=6,
            volume_real=1.0,
        )


@pytest.fixture()
def env(tmp_path: Path, monkeypatch):
    """Hermetic operator environment — every durable side effect in tmp_path."""
    (tmp_path / "authorization.json").write_text(json.dumps(authorization_doc()), encoding="utf-8")
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps(_registry_doc(), indent=2), encoding="utf-8")
    setup = tmp_path / "setup.json"
    setup.write_text(json.dumps({"symbol": "XAUUSD@", "symbol_map": SYMBOL_MAP}), encoding="utf-8")

    monkeypatch.setenv("QTS_MODE", "demo_execution")
    monkeypatch.setenv("QTS_DEMO_AUTHORIZATION", str(tmp_path / "authorization.json"))
    monkeypatch.setenv("QTS_DEMO_REGISTRY", str(registry))
    monkeypatch.setenv("QTS_DEMO_IDENTITY_PIN", str(tmp_path / "pin.json"))
    monkeypatch.setenv("QTS_SETUP_FILE", str(setup))

    import qts.execution.demo_session as dsmod

    monkeypatch.setattr(dsmod, "SELF_TEST_DB", tmp_path / "selftest.db")

    # The audit log is the EVIDENCE store these tests inspect; keep it hermetic.
    from qts.observability import audit as audit_module

    real_audit = audit_module.SqliteAuditLog
    monkeypatch.setattr(
        audit_module,
        "SqliteAuditLog",
        lambda *a, **k: real_audit(db_path=tmp_path / "audit.db", jsonl_path=tmp_path / "audit.jsonl"),
    )
    return {"tmp": tmp_path, "registry": registry, "db": tmp_path / "qts.db", "audit": tmp_path / "audit.db"}


# ------------------------------------------------------------------ helpers


def _durable_rows(db: Path) -> dict[str, object]:
    """The two durable suspension rows, read straight from SQLite."""
    out: dict[str, object] = {"risk_state": None, "reconcile_state": None}
    if not db.exists():
        return out
    with db_connect(db) as con:
        for table, sql in (
            ("risk_state", "SELECT killed, reason FROM risk_state WHERE k=1"),
            ("reconcile_state", "SELECT suspended, reason FROM reconcile_state WHERE k=1"),
        ):
            try:
                out[table] = con.execute(sql).fetchone()
            except Exception:
                out[table] = None
    return out


def _audit_payloads(audit_db: Path) -> list[dict]:
    if not audit_db.exists():
        return []
    with db_connect(audit_db) as con:
        try:
            rows = con.execute("SELECT event_type, payload FROM audit_events ORDER BY rowid").fetchall()
        except Exception:
            return []
    out = []
    for event_type, payload in rows:
        try:
            body = json.loads(payload)
        except Exception:
            body = {"raw": payload}
        body["_event_type"] = event_type
        out.append(body)
    return out


def _venue_position() -> SimpleNamespace:
    """A broker position QTS has no journal record for — real drift."""
    return SimpleNamespace(
        ticket=555_001,
        symbol="XAUUSD@",
        volume=0.01,
        type=0,
        price_open=2000.0,
        price_current=2000.0,
        profit=-1.0,
        time=int(datetime.now(UTC).timestamp()) - 60,
        comment="",
        magic=0,
    )


def _suspend_on_stale_market_data(env, terminal) -> object:
    """Drive the REAL fault path: a stale quote trips the policy kill condition."""
    session = _session(env["tmp"], terminal)
    _arm_to_stage_2(session, terminal)
    terminal.quote_age_s = 900.0  # far beyond the 60 s freshness contract
    result = session.submit(side="BUY")
    assert result.allowed is False
    assert terminal.requests == [], "a refused gate must never reach the broker"
    return session


# ------------------------------------------------------------------- Test 1


def test_1_a_fresh_system_is_not_suspended(env):
    terminal = AgeableTerminal()
    session = _session(env["tmp"], terminal)
    _arm_to_stage_2(session, terminal)

    state = session.durable_suspension_state()
    assert state["suspended"] is False
    assert state["active_blockers"] == []
    assert state["kill_switch"]["killed"] is False
    assert state["reconciliation"]["suspended"] is False
    assert state["orders_permitted"] is True
    assert state["stage"]["stage"] in ORDER_STAGES

    verdict = session.preflight(side="BUY")["verdict"]
    assert verdict["passed"] is True, verdict["failed"] + verdict["unknown"]
    assert terminal.requests == []


# ------------------------------------------------------------------- Test 2


def test_2_a_market_data_fault_activates_a_durable_suspension(env):
    terminal = AgeableTerminal()
    session = _suspend_on_stale_market_data(env, terminal)

    # The gate refused on the real freshness check…
    state = session.durable_suspension_state()
    assert state["suspended"] is True
    assert "kill_switch" in state["active_ids"]
    # …and the policy kill condition made it a STATE CHANGE, not a retry.
    assert "market_data_stale" in str(state["kill_switch"]["reason"])
    assert state["stage"]["stage"] == DemoStage.HALTED.value

    rows = _durable_rows(env["db"])
    assert rows["risk_state"] is not None and rows["risk_state"][0] == 1, "the kill must be DURABLE"
    assert terminal.requests == []


# ------------------------------------------------------------------- Test 3


def test_3_restart_while_suspended_restores_the_suspension(env):
    terminal = AgeableTerminal()
    _suspend_on_stale_market_data(env, terminal)

    # Simulated restart: brand-new session/engine objects, same durable store.
    restarted = _session(env["tmp"], terminal)
    state = restarted.durable_suspension_state()
    assert state["suspended"] is True
    assert "kill_switch" in state["active_ids"]
    assert state["orders_permitted"] is False

    verdict = restarted.preflight(side="BUY")["verdict"]
    assert verdict["passed"] is False
    assert "kill_switch_functional" in verdict["failed"]
    assert terminal.requests == []


# ------------------------------------------------------------------- Test 4


def test_4_recovery_deactivates_the_condition_but_keeps_the_evidence(env):
    terminal = AgeableTerminal()
    _suspend_on_stale_market_data(env, terminal)

    # The market recovers: quotes are fresh again.
    terminal.quote_age_s = 0.0
    restarted = _session(env["tmp"], terminal)

    # Canonical reconciliation says broker and local state agree.
    reconciliation = restarted.reconcile()
    assert reconciliation["requires_suspend"] is False

    # The CURRENT stale condition is gone — the gate measures it live.
    verdict = restarted.preflight(side="BUY")["verdict"]
    assert "market_data_fresh" not in verdict["failed"]
    assert "market_data_fresh" not in verdict["unknown"]
    assert verdict["checks"]["market_data_fresh"]["status"] == "PASS"

    # …but the HISTORICAL fault is still recorded, and the durable kill is
    # still ACTIVE: a recoverable suspension is cleared by an explicit
    # transition, never by the fault simply going away.
    state = restarted.durable_suspension_state()
    assert state["suspended"] is True
    assert "market_data_stale" in str(state["kill_switch"]["reason"])
    assert terminal.requests == []


# ------------------------------------------------------------------- Test 5


def test_5_resume_clears_the_complete_durable_suspension_set(env):
    terminal = AgeableTerminal()
    _suspend_on_stale_market_data(env, terminal)
    terminal.quote_age_s = 0.0

    restarted = _session(env["tmp"], terminal)
    recovery = restarted.resume_from_suspension(reason="operator reviewed the stale-feed halt", actor="test")

    assert recovery["recovered"] is True
    assert recovery["changed"] is True
    assert "kill_switch" in recovery["cleared"]
    assert recovery["active_blockers"] == []

    # Durable, restart-safe, and verified AFTER the write.
    after = restarted.durable_suspension_state()
    assert after["suspended"] is False
    assert after["kill_switch"]["killed"] is False
    assert after["reconciliation"]["suspended"] is False
    assert _durable_rows(env["db"])["risk_state"] is None

    # Recovery grants nothing: the stage stays HALTED and the response says so.
    assert after["stage"]["stage"] == DemoStage.HALTED.value
    assert recovery["orders_permitted"] is False
    assert recovery["next"] == "prepare"
    assert terminal.requests == []


def test_5b_resume_is_idempotent_on_an_already_recovered_system(env):
    terminal = AgeableTerminal()
    session = _session(env["tmp"], terminal)
    _arm_to_stage_2(session, terminal)

    first = session.resume_from_suspension(reason="nothing was stopped", actor="test")
    assert first["recovered"] is True
    assert first["changed"] is False
    assert first["cleared"] == []

    second = session.resume_from_suspension(reason="again", actor="test")
    assert second["recovered"] is True
    assert second["changed"] is False
    assert session.durable_suspension_state()["suspended"] is False
    assert terminal.requests == []


def test_5c_resume_requires_a_recorded_reason(env):
    terminal = AgeableTerminal()
    session = _suspend_on_stale_market_data(env, terminal)

    refused = session.resume_from_suspension(reason="   ", actor="test")
    assert refused["recovered"] is False
    assert refused["active_blockers"][0]["id"] == "invalid_request"
    assert session.durable_suspension_state()["suspended"] is True, "a refused resume clears nothing"


# ------------------------------------------------------------------- Test 6


def test_6_resume_refuses_while_a_real_blocker_remains(env):
    """An UNRESOLVED broker/local divergence is a genuine active blocker."""
    terminal = AgeableTerminal()
    session = _session(env["tmp"], terminal)
    _arm_to_stage_2(session, terminal)

    terminal.positions = [_venue_position()]
    terminal.deals = []
    assert session.reconcile()["requires_suspend"] is True
    result = session.submit(side="BUY")
    assert result.allowed is False
    assert "reconciliation_ready" in (result.verdict or {})["failed"]

    before = session.durable_suspension_state()
    assert set(before["active_ids"]) == {"kill_switch", "reconciliation_suspension"}

    # The drift is STILL present when the operator asks to resume.
    restarted = _session(env["tmp"], terminal)
    recovery = restarted.resume_from_suspension(reason="trying to clear the halt", actor="test")

    assert recovery["recovered"] is False
    assert recovery["changed"] is False
    assert recovery["cleared"] == []
    blockers = {b["id"] for b in recovery["active_blockers"]}
    assert "reconciliation_suspension" in blockers
    assert recovery["recovery_checks"]["reconciliation_verified_clean"]["satisfied"] is False
    assert recovery["recovery_checks"]["reconciliation_verified_clean"]["detail"]

    # All-or-nothing: the kill switch was NOT cleared either.
    after = restarted.durable_suspension_state()
    assert after["suspended"] is True
    assert after["kill_switch"]["killed"] is True
    assert after["reconciliation"]["suspended"] is True
    assert terminal.requests == []


def test_6b_resume_recovers_once_the_divergence_is_actually_resolved(env):
    """The headline regression: a recoverable reconciliation suspension must
    stop resurrecting itself through the policy kill condition."""
    terminal = AgeableTerminal()
    session = _session(env["tmp"], terminal)
    _arm_to_stage_2(session, terminal)

    terminal.positions = [_venue_position()]
    terminal.deals = []
    session.reconcile()
    session.submit(side="BUY")  # refused; raises the kill + halts the stage
    assert terminal.requests == []
    assert load_reconcile_suspension(env["db"]).suspended is True

    # Operator resolves the divergence at the venue, then resumes.
    terminal.positions = []
    terminal.deals = []
    restarted = _session(env["tmp"], terminal)
    recovery = restarted.resume_from_suspension(reason="venue position closed and verified", actor="test")

    assert recovery["recovered"] is True
    assert set(recovery["cleared"]) == {"reconciliation_suspension", "kill_switch"}
    assert load_reconcile_suspension(env["db"]).suspended is False

    # Re-arm through the canonical stage machine and prove the order gate is
    # no longer refusing — and that nothing re-raised the kill switch.
    rearmed = _session(env["tmp"], terminal)
    rearmed.stage.reset_to_disabled(reason="halt acknowledged", actor="test")
    _arm_to_stage_2(rearmed, terminal)
    verdict = rearmed.preflight(side="BUY")["verdict"]
    assert verdict["passed"] is True, verdict["failed"] + verdict["unknown"]
    assert rearmed.durable_suspension_state()["suspended"] is False
    assert terminal.requests == []


# ------------------------------------------------------------------- Test 7


def test_7_restart_after_recovery_does_not_resurrect_the_old_kill(env):
    terminal = AgeableTerminal()
    _suspend_on_stale_market_data(env, terminal)
    terminal.quote_age_s = 0.0

    recovered = _session(env["tmp"], terminal)
    assert recovered.resume_from_suspension(reason="reviewed", actor="test")["recovered"] is True

    # Restart again — twice, to catch a lazily-restored in-memory copy.
    for _ in range(2):
        restarted = _session(env["tmp"], terminal)
        state = restarted.durable_suspension_state()
        assert state["suspended"] is False, state["active_blockers"]
        assert state["kill_switch"]["killed"] is False
        assert restarted.engine.is_suspended is False
    assert terminal.requests == []


# ------------------------------------------------------------------- Test 8


def test_8_the_order_gate_agrees_with_the_recovered_state(env):
    terminal = AgeableTerminal()
    _suspend_on_stale_market_data(env, terminal)
    terminal.quote_age_s = 0.0

    session = _session(env["tmp"], terminal)
    assert session.resume_from_suspension(reason="reviewed", actor="test")["recovered"] is True

    # Before re-arming, both surfaces agree that orders are NOT permitted.
    assert session.durable_suspension_state()["orders_permitted"] is False
    halted_verdict = session.preflight(side="BUY")["verdict"]
    assert halted_verdict["passed"] is False
    assert "stage_allows_order" in halted_verdict["failed"]

    # After the canonical re-arm they agree that they are.
    rearmed = _session(env["tmp"], terminal)
    rearmed.stage.reset_to_disabled(reason="halt acknowledged", actor="test")
    _arm_to_stage_2(rearmed, terminal)
    assert rearmed.durable_suspension_state()["orders_permitted"] is True
    verdict = rearmed.preflight(side="BUY")["verdict"]
    assert verdict["passed"] is True, verdict["failed"] + verdict["unknown"]
    assert verdict["checks"]["kill_switch_functional"]["status"] == "PASS"
    assert verdict["checks"]["reconciliation_ready"]["status"] == "PASS"
    assert terminal.requests == [], "the gate was evaluated, never executed"


# ------------------------------------------------------------------ Test 10


def test_10_recovery_preserves_the_audit_evidence_of_the_original_fault(env):
    terminal = AgeableTerminal()
    _suspend_on_stale_market_data(env, terminal)
    terminal.quote_age_s = 0.0

    before_events = _audit_payloads(env["audit"])
    assert before_events, "the fault must be recorded"

    session = _session(env["tmp"], terminal)
    recovery = session.resume_from_suspension(reason="reviewed the stale-feed halt", actor="test")
    assert recovery["recovered"] is True

    after_events = _audit_payloads(env["audit"])
    assert len(after_events) >= len(before_events), "clearing a suspension must never delete audit history"
    blob = json.dumps(after_events)
    # The ORIGINAL fault survives as evidence…
    assert "market_data_stale" in blob
    # …including on the recovery record itself, which names what it cleared.
    cleared = [e for e in after_events if e.get("action") == "cleared"]
    assert cleared, "the recovery decision must be audited"
    assert "market_data_stale" in str(cleared[-1].get("previous_reason"))
    assert cleared[-1].get("reason") == "reviewed the stale-feed halt"
    completed = [e for e in after_events if e.get("action") == "resume_completed"]
    assert completed and completed[-1]["recovered"] is True
    assert terminal.requests == []


def test_10b_a_refused_resume_is_recorded_too(env):
    terminal = AgeableTerminal()
    session = _session(env["tmp"], terminal)
    _arm_to_stage_2(session, terminal)
    terminal.positions = [_venue_position()]
    terminal.deals = []
    session.reconcile()
    session.submit(side="BUY")

    restarted = _session(env["tmp"], terminal)
    assert restarted.resume_from_suspension(reason="attempted", actor="test")["recovered"] is False

    refusals = [e for e in _audit_payloads(env["audit"]) if e.get("action") == "resume_refused"]
    assert refusals, "a refused recovery must be durable evidence, not a silent no-op"
    assert "reconciliation_verified_clean" in refusals[-1]["unsatisfied_recovery_checks"]
    assert terminal.requests == []


# ------------------------------------------- startup health reads the authority


def test_startup_health_reads_the_durable_reconciliation_authority(tmp_path, monkeypatch):
    """``run_reconciliation`` must report the durable row, not an audit scan.

    The old probe scanned the last 50 audit events for the words "DRIFT" or
    "SUSPENDED". That is evidence, not state: once 50 newer events existed it
    reported ``reconciliation healthy`` while ``reconcile_state.suspended=1``
    still refused every order — the exact contradiction seen on the host.
    """
    from qts.desktop.health import startup_health_check
    from qts.domain.events import DomainEvent, EventType
    from qts.execution.engine import RECONCILE_STATE_SCHEMA
    from qts.observability.audit import SqliteAuditLog

    monkeypatch.chdir(tmp_path)
    db = tmp_path / "data" / "sqlite" / "qts.db"
    db.parent.mkdir(parents=True)
    with db_connect(db) as con:
        con.execute(RECONCILE_STATE_SCHEMA)
        con.execute("INSERT OR REPLACE INTO reconcile_state VALUES (1,1,'venue XAUUSD 0.01 not local','t')")
        con.commit()

    # Bury the drift under a rolling window of newer, unrelated audit events —
    # the condition is still ACTIVE and must still be reported.
    log = SqliteAuditLog(db_path=db, jsonl_path=tmp_path / "audit.jsonl")
    for i in range(60):
        log.emit(DomainEvent(event_type=EventType.TICK, payload={"seq": i}))

    health = startup_health_check()
    recon = next(c for c in health["checks"] if c["name"] == "run_reconciliation")
    assert recon["passed"] is False, recon["detail"]
    assert "SUSPENDED" in recon["detail"]
    assert "venue XAUUSD 0.01 not local" in recon["detail"]
    assert health["system_status"] == "Suspended"

    # Healed through the canonical authority ⇒ the historical events remain in
    # the audit log, but they are no longer an ACTIVE blocker.
    with db_connect(db) as con:
        con.execute("INSERT OR REPLACE INTO reconcile_state VALUES (1,0,'','t')")
        con.commit()
    healed = startup_health_check()
    recon2 = next(c for c in healed["checks"] if c["name"] == "run_reconciliation")
    assert recon2["passed"] is True, recon2["detail"]
    with db_connect(db) as con:
        assert con.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] >= 60


# ------------------------------- startup health reads the order-state authority


def _seed_journal(db, *, state: str) -> None:
    """A real journal row, written through the journal's own API."""
    from decimal import Decimal

    from qts.execution.demo_journal import DemoOrderJournal

    journal = DemoOrderJournal(db)
    journal_id = journal.open_order(
        client_order_id="qts-abc123",
        strategy_id="DEMO-EXECPROBE-XAUUSD-V1",
        strategy_config_hash="deadbeef",
        symbol="XAUUSD",
        broker_symbol="XAUUSD@",
        side="BUY",
        requested_lots=Decimal("0.01"),
        order_request={"symbol": "XAUUSD@", "volume": 0.01},
    )
    if state not in ("NEW", "SUBMITTED"):
        journal.mark_outcome(journal_id, state=state, exit_reason="test fixture")
    elif state == "SUBMITTED":
        journal.mark_submitted(journal_id, broker_order_id="1", submitted_at=datetime.now(UTC).isoformat())
    assert any(r["state"] == state for r in journal.list_orders()), journal.list_orders()


def _bury_under_audit_noise(db, count: int, payload: dict) -> None:
    """Push `count` newer events in, the way a running system would."""
    from qts.domain.events import DomainEvent, EventType
    from qts.observability.audit import SqliteAuditLog

    log = SqliteAuditLog(db_path=db, jsonl_path=db.parent / "audit.jsonl")
    for i in range(count):
        log.emit(DomainEvent(event_type=EventType.TICK, payload={**payload, "seq": i}))


def test_startup_health_reads_the_order_journal_not_an_audit_keyword_scan(tmp_path, monkeypatch):
    """``restore_pending_orders`` must report the durable order state.

    The old probe scanned the last 20 audit events for the substring
    "AMBIGUOUS". That failed OPEN: an order whose outcome is genuinely unknown
    stopped being reported the moment 20 newer events existed.
    """
    from qts.desktop.health import startup_health_check

    monkeypatch.chdir(tmp_path)
    db = tmp_path / "data" / "sqlite" / "qts.db"
    db.parent.mkdir(parents=True)
    _seed_journal(db, state="AMBIGUOUS")
    _bury_under_audit_noise(db, 40, {"note": "routine"})

    pending = next(c for c in startup_health_check()["checks"] if c["name"] == "restore_pending_orders")
    assert pending["passed"] is False, pending["detail"]
    assert "AMBIGUOUS" in pending["detail"]
    assert "qts-abc123" in pending["detail"], "the blocking order must be named, not just counted"


def test_startup_health_does_not_block_on_a_reconciliation_drift_word(tmp_path, monkeypatch):
    """The mirror image: a resolved order must not keep blocking, and a
    reconciliation report carrying ``drift="AMBIGUOUS"`` is a DIFFERENT
    condition — the substring scan conflated the two."""
    from qts.desktop.health import startup_health_check

    monkeypatch.chdir(tmp_path)
    db = tmp_path / "data" / "sqlite" / "qts.db"
    db.parent.mkdir(parents=True)
    _seed_journal(db, state="CLOSED")
    _bury_under_audit_noise(db, 3, {"drift": "AMBIGUOUS", "details": "transport timeout, since resolved"})

    pending = next(c for c in startup_health_check()["checks"] if c["name"] == "restore_pending_orders")
    assert pending["passed"] is True, pending["detail"]
    assert pending["detail"] == "pending/ambiguous orders none"


def test_startup_health_blocks_on_a_submission_with_no_recorded_outcome(tmp_path, monkeypatch):
    """A row still SUBMITTED at startup means a process died mid-order: the
    outcome is UNKNOWN, which is a blocker, not a clean state."""
    from qts.desktop.health import startup_health_check

    monkeypatch.chdir(tmp_path)
    db = tmp_path / "data" / "sqlite" / "qts.db"
    db.parent.mkdir(parents=True)
    _seed_journal(db, state="SUBMITTED")

    pending = next(c for c in startup_health_check()["checks"] if c["name"] == "restore_pending_orders")
    assert pending["passed"] is False, pending["detail"]
    assert "no recorded outcome" in pending["detail"]
    assert "qts-abc123" in pending["detail"]
