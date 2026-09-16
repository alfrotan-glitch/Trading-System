"""Forward Market Observatory — safe forward-observation mode without real orders.
Records live quotes, spreads, volatility, sessions, signals, NO_TRADE, hypothetical orders/fills, theoretical vs executable prices, latency, regime, interruptions, anomalies.
No live trading, no capital exposure — data becomes future research evidence.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from qts.domain.value_objects import uuid7


class ObservationTick(BaseModel):
    id: str = Field(default_factory=lambda: f"OT-{uuid7()[:6]}")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
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


class ForwardObservatory:
    def __init__(self, db_path: Path | str = "data/sqlite/forward_observatory.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _init(self):
        with sqlite3.connect(self.db_path) as con:
            con.execute("CREATE TABLE IF NOT EXISTS observation_ticks (id TEXT PRIMARY KEY, payload TEXT, created_at TEXT)")
            con.execute("CREATE TABLE IF NOT EXISTS observation_signals (id TEXT PRIMARY KEY, payload TEXT, created_at TEXT)")
            con.execute("CREATE TABLE IF NOT EXISTS observation_sessions (id TEXT PRIMARY KEY, start TEXT, end TEXT, status TEXT)")
            con.commit()

    def record_tick(self, tick: ObservationTick):
        with sqlite3.connect(self.db_path) as con:
            con.execute("INSERT OR REPLACE INTO observation_ticks VALUES (?,?,?)", (tick.id, tick.model_dump_json(), tick.timestamp.isoformat()))
            con.commit()

    def record_signal(self, sig: ObservationSignal):
        with sqlite3.connect(self.db_path) as con:
            con.execute("INSERT OR REPLACE INTO observation_signals VALUES (?,?,?)", (sig.id, sig.model_dump_json(), sig.timestamp.isoformat()))
            con.commit()

    def start_session(self, session_id: str | None = None) -> str:
        sid = session_id or f"FS-{uuid7()[:6]}"
        with sqlite3.connect(self.db_path) as con:
            con.execute("INSERT OR REPLACE INTO observation_sessions VALUES (?,?,?,?)", (sid, datetime.now(UTC).isoformat(), "", "ACTIVE"))
            con.commit()
        return sid

    def end_session(self, session_id: str):
        with sqlite3.connect(self.db_path) as con:
            con.execute("UPDATE observation_sessions SET end=?, status=? WHERE id=?", (datetime.now(UTC).isoformat(), "ENDED", session_id))
            con.commit()

    def summary(self) -> dict[str, Any]:
        with sqlite3.connect(self.db_path) as con:
            tick_count = con.execute("SELECT COUNT(*) FROM observation_ticks").fetchone()[0]
            signal_count = con.execute("SELECT COUNT(*) FROM observation_signals").fetchone()[0]
            sessions = con.execute("SELECT COUNT(*) FROM observation_sessions WHERE status='ACTIVE'").fetchone()[0]
        return {
            "active_observation_sessions": sessions,
            "ticks_recorded": tick_count,
            "signals_recorded": signal_count,
            "no_capital_exposure": True,
            "safety": "No live trading — only hypothetical executions recorded",
        }

    def to_manifest(self, path: Path = Path("data/evidence/forward_observation_manifest.json")) -> dict[str, Any]:
        s = self.summary()
        # Also include sample ticks/signals
        with sqlite3.connect(self.db_path) as con:
            tick_rows = con.execute("SELECT payload FROM observation_ticks ORDER BY created_at DESC LIMIT 5").fetchall()
            sig_rows = con.execute("SELECT payload FROM observation_signals ORDER BY created_at DESC LIMIT 5").fetchall()
        s["sample_ticks"] = [json.loads(r[0]) for r in tick_rows]
        s["sample_signals"] = [json.loads(r[0]) for r in sig_rows]
        s["generated_at"] = datetime.now(UTC).isoformat()
        s["forward_observation_protocol"] = "docs/forward_observation_protocol.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(s, indent=2, default=str))
        return s

    def simulate_observation(self, symbol: str = "XAUUSD", n_ticks: int = 10):
        """Simulate n_ticks of forward observation without capital — for testing/demo."""
        import random
        from decimal import Decimal
        session = self.start_session()
        base = Decimal("2000")
        for i in range(n_ticks):
            spread = Decimal(str(random.uniform(0.5, 1.5)))
            bid = base + Decimal(str(random.uniform(-2, 2)))
            ask = bid + spread
            tick = ObservationTick(symbol=symbol, bid=bid, ask=ask, mid=(bid+ask)/2, spread_bps=float(spread/base*10000), session="London" if i%2==0 else "NY", regime="trend" if i%3==0 else "range")
            self.record_tick(tick)
            # Simulate signal 30% of time, NO_TRADE otherwise
            if random.random() < 0.3:
                sig = ObservationSignal(symbol=symbol, signal_side="BUY" if random.random()<0.5 else "SELL", strategy_id="demo_state_machine", theoretical_price=tick.mid, executable_bid=tick.bid, executable_ask=tick.ask, hypothetical_fill_price=tick.ask if random.random()<0.5 else tick.bid, slippage_model_bps=2.0, regime_at_signal=tick.regime)
            else:
                sig = ObservationSignal(symbol=symbol, signal_side=None, strategy_id="demo_state_machine", no_trade_reason="regime filter: range chop" if tick.regime=="range" else "volatility too low")
            self.record_signal(sig)
        self.end_session(session)
        return self.summary()
