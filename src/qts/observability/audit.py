"""Audit log — append-only, structured, queryable."""

from __future__ import annotations

import contextlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from qts.db import connect as db_connect
from qts.domain.events import DomainEvent, EventType

#: Credential-shaped payload keys are redacted in EVERY audit sink, and
#: login-shaped values are masked. Same discipline as
#: ``qts.observability.session_export`` / ``qts.observability.research_snapshot``
#: so the durable audit store is not the least-protected copy of an event.
_CREDENTIAL_KEY_RE = re.compile(r"(password|passwd|token|secret|api_?key|credential)", re.I)
_LOGIN_KEY_RE = re.compile(r"login", re.I)
_REDACTED = "***REDACTED***"


def _mask_login(value: Any) -> str:
    text = str(value)
    return f"****{text[-2:]}" if len(text) > 2 else "****"


def sanitize_audit_payload(payload: Any) -> Any:
    """Recursively redact credential-shaped keys and mask login-shaped values.

    Applied ONCE per event; every sink writes the same sanitized value.
    Redaction previously touched only the JSONL copy — it mutated a
    ``model_dump`` clone — while the SQLite ``audit_events`` table (the durable
    store queried by ``/api/audit`` and rendered in the desktop UI) received
    ``event.payload`` raw. Nested payloads were never inspected either.
    """
    if isinstance(payload, dict):
        out: dict[Any, Any] = {}
        for key, value in payload.items():
            name = str(key)
            if _CREDENTIAL_KEY_RE.search(name):
                out[key] = _REDACTED
            elif _LOGIN_KEY_RE.search(name):
                out[key] = _mask_login(value)
            else:
                out[key] = sanitize_audit_payload(value)
        return out
    if isinstance(payload, (list, tuple)):
        return [sanitize_audit_payload(v) for v in payload]
    return payload


class AuditLog(Protocol):
    def emit(self, event: DomainEvent) -> None: ...
    def query(
        self,
        event_type: EventType | None = None,
        strategy_id: str | None = None,
        limit: int = 100,
        **filters: str,
    ) -> list[DomainEvent]: ...


class InMemoryAuditLog:
    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    def emit(self, event: DomainEvent) -> None:
        self.events.append(event)

    def query(
        self,
        event_type: EventType | None = None,
        strategy_id: str | None = None,
        limit: int = 100,
        **filters: str,
    ) -> list[DomainEvent]:
        out = self.events
        if event_type:
            out = [e for e in out if e.event_type == event_type]
        if strategy_id:
            out = [e for e in out if e.payload.get("strategy_id") == strategy_id]
        for k, v in filters.items():
            out = [e for e in out if str(e.payload.get(k)) == str(v)]
        return out[-limit:]

    def clear(self) -> None:
        self.events.clear()


class SqliteAuditLog:
    def __init__(
        self,
        db_path: Path | str = "data/sqlite/qts.db",
        jsonl_path: Path | str | None = "logs/audit.jsonl",
    ):
        self.db_path = Path(db_path)
        self.jsonl_path = Path(jsonl_path) if jsonl_path else None
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if self.jsonl_path:
            self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with db_connect(self.db_path) as con:
            con.execute("""
            CREATE TABLE IF NOT EXISTS audit_events (
                event_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                event_time TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                source TEXT,
                payload TEXT,
                code_version TEXT,
                data_version TEXT
            )
            """)
            con.execute("CREATE INDEX IF NOT EXISTS idx_audit_type_time ON audit_events(event_type, event_time)")
            con.commit()

    def emit(self, event: DomainEvent) -> None:
        # Sanitize ONCE and write the SAME value to every sink.
        payload = sanitize_audit_payload(event.payload)
        payload_json = json.dumps(payload, default=str)

        # The durable SQLite store is written FIRST and is authoritative: if it
        # cannot append the event, emit() fails loudly and the derived JSONL log
        # is not written either, so the two sinks can never diverge. A silently
        # ignored append (duplicate event_id) is a lost audit record and is
        # surfaced rather than swallowed.
        with db_connect(self.db_path) as con:
            cur = con.execute(
                "INSERT OR IGNORE INTO audit_events VALUES (?,?,?,?,?,?,?,?)",
                (
                    event.event_id,
                    event.event_type.value,
                    event.event_time.isoformat(),
                    event.recorded_at.isoformat(),
                    event.source,
                    payload_json,
                    event.code_version,
                    event.data_version,
                ),
            )
            if cur.rowcount != 1:
                raise ValueError(
                    f"audit event {event.event_id} was NOT appended (event_id already present) — "
                    "an append-only audit log must never silently drop an event"
                )
            con.commit()
        if self.jsonl_path:
            # The derived sink carries the SAME sanitized payload as the
            # authoritative store; serializing it is skipped entirely when the
            # JSONL sink is disabled.
            line = event.model_dump(mode="json")
            line["payload"] = payload
            with open(self.jsonl_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(line, default=str) + "\n")

    def query(
        self,
        event_type: EventType | None = None,
        strategy_id: str | None = None,
        limit: int = 100,
        **filters: str,
    ) -> list[DomainEvent]:
        # simple query via SQLite + JSON payload filtering
        q = "SELECT event_id, event_type, event_time, recorded_at, source, payload, code_version, data_version FROM audit_events"
        params: list[str] = []
        clauses: list[str] = []
        if event_type:
            clauses.append("event_type = ?")
            params.append(event_type.value)
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += " ORDER BY event_time DESC LIMIT ?"
        params.append(str(limit * 5))  # fetch more for payload filtering
        with db_connect(self.db_path) as con:
            rows = con.execute(q, params).fetchall()
        events: list[DomainEvent] = []
        for row in rows:
            payload = json.loads(row[5])
            if strategy_id and payload.get("strategy_id") != strategy_id:
                continue
            skip = False
            for k, v in filters.items():
                if str(payload.get(k)) != str(v):
                    skip = True
                    break
            if skip:
                continue
            events.append(
                DomainEvent(
                    event_id=row[0],
                    event_type=EventType(row[1]),
                    event_time=datetime.fromisoformat(row[2]),
                    recorded_at=datetime.fromisoformat(row[3]),
                    source=row[4],
                    payload=payload,
                    # Older rows may predate lineage stamping; preserve that
                    # uncertainty instead of fabricating a package version.
                    code_version=row[6] or "UNAVAILABLE",
                    data_version=row[7],
                )
            )
            if len(events) >= limit:
                break
        return list(reversed(events))

    def close(self) -> None:
        with contextlib.suppress(Exception):
            # File-backed connections are opened/closed per operation via qts.db.connect,
            # so no persistent handle exists here. We must NOT re-open the database file
            # in close()/__del__: that recreates deleted files and re-acquires Windows
            # file locks during GC/shutdown (root cause of WinError 32 on cleanup).
            # close any memory connection if present
            mem = getattr(self, "_memory_con", None)
            if mem is not None:
                with contextlib.suppress(Exception):
                    mem.commit()
                    mem.close()
                self._memory_con = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
