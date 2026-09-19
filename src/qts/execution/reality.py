"""Execution-Reality Data — collect SIGNAL vs EXPECTED vs ACTUAL execution, without claiming realism without observations."""

from __future__ import annotations

import contextlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from qts.db import connect as db_connect
from qts.domain.value_objects import uuid7


class ExecutionObservation(BaseModel):
    id: str = Field(default_factory=lambda: f"EO-{uuid7()[:6]}")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    symbol: str
    signal_price: Decimal  # signal generation price (mid or close)
    expected_price: Decimal  # executable bid/ask at decision time
    requested_price: Decimal
    submission_timestamp: datetime
    broker_ack_timestamp: datetime | None = None
    fill_timestamp: datetime | None = None
    requested_volume: Decimal
    filled_volume: Decimal = Decimal("0")
    realized_price: Decimal | None = None
    bid_at_decision: Decimal | None = None
    ask_at_decision: Decimal | None = None
    spread_at_decision: Decimal | None = None
    slippage_bps: float | None = None
    latency_ms: float | None = None
    rejection_reason: str | None = None
    cancellation_reason: str | None = None
    partial_fill: bool = False
    market_state: str = "unknown"  # e.g., "open", "high_vol", "low_liquidity"
    # Fail-closed: an execution observation is not a verified REAL fill merely
    # because a caller omitted its provenance.
    source: str = (
        "UNVERIFIED"  # REAL, DEMO, SYNTHETIC, SIMULATED, ESTIMATED, MODEL_DERIVED
    )

    def compute_slippage(self):
        if self.realized_price and self.expected_price and self.expected_price != 0:
            diff = float(self.realized_price - self.expected_price) / float(self.expected_price) * 10000
            self.slippage_bps = diff
            if self.broker_ack_timestamp and self.submission_timestamp:
                self.latency_ms = (self.broker_ack_timestamp - self.submission_timestamp).total_seconds() * 1000


class ExecutionRealityStore:
    def __init__(self, db_path: Path | str = "data/sqlite/execution_reality.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _init(self):
        with db_connect(self.db_path) as con:
            con.execute(
                "CREATE TABLE IF NOT EXISTS execution_observations (id TEXT PRIMARY KEY, payload TEXT, created_at TEXT)"
            )
            con.commit()

    def record(self, obs: ExecutionObservation):
        obs.compute_slippage()
        with db_connect(self.db_path) as con:
            con.execute(
                "INSERT OR REPLACE INTO execution_observations VALUES (?,?,?)",
                (obs.id, obs.model_dump_json(), obs.timestamp.isoformat()),
            )
            con.commit()

    def list(self, limit: int = 100) -> list[ExecutionObservation]:
        with db_connect(self.db_path) as con:
            rows = con.execute(
                "SELECT payload FROM execution_observations ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [ExecutionObservation.model_validate_json(r[0]) for r in rows]

    def summary(self) -> dict[str, Any]:
        obs = self.list(limit=1000)
        if not obs:
            return {
                "count": 0,
                "note": "No real execution observations — cannot claim execution realism without actual observations. Synthetic may be used but must be labeled SYNTHETIC.",
            }
        real = [o for o in obs if o.source == "REAL"]
        synth = [o for o in obs if o.source != "REAL"]
        slippages = [o.slippage_bps for o in real if o.slippage_bps is not None]
        return {
            "count": len(obs),
            "real_count": len(real),
            "synthetic_count": len(synth),
            "avg_slippage_bps": float(sum(slippages) / len(slippages)) if slippages else None,
            "max_slippage_bps": float(max(slippages)) if slippages else None,
            "rejections": len([o for o in obs if o.rejection_reason]),
            "partial_fills": len([o for o in obs if o.partial_fill]),
            "never_claim_real_without_observations": True,
        }

    def to_json(self, path: Path = Path("data/evidence/execution_reality.json")) -> dict[str, Any]:
        s = self.summary()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(s, indent=2, default=str), encoding="utf-8")
        return s

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
