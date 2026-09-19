"""OBSERVE-ONLY runtime collection: REAL ticks, ZERO orders (fail-closed).

Pins the Phase-9 contract:

- ``start()`` creates exactly ONE forward-observation session and persists
  ticks with the full auditable timestamp basis (broker_time_raw,
  server_utc_offset_s, timestamp_basis, provenance) — REAL data only.
- Duplicate start is idempotent (same session, one thread, one session row);
  a restart after a completed stop creates a NEW session.
- Readiness failure blocks the start fail-closed (state ``BLOCKED``, no
  thread, no session rows).
- Terminal disconnect / stale quotes fail closed: the collector auto-stops
  (``STOPPED_ON_ERRORS``), persists the session end, and never fabricates
  rows for rejected data.
- A frozen feed (identical raw quote repeated) is recorded ONCE, further
  duplicates counted — never re-observed as new data.
- ``stop()`` is deterministic: thread joined, session ENDED + end timestamp
  persisted, evidence manifest rewritten with ``class: DEMO`` and
  ``orders_submitted: 0``.
- Terminal-error semantics: a normal operator stop persists ``ENDED`` with NO
  terminal ``error`` even when a transient runtime error occurred earlier and
  collection recovered; only an error auto-stop (``ENDED_ON_ERRORS``) carries
  the terminal failure reason. ``last_error`` remains a runtime diagnostic
  surfaced in ``status()``/the derived manifest, never a failure cause
  (FS-aeb881).
- ``order_send`` / order submission / the observatory's simulation helper are
  unreachable from the observe-only path: proven structurally (AST call scan
  of the collector module and every observe endpoint) AND at runtime (the
  fake MT5 raises ``AssertionError`` from ``order_send``; call log stays empty).
- API lifecycle (start/status/stop) and the UI wiring are pinned end to end.
"""

from __future__ import annotations

import ast
import inspect
import json
import re
import sqlite3
import time
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from qts.adapters.market_data import MarketDataProvider
from qts.adapters.mt5_adapter import MT5Adapter
from qts.db import connect as db_connect
from qts.domain.value_objects import Instrument, uuid7
from qts.observability.demo_collector import ObservationCollector
from qts.observability.forward_observatory import ForwardObservatory, ObservationTick
from qts.observability.session_export import export_session_evidence, verify_session_export

BROKER_OFFSET_S = 10800  # UTC+3, like the verified WMMarkets-Demo server
PASSED_READINESS: dict[str, Any] = {
    "passed": True,
    "demo_enabled": True,
    "blocked_reasons": [],
    "checks": {f"check-{i}": True for i in range(14)},
    "timestamp": "2026-09-17T00:00:00+00:00",
}
FAILED_READINESS: dict[str, Any] = {
    "passed": False,
    "demo_enabled": False,
    "blocked_reasons": ["Terminal not running"],
    "checks": {},
    "timestamp": "2026-09-17T00:00:00+00:00",
}


class _RawTick:
    def __init__(self, time_s: float, time_msc: int, bid: float, ask: float) -> None:
        self.time = time_s
        self.time_msc = time_msc
        self.bid = bid
        self.ask = ask
        self.last = 0.0
        self.volume = 0
        self.flags = 0
        self.volume_real = 0.0


class _SI:
    trade_mode = 4
    currency_base = "XAU"
    currency_profit = "USD"
    currency_margin = "XAU"
    digits = 2
    point = 0.01
    trade_tick_size = 0.01
    trade_tick_value = 1.0
    trade_contract_size = 100.0
    visible = True
    description = "Gold vs US Dollar"
    path = "Metals\\XAUUSD@"
    trade_stops_level = 0
    trade_freeze_level = 0
    volume_min = 0.01
    volume_max = 100.0
    volume_step = 0.01
    spread = 25
    trade_exemode = 2
    filling_mode = 1


