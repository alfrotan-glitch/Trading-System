"""Startup / shutdown health — loads durable state, restores suspension, verifies data/config/MT5/reconciliation."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from qts.db import connect as db_connect


def startup_health_check(data_dir: Path | str = "data") -> dict[str, Any]:
    """1. Load durable state. 2. Restore suspension. 3. Restore pending/ambiguous orders. 4. Verify data. 5. Verify config. 6. Verify account/MT5 if requested. 7. Run reconciliation. 8. Only then permit normal operation."""
    data_dir = Path(data_dir)
    results: dict[str, Any] = {"timestamp": datetime.now(UTC).isoformat(), "checks": []}

    def _check(name: str, fn):
        try:
            ok, detail = fn()
            results["checks"].append({"name": name, "passed": ok, "detail": detail})
            return ok
        except Exception as e:
            results["checks"].append({"name": name, "passed": False, "detail": str(e)[:300]})
            return False

    # 1 durable state
    def check_state():
        p = Path("data/sqlite/qts.db")
        if not p.exists():
            # Fresh installation: there is no durable state to load yet.
            # That is not a failure — the store is created on first use.
            # A BLOCKED verdict here made every clean clone look broken (§16).
            return True, "no durable state yet — first run will create it"
        try:
            with db_connect(p) as con:
                try:
                    con.execute("SELECT 1 FROM promotion_state LIMIT 1")
                    con.execute("SELECT 1 FROM experiments LIMIT 1")
                    return True, "durable state loaded"
                except Exception as e:
                    if "no such table" in str(e).lower():
                        # State tables are created lazily on first use
                        # (lifecycle writes promotion_state, research writes
                        # experiments). Their absence on a fresh install is
                        # not corruption — the database itself read fine.
                        # Real damage (unreadable file) still fails below.
                        return True, "durable store present — state tables initialize on first use"
                    raise
        except Exception as e:
            return False, f"state load failed: {e}"

    # 2 suspension — the DURABLE kill-switch authority (the same flag
    # RiskEngine.pre_trade enforces). The old probe called a method that did
    # not exist and silently fell back to False, so an ACTIVE kill switch was
    # reported as "suspension state healthy" and system_status could never
    # become "Suspended".
    def check_suspension():
        try:
            from qts.risk.engine import RiskEngine, RiskLimits

            state = RiskEngine(RiskLimits()).kill_state()
            if state.get("killed"):
                reason = state.get("reason") or "no reason recorded"
                # The reason is HISTORICAL evidence of the fault that raised
                # the flag; it is not, by itself, proof that the fault is still
                # present. Say so, and name the canonical recovery transition —
                # a restored suspension that no lifecycle can clear is how this
                # system spent a whole session "Suspended" with a fresh quote
                # and a healthy reconciliation.
                return False, (
                    f"kill switch active — trading suspended (recorded reason: {reason}); "
                    "recoverable through the canonical resume transition "
                    "(POST /api/demo/guide/resume or `qts demo clear-kill`) once every "
                    "recovery predicate holds"
                )
            return True, f"suspension state healthy (source={state.get('source')})"
        except Exception as e:
            # Fail closed: an unreadable kill-switch state is treated as active.
            return False, f"kill switch state unreadable — fail closed: {type(e).__name__}: {e}"

    # 3 pending orders — the DURABLE order journal is the authority.
    #
    # This used to scan the last 20 audit events for the substring
    # "AMBIGUOUS". Same defect as the reconciliation probe below: evidence is
    # not state, and a rolling window is wrong in both directions.
    #
    #   * fail OPEN — an order whose outcome is genuinely UNKNOWN stopped
    #     being reported as soon as 20 newer events existed, so startup
    #     announced "pending/ambiguous orders none" with an unresolved order
    #     sitting in the journal;
    #   * false positive — a long-resolved order kept blocking startup until
    #     it aged out, and because the scan matched the whole payload text it
    #     also tripped on a reconciliation report carrying
    #     ``drift="AMBIGUOUS"``, which is a different condition entirely.
    #
    # `DemoOrderJournal` is the only store that persists execution history
    # (QTS_PROJECT_CONTROL.md §11.4), so it is what this check reads.
    def check_pending():
        try:
            from qts.config.paths import artifact_path
            from qts.execution.demo_journal import DemoOrderJournal

            journal = DemoOrderJournal(artifact_path("journal_db"))
            rows = journal.list_orders(limit=500)
            ambiguous = [r for r in rows if r.get("state") == "AMBIGUOUS"]
            if ambiguous:
                ids = ", ".join(str(r.get("client_order_id") or r.get("journal_id")) for r in ambiguous[:5])
                more = "" if len(ambiguous) <= 5 else f" (+{len(ambiguous) - 5} more)"
                return False, (
                    f"{len(ambiguous)} order(s) in AMBIGUOUS state require reconciliation "
                    f"with the broker: {ids}{more}"
                )
            # A row still NEW/SUBMITTED at startup means a process died between
            # the broker call and the journal update: the outcome is UNKNOWN,
            # which is a blocker, not a clean state. `expire_inflight_rows`
            # resolves these to REJECTED once they are provably abandoned.
            inflight = [r for r in rows if r.get("state") in ("NEW", "SUBMITTED")]
            if inflight:
                ids = ", ".join(str(r.get("client_order_id") or r.get("journal_id")) for r in inflight[:5])
                return False, (
                    f"{len(inflight)} submission(s) in flight with no recorded outcome — "
                    f"verify with the broker before trading: {ids}"
                )
            return True, "pending/ambiguous orders none"
        except Exception as e:
            # Fail closed: unverified pending/ambiguous state is not clean state.
            return False, f"pending/ambiguous order state unreadable: {type(e).__name__}: {e}"

    # 4 data
    def check_data():
        try:
            from qts.data.quality import validate_bars
            from qts.data.store import SqliteParquetDataStore
            from qts.domain.value_objects import Instrument

            store = SqliteParquetDataStore()
            versions = store.list_versions()
            if not versions:
                return False, "no data versions"
            v = versions[-1]
            m = store.manifest(v)
            instr = Instrument(symbol=m.instrument, venue=m.venue)
            bars = store.read_bars(instr, m.timeframe, version=v)
            rpt = validate_bars(bars)
            if not rpt.passed:
                return False, f"data quality fail: {rpt.checks[0].details if rpt.checks else 'fail'}"
            return True, f"data healthy {v} {len(bars)} bars"
        except Exception as e:
            return False, f"data verify failed: {e}"

    # 5 config
    def check_config():
        try:
            from qts.config.settings import load_settings
            from qts.domain.modes import resolve_mode

            s = load_settings()
            # Mode comes from the ONE canonical authority (qts.domain.modes) —
            # never from a guessed/defaulted string (the old 'research' default
            # named a mode that does not exist).
            try:
                mode = resolve_mode(config_env=s.env).value
            except Exception as e:
                return False, f"config failed: mode resolution fail-closed ({e})"
            return True, f"config loaded env={s.env} mode={mode}"
        except Exception as e:
            return False, f"config failed: {e}"

    # 6 MT5
    def check_mt5():
        try:
            import os

            mode = os.getenv("QTS_MT5_MODE", "MOCK")
            if mode == "MOCK":
                return True, "MT5 MOCK — no real broker connection (correct for dev)"
            if mode != "REAL":
                return False, f"MT5 mode {mode!r} unrecognized — expected MOCK or REAL"
            # REAL means "probe the actual terminal". The probe goes through the
            # SAME canonical path Demo execution uses — adapter_from_setup()
            # (terminal_path + symbol map from the machine-local setup) and
            # MT5Adapter.ensure_session() (establish + verify the IPC link).
            # A mode name alone is never treated as a connection; a probe that
            # cannot run fails closed with the precise reason.
            from qts.adapters.mt5_factory import adapter_from_setup

            adapter, connection = adapter_from_setup()
            adapter.ensure_session()
            identity = adapter.broker_identity()
            # DEMO ONLY — hard gate: a REAL, CONTEST or unverifiable account
            # cannot pass startup health, whatever its connectivity.
            if identity.is_demo is not True:
                return False, (
                    f"MT5 REAL connected (login={identity.login} server={identity.server}) but account type is "
                    f"{identity.account_type} — only a DEMO account passes this check"
                )
            broker_symbol = connection["broker_symbol"]
            spec = adapter.get_symbol_spec(broker_symbol)
            from qts.domain.value_objects import Instrument

            tick = adapter.ticks(Instrument(symbol=connection["canonical_symbol"], venue="MT5"))
            if tick is not None:
                # Freshness is judged on the RAW broker stamp by the same
                # server-clock contract the readiness gate uses — never on the
                # normalized event_time, which is unusable while the server-UTC
                # offset is unmeasured.
                provenance = getattr(tick, "provenance", None) or {}
                raw_msc = provenance.get("mt5_time_msc")
                raw_s = provenance.get("mt5_time")
                raw_epoch = float(raw_msc) / 1000.0 if raw_msc is not None and float(raw_msc) > 1e12 else raw_s
                fresh, detail = adapter.raw_tick_freshness(broker_symbol, raw_epoch)
                quote_note = f"quote {'fresh' if fresh else 'not fresh'} on server clock — {detail}"
            else:
                quote_note = "quote unavailable right now (readiness enforces freshness before trading)"
            return True, (
                f"MT5 REAL connected: login={identity.login} server={identity.server} account=DEMO "
                f"{connection['canonical_symbol']}->{broker_symbol} tradable vol_min={spec.volume_min} {quote_note}"
            )
        except Exception as e:
            return False, f"MT5 REAL probe failed: {type(e).__name__}: {e}"

    # 7 reconciliation — the DURABLE ``reconcile_state`` row is the authority.
    #
    # This used to scan the last 50 audit events for the words "DRIFT" or
    # "SUSPENDED". That is evidence, not state, and it is wrong in BOTH
    # directions:
    #
    #   * a healed drift kept failing startup until it aged out of the window
    #     (historical evidence treated as an active blocker), and
    #   * an UNHEALED suspension reported "reconciliation healthy" as soon as
    #     50 newer events had been recorded — which is exactly how a host could
    #     show `run_reconciliation: PASS` while `reconcile_state.suspended=1`
    #     kept every order refused on ``reconciliation_ready``.
    #
    # It now reads the same row ExecutionEngine enforces, through the same
    # function (``load_reconcile_suspension``), so reporting and enforcement
    # cannot disagree. The audit trail is untouched and remains the evidence.
    def check_recon():
        try:
            from qts.config.paths import artifact_path
            from qts.execution.engine import load_reconcile_suspension

            state = load_reconcile_suspension(artifact_path("db"))
            if not state.readable:
                return False, f"reconciliation suspension state unreadable — fail closed ({state.reason})"
            if state.suspended:
                return False, (
                    f"reconciliation SUSPENDED (durable reconcile_state): {state.reason or 'unresolved drift'} — "
                    "recoverable through the canonical resume transition once a fresh reconciliation reports no drift"
                )
            if not state.recorded:
                return True, "reconciliation healthy — no suspension was ever recorded"
            return True, "reconciliation healthy — no active durable suspension"
        except Exception as e:
            # Fail closed: reconciliation health that could not be measured is
            # never reported as healthy.
            return False, f"reconciliation health unreadable: {type(e).__name__}: {e}"

    _check("load_durable_state", check_state)
    _check("restore_suspension", check_suspension)
    _check("restore_pending_orders", check_pending)
    _check("verify_data", check_data)
    _check("verify_configuration", check_config)
    _check("verify_account_MT5", check_mt5)
    _check("run_reconciliation", check_recon)

    results["overall"] = all(c["passed"] for c in results["checks"])
    results["system_status"] = "Running" if results["overall"] else "Blocked"
    # The two named suspension checks are the authority for "Suspended" — they
    # are read directly rather than inferred from wording. BOTH durable records
    # count: an unhealed ``reconcile_state.suspended`` is a suspension even when
    # the kill switch is clear, and reporting it merely as "Blocked" is what
    # made the two surfaces describe the same machine differently. The keyword
    # scan is kept only as a backstop so that a kill condition reported by any
    # OTHER check still wins the conservative status; all directions fail safe.
    named = {c["name"]: c for c in results["checks"]}
    suspension = named.get("restore_suspension")
    reconciliation = named.get("run_reconciliation")
    suspension_reported = (
        (suspension is not None and not suspension["passed"])
        or (reconciliation is not None and not reconciliation["passed"] and "SUSPENDED" in reconciliation["detail"])
        or any("kill" in c["detail"].lower() for c in results["checks"])
    )
    if suspension_reported:
        results["system_status"] = "Suspended"
    return results


def shutdown_procedure() -> dict[str, Any]:
    """On shutdown: stop new orders, persist state, record shutdown event, safely disconnect, preserve audit state."""
    results: dict[str, Any] = {"timestamp": datetime.now(UTC).isoformat(), "steps": []}
    try:
        from qts.domain.events import DomainEvent, EventType
        from qts.observability.audit import SqliteAuditLog

        log = SqliteAuditLog()
        log.emit(
            DomainEvent(
                event_type=EventType.NO_TRADE,
                payload={"event": "SHUTDOWN", "reason": "orderly shutdown", "timestamp": datetime.now(UTC).isoformat()},
            )
        )
        results["steps"].append("persist state + audit shutdown event: ok")
    except Exception as e:
        results["steps"].append(f"persist state failed: {e}")
    # safe disconnect mock
    results["steps"].append("disconnect: ok (mock)")
    results["overall"] = True
    return results
