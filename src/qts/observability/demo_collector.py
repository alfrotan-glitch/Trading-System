"""OBSERVE-ONLY live collector — REAL MT5 market observations, ZERO orders.

Runtime path behind the UI button "Start Observation (No Orders)":

    POST /api/observe/start -> DEMO readiness must PASS (refuse otherwise)
      -> one explicit ForwardObservatory session
      -> background poller: MT5Adapter.ticks() (canonical timestamp contract,
         commit 0cb916f) -> MarketDataProvider.get_tick() (UNCHANGED
         validation: future/stale/spread/integrity, fail-closed)
      -> ObservationTick.from_domain_tick() -> ForwardObservatory.record_tick()
      -> real forward-observation manifest (class REAL)

Safety contract:
- market data ONLY. This module never calls order_send, never touches the
  execution engine, risk limits, promotion, or LIVE gates. `orders_submitted`
  is a constant 0 and the injected MT5 module's order_send is never reached.
- refuses to start unless the caller supplies a readiness report with
  passed=True (state BLOCKED otherwise, reasons surfaced).
- fail-closed runtime: terminal disconnect, stale data, timestamp conversion
  failure, symbol disappearance, and validation errors are recorded as
  failures; after `max_consecutive_failures` the session auto-stops with
  state STOPPED_ON_ERRORS and the session end is persisted. Invalid ticks
  are NEVER persisted.
- duplicate quotes (identical raw broker stamps) are skipped, never recorded
  twice — the same standing quote is not two observations.
- synthetic/simulated data has no path in: the observatory's simulation
  helper is never referenced by this module, and every persisted record
  carries broker_event_time, raw MT5 stamp, server_utc_offset_s,
  timestamp_basis, and full tick provenance.
- idempotent start (one collector/session), deterministic stop (thread join,
  persisted session end, final manifest).
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from qts.db import connect as db_connect
from qts.domain.value_objects import Instrument
from qts.observability.forward_observatory import ForwardObservatory, ObservationTick

MIN_INTERVAL_S = 0.2
MAX_INTERVAL_S = 60.0


class ObservationCollector:
    """Single OBSERVE-ONLY session over a validated live broker feed."""

    STATES = ("STOPPED", "OBSERVING", "BLOCKED", "STOPPED_ON_ERRORS")

    def __init__(
        self,
        provider: Any,  # MarketDataProvider (validation path, unchanged)
        observatory: ForwardObservatory,
        instrument: Instrument,
        broker_symbol: str,
        interval_s: float = 1.0,
        max_consecutive_failures: int = 30,
        manifest_path: Path | str = Path("data/evidence/forward_observation_manifest.json"),
        manifest_every_ticks: int = 60,
    ) -> None:
        self.provider = provider
        self.observatory = observatory
        self.instrument = instrument
        self.broker_symbol = broker_symbol
        self.interval_s = min(max(float(interval_s), MIN_INTERVAL_S), MAX_INTERVAL_S)
        self.max_consecutive_failures = max(1, int(max_consecutive_failures))
        self.manifest_path = Path(manifest_path)
        self.manifest_every_ticks = max(1, int(manifest_every_ticks))

        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

        self.state = "STOPPED"
        self.session_id: str | None = None
        self.started_at: str | None = None
        self.stopped_at: str | None = None
        self.blocked_reasons: list[str] = []
        self.readiness_at_start: dict[str, Any] | None = None

        self.ticks_recorded = 0
        self.duplicates_skipped = 0
        self.consecutive_failures = 0
        self.last_error: str | None = None
        self.last_tick_time: str | None = None  # broker event time (true UTC), ISO
        self.last_timestamp_basis: str | None = None
        self._last_raw_key: tuple[Any, Any, float] | None = None

    # ------------------------------------------------------------------ API

    @property
    def thread_alive(self) -> bool:
        """True while the poll thread exists and is running."""
        return bool(self._thread is not None and self._thread.is_alive())

    def start(self, readiness: dict[str, Any]) -> dict[str, Any]:
        """Begin observing. Idempotent; refuses without a PASSED readiness report."""
        with self._lock:
            if self.state == "OBSERVING":
                return self.status()  # idempotent: no duplicate collector/session
            if not readiness.get("passed"):
                self.state = "BLOCKED"
                self.blocked_reasons = [str(b) for b in readiness.get("blocked_reasons", [])] or [
                    "readiness not passed"
                ]
                return self.status()
            from qts.domain.modes import resolve_mode
            from qts.observability.lineage import code_version

            mode = resolve_mode()
            self.readiness_at_start = {
                "passed": True,
                "timestamp": readiness.get("timestamp"),
                "checks_passed": sum(1 for v in (readiness.get("checks") or {}).values() if v),
            }
            # Canonical session identity (finding #5): environment, broker,
            # symbol, timestamp basis, code version — bound at session start.
            self.session_id = self.observatory.start_session(
                meta={
                    "kind": "LIVE_OBSERVATION",
                    "mode": mode.value,
                    "environment": mode.value,
                    "canonical_symbol": self.instrument.symbol,
                    "broker_symbol": self.broker_symbol,
                    "broker": "MT5",
                    "data_source": "MT5Adapter.ticks -> MarketDataProvider.get_tick",
                    "timestamp_basis": "broker-normalized(measured-m1-bar|assumed-utc-fallback)",
                    "code_version": code_version(),
                    "readiness_checks_passed": self.readiness_at_start["checks_passed"],
                    "orders_possible": False,  # observe-only runtime has no order path
                }
            )
            self._stop.clear()
            self.state = "OBSERVING"
            self.started_at = datetime.now(UTC).isoformat()
            self._thread = threading.Thread(target=self._run, name="qts-observe-only", daemon=True)
            self._thread.start()
            return self.status()

    def stop(self) -> dict[str, Any]:
        """Deterministic stop: signal, persist session end + manifest, join.

        The join happens OUTSIDE the lock: the poll thread needs the lock for
        its bookkeeping, so joining under the lock would deadlock until the
        join timeout (observed as a multi-second stop).
        """
        with self._lock:
            if self.state != "OBSERVING":
                return self.status()  # idempotent
            thread = self._finish("STOPPED")
        self._join(thread)
        with self._lock:
            return self.status()

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "state": self.state,
                "mode": "OBSERVE_ONLY",
                "orders_submitted": 0,  # invariant: this runtime has no order path
                "session_id": self.session_id,
                "symbol": self.broker_symbol,
                "instrument_symbol": self.instrument.symbol,
                "interval_s": self.interval_s,
                "ticks_recorded": self.ticks_recorded,
                "duplicates_skipped": self.duplicates_skipped,
                "consecutive_failures": self.consecutive_failures,
                "max_consecutive_failures": self.max_consecutive_failures,
                "last_tick_time": self.last_tick_time,
                "timestamp_basis": self.last_timestamp_basis,
                "last_error": self.last_error,
                "blocked_reasons": list(self.blocked_reasons),
                "started_at": self.started_at,
                "stopped_at": self.stopped_at,
                "readiness_at_start": self.readiness_at_start,
                "thread_alive": self.thread_alive,
            }

    # ----------------------------------------------------------------- loop

    def _run(self) -> None:
        # The loop exits only when _stop is set, and every setter (_finish)
        # has already persisted the terminal state — no finalizer needed here
        # (a lock-taking finalizer would deadlock against stop()'s join).
        while not self._stop.is_set():
            self._poll_once()
            if self._stop.wait(self.interval_s):
                break

    def _poll_once(self) -> None:
        try:
            tick = self.provider.get_tick(self.instrument)
        except Exception as e:  # noqa: BLE001 — fail-closed: ANY retrieval/validation error counts
            self._register_failure(f"{type(e).__name__}: {e}")
            return
        prov = tick.provenance or {}
        raw_key = (prov.get("mt5_time_msc"), prov.get("mt5_time"), float(tick.event_time.timestamp()))
        with self._lock:
            if raw_key == self._last_raw_key:
                self.duplicates_skipped += 1
                return  # same standing quote — not a new observation
            self._last_raw_key = raw_key
        obs = ObservationTick.from_domain_tick(tick, symbol=self.broker_symbol)
        # Provenance stamping: this collector only runs behind a PASSED 14/14
        # readiness gate whose checks include account_is_demo on the live
        # terminal — the observation class is DEMO (real broker, demo account).
        # No code path may stamp REAL from a demo session.
        obs.provenance = "DEMO"
        obs.session_id = self.session_id
        self.observatory.record_tick(obs)
        with self._lock:
            self.ticks_recorded += 1
            self.consecutive_failures = 0
            self.last_tick_time = (
                obs.broker_event_time.isoformat() if obs.broker_event_time else obs.timestamp.isoformat()
            )
            self.last_timestamp_basis = obs.timestamp_basis
            recorded = self.ticks_recorded
        if recorded % self.manifest_every_ticks == 0:
            self.write_manifest()

    def _register_failure(self, message: str) -> None:
        thread: threading.Thread | None = None
        with self._lock:
            self.consecutive_failures += 1
            self.last_error = f"{datetime.now(UTC).isoformat()} {message}"
            if self.consecutive_failures >= self.max_consecutive_failures:
                thread = self._finish("STOPPED_ON_ERRORS")
        self._join(thread)  # no-op when called from the poll thread itself

    def _join(self, thread: threading.Thread | None) -> None:
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=self.interval_s + 5.0)

    def _finish(self, new_state: str) -> threading.Thread | None:
        """Persist the terminal state; caller holds self._lock.

        Returns the poll thread so the CALLER can join it outside the lock.
        """
        self._stop.set()
        self.state = new_state
        self.stopped_at = datetime.now(UTC).isoformat()
        if self.session_id:
            self.observatory.end_session(
                self.session_id,
                status="ENDED" if new_state == "STOPPED" else "ENDED_ON_ERRORS",
                error=self.last_error,
            )
        thread = self._thread
        self._thread = None
        self.write_manifest()
        return thread

    # -------------------------------------------------------------- manifest

    def write_manifest(self) -> dict[str, Any]:
        """Aggregate the DEMO-class collected records into the DERIVED manifest.

        The canonical source is the observatory SQLite store; this JSON is a
        regenerable export (finding #5) and never the primary evidence.
        """
        session = self.observatory.session(self.session_id) if self.session_id else None
        with db_connect(self.observatory.db_path) as con:
            rows = con.execute("SELECT payload FROM observation_ticks ORDER BY created_at").fetchall()
        all_payloads: list[dict[str, Any]] = []
        bases: dict[str, int] = {}
        offsets: set[float] = set()
        spreads: list[float] = []
        first_event: str | None = None
        last_event: str | None = None
        symbols: set[str] = set()
        for (payload_json,) in rows:
            try:
                p = json.loads(payload_json)
            except ValueError:
                continue
            all_payloads.append(p)
            symbols.add(str(p.get("symbol", "")))
            basis = str(p.get("timestamp_basis", "unknown"))
            bases[basis] = bases.get(basis, 0) + 1
            off = p.get("server_utc_offset_s")
            if off is not None:
                offsets.add(float(off))
            sp = p.get("spread_bps")
            if isinstance(sp, (int, float)):
                spreads.append(float(sp))
            ev = p.get("broker_event_time")
            if ev:
                first_event = first_event or str(ev)
                last_event = str(ev)
        with self._lock:
            status_snapshot = self.status()
        manifest: dict[str, Any] = {
            "class": "DEMO",
            "data_class_note": (
                "live MT5 DEMO feed via OBSERVE-ONLY ObservationCollector behind a PASSED readiness gate; "
                "no synthetic, no simulation, no fixture data in this manifest; "
                "provenance class DEMO (real broker, demo account) — never presented as LIVE/REAL-money evidence"
            ),
            "mode": "OBSERVE_ONLY",
            "orders_submitted": 0,
            "order_send_called": False,
            "canonical_store": str(self.observatory.db_path),
            "derived_export": True,
            "symbols": sorted(s for s in symbols if s),
            "session": session,
            "state": status_snapshot["state"],
            "started_at": status_snapshot["started_at"],
            "stopped_at": status_snapshot["stopped_at"],
            "readiness_at_start": status_snapshot["readiness_at_start"],
            "ticks_recorded": len(all_payloads),
            "duplicates_skipped": status_snapshot["duplicates_skipped"],
            "first_event_time": first_event,
            "last_event_time": last_event,
            "timestamp_bases": bases,
            "server_utc_offsets_s": sorted(offsets),
            "spread_bps": (
                {"min": min(spreads), "avg": sum(spreads) / len(spreads), "max": max(spreads)} if spreads else None
            ),
            "last_error": status_snapshot["last_error"],
            "pipeline": "MT5Adapter.ticks -> MarketDataProvider.get_tick (validated) -> ForwardObservatory",
            "timestamp_contract": "docs/mt5_demo_setup.md#canonical-timestamp-contract-ticks--observations",
            "generated_at": datetime.now(UTC).isoformat(),
        }
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8")
        return manifest