class LiveFakeMT5:
    """MT5 double serving REAL-shaped live data.

    modes:
      live       fresh quote every poll (broker basis, age ~0.5s)
      disconnect symbol_info_tick -> None (terminal/quote feed down)
      stale      quote 600s old on the broker clock (dead feed, honest stamps)
      frozen     identical raw quote repeated (integer stamp; frozen bar too)

    ``order_send`` is a runtime sentinel: calling it from the observe-only
    path raises AssertionError and is recorded in ``order_send_calls``.
    """

    TIMEFRAME_M1 = 1

    def __init__(self, mode: str = "live", offset_s: int = BROKER_OFFSET_S) -> None:
        self.mode = mode
        self.offset_s = offset_s
        self.order_send_calls: list[Any] = []
        if mode == "frozen":
            self._frozen_stamp = float(int(time.time()) + offset_s)
            self._frozen_tick = _RawTick(
                time_s=self._frozen_stamp,
                time_msc=int(self._frozen_stamp * 1000),
                bid=2000.0,
                ask=2000.5,
            )

    def order_send(self, *args: Any, **kwargs: Any) -> None:
        self.order_send_calls.append((args, kwargs))
        raise AssertionError("order_send must never be called from the OBSERVE-ONLY path")

    def symbol_info_tick(self, symbol: str) -> _RawTick | None:
        if self.mode == "disconnect":
            return None
        if self.mode == "frozen":
            return self._frozen_tick
        age_s = 600.0 if self.mode == "stale" else 0.5
        stamp = time.time() + self.offset_s - age_s
        return _RawTick(time_s=stamp, time_msc=int(stamp * 1000), bid=2000.0, ask=2000.5)

    def copy_rates_from_pos(self, symbol: str, timeframe: int, start: int, count: int) -> Any:
        if self.mode == "disconnect":
            return None
        if self.mode == "frozen":
            # dead feed: the forming bar is frozen at the quote stamp too
            return [{"time": int(self._frozen_stamp)}]
        return [{"time": int(time.time() + self.offset_s - 30)}]

    def symbol_info(self, symbol: str) -> _SI:
        return _SI()

    def symbol_select(self, symbol: str, flag: bool) -> bool:
        return True

    def last_error(self) -> tuple[int, str]:
        return (1, "ok")


def _wait_for(predicate: Any, timeout: float = 6.0, step: float = 0.05) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return bool(predicate())


def _make_collector(tmp_path: Path, fake: LiveFakeMT5, **overrides: Any) -> tuple[ObservationCollector, LiveFakeMT5]:
    kwargs: dict[str, Any] = {
        "interval_s": 0.2,
        "max_consecutive_failures": 40,
        "manifest_every_ticks": 5,
    }
    kwargs.update(overrides)
    adapter = MT5Adapter(
        config={"symbol_map": {"XAUUSD": "XAUUSD@"}},
        mt5_module=fake,
        db_path=tmp_path / "adapter.db",
    )
    collector = ObservationCollector(
        provider=MarketDataProvider(broker=adapter),
        observatory=ForwardObservatory(db_path=tmp_path / "obs.db"),
        instrument=Instrument(symbol="XAUUSD", venue="MT5"),
        broker_symbol="XAUUSD@",
        manifest_path=tmp_path / "manifest.json",
        **kwargs,
    )
    return collector, fake


def _tick_rows(db_path: Path) -> list[dict[str, Any]]:
    """observation_ticks schema: (id, payload JSON, created_at)."""
    with db_connect(db_path) as con:
        rows = con.execute("select payload from observation_ticks order by created_at").fetchall()
    return [json.loads(r[0]) for r in rows]


def _session_rows(db_path: Path) -> list[dict[str, Any]]:
    """observation_sessions schema: (id, start, end, status, meta)."""
    with db_connect(db_path) as con:
        rows = con.execute("select id, start, end, status, meta from observation_sessions").fetchall()
    return [{"id": r[0], "start": r[1], "end": r[2], "status": r[3], "meta": r[4]} for r in rows]


# ---------------------------------------------------------------------------
# happy path: DEMO-class session + fully auditable rows + derived manifest
# ---------------------------------------------------------------------------


