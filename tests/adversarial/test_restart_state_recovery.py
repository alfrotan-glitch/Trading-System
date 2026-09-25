"""Adversarial tests for state recovery across a process restart.

Two durable-state defects are covered here. Both were reproduced empirically
before being fixed, and both fail in the UNSAFE direction:

1. ``OrderManager.submit()`` answered a duplicate ``client_order_id`` from the
   DURABLE idempotency store by falling through and constructing a FRESH
   ``PENDING`` order with a new ``order_id``. After a restart the in-memory
   ``orders`` dict is empty while the store still says FILLED, so a replayed
   submission looked like a brand-new economic order instead of a duplicate of
   one already executed.

2. ``ExecutionEngine._load_reconcile_suspend()`` wrapped every exception in
   ``contextlib.suppress`` and returned ``(False, None)``, so a locked or
   corrupt suspension store restarted the engine as HEALTHY — defeating the
   durable-suspend guarantee that the live gate claims to check.

The invariant under test: restart must never make the system look SAFER than
the durable record says it is.
"""

from __future__ import annotations

import contextlib
import sqlite3
import tempfile
from decimal import Decimal
from pathlib import Path

import pytest

from qts.adapters.paper_adapter import RealisticPaperBroker
from qts.domain.events import DomainEvent, EventType
from qts.domain.value_objects import Instrument, OrderIntent, OrderType, Position, Side
from qts.execution.engine import ExecutionEngine, OrderManager, OrderState
from qts.execution.idempotency import IdempotencyStore
from qts.execution.matching import MatchingConfig, MatchingEngine
from qts.observability.audit import InMemoryAuditLog
from qts.portfolio.portfolio import Portfolio
from qts.risk.engine import RiskEngine, RiskLimits


def _intent(client_order_id: str, quantity: str = "0.01") -> OrderIntent:
    return OrderIntent(
        instrument=Instrument(symbol="XAUUSD"),
        side=Side.BUY,
        quantity=Decimal(quantity),
        order_type=OrderType.MARKET,
        client_order_id=client_order_id,
        strategy_id="sma_breakout",
    )


def _order_manager(db: Path) -> tuple[OrderManager, InMemoryAuditLog]:
    audit = InMemoryAuditLog()
    return OrderManager(audit=audit, idempotency=IdempotencyStore(db_path=db)), audit


def _db() -> Path:
    return Path(tempfile.mktemp(suffix=".db"))


# ---------------------------------------------------------------------------
# OrderManager: a duplicate after restart is a DUPLICATE, not a new order
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("persisted", ["FILLED", "PENDING", "ACCEPTED", "PARTIALLY_FILLED", "CANCELLED", "REJECTED"])
def test_duplicate_after_restart_restores_persisted_state_not_a_new_pending(persisted: str):
    db = _db()
    cid = "restart-dup-001"

    # process 1: submit and drive the order to a terminal/known state
    om1, _ = _order_manager(db)
    order1 = om1.submit(_intent(cid))
    assert order1.state is OrderState.PENDING
    om1.update_state(cid, OrderState(persisted))
    assert om1.idempotency.get_status(cid) == persisted
    order_id_1 = order1.order_id
    om1.idempotency.close()

    # process 2: SAME durable store, EMPTY in-memory state (a restart)
    om2, audit2 = _order_manager(db)
    try:
        assert om2.orders == {}, "precondition: a restarted manager has no in-memory orders"
        replay = om2.submit(_intent(cid))

        assert replay.state is OrderState(persisted), (
            f"a duplicate for an id the durable store records as {persisted} must not come back "
            f"as {replay.state.value} — that is a new economic order for an existing one"
        )
        assert replay.state is not OrderState.PENDING or persisted == "PENDING"
        assert replay.reject_reason == "duplicate-persistent"
        # it is flagged as a duplicate in the audit trail
        dup_events = [e for e in audit2.events if e.payload.get("duplicate") is True]
        assert len(dup_events) == 1
        assert dup_events[0].payload["existing_state"] == persisted
        assert dup_events[0].payload["restored"] is True
        assert dup_events[0].payload["persistent"] is True
        # no NEW order was appended to the durable store
        assert om2.idempotency.get_status(cid) == persisted
        # the original submission is still the one recorded in-memory
        assert om2.orders[cid].client_order_id == cid
        assert order_id_1  # the first order id existed; the replay did not reuse the PENDING path
    finally:
        om2.idempotency.close()


