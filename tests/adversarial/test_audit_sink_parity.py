"""Adversarial tests for audit-log sink parity and redaction.

The durable SQLite ``audit_events`` table is what ``/api/audit`` queries and
what the desktop UI renders, so it must never be the LEAST protected copy of an
event. Before the fix:

* redaction was applied to a ``model_dump`` clone used for the JSONL line only,
  so credential-shaped payload keys reached SQLite verbatim;
* nested payloads were never inspected at all (only top-level keys);
* the derived JSONL log was appended BEFORE the authoritative SQLite store, so
  a failed SQLite append still produced a JSONL record — the two sinks could
  diverge, and the JSONL would claim an event the audit trail did not have;
* ``INSERT OR IGNORE`` made a duplicate ``event_id`` a silently dropped audit
  record.

Invariant under test: every sink holds the SAME sanitized payload, the
authoritative sink is written first, and no event is ever dropped silently.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from qts.db import connect as db_connect
from qts.domain.events import DomainEvent, EventType

# NOTE: `sanitize_audit_payload` is deliberately imported INSIDE the tests that
# exercise it, so the sink-parity tests below still run — and fail loudly —
# against a build where the sanitizer is missing or applied to only one sink.
from qts.observability.audit import SqliteAuditLog

_SECRET = "sup3r-s3cret-do-not-persist"
_TOKEN = "tok_live_9f8e7d6c"
_LOGIN = "5012345678"


def _event(payload: dict, event_id: str | None = None) -> DomainEvent:
    kwargs = {"event_type": EventType.ACCOUNT_UPDATE, "payload": payload}
    if event_id is not None:
        kwargs["event_id"] = event_id
    return DomainEvent(**kwargs)  # type: ignore[arg-type]


def _log(tmp_path: Path) -> SqliteAuditLog:
    return SqliteAuditLog(db_path=tmp_path / "audit.db", jsonl_path=tmp_path / "audit.jsonl")


def _sqlite_payloads(db: Path) -> list[dict]:
    # file-backed reads go through qts.db.connect (repo structural guard:
    # deterministic close, no leaked Windows file locks)
    with db_connect(db) as con:
        rows = con.execute("SELECT payload FROM audit_events ORDER BY rowid").fetchall()
    return [json.loads(r[0]) for r in rows]


def _jsonl_lines(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# sanitize_audit_payload
# ---------------------------------------------------------------------------


def test_credential_keys_are_redacted_at_every_depth():
    from qts.observability.audit import sanitize_audit_payload

    payload = {
        "password": _SECRET,
        "api_key": _TOKEN,
        "connection": {"token": _TOKEN, "nested": {"client_secret": _SECRET, "keep": 1}},
        "history": [{"passwd": _SECRET}, {"ok": True}],
        "credential": _SECRET,
        "apikey": _TOKEN,
        "innocent": "visible",
    }
    out = sanitize_audit_payload(payload)

    assert out["password"] == "***REDACTED***"
    assert out["api_key"] == "***REDACTED***"
    assert out["apikey"] == "***REDACTED***"
    assert out["credential"] == "***REDACTED***"
    assert out["connection"]["token"] == "***REDACTED***"
    assert out["connection"]["nested"]["client_secret"] == "***REDACTED***"
    assert out["connection"]["nested"]["keep"] == 1
    assert out["history"][0]["passwd"] == "***REDACTED***"
    assert out["history"][1] == {"ok": True}
    # non-sensitive values survive untouched — redaction must not destroy evidence
    assert out["innocent"] == "visible"
    assert _SECRET not in json.dumps(out)
    assert _TOKEN not in json.dumps(out)


def test_login_values_are_masked_not_dropped():
    from qts.observability.audit import sanitize_audit_payload

    """A login is an identifier, not a credential: mask it, keep the shape."""
    out = sanitize_audit_payload({"login": _LOGIN, "broker": {"login": _LOGIN, "server": "demo"}})
    assert out["login"] == "****78"
    assert out["broker"]["login"] == "****78"
    assert out["broker"]["server"] == "demo"
    assert _LOGIN not in json.dumps(out)


def test_sanitize_does_not_mutate_its_input():
    from qts.observability.audit import sanitize_audit_payload

    """The event model is frozen and its payload is shared with the caller;
    sanitizing must not rewrite what the caller still holds."""
    payload = {"password": _SECRET, "nested": {"token": _TOKEN}, "list": [{"secret": _SECRET}]}
    before = json.dumps(payload, sort_keys=True)
    sanitize_audit_payload(payload)
    assert json.dumps(payload, sort_keys=True) == before


def test_sanitize_handles_non_dict_payloads():
    from qts.observability.audit import sanitize_audit_payload

    assert sanitize_audit_payload("plain") == "plain"
    assert sanitize_audit_payload(None) is None
    assert sanitize_audit_payload([{"password": _SECRET}]) == [{"password": "***REDACTED***"}]


# ---------------------------------------------------------------------------
# Sink parity — the durable SQLite store must be sanitized too
# ---------------------------------------------------------------------------


def test_sqlite_sink_receives_the_sanitized_payload(tmp_path):
    log = _log(tmp_path)
    log.emit(
        _event(
            {
                "account_password": _SECRET,
                "token": _TOKEN,
                "login": _LOGIN,
                "meta": {"api_key": _TOKEN, "equity": 10000},
                "history": [{"secret": _SECRET}],
            }
        )
    )
    log.close()

    stored = _sqlite_payloads(tmp_path / "audit.db")
    assert len(stored) == 1
    row = stored[0]
    blob = json.dumps(row)
    assert _SECRET not in blob, "a credential reached the DURABLE audit store"
    assert _TOKEN not in blob
    assert _LOGIN not in blob
    assert row["account_password"] == "***REDACTED***"
    assert row["token"] == "***REDACTED***"
    assert row["login"] == "****78"
    assert row["meta"]["api_key"] == "***REDACTED***"
    assert row["meta"]["equity"] == 10000
    assert row["history"][0]["secret"] == "***REDACTED***"

    # and not through the raw database file either
    assert _SECRET.encode() not in (tmp_path / "audit.db").read_bytes()
    assert _TOKEN.encode() not in (tmp_path / "audit.db").read_bytes()


def test_both_sinks_hold_the_identical_sanitized_payload(tmp_path):
    from qts.observability.audit import sanitize_audit_payload

    """No sink may be a weaker copy of the same event."""
    log = _log(tmp_path)
    payload = {"token": _TOKEN, "login": _LOGIN, "detail": {"password": _SECRET}, "drift": "NONE"}
    log.emit(_event(payload))
    log.close()

    sqlite_rows = _sqlite_payloads(tmp_path / "audit.db")
    jsonl_rows = [line["payload"] for line in _jsonl_lines(tmp_path / "audit.jsonl")]
    assert len(sqlite_rows) == 1
    assert len(jsonl_rows) == 1
    assert sqlite_rows[0] == jsonl_rows[0], "SQLite and JSONL audit payloads diverged"
    assert sqlite_rows[0] == sanitize_audit_payload(payload)


def test_query_returns_sanitized_payloads(tmp_path):
    """/api/audit and the desktop UI read through query() — the values they
    render must already be sanitized."""
    log = _log(tmp_path)
    log.emit(_event({"strategy_id": "sma", "token": _TOKEN}))
    events = log.query(event_type=EventType.ACCOUNT_UPDATE, strategy_id="sma")
    log.close()

    assert len(events) == 1
    assert events[0].payload["token"] == "***REDACTED***"
    assert _TOKEN not in json.dumps(events[0].payload)


# ---------------------------------------------------------------------------
# Ordering and no-silent-drop
# ---------------------------------------------------------------------------


def test_duplicate_event_id_raises_instead_of_silently_dropping(tmp_path):
    log = _log(tmp_path)
    log.emit(_event({"n": 1}, event_id="fixed-event-id"))
    with pytest.raises(ValueError, match="NOT appended"):
        log.emit(_event({"n": 2}, event_id="fixed-event-id"))
    log.close()

    # exactly one record survived, and the JSONL never got a second line for it
    assert len(_sqlite_payloads(tmp_path / "audit.db")) == 1
    assert len(_jsonl_lines(tmp_path / "audit.jsonl")) == 1


def test_failed_sqlite_append_does_not_produce_a_jsonl_record(tmp_path, monkeypatch):
    """SQLite is authoritative and written FIRST: if it cannot append, the
    derived JSONL must not claim the event happened."""
    import qts.observability.audit as audit_module

    log = _log(tmp_path)
    log.emit(_event({"ok": True}))
    assert len(_jsonl_lines(tmp_path / "audit.jsonl")) == 1

    def _boom(*_a, **_k):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(audit_module, "db_connect", _boom)
    with pytest.raises(sqlite3.OperationalError):
        log.emit(_event({"ok": False}))

    lines = _jsonl_lines(tmp_path / "audit.jsonl")
    assert len(lines) == 1, "the JSONL log recorded an event the authoritative store rejected"
    assert lines[0]["payload"] == {"ok": True}


def test_jsonl_disabled_still_writes_the_durable_store(tmp_path):
    log = SqliteAuditLog(db_path=tmp_path / "audit.db", jsonl_path=None)
    log.emit(_event({"token": _TOKEN}))
    log.close()
    assert len(_sqlite_payloads(tmp_path / "audit.db")) == 1
    assert not (tmp_path / "audit.jsonl").exists()


def test_audit_log_never_writes_into_the_repository_from_a_temp_workspace(tmp_path, monkeypatch):
    """Guard the guard: an audit log built inside an isolated workspace must
    not touch the repository's real data root."""
    monkeypatch.chdir(tmp_path)
    log = SqliteAuditLog(db_path="data/sqlite/qts.db", jsonl_path="logs/audit.jsonl")
    log.emit(_event({"x": 1}))
    log.close()
    assert (tmp_path / "data" / "sqlite" / "qts.db").exists()
    assert (tmp_path / "logs" / "audit.jsonl").exists()


def test_lineage_columns_are_persisted_with_the_event(tmp_path):
    """An audit record without lineage cannot be attributed to a code version."""
    log = _log(tmp_path)
    event = _event({"x": 1})
    log.emit(event)
    with db_connect(tmp_path / "audit.db") as con:
        row = con.execute(
            "SELECT event_id, event_type, source, code_version, data_version FROM audit_events"
        ).fetchone()
    log.close()

    assert row[0] == event.event_id
    assert row[1] == EventType.ACCOUNT_UPDATE.value
    assert row[2] == event.source
    assert row[3] == event.code_version
    assert row[3], "an empty code_version defeats audit attribution"
    assert row[4] == event.data_version


def test_tempfile_mktemp_path_is_not_required(tmp_path):
    """Sanity: the store creates missing parent directories."""
    nested = tmp_path / "a" / "b" / "audit.db"
    log = SqliteAuditLog(db_path=nested, jsonl_path=tmp_path / "x" / "y" / "audit.jsonl")
    log.emit(_event({"x": 1}))
    log.close()
    assert nested.exists()
    assert Path(tmp_path / "x" / "y" / "audit.jsonl").exists()