def test_start_creates_session_and_persists_real_ticks_with_full_audit(tmp_path: Path) -> None:
    collector, fake = _make_collector(tmp_path, LiveFakeMT5("live"))
    status = collector.start(PASSED_READINESS)
    try:
        assert status["state"] == "OBSERVING"
        assert status["session_id"].startswith("FS-")
        assert status["orders_submitted"] == 0
        assert collector.thread_alive
        assert _wait_for(lambda: collector.ticks_recorded >= 2), collector.last_error
    finally:
        stopped = collector.stop()

    assert stopped["state"] == "STOPPED"
    assert stopped["stopped_at"]
    assert stopped["ticks_recorded"] >= 2
    assert not collector.thread_alive
    # ZERO orders — runtime sentinel never tripped
    assert fake.order_send_calls == []

    db = tmp_path / "obs.db"
    sessions = _session_rows(db)
    assert len(sessions) == 1
    assert sessions[0]["status"] == "ENDED" and sessions[0]["end"]
    # Canonical session identity (finding #5): env/broker/symbol/lineage meta
    meta = json.loads(sessions[0]["meta"])
    assert meta.get("kind") == "LIVE_OBSERVATION"
    assert meta.get("broker_symbol") == "XAUUSD@"
    assert meta.get("orders_possible") is False
    assert meta.get("code_version")

    ticks = _tick_rows(db)
    assert len(ticks) == stopped["ticks_recorded"] >= 2
    for row in ticks:
        assert row["symbol"] == "XAUUSD@"
        # Decimal fields serialize as JSON strings in pydantic v2
        assert float(row["bid"]) == 2000.0 and float(row["ask"]) == 2000.5
        assert row["spread_bps"] == pytest.approx((2000.5 - 2000.0) / 2000.25 * 10000)
        assert row["broker_event_time"] is not None
        assert row["broker_time_raw"] > 1_600_000_000.0
        assert row["server_utc_offset_s"] == float(BROKER_OFFSET_S)
        assert row["timestamp_basis"] == "broker-normalized(measured-m1-bar)"
        assert row["tick_provenance"]["broker_symbol"] == "XAUUSD@"
        received = datetime.fromisoformat(str(row["tick_provenance"]["received_at"]))
        assert received.tzinfo is not None  # true-UTC aware receipt time
        assert abs((datetime.now(UTC) - received).total_seconds()) < 120
        assert row["data_freshness_ms"] is not None and row["data_freshness_ms"] < 5000.0

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["class"] == "DEMO"
    assert manifest["orders_submitted"] == 0
    assert manifest["order_send_called"] is False
    assert manifest["ticks_recorded"] == len(ticks)
    assert manifest["symbols"] == ["XAUUSD@"]
    assert manifest["timestamp_bases"] == {"broker-normalized(measured-m1-bar)": len(ticks)}
    assert manifest["state"] == "STOPPED"
    assert manifest["session"]["status"] == "ENDED"
    assert manifest["duplicates_skipped"] == 0


# ---------------------------------------------------------------------------
# idempotency / lifecycle
# ---------------------------------------------------------------------------


def test_duplicate_start_reuses_running_session(tmp_path: Path) -> None:
    collector, _ = _make_collector(tmp_path, LiveFakeMT5("live"))
    first = collector.start(PASSED_READINESS)
    thread = collector._thread
    try:
        second = collector.start(PASSED_READINESS)
        assert second["state"] == "OBSERVING"
        assert second["session_id"] == first["session_id"]
        assert collector._thread is thread  # no duplicate poll thread
        assert _wait_for(lambda: collector.ticks_recorded >= 1)
    finally:
        collector.stop()
    sessions = _session_rows(tmp_path / "obs.db")
    assert len(sessions) == 1  # exactly one session despite two starts


def test_restart_after_stop_creates_new_session(tmp_path: Path) -> None:
    collector, _ = _make_collector(tmp_path, LiveFakeMT5("live"))
    first = collector.start(PASSED_READINESS)
    collector.stop()
    second = collector.start(PASSED_READINESS)
    try:
        assert second["state"] == "OBSERVING"
        assert second["session_id"] != first["session_id"]
    finally:
        collector.stop()
    sessions = _session_rows(tmp_path / "obs.db")
    assert len(sessions) == 2
    assert all(s["status"] == "ENDED" and s["end"] for s in sessions)


def test_readiness_failure_blocks_start_fail_closed(tmp_path: Path) -> None:
    collector, _ = _make_collector(tmp_path, LiveFakeMT5("live"))
    status = collector.start(FAILED_READINESS)
    assert status["state"] == "BLOCKED"
    assert "Terminal not running" in status["blocked_reasons"]
    assert not collector.thread_alive
    assert collector._thread is None
    assert collector.stop()["state"] == "BLOCKED"  # stop is safe, nothing to end
    with db_connect(tmp_path / "obs.db") as con:
        assert con.execute("select count(*) c from observation_sessions").fetchone()[0] == 0
        assert con.execute("select count(*) c from observation_ticks").fetchone()[0] == 0
    assert not (tmp_path / "manifest.json").exists()  # no evidence manufactured


def test_interval_is_clamped_to_safe_bounds(tmp_path: Path) -> None:
    fast, _ = _make_collector(tmp_path, LiveFakeMT5("live"), interval_s=0.001)
    slow, _ = _make_collector(tmp_path, LiveFakeMT5("live"), interval_s=999.0)
    assert fast.interval_s == 0.2
    assert slow.interval_s == 60.0


# ---------------------------------------------------------------------------
# fail-closed behavior
# ---------------------------------------------------------------------------


