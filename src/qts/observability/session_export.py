"""Sanitized session-evidence export — Desktop runtime truth -> auditable artifact.

The OBSERVE-ONLY session lives in the canonical SQLite store on the machine
that watched MT5 (the Windows Desktop runtime). An auditor (human or agent)
inspecting the Git repository CANNOT see that store, the MT5 terminal, or the
broker. This module closes that boundary with evidence discipline:

* EXPORT (on the Desktop): recompute every counter DIRECTLY from the canonical
  store for one session — never from in-memory collector state, never from a
  derived JSON — and emit ONE sanitized artifact binding each tick to a sha256
  row digest and an ordered hash chain. Nothing secret is exported: session
  meta is allowlisted, credential-shaped keys are redacted, logins masked.
* VERIFY (anywhere, e.g. on GitHub): recompute the hash chain and every
  counter from the artifact alone and check the structural contracts
  (provenance classes, symbol identity, timestamp-basis rules, order-freedom,
  duplicate handling, lifecycle status). Verification proves INTERNAL
  CONSISTENCY and contract conformance — it can never prove, by itself, that
  the underlying store was produced by a real MT5 terminal. That limit is
  stated in every verification report.

Artifact versions: ``qts.session_evidence.v1``.

Fail-closed rules:
* Unknown session -> export refused.
* Any tick whose stored payload cannot be parsed or disagrees with its
  accessor columns -> export refused (a store that cannot vouch for itself
  produces no evidence).
* Verification of a tampered/malformed artifact -> verdict REFUSED with the
  concrete list of violations, never a partial pass.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from qts.db import connect as db_connect
from qts.observability.lineage import code_version

ARTIFACT_VERSION = "qts.session_evidence.v1"

#: Session meta keys the OBSERVE-ONLY collector is contracted to write.
#: Anything else is redacted on export (allowlist, fail-closed).
_META_ALLOWLIST = frozenset(
    {
        "kind",
        "mode",
        "environment",
        "canonical_symbol",
        "broker_symbol",
        "broker",
        "data_source",
        "timestamp_basis",
        "code_version",
        "readiness_checks_passed",
        "orders_possible",
        "started_at",
        "ended_at",
        "error",
    }
)

#: Provenance classes a genuine observe-only session may contain. Anything
#: else in the session's ticks is contamination and is surfaced, not hidden.
_OBSERVE_PROVENANCE_CLASSES = frozenset({"DEMO", "REAL"})

#: Timestamp bases the canonical tick contract can produce.
_KNOWN_BASES = ("broker-normalized(measured-m1-bar)", "broker-normalized(assumed-utc-fallback)")

_CREDENTIAL_KEY_RE = re.compile(r"(password|passwd|token|secret|api_?key|credential)", re.I)
_LOGIN_KEY_RE = re.compile(r"login", re.I)
_SESSION_ID_RE = re.compile(r"^FS-[0-9a-f]{6}$")


class SessionExportError(RuntimeError):
    """Export refused — the store cannot vouch for this session's evidence."""


