"""OBSERVE-ONLY live collector — REAL MT5 market observations, ZERO orders.

Runtime path behind the UI button "Start Observation (No Orders)":

    POST /api/observe/start -> DEMO readiness must PASS (refuse otherwise)
      -> one explicit ForwardObservatory session
      -> background poller: MT5Adapter.ticks() (canonical timestamp contract,
         commit 0cb916f) -> MarketDataProvider.get_tick() (UNCHANGED
         validation: future/stale/spread/integrity, fail-closed)
      -> ObservationTick.from_domain_tick() -> ForwardObservatory.record_tick()
      -> DEMO-class forward-observation manifest (real broker observations on a demo account; never REAL-money evidence)

Safety contract:
- market data ONLY. This module never calls order_send, never touches the
  execution engine, risk limits, promotion, or LIVE gates. `orders_submitted`
  is a constant 0 and the injected MT5 module's order_send is never reached.
- refuses to start unless the caller supplies a readiness report with
  passed=True (state BLOCKED otherwise, reasons surfaced).
- fail-closed runtime: terminal disconnect, stale data, timestamp conversion
  failure, symbol disappearance, validation errors, and storage/manifest
  publication errors are recorded as failures; after
  `max_consecutive_failures` the session auto-stops with state
  STOPPED_ON_ERRORS and the session end is persisted. Invalid ticks
  are NEVER persisted.
- duplicate quotes (identical raw broker stamps) are skipped, never recorded
  twice — the same standing quote is not two observations.
- synthetic/simulated data has no path in: the observatory's simulation
  helper is never referenced by this module, and every persisted record
  carries broker_event_time, raw MT5 stamp, server_utc_offset_s,
  timestamp_basis, and full tick provenance.
- idempotent start (one collector/session), deterministic stop (thread join,
  persisted session end, final manifest).
- the worker thread can never stop silently: an exception anywhere in the poll
  body is routed through the failure/lifecycle machinery, the terminal session
  write is bounded-retried and never blocked by the DERIVED manifest export,
  and `state` always flips to a terminal state when the worker ends. A session
  therefore cannot remain `ACTIVE` while advertising `OBSERVING` after the
  worker has stopped; a storage outage is surfaced loudly instead.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import platform
import sqlite3
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from qts.adapters.market_data import MarketDataError
from qts.db import connect as db_connect
from qts.domain.value_objects import Instrument
from qts.observability.forward_observatory import ForwardObservatory, ObservationTick

MIN_INTERVAL_S = 0.2
MAX_INTERVAL_S = 60.0
OBSERVATION_PRODUCT_MODE = "DEMO_FORWARD"
OBSERVATION_MODE = "OBSERVE_ONLY"
OBSERVATION_ENVIRONMENT = "DEMO_FORWARD"

#: Bounded journal backlog: attempts whose ledger row could not be written are
#: carried and flushed (flagged `deferred`) on the next successful write. The
#: cap keeps memory bounded during a long outage; overflow is recorded as ONE
#: explicit UNRESOLVED row, never silently dropped.
MAX_JOURNAL_BACKLOG = 500

#: Version of the session run-metadata contract (reproducibility identity).
RUN_METADATA_VERSION = "qts.run_metadata.v1"

#: Bounded retry for the terminal session-row write. Covers transient storage
#: contention (e.g. a momentary SQLite lock) without adding machinery.
_TERMINAL_PERSIST_ATTEMPTS = 3
_TERMINAL_PERSIST_RETRY_S = 0.05


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
        manifest_path: Path | str | None = None,
        manifest_every_ticks: int = 60,
    ) -> None:
        from qts.config.paths import artifact_path, resolve_state_path

        self.provider = provider
        self.observatory = observatory
        self.instrument = instrument
        self.broker_symbol = broker_symbol
        self.interval_s = min(max(float(interval_s), MIN_INTERVAL_S), MAX_INTERVAL_S)
        self.max_consecutive_failures = max(1, int(max_consecutive_failures))
        if manifest_path is None or str(manifest_path) == "data/evidence/forward_observation_manifest.json":
            self.manifest_path = artifact_path("forward_manifest")
        else:
            self.manifest_path = resolve_state_path(manifest_path)
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
        self.last_failure_category: str | None = None
        self._last_failure_at: str | None = None
        self.last_tick_time: str | None = None  # broker event time (true UTC), ISO
        self.last_timestamp_basis: str | None = None
        self._last_raw_key: tuple[Any, Any, float] | None = None
        #: Set when the terminal session row could not be persisted (storage
        #: outage at the transition). `stop()` retries it, so a session is
        #: never left permanently ACTIVE through inaction.
        self._terminal_persist_pending = False
        #: Derived terminal manifest publication also has a retry marker. The
        #: manifest is not canonical, but a stale terminal projection must be
        #: surfaced and repairable by an idempotent stop.
        self._terminal_manifest_pending = False
        #: The authoritative end timestamp returned by the canonical store.
        #: ``stopped_at`` and terminal manifests are derived from this value;
        #: it is never replaced by a later wall-clock read.
        self._authoritative_end: str | None = None
        #: The terminal failure reason captured at the transition (retry-safe).
        self._terminal_error: str | None = None
        self._terminal_failure: dict[str, Any] | None = None

        # ------------------------------------------------ acquisition ledger
        #: Monotonic per-session attempt counter (seq 0 = SESSION_START anchor).
        self._attempt_seq = 0
        #: Nominal poll-slot math: slot = floor((monotonic - start) / interval).
        self._start_monotonic = 0.0
        self._start_utc: datetime | None = None
        self._last_slot_index: int | None = None
        #: Attempts whose ledger row could not be written yet (bounded).
        self._journal_backlog: list[dict[str, Any]] = []
        #: Ledger rows that could not be persisted at all (bounded overflow).
        self._journal_dropped = 0
        #: In-memory mirror of the durable outcome counts (for status/reporting).
        self.attempt_outcomes: dict[str, int] = {}

        # ------------------------------------------- bounded manifest aggregate
        #: Incremental aggregate over ACCEPTED rows. Lets the periodic derived
        #: manifest stay O(1) instead of re-scanning the whole session; the
        #: canonical store remains the authority (full regeneration is still
        #: available via ``write_manifest(from_store=True)``).
        self._agg: dict[str, Any] = self._empty_aggregate()

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
            if self._terminal_persist_pending and self.session_id:
                # Never open a replacement session while the previous
                # canonical row is still ACTIVE.  Reuse the same retry path as
                # idempotent stop; if it remains unavailable, fail closed.
                end = self._persist_session_end(self.state, self._terminal_error)
                if end is None:
                    return self.status()
                self._authoritative_end = end
                self.stopped_at = end
                self._terminal_manifest_pending = False
                try:
                    self.write_manifest(state_override=self.state)
                except Exception as e:  # noqa: BLE001 — retry remains fail-closed
                    self._terminal_manifest_pending = True
                    self._note_diagnostic(f"terminal manifest retry failed: {type(e).__name__}: {e}")
            if not readiness.get("passed"):
                self.state = "BLOCKED"
                self.blocked_reasons = [str(b) for b in readiness.get("blocked_reasons", [])] or [
                    "readiness not passed"
                ]
                return self.status()
            from qts.domain.modes import resolve_mode
            from qts.observability.lineage import code_version

            application_mode = resolve_mode()
            readiness_checks = dict(readiness.get("checks") or {})
            self.readiness_at_start = {
                "passed": True,
                "timestamp": readiness.get("timestamp"),
                "checks_passed": sum(1 for v in readiness_checks.values() if v),
                "checks": readiness_checks,
                "blocked_reasons": list(readiness.get("blocked_reasons") or []),
            }
            # A running application's development mode is not the identity of
            # the broker observation.  This collector is only an observe-only
            # MT5 DEMO forward session; bind that identity explicitly and keep
            # the application mode only as non-authoritative diagnostics.
            run_metadata = self._build_run_metadata(mode=OBSERVATION_PRODUCT_MODE)
            # Canonical session identity (finding #5): product/environment,
            # observation mode, broker, symbol, timestamp basis, and code
            # version — bound at session start.
            self.session_id = self.observatory.start_session(
                meta={
                    "kind": "LIVE_OBSERVATION",
                    "product_mode": OBSERVATION_PRODUCT_MODE,
                    "observation_mode": OBSERVATION_MODE,
                    "mode": OBSERVATION_MODE,
                    "environment": OBSERVATION_ENVIRONMENT,
                    "application_mode": application_mode.value,
                    "canonical_symbol": self.instrument.symbol,
                    "broker_symbol": self.broker_symbol,
                    "broker": "MT5",
                    "data_source": "MT5Adapter.ticks -> MarketDataProvider.get_tick",
                    "timestamp_basis": "broker-normalized(measured-m1-bar|assumed-utc-fallback)",
                    "code_version": code_version(),
                    "readiness_checks_passed": self.readiness_at_start["checks_passed"],
                    "readiness_report": dict(readiness),
                    "orders_possible": False,  # observe-only runtime has no order path
                    "run_metadata": run_metadata,
                }
            )
            # A collector instance may be deliberately restarted after a
            # completed session.  Every runtime counter and terminal marker is
            # scoped to the new canonical session.
            self.started_at = None
            self.stopped_at = None
            self._authoritative_end = None
            self._terminal_persist_pending = False
            self._terminal_manifest_pending = False
            self._terminal_error = None
            self._terminal_failure = None
            self.last_error = None
            self.last_failure_category = None
            self._last_failure_at = None
            self.ticks_recorded = 0
            self.duplicates_skipped = 0
            self.consecutive_failures = 0
            self.last_tick_time = None
            self.last_timestamp_basis = None
            self._last_raw_key = None
            self._stop.clear()
            self.state = "OBSERVING"
            self.started_at = datetime.now(UTC).isoformat()
            # Acquisition-ledger anchor: schedule + policy are durable BEFORE
            # the first poll, so coverage is computable from the ledger alone.
            self._start_utc = datetime.now(UTC)
            self._start_monotonic = time.monotonic()
            self._last_slot_index = None
            self._attempt_seq = 0
            self._journal_backlog = []
            self._journal_dropped = 0
            self.attempt_outcomes = {}
            self._agg = self._empty_aggregate()
            self._journal(
                "SESSION_START",
                attempted_at=self._start_utc.isoformat(),
                scheduled_at=self._start_utc.isoformat(),
                slot_index=None,
                extra={
                    "interval_s": self.interval_s,
                    "max_consecutive_failures": self.max_consecutive_failures,
                    "manifest_every_ticks": self.manifest_every_ticks,
                    "run_metadata_version": RUN_METADATA_VERSION,
                },
            )
            self._thread = threading.Thread(target=self._run, name="qts-observe-only", daemon=True)
            self._thread.start()
            return self.status()

    def stop(self) -> dict[str, Any]:
        """Deterministic, idempotent stop with a canonical end timestamp.

        The join happens OUTSIDE the lock: the poll thread needs the lock for
        its bookkeeping, so joining under the lock would deadlock until the
        join timeout.  A retry after a terminal persistence outage also
        refreshes the terminal manifest, so the public projection catches up
        to the canonical session row without inventing a new end time.
        """
        with self._lock:
            if self.state != "OBSERVING":
                if self._terminal_persist_pending and self.session_id:
                    # The transition happened while storage was unavailable.
                    # Retry now so the session row cannot stay ACTIVE forever.
                    end = self._persist_session_end(self.state, self._terminal_error)
                    if end is not None:
                        self._authoritative_end = end
                        self.stopped_at = end
                        self._terminal_manifest_pending = True
                if self._terminal_manifest_pending:
                    self._terminal_manifest_pending = False
                    try:
                        self.write_manifest(state_override=self.state)
                    except Exception as e:  # noqa: BLE001 — retry remains fail-closed
                        self._terminal_manifest_pending = True
                        self._note_diagnostic(f"terminal manifest retry failed: {type(e).__name__}: {e}")
                return self.status()  # idempotent
            thread = self._finish("STOPPED")
        self._join(thread)
        with self._lock:
            return self.status()

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "state": self.state,
                "product_mode": OBSERVATION_PRODUCT_MODE,
                "observation_mode": OBSERVATION_MODE,
                "mode": OBSERVATION_MODE,
                "environment": OBSERVATION_ENVIRONMENT,
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
                "last_failure_category": self.last_failure_category,
                "blocked_reasons": list(self.blocked_reasons),
                "started_at": self.started_at,
                "stopped_at": self.stopped_at,
                "authoritative_end": self._authoritative_end,
                "terminal_failure": self._terminal_failure,
                "terminal_persist_pending": self._terminal_persist_pending,
                "terminal_manifest_pending": self._terminal_manifest_pending,
                "readiness_at_start": self.readiness_at_start,
                "thread_alive": self.thread_alive,
                # Acquisition-ledger mirror (in-memory; the durable ledger in
                # the canonical store is the authority — see reconciliation()).
                "acquisition_ledger": {
                    "attempts": self._attempt_seq,
                    "outcomes": dict(self.attempt_outcomes),
                    "journal_backlog": len(self._journal_backlog),
                    "journal_dropped": self._journal_dropped,
                },
            }

    # ----------------------------------------------------------------- loop

    def _run(self) -> None:
        # The loop exits only when _stop is set, and every setter (_finish)
        # has already persisted the terminal state — no finalizer needed here
        # (a lock-taking finalizer would deadlock against stop()'s join).
        while not self._stop.is_set():
            try:
                self._poll_once()
            except Exception as e:  # noqa: BLE001 — last resort: the worker must never die silently
                self._register_failure(
                    f"unexpected poll loop error: {type(e).__name__}: {e}",
                    category="WORKER_CRASH",
                )
            if self._stop.wait(self.interval_s):
                break

    def _poll_once(self) -> None:
        """One poll — fail-closed over the WHOLE body, not just retrieval.

        Retrieval/validation errors were already failure-accounted, but
        persistence (``record_tick``) and manifest publication were not: a
        storage or manifest exception escaped this method, killed the poll
        thread and left the session advertising ``OBSERVING`` with no counted
        failure, no diagnostic and no way to resume collection (the session row
        also stayed ACTIVE with no reason). Counting them through the SAME
        failure account keeps the documented contract: a transient error is
        tolerated and reset by the next recorded tick, and
        ``max_consecutive_failures`` consecutive errors auto-stop the session
        with a persisted terminal state.
        """
        try:
            self._poll_and_record()
        except Exception as e:  # noqa: BLE001 — fail-closed: ANY poll error counts
            self._register_failure(f"{type(e).__name__}: {e}", category=self._failure_category(str(e)))

    def _poll_and_record(self) -> None:
        """One acquisition attempt: classify its outcome in the durable ledger.

        Exactly one attempt row is written per call, whatever happens, so the
        ledger reconciles against the accepted-tick store in both directions.
        """
        slot_index, scheduled_at, gap_slots = self._slot_for_attempt()
        attempted_at = datetime.now(UTC).isoformat()
        clock = self._clock_extra()  # offset/basis actually in force, when known

        try:
            tick = self.provider.get_tick(self.instrument)
        except MarketDataError as e:
            # Machine-readable classification from the provider: a rejected
            # QUOTE is a validation rejection; an unobtainable tick is an
            # acquisition/availability failure. Both stay fail-closed.
            outcome = "RETRIEVAL_ERROR" if getattr(e, "kind", "validation") == "unavailable" else "VALIDATION_REJECTED"
            self._journal(
                outcome,
                attempted_at=attempted_at,
                scheduled_at=scheduled_at,
                slot_index=slot_index,
                gap_slots=gap_slots,
                reason=f"{type(e).__name__}: {e}",
                extra=clock,
            )
            self._register_failure(
                f"{type(e).__name__}: {e}",
                category="RETRIEVAL_UNAVAILABLE" if getattr(e, "kind", "validation") == "unavailable" else self._failure_category(str(e)),
            )
            return
        except Exception as e:  # noqa: BLE001 — retrieval/normalization failure
            self._journal(
                "RETRIEVAL_ERROR",
                attempted_at=attempted_at,
                scheduled_at=scheduled_at,
                slot_index=slot_index,
                gap_slots=gap_slots,
                reason=f"{type(e).__name__}: {e}",
                extra=clock,
            )
            self._register_failure(
                f"{type(e).__name__}: {e}", category="RETRIEVAL_ERROR"
            )
            return

        if tick is None:  # broker returned no tick (feed/terminal unavailable)
            self._journal(
                "RETRIEVAL_ERROR",
                attempted_at=attempted_at,
                scheduled_at=scheduled_at,
                slot_index=slot_index,
                gap_slots=gap_slots,
                reason="RuntimeError: no tick available from the broker",
                extra=clock,
            )
            self._register_failure("RuntimeError: no tick available from the broker", category="RETRIEVAL_UNAVAILABLE")
            return

        prov = tick.provenance or {}
        raw_key = (prov.get("mt5_time_msc"), prov.get("mt5_time"), float(tick.event_time.timestamp()))
        with self._lock:
            if raw_key == self._last_raw_key:
                # Same standing quote — not a new observation. The attempt is
                # still accounted (coverage), it is simply not a new record.
                self.duplicates_skipped += 1
                self._journal(
                    "DUPLICATE",
                    attempted_at=attempted_at,
                    scheduled_at=scheduled_at,
                    slot_index=slot_index,
                    gap_slots=gap_slots,
                    dup_key=self._dup_key(raw_key),
                    extra=clock,
                )
                return
            self._last_raw_key = raw_key

        obs = ObservationTick.from_domain_tick(tick, symbol=self.broker_symbol)
        # Provenance stamping: this collector only runs behind a PASSED 14/14
        # readiness gate whose checks include account_is_demo on the live
        # terminal — the observation class is DEMO (real broker, demo account).
        # No code path may stamp REAL from a demo session.
        obs.provenance = "DEMO"
        obs.session_id = self.session_id

        clock = {
            "server_utc_offset_s": prov.get("server_utc_offset_s"),
            "offset_basis": prov.get("offset_basis"),
        }
        try:
            self.observatory.record_tick(obs)
        except Exception as e:  # noqa: BLE001 — accepted quote NOT persisted -> not accepted
            self._journal(
                "STORAGE_ERROR",
                attempted_at=attempted_at,
                scheduled_at=scheduled_at,
                slot_index=slot_index,
                gap_slots=gap_slots,
                record_id=obs.id,
                reason=f"{type(e).__name__}: {e}",
                persistence_ok=False,
                extra=clock,
            )
            raise  # fail-closed accounting continues through _poll_once
        self._journal(
            "STORED",
            attempted_at=attempted_at,
            scheduled_at=scheduled_at,
            slot_index=slot_index,
            gap_slots=gap_slots,
            record_id=obs.id,
            persistence_ok=True,
            extra=clock,
        )
        with self._lock:
            self.ticks_recorded += 1
            self.consecutive_failures = 0
            self.last_tick_time = (
                obs.broker_event_time.isoformat() if obs.broker_event_time else obs.timestamp.isoformat()
            )
            self.last_timestamp_basis = obs.timestamp_basis
            recorded = self.ticks_recorded
        self._observe_aggregate(obs)
        if recorded % self.manifest_every_ticks == 0:
            try:
                self.write_manifest()
            except Exception as e:  # noqa: BLE001 — derived export is failure-accounted
                self._register_failure(
                    f"{type(e).__name__}: {e}", category="MANIFEST_EXPORT_ERROR"
                )

    # ------------------------------------------------- acquisition ledger

    def _dup_key(self, raw_key: tuple[Any, Any, float]) -> str:
        """Stable identity of a standing quote (never a price or a credential)."""
        return hashlib.sha256(json.dumps(list(raw_key), default=str).encode()).hexdigest()[:32]

    def _slot_for_attempt(self) -> tuple[int, str, int]:
        """Nominal poll slot for this attempt: (slot_index, scheduled_at, gap_slots).

        Slots are derived from the monotonic clock and the requested interval,
        so a stalled or restarted loop shows up as MISSED slots instead of a
        tidy, contiguous-looking series. Missing slots are never market data.
        """
        with self._lock:
            start_mono = self._start_monotonic
            start_utc = self._start_utc or datetime.now(UTC)
            interval = self.interval_s
            previous = self._last_slot_index
        index = int(max(0.0, time.monotonic() - start_mono) / interval)
        scheduled = (start_utc + timedelta(seconds=index * interval)).isoformat()
        gap = 0 if previous is None else max(0, index - previous - 1)
        with self._lock:
            self._last_slot_index = index
        return index, scheduled, gap

    def _clock_extra(self) -> dict[str, Any]:
        """Offset/basis in force for this attempt (cache-only, never measured here)."""
        try:
            info = self.provider.broker.offset_cache_info(self.broker_symbol)
        except Exception:  # noqa: BLE001 — a ledger row must never depend on this
            return {}
        if info.get("status") != "MEASURED":
            return {}
        return {
            "server_utc_offset_s": info.get("server_utc_offset_s"),
            "offset_basis": info.get("basis"),
        }

    def _journal(self, outcome: str, **fields: Any) -> None:
        """Append one attempt outcome to the durable ledger.

        A ledger write failure never kills the attempt accounting: the row is
        carried in a bounded backlog and flushed (flagged ``deferred``) once
        storage recovers. Beyond the cap the attempt is counted as dropped and,
        on recovery, recorded as ONE explicit UNRESOLVED marker row — never
        silently discarded, never counted as market activity.
        """
        with self._lock:
            self._attempt_seq += 1
            seq = self._attempt_seq
            self.attempt_outcomes[outcome] = self.attempt_outcomes.get(outcome, 0) + 1
        entry = {
            "seq": seq,
            "outcome": outcome,
            "interval_s": self.interval_s,
            "monotonic_s": round(time.monotonic(), 6),
            "deferred": False,
            **fields,
        }
        if self.session_id is None:
            return
        try:
            self._flush_journal(entry)
        except Exception:  # noqa: BLE001 — deferred, counted, never silent
            with self._lock:
                if len(self._journal_backlog) < MAX_JOURNAL_BACKLOG:
                    self._journal_backlog.append(entry)
                else:
                    self._journal_dropped += 1

    def _flush_journal(self, entry: dict[str, Any]) -> None:
        """Persist carried backlog rows (flagged ``deferred``) then this entry."""
        with self._lock:
            pending = list(self._journal_backlog)
            dropped = self._journal_dropped
        done: list[dict[str, Any]] = []
        for row in pending:
            try:
                self._write_attempt(row, deferred=True)
            except sqlite3.IntegrityError:
                done.append(row)  # already durable at this seq — stop carrying it
                continue
            except Exception:
                break  # storage still unavailable: keep the rest for the next flush
            done.append(row)
        with self._lock:
            for row in done:
                with contextlib.suppress(ValueError):
                    self._journal_backlog.remove(row)
        if dropped and not self._journal_backlog:
            # Storage recovered: make the un-journaled attempts explicit.
            with self._lock:
                self._journal_dropped = 0
                self._attempt_seq += 1
                marker_seq = self._attempt_seq
            self._write_attempt(
                {
                    "seq": marker_seq,
                    "outcome": "UNRESOLVED",
                    "attempted_at": datetime.now(UTC).isoformat(),
                    "interval_s": self.interval_s,
                    "monotonic_s": round(time.monotonic(), 6),
                    "deferred": False,
                    "reason": (
                        f"{dropped} acquisition attempts could not be journaled during a storage outage "
                        "and have no recoverable outcome"
                    ),
                },
                deferred=False,
            )
        self._write_attempt(entry, deferred=bool(entry.get("deferred", False)))

    def _write_attempt(self, entry: dict[str, Any], *, deferred: bool) -> None:
        self.observatory.record_attempt(
            self.session_id or "",
            int(entry["seq"]),
            outcome=str(entry["outcome"]),
            attempted_at=str(entry.get("attempted_at") or ""),
            scheduled_at=entry.get("scheduled_at"),
            slot_index=entry.get("slot_index"),
            interval_s=entry.get("interval_s", self.interval_s),
            monotonic_s=entry.get("monotonic_s"),
            record_id=entry.get("record_id"),
            dup_key=entry.get("dup_key"),
            reason=entry.get("reason"),
            persistence_ok=entry.get("persistence_ok"),
            deferred=deferred,
            gap_slots=int(entry.get("gap_slots") or 0),
            extra=entry.get("extra"),
        )

    def reconciliation(self, *, stale_after_s: float = 300.0) -> dict[str, Any]:
        """Durable attempt-vs-store reconciliation for THIS session.

        Reports deferred/dropped rows too, so an in-memory backlog can never be
        mistaken for a clean ledger.
        """
        if not self.session_id:
            return {"session_id": None, "note": "no session has been started"}
        rec = self.observatory.attempt_reconciliation(self.session_id, stale_after_s=stale_after_s)
        with self._lock:
            rec["runtime_journal_backlog"] = len(self._journal_backlog)
            rec["runtime_journal_dropped"] = self._journal_dropped
            rec["runtime_outcomes"] = dict(self.attempt_outcomes)
        rec["fully_reconciled"] = bool(
            rec["accounting_balanced"]
            and rec["ledger_store_agreement"]
            and rec["sequence_contiguous"]
            and not rec["runtime_journal_backlog"]
            and not rec["runtime_journal_dropped"]
        )
        return rec

    @staticmethod
    def _failure_category(message: str) -> str:
        """Classify diagnostics without changing the safety thresholds."""
        text = message.lower()
        if "stale" in text:
            return "STALE_DATA"
        if "future" in text:
            return "FUTURE_DATA"
        if "spread" in text or "bid/ask" in text:
            return "QUOTE_VALIDATION"
        if "storage" in text or "sqlite" in text or "integrityerror" in text or "database" in text:
            return "STORAGE_ERROR"
        if "manifest" in text or "no space" in text:
            return "MANIFEST_EXPORT_ERROR"
        return "RUNTIME_ERROR"

    def _register_failure(self, message: str, *, category: str | None = None) -> None:
        thread: threading.Thread | None = None
        with self._lock:
            self.consecutive_failures += 1
            failure_at = datetime.now(UTC).isoformat()
            self._last_failure_at = failure_at
            self.last_failure_category = category or self._failure_category(message)
            self.last_error = f"{failure_at} {message}"
            if self.consecutive_failures >= self.max_consecutive_failures:
                thread = self._finish("STOPPED_ON_ERRORS")
        self._join(thread)  # no-op when called from the poll thread itself

    def _join(self, thread: threading.Thread | None) -> None:
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=self.interval_s + 5.0)

    def _finish(self, new_state: str) -> threading.Thread | None:
        """Persist the terminal state and derive all terminal projections.

        Caller holds ``self._lock``.  The canonical SQLite end timestamp is
        obtained first and then copied to ``stopped_at`` and the manifest.  If
        SQLite is unavailable, the terminal transition is still fail-closed
        and loud, but ``_terminal_persist_pending`` remains set; a later
        idempotent ``stop()`` retries and republishes the manifest.
        """
        self._stop.set()
        if self.session_id:
            self._terminal_error = self.last_error if new_state != "STOPPED" else None
            self._terminal_failure = None
            if new_state != "STOPPED":
                self._terminal_failure = {
                    "category": self.last_failure_category or "RUNTIME_ERROR",
                    "timestamp": self._last_failure_at or datetime.now(UTC).isoformat(),
                    "consecutive_failures": self.consecutive_failures,
                }
            end = self._persist_session_end(new_state, self._terminal_error)
            if end is not None:
                self._authoritative_end = end
                self.stopped_at = end
            else:
                self._authoritative_end = None
                self.stopped_at = None
        # The DERIVED manifest export must never be able to block the lifecycle
        # transition. It is generated after the state/end snapshot is set, so
        # a successful terminal export agrees with canonical SQLite.
        self._terminal_manifest_pending = False
        try:
            self.write_manifest(state_override=new_state)
        except Exception as e:  # noqa: BLE001 — derived export, never lifecycle-fatal
            self._terminal_manifest_pending = True
            self._note_diagnostic(f"terminal manifest write failed: {type(e).__name__}: {e}")
        self.state = new_state
        thread = self._thread
        self._thread = None
        return thread

    def _note_diagnostic(self, message: str) -> None:
        """Append a runtime diagnostic. Diagnostics never become terminal errors."""
        stamped = f"{datetime.now(UTC).isoformat()} {message}"
        self.last_error = stamped if not self.last_error else f"{self.last_error} | {stamped}"

    def _persist_session_end(self, new_state: str, terminal_error: str | None) -> str | None:
        """Persist the terminal session row; bounded-retried, never raises.

        The returned value is the timestamp committed by SQLite.  It is the
        only valid source for ``stopped_at``.  The terminal failure object is
        written once with the canonical row and is reused on persistence retry.
        """
        status = "ENDED" if new_state == "STOPPED" else "ENDED_ON_ERRORS"
        session_id = self.session_id
        if session_id is None:  # pragma: no cover — _finish() only runs inside a started session
            self._terminal_persist_pending = False
            return None
        last: Exception | None = None
        for attempt in range(_TERMINAL_PERSIST_ATTEMPTS):
            try:
                kwargs: dict[str, Any] = {"status": status, "error": terminal_error}
                if self._terminal_failure is not None:
                    kwargs["terminal_failure"] = self._terminal_failure
                committed_end = self.observatory.end_session(session_id, **kwargs)
                if not committed_end:
                    # Backward-compatible adapter/test doubles may persist
                    # correctly but omit the new return value.  Accept only a
                    # timestamp read back from the canonical session row; do
                    # not turn ``None`` into a fabricated string.
                    persisted = self.observatory.session(session_id) or {}
                    read_back = persisted.get("end")
                    committed_end = str(read_back) if read_back else ""
                if not committed_end:
                    raise RuntimeError("canonical end_session returned no committed timestamp")
            except Exception as e:  # noqa: BLE001 — persistence must never escape the worker
                last = e
                if attempt + 1 < _TERMINAL_PERSIST_ATTEMPTS:
                    time.sleep(_TERMINAL_PERSIST_RETRY_S)
                continue
            self._terminal_persist_pending = False
            return str(committed_end)
        self._terminal_persist_pending = True
        self._note_diagnostic(f"terminal session persist failed: {type(last).__name__}: {last}")
        return None

    # ------------------------------------------------- reputation metadata

    @staticmethod
    def _unavailable(reason: str) -> dict[str, Any]:
        """Explicit UNAVAILABLE marker — a missing fact is never a fabricated value."""
        return {"status": "UNAVAILABLE", "value": None, "reason": reason}

    @staticmethod
    def _iso_utc(value: datetime) -> str:
        """Canonical UTC ISO form, matching the stored payload representation.

        Keeps the bounded aggregate byte-identical to the store-derived
        regeneration (both are ``...Z``), so the two manifest paths cannot
        disagree on representation alone.
        """
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _canonical_hash(obj: Any) -> str:
        body = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(body.encode("utf-8")).hexdigest()

    def _collector_config(self) -> dict[str, Any]:
        """Sampling policy + validation thresholds actually in force."""
        return {
            "collector_policy": {
                "interval_s": self.interval_s,
                "max_consecutive_failures": self.max_consecutive_failures,
                "manifest_every_ticks": self.manifest_every_ticks,
                "duplicate_policy": "identical raw broker stamps are skipped, never re-persisted",
                "sample_source": "MT5Adapter.ticks -> MarketDataProvider.get_tick (validated)",
            },
            "validation_thresholds": {
                "max_tick_age_s": getattr(self.provider, "max_tick_age_s", None),
                "max_spread_bps": getattr(self.provider, "max_spread_bps", None),
                "future_guard_s": -1.0,
            },
        }

    def _broker_identity(self) -> dict[str, Any]:
        """Privacy-preserving broker/terminal identity (never a credential)."""
        login = os.getenv("QTS_MT5_LOGIN") or ""
        server = os.getenv("QTS_MT5_SERVER") or ""
        identity: dict[str, Any] = {
            "broker": "MT5",
            "feed": "MT5Adapter.ticks -> MarketDataProvider.get_tick",
            "login_masked": (
                {"status": "AVAILABLE", "value": ("****" + login[-2:]) if len(login) > 2 else "****"}
                if login
                else self._unavailable("QTS_MT5_LOGIN is not set in this environment")
            ),
            "server": (
                {"status": "AVAILABLE", "value": server}
                if server
                else self._unavailable("QTS_MT5_SERVER is not set in this environment")
            ),
        }
        try:
            info = self.provider.broker.terminal_info()
            build = getattr(info, "build", None)
            identity["terminal_build"] = (
                {"status": "AVAILABLE", "value": int(build)}
                if build is not None
                else self._unavailable("terminal_info() exposes no build number")
            )
        except Exception as e:  # noqa: BLE001 — identity metadata never blocks a session
            identity["terminal_build"] = self._unavailable(f"terminal_info unavailable: {type(e).__name__}: {e}")
        return identity

    def _symbol_spec_snapshot(self) -> dict[str, Any]:
        """Versioned, hashed snapshot of the broker symbol specification."""
        try:
            spec = self.provider.broker.get_symbol_spec(self.broker_symbol)
        except Exception as e:  # noqa: BLE001
            return self._unavailable(f"symbol specification unavailable: {type(e).__name__}: {e}")
        fields = {
            "symbol": str(getattr(spec, "symbol", "")),
            "digits": getattr(spec, "digits", None),
            "point": str(getattr(spec, "point", "")),
            "tick_size": str(getattr(spec, "tick_size", "")),
            "contract_size": str(getattr(spec, "contract_size", "")),
            "volume_min": str(getattr(spec, "volume_min", "")),
            "volume_max": str(getattr(spec, "volume_max", "")),
            "volume_step": str(getattr(spec, "volume_step", "")),
            "trade_mode": getattr(spec, "trade_mode", None),
            "trade_allowed": getattr(spec, "trade_allowed", None),
            "filling_mode": getattr(spec, "filling_mode", None),
            "execution_mode": getattr(spec, "execution_mode", None),
            "stops_level": getattr(spec, "stops_level", None),
            "freeze_level": getattr(spec, "freeze_level", None),
        }
        return {"status": "AVAILABLE", "value": fields, "hash": self._canonical_hash(fields)}

    def _broker_offset_metadata(self) -> dict[str, Any]:
        """Broker UTC-offset measurement identity (cache-only, never invented)."""
        try:
            info = self.provider.broker.offset_cache_info(self.broker_symbol)
        except Exception as e:  # noqa: BLE001
            return self._unavailable(f"offset cache unavailable: {type(e).__name__}: {e}")
        if info.get("status") != "MEASURED":
            unavailable = self._unavailable(str(info.get("reason") or "no offset measured yet"))
            unavailable["measurement_time"] = self._unavailable("no offset measurement exists yet for this session")
            return unavailable
        return {
            "status": "MEASURED",
            "value": {
                "server_utc_offset_s": info.get("server_utc_offset_s"),
                "basis": info.get("basis"),
                "cache_stamped_at": info.get("cache_stamped_at"),
                "cache_age_s": info.get("cache_age_s"),
            },
            "note": info.get("note"),
            "measurement_time": self._unavailable(
                "the adapter exposes the offset and its basis, not the original measurement timestamp"
            ),
        }

    def _build_run_metadata(self, *, mode: str) -> dict[str, Any]:
        """Minimum durable run/clock/source identity for reproducible cohorts."""
        from qts.observability.lineage import code_version, git_commit

        config = self._collector_config()
        return {
            "version": RUN_METADATA_VERSION,
            "code": {
                "package_version": code_version(),
                "git_commit": git_commit() or "unknown",
            },
            "environment": {
                "mode": mode,
                "python": platform.python_version(),
                "platform": sys.platform,
            },
            "config": {**config, "hash": self._canonical_hash(config)},
            "symbols": {"canonical": self.instrument.symbol, "broker": self.broker_symbol},
            "broker_identity": self._broker_identity(),
            "symbol_spec": self._symbol_spec_snapshot(),
            "clock": {
                "broker_offset_measurement": self._broker_offset_metadata(),
                "host_clock": self._unavailable("no host clock-synchronization probe exists in this architecture"),
                "normalization_rule": (
                    "event_time = broker_stamp - measured_server_offset (single application, true UTC = system clock)"
                ),
            },
            "privacy": {
                "credentials_persisted": False,
                "absolute_paths_persisted": False,
                "login_masked": True,
                "purpose": "reproducibility identity only — never an access credential",
            },
        }

    # ------------------------------------------------- bounded aggregation

    @staticmethod
    def _empty_aggregate() -> dict[str, Any]:
        return {
            "count": 0,
            "bases": {},
            "offsets": set(),
            "spread_min": None,
            "spread_max": None,
            "spread_sum": 0.0,
            "spread_n": 0,
            "first_event": None,
            "last_event": None,
            "symbols": set(),
        }

    def _observe_aggregate(self, obs: ObservationTick) -> None:
        """Update the O(1) derived aggregate — the periodic manifest never scans."""
        with self._lock:
            agg = self._agg
            agg["count"] += 1
            basis = str(obs.timestamp_basis or "unknown")
            agg["bases"][basis] = agg["bases"].get(basis, 0) + 1
            if obs.server_utc_offset_s is not None:
                agg["offsets"].add(float(obs.server_utc_offset_s))
            spread = obs.spread_bps
            if isinstance(spread, (int, float)):
                value = float(spread)
                agg["spread_n"] += 1
                agg["spread_sum"] += value
                agg["spread_min"] = value if agg["spread_min"] is None else min(agg["spread_min"], value)
                agg["spread_max"] = value if agg["spread_max"] is None else max(agg["spread_max"], value)
            event = self._iso_utc(obs.broker_event_time or obs.timestamp)
            if agg["first_event"] is None:
                agg["first_event"] = event
            agg["last_event"] = event
            if obs.symbol:
                agg["symbols"].add(str(obs.symbol))

    # -------------------------------------------------------------- manifest

    def write_manifest(self, state_override: str | None = None, *, from_store: bool = False) -> dict[str, Any]:
        """Aggregate the DEMO-class collected records into the DERIVED manifest.

        The canonical source is the observatory SQLite store; this JSON is a
        regenerable export (finding #5) and never the primary evidence.
        ``state_override`` records the terminal state during a transition.

        Scaling contract: the DEFAULT path is O(1) — it reads the aggregate
        maintained as ticks are accepted, so periodic manifest publication
        never re-scans the session on the critical acquisition path.
        ``from_store=True`` performs the authoritative full regeneration from
        canonical storage and is the explicit audit path, never the periodic one.
        """
        agg = self._aggregate_from_store() if from_store else self._bounded_aggregate()
        session = self.observatory.session(self.session_id) if self.session_id else None
        with self._lock:
            status_snapshot = self.status()
        if state_override is not None:
            status_snapshot = {**status_snapshot, "state": state_override}
        manifest: dict[str, Any] = {
            "class": "DEMO",
            "data_class_note": (
                "live MT5 DEMO feed via OBSERVE-ONLY ObservationCollector behind a PASSED readiness gate; "
                "no synthetic, no simulation, no fixture data in this manifest; "
                "provenance class DEMO (real broker, demo account) — never presented as LIVE/REAL-money evidence"
            ),
            "product_mode": OBSERVATION_PRODUCT_MODE,
            "observation_mode": OBSERVATION_MODE,
            "mode": OBSERVATION_MODE,
            "environment": OBSERVATION_ENVIRONMENT,
            "orders_submitted": 0,
            "order_send_called": False,
            "canonical_store": str(self.observatory.db_path),
            "derived_export": True,
            "derived_from_aggregate": not from_store,
            "symbols": agg["symbols"],
            "session": session,
            "state": status_snapshot["state"],
            "started_at": status_snapshot["started_at"],
            "stopped_at": status_snapshot["stopped_at"],
            "readiness_at_start": status_snapshot["readiness_at_start"],
            "ticks_recorded": agg["ticks_recorded"],
            "signals_recorded": agg["signals_recorded"],
            "divergence": agg["divergence"],
            "duplicates_skipped": status_snapshot["duplicates_skipped"],
            "first_event_time": agg["first_event_time"],
            "last_event_time": agg["last_event_time"],
            "timestamp_bases": agg["timestamp_bases"],
            "server_utc_offsets_s": agg["server_utc_offsets_s"],
            "spread_bps": agg["spread_bps"],
            "last_error": status_snapshot["last_error"],
            "last_failure_category": status_snapshot.get("last_failure_category"),
            "terminal_failure": status_snapshot.get("terminal_failure"),
            "authoritative_end": status_snapshot.get("authoritative_end"),
            "terminal_persist_pending": status_snapshot.get("terminal_persist_pending"),
            "acquisition_ledger": status_snapshot.get("acquisition_ledger"),
            "pipeline": "MT5Adapter.ticks -> MarketDataProvider.get_tick (validated) -> ForwardObservatory",
            "timestamp_contract": "docs/mt5_demo_setup.md#canonical-timestamp-contract-ticks--observations",
            "generated_at": datetime.now(UTC).isoformat(),
        }
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8")
        return manifest

    def _bounded_aggregate(self) -> dict[str, Any]:
        """O(1) aggregate over accepted rows (no store scan)."""
        with self._lock:
            agg = self._agg
            spread_n = int(agg["spread_n"])
            spread = (
                {
                    "min": float(agg["spread_min"]),
                    "avg": float(agg["spread_sum"]) / spread_n,
                    "max": float(agg["spread_max"]),
                }
                if spread_n
                else None
            )
            return {
                "ticks_recorded": int(agg["count"]),
                "timestamp_bases": dict(agg["bases"]),
                "server_utc_offsets_s": sorted(agg["offsets"]),
                "spread_bps": spread,
                "first_event_time": agg["first_event"],
                "last_event_time": agg["last_event"],
                "symbols": sorted(s for s in agg["symbols"] if s),
                # OBSERVE_ONLY records no signals: the zero-signal divergence
                # shape is exact, so no signal-table scan is needed here.
                "signals_recorded": 0,
                "divergence": self.observatory.empty_divergence_shape(self.session_id),
            }

    def _aggregate_from_store(self) -> dict[str, Any]:
        """Authoritative full regeneration from canonical storage (audit path)."""
        with db_connect(self.observatory.db_path) as con:
            if self.session_id:
                rows = con.execute(
                    "SELECT payload FROM observation_ticks WHERE session_id=?"
                    " ORDER BY COALESCE(event_time, created_at), rowid",
                    (self.session_id,),
                ).fetchall()
                signal_count = con.execute(
                    "SELECT COUNT(*) FROM observation_signals WHERE session_id=?", (self.session_id,)
                ).fetchone()[0]
            else:
                rows = con.execute(
                    "SELECT payload FROM observation_ticks ORDER BY COALESCE(event_time, created_at), rowid"
                ).fetchall()
                signal_count = con.execute("SELECT COUNT(*) FROM observation_signals").fetchone()[0]
        counted = 0
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
            counted += 1
            symbols.add(str(p.get("symbol", "")))
            basis = str(p.get("timestamp_basis", "unknown"))
            bases[basis] = bases.get(basis, 0) + 1
            off = p.get("server_utc_offset_s")
            if off is not None:
                offsets.add(float(off))
            spread_value = p.get("spread_bps")
            if isinstance(spread_value, (int, float)):
                spreads.append(float(spread_value))
            event = p.get("broker_event_time")
            if event:
                first_event = first_event or str(event)
                last_event = str(event)
        return {
            "ticks_recorded": counted,
            "timestamp_bases": bases,
            "server_utc_offsets_s": sorted(offsets),
            "spread_bps": (
                {"min": min(spreads), "avg": sum(spreads) / len(spreads), "max": max(spreads)} if spreads else None
            ),
            "first_event_time": first_event,
            "last_event_time": last_event,
            "symbols": sorted(s for s in symbols if s),
            "signals_recorded": signal_count,
            "divergence": self.observatory.divergence_summary(self.session_id),
        }