def test_terminal_disconnect_auto_stops_fail_closed(tmp_path: Path) -> None:
    collector, fake = _make_collector(tmp_path, LiveFakeMT5("disconnect"), max_consecutive_failures=3)
    status = collector.start(PASSED_READINESS)
    assert status["state"] == "OBSERVING"
    assert _wait_for(lambda: collector.state == "STOPPED_ON_ERRORS"), collector.last_error
    assert collector.ticks_recorded == 0
    assert "no tick available" in (collector.last_error or "")
    assert fake.order_send_calls == []

    sessions = _session_rows(tmp_path / "obs.db")
    # Honest terminal status: an error auto-stop is ENDED_ON_ERRORS, not a
    # clean ENDED (session completion must not be misrepresented, finding #36).
    assert len(sessions) == 1 and sessions[0]["status"] == "ENDED_ON_ERRORS"
    assert sessions[0]["meta"]
    assert _tick_rows(tmp_path / "obs.db") == []
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["class"] == "DEMO" and manifest["ticks_recorded"] == 0
    assert manifest["orders_submitted"] == 0


def test_stale_quotes_are_never_persisted(tmp_path: Path) -> None:
    collector, _ = _make_collector(tmp_path, LiveFakeMT5("stale"), max_consecutive_failures=3)
    collector.start(PASSED_READINESS)
    assert _wait_for(lambda: collector.state == "STOPPED_ON_ERRORS"), collector.last_error
    assert "stale" in (collector.last_error or "")
    assert collector.ticks_recorded == 0
    assert _tick_rows(tmp_path / "obs.db") == []
    sessions = _session_rows(tmp_path / "obs.db")
    assert sessions[0]["status"] == "ENDED_ON_ERRORS"  # honest terminal status


def test_frozen_duplicate_quotes_recorded_once(tmp_path: Path) -> None:
    collector, _ = _make_collector(tmp_path, LiveFakeMT5("frozen"))
    collector.start(PASSED_READINESS)
    try:
        assert _wait_for(lambda: collector.ticks_recorded == 1 and collector.duplicates_skipped >= 2, timeout=4.0), (
            f"recorded={collector.ticks_recorded} dups={collector.duplicates_skipped} err={collector.last_error}"
        )
    finally:
        collector.stop()
    ticks = _tick_rows(tmp_path / "obs.db")
    assert len(ticks) == 1  # one REAL quote, never re-observed as new data
    assert ticks[0]["timestamp_basis"] == "broker-normalized(measured-m1-bar)"


# ---------------------------------------------------------------------------
# storage/manifest failures are failure-accounted, never silently fatal
# ---------------------------------------------------------------------------


def _failing_record_tick(_tick: Any) -> None:
    """Stand-in for a duplicate-ID collision or any write/manifest error."""
    raise sqlite3.IntegrityError("UNIQUE constraint failed: observation_ticks.id")


def test_storage_failure_is_accounted_and_collection_recovers(tmp_path: Path) -> None:
    """A transient write error must not kill the poll thread silently.

    Pre-fix, the exception escaped ``_poll_once``: the session kept advertising
    OBSERVING, ``consecutive_failures`` stayed 0, ``last_error`` stayed None and
    the session row stayed ACTIVE with no reason — collection was dead and could
    not be resumed until the operator pressed Stop.
    """
    collector, fake = _make_collector(tmp_path, LiveFakeMT5("live"), max_consecutive_failures=40)
    collector.start(PASSED_READINESS)
    assert _wait_for(lambda: collector.ticks_recorded >= 2), collector.last_error
    real = collector.observatory.record_tick
    collector.observatory.record_tick = _failing_record_tick
    try:
        assert _wait_for(lambda: collector.consecutive_failures >= 1), "storage failure was not accounted"
        assert "IntegrityError" in (collector.last_error or "")  # diagnostic recorded
        assert collector.state == "OBSERVING" and collector.thread_alive  # not silently fatal
    finally:
        collector.observatory.record_tick = real
    recorded = collector.ticks_recorded
    assert _wait_for(lambda: collector.consecutive_failures == 0 and collector.ticks_recorded > recorded), (
        "collection did not recover after storage healed"
    )
    stopped = collector.stop()
    assert stopped["state"] == "STOPPED"
    sessions = _session_rows(tmp_path / "obs.db")
    assert sessions[0]["status"] == "ENDED" and "error" not in json.loads(sessions[0]["meta"])
    assert fake.order_send_calls == []


def test_sustained_storage_failure_auto_stops_with_persisted_terminal_state(tmp_path: Path) -> None:
    """Sustained write failure auto-stops under the EXISTING tolerance."""
    collector, fake = _make_collector(tmp_path, LiveFakeMT5("live"), max_consecutive_failures=3)
    collector.start(PASSED_READINESS)
    assert _wait_for(lambda: collector.ticks_recorded >= 1), collector.last_error
    collector.observatory.record_tick = _failing_record_tick
    assert _wait_for(lambda: collector.state == "STOPPED_ON_ERRORS"), collector.last_error
    assert not collector.thread_alive
    terminal = collector.last_error
    assert terminal and "IntegrityError" in terminal

    sessions = _session_rows(tmp_path / "obs.db")
    meta = json.loads(sessions[0]["meta"])
    assert sessions[0]["status"] == "ENDED_ON_ERRORS"  # persisted terminal state, not silent OBSERVING
    assert sessions[0]["end"] and meta.get("error") == terminal

    art = export_session_evidence(collector.session_id, db_path=collector.observatory.db_path)
    assert art["session"]["status"] == "ENDED_ON_ERRORS"
    verdict = verify_session_export(art)
    assert verdict["verdict"] == "CONSISTENT", verdict
    assert fake.order_send_calls == []


