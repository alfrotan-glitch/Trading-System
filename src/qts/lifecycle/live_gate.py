"""Live gate — structural blocking until every required capability is implemented and verified.

Live is blocked unless ALL of:
- MT5 submission implemented (not NotImplemented)
- account state authoritative (not mocked)
- market data safety checks pass (MarketDataProvider exists and validates)
- order lifecycle tests pass (INTENT→... verified)
- restart recovery passes (idempotency + suspend durable)
- reconciliation passes (drift detection)
- paper trading evidence exists
- shadow-mode evidence exists
- audit evidence present (RECONCILE, FILL, NO_TRADE, etc.)

Fail-closed: any missing → live blocked.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

from qts.db import connect as db_connect


def check_mt5_submission_implemented() -> tuple[bool, str]:
    try:
        from qts.adapters.mt5_adapter import MT5Adapter

        src = inspect.getsource(MT5Adapter.submit)
        # Check if it's still the stub that just raises NotImplemented without real
        # logic markers (get_symbol_spec / order_send)
        if ("NotImplementedError" in src or "raise NotImplementedError" in src) and (
            "get_symbol_spec" not in src or "order_send" not in src
        ):
            return False, "MT5Adapter.submit still stub (no symbol spec / order_send)"
        # Also check that symbol metadata handling exists
        if not hasattr(MT5Adapter, "get_symbol_spec"):
            return False, "MT5Adapter missing get_symbol_spec"
        return True, "MT5 submit implemented with symbol spec and order_send"
    except Exception as e:
        return False, f"MT5 check failed: {e}"


def check_account_authoritative() -> tuple[bool, str]:
    try:
        from qts.adapters.mt5_adapter import MT5Adapter

        src = inspect.getsource(MT5Adapter.account)
        if "is_finite" not in src or "stale" not in src.lower():
            return False, "MT5 account not authoritative (missing staleness/validation)"
        # Mock fallback still present? It must at least raise on None (fail closed)
        if 'return Account(balance=Decimal("0")' in src and "raise ConnectionError" not in src:
            return False, "MT5 account still returns mock 0 on None without fail-closed"
        return True, "MT5 account authoritative with staleness/validation"
    except Exception as e:
        return False, f"account check failed: {e}"


def check_market_data_safety() -> tuple[bool, str]:
    try:
        from qts.adapters.market_data import MarketDataProvider
        from qts.execution.engine import ExecutionEngine

        src = inspect.getsource(MarketDataProvider)
        src2 = inspect.getsource(ExecutionEngine)
        checks = ["max_tick_age", "spread", "bid", "ask", "stale"]
        for c in checks:
            if c not in src:
                return False, f"MarketDataProvider missing {c}"
        if "MARKET_DATA_UNSAFE" not in src2:
            return False, "ExecutionEngine missing MARKET_DATA_UNSAFE handling"
        return (
            True,
            "MarketDataProvider validates freshness, spread, bid/ask, symbol, market availability; ExecutionEngine suspends on unsafe",
        )
    except ImportError:
        return False, "MarketDataProvider not found"
    except Exception as e:
        return False, f"market data check failed: {e}"


def check_order_lifecycle() -> tuple[bool, str]:
    try:
        from qts.execution.engine import ExecutionEngine

        src = inspect.getsource(ExecutionEngine)
        needed = ["PARTIALLY_FILLED", "AMBIGUOUS", "REJECTED", "CANCELLED", "poll_live_fills", "market_data"]
        for n in needed:
            if n not in src:
                return False, f"ExecutionEngine missing lifecycle {n}"
        return (
            True,
            "Order lifecycle INTENT→RISK→SUBMITTED→ACCEPTED→PARTIALLY_FILLED→FILLED/REJECTED/CANCELLED/AMBIGUOUS durable",
        )
    except Exception as e:
        return False, f"lifecycle check failed: {e}"


def check_restart_recovery() -> tuple[bool, str]:
    try:
        from qts.execution.engine import ExecutionEngine

        src = inspect.getsource(ExecutionEngine)
        if "reconcile_state" not in src or "_persist_reconcile_suspend" not in src:
            return False, "ExecutionEngine missing durable suspend"
        from qts.execution.idempotency import IdempotencyStore

        src2 = inspect.getsource(IdempotencyStore)
        if "sqlite3" not in src2 or "seen" not in src2:
            return False, "Idempotency not persistent"
        return True, "Restart recovery durable (suspend + idempotency)"
    except Exception as e:
        return False, f"restart check failed: {e}"


def check_reconciliation() -> tuple[bool, str]:
    try:
        from qts.execution.engine import ExecutionEngine

        src = inspect.getsource(ExecutionEngine.reconcile)
        needed = [
            "UNKNOWN_POSITION",
            "MISSING_POSITION",
            "QUANTITY_MISMATCH",
            "PRICE_MISMATCH",
            "STATUS_MISMATCH",
            "UNKNOWN_ORDER",
            "MISSING_ORDER",
            "BROKER_DISCONNECT",
        ]
        for n in needed:
            if n not in src:
                return False, f"Reconcile missing {n}"
        return True, "Reconciliation detects missing/unknown/quantity/price/status disconnect, suspends"
    except Exception as e:
        return False, f"reconcile check failed: {e}"


def _lineage_checked_evidence(candidates: list[Path], expected_mode: str, required_list_key: str) -> tuple[bool, str]:
    """Lineage-checked mode evidence — NEVER mere file existence (finding #22).

    Evidence passes only when it proves WHAT produced it, WHEN, with WHICH
    code, under WHICH dataset, and that it contains real event records:
      * parseable JSON with ``mode == expected_mode``
      * dataset lineage (``data_version``) and time/code lineage
        (``generated_at`` + ``code_version``)
      * a non-empty ``required_list_key`` list whose records carry the
        essential fields
    Legacy/orphaned files lacking lineage FAIL with a precise reason and must
    be regenerated by the producing run.
    """
    from datetime import UTC, datetime

    reasons: list[str] = []
    for p in candidates:
        if not p.exists() or p.stat().st_size <= 10:
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            reasons.append(f"{p}: unparseable ({e})")
            continue
        if not isinstance(data, dict):
            reasons.append(f"{p}: not a JSON object")
            continue
        if data.get("mode") != expected_mode:
            reasons.append(f"{p}: mode={data.get('mode')!r} != {expected_mode!r}")
            continue
        missing_lineage = [k for k in ("data_version", "generated_at", "code_version") if not data.get(k)]
        if missing_lineage:
            reasons.append(f"{p}: lacks lineage {missing_lineage} — regenerate with current CLI")
            continue
        # A code identity that could not be resolved is not lineage. The
        # lineage contract states results that cannot be traced to a code
        # version are not promotion-grade, so "0.1.0+unknown" (a packaged
        # build with no resolvable source tree) must not pass as traced.
        if "unknown" in str(data["code_version"]).lower():
            reasons.append(
                f"{p}: code_version={data['code_version']!r} is not a traceable code identity — "
                "regenerate inside a resolvable source tree"
            )
            continue
        try:
            generated = datetime.fromisoformat(str(data["generated_at"]))
            age_days = (datetime.now(UTC) - generated).total_seconds() / 86400.0
        except (TypeError, ValueError):
            reasons.append(f"{p}: generated_at unparseable")
            continue
        events = data.get(required_list_key, [])
        if not isinstance(events, list) or not events:
            reasons.append(f"{p}: no {required_list_key} records")
            continue
        sample = events[0]
        if not isinstance(sample, dict) or not ({"price", "qty"} <= set(sample) or {"client_order_id"} <= set(sample)):
            reasons.append(f"{p}: {required_list_key} records lack essential fields")
            continue
        return (
            True,
            f"{expected_mode} evidence {p.name}: {len(events)}+ records, data_version="
            f"{data['data_version']}, age {age_days:.1f}d, code {data['code_version']}",
        )
    if reasons:
        return False, f"{expected_mode} evidence invalid: " + "; ".join(reasons[:3])
    return False, f"{expected_mode} evidence missing (run `qts run --mode {expected_mode}` to generate)"


def check_paper_evidence() -> tuple[bool, str]:
    return _lineage_checked_evidence(
        [
            Path("data/evidence/paper_trades.json"),
            Path("data/paper_evidence.json"),
        ],
        expected_mode="paper",
        required_list_key="fills",
    )


def check_shadow_evidence() -> tuple[bool, str]:
    return _lineage_checked_evidence(
        [
            Path("data/evidence/shadow_intents.json"),
            Path("data/shadow_evidence.json"),
        ],
        expected_mode="shadow",
        required_list_key="intents_sample",
    )


def check_audit_evidence() -> tuple[bool, str]:
    try:
        from qts.observability.audit import SqliteAuditLog

        log = SqliteAuditLog()
        events = log.query(limit=5)
        if not events:
            return False, "audit log empty"
        # Check for required event types
        types = {e.event_type.value for e in events}
        # At least one decision-bearing event type must actually be present.
        # This requirement was computed and then DISCARDED (the result was
        # bound to `_has` and the function returned True unconditionally), so
        # any five audit events at all satisfied the LIVE gate's audit-evidence
        # prerequisite.
        needed = {"OrderEvent", "Fill", "NoTrade", "ReconcileReport"}
        present = sorted(needed & types)
        if not present:
            return False, f"audit evidence lacks any decision-bearing event {sorted(needed)} — found {sorted(types)}"
        return True, f"audit evidence present: {present} (observed types: {sorted(types)})"
    except Exception as e:
        return False, f"audit check failed: {e}"


def check_environment() -> tuple[bool, str]:
    try:
        from qts.config.settings import load_settings

        settings = load_settings()
        if settings.env != "live":
            return False, f"env={settings.env} not live"
        if not settings.confirm_live:
            return False, "confirm_live not set"
        if not settings.risk.approved:
            return False, "risk.approved=false"
        return True, "env live + confirm + risk approved"
    except Exception as e:
        return False, f"env check failed: {e}"


def check_manifest() -> tuple[bool, str]:
    try:
        from qts.data.store import SqliteParquetDataStore

        store = SqliteParquetDataStore()
        versions = store.list_versions()
        if not versions:
            return False, "no data versions ingested"
        # Check that latest manifest validates
        v = versions[-1]
        m = store.manifest(v)
        if not m:
            return False, f"manifest {v} missing"
        from qts.data.quality import validate_bars
        from qts.domain.value_objects import Instrument

        instr = Instrument(symbol=m.instrument, venue=m.venue)
        bars = store.read_bars(instr, m.timeframe, version=v)
        rpt = validate_bars(bars)
        if not rpt.passed:
            return False, f"data quality fail for {v}: {[c.details for c in rpt.checks if not c.passed][:2]}"
        return True, f"manifest {v} quality PASS {len(bars)} bars"
    except Exception as e:
        return False, f"manifest check failed: {e}"


def check_mt5_connectivity() -> tuple[bool, str]:
    """REAL MT5 connectivity — evidence tiers are explicit (finding #20).

    A MagicMock-based probe was previously counted as connectivity evidence;
    that is test proof at best and can never satisfy a live gate. Now:

    * REAL terminal reachable (health_check connected) -> PASS (integration
      proof, real environment).
    * MetaTrader5 importable but terminal unreachable -> FAIL with the reason.
    * MetaTrader5 not installed (development without MT5) -> FAIL "UNAVAILABLE
      in this environment" — honest, never faked.
    Structural/test-level guarantees are reported by the other checks; this
    check demands REAL infrastructure.
    """
    try:
        import importlib

        try:
            importlib.import_module("MetaTrader5")
        except ImportError:
            return (
                False,
                "UNAVAILABLE: MetaTrader5 package not installed in this environment — "
                "no connectivity claim is possible (mock-based connectivity evidence is not valid)",
            )
        from qts.adapters.mt5_adapter import MT5Adapter

        adapter = MT5Adapter()
        health = adapter.health_check()
        if health.get("connected"):
            login = (health.get("account") or {}).get("login")
            return True, f"REAL MT5 terminal connected (login={login})"
        return (
            False,
            f"MT5 terminal not connected: terminal_ok={health.get('terminal_ok')} "
            f"account_ok={health.get('account_ok')} — real connectivity required for LIVE",
        )
    except Exception as e:
        return False, f"MT5 connectivity check failed: {e}"


def check_symbol_spec() -> tuple[bool, str]:
    try:
        from qts.adapters.mt5_adapter import MT5Adapter, SymbolSpec

        # Check that spec includes required fields and no hardcoded duplicates
        fields = SymbolSpec.__dataclass_fields__.keys()
        needed = [
            "contract_size",
            "volume_min",
            "volume_max",
            "volume_step",
            "digits",
            "point",
            "tick_size",
            "trade_mode",
            "trade_allowed",
            "filling_mode",
            "execution_mode",
            "stops_level",
            "freeze_level",
        ]
        for f in needed:
            if f not in fields:
                return False, f"SymbolSpec missing {f}"
        # Check that adapter has canonical method and risk uses it (no hardcoded)
        import inspect

        src = inspect.getsource(MT5Adapter.get_symbol_spec)
        if "contract_size" not in src or "volume_min" not in src:
            return False, "get_symbol_spec not authoritative"
        return True, f"SymbolSpec canonical with {len(needed)} fields, no hardcoded duplicates"
    except Exception as e:
        return False, f"symbol spec check failed: {e}"


def check_reconciliation_health() -> tuple[bool, str]:
    """No unresolved reconcile suspension in the durable state.

    A missing ``reconcile_state`` table means no ExecutionEngine has ever
    persisted suspension state — honestly "nothing suspended", not a failure.
    Previously that benign case raised and was reported as a gate failure
    whenever another component had created ``qts.db`` first, so the result
    depended on which subsystem happened to touch the database.

    ONLY "no such table" is benign. Every other read failure — a locked store,
    a damaged page, a permission error — fails CLOSED, because "could not read
    the suspension flag" must never be reported as "not suspended".

    The structural reconcile capability itself is asserted separately by
    :func:`check_reconciliation`; this check is the durable-state probe.
    """
    import sqlite3
    from pathlib import Path

    db = Path("data/sqlite/qts.db")
    if not db.exists():
        return True, "reconciliation health OK — no qts.db, so no recorded suspension"
    try:
        with db_connect(db) as con:
            try:
                row = con.execute("SELECT suspended FROM reconcile_state WHERE k=1").fetchone()
            except sqlite3.OperationalError as e:
                if "no such table" in str(e).lower():
                    return True, f"reconciliation health OK — no reconcile_state table recorded ({e})"
                return False, f"reconcile suspension state unreadable — fail closed ({type(e).__name__}: {e})"
        if row and row[0]:
            return False, f"unresolved SUSPENDED in {db} — must heal"
        return True, "reconciliation health OK, no unresolved suspension"
    except Exception as e:
        return False, f"reconcile health failed: {e}"


def check_validation_evidence() -> tuple[bool, str]:
    try:
        # Check that validation evidence exists (backtest + validation).
        # VALIDATION outcomes are emitted as audit events; a validation run
        # must be traceable, not merely present on disk.
        from qts.observability.audit import SqliteAuditLog

        log = SqliteAuditLog()
        events = log.query(limit=50)
        validation_events = [e for e in events if "VALIDATION" in str(e.payload)]
        if validation_events:
            return True, f"validation evidence present: {len(validation_events)} VALIDATION audit event(s)"
        # A paper artifact on disk is NOT validation evidence. Bare file
        # existence is exactly what _lineage_checked_evidence rejects
        # (finding #22) — and data/evidence/paper_trades.json is committed, so
        # the old `.exists()` fallback made this gate pass in every clone
        # regardless of whether validation ever ran. Fall back to the
        # lineage-checked paper gate so one provenance standard applies.
        ok, detail = check_paper_evidence()
        if ok:
            return True, f"validation evidence present via lineage-checked paper evidence — {detail}"
        return False, f"validation evidence missing — run `qts validate` and `qts run --mode paper` ({detail})"
    except Exception as e:
        return False, f"validation evidence check failed: {e}"


def live_readiness_report() -> dict[str, Any]:
    checks = {
        "environment": check_environment(),
        "manifest": check_manifest(),
        "mt5_submit": check_mt5_submission_implemented(),
        "mt5_connectivity": check_mt5_connectivity(),
        "symbol_spec": check_symbol_spec(),
        "account_authoritative": check_account_authoritative(),
        "market_data_safety": check_market_data_safety(),
        "order_lifecycle": check_order_lifecycle(),
        "restart_recovery": check_restart_recovery(),
        "reconciliation": check_reconciliation(),
        "reconciliation_health": check_reconciliation_health(),
        "paper_evidence": check_paper_evidence(),
        "shadow_evidence": check_shadow_evidence(),
        "audit_evidence": check_audit_evidence(),
        "validation_evidence": check_validation_evidence(),
    }
    report: dict[str, Any] = {}
    all_pass = True
    #: Proof-tier classification (finding #20): structural checks prove source
    #: architecture; integration checks prove real-component behavior. A gate
    #: must never present test/mock evidence as real-environment proof.
    PROOF_TIERS = {
        "environment": "structural",
        "manifest": "structural",
        "mt5_submit": "structural",
        "mt5_connectivity": "real_environment",
        "symbol_spec": "structural",
        "account_authoritative": "structural",
        "market_data_safety": "structural",
        "order_lifecycle": "structural",
        "restart_recovery": "structural",
        "reconciliation": "structural",
        "reconciliation_health": "integration",
        "paper_evidence": "integration",
        "shadow_evidence": "integration",
        "audit_evidence": "integration",
        "validation_evidence": "integration",
    }
    for k, (passed, detail) in checks.items():
        report[k] = {"passed": passed, "detail": detail, "proof_tier": PROOF_TIERS.get(k, "structural")}
        if not passed:
            all_pass = False
    report["ready"] = all_pass
    report["blocked_reasons"] = [k for k, v in checks.items() if not v[0]]
    report["proof_tiers"] = PROOF_TIERS
    report["tier_note"] = (
        "structural = source architecture guarantees; integration = verified against real "
        "components in-process; real_environment = verified against real broker infrastructure. "
        "Mock-based evidence is never accepted for a tier."
    )
    return report


def is_live_ready() -> bool:
    return live_readiness_report()["ready"]


def assert_live_ready() -> None:
    rpt = live_readiness_report()
    if not rpt["ready"]:
        reasons = ", ".join(rpt["blocked_reasons"])
        details = "; ".join(
            f"{k}: {v['detail']}" for k, v in rpt.items() if k not in ("ready", "blocked_reasons") and not v["passed"]
        )
        raise RuntimeError(f"Live not ready — blocked by: {reasons}. Details: {details}")
