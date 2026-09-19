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
from qts.observability.lineage import code_version


class ObservationTick(BaseModel):
    # Collision-resistant record identity: full 128-bit random hex. The earlier
    # 6-hex-char (24-bit) form reached ~50% birthday-collision probability near
    # 4.8k records — unusable for multi-million-row forward collection. Record
    # IDs are not format-constrained by the v1 evidence contract; session IDs
    # below keep the canonical `FS-<6 hex>` form the verifier requires.
    id: str = Field(default_factory=lambda: f"OT-{uuid7()}")
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
            # Durable acquisition ledger (FO-R1 prerequisite: every acquisition
            # attempt has an auditable outcome). Same store, same module — the
            # accepted-tick table stays the ONLY pricing data; this table never
            # holds a price and never holds a rejected observation's data.
            con.execute(
                "CREATE TABLE IF NOT EXISTS observation_attempts ("
                " session_id TEXT, seq INTEGER, outcome TEXT, attempted_at TEXT,"
                " scheduled_at TEXT, slot_index INTEGER, interval_s REAL,"
                " monotonic_s REAL, record_id TEXT, dup_key TEXT, reason TEXT,"
                " persistence_ok INTEGER, deferred INTEGER, gap_slots INTEGER,"
                " payload TEXT, PRIMARY KEY (session_id, seq))"
            )
            # Canonical accessor columns (added for provenance-first queries;
            # older databases are migrated in place, payload stays immutable).
            # Backfill runs ONCE, only when a column was just added — never a
            # full-table scan on every construction.
            added = {
                ("observation_ticks", "provenance"): self._ensure_column(
                    con, "observation_ticks", "provenance", "TEXT"
                ),
                ("observation_ticks", "session_id"): self._ensure_column(
                    con, "observation_ticks", "session_id", "TEXT"
                ),
                ("observation_ticks", "symbol"): self._ensure_column(con, "observation_ticks", "symbol", "TEXT"),
                ("observation_ticks", "event_time"): self._ensure_column(
                    con, "observation_ticks", "event_time", "TEXT"
                ),
                ("observation_signals", "provenance"): self._ensure_column(
                    con, "observation_signals", "provenance", "TEXT"
                ),
                ("observation_signals", "session_id"): self._ensure_column(
                    con, "observation_signals", "session_id", "TEXT"
                ),
                ("observation_sessions", "meta"): self._ensure_column(con, "observation_sessions", "meta", "TEXT"),
            }
            if any(added.values()):
                con.execute(
                    "UPDATE observation_ticks SET provenance="
                    "COALESCE(provenance, json_extract(payload, '$.provenance'), 'UNVERIFIED')"
                )
                con.execute(
                    "UPDATE observation_ticks SET session_id="
                    "COALESCE(session_id, json_extract(payload, '$.session_id'))"
                )
                con.execute("UPDATE observation_ticks SET symbol=COALESCE(symbol, json_extract(payload, '$.symbol'))")
                con.execute(
                    "UPDATE observation_ticks SET event_time="
                    "COALESCE(event_time, json_extract(payload, '$.broker_event_time'))"
                )
                con.execute(
                    "UPDATE observation_signals SET provenance="
                    "COALESCE(provenance, json_extract(payload, '$.provenance'), 'UNVERIFIED')"
                )
                con.execute(
                    "UPDATE observation_signals SET session_id="
                    "COALESCE(session_id, json_extract(payload, '$.session_id'))"
                )
            con.commit()

    @staticmethod
    def _ensure_column(con: Any, table: str, column: str, decl: str) -> bool:
        """Add the column if missing. Returns True when JUST added (so callers
        can backfill once instead of scanning the table on every open)."""
        cols = {r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in cols:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
            return True
        return False

    # ---------------------------------------------------------------- writes
    def record_tick(self, tick: ObservationTick):
        with db_connect(self.db_path) as con:
            con.execute(
                "INSERT INTO observation_ticks (id, payload, created_at, provenance, session_id, symbol, event_time)"
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
                "INSERT INTO observation_signals (id, payload, created_at, provenance, session_id)"
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
                "INSERT INTO observation_sessions (id, start, end, status, meta) VALUES (?,?,?,?,?)",
                (sid, body["started_at"], "", "ACTIVE", json.dumps(body, default=str)),
            )
            con.commit()
        return sid

    def end_session(
        self,
        session_id: str,
        *,
        status: str = "ENDED",
        error: str | None = None,
        terminal_failure: dict[str, Any] | None = None,
    ) -> str:
        """Persist and return the authoritative session end timestamp.

        Returning the committed timestamp prevents the derived collector
        manifest from inventing a second ``stopped_at`` clock value.  Terminal
        failure metadata is stored with the canonical session row so exports
        can preserve the exact category and consecutive-failure count.
        """
        body: dict[str, Any] = {"ended_at": datetime.now(UTC).isoformat()}
        if error:
            body["error"] = error
        if terminal_failure is not None:
            body["terminal_failure"] = terminal_failure
        with db_connect(self.db_path) as con:
            existing = con.execute(
                "SELECT end, status FROM observation_sessions WHERE id=?", (session_id,)
            ).fetchone()
            # Terminal writes are idempotent.  This protects repeated stop,
            # restart recovery, and a caller retry after an ambiguous commit
            # from manufacturing a second end timestamp.
            if existing and existing[0] and existing[1] != "ACTIVE":
                return str(existing[0])
            con.execute(
                "UPDATE observation_sessions SET end=?, status=?, meta=COALESCE(meta,'') WHERE id=?",
                (body["ended_at"], status, session_id),
            )
            # merge end info into meta JSON
            row = con.execute("SELECT meta FROM observation_sessions WHERE id=?", (session_id,)).fetchone()
            if row and row[0]:
                try:
                    merged = {**json.loads(row[0]), **body}
                    con.execute(
                        "UPDATE observation_sessions SET meta=? WHERE id=?",
                        (json.dumps(merged, default=str), session_id),
                    )
                except ValueError:
                    pass
            con.commit()
        return body["ended_at"]

    # ---------------------------------------------------------------- reads
    def list_ticks(
        self, limit: int = 100, *, session_id: str | None = None, provenance: str | None = None
    ) -> list[dict[str, Any]]:
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

    def divergence_summary(self, session_id: str | None = None) -> dict[str, Any]:
        """Measure only observable paper/shadow intent divergence.

        Observation-only has no broker execution, therefore execution/fill
        divergence is explicitly UNAVAILABLE.  The measurable comparison is
        theoretical signal price versus the stored *hypothetical* fill price;
        it is not presented as realized slippage or PnL.
        """
        q = "SELECT payload FROM observation_signals"
        args: list[Any] = []
        if session_id:
            q += " WHERE session_id=?"
            args.append(session_id)
        with db_connect(self.db_path) as con:
            rows = con.execute(q, args).fetchall()
        paired: list[float] = []
        signal_count = 0
        no_trade_count = 0
        for (payload,) in rows:
            try:
                signal = json.loads(payload)
            except ValueError:
                continue
            signal_count += 1
            if not signal.get("signal_side"):
                no_trade_count += 1
                continue
            theoretical = signal.get("theoretical_price")
            hypothetical = signal.get("hypothetical_fill_price")
            if theoretical is None or hypothetical is None:
                continue
            try:
                t = float(theoretical)
                h = float(hypothetical)
            except (TypeError, ValueError):
                continue
            if t:
                paired.append((h - t) / abs(t) * 10_000)
        if paired:
            measured: dict[str, Any] = {
                "status": "MEASURED",
                "value": {
                    "count": len(paired),
                    "mean_bps": sum(paired) / len(paired),
                    "min_bps": min(paired),
                    "max_bps": max(paired),
                },
            }
        elif signal_count:
            measured = {
                "status": "INSUFFICIENT_EVIDENCE",
                "value": None,
                "reason": "signals have no paired theoretical and hypothetical prices",
            }
        else:
            measured = {"status": "UNAVAILABLE", "value": None, "reason": "no observation signals"}
        if not signal_count:
            return self.empty_divergence_shape(session_id)
        return {
            "session_id": session_id,
            "signals": signal_count,
            "no_trade_signals": no_trade_count,
            "hypothetical_price_divergence": measured,
            "execution_divergence": {
                "status": "UNAVAILABLE",
                "value": None,
                "reason": "OBSERVE_ONLY never submits orders and receives no realized fills",
            },
            "realized_pnl": {
                "status": "UNAVAILABLE",
                "value": None,
                "reason": "no positions or executions in observation store",
            },
            "order_path": {"orders_submitted": 0, "execution_engine_reachable": False},
        }

    def empty_divergence_shape(self, session_id: str | None = None) -> dict[str, Any]:
        """The exact zero-signal divergence report.

        Single source of truth for the no-signals case, so the collector's
        bounded manifest path can report divergence without scanning the
        signal table (OBSERVE_ONLY records no signals at all).
        """
        return {
            "session_id": session_id,
            "signals": 0,
            "no_trade_signals": 0,
            "hypothetical_price_divergence": {
                "status": "UNAVAILABLE",
                "value": None,
                "reason": "no observation signals",
            },
            "execution_divergence": {
                "status": "UNAVAILABLE",
                "value": None,
                "reason": "OBSERVE_ONLY never submits orders and receives no realized fills",
            },
            "realized_pnl": {
                "status": "UNAVAILABLE",
                "value": None,
                "reason": "no positions or executions in observation store",
            },
            "order_path": {"orders_submitted": 0, "execution_engine_reachable": False},
        }

    # ----------------------------------------------------- acquisition ledger

    #: Closed acquisition-outcome vocabulary — every acquisition attempt has
    #: exactly ONE outcome. Rejected/errored attempts never enter accepted
    #: tick data, and a missing interval is never classified as an observation.
    ATTEMPT_OUTCOMES = (
        "SESSION_START",  # session anchor row: schedule + policy, not a market attempt
        "STORED",  # validated quote persisted as a NEW accepted record
        "DUPLICATE",  # same raw broker quote already observed — never re-persisted
        "VALIDATION_REJECTED",  # provider rejected it (stale/future/spread/integrity/symbol)
        "RETRIEVAL_ERROR",  # broker/terminal retrieval or normalization failed
        "STORAGE_ERROR",  # validated quote could NOT be persisted — never accepted
        "UNRESOLVED",  # outcome could not be determined — never treated as market activity
    )

    def record_attempt(
        self,
        session_id: str,
        seq: int,
        *,
        outcome: str,
        attempted_at: str,
        scheduled_at: str | None = None,
        slot_index: int | None = None,
        interval_s: float | None = None,
        monotonic_s: float | None = None,
        record_id: str | None = None,
        dup_key: str | None = None,
        reason: str | None = None,
        persistence_ok: bool | None = None,
        deferred: bool = False,
        gap_slots: int = 0,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Append ONE acquisition-attempt row to the durable ledger.

        Append-only by construction: ``(session_id, seq)`` is the primary key,
        so a re-used sequence refuses rather than replacing history. The caller
        decides how a failure here is accounted for (the collector counts it);
        this method never swallows a storage error.
        """
        if outcome not in self.ATTEMPT_OUTCOMES:
            raise ValueError(f"unknown acquisition outcome {outcome!r}")
        body: dict[str, Any] = {
            "session_id": session_id,
            "seq": int(seq),
            "outcome": outcome,
            "attempted_at": attempted_at,
            "scheduled_at": scheduled_at,
            "slot_index": slot_index,
            "interval_s": interval_s,
            "monotonic_s": monotonic_s,
            "record_id": record_id,
            "dup_key": dup_key,
            "reason": reason,
            "persistence_ok": persistence_ok,
            "deferred": bool(deferred),
            "gap_slots": int(gap_slots),
        }
        if extra:
            body["extra"] = extra
        with db_connect(self.db_path) as con:
            con.execute(
                "INSERT INTO observation_attempts (session_id, seq, outcome, attempted_at, scheduled_at,"
                " slot_index, interval_s, monotonic_s, record_id, dup_key, reason, persistence_ok,"
                " deferred, gap_slots, payload) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    session_id,
                    int(seq),
                    outcome,
                    attempted_at,
                    scheduled_at,
                    slot_index,
                    interval_s,
                    monotonic_s,
                    record_id,
                    dup_key,
                    reason,
                    None if persistence_ok is None else int(bool(persistence_ok)),
                    int(bool(deferred)),
                    int(gap_slots),
                    json.dumps(body, sort_keys=True, default=str),
                ),
            )
            con.commit()

    def list_attempts(self, session_id: str) -> list[dict[str, Any]]:
        """Ledger rows for one session, in acquisition order."""
        with db_connect(self.db_path) as con:
            rows = con.execute(
                "SELECT seq, outcome, attempted_at, scheduled_at, slot_index, interval_s, monotonic_s,"
                " record_id, dup_key, reason, persistence_ok, deferred, gap_slots, payload"
                " FROM observation_attempts WHERE session_id=? ORDER BY seq",
                (session_id,),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for (
            seq,
            outcome,
            attempted_at,
            scheduled_at,
            slot_index,
            interval_s,
            monotonic_s,
            record_id,
            dup_key,
            reason,
            persistence_ok,
            deferred,
            gap_slots,
            payload,
        ) in rows:
            out.append(
                {
                    "session_id": session_id,
                    "seq": seq,
                    "outcome": outcome,
                    "attempted_at": attempted_at,
                    "scheduled_at": scheduled_at,
                    "slot_index": slot_index,
                    "interval_s": interval_s,
                    "monotonic_s": monotonic_s,
                    "record_id": record_id,
                    "dup_key": dup_key,
                    "reason": reason,
                    "persistence_ok": None if persistence_ok is None else bool(persistence_ok),
                    "deferred": bool(deferred),
                    "gap_slots": gap_slots,
                    "payload": payload,
                }
            )
        return out

    def attempt_reconciliation(self, session_id: str, *, stale_after_s: float = 300.0) -> dict[str, Any]:
        """Reconcile acquisition outcomes against the accepted-tick store.

        Invariant (FO-R1): every attempt is classified, and the accepted rows
        are exactly the attempts that reported a successful persistence — so
        ``stored + duplicate + validation_reject + retrieval_error +
        storage_error + unresolved == attempts`` holds with no residue, and no
        stored row exists without a ledger entry (both directions checked).
        Missing slots are reported as MISSED, never as market activity.
        """
        attempts = self.list_attempts(session_id)
        counts: dict[str, int] = dict.fromkeys(self.ATTEMPT_OUTCOMES, 0)
        stored_ids: list[str] = []
        for row in attempts:
            counts[row["outcome"]] = counts.get(row["outcome"], 0) + 1
            if row["outcome"] == "STORED" and row["record_id"]:
                stored_ids.append(row["record_id"])

        with db_connect(self.db_path) as con:
            store_ids = [
                r[0]
                for r in con.execute(
                    "SELECT id FROM observation_ticks WHERE session_id=? ORDER BY rowid", (session_id,)
                ).fetchall()
            ]
        stored_unique = len(set(stored_ids))
        missing = sorted(set(stored_ids) - set(store_ids))
        orphans = sorted(set(store_ids) - set(stored_ids))

        # Sequence continuity: attempts are numbered 1..N (seq 0 = session anchor).
        seqs = sorted(r["seq"] for r in attempts)
        expected_seqs = list(range(1, (max(seqs) + 1) if seqs else 1))
        seq_gaps = [s for s in expected_seqs if s not in set(seqs)]

        # Coverage: nominal poll slots vs the slots actually serviced.
        slots = sorted({r["slot_index"] for r in attempts if r["slot_index"] is not None})
        expected_slots = (max(slots) + 1) if slots else 0
        missed = [i for i in range(expected_slots) if i not in set(slots)]
        ranges: list[list[int]] = []
        for idx in missed:
            if ranges and idx == ranges[-1][1] + 1:
                ranges[-1][1] = idx
            else:
                ranges.append([idx, idx])

        attempted = [r["attempted_at"] for r in attempts if r["attempted_at"]]
        last_age: float | None = None
        if attempted:
            with contextlib.suppress(ValueError):
                last_age = (datetime.now(UTC) - datetime.fromisoformat(attempted[-1])).total_seconds()
        status = (self.session(session_id) or {}).get("status")

        market_attempts = [r for r in attempts if r["outcome"] != "SESSION_START"]
        classified = sum(counts[k] for k in self.ATTEMPT_OUTCOMES if k != "SESSION_START")
        return {
            "session_id": session_id,
            "session_status": status,
            "attempts": len(market_attempts),
            "counts_by_outcome": counts,
            "stored": stored_unique,
            "duplicate_skip": counts["DUPLICATE"],
            "validation_reject": counts["VALIDATION_REJECTED"],
            "retrieval_error": counts["RETRIEVAL_ERROR"],
            "storage_error": counts["STORAGE_ERROR"],
            "unresolved": counts["UNRESOLVED"],
            "deferred_attempts": sum(1 for r in attempts if r["deferred"]),
            "classified_total": classified,
            "accounting_balanced": classified == len(market_attempts),
            "store_rows": len(store_ids),
            "ledger_store_agreement": (stored_unique == len(store_ids) and not missing and not orphans),
            "missing_record_ids": missing,
            "orphan_store_ids": orphans,
            "sequence_contiguous": not seq_gaps,
            "sequence_gaps": seq_gaps[:100],
            "expected_slots": expected_slots,
            "serviced_slots": len(slots),
            "missed_slots": len(missed),
            "missed_slot_ranges": ranges[:50],
            "missed_slot_ranges_truncated": len(ranges) > 50,
            "first_attempt_at": attempted[0] if attempted else None,
            "last_attempt_at": attempted[-1] if attempted else None,
            "last_attempt_age_s": last_age,
            "stale_active": bool(status == "ACTIVE" and last_age is not None and last_age > stale_after_s),
            "note": (
                "MISSED slots and UNRESOLVED attempts are NOT market activity: they carry no price "
                "and must never be read as zero spread, zero volatility or a quiet market."
            ),
        }

    def clock_history(self, session_id: str) -> dict[str, Any]:
        """Measured broker-UTC offset history for one session.

        Derived from the per-attempt ledger (each row carries the offset and
        basis actually applied). Reports only what was observed; the adapter
        exposes no measurement timestamp, so that field is never fabricated.
        """
        seen: dict[tuple[float, str], dict[str, Any]] = {}
        for row in self.list_attempts(session_id):
            try:
                extra = json.loads(row["payload"] or "{}").get("extra") or {}
            except ValueError:
                continue
            offset = extra.get("server_utc_offset_s")
            if offset is None:
                continue
            basis = str(extra.get("offset_basis", "unknown"))
            key = (float(offset), basis)
            entry = seen.setdefault(
                key,
                {
                    "server_utc_offset_s": float(offset),
                    "basis": basis,
                    "first_seen_at": row["attempted_at"],
                    "last_seen_at": row["attempted_at"],
                    "observations": 0,
                },
            )
            entry["last_seen_at"] = row["attempted_at"]
            entry["observations"] += 1
        offsets = sorted(seen.values(), key=lambda e: (e["first_seen_at"] or "", e["server_utc_offset_s"]))
        return {
            "session_id": session_id,
            "distinct_offsets": len(offsets),
            "offsets": offsets,
            "offset_changed_mid_session": len(offsets) > 1,
            "measurement_time": {
                "status": "UNAVAILABLE",
                "value": None,
                "reason": "the MT5 adapter exposes the measured offset and its basis, not the measurement timestamp",
            },
        }

    def stale_active_sessions(self, *, stale_after_s: float = 300.0) -> list[dict[str, Any]]:
        """ACTIVE sessions whose ledger has gone quiet — a possible unexplained stop.

        A worker that dies without writing a terminal state leaves its session
        ACTIVE. This is the durable detector for that condition (it never
        rewrites the historical row; it reports it).
        """
        with db_connect(self.db_path) as con:
            rows = con.execute("SELECT id FROM observation_sessions WHERE status='ACTIVE'").fetchall()
        out: list[dict[str, Any]] = []
        for (sid,) in rows:
            rec = self.attempt_reconciliation(sid, stale_after_s=stale_after_s)
            if rec["stale_active"]:
                out.append(
                    {
                        "session_id": sid,
                        "last_attempt_at": rec["last_attempt_at"],
                        "last_attempt_age_s": rec["last_attempt_age_s"],
                        "attempts": rec["attempts"],
                        "reason": "session is ACTIVE with no recent acquisition attempt — possible unexplained stop",
                    }
                )
        return out

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
        divergence = self.divergence_summary()
        return {
            "canonical_store": str(self.db_path),
            "active_observation_sessions": sessions,
            "ticks_recorded": tick_count,
            "signals_recorded": signal_count,
            "real_market_ticks": real_count,
            "ticks_by_provenance": by_prov,
            "divergence": divergence,
            "no_capital_exposure": True,
            "code_version": code_version(),
            "safety": "No live trading — OBSERVE_ONLY market observations only; no orders or executions recorded",
            "measurement_limits": "Hypothetical price divergence may be measured; realized execution/PnL is UNAVAILABLE",
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