def test_duplicate_ambiguous_state_is_preserved_and_never_auto_healed():
    """AMBIGUOUS means "we do not know if the venue took it" — a restart must
    not turn that into a clean PENDING (re-send risk) or a FILLED (invented
    execution). It must come back AMBIGUOUS and say why."""
    db = _db()
    cid = "restart-dup-ambiguous"

    om1, _ = _order_manager(db)
    om1.submit(_intent(cid))
    om1.update_state(cid, OrderState.AMBIGUOUS)
    om1.idempotency.close()

    om2, audit2 = _order_manager(db)
    try:
        replay = om2.submit(_intent(cid))
        assert replay.state is OrderState.AMBIGUOUS
        assert replay.reject_reason == "duplicate-persistent-ambiguous"
        assert om2.idempotency.is_ambiguous(cid) is True
        assert om2.idempotency.should_block(cid) is True
        dup = [e for e in audit2.events if e.payload.get("duplicate") is True]
        assert dup and dup[0].payload["existing_state"] == "AMBIGUOUS"
    finally:
        om2.idempotency.close()


def test_duplicate_with_unreadable_persisted_status_fails_closed_to_rejected():
    """If the durable store says "seen" but its status cannot be mapped to a
    known order state, the duplicate must NOT be presented as a fresh,
    submittable PENDING order. Fail closed to REJECTED."""
    db = _db()
    cid = "restart-dup-corrupt-status"

    store = IdempotencyStore(db_path=db)
    store.record(cid, "NOT_A_REAL_ORDER_STATE")
    assert store.seen(cid) is True
    store.close()

    om, audit = _order_manager(db)
    try:
        replay = om.submit(_intent(cid))
        assert replay.state is OrderState.REJECTED
        assert replay.reject_reason == "duplicate-persistent"
        dup = [e for e in audit.events if e.payload.get("duplicate") is True]
        assert dup and dup[0].payload["persisted_status"] == "NOT_A_REAL_ORDER_STATE"
    finally:
        om.idempotency.close()


def test_first_submission_still_creates_a_pending_order():
    """The duplicate guard must not swallow genuine new orders."""
    db = _db()
    om, audit = _order_manager(db)
    try:
        order = om.submit(_intent("brand-new-001"))
        assert order.state is OrderState.PENDING
        assert order.reject_reason is None
        assert not [e for e in audit.events if e.payload.get("duplicate") is True]
        assert om.idempotency.get_status("brand-new-001") == "PENDING"
    finally:
        om.idempotency.close()


# ---------------------------------------------------------------------------
# ExecutionEngine: durable suspension must survive a restart AND a corrupt store
# ---------------------------------------------------------------------------


def _engine(db: Path, portfolio: Portfolio | None = None) -> ExecutionEngine:
    audit = InMemoryAuditLog()
    return ExecutionEngine(
        OrderManager(audit=audit, idempotency=IdempotencyStore(db_path=db)),
        RiskEngine(RiskLimits(), db_path=db),
        RealisticPaperBroker(),
        MatchingEngine(MatchingConfig()),
        portfolio or Portfolio(initial_balance=Decimal("10000")),
        audit=audit,
        db_path=db,
    )