# ---------------------------------------------------------------------------
# manifest failures, terminal persistence, and record identity
# ---------------------------------------------------------------------------


def test_manifest_failure_is_accounted_and_collection_recovers(tmp_path: Path) -> None:
    """A DERIVED-manifest write error is a counted failure, never a silent death."""
    collector, fake = _make_collector(
        tmp_path, LiveFakeMT5("live"), max_consecutive_failures=40, manifest_every_ticks=1
    )
    collector.start(PASSED_READINESS)
    assert _wait_for(lambda: collector.ticks_recorded >= 1), collector.last_error
    real = collector.write_manifest

    def boom(*_a: Any, **_k: Any) -> dict[str, Any]:
        raise OSError(28, "No space left on device")

    collector.write_manifest = boom
    try:
        assert _wait_for(lambda: collector.consecutive_failures >= 1), "manifest failure was not accounted"
        assert "OSError" in (collector.last_error or "")
        assert collector.state == "OBSERVING" and collector.thread_alive
        recorded = collector.ticks_recorded
    finally:
        collector.write_manifest = real
    assert _wait_for(lambda: collector.consecutive_failures == 0 and collector.ticks_recorded > recorded)
    stopped = collector.stop()
    assert stopped["state"] == "STOPPED"
    assert fake.order_send_calls == []


def test_terminal_manifest_failure_cannot_block_session_end(tmp_path: Path) -> None:
    """stop() must still persist ENDED and flip state when the manifest write fails."""
    collector, fake = _make_collector(tmp_path, LiveFakeMT5("live"))
    collector.start(PASSED_READINESS)
    assert _wait_for(lambda: collector.ticks_recorded >= 1), collector.last_error

    def boom(*_a: Any, **_k: Any) -> dict[str, Any]:
        raise OSError(28, "No space left on device")

    collector.write_manifest = boom
    stopped = collector.stop()  # must NOT raise into the caller / API handler

    assert stopped["state"] == "STOPPED"  # truthful terminal state, not a stuck OBSERVING
    assert not collector.thread_alive
    assert "terminal manifest write failed" in (stopped["last_error"] or "")  # loud diagnostic
    sessions = _session_rows(tmp_path / "obs.db")
    assert sessions[0]["status"] == "ENDED" and "error" not in json.loads(sessions[0]["meta"])
    art = export_session_evidence(stopped["session_id"], db_path=collector.observatory.db_path)
    assert art["session"]["status"] == "ENDED"
    assert verify_session_export(art)["verdict"] == "CONSISTENT"
    assert fake.order_send_calls == []


def test_terminal_persist_failure_is_loud_and_never_leaves_worker_untrusted(tmp_path: Path) -> None:
    """If storage is down at the transition the state is still terminal and loud,
    and `stop()` retries the row so it cannot stay ACTIVE forever."""
    collector, fake = _make_collector(tmp_path, LiveFakeMT5("live"))
    collector.start(PASSED_READINESS)
    assert _wait_for(lambda: collector.ticks_recorded >= 1), collector.last_error

    real = collector.observatory.end_session
    calls = {"n": 0}

    def flaky(session_id: str, *, status: str = "ENDED", error: str | None = None) -> None:
        calls["n"] += 1
        if calls["n"] <= 3:  # every bounded attempt fails
            raise sqlite3.OperationalError("database is locked")
        real(session_id, status=status, error=error)

    collector.observatory.end_session = flaky
    stopped = collector.stop()

    # never silently OBSERVING/ACTIVE: state is terminal and the failure is loud
    assert stopped["state"] == "STOPPED"
    assert not collector.thread_alive
    assert "terminal session persist failed" in (stopped["last_error"] or "")
    assert _session_rows(tmp_path / "obs.db")[0]["status"] == "ACTIVE"  # storage was down
    assert collector._terminal_persist_pending is True

    # storage recovers -> the operator's Stop retries and the row becomes terminal
    retry_status = collector.stop()
    row = _session_rows(tmp_path / "obs.db")[0]
    assert row["status"] == "ENDED" and row["end"]
    assert collector._terminal_persist_pending is False
    assert retry_status["stopped_at"] == row["end"]
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["state"] == "STOPPED" and manifest["stopped_at"] == row["end"]
    assert manifest["session"]["end"] == row["end"]
    art = export_session_evidence(collector.session_id, db_path=collector.observatory.db_path)
    assert art["session"]["status"] == "ENDED"
    assert verify_session_export(art)["verdict"] == "CONSISTENT"
    assert fake.order_send_calls == []


