"""Durable acquisition ledger — every attempt has an auditable outcome (FO-R1).

Pins the acquisition-accounting contract:

* exactly ONE durable outcome row per acquisition attempt, from a closed
  vocabulary (SESSION_START / STORED / DUPLICATE / VALIDATION_REJECTED /
  RETRIEVAL_ERROR / STORAGE_ERROR / UNRESOLVED);
* ``stored + duplicate + validation_reject + retrieval_error + storage_error +
  unresolved == attempts`` with no residue, and the accepted rows reconcile
  against the ledger in BOTH directions;
* rejected observations stay rejected (never admitted to accepted tick data);
* missed poll slots are reported as missed, never as market activity;
* a ledger-write outage defers rows (flagged) instead of losing them, and the
  backlog can never wedge on a duplicate sequence;
* recovery/continuity is detectable: a session left ACTIVE with a quiet ledger
  is reported as a possible unexplained stop.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from test_observe_only_collector import (
    PASSED_READINESS,
    LiveFakeMT5,
    _make_collector,
    _wait_for,
)

from qts.observability.forward_observatory import ForwardObservatory

ACTIVE = {"STORED", "DUPLICATE", "VALIDATION_REJECTED", "RETRIEVAL_ERROR", "STORAGE_ERROR", "UNRESOLVED"}


def _rows(collector: Any) -> list[dict[str, Any]]:
    return collector.observatory.list_attempts(collector.session_id)


def _outcomes(collector: Any) -> dict[str, int]:
    seen: dict[str, int] = {}
    for row in _rows(collector):
        seen[row["outcome"]] = seen.get(row["outcome"], 0) + 1
    return seen


def _store_count(collector: Any) -> int:
    rec = collector.reconciliation()
    return int(rec["store_rows"])


# ------------------------------------------------------------------ accounting


def test_every_attempt_has_a_classified_outcome(tmp_path: Path) -> None:
    collector, fake = _make_collector(tmp_path, LiveFakeMT5("live"), interval_s=0.2)
    collector.start(PASSED_READINESS)
    assert _wait_for(lambda: collector.ticks_recorded >= 3), collector.last_error
    collector.stop()

    rec = collector.reconciliation()
    outcomes = _outcomes(collector)
    assert outcomes.get("SESSION_START") == 1  # durable schedule/policy anchor
    assert rec["attempts"] == sum(v for k, v in outcomes.items() if k != "SESSION_START")
    assert rec["accounting_balanced"] is True
    assert rec["ledger_store_agreement"] is True
    assert rec["stored"] == rec["store_rows"] == collector.ticks_recorded
    assert rec["fully_reconciled"] is True
    assert rec["sequence_contiguous"] is True
    assert rec["missed_slots"] == 0
    assert fake.order_send_calls == []  # still strictly order-free

    # Every attempt row is a heartbeat: it carries timing + slot identity.
    for row in _rows(collector):
        assert row["attempted_at"]
        if row["outcome"] != "SESSION_START":
            assert row["slot_index"] is not None and row["scheduled_at"]


def test_duplicate_attempts_are_accounted_and_stored_once(tmp_path: Path) -> None:
    collector, _ = _make_collector(tmp_path, LiveFakeMT5("frozen"), interval_s=0.2)
    collector.start(PASSED_READINESS)
    assert _wait_for(lambda: collector.duplicates_skipped >= 2), collector.last_error
    collector.stop()

    outcomes = _outcomes(collector)
    assert outcomes.get("DUPLICATE", 0) >= 2
    assert outcomes.get("STORED", 0) == 1
    assert _store_count(collector) == 1  # the standing quote was never re-persisted
    dup = [r for r in _rows(collector) if r["outcome"] == "DUPLICATE"][0]
    assert dup["dup_key"] and dup["record_id"] is None  # duplicate identity, not a new record
    rec = collector.reconciliation()
    assert rec["duplicate_skip"] == outcomes["DUPLICATE"]
    assert rec["ledger_store_agreement"] is True


def test_rejected_quotes_are_accounted_and_never_stored(tmp_path: Path) -> None:
    collector, _ = _make_collector(tmp_path, LiveFakeMT5("stale"), interval_s=0.2, max_consecutive_failures=3)
    collector.start(PASSED_READINESS)
    assert _wait_for(lambda: collector.state == "STOPPED_ON_ERRORS"), collector.last_error

    outcomes = _outcomes(collector)
    assert outcomes.get("VALIDATION_REJECTED", 0) >= 1
    assert outcomes.get("STORED", 0) == 0
    assert _store_count(collector) == 0  # rejected data never enters accepted rows
    rejections = [r for r in _rows(collector) if r["outcome"] == "VALIDATION_REJECTED"]
    assert all("stale" in (r["reason"] or "") for r in rejections)
    rec = collector.reconciliation()
    assert rec["validation_reject"] == len(rejections)
    assert rec["ledger_store_agreement"] is True


def test_retrieval_failure_is_accounted(tmp_path: Path) -> None:
    collector, _ = _make_collector(tmp_path, LiveFakeMT5("disconnect"), interval_s=0.2, max_consecutive_failures=3)
    collector.start(PASSED_READINESS)
    assert _wait_for(lambda: collector.state == "STOPPED_ON_ERRORS"), collector.last_error

    outcomes = _outcomes(collector)
    assert outcomes.get("RETRIEVAL_ERROR", 0) >= 1
    assert _store_count(collector) == 0
    errs = [r for r in _rows(collector) if r["outcome"] == "RETRIEVAL_ERROR"]
    assert all("no tick available" in (r["reason"] or "") for r in errs)
    assert collector.reconciliation()["retrieval_error"] == len(errs)


def test_storage_failure_is_accounted_and_never_accepted(tmp_path: Path) -> None:
    import sqlite3

    collector, _ = _make_collector(tmp_path, LiveFakeMT5("live"), interval_s=0.2, max_consecutive_failures=3)
    collector.start(PASSED_READINESS)
    assert _wait_for(lambda: collector.ticks_recorded >= 1), collector.last_error

    def boom(_tick: Any) -> None:
        raise sqlite3.IntegrityError("UNIQUE constraint failed: observation_ticks.id")

    collector.observatory.record_tick = boom
    assert _wait_for(lambda: collector.state == "STOPPED_ON_ERRORS"), collector.last_error

    storages = [r for r in _rows(collector) if r["outcome"] == "STORAGE_ERROR"]
    assert storages, "a failed persistence must be a ledger row"
    assert all(r["persistence_ok"] is False for r in storages)
    assert all("IntegrityError" in (r["reason"] or "") for r in storages)
    rec = collector.reconciliation()
    assert rec["storage_error"] == len(storages)
    # A failed persistence is NOT an accepted row, and leaves no dangling ledger ref
    assert rec["store_rows"] == collector.ticks_recorded
    assert rec["stored"] == rec["store_rows"]
    assert rec["ledger_store_agreement"] is True
    assert not rec["missing_record_ids"] and not rec["orphan_store_ids"]


def test_sequence_and_coverage_reconciliation_detects_gaps(tmp_path: Path) -> None:
    collector, _ = _make_collector(tmp_path, LiveFakeMT5("live"), interval_s=0.2)
    collector.start(PASSED_READINESS)
    assert _wait_for(lambda: collector.ticks_recorded >= 1), collector.last_error
    # Force a stall: the next attempt lands many nominal slots later.
    collector._start_monotonic -= 30.0
    assert _wait_for(lambda: collector.ticks_recorded >= 2), collector.last_error
    collector.stop()

    rec = collector.reconciliation()
    assert rec["expected_slots"] > rec["serviced_slots"]
    assert rec["missed_slots"] >= 1  # the stall is visible, not silently smoothed away
    assert rec["missed_slot_ranges"], "missed slots must be reported as explicit ranges"
    assert rec["sequence_contiguous"] is True  # sequence identity stays gapless


def test_missing_slots_are_never_market_activity(tmp_path: Path) -> None:
    collector, _ = _make_collector(tmp_path, LiveFakeMT5("live"), interval_s=0.2)
    collector.start(PASSED_READINESS)
    assert _wait_for(lambda: collector.ticks_recorded >= 1), collector.last_error
    collector._start_monotonic -= 10.0
    assert _wait_for(lambda: collector.ticks_recorded >= 2), collector.last_error
    collector.stop()

    rec = collector.reconciliation()
    assert rec["missed_slots"] >= 1
    # No synthetic row was manufactured for the missing interval.
    assert rec["store_rows"] == rec["stored"] == collector.ticks_recorded
    assert "NOT market activity" in rec["note"]
    gaps = [r for r in _rows(collector) if (r["gap_slots"] or 0) > 0]
    assert gaps, "the attempt after the gap must record how many slots it skipped"


# ------------------------------------------------------- recovery / continuity


def test_restart_creates_a_new_session_and_preserves_the_old_ledger(tmp_path: Path) -> None:
    collector, _ = _make_collector(tmp_path, LiveFakeMT5("live"), interval_s=0.2)
    first = collector.start(PASSED_READINESS)
    assert _wait_for(lambda: collector.ticks_recorded >= 2), collector.last_error
    collector.stop()
    first_rec = collector.reconciliation()

    second = collector.start(PASSED_READINESS)
    try:
        assert second["session_id"] != first["session_id"]
        assert _wait_for(lambda: collector.ticks_recorded >= 1), collector.last_error
    finally:
        stopped = collector.stop()

    rows_first = collector.observatory.list_attempts(first["session_id"])
    rows_second = collector.observatory.list_attempts(stopped["session_id"])
    assert first_rec["attempts"] > 0 and len(rows_first) == first_rec["attempts"] + 1
    assert rows_second and rows_second[0]["outcome"] == "SESSION_START"
    # Both ledgers reconcile independently against their own accepted rows.
    assert collector.reconciliation()["ledger_store_agreement"] is True


def test_quiet_active_session_is_reported_as_a_possible_unexplained_stop(tmp_path: Path) -> None:
    observatory = ForwardObservatory(db_path=tmp_path / "obs.db")
    sid = observatory.start_session(meta={"orders_possible": False, "broker_symbol": "XAUUSD@"})
    observatory.record_attempt(
        sid,
        1,
        outcome="STORED",
        attempted_at="2026-09-18T10:00:00+00:00",
        scheduled_at="2026-09-18T10:00:00+00:00",
        slot_index=0,
        interval_s=1.0,
        record_id="OT-abc",
        persistence_ok=True,
    )
    stale = observatory.stale_active_sessions(stale_after_s=60.0)
    assert [s["session_id"] for s in stale] == [sid]
    assert "possible unexplained stop" in stale[0]["reason"]
    # The historical row is REPORTED, never rewritten by the detector.
    assert observatory.session(sid)["status"] == "ACTIVE"
    recent = observatory.stale_active_sessions(stale_after_s=10**9)
    assert recent == []


# ------------------------------------------------------------- ledger outages


def test_ledger_backlog_is_flushed_deferred_and_never_wedges(tmp_path: Path) -> None:
    collector, _ = _make_collector(tmp_path, LiveFakeMT5("live"), interval_s=0.2, max_consecutive_failures=40)
    collector.start(PASSED_READINESS)
    assert _wait_for(lambda: collector.ticks_recorded >= 2), collector.last_error

    real = collector.observatory.record_attempt
    state = {"fail": True}

    def flaky(*args: Any, **kwargs: Any) -> None:
        if state["fail"]:
            raise RuntimeError("database is locked")
        real(*args, **kwargs)

    collector.observatory.record_attempt = flaky
    assert _wait_for(lambda: len(collector._journal_backlog) >= 2), "outage rows must be carried"
    assert collector.reconciliation()["fully_reconciled"] is False  # backlog is visible, not hidden

    state["fail"] = False  # storage recovers
    assert _wait_for(lambda: not collector._journal_backlog), "backlog must flush on recovery"
    collector.stop()

    rows = _rows(collector)
    assert all(r["outcome"] != "UNRESOLVED" for r in rows), "nothing was actually lost"
    assert any(r["deferred"] is True for r in rows), "late rows must be flagged deferred"
    seqs = [r["seq"] for r in rows]
    assert len(seqs) == len(set(seqs)), "the backlog flush must never duplicate a sequence"
    rec = collector.reconciliation()
    assert rec["accounting_balanced"] is True and rec["ledger_store_agreement"] is True
    assert rec["runtime_journal_backlog"] == 0 and rec["runtime_journal_dropped"] == 0


def test_unresolvable_ledger_outage_is_recorded_as_one_unresolved_marker(tmp_path: Path) -> None:
    collector, _ = _make_collector(tmp_path, LiveFakeMT5("live"), interval_s=0.2, max_consecutive_failures=40)
    collector.start(PASSED_READINESS)
    assert _wait_for(lambda: collector.ticks_recorded >= 1), collector.last_error

    real = collector.observatory.record_attempt
    state = {"fail": True}

    def flaky(*args: Any, **kwargs: Any) -> None:
        if state["fail"]:
            raise RuntimeError("database is locked")
        real(*args, **kwargs)

    collector.observatory.record_attempt = flaky
    # Overflow the bounded backlog with unwritable attempts.
    for _ in range(505):
        collector._journal("DUPLICATE", attempted_at="2026-09-18T10:00:00+00:00", dup_key="k")
    assert collector._journal_dropped >= 1
    state["fail"] = False
    assert _wait_for(lambda: not collector._journal_backlog), "backlog must drain"
    collector.stop()

    markers = [r for r in _rows(collector) if r["outcome"] == "UNRESOLVED"]
    assert len(markers) == 1, "overflow collapses into ONE explicit marker, never silent loss"
    assert "could not be journaled" in (markers[0]["reason"] or "")
    assert json.loads(markers[0]["payload"])["outcome"] == "UNRESOLVED"


def test_ledger_row_has_no_price_or_credential_content(tmp_path: Path) -> None:
    collector, _ = _make_collector(tmp_path, LiveFakeMT5("live"), interval_s=0.2)
    collector.start(PASSED_READINESS)
    assert _wait_for(lambda: collector.ticks_recorded >= 2), collector.last_error
    collector.stop()

    for row in _rows(collector):
        blob = (row["payload"] or "").lower()
        # The ledger records outcomes and identities — never a price, and never a secret.
        assert "bid" not in blob and "ask" not in blob and "password" not in blob and "token" not in blob


def test_attempt_ledger_is_append_only(tmp_path: Path) -> None:
    observatory = ForwardObservatory(db_path=tmp_path / "obs.db")
    sid = observatory.start_session(meta={"orders_possible": False})
    observatory.record_attempt(sid, 1, outcome="STORED", attempted_at="t", record_id="OT-1", persistence_ok=True)
    import sqlite3

    try:
        observatory.record_attempt(sid, 1, outcome="DUPLICATE", attempted_at="t2", dup_key="k")
        raise AssertionError("a re-used sequence must refuse, never replace")
    except sqlite3.IntegrityError:
        pass
    rows = observatory.list_attempts(sid)
    assert len(rows) == 1 and rows[0]["outcome"] == "STORED"
    assert observatory.record_attempt.__doc__  # documented append-only contract


def test_unknown_outcome_is_refused(tmp_path: Path) -> None:
    observatory = ForwardObservatory(db_path=tmp_path / "obs.db")
    sid = observatory.start_session(meta={"orders_possible": False})
    try:
        observatory.record_attempt(sid, 1, outcome="PROFIT", attempted_at="t")
        raise AssertionError("unknown outcomes must be refused")
    except ValueError as e:
        assert "unknown acquisition outcome" in str(e)


def test_ledger_query_is_bounded_for_a_long_session(tmp_path: Path) -> None:
    """Reconciliation reads ONE session and stays linear in its own attempts."""
    observatory = ForwardObservatory(db_path=tmp_path / "obs.db")
    small = observatory.start_session(meta={"orders_possible": False})
    big = observatory.start_session(meta={"orders_possible": False})
    for i in range(1, 201):
        observatory.record_attempt(big, i, outcome="DUPLICATE", attempted_at="t", dup_key=f"k{i}")
    observatory.record_attempt(small, 1, outcome="DUPLICATE", attempted_at="t", dup_key="k")
    assert len(observatory.list_attempts(small)) == 1  # session-scoped, not global
    assert observatory.attempt_reconciliation(small)["attempts"] == 1
    start = time.perf_counter()
    observatory.attempt_reconciliation(big)
    assert time.perf_counter() - start < 5.0
