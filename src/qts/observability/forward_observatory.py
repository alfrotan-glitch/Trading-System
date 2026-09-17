"""Forward Market Observatory — THE canonical observation/session store.

ONE authoritative store for market observations (finding #5). JSON exports
(``data/evidence/forward_observation_manifest.json`` etc.) are DERIVED,
regenerable artifacts — never the primary source.

Canonical store contract (every record carries):

* identity            (id, session_id)
* provenance class    (SYNTHETIC | HISTORICAL | PAPER | SHADOW | DEMO | REAL | UNVERIFIED)
* environment         (mode, env at session start)
* broker/account      (broker name, masked login)
* symbol              (canonical + broker symbol)
* time                (broker event time + basis, local receipt time)
* payload             (full observation JSON, immutable)

Fail-closed defaults: ``provenance`` defaults to UNVERIFIED; only code paths
that genuinely know the origin stamp a stronger class. The live DEMO
collector stamps DEMO; the simulator stamps SYNTHETIC; nothing stamps REAL
except a verified real-account session.
"""

from __future__ import annotations

import contextlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from qts.db import connect as db_connect
from qts.domain.provenance import EvidenceProvenance
from qts.domain.value_objects import Tick, uuid7


class ObservationTick(BaseModel):
    id: str = Field(default_factory=lambda: f"OT-{uuid7()[:6]}")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))  # local receipt time
    symbol: str
    bid: Decimal | None = None
    ask: Decimal | None = None
    mid: Decimal | None = None
    spread_bps: float | None = None
    volatility_20: float | None = None
    session: str = "unknown"  # e.g., "London", "NY", "Asian", "weekend_closed"
    regime: str = "unknown"
    data_freshness_ms: float | None = None
    anomaly: str | None = None
    # Provenance — FAIL-CLOSED default: unclassified records are excluded
    # from every claim that requires real evidence until classified.
    provenance: str = EvidenceProvenance.UNVERIFIED.value
    # Broker-timestamp provenance — every stored observation must expose its
    # timestamp basis (canonical contract: MT5 server-basis stamps normalized
    # to true UTC via the measured server offset).
    broker_event_time: datetime | None = None  # normalized true-UTC quote time
    broker_time_raw: float | None = None  # raw MT5 server-basis epoch seconds, as received
    server_utc_offset_s: float | None = None  # offset applied during normalization
    timestamp_basis: str = "ingest-utc"  # ingest-utc | broker-normalized(<offset basis>)
    tick_provenance: dict[str, Any] | None = None  # full Tick.provenance (receipt time, stamps, basis)
    session_id: str | None = None

    @classmethod
    def from_domain_tick(cls, tick: Tick, symbol: str | None = None) -> ObservationTick:
        """Build from a domain Tick (e.g. validated MT5Adapter output), carrying
        the broker-timestamp provenance so persisted evidence is auditable."""
        prov = tick.provenance or {}
        mid = tick.mid
        spread_bps = float((tick.ask - tick.bid) / mid * Decimal("10000")) if mid else None
        basis_src = prov.get("offset_basis", "unknown") if prov else "no-provenance"
        return cls(
            symbol=symbol or tick.instrument.symbol,
            bid=tick.bid,
            ask=tick.ask,
            mid=mid,
            spread_bps=spread_bps,
            data_freshness_ms=(datetime.now(UTC) - tick.event_time).total_seconds() * 1000.0,
            broker_event_time=tick.event_time,
            broker_time_raw=prov.get("mt5_time"),
            server_utc_offset_s=prov.get("server_utc_offset_s"),
            timestamp_basis=f"broker-normalized({basis_src})",
            tick_provenance=dict(prov) if prov else None,
            # Domain ticks are only produced by real broker adapters — but the
            # SESSION context decides DEMO vs REAL; the collector stamps it.
            provenance=EvidenceProvenance.UNVERIFIED.value,
        )