def test_record_identity_is_collision_resistant_and_session_ids_stay_canonical() -> None:
    """Record IDs carry full 128-bit entropy; session IDs keep the FS-<6 hex> contract."""
    ids = {ObservationTick(symbol="XAUUSD@").id for _ in range(500)}
    assert len(ids) == 500
    assert all(re.fullmatch(r"OT-[0-9a-f]{32}", i) for i in ids)  # was 6 hex chars (24 bits)
    assert all(re.fullmatch(r"FS-[0-9a-f]{6}", f"FS-{uuid7()[:6]}") for _ in range(50))  # unchanged


def test_duplicate_record_id_is_refused_not_overwritten(tmp_path: Path) -> None:
    """Append-only identity: a duplicate record ID refuses, never replaces."""
    observatory = ForwardObservatory(db_path=tmp_path / "obs.db")
    sid = observatory.start_session(meta={"orders_possible": False, "broker_symbol": "XAUUSD@"})
    first = ObservationTick(
        symbol="XAUUSD@",
        bid=Decimal("2000.0"),
        ask=Decimal("2000.5"),
        provenance="DEMO",
        broker_event_time=datetime.now(UTC),
        broker_time_raw=1_750_000_000.0,
        server_utc_offset_s=10800.0,
        timestamp_basis="broker-normalized(measured-m1-bar)",
        tick_provenance={"mt5_time": 1_750_000_000.0, "mt5_time_msc": 1_750_000_000_007},
        session_id=sid,
    )
    observatory.record_tick(first)
    clash = first.model_copy(deep=True)
    clash.bid = Decimal("1999.0")  # conflicting payload, identical identity
    with pytest.raises(sqlite3.IntegrityError):
        observatory.record_tick(clash)
    stored = _tick_rows(tmp_path / "obs.db")
    assert len(stored) == 1 and float(stored[0]["bid"]) == 2000.0  # original preserved


def test_session_id_collision_never_replaces_existing_session(tmp_path: Path) -> None:
    """Session IDs keep the v1 canonical format and collide loudly, never replace."""
    observatory = ForwardObservatory(db_path=tmp_path / "obs.db")
    sid = observatory.start_session(session_id="FS-abcdef", meta={"kind": "LIVE_OBSERVATION", "orders_possible": False})
    assert re.fullmatch(r"FS-[0-9a-f]{6}", sid)
    with pytest.raises(sqlite3.IntegrityError):
        observatory.start_session(session_id="FS-abcdef", meta={"kind": "OTHER", "orders_possible": False})
    row = observatory.session("FS-abcdef")
    assert row["status"] == "ACTIVE" and row["meta"]["kind"] == "LIVE_OBSERVATION"  # original preserved


