"""Audit retention contract: measure, archive, prune — never erase safety evidence.

The audit log is the product's evidence of what it did. These guards pin the two
properties that make pruning safe:

1. ``qts audit prune`` can only remove high-volume market observations. Kill
   switches, risk vetoes, orders, fills, reconciliations, lifecycle transitions and
   data-quality alerts are excluded **in SQL**, at any age, with no override flag.
2. Every prune is itself recorded, so the deletion leaves a trace.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from click.testing import CliRunner

from qts.cli.audit import audit
from qts.domain.events import DomainEvent, EventType
from qts.observability.audit import (
    PROTECTED_EVENT_TYPES,
    PRUNABLE_EVENT_TYPES,
    SqliteAuditLog,
)

OLD = datetime(2020, 1, 1, tzinfo=UTC)


def _log(tmp_path: Path) -> SqliteAuditLog:
    return SqliteAuditLog(db_path=tmp_path / "audit.db", jsonl_path=tmp_path / "audit.jsonl")


def _emit(log: SqliteAuditLog, event_type: EventType, when: datetime, **payload: object) -> None:
    log.emit(DomainEvent(event_type=event_type, event_time=when, recorded_at=when, payload=dict(payload)))


# --------------------------------------------------------------------- policy


def test_every_event_type_is_classified_and_protected_by_default():
    """A future EventType that nobody classified must land in the protected set."""
    assert PRUNABLE_EVENT_TYPES.isdisjoint(PROTECTED_EVENT_TYPES)
    assert set(EventType) == PRUNABLE_EVENT_TYPES | PROTECTED_EVENT_TYPES


@pytest.mark.parametrize(
    "event_type",
    [EventType.KILL_SWITCH, EventType.RISK_VETO, EventType.ORDER_EVENT, EventType.FILL, EventType.RECONCILE],
)
def test_safety_events_are_never_prunable(event_type: EventType):
    assert event_type in PROTECTED_EVENT_TYPES
    assert event_type not in PRUNABLE_EVENT_TYPES


# ---------------------------------------------------------------------- prune


def test_dry_run_deletes_nothing(tmp_path: Path):
    log = _log(tmp_path)
    _emit(log, EventType.TICK, OLD)
    result = log.prune(before=datetime.now(UTC) - timedelta(days=1), dry_run=True)
    assert result["dry_run"] is True
    assert result["deleted"] == 0
    assert result["matched_prunable"] == 1
    assert log.stats()["rows"] == 1


def test_prune_removes_only_old_prunable_rows(tmp_path: Path):
    log = _log(tmp_path)
    recent = datetime.now(UTC) - timedelta(hours=1)
    _emit(log, EventType.TICK, OLD)  # prunable + old  -> deleted
    _emit(log, EventType.BAR, OLD)  # prunable + old  -> deleted
    _emit(log, EventType.TICK, recent)  # prunable + new -> kept
    _emit(log, EventType.KILL_SWITCH, OLD)  # protected + old -> kept
    _emit(log, EventType.ORDER_EVENT, OLD)  # protected + old -> kept

    result = log.prune(before=datetime.now(UTC) - timedelta(days=30), dry_run=False, vacuum=True)

    assert result["deleted"] == 2
    assert result["protected_kept"] == 2
    stats = log.stats()
    # 3 remaining + the prune record itself (a LifecycleTransition event)
    assert stats["rows"] == 4
    assert stats["rows_by_type"]["KillSwitchEvent"] == 1
    assert stats["rows_by_type"]["OrderEvent"] == 1
    assert stats["rows_by_type"]["TickReceived"] == 1
    assert stats["rows_by_type"]["LifecycleTransition"] == 1


def test_prune_records_itself_with_real_counts(tmp_path: Path):
    log = _log(tmp_path)
    _emit(log, EventType.TICK, OLD)
    log.prune(before=datetime.now(UTC) - timedelta(days=1), dry_run=False)
    recorded = log.query(event_type=EventType.LIFECYCLE, limit=10)
    assert len(recorded) == 1
    payload = recorded[0].payload
    assert payload["action"] == "audit_prune"
    assert payload["deleted"] == 1
    assert payload["note"] == "safety events are never pruned"


def test_naive_cutoff_is_refused(tmp_path: Path):
    with pytest.raises(ValueError, match="timezone-aware"):
        _log(tmp_path).prune(before=datetime(2020, 1, 1))


# --------------------------------------------------------------------- rotate


def test_rotate_preserves_history_and_empties_the_live_sink(tmp_path: Path):
    log = _log(tmp_path)
    _emit(log, EventType.TICK, OLD)
    assert log.jsonl_path is not None and log.jsonl_path.exists()
    before = log.jsonl_path.read_text(encoding="utf-8").count("\n")

    archive = log.rotate_jsonl()

    assert archive is not None and archive.exists()
    assert archive.read_text(encoding="utf-8").count("\n") == before
    assert not log.jsonl_path.exists()
    assert log.rotate_jsonl() is None  # nothing left to rotate


def test_rotate_can_move_archives_elsewhere(tmp_path: Path):
    log = _log(tmp_path)
    _emit(log, EventType.TICK, OLD)
    archive = log.rotate_jsonl(archive_dir=tmp_path / "archive")
    assert archive is not None
    assert archive.parent == tmp_path / "archive"


# ------------------------------------------------------------------------ CLI


def test_cli_prune_without_confirm_is_a_dry_run(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("QTS_DB_PATH", str(tmp_path / "qts.db"))
    monkeypatch.setenv("QTS_AUDIT_JSONL_PATH", str(tmp_path / "audit.jsonl"))
    log = SqliteAuditLog(db_path=tmp_path / "qts.db", jsonl_path=tmp_path / "audit.jsonl")
    _emit(log, EventType.TICK, OLD)

    result = CliRunner().invoke(audit, ["prune", "--older-than-days", "7"])
    assert result.exit_code == 0, result.output
    assert "WOULD DELETE" in result.output
    assert "nothing was deleted" in result.output
    assert log.stats()["rows"] == 1


def test_cli_prune_with_confirm_deletes_and_says_so(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("QTS_DB_PATH", str(tmp_path / "qts.db"))
    monkeypatch.setenv("QTS_AUDIT_JSONL_PATH", str(tmp_path / "audit.jsonl"))
    log = SqliteAuditLog(db_path=tmp_path / "qts.db", jsonl_path=tmp_path / "audit.jsonl")
    _emit(log, EventType.TICK, OLD)

    result = CliRunner().invoke(audit, ["prune", "--older-than-days", "7", "--confirm"])
    assert result.exit_code == 0, result.output
    assert "DELETED" in result.output
    assert "audit_prune lifecycle event written" in result.output
    # the tick is gone, the prune record remains
    by_type = log.stats()["rows_by_type"]
    assert "TickReceived" not in by_type
    assert by_type["LifecycleTransition"] == 1


def test_cli_stats_reports_policy_and_sizes(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("QTS_DB_PATH", str(tmp_path / "qts.db"))
    monkeypatch.setenv("QTS_AUDIT_JSONL_PATH", str(tmp_path / "audit.jsonl"))
    out = tmp_path / "report.json"
    result = CliRunner().invoke(audit, ["stats", "--json-out", str(out)])
    assert result.exit_code == 0, result.output
    assert "(never pruned)" in result.output
    report = json.loads(out.read_text(encoding="utf-8"))
    assert "prunable_types" in report and "protected_types" in report
    assert "KillSwitchEvent" in report["protected_types"]
