"""Phase 15 & 16: One-way promotion + micro capital exposure."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from qts.db import connect as db_connect


class PromotionState(StrEnum):
    RESEARCH = "RESEARCH"
    CANDIDATE = "CANDIDATE"
    VALIDATING = "VALIDATING"
    VALIDATED = "VALIDATED"
    FORWARD_OBSERVATION = "FORWARD_OBSERVATION"
    PAPER_VERIFIED = "PAPER_VERIFIED"
    SHADOW_VERIFIED = "SHADOW_VERIFIED"
    DEMO_OBSERVATION = "DEMO_OBSERVATION"
    DEMO_EXECUTION = "DEMO_EXECUTION"
    MICRO_ELIGIBLE = "MICRO_ELIGIBLE"
    MICRO_VALIDATED = "MICRO_VALIDATED"
    LIVE_ELIGIBLE = "LIVE_ELIGIBLE"
    SUSPENDED = "SUSPENDED"
    REJECTED = "REJECTED"


_ALLOWED = {
    PromotionState.RESEARCH: {PromotionState.CANDIDATE, PromotionState.REJECTED},
    PromotionState.CANDIDATE: {
        PromotionState.VALIDATING,
        PromotionState.VALIDATED,
        PromotionState.REJECTED,
        PromotionState.SUSPENDED,
    },
    PromotionState.VALIDATING: {PromotionState.VALIDATED, PromotionState.REJECTED, PromotionState.SUSPENDED},
    PromotionState.VALIDATED: {PromotionState.FORWARD_OBSERVATION, PromotionState.REJECTED, PromotionState.SUSPENDED},
    PromotionState.FORWARD_OBSERVATION: {
        PromotionState.PAPER_VERIFIED,
        PromotionState.REJECTED,
        PromotionState.SUSPENDED,
    },
    PromotionState.PAPER_VERIFIED: {PromotionState.SHADOW_VERIFIED, PromotionState.REJECTED, PromotionState.SUSPENDED},
    PromotionState.SHADOW_VERIFIED: {
        PromotionState.DEMO_OBSERVATION,
        PromotionState.MICRO_ELIGIBLE,
        PromotionState.REJECTED,
        PromotionState.SUSPENDED,
    },
    # DEMO_EXECUTION is retained as a historical label only. The shipped
    # product has no transition into it; DEMO_OBSERVATION is terminal for the
    # broker-facing path unless it is rejected or suspended.
    PromotionState.DEMO_OBSERVATION: {PromotionState.REJECTED, PromotionState.SUSPENDED},
    PromotionState.DEMO_EXECUTION: {
        PromotionState.REJECTED,
        PromotionState.SUSPENDED,
    },  # legacy rows can only be wound down
    PromotionState.MICRO_ELIGIBLE: {PromotionState.MICRO_VALIDATED, PromotionState.REJECTED, PromotionState.SUSPENDED},
    PromotionState.MICRO_VALIDATED: {PromotionState.LIVE_ELIGIBLE, PromotionState.REJECTED, PromotionState.SUSPENDED},
    PromotionState.LIVE_ELIGIBLE: {PromotionState.SUSPENDED, PromotionState.REJECTED},
    PromotionState.SUSPENDED: {PromotionState.RESEARCH, PromotionState.REJECTED},
    PromotionState.REJECTED: set(),
}


@dataclass
class PromotionRecord:
    strategy_id: str
    from_state: str
    to_state: str
    timestamp: str
    reason: str
    evidence_hash: str


class PromotionLedger:
    def __init__(self, db_path: Path | str = "data/sqlite/qts.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _init(self):
        with db_connect(self.db_path) as con:
            con.execute(
                "CREATE TABLE IF NOT EXISTS promotion_state (strategy_id TEXT PRIMARY KEY, state TEXT, updated_at TEXT)"
            )
            con.execute(
                "CREATE TABLE IF NOT EXISTS promotion_log (id TEXT PRIMARY KEY, strategy_id TEXT, from_state TEXT, to_state TEXT, timestamp TEXT, reason TEXT, evidence_hash TEXT)"
            )
            con.commit()

    def get_state(self, strategy_id: str) -> PromotionState:
        with db_connect(self.db_path) as con:
            row = con.execute("SELECT state FROM promotion_state WHERE strategy_id=?", (strategy_id,)).fetchone()
            return PromotionState(row[0]) if row else PromotionState.RESEARCH

    def can_transition(self, strategy_id: str, target: PromotionState) -> tuple[bool, str]:
        cur = self.get_state(strategy_id)
        if target is PromotionState.DEMO_EXECUTION:
            return False, "DEMO_EXECUTION is disabled by product policy; no promotion path is shipped"
        if target not in _ALLOWED.get(cur, set()):
            return False, f"transition {cur} -> {target} not allowed (one-way, no skip)"
        return True, "ok"

    def transition(
        self, strategy_id: str, target: PromotionState, reason: str = "", evidence_hash: str = ""
    ) -> PromotionRecord:
        cur = self.get_state(strategy_id)
        ok, msg = self.can_transition(strategy_id, target)
        if not ok:
            raise ValueError(msg)
        # No manual DB edit can promote — all via this method (audit logged)
        with db_connect(self.db_path) as con:
            con.execute(
                "INSERT OR REPLACE INTO promotion_state VALUES (?,?,?)",
                (strategy_id, target.value, datetime.now(UTC).isoformat()),
            )
            rec_id = f"{strategy_id}:{cur}->{target}:{datetime.now(UTC).timestamp()}"
            con.execute(
                "INSERT INTO promotion_log VALUES (?,?,?,?,?,?,?)",
                (rec_id, strategy_id, cur.value, target.value, datetime.now(UTC).isoformat(), reason, evidence_hash),
            )
            con.commit()
        return PromotionRecord(
            strategy_id, cur.value, target.value, datetime.now(UTC).isoformat(), reason, evidence_hash
        )

    def suspend_on_anomaly(self, strategy_id: str, reason: str):
        cur = self.get_state(strategy_id)
        if cur not in (PromotionState.SUSPENDED, PromotionState.REJECTED):
            with contextlib.suppress(Exception):
                self.transition(strategy_id, PromotionState.SUSPENDED, reason=reason)

    def scaling_protocol(
        self,
        strategy_id: str,
        observations: int,
        drawdown: float,
        slippage: float,
        reconciliation_health: bool,
        expectancy_stability: bool,
    ) -> tuple[bool, str]:
        """Scaling must depend on forward observations, drawdown, slippage, reconciliation, expectancy stability."""
        if observations < 30:
            return False, "need >=30 forward observations"
        if drawdown > 0.1:
            return False, "drawdown >10% blocks scaling"
        if slippage > 5.0:
            return False, "slippage >5bps blocks scaling"
        if not reconciliation_health:
            return False, "reconciliation unhealthy"
        if not expectancy_stability:
            return False, "expectancy unstable"
        return True, "scaling allowed per protocol (wins alone never scale)"

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
