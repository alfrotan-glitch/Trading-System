"""Audit log — append-only, structured, queryable."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Protocol

from qts.domain.events import DomainEvent, EventType


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
        with sqlite3.connect(self.db_path) as con:
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
        # JSONL
        if self.jsonl_path:
            line = event.model_dump(mode="json")
            # safe logging: redact known secret keys
            payload = line.get("payload", {})
            for k in list(payload.keys()):
                if any(s in k.lower() for s in ["password", "secret", "token"]):
                    payload[k] = "***REDACTED***"
            with open(self.jsonl_path, "a") as f:
                f.write(json.dumps(line, default=str) + "\n")
        # SQLite
        with sqlite3.connect(self.db_path) as con:
            con.execute(
                "INSERT OR IGNORE INTO audit_events VALUES (?,?,?,?,?,?,?,?)",
                (
                    event.event_id,
                    event.event_type.value,
                    event.event_time.isoformat(),
                    event.recorded_at.isoformat(),
                    event.source,
                    json.dumps(event.payload, default=str),
                    event.code_version,
                    event.data_version,
                ),
            )
            con.commit()

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
        with sqlite3.connect(self.db_path) as con:
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
                    code_version=row[6] or "0.1.0",
                    data_version=row[7],
                )
            )
            if len(events) >= limit:
                break
        return list(reversed(events))
    def close(self) -> None:
        try:
            db = getattr(self, "db_path", getattr(self, "_db_path", None))
            if db is not None:
                db = Path(db)
                if db.exists() and str(db) != ":memory:":
                    import sqlite3
                    with sqlite3.connect(db) as con:
                        try:
                            con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                            con.commit()
                        except Exception:
                            pass
            # close any memory connection if present
            mem = getattr(self, "_memory_con", None)
            if mem is not None:
                try:
                    mem.commit()
                    mem.close()
                except Exception:
                    pass
                self._memory_con = None
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
