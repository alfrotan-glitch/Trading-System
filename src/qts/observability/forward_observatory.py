"""Forward Market Observatory — safe forward-observation mode without real orders.
Records live quotes, spreads, volatility, sessions, signals, NO_TRADE, hypothetical orders/fills, theoretical vs executable prices, latency, regime, interruptions, anomalies.
No live trading, no capital exposure — data becomes future research evidence.
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
from qts.domain.value_objects import Tick, uuid7


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
    # Broker-timestamp provenance — every stored observation must expose its
    # timestamp basis (canonical contract: MT5 server-basis stamps normalized
    # to true UTC via the measured server offset).
    broker_event_time: datetime | None = None  # normalized true-UTC quote time
    broker_time_raw: float | None = None  # raw MT5 server-basis epoch seconds, as received
    server_utc_offset_s: float | None = None  # offset applied during normalization
    timestamp_basis: str = "ingest-utc"  # ingest-utc | broker-normalized(<offset basis>)
    tick_provenance: dict[str, Any] | None = None  # full Tick.provenance (receipt time, stamps, basis)

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


class ForwardObservatory:
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
            con.commit()

    def record_tick(self, tick: ObservationTick):
        with db_connect(self.db_path) as con:
            con.execute(
                "INSERT OR REPLACE INTO observation_ticks VALUES (?,?,?)",
                (tick.id, tick.model_dump_json(), tick.timestamp.isoformat()),
            )
            con.commit()

    def record_signal(self, sig: ObservationSignal):
        with db_connect(self.db_path) as con:
            con.execute(
                "INSERT OR REPLACE INTO observation_signals VALUES (?,?,?)",
                (sig.id, sig.model_dump_json(), sig.timestamp.isoformat()),
            )
            con.commit()

    def start_session(self, session_id: str | None = None) -> str:
        sid = session_id or f"FS-{uuid7()[:6]}"
        with db_connect(self.db_path) as con:
            con.execute(
                "INSERT OR REPLACE INTO observation_sessions VALUES (?,?,?,?)",
                (sid, datetime.now(UTC).isoformat(), "", "ACTIVE"),
            )
            con.commit()
        return sid

    def end_session(self, session_id: str):
        with db_connect(self.db_path) as con:
            con.execute(
                "UPDATE observation_sessions SET end=?, status=? WHERE id=?",
                (datetime.now(UTC).isoformat(), "ENDED", session_id),
            )
            con.commit()

    def summary(self) -> dict[str, Any]:
        with db_connect(self.db_path) as con:
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
        with db_connect(self.db_path) as con:
            tick_rows = con.execute("SELECT payload FROM observation_ticks ORDER BY created_at DESC LIMIT 5").fetchall()
            sig_rows = con.execute(
                "SELECT payload FROM observation_signals ORDER BY created_at DESC LIMIT 5"
            ).fetchall()
        s["sample_ticks"] = [json.loads(r[0]) for r in tick_rows]
        s["sample_signals"] = [json.loads(r[0]) for r in sig_rows]
        s["generated_at"] = datetime.now(UTC).isoformat()
        s["forward_observation_protocol"] = "docs/forward_observation_protocol.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(s, indent=2, default=str), encoding="utf-8")
        return s

    def simulate_observation(self, symbol: str = "XAUUSD", n_ticks: int = 10):
        """Simulate n_ticks of forward observation without capital — for testing/demo."""
        import random
        from decimal import Decimal

        session = self.start_session()
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
                )
            else:
                sig = ObservationSignal(
                    symbol=symbol,
                    signal_side=None,
                    strategy_id="demo_state_machine",
                    no_trade_reason="regime filter: range chop" if tick.regime == "range" else "volatility too low",
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