def test_suspension_persisted_by_one_process_is_restored_by_the_next():
    db = _db()
    eng = _engine(db)
    try:
        assert eng.is_suspended is False
        # real drift: local position the venue does not hold
        eng.portfolio.positions["XAUUSD"] = Position(
            instrument=Instrument(symbol="XAUUSD"),
            quantity=Decimal("0.10"),
            avg_price=Decimal("2000"),
        )
        report = eng.reconcile()
        assert report.drift == "MISSING_POSITION"
        assert report.requires_suspend is True
        assert eng.is_suspended is True
    finally:
        eng.close()

    restarted = _engine(db)
    try:
        assert restarted.is_suspended is True, "durable suspension must survive a restart"
        assert restarted._suspend_reason, "the reason must be restored with the flag"
        restored = [e for e in restarted.audit.events if e.payload.get("drift") == "RESTORED_SUSPEND"]
        assert len(restored) == 1, "restoring a suspension must itself be audited"
    finally:
        restarted.close()


def test_unreadable_reconcile_state_restarts_suspended_not_healthy():
    """A corrupt/locked suspension store must fail CLOSED.

    Before the fix every read error was suppressed and the engine came up
    healthy, so an operator's durable suspension vanished on the next restart
    exactly when the store was in a bad state.
    """
    db = _db()
    eng = _engine(db)
    try:
        # record a real suspension first, so the store is populated
        # (`_persist_reconcile_suspend` only writes the durable row; the
        # in-memory flag is set by the callers that detect the drift)
        eng._suspended = True
        eng._suspend_reason = "operator suspension"
        eng._persist_reconcile_suspend(True, "operator suspension")
        assert eng.is_suspended is True
    finally:
        eng.close()

    # corrupt the store out from under the next process
    for suffix in ("", "-wal", "-shm"):
        with contextlib.suppress(OSError):
            Path(str(db) + suffix).unlink()
    db.write_bytes(b"definitely not a sqlite database file" * 4)

    # the table cannot even be created, so construction surfaces the failure
    # rather than silently starting healthy
    with pytest.raises(sqlite3.DatabaseError):
        _engine(db)

    # and if only the ROW read fails (table present, store damaged after init),
    # the loader itself must answer "suspended"
    db2 = _db()
    eng2 = _engine(db2)
    try:
        suspended, reason = eng2._load_reconcile_suspend()
        assert (suspended, reason) == (False, None), "no row yet == never suspended"
        with _raw_connection(db2) as con:
            con.execute("DROP TABLE reconcile_state")
            con.commit()
        suspended, reason = eng2._load_reconcile_suspend()
        assert suspended is False and reason is None, "missing table honestly means nothing was persisted"

        # a genuine read error (not "no such table") must fail closed
        eng2._init_reconcile_db()
        eng2._persist_reconcile_suspend(True, "real suspension")
        # sanity: with a readable store the real row is restored exactly
        assert eng2._load_reconcile_suspend() == (True, "real suspension")
        with _broken_connection(db2):
            suspended, reason = eng2._load_reconcile_suspend()
        assert suspended is True, "an unreadable suspension store must restart SUSPENDED"
        assert reason and "fail closed" in reason
    finally:
        eng2.close()


@contextlib.contextmanager
def _raw_connection(path: Path):
    from qts.db import connect as db_connect

    with db_connect(path) as con:
        yield con


@contextlib.contextmanager
def _broken_connection(_path: Path):
    """Make the engine's ``db_connect`` raise a non-"no such table" error.

    "database is locked" is the realistic case: another process holds the
    store, so the suspension flag cannot be read at startup.
    """
    import qts.execution.engine as engine_module

    def _boom(*_args, **_kwargs):
        raise sqlite3.OperationalError("database is locked")

    original = engine_module.db_connect
    engine_module.db_connect = _boom
    try:
        yield
    finally:
        engine_module.db_connect = original


