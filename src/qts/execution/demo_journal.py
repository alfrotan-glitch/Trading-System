"""DEMO forward-observation journal — the audit trail for every DEMO order.

Everything the owner asked to be recorded lives here:

* signal → order request → fill → spread → slippage → latency → position
  lifecycle → stop/target behaviour → exit reason → realized/unrealized P&L →
  market state at entry and exit;
* broker order ID / position ID and retcode (safeguard #14);
* requested price, executed price, spread, slippage and timestamps (#15);
* the strategy ID **and the frozen configuration hash** responsible (#16);
* the authorization ID that permitted the order, and the immutable
  ``RESEARCH_DEMO_ORDER`` label so a DEMO research order can never be replayed
  or reported as a LIVE order.

The journal is append-oriented and separate from historical research evidence:
forward DEMO observations are *not* research results and must never be fed
back into parameter selection (see ``docs/demo_execution_authorization_and_safety_2026-09-23.md``).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from qts.db import connect as db_connect
from qts.db import immediate as db_immediate
from qts.execution.demo_pretrade import REQUIRED_RECORD_FIELDS, RESEARCH_DEMO_ORDER

ORDER_JOURNAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS demo_order_journal (
    journal_id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT NOT NULL,
    authorization_id TEXT,
    client_order_id TEXT NOT NULL,
    strategy_id TEXT,
    strategy_config_hash TEXT,
    hypothesis_id TEXT,
    registry_entry_hash TEXT,
    symbol TEXT,
    broker_symbol TEXT,
    side TEXT,
    order_type TEXT,
    requested_lots TEXT,
    requested_price TEXT,
    stop_loss TEXT,
    take_profit TEXT,
    order_request TEXT,
    signal_snapshot TEXT,
    signal_at TEXT,
    requested_at TEXT,
    submitted_at TEXT,
    acknowledged_at TEXT,
    closed_at TEXT,
    broker_order_id TEXT,
    broker_position_id TEXT,
    broker_retcode TEXT,
    filled_lots TEXT,
    executed_price TEXT,
    spread_bps REAL,
    slippage_bps REAL,
    latency_ms REAL,
    state TEXT NOT NULL,
    exit_reason TEXT,
    realized_pnl TEXT,
    unrealized_pnl TEXT,
    fees TEXT,
    market_state_entry TEXT,
    market_state_exit TEXT,
    reconciled INTEGER,
    reconcile_note TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

SIGNAL_JOURNAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS demo_signal_journal (
    journal_id INTEGER PRIMARY KEY AUTOINCREMENT,
    authorization_id TEXT,
    strategy_id TEXT,
    strategy_config_hash TEXT,
    symbol TEXT,
    side TEXT,
    signal_id TEXT,
    rationale TEXT,
    market_state TEXT,
    decision TEXT NOT NULL,
    reason TEXT,
    created_at TEXT NOT NULL
)
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _epoch(iso_value: str | None) -> float | None:
    if not iso_value:
        return None
    try:
        dt = datetime.fromisoformat(iso_value)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.timestamp()


class DemoOrderJournal:
    """Durable DEMO order/signal journal (SQLite, exported to JSONL)."""

    def __init__(self, db_path: Path | str = "data/sqlite/qts.db") -> None:
        self.db_path = Path(db_path)
        if str(db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with db_connect(self.db_path) as con:
            con.execute(ORDER_JOURNAL_SCHEMA)
            con.execute(SIGNAL_JOURNAL_SCHEMA)
            con.commit()

    # ------------------------------------------------------------- capability
    @staticmethod
    def record_fields_available() -> dict[str, bool]:
        """Capability report consumed by the pre-trade gate (safeguard #15)."""
        columns = {
            "authorization_id",
            "client_order_id",
            "strategy_id",
            "strategy_config_hash",
            "requested_price",
            "executed_price",
            "spread_bps",
            "slippage_bps",
            "requested_at",
            "submitted_at",
            "broker_order_id",
            "label",
        }
        return {field: field in columns for field in REQUIRED_RECORD_FIELDS}

    # ------------------------------------------------------------------ write
    def record_signal(
        self,
        *,
        strategy_id: str,
        strategy_config_hash: str,
        symbol: str,
        decision: str,
        side: str | None = None,
        signal_id: str | None = None,
        rationale: str = "",
        market_state: dict[str, Any] | None = None,
        reason: str = "",
        authorization_id: str | None = None,
    ) -> int:
        """Record a signal — including the NO_TRADE decisions (auditable flat)."""
        with db_connect(self.db_path) as con:
            cur = con.execute(
                "INSERT INTO demo_signal_journal (authorization_id, strategy_id, strategy_config_hash, symbol,"
                " side, signal_id, rationale, market_state, decision, reason, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    authorization_id,
                    strategy_id,
                    strategy_config_hash,
                    symbol,
                    side,
                    signal_id,
                    rationale,
                    json.dumps(market_state or {}, default=str),
                    decision,
                    reason,
                    _now(),
                ),
            )
            con.commit()
            return int(cur.lastrowid or 0)

    def open_order(
        self,
        *,
        client_order_id: str,
        strategy_id: str,
        strategy_config_hash: str,
        symbol: str,
        side: str,
        requested_lots: Decimal | str,
        order_request: dict[str, Any],
        authorization_id: str | None = None,
        hypothesis_id: str | None = None,
        registry_entry_hash: str | None = None,
        broker_symbol: str | None = None,
        order_type: str = "MARKET",
        requested_price: Decimal | str | None = None,
        stop_loss: Decimal | str | None = None,
        take_profit: Decimal | str | None = None,
        signal_snapshot: dict[str, Any] | None = None,
        signal_at: str | None = None,
        market_state_entry: dict[str, Any] | None = None,
        notes: str = "",
    ) -> int:
        now = _now()
        with db_connect(self.db_path) as con:
            cur = con.execute(
                "INSERT INTO demo_order_journal (label, authorization_id, client_order_id, strategy_id,"
                " strategy_config_hash, hypothesis_id, registry_entry_hash, symbol, broker_symbol, side,"
                " order_type, requested_lots, requested_price, stop_loss, take_profit, order_request,"
                " signal_snapshot, signal_at, requested_at, state, market_state_entry, notes, created_at,"
                " updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    RESEARCH_DEMO_ORDER,
                    authorization_id,
                    client_order_id,
                    strategy_id,
                    strategy_config_hash,
                    hypothesis_id,
                    registry_entry_hash,
                    symbol,
                    broker_symbol,
                    side,
                    order_type,
                    str(requested_lots),
                    None if requested_price is None else str(requested_price),
                    None if stop_loss is None else str(stop_loss),
                    None if take_profit is None else str(take_profit),
                    json.dumps(order_request, default=str),
                    json.dumps(signal_snapshot or {}, default=str),
                    signal_at,
                    now,
                    "NEW",
                    json.dumps(market_state_entry or {}, default=str),
                    notes,
                    now,
                    now,
                ),
            )
            con.commit()
            return int(cur.lastrowid or 0)

    # ------------------------------------------------------------ claiming

    def expire_inflight_rows(self, *, max_age_s: float = 120.0) -> int:
        """Fail a submission that never completed (process died mid-order).

        A row in ``NEW``/``SUBMITTED`` means "the broker call is in progress or
        its outcome was never recorded". If it is older than ``max_age_s`` the
        process that started it is gone, and the only honest state is
        ``REJECTED`` with an unknown-fill caveat — never "it probably worked".
        """
        cutoff = (datetime.now(UTC) - timedelta(seconds=max_age_s)).isoformat()
        with db_connect(self.db_path) as con:
            cur = con.execute(
                "UPDATE demo_order_journal SET state='REJECTED', "
                "exit_reason='in-flight submission abandoned (outcome unknown — verify with the broker)', "
                "updated_at=? WHERE state IN ('NEW','SUBMITTED') AND requested_at < ?",
                (_now(), cutoff),
            )
            con.commit()
            return int(cur.rowcount or 0)

    def claim_order_slot(
        self,
        *,
        client_order_id: str,
        strategy_id: str,
        strategy_config_hash: str,
        symbol: str,
        side: str,
        order_request: dict[str, Any],
        min_interval_s: float = 30.0,
        stale_inflight_s: float = 120.0,
        timeout_s: float = 30.0,
        authorization_id: str | None = None,
        hypothesis_id: str | None = None,
        registry_entry_hash: str | None = None,
        broker_symbol: str | None = None,
        requested_lots: Decimal | str = "0",
        requested_price: Decimal | str | None = None,
        stop_loss: Decimal | str | None = None,
        take_profit: Decimal | str | None = None,
        signal_snapshot: dict[str, Any] | None = None,
        signal_at: str | None = None,
        market_state_entry: dict[str, Any] | None = None,
        notes: str = "",
    ) -> tuple[int | None, str]:
        """Atomically reserve the right to send ONE order.

        The gate's duplicate/rate check reads the journal and the insert happens
        afterwards — fine for one process, racy for two (or for a CLI call while
        the autopilot is mid-cycle). This method performs the whole
        check-then-insert inside a single ``BEGIN IMMEDIATE`` transaction, so a
        concurrent caller either waits for this row or sees it and refuses:

        1. abandon stale in-flight rows (crash recovery);
        2. refuse if this strategy already ordered this symbol/side within
           ``min_interval_s`` (duplicate / rate guard);
        3. refuse if any submission is still in flight (one order at a time);
        4. insert the ``NEW`` row and return its id.

        Returns ``(journal_id, "claimed")`` or ``(None, reason)``.
        """
        now = _now()
        cutoff = (datetime.now(UTC) - timedelta(seconds=min_interval_s)).isoformat()
        stale_cutoff = (datetime.now(UTC) - timedelta(seconds=stale_inflight_s)).isoformat()
        try:
            with db_immediate(self.db_path, timeout=timeout_s) as con:
                # 1. crash recovery: unfinished submissions older than the
                #    in-flight budget cannot still be running.
                con.execute(
                    "UPDATE demo_order_journal SET state='REJECTED', "
                    "exit_reason='in-flight submission abandoned (outcome unknown — verify with the broker)', "
                    "updated_at=? WHERE state IN ('NEW','SUBMITTED') AND requested_at < ?",
                    (now, stale_cutoff),
                )
                # 2. duplicate / rate guard on committed rows.
                recent = con.execute(
                    "SELECT client_order_id, requested_at FROM demo_order_journal "
                    "WHERE strategy_id IS ? AND symbol IS ? AND side IS ? AND state NOT IN ('REJECTED') "
                    "AND requested_at >= ? ORDER BY journal_id DESC LIMIT 1",
                    (strategy_id, symbol, side, cutoff),
                ).fetchone()
                if recent is not None:
                    return None, (
                        f"duplicate/rate guard: order {recent[0]} was already requested this cycle "
                        f"(min interval {min_interval_s:.0f}s)"
                    )
                # 3. one submission in flight at a time (exposure is capped, and
                #    two concurrent market orders would double it).
                inflight = con.execute(
                    "SELECT client_order_id FROM demo_order_journal "
                    "WHERE state IN ('NEW','SUBMITTED') ORDER BY journal_id DESC LIMIT 1"
                ).fetchone()
                if inflight is not None:
                    return None, (
                        f"another submission is in flight ({inflight[0]}) — refusing to send a concurrent order"
                    )
                # 4. claim it.
                cur = con.execute(
                    "INSERT INTO demo_order_journal (label, authorization_id, client_order_id, strategy_id,"
                    " strategy_config_hash, hypothesis_id, registry_entry_hash, symbol, broker_symbol, side,"
                    " order_type, requested_lots, requested_price, stop_loss, take_profit, order_request,"
                    " signal_snapshot, signal_at, requested_at, state, market_state_entry, notes, created_at,"
                    " updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        RESEARCH_DEMO_ORDER,
                        authorization_id,
                        client_order_id,
                        strategy_id,
                        strategy_config_hash,
                        hypothesis_id,
                        registry_entry_hash,
                        symbol,
                        broker_symbol,
                        side,
                        "MARKET",
                        str(requested_lots),
                        None if requested_price is None else str(requested_price),
                        None if stop_loss is None else str(stop_loss),
                        None if take_profit is None else str(take_profit),
                        json.dumps(order_request, default=str),
                        json.dumps(signal_snapshot or {}, default=str),
                        signal_at,
                        now,
                        "NEW",
                        json.dumps(market_state_entry or {}, default=str),
                        notes,
                        now,
                        now,
                    ),
                )
                return int(cur.lastrowid or 0), "claimed"
        except sqlite3.OperationalError as exc:
            # A locked database is an unknown state: never assume the slot is free.
            return None, f"order slot could not be claimed atomically ({exc}) — refusing to submit"

    def _update(self, journal_id: int, **fields: Any) -> None:
        if not fields:
            return
        fields["updated_at"] = _now()
        assignments = ", ".join(f"{k}=?" for k in fields)
        values = list(fields.values()) + [journal_id]
        with db_connect(self.db_path) as con:
            con.execute(f"UPDATE demo_order_journal SET {assignments} WHERE journal_id=?", values)
            con.commit()

    def mark_submitted(
        self,
        journal_id: int,
        *,
        submitted_at: str | None = None,
        acknowledged_at: str | None = None,
        broker_order_id: str | None = None,
        broker_position_id: str | None = None,
        broker_retcode: str | None = None,
        latency_ms: float | None = None,
    ) -> None:
        submitted = submitted_at or _now()
        latency = latency_ms
        if latency is None:
            row = self.get(journal_id)
            requested_epoch = _epoch(row.get("requested_at")) if row else None
            submitted_epoch = _epoch(submitted)
            if requested_epoch is not None and submitted_epoch is not None:
                latency = max((submitted_epoch - requested_epoch) * 1000.0, 0.0)
        self._update(
            journal_id,
            state="SUBMITTED",
            submitted_at=submitted,
            acknowledged_at=acknowledged_at,
            broker_order_id=broker_order_id,
            broker_position_id=broker_position_id,
            broker_retcode=broker_retcode,
            latency_ms=latency,
        )

    def mark_fill(
        self,
        journal_id: int,
        *,
        filled_lots: Decimal | str,
        executed_price: Decimal | str,
        requested_price: Decimal | str | None = None,
        spread_bps: float | None = None,
        market_state_entry: dict[str, Any] | None = None,
        broker_position_id: str | None = None,
    ) -> None:
        """Record the fill, spread and slippage (vs the requested price)."""
        slippage: float | None = None
        if requested_price is not None:
            try:
                req = Decimal(str(requested_price))
                exe = Decimal(str(executed_price))
                if req > 0:
                    slippage = float((exe - req) / req * Decimal("10000"))
            except Exception:
                slippage = None
        fields: dict[str, Any] = {
            "state": "FILLED",
            "filled_lots": str(filled_lots),
            "executed_price": str(executed_price),
            "spread_bps": spread_bps,
            "slippage_bps": slippage,
        }
        if broker_position_id:
            fields["broker_position_id"] = broker_position_id
        if market_state_entry is not None:
            fields["market_state_entry"] = json.dumps(market_state_entry, default=str)
        self._update(journal_id, **fields)

    def mark_outcome(
        self,
        journal_id: int,
        *,
        state: str,
        exit_reason: str | None = None,
        realized_pnl: Decimal | str | None = None,
        fees: Decimal | str | None = None,
        market_state_exit: dict[str, Any] | None = None,
        closed_at: str | None = None,
        broker_retcode: str | None = None,
    ) -> None:
        fields: dict[str, Any] = {"state": state}
        if exit_reason is not None:
            fields["exit_reason"] = exit_reason
        if broker_retcode is not None:
            # Broker response codes belong on the record even when the order
            # never filled: "why the broker said no" is part of the audit trail.
            fields["broker_retcode"] = str(broker_retcode)
        if realized_pnl is not None:
            fields["realized_pnl"] = str(realized_pnl)
        if fees is not None:
            fields["fees"] = str(fees)
        if market_state_exit is not None:
            fields["market_state_exit"] = json.dumps(market_state_exit, default=str)
        if state in ("CLOSED", "REJECTED", "CANCELLED", "AMBIGUOUS"):
            fields["closed_at"] = closed_at or _now()
        self._update(journal_id, **fields)

    def update_unrealized(
        self,
        journal_id: int,
        *,
        unrealized_pnl: Decimal | str,
        market_state: dict[str, Any] | None = None,
    ) -> None:
        fields: dict[str, Any] = {"unrealized_pnl": str(unrealized_pnl)}
        if market_state is not None:
            fields["market_state_exit"] = json.dumps(market_state, default=str)
        self._update(journal_id, **fields)

    def mark_reconciled(self, journal_id: int, *, ok: bool, note: str = "") -> None:
        self._update(journal_id, reconciled=1 if ok else 0, reconcile_note=note)

    # ------------------------------------------------------------------- read
    def get(self, journal_id: int) -> dict[str, Any] | None:
        with db_connect(self.db_path) as con:
            con.row_factory = _row_factory
            row = con.execute("SELECT * FROM demo_order_journal WHERE journal_id=?", (journal_id,)).fetchone()
        return dict(row) if row else None

    def get_by_client_order_id(self, client_order_id: str) -> dict[str, Any] | None:
        with db_connect(self.db_path) as con:
            con.row_factory = _row_factory
            row = con.execute(
                "SELECT * FROM demo_order_journal WHERE client_order_id=? ORDER BY journal_id DESC LIMIT 1",
                (client_order_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_orders(self, limit: int = 100) -> list[dict[str, Any]]:
        with db_connect(self.db_path) as con:
            con.row_factory = _row_factory
            rows = con.execute(
                "SELECT * FROM demo_order_journal ORDER BY journal_id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def open_orders(self) -> list[dict[str, Any]]:
        return [
            r
            for r in self.list_orders(limit=500)
            if r.get("state") in ("NEW", "SUBMITTED", "ACCEPTED", "FILLED")
        ]

    def daily_realized_pnl(self, day: date | None = None) -> Decimal:
        """Realized P&L for the UTC day (negative = loss)."""
        target = (day or datetime.now(UTC).date()).isoformat()
        total = Decimal("0")
        with db_connect(self.db_path) as con:
            con.row_factory = _row_factory
            rows = con.execute(
                "SELECT realized_pnl, closed_at FROM demo_order_journal"
                " WHERE realized_pnl IS NOT NULL AND closed_at IS NOT NULL"
            ).fetchall()
        for row in rows:
            closed_at = row_dict(row).get("closed_at")
            if not closed_at or not str(closed_at).startswith(target):
                continue
            try:
                total += Decimal(str(row_dict(row).get("realized_pnl")))
            except Exception:
                continue
        return total

    def orders_today(self, day: date | None = None) -> int:
        target = (day or datetime.now(UTC).date()).isoformat()
        return sum(
            1
            for r in self.list_orders(limit=1000)
            if str(r.get("requested_at") or "").startswith(target) and r.get("state") != "REJECTED"
        )

    def recent_order_epochs(self, within_s: float) -> list[float]:
        now = datetime.now(UTC).timestamp()
        out: list[float] = []
        for r in self.list_orders(limit=200):
            epoch = _epoch(r.get("requested_at"))
            if epoch is not None and (now - epoch) < within_s:
                out.append(epoch)
        return out

    # ----------------------------------------------------------------- export
    def export_jsonl(self, out_path: str | Path) -> Path:
        """Export the journal for offline audit (append-only evidence)."""
        target = Path(out_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        rows = self.list_orders(limit=100000)
        with target.open("w", encoding="utf-8") as fh:
            for row in reversed(rows):
                fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")
        return target


def _row_factory(cursor: Any, row: Any) -> dict[str, Any]:
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


def row_dict(row: Any) -> dict[str, Any]:
    return dict(row) if row is not None else {}


@dataclass(frozen=True)
class JournalSummary:
    orders: int
    open_orders: int
    realized_pnl: Decimal
    unreconciled: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "orders": self.orders,
            "open_orders": self.open_orders,
            "realized_pnl": str(self.realized_pnl),
            "unreconciled": self.unreconciled,
        }


def summarize(journal: DemoOrderJournal) -> JournalSummary:
    orders = journal.list_orders(limit=1000)
    realized = Decimal("0")
    for row in orders:
        if row.get("realized_pnl"):
            try:
                realized += Decimal(str(row["realized_pnl"]))
            except Exception:
                continue
    return JournalSummary(
        orders=len(orders),
        open_orders=len(journal.open_orders()),
        realized_pnl=realized,
        unreconciled=sum(1 for r in orders if r.get("reconciled") in (None, 0)),
    )