def test_record_id_collision_is_accounted_and_exports_truthfully(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A genuine duplicate-insertion collision is accounted, not fatal."""
    collector, fake = _make_collector(tmp_path, LiveFakeMT5("live"), max_consecutive_failures=40)
    collector.start(PASSED_READINESS)
    assert _wait_for(lambda: collector.ticks_recorded >= 2), collector.last_error
    recorded = collector.ticks_recorded
    with monkeypatch.context() as mp:
        # every new record gets the SAME identity -> real UNIQUE collisions
        mp.setattr("qts.domain.value_objects.uuid.uuid4", lambda: uuid.UUID("00000000-0000-4000-8000-000000000009"))
        assert _wait_for(lambda: collector.consecutive_failures >= 1), "collision was not accounted"
        assert "IntegrityError" in (collector.last_error or "")
        assert collector.state == "OBSERVING" and collector.thread_alive  # thread survived
        assert collector.ticks_recorded <= recorded + 1  # duplicates never inserted
    assert _wait_for(lambda: collector.consecutive_failures == 0 and collector.ticks_recorded > recorded), (
        "collection did not recover once identity was unique again"
    )
    stopped = collector.stop()
    rows = _tick_rows(tmp_path / "obs.db")
    assert len(rows) == stopped["ticks_recorded"]  # no silent overwrite, no lost rows
    assert len({r["id"] for r in rows}) == len(rows)  # every stored record uniquely identified
    art = export_session_evidence(stopped["session_id"], db_path=collector.observatory.db_path)
    assert verify_session_export(art)["verdict"] == "CONSISTENT"
    assert art["session"]["status"] == "ENDED"
    assert fake.order_send_calls == []


# ---------------------------------------------------------------------------
# terminal-error semantics: transient runtime errors are not failure causes
# ---------------------------------------------------------------------------


def test_transient_error_then_recovery_then_manual_stop_has_no_terminal_error(tmp_path: Path) -> None:
    """FS-aeb881 shape: transient stale-tick error, recovery, normal stop.

    The operator stop is ENDED with NO terminal `error` — `last_error` is a
    runtime diagnostic and must not be promoted to failure cause. The stale
    diagnostic stays legitimately surfaced in status()/the derived manifest.
    """
    collector, fake = _make_collector(tmp_path, LiveFakeMT5("live"), max_consecutive_failures=40)
    collector.start(PASSED_READINESS)
    # early transient failure: feed goes stale for a moment, then recovers
    fake.mode = "stale"
    assert _wait_for(lambda: collector.consecutive_failures >= 1), "expected a transient failure"
    transient = collector.last_error
    fake.mode = "live"
    assert _wait_for(lambda: collector.consecutive_failures == 0 and collector.ticks_recorded >= 1), (
        f"collection did not recover: {collector.last_error}"
    )
    stopped = collector.stop()

    assert stopped["state"] == "STOPPED"
    assert stopped["consecutive_failures"] == 0
    assert "stale" in (stopped["last_error"] or "")  # diagnostic preserved at runtime
    assert fake.order_send_calls == []

    sessions = _session_rows(tmp_path / "obs.db")
    assert len(sessions) == 1
    meta = json.loads(sessions[0]["meta"])
    assert sessions[0]["status"] == "ENDED"
    assert meta.get("ended_at") == sessions[0]["end"]
    assert "error" not in meta  # a normal operator stop declares no terminal error

    # the derived manifest keeps the diagnostic, without a terminal failure claim
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["state"] == "STOPPED"
    assert manifest["last_error"] == transient
    assert manifest["orders_submitted"] == 0

    art = export_session_evidence(stopped["session_id"], db_path=collector.observatory.db_path)
    assert art["session"]["status"] == "ENDED"
    assert "error" not in art["session"]["meta_sanitized"]
    verdict = verify_session_export(art)
    assert verdict["verdict"] == "CONSISTENT", verdict
    assert verdict["violations"] == []


def test_genuine_error_autostop_still_carries_terminal_error(tmp_path: Path) -> None:
    """A real error auto-stop keeps its terminal cause and verifies correctly."""
    collector, fake = _make_collector(tmp_path, LiveFakeMT5("disconnect"), max_consecutive_failures=3)
    collector.start(PASSED_READINESS)
    assert _wait_for(lambda: collector.state == "STOPPED_ON_ERRORS"), collector.last_error
    terminal = collector.last_error
    assert terminal and "no tick available" in terminal

    sessions = _session_rows(tmp_path / "obs.db")
    meta = json.loads(sessions[0]["meta"])
    assert sessions[0]["status"] == "ENDED_ON_ERRORS"
    assert meta.get("error") == terminal  # required terminal failure reason

    art = export_session_evidence(collector.session_id, db_path=collector.observatory.db_path)
    assert art["session"]["status"] == "ENDED_ON_ERRORS"
    assert art["session"]["meta_sanitized"]["error"] == terminal
    verdict = verify_session_export(art)
    assert verdict["verdict"] == "CONSISTENT", verdict
    assert any("ended on errors" in note for note in verdict["notes"])
    assert fake.order_send_calls == []


# ---------------------------------------------------------------------------
# structural safety: no order / simulation path exists
# ---------------------------------------------------------------------------


def _called_names(src: str) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                names.add(func.attr)
            elif isinstance(func, ast.Name):
                names.add(func.id)
    return names


FORBIDDEN_CALLS = {"order_send", "simulate_observation", "submit_order", "send_order", "place_order"}


def test_collector_module_has_no_order_or_simulation_call_paths() -> None:
    import qts.observability.demo_collector as dc

    names = _called_names(Path(inspect.getsourcefile(dc) or dc.__file__).read_text(encoding="utf-8"))
    assert names & FORBIDDEN_CALLS == set()
    assert "get_tick" in names  # the ONLY broker touchpoint


def test_observe_endpoints_have_no_order_or_simulation_call_paths() -> None:
    import qts.api.server as srv

    for fn in (srv.observe_start, srv.observe_status, srv.observe_stop, srv._build_observe_collector):
        names = _called_names(inspect.getsource(fn))
        assert names & FORBIDDEN_CALLS == set(), fn.__name__


# ---------------------------------------------------------------------------
# API lifecycle (factory injected; readiness monkeypatched)
# ---------------------------------------------------------------------------


@pytest.fixture()
def _observe_state_reset():
    import qts.api.server as srv

    def _clear() -> None:
        with srv._OBSERVE_LOCK:
            existing = srv._OBSERVE_STATE.get("collector")
            if existing is not None and existing.state == "OBSERVING":
                existing.stop()
            srv._OBSERVE_STATE["collector"] = None

    _clear()
    yield
    _clear()


def _api_client():
    from fastapi.testclient import TestClient

    from qts.api.server import app

    return TestClient(app)


def test_api_start_status_stop_lifecycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _observe_state_reset: None
) -> None:
    import qts.api.server as srv
    import qts.lifecycle.demo_gate as dg

    setup_file = tmp_path / "setup.json"
    setup_file.write_text(
        json.dumps({"symbol": "XAUUSD", "symbol_map": {"XAUUSD": "XAUUSD@"}, "terminal_path": "C:\\MT5"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("QTS_SETUP_FILE", str(setup_file))
    monkeypatch.setattr(dg, "demo_forward_readiness_report", lambda **kwargs: dict(PASSED_READINESS))
    fakes: list[LiveFakeMT5] = []

    def fake_factory(terminal_path: Any, requested: str, broker: str, interval_s: float) -> ObservationCollector:
        fake = LiveFakeMT5("live")
        fakes.append(fake)
        collector, _ = _make_collector(tmp_path, fake, interval_s=interval_s)
        assert broker == "XAUUSD@" and requested == "XAUUSD"
        return collector

    monkeypatch.setattr(srv, "_build_observe_collector", fake_factory)

    with _api_client() as client:
        r = client.post("/api/observe/start", json={"interval_s": 0.2})
        assert r.status_code == 200
        body = r.json()
        assert body["started"] is True
        session_id = body["status"]["session_id"]

        # duplicate start -> idempotent, same session
        r2 = client.post("/api/observe/start", json={"interval_s": 0.2}).json()
        assert r2["started"] is False and r2["reason"] == "already_running"
        assert r2["status"]["session_id"] == session_id
        assert len(fakes) == 1  # factory called exactly once

        st = client.get("/api/observe/status").json()
        assert st["state"] == "OBSERVING" and st["symbol"] == "XAUUSD@" and st["mode"] == "OBSERVE_ONLY"
        assert st["orders_submitted"] == 0

        r3 = client.post("/api/observe/stop").json()
        assert r3["stopped"] is True and r3["status"]["state"] == "STOPPED"
        st2 = client.get("/api/observe/status").json()
        assert st2["state"] == "STOPPED" and st2["session_id"] == session_id

    assert fakes[0].order_send_calls == []
    sessions = _session_rows(tmp_path / "obs.db")
    assert len(sessions) == 1 and sessions[0]["status"] == "ENDED"


def test_api_start_blocked_when_readiness_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _observe_state_reset: None
) -> None:
    import qts.api.server as srv
    import qts.lifecycle.demo_gate as dg

    monkeypatch.setenv("QTS_SETUP_FILE", str(tmp_path / "missing-setup.json"))
    monkeypatch.setattr(dg, "demo_forward_readiness_report", lambda **kwargs: dict(FAILED_READINESS))
    built: list[Any] = []

    def fake_factory(terminal_path: Any, requested: str, broker: str, interval_s: float) -> ObservationCollector:
        fake = LiveFakeMT5("live")
        built.append(fake)
        collector, _ = _make_collector(tmp_path, fake)
        return collector

    monkeypatch.setattr(srv, "_build_observe_collector", fake_factory)

    with _api_client() as client:
        body = client.post("/api/observe/start", json={}).json()
        assert body["started"] is False
        assert body["status"]["state"] == "BLOCKED"
        assert "Terminal not running" in body["status"]["blocked_reasons"]
        # status endpoint surfaces the BLOCKED state for the UI
        st = client.get("/api/observe/status").json()
        assert st["state"] == "BLOCKED" and st["ticks_recorded"] == 0
        assert st["orders_submitted"] == 0
    assert built[0].order_send_calls == []
    assert _tick_rows(tmp_path / "obs.db") == []


def test_ui_wires_observe_endpoints() -> None:
    ui_dir = Path(__file__).resolve().parents[1] / "src" / "qts" / "desktop" / "ui"
    market_js = (ui_dir / "js" / "views" / "market.js").read_text(encoding="utf-8")
    main_js = (ui_dir / "js" / "main.js").read_text(encoding="utf-8")
    assert '"/api/observe/start"' in market_js
    assert '"/api/observe/stop"' in market_js
    assert '"/api/observe/status"' in market_js
    assert "refresh" in market_js  # live refresh loop for observation state
    assert '"observations"' in main_js  # observations route registered in the IA
    assert "Start Observation" in market_js