class ObservationSignal(BaseModel):
    id: str = Field(default_factory=lambda: f"OS-{uuid7()[:6]}")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    symbol: str
    signal_side: str | None = None  # BUY/SELL/None for NO_TRADE
    strategy_id: str
    theoretical_price: Decimal | None = None
    executable_bid: Decimal | None = None
    executable_ask: Decimal | None = None
    hypothetical_fill_price: Decimal | None = None
    slippage_model_bps: float | None = None
    latency_ms: float | None = None
    no_trade_reason: str | None = None
    regime_at_signal: str | None = None
    market_state: str | None = None
    provenance: str = EvidenceProvenance.UNVERIFIED.value
    session_id: str | None = None


class ForwardObservatory:
    """Canonical SQLite observation store (WAL-safe via qts.db.connect)."""

    def __init__(self, db_path: Path | str = "data/sqlite/forward_observatory.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _init(self):
        with db_connect(self.db_path) as con:
            con.execute(
                "CREATE TABLE IF NOT EXISTS observation_ticks (id TEXT PRIMARY KEY, payload TEXT, created_at TEXT)"
            )
            con.execute(
                "CREATE TABLE IF NOT EXISTS observation_signals (id TEXT PRIMARY KEY, payload TEXT, created_at TEXT)"
            )
            con.execute(
                "CREATE TABLE IF NOT EXISTS observation_sessions (id TEXT PRIMARY KEY, start TEXT, end TEXT, status TEXT)"
            )
            # Canonical accessor columns (added for provenance-first queries;
            # older databases are migrated in place, payload stays immutable).
            self._ensure_column(con, "observation_ticks", "provenance", "TEXT")
            self._ensure_column(con, "observation_ticks", "session_id", "TEXT")
            self._ensure_column(con, "observation_ticks", "symbol", "TEXT")
            self._ensure_column(con, "observation_ticks", "event_time", "TEXT")
            self._ensure_column(con, "observation_signals", "provenance", "TEXT")
            self._ensure_column(con, "observation_signals", "session_id", "TEXT")
            self._ensure_column(
                con,
                "observation_sessions",
                "meta",
                "TEXT",
            )
            # Backfill accessor columns from immutable payloads (idempotent).
            con.execute(
                "UPDATE observation_ticks SET provenance="
                "COALESCE(provenance, json_extract(payload, '$.provenance'), 'UNVERIFIED')"
            )
            con.execute(
                "UPDATE observation_ticks SET session_id=COALESCE(session_id, json_extract(payload, '$.session_id'))"
            )
            con.execute("UPDATE observation_ticks SET symbol=COALESCE(symbol, json_extract(payload, '$.symbol'))")
            con.execute(
                "UPDATE observation_ticks SET event_time=COALESCE(event_time, json_extract(payload, '$.broker_event_time'))"
            )
            con.execute(
                "UPDATE observation_signals SET provenance="
                "COALESCE(provenance, json_extract(payload, '$.provenance'), 'UNVERIFIED')"
            )
            con.execute(
                "UPDATE observation_signals SET session_id=COALESCE(session_id, json_extract(payload, '$.session_id'))"
            )
            con.commit()

    @staticmethod
    def _ensure_column(con: Any, table: str, column: str, decl: str) -> None:
        cols = {r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in cols:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")

    # ---------------------------------------------------------------- writes
    def record_tick(self, tick: ObservationTick):
        with db_connect(self.db_path) as con:
            con.execute(
                "INSERT OR REPLACE INTO observation_ticks (id, payload, created_at, provenance, session_id, symbol, event_time)"
                " VALUES (?,?,?,?,?,?,?)",
                (
                    tick.id,
                    tick.model_dump_json(),
                    tick.timestamp.isoformat(),
                    tick.provenance,
                    tick.session_id,
                    tick.symbol,
                    tick.broker_event_time.isoformat() if tick.broker_event_time else None,
                ),
            )
            con.commit()

    def record_signal(self, sig: ObservationSignal):
        with db_connect(self.db_path) as con:
            con.execute(
                "INSERT OR REPLACE INTO observation_signals (id, payload, created_at, provenance, session_id)"
                " VALUES (?,?,?,?,?)",
                (sig.id, sig.model_dump_json(), sig.timestamp.isoformat(), sig.provenance, sig.session_id),
            )
            con.commit()

    # -------------------------------------------------------------- sessions
    def start_session(
        self,
        session_id: str | None = None,
        *,
        meta: dict[str, Any] | None = None,
    ) -> str:
        """Open a session. ``meta`` records environment/broker/symbol/timestamp
        basis/code version — the session identity contract (finding #5)."""
        sid = session_id or f"FS-{uuid7()[:6]}"
        body = {
            **(meta or {}),
            "started_at": datetime.now(UTC).isoformat(),
        }
        with db_connect(self.db_path) as con:
            con.execute(
                "INSERT OR REPLACE INTO observation_sessions (id, start, end, status, meta) VALUES (?,?,?,?,?)",
                (sid, body["started_at"], "", "ACTIVE", json.dumps(body, default=str)),
            )
            con.commit()
        return sid

    def end_session(self, session_id: str, *, status: str = "ENDED", error: str | None = None):
        body: dict[str, Any] = {"ended_at": datetime.now(UTC).isoformat()}
        if error:
            body["error"] = error
        with db_connect(self.db_path) as con:
            con.execute(
                "UPDATE observation_sessions SET end=?, status=?, meta=COALESCE(meta,'') WHERE id=?",
                (body["ended_at"], status, session_id),
            )
            # merge end info into meta JSON
            row = con.execute("SELECT meta FROM observation_sessions WHERE id=?", (session_id,)).fetchone()
            if row and row[0]:
                try:
                    merged = {**json.loads(row[0]), **body}
                    con.execute("UPDATE observation_sessions SET meta=? WHERE id=?", (json.dumps(merged, default=str), session_id))
                except ValueError:
                    pass
            con.commit()

    # ---------------------------------------------------------------- reads
    def list_ticks(self, limit: int = 100, *, session_id: str | None = None, provenance: str | None = None) -> list[dict[str, Any]]:
        """Canonical tick reader (dicts, newest first)."""
        q = "SELECT payload FROM observation_ticks"
        conds: list[str] = []
        args: list[Any] = []
        if session_id:
            conds.append("session_id=?")
            args.append(session_id)
        if provenance:
            conds.append("provenance=?")
            args.append(provenance)
        if conds:
            q += " WHERE " + " AND ".join(conds)
        q += " ORDER BY created_at DESC LIMIT ?"
        args.append(int(limit))
        with db_connect(self.db_path) as con:
            rows = con.execute(q, args).fetchall()
        out: list[dict[str, Any]] = []
        for (payload,) in rows:
            try:
                out.append(json.loads(payload))
            except ValueError:
                continue
        return out

    def session(self, session_id: str) -> dict[str, Any] | None:
        with db_connect(self.db_path) as con:
            row = con.execute(
                "SELECT id, start, end, status, meta FROM observation_sessions WHERE id=?", (session_id,)
            ).fetchone()
        if not row:
            return None
        sid, start, end, status, meta = row
        try:
            meta_d = json.loads(meta) if meta else {}
        except ValueError:
            meta_d = {"unparseable": True}
        return {"id": sid, "start": start, "end": end or None, "status": status, "meta": meta_d}

    def real_observation_count(self, *, symbol: str | None = None, since_iso: str | None = None) -> int:
        """Count observations whose provenance qualifies as REAL-market evidence
        (DEMO or REAL class only — SYNTHETIC/PAPER/UNVERIFIED never count)."""
        q = "SELECT COUNT(*) FROM observation_ticks WHERE provenance IN ('DEMO','REAL')"
        args: list[Any] = []
        if symbol:
            q += " AND symbol=?"
            args.append(symbol)
        if since_iso:
            q += " AND COALESCE(event_time, created_at) >= ?"
            args.append(since_iso)
        with db_connect(self.db_path) as con:
            (n,) = con.execute(q, args).fetchone()
        return int(n)

    def summary(self) -> dict[str, Any]:
        with db_connect(self.db_path) as con:
            tick_count = con.execute("SELECT COUNT(*) FROM observation_ticks").fetchone()[0]
            signal_count = con.execute("SELECT COUNT(*) FROM observation_signals").fetchone()[0]
            sessions = con.execute("SELECT COUNT(*) FROM observation_sessions WHERE status='ACTIVE'").fetchone()[0]
            (real_count,) = con.execute(
                "SELECT COUNT(*) FROM observation_ticks WHERE provenance IN ('DEMO','REAL')"
            ).fetchone()
            by_prov = {
                str(p): c
                for p, c in con.execute(
                    "SELECT provenance, COUNT(*) FROM observation_ticks GROUP BY provenance"
                ).fetchall()
            }
        return {
            "canonical_store": str(self.db_path),
            "active_observation_sessions": sessions,
            "ticks_recorded": tick_count,
            "signals_recorded": signal_count,
            "real_market_ticks": real_count,
            "ticks_by_provenance": by_prov,
            "no_capital_exposure": True,
            "safety": "No live trading — only hypothetical executions recorded",
        }

    # ------------------------------------------------------ derived exports
    def to_manifest(self, path: Path = Path("data/evidence/forward_observation_manifest.json")) -> dict[str, Any]:
        """DERIVED export (regenerable). The SQLite store remains authoritative."""
        s = self.summary()
        with db_connect(self.db_path) as con:
            tick_rows = con.execute("SELECT payload FROM observation_ticks ORDER BY created_at DESC LIMIT 5").fetchall()
            sig_rows = con.execute(
                "SELECT payload FROM observation_signals ORDER BY created_at DESC LIMIT 5"
            ).fetchall()
        s["sample_ticks"] = [json.loads(r[0]) for r in tick_rows]
        s["sample_signals"] = [json.loads(r[0]) for r in sig_rows]
        s["generated_at"] = datetime.now(UTC).isoformat()
        s["derived_from"] = str(self.db_path)
        s["forward_observation_protocol"] = "docs/forward_observation_protocol.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(s, indent=2, default=str), encoding="utf-8")
        return s

    def simulate_observation(self, symbol: str = "XAUUSD", n_ticks: int = 10):
        """Simulate n_ticks of forward observation — LABELED SYNTHETIC.

        Every record written here carries provenance=SYNTHETIC and a session
        meta marker; simulation can never be mistaken for market evidence
        (real_observation_count excludes it by provenance class).
        """
        import random

        session = self.start_session(meta={"kind": "SIMULATION", "provenance": "SYNTHETIC", "symbol": symbol})
        base = Decimal("2000")
        for i in range(n_ticks):
            # B311: non-cryptographic scientific randomness (seeded permutation/simulation), not security
            spread = Decimal(str(random.uniform(0.5, 1.5)))  # nosec B311
            # B311: non-cryptographic scientific randomness (seeded permutation/simulation), not security
            bid = base + Decimal(str(random.uniform(-2, 2)))  # nosec B311
            ask = bid + spread
            tick = ObservationTick(
                symbol=symbol,
                bid=bid,
                ask=ask,
                mid=(bid + ask) / 2,
                spread_bps=float(spread / base * 10000),
                session="London" if i % 2 == 0 else "NY",
                regime="trend" if i % 3 == 0 else "range",
                provenance=EvidenceProvenance.SYNTHETIC.value,
                session_id=session,
            )
            self.record_tick(tick)
            # Simulate signal 30% of time, NO_TRADE otherwise
            # B311: non-cryptographic scientific randomness (seeded permutation/simulation), not security
            if random.random() < 0.3:  # nosec B311
                sig = ObservationSignal(
                    symbol=symbol,
                    # B311: non-cryptographic scientific randomness (seeded permutation/simulation), not security
                    signal_side="BUY" if random.random() < 0.5 else "SELL",  # nosec B311
                    strategy_id="demo_state_machine",
                    theoretical_price=tick.mid,
                    executable_bid=tick.bid,
                    executable_ask=tick.ask,
                    # B311: non-cryptographic scientific randomness (seeded permutation/simulation), not security
                    hypothetical_fill_price=tick.ask if random.random() < 0.5 else tick.bid,  # nosec B311
                    slippage_model_bps=2.0,
                    regime_at_signal=tick.regime,
                    provenance=EvidenceProvenance.SYNTHETIC.value,
                    session_id=session,
                )
            else:
                sig = ObservationSignal(
                    symbol=symbol,
                    signal_side=None,
                    strategy_id="demo_state_machine",
                    no_trade_reason="regime filter: range chop" if tick.regime == "range" else "volatility too low",
                    provenance=EvidenceProvenance.SYNTHETIC.value,
                    session_id=session,
                )
            self.record_signal(sig)
        self.end_session(session)
        return self.summary()

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