def test_persist_reconcile_state_disabled_never_reads_or_writes_the_durable_flag():
    """Isolated research/backtest runs must not disturb production suspension
    state — the same separation ``RiskEngine(persist_kill=False)`` provides."""
    db = _db()
    suspended_writer = _engine(db)
    try:
        suspended_writer._persist_reconcile_suspend(True, "production suspension")
    finally:
        suspended_writer.close()

    audit = InMemoryAuditLog()
    isolated = ExecutionEngine(
        OrderManager(audit=audit, idempotency=IdempotencyStore(db_path=db)),
        RiskEngine(RiskLimits(), db_path=db, persist_kill=False),
        RealisticPaperBroker(),
        MatchingEngine(MatchingConfig()),
        Portfolio(initial_balance=Decimal("10000")),
        audit=audit,
        db_path=db,
        persist_reconcile_state=False,
    )
    try:
        assert isolated.is_suspended is False, "an isolated run must not inherit durable suspension"
        isolated.heal_reconcile("isolated run")
    finally:
        isolated.close()

    # the production suspension must be untouched by the isolated run
    checker = _engine(db)
    try:
        assert checker.is_suspended is True, "an isolated run must not clear production suspension state"
    finally:
        checker.close()


def test_no_trade_event_is_emitted_when_drift_requires_suspension():
    """Drift that suspends must also be reported as a NO_TRADE decision."""
    db = _db()
    eng = _engine(db)
    try:
        eng.portfolio.positions["XAUUSD"] = Position(
            instrument=Instrument(symbol="XAUUSD"),
            quantity=Decimal("0.10"),
            avg_price=Decimal("2000"),
        )
        report = eng.reconcile()
        assert report.requires_suspend is True
        types = [e.event_type for e in eng.audit.events]
        assert EventType.RECONCILE in types
        assert EventType.NO_TRADE in types, "a suspending drift must emit an explicit NO_TRADE decision"
        no_trade = [e for e in eng.audit.events if e.event_type == EventType.NO_TRADE]
        assert no_trade[-1].payload["reason"] == report.drift
        assert isinstance(no_trade[-1], DomainEvent)
    finally:
        eng.close()


def _store_with_table(tmp_path: Path) -> Path:
    """A real qts.db that HAS reconcile_state, so readers get past the
    "no such table" fast path."""
    import qts.db as db_module

    store = tmp_path / "data" / "sqlite" / "qts.db"
    store.parent.mkdir(parents=True, exist_ok=True)
    with db_module.connect(store) as con:
        con.execute(
            "CREATE TABLE IF NOT EXISTS reconcile_state (k INTEGER PRIMARY KEY, suspended INTEGER NOT NULL,"
            " reason TEXT, updated_at TEXT)"
        )
        con.execute("INSERT OR REPLACE INTO reconcile_state VALUES (1,0,'','')")
        con.commit()
    return store