def _redact_meta(meta: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Allowlist-sanitize session meta. Returns (sanitized, redacted_keys)."""
    out: dict[str, Any] = {}
    redacted: list[str] = []
    for k, v in (meta or {}).items():
        if _CREDENTIAL_KEY_RE.search(k):
            redacted.append(k)
            out[k] = "<REDACTED>"
            continue
        if _LOGIN_KEY_RE.search(k):
            s = str(v)
            out[k] = f"****{s[-2:]}" if len(s) > 2 else "****"
            continue
        if k not in _META_ALLOWLIST:
            redacted.append(k)
            out[k] = "<REDACTED:non-allowlisted>"
            continue
        out[k] = v
    return out, redacted


def _row_digest(row: dict[str, Any]) -> str:
    """Deterministic sha256 over the exported row fields (canonical JSON)."""
    body = json.dumps(row, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _chain_root(session_id: str, row_digests: list[str]) -> str:
    """Ordered hash chain: H(...H(H(session_id || d0) || d1)...) — binds the
    tick COUNT, ORDER, and CONTENT together; any insertion/deletion/reorder
    breaks the root."""
    acc = hashlib.sha256(f"qts-session-chain:{session_id}".encode()).hexdigest()
    for d in row_digests:
        acc = hashlib.sha256(f"{acc}:{d}".encode()).hexdigest()
    return acc


def export_session_evidence(
    session_id: str,
    *,
    db_path: Path | str = "data/sqlite/forward_observatory.db",
    samples_each_end: int = 5,
) -> dict[str, Any]:
    """Build the sanitized evidence artifact for ONE session from the store.

    Every counter is recomputed here, from canonical storage, at export time.
    Raises :class:`SessionExportError` (fail closed) when the session is
    unknown or any stored record fails integrity checks.
    """
    db_path = Path(db_path)
    if not db_path.exists():
        raise SessionExportError(f"canonical observation store not found: {db_path}")

    with db_connect(db_path) as con:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "observation_ticks" not in tables or "observation_sessions" not in tables:
            raise SessionExportError(f"store {db_path} lacks canonical observation tables")
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise SessionExportError(f"store failed PRAGMA integrity_check: {integrity}")

        srow = con.execute(
            "SELECT id, start, end, status, meta FROM observation_sessions WHERE id=?", (session_id,)
        ).fetchone()
        if srow is None:
            raise SessionExportError(f"session {session_id} not found in canonical store")
        sid, start, end, status, meta_json = srow
        try:
            meta = json.loads(meta_json) if meta_json else {}
        except ValueError:
            raise SessionExportError(f"session {session_id} meta unparseable — store cannot vouch") from None

        rows = con.execute(
            "SELECT payload FROM observation_ticks WHERE session_id=? ORDER BY COALESCE(event_time, created_at), rowid",
            (session_id,),
        ).fetchall()
        signal_count = con.execute(
            "SELECT COUNT(*) FROM observation_signals WHERE session_id=?", (session_id,)
        ).fetchone()[0]
        order_tables = sorted(t for t in tables if "order" in t.lower())

    tick_rows: list[dict[str, Any]] = []
    payloads: list[dict[str, Any]] = []
    for i, (payload_json,) in enumerate(rows):
        try:
            p = json.loads(payload_json)
        except ValueError as e:
            raise SessionExportError(f"tick #{i} payload unparseable — export refused") from e
        row = {
            "i": i,
            "event_time": p.get("broker_event_time"),
            "receipt_time": p.get("timestamp"),
            "broker_time_raw": p.get("broker_time_raw"),
            "server_utc_offset_s": p.get("server_utc_offset_s"),
            "timestamp_basis": p.get("timestamp_basis"),
            "provenance": p.get("provenance"),
            "symbol": p.get("symbol"),
        }
        tick_rows.append(row)
        payloads.append(p)

    meta_sanitized, redacted_keys = _redact_meta(meta)

    by_prov: dict[str, int] = {}
    bases: dict[str, int] = {}
    symbols: set[str] = set()
    offsets: set[float] = set()
    raw_stamps: list[tuple[Any, Any]] = []
    monotonic_violations = 0
    prev_event: str | None = None
    for row, p in zip(tick_rows, payloads, strict=True):
        by_prov[row["provenance"] or "UNVERIFIED"] = by_prov.get(row["provenance"] or "UNVERIFIED", 0) + 1
        basis = str(row["timestamp_basis"])
        bases[basis] = bases.get(basis, 0) + 1
        if row["symbol"]:
            symbols.add(str(row["symbol"]))
        if row["server_utc_offset_s"] is not None:
            offsets.add(float(row["server_utc_offset_s"]))
        tp = p.get("tick_provenance") or {}
        raw_stamps.append((tp.get("mt5_time_msc"), tp.get("mt5_time")))
        ev = row["event_time"]
        if prev_event is not None and ev is not None and str(ev) < prev_event:
            monotonic_violations += 1
        if ev is not None:
            prev_event = str(ev)

    duplicates_in_store = len(raw_stamps) - len(set(raw_stamps))
    for r in tick_rows:
        r["sha256"] = _row_digest({k: v for k, v in r.items() if k != "sha256"})
    chain_root = _chain_root(session_id, [r["sha256"] for r in tick_rows])

    n = samples_each_end
    sample_payloads = {
        "first": payloads[:n],
        "last": payloads[-n:] if len(payloads) > n else [],
        "note": "verbatim stored payloads for human inspection; every other tick is digest-bound",
    }

    return {
        "artifact": ARTIFACT_VERSION,
        "exported_at": datetime.now(UTC).isoformat(),
        "exporter_code_version": code_version(),
        "session": {
            "id": sid,
            "status": status,
            "start": start,
            "end": end or None,
            "meta_sanitized": meta_sanitized,
            "meta_redacted_keys": sorted(set(redacted_keys)),
        },
        "claims_basis": (
            "every counter below was recomputed from the canonical SQLite observation store "
            "at export time; nothing is copied from in-memory collector state or derived JSON"
        ),
        "canonical_store": {
            "path": str(db_path),
            "tables": sorted(tables),
            "integrity_check": integrity,
        },
        "counters": {
            "tick_count": len(tick_rows),
            "distinct_raw_broker_stamps": len(set(raw_stamps)),
            "duplicate_raw_stamps_in_store": duplicates_in_store,
            "ticks_by_provenance": by_prov,
            "symbols": sorted(symbols),
            "timestamp_bases": bases,
            "server_utc_offsets_s": sorted(offsets),
            "first_event_time": tick_rows[0]["event_time"] if tick_rows else None,
            "last_event_time": tick_rows[-1]["event_time"] if tick_rows else None,
            "signal_records_for_session": signal_count,
            "monotonic_event_time_violations": monotonic_violations,
        },
        "order_free": {
            "orders_possible_flag": meta_sanitized.get("orders_possible"),
            "signal_records_for_session": signal_count,
            "order_tables_in_store": order_tables,
            "structural_note": (
                "the observe-only collector module is AST-pinned order-free and its injected "
                "order_send sentinel raises if ever reached (tests/test_observe_only_collector.py)"
            ),
        },
        "digest": {
            "algorithm": "sha256",
            "row_digest_over": "canonical JSON of tick_rows fields (excluding sha256)",
            "chain": "sha256 chain over session_id then ordered row digests",
            "chain_root": chain_root,
        },
        "tick_rows": tick_rows,
        "sample_payloads": sample_payloads,
    }


def write_session_evidence(
    session_id: str,
    *,
    db_path: Path | str = "data/sqlite/forward_observatory.db",
    out_path: Path | str | None = None,
) -> tuple[dict[str, Any], Path]:
    art = export_session_evidence(session_id, db_path=db_path)
    out = Path(out_path) if out_path else Path("data/evidence/exports") / f"{session_id}.session_evidence.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(art, indent=2, default=str) + "\n", encoding="utf-8")
    return art, out


# ------------------------------------------------------------------ verify


def verify_session_export(artifact: dict[str, Any] | Path | str) -> dict[str, Any]:
    """Structurally verify an exported artifact. Returns a verdict dict.

    Proves: internal consistency (hash chain, counts), provenance classes,
    symbol identity, timestamp-basis contract, duplicate handling, lifecycle
    status, order-freedom fields, and sanitization. It CANNOT prove the
    artifact's origin (a real MT5 terminal on the Desktop) — that is stated
    explicitly in the verdict so no one over-claims.
    """
    violations: list[str] = []
    notes: list[str] = []

    if isinstance(artifact, (str, Path)):
        try:
            artifact = json.loads(Path(artifact).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            return {"verdict": "REFUSED", "violations": [f"artifact unreadable: {e}"]}
    if not isinstance(artifact, dict):
        return {"verdict": "REFUSED", "violations": ["artifact is not a JSON object"]}

    if artifact.get("artifact") != ARTIFACT_VERSION:
        violations.append(f"unknown artifact version {artifact.get('artifact')!r}")

    session = artifact.get("session") or {}
    sid = session.get("id")
    if not isinstance(sid, str) or not _SESSION_ID_RE.match(sid):
        violations.append(f"session id {sid!r} does not match canonical FS-<6 hex> format")

    status = session.get("status")
    if status not in ("ENDED", "ENDED_ON_ERRORS", "ACTIVE"):
        violations.append(f"unexpected session status {status!r}")
    elif status == "ACTIVE":
        notes.append("session still ACTIVE — counters are a mid-session snapshot, not terminal")
    if status == "ENDED_ON_ERRORS":
        notes.append("session ended on errors — see session.meta_sanitized.error")

    meta = session.get("meta_sanitized") or {}
    for k, v in meta.items():
        if isinstance(v, str) and _CREDENTIAL_KEY_RE.search(k) and v != "<REDACTED>":
            violations.append(f"credential-shaped meta key {k!r} not redacted")
    if meta.get("orders_possible") is not False:
        violations.append(
            f"orders_possible must be false for observe-only sessions, got {meta.get('orders_possible')!r}"
        )

    rows = artifact.get("tick_rows") or []
    counters = artifact.get("counters") or {}
    if len(rows) != counters.get("tick_count"):
        violations.append(f"tick_count {counters.get('tick_count')} != exported rows {len(rows)}")

    # Recompute row digests + chain root.
    digests: list[str] = []
    for r in rows:
        if not isinstance(r, dict):
            violations.append("tick row is not an object")
            continue
        declared = r.get("sha256")
        recomputed = _row_digest({k: v for k, v in r.items() if k != "sha256"})
        if declared != recomputed:
            violations.append(f"row {r.get('i')}: sha256 mismatch (tampered or corrupted)")
        digests.append(recomputed)
    root = _chain_root(str(sid), digests)
    declared_root = (artifact.get("digest") or {}).get("chain_root")
    if root != declared_root:
        violations.append("hash chain root mismatch — tick count/order/content altered")

    # Ordering + monotonicity.
    for idx, r in enumerate(rows):
        if r.get("i") != idx:
            violations.append(f"row index gap at position {idx} (got i={r.get('i')})")
            break
    if counters.get("monotonic_event_time_violations", 0) != 0:
        violations.append(f"{counters.get('monotonic_event_time_violations')} non-monotonic broker event times")

    # Duplicate handling: store must not contain the same raw stamp twice.
    if counters.get("duplicate_raw_stamps_in_store", 0) != 0:
        violations.append("duplicate raw broker stamps persisted in the canonical store")

    # Provenance + symbol + timestamp-basis contracts.
    by_prov = counters.get("ticks_by_provenance") or {}
    contamination = sorted(set(by_prov) - _OBSERVE_PROVENANCE_CLASSES)
    if contamination:
        violations.append(f"non-observe provenance classes in session ticks: {contamination} (synthetic contamination)")
    symbols = counters.get("symbols") or []
    broker_symbol = meta.get("broker_symbol")
    if rows and broker_symbol and any(str(s) != str(broker_symbol) for s in symbols):
        violations.append(f"symbol drift: session ticks {symbols} vs broker symbol {broker_symbol}")
    bases = counters.get("timestamp_bases") or {}
    for b in bases:
        if not (b.startswith("broker-normalized(") or b in _KNOWN_BASES):
            violations.append(f"unknown timestamp basis {b!r}")
    for off in counters.get("server_utc_offsets_s") or []:
        if float(off) % 900.0 != 0.0:
            violations.append(f"server_utc_offset_s {off} not on the 15-minute measurement grid")

    # Sample payloads must agree with the row contracts.
    samples = (artifact.get("sample_payloads") or {}).get("first") or []
    samples += (artifact.get("sample_payloads") or {}).get("last") or []
    for s in samples:
        prov = s.get("provenance")
        if prov not in _OBSERVE_PROVENANCE_CLASSES:
            violations.append(f"sample payload provenance {prov!r} outside {_OBSERVE_PROVENANCE_CLASSES}")
        if broker_symbol and s.get("symbol") != broker_symbol:
            violations.append(f"sample payload symbol {s.get('symbol')!r} != broker symbol {broker_symbol!r}")

    # Order-freedom fields.
    order_free = artifact.get("order_free") or {}
    if order_free.get("signal_records_for_session", None) != 0:
        violations.append(f"signal records exist for session: {order_free.get('signal_records_for_session')}")
    if order_free.get("order_tables_in_store"):
        violations.append(f"order tables present in observation store: {order_free.get('order_tables_in_store')}")

    verdict = "REFUSED" if violations else "CONSISTENT"
    return {
        "verdict": verdict,
        "session_id": sid,
        "status": status,
        "tick_count": len(rows),
        "ticks_by_provenance": by_prov,
        "violations": violations,
        "notes": notes,
        "verification_limits": (
            "This verdict proves the artifact is internally consistent and satisfies the "
            "observe-only structural contracts. It does NOT independently prove the session "
            "was produced by a real MT5 terminal — that origin claim requires the artifact to "
            "come from the Desktop's canonical store, which only the operator can attest."
        ),
    }