class _FakeEngine:
    """Minimal stand-in exposing only what ``_load_reconcile_suspend`` reads."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path


@contextlib.contextmanager
def _broken_connection_at(_path):
    """``db_connect`` itself raises — the store cannot even be opened."""
    raise sqlite3.OperationalError("database is locked")
    yield  # pragma: no cover - unreachable, makes this a generator


@contextlib.contextmanager
def _broken_query(real_connect, _path):
    """``db_connect`` succeeds but every query raises a locked-store error.

    This is the case the narrow ``except sqlite3.OperationalError`` handlers
    inside the readers are for: the table exists, the row may well say
    SUSPENDED, and the read still fails. Reporting "Healthy" here would be a
    fail-OPEN hole.
    """

    class _LockedConnection:
        def execute(self, *_a, **_k):
            raise sqlite3.OperationalError("database is locked")

        def commit(self) -> None:  # pragma: no cover - never reached
            raise sqlite3.OperationalError("database is locked")

    yield _LockedConnection()


def test_every_reader_fails_closed_when_the_store_cannot_be_opened(tmp_path, monkeypatch):
    """Three components read the SAME durable ``reconcile_state`` row:

    * ``ExecutionEngine._load_reconcile_suspend`` (enforcement / restart),
    * ``live_gate.check_reconciliation_health`` (the LIVE gate),
    * ``api.server._reconciliation_status`` (``/api/health`` + ``/api/risk``).

    None of them may report "not suspended" when the store cannot be read, and
    they must not disagree with each other.
    """
    import qts.db as db_module
    import qts.execution.engine as engine_module
    import qts.lifecycle.live_gate as live_gate
    from qts.api.server import _reconciliation_status
    from qts.lifecycle.live_gate import check_reconciliation_health

    monkeypatch.chdir(tmp_path)
    store = _store_with_table(tmp_path)

    monkeypatch.setattr(engine_module, "db_connect", _broken_connection_at)
    monkeypatch.setattr(live_gate, "db_connect", _broken_connection_at)
    # api.server._reconciliation_status imports qts.db.connect inside the call
    monkeypatch.setattr(db_module, "connect", _broken_connection_at)

    suspended, reason = engine_module.ExecutionEngine._load_reconcile_suspend(_FakeEngine(store))
    assert suspended is True, "engine must restart SUSPENDED when the store cannot be opened"
    assert reason and "fail closed" in reason

    ok, detail = check_reconciliation_health()
    assert ok is False, "the LIVE gate must not pass on an unreadable suspension store"
    assert "locked" in detail

    healthy, status, api_detail = _reconciliation_status()
    assert healthy is False
    assert status == "UNAVAILABLE", f"an unreadable probe must not report {status}"
    assert "locked" in api_detail


def test_every_reader_fails_closed_when_the_query_fails_but_the_store_opens(tmp_path, monkeypatch):
    """The narrower and more dangerous case: the connection succeeds and only
    the SELECT fails. A reader that treats every ``OperationalError`` as
    "no such table" would answer HEALTHY here while the row may say SUSPENDED.
    """
    import qts.db as db_module
    import qts.execution.engine as engine_module
    import qts.lifecycle.live_gate as live_gate
    from qts.api.server import _reconciliation_status
    from qts.lifecycle.live_gate import check_reconciliation_health

    monkeypatch.chdir(tmp_path)
    store = _store_with_table(tmp_path)
    real_connect = db_module.connect

    def _opens_then_locks(path, **kwargs):
        return _broken_query(real_connect, path)

    monkeypatch.setattr(engine_module, "db_connect", _opens_then_locks)
    monkeypatch.setattr(live_gate, "db_connect", _opens_then_locks)
    monkeypatch.setattr(db_module, "connect", _opens_then_locks)

    suspended, reason = engine_module.ExecutionEngine._load_reconcile_suspend(_FakeEngine(store))
    assert suspended is True
    assert reason and "fail closed" in reason

    ok, detail = check_reconciliation_health()
    assert ok is False, "a failed SELECT must not pass the LIVE gate as 'no reconcile_state recorded'"
    assert "fail closed" in detail

    healthy, status, api_detail = _reconciliation_status()
    assert healthy is False
    assert status == "UNAVAILABLE"
    assert "fail closed" in api_detail


def test_missing_reconcile_table_is_benign_for_every_reader(tmp_path, monkeypatch):
    """The mirror image: a store with NO ``reconcile_state`` table means nothing
    was ever persisted. That is honestly "not suspended" for all three readers —
    failing closed here would make the gate depend on which subsystem happened
    to create qts.db first."""
    import qts.db as db_module
    from qts.api.server import _reconciliation_status
    from qts.lifecycle.live_gate import check_reconciliation_health

    monkeypatch.chdir(tmp_path)
    store = tmp_path / "data" / "sqlite" / "qts.db"
    store.parent.mkdir(parents=True, exist_ok=True)
    with db_module.connect(store) as con:
        con.execute("CREATE TABLE unrelated (x INTEGER)")
        con.commit()

    ok, detail = check_reconciliation_health()
    assert ok is True, detail
    assert "no reconcile_state table" in detail

    healthy, status, api_detail = _reconciliation_status()
    assert healthy is True
    assert status == "Healthy"
    assert "no reconcile state recorded" in api_detail

    eng = _engine(store)
    try:
        assert eng._load_reconcile_suspend() == (False, None)
    finally:
        eng.close()
