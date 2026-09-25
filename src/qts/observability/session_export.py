"""Sanitized session-evidence export — Desktop runtime truth -> auditable artifact.

The OBSERVE-ONLY session lives in the canonical SQLite store on the machine
that watched MT5 (the Windows Desktop runtime). An auditor (human or agent)
inspecting the Git repository CANNOT see that store, the MT5 terminal, or the
broker. This module closes that boundary with evidence discipline:

* EXPORT (on the Desktop): recompute every counter DIRECTLY from the canonical
  store for one session — never from in-memory collector state, never from a
  derived JSON — and emit ONE artifact binding a selected projection of each
  tick to a sha256 row digest and an ordered hash chain. Session metadata is
  allowlisted, credential-shaped keys redacted and logins masked. Full sample
  payloads are not cryptographically bound by v1.
* VERIFY (anywhere): recompute the hash chain and all row-derivable
  summaries, cross-check source-store declarations, and check structural contracts
  (provenance classes, symbol identity, timestamp-basis rules, order-freedom,
  duplicate handling, lifecycle status). Verification proves INTERNAL
  CONSISTENCY and contract conformance — it can never prove, by itself, that
  the underlying store was produced by a real MT5 terminal. That limit is
  stated in every verification report. Omitted raw stamp pairs, database
  inventory/integrity and signal counts cannot be independently recomputed.

Artifact versions: ``qts.session_evidence.v1``.

Fail-closed rules:
* Unknown session -> export refused.
* Any tick whose stored payload cannot be parsed ->
  export refused. Source-store accessor-column agreement is not established
  by this artifact-only verifier.
* Observable contradictions, digest mismatches or malformed artifacts ->
  REFUSED with a concrete violation, never a partial pass. A fully rewritten
  self-consistent artifact is not distinguishable without external authentication.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal, DecimalException
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
        "product_mode",
        "observation_mode",
        "mode",
        "environment",
        "application_mode",
        "canonical_symbol",
        "broker_symbol",
        "broker",
        "data_source",
        "timestamp_basis",
        "code_version",
        "readiness_checks_passed",
        "readiness_report",
        "terminal_failure",
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


_VERIFICATION_LIMITS = (
    "CONSISTENT means artifact-internal structural consistency under the v1 checks, not authenticity. "
    "Row-derived summaries are recomputed. SQLite integrity, table inventory, signal counts and "
    "full-store raw-stamp duplicate counts remain exporter declarations, not independently observed "
    "store evidence. Original millisecond stamp pairs and full payloads are absent for non-sampled "
    "ticks. Only selected row fields are hash-bound; metadata, prices and full samples are not. "
    "The unsigned chain can be recomputed by an editor. Desktop/MT5 origin remains operator-attested. "
    "Clock accuracy, collection completeness, dropped duplicates, broker order history and execution "
    "eligibility cannot be established from this artifact. Verification grants no trading authority."
)


class _InvalidEvidence(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise _InvalidEvidence(message)


def _keys(value: Any, fields: str, path: str) -> None:
    _require(isinstance(value, dict), f"{path}: expected object")
    _require(set(value) == set(fields.split()), f"{path}: missing or unknown v1 fields")


def _text(value: Any, path: str) -> str:
    _require(isinstance(value, str) and bool(value), f"{path}: expected nonempty string")
    return value


def _number(value: Any, path: str) -> float:
    _require(type(value) in (int, float), f"{path}: expected number (not boolean or string)")
    _require(math.isfinite(value), f"{path}: expected finite number")
    return float(value)


def _count(value: Any, path: str) -> int:
    _require(type(value) is int and value >= 0, f"{path}: expected nonnegative integer")
    return value


def _stamp(value: Any, path: str) -> datetime:
    _text(value, path)
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise _InvalidEvidence(f"{path}: invalid timestamp") from None
    _require("T" in value and stamp.utcoffset() is not None, f"{path}: timezone-aware timestamp required")
    return stamp


def _strings(value: Any, path: str) -> list[str]:
    _require(isinstance(value, list), f"{path}: expected list")
    for item in value:
        _text(item, path)
    _require(value == sorted(set(value)), f"{path}: expected sorted unique strings")
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in result, f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def verify_session_export(artifact: dict[str, Any] | Path | str) -> dict[str, Any]:
    """Read-only, fail-closed structural verification; never grants execution authority.

    Reject malformed inputs as verdicts (including duplicate JSON keys, nonfinite
    numbers and bool-as-int counters). Checks observable contradictions, not the
    truth of source-store declarations or operator-attested physical origin.
    """
    try:
        if isinstance(artifact, (str, Path)):
            artifact = json.loads(Path(artifact).read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
        # Also reject NaN/Infinity, non-JSON objects and cycles on the dict API.
        json.dumps(artifact, allow_nan=False)
        return _verify_artifact(artifact)
    except (OSError, ValueError, TypeError, OverflowError, RecursionError, DecimalException) as exc:
        return {"verdict": "REFUSED", "violations": [str(exc)], "verification_limits": _VERIFICATION_LIMITS}


def _verify_artifact(artifact: Any) -> dict[str, Any]:
    _keys(
        artifact,
        "artifact exported_at exporter_code_version session claims_basis canonical_store counters "
        "order_free digest tick_rows sample_payloads",
        "artifact",
    )
    _require(artifact["artifact"] == ARTIFACT_VERSION, "unknown artifact version")
    exported = _stamp(artifact["exported_at"], "exported_at")
    _text(artifact["exporter_code_version"], "exporter_code_version")
    _require(
        artifact["claims_basis"]
        == (
            "every counter below was recomputed from the canonical SQLite observation store "
            "at export time; nothing is copied from in-memory collector state or derived JSON"
        ),
        "claims_basis: unexpected v1 descriptor",
    )
    session = artifact["session"]
    _keys(session, "id status start end meta_sanitized meta_redacted_keys", "session")
    sid = _text(session["id"], "session.id")
    _require(_SESSION_ID_RE.fullmatch(sid) is not None, "session id does not match canonical FS-<6 hex> format")
    status = session["status"]
    _require(status in ("ACTIVE", "ENDED", "ENDED_ON_ERRORS"), "unexpected session status")
    start = _stamp(session["start"], "session.start")
    _require(exported >= start, "export predates session start")
    if status == "ACTIVE":
        _require(session["end"] is None, "ACTIVE session has terminal end")
    else:
        end = _stamp(session["end"], "session.end")
        _require(start <= end <= exported, "session lifecycle/export chronology contradiction")

    meta = session["meta_sanitized"]
    _require(isinstance(meta, dict), "session.meta_sanitized: expected object")
    redacted = []
    for key, value in meta.items():
        _text(key, "meta key")
        if _CREDENTIAL_KEY_RE.search(key):
            _require(value == "<REDACTED>", f"credential-shaped meta key {key!r} not redacted")
            redacted.append(key)
        elif _LOGIN_KEY_RE.search(key):
            _require(
                isinstance(value, str) and re.fullmatch(r"\*{4}(?:.{2})?", value) is not None,
                "login metadata not masked",
            )
        elif key not in _META_ALLOWLIST:
            _require(value == "<REDACTED:non-allowlisted>", f"non-allowlisted meta key {key!r} not redacted")
            redacted.append(key)
        elif key == "readiness_checks_passed":
            _count(value, "meta.readiness_checks_passed")
        elif key == "readiness_report":
            _require(isinstance(value, dict), "meta.readiness_report: expected object")
            if isinstance(value, dict):
                _require(value.get("passed") is True, "meta.readiness_report.passed must be true")
                _require(isinstance(value.get("checks"), dict), "meta.readiness_report.checks: expected object")
                _require(isinstance(value.get("blocked_reasons", []), list), "meta.readiness_report.blocked_reasons: expected list")
        elif key == "terminal_failure":
            _require(isinstance(value, dict), "meta.terminal_failure: expected object")
            if isinstance(value, dict):
                _text(value.get("category"), "meta.terminal_failure.category")
                _stamp(value.get("timestamp"), "meta.terminal_failure.timestamp")
                _count(value.get("consecutive_failures"), "meta.terminal_failure.consecutive_failures")
        elif key != "orders_possible":
            _text(value, f"meta.{key}")
    _require(
        _strings(session["meta_redacted_keys"], "meta_redacted_keys") == sorted(redacted),
        "meta_redacted_keys contradicts sanitized metadata",
    )
    _require(meta.get("orders_possible") is False, "orders_possible must be false for observe-only sessions")
    _require(meta.get("started_at") == session["start"], "meta.started_at contradicts session.start")
    if status == "ACTIVE":
        _require("ended_at" not in meta and "error" not in meta, "ACTIVE session has terminal metadata")
    else:
        _require(meta.get("ended_at") == session["end"], "meta.ended_at contradicts session.end")
    if status == "ENDED":
        _require("error" not in meta, "ENDED session declares an error")

    rows = artifact["tick_rows"]
    _require(isinstance(rows, list), "tick_rows: expected list")
    counters = artifact["counters"]
    _keys(
        counters,
        "tick_count distinct_raw_broker_stamps duplicate_raw_stamps_in_store ticks_by_provenance "
        "symbols timestamp_bases server_utc_offsets_s first_event_time last_event_time "
        "signal_records_for_session monotonic_event_time_violations",
        "counters",
    )
    for key in (
        "tick_count",
        "distinct_raw_broker_stamps",
        "duplicate_raw_stamps_in_store",
        "signal_records_for_session",
        "monotonic_event_time_violations",
    ):
        _count(counters[key], f"counters.{key}")
    for key in ("ticks_by_provenance", "timestamp_bases"):
        _require(isinstance(counters[key], dict), f"counters.{key}: expected object")
        for label, count in counters[key].items():
            _text(label, f"counters.{key} key")
            _count(count, f"counters.{key}.{label}")
    _strings(counters["symbols"], "counters.symbols")
    offsets = counters["server_utc_offsets_s"]
    _require(isinstance(offsets, list), "counters.server_utc_offsets_s: expected list")
    for offset in offsets:
        _number(offset, "counters.server_utc_offsets_s")
    _require(offsets == sorted(set(offsets)), "counter offsets must be sorted and unique")
    _require(counters["tick_count"] == len(rows), "tick_count does not match exported rows")

    digest = artifact["digest"]
    _keys(digest, "algorithm row_digest_over chain chain_root", "digest")
    _require(digest["algorithm"] == "sha256", "digest algorithm must be sha256")
    _require(
        digest["row_digest_over"] == "canonical JSON of tick_rows fields (excluding sha256)",
        "row_digest_over contradicts v1 contract",
    )
    _require(
        digest["chain"] == "sha256 chain over session_id then ordered row digests",
        "chain descriptor contradicts v1 contract",
    )
    digests = []
    events = []
    raw_event_pairs = set()
    for idx, row in enumerate(rows):
        _keys(
            row,
            "i event_time receipt_time broker_time_raw server_utc_offset_s timestamp_basis provenance symbol sha256",
            f"row {idx}",
        )
        _require(type(row["i"]) is int and row["i"] == idx, f"row index gap at position {idx}")
        recomputed = _row_digest({k: v for k, v in row.items() if k != "sha256"})
        _require(row["sha256"] == recomputed, f"row {idx}: sha256 mismatch (tampered or corrupted)")
        digests.append(recomputed)
        event = _stamp(row["event_time"], f"row {idx}.event_time")
        receipt = _stamp(row["receipt_time"], f"row {idx}.receipt_time")
        _require(start <= receipt <= exported, "row receipt_time outside session/export interval")
        if status != "ACTIVE":
            _require(receipt <= end, "row receipt_time after session end")
        events.append(event)
        raw = row["broker_time_raw"]
        if raw is not None:
            raw = _number(raw, f"row {idx}.broker_time_raw")
        offset = _number(row["server_utc_offset_s"], f"row {idx}.server_utc_offset_s")
        _require(offset % 900 == 0, "server_utc_offset_s not on the 15-minute measurement grid")
        if raw is not None:
            # The adapter also supports raw time in milliseconds, or no raw
            # seconds when time_msc is usable. Do not invent omitted stamps.
            raw_seconds = raw / 1000 if raw > 1e12 else raw
            _require(raw_seconds > 1e9, "unusable raw broker seconds")
            _require(
                math.floor(event.timestamp() + offset) == math.floor(raw_seconds),
                "raw broker seconds contradict normalized event_time",
            )
        _require(row["timestamp_basis"] in _KNOWN_BASES, "unknown timestamp basis")
        if row["timestamp_basis"] == "broker-normalized(assumed-utc-fallback)":
            _require(offset == 0, "assumed UTC fallback contradicts nonzero offset")
        _require(row["provenance"] in ("DEMO", "REAL"), "non-observe provenance (synthetic contamination)")
        _text(row["symbol"], f"row {idx}.symbol")
        _require(row["symbol"] == meta.get("broker_symbol"), "symbol drift vs session broker symbol")
        raw_event_pairs.add((raw, event))
    _require(_chain_root(sid, digests) == digest["chain_root"], "hash chain root mismatch")

    # Authoritative summaries come from rows, never from their duplicated declarations.
    derived = {
        "ticks_by_provenance": dict(Counter(r["provenance"] for r in rows)),
        "symbols": sorted({r["symbol"] for r in rows}),
        "timestamp_bases": dict(Counter(r["timestamp_basis"] for r in rows)),
        "server_utc_offsets_s": sorted({r["server_utc_offset_s"] for r in rows}),
        "first_event_time": rows[0]["event_time"] if rows else None,
        "last_event_time": rows[-1]["event_time"] if rows else None,
        "monotonic_event_time_violations": sum(a > b for a, b in zip(events, events[1:], strict=False)),
    }
    for key, value in derived.items():
        _require(counters[key] == value, f"counters.{key} contradicts tick_rows")
    _require(derived["monotonic_event_time_violations"] == 0, "non-monotonic broker event times")
    _require(counters["duplicate_raw_stamps_in_store"] == 0, "duplicate raw broker stamps persisted in canonical store")
    _require(
        counters["distinct_raw_broker_stamps"] + counters["duplicate_raw_stamps_in_store"] == len(rows),
        "raw stamp counters contradict tick_count",
    )
    # A repeated normalized stamp with the same offset/raw second is observable;
    # absence of repeats is NOT proof about omitted original millisecond stamps.
    _require(len(raw_event_pairs) == len(rows), "duplicate exported broker event stamps")
    if "timestamp_basis" in meta:
        basis = meta["timestamp_basis"]
        _require(
            basis in (*_KNOWN_BASES, "broker-normalized(measured-m1-bar|assumed-utc-fallback)"),
            "unknown metadata timestamp basis",
        )
        if basis in _KNOWN_BASES:
            _require(all(r["timestamp_basis"] == basis for r in rows), "metadata timestamp basis contradicts rows")

    store = artifact["canonical_store"]
    _keys(store, "path tables integrity_check", "canonical_store")
    _text(store["path"], "canonical_store.path")
    tables = _strings(store["tables"], "canonical_store.tables")
    _require(
        {"observation_sessions", "observation_ticks", "observation_signals"} <= set(tables),
        "canonical_store missing observation tables",
    )
    _require(store["integrity_check"] == "ok", "canonical_store integrity declaration is not ok")
    order_free = artifact["order_free"]
    _keys(
        order_free,
        "orders_possible_flag signal_records_for_session order_tables_in_store structural_note",
        "order_free",
    )
    _require(order_free["orders_possible_flag"] is False, "orders_possible_flag contradicts observe-only contract")
    _count(order_free["signal_records_for_session"], "order_free.signal_records_for_session")
    _require(
        order_free["signal_records_for_session"] == counters["signal_records_for_session"] == 0,
        "signal records counters must agree and both be zero",
    )
    order_tables = _strings(order_free["order_tables_in_store"], "order_tables_in_store")
    _require(
        order_tables == [t for t in tables if "order" in t.lower()], "order tables contradict canonical_store.tables"
    )
    _require(not order_tables, "order tables present in observation store")
    _require(
        order_free["structural_note"]
        == (
            "the observe-only collector module is AST-pinned order-free and its injected "
            "order_send sentinel raises if ever reached (tests/test_observe_only_collector.py)"
        ),
        "unexpected order_free structural descriptor",
    )
    _verify_samples(artifact["sample_payloads"], rows, sid)

    notes = []
    if status == "ACTIVE":
        notes.append("session still ACTIVE — counters are a mid-session snapshot, not terminal")
    if status == "ENDED_ON_ERRORS":
        notes.append("session ended on errors — see session.meta_sanitized.error")
    return {
        "verdict": "CONSISTENT",
        "session_id": sid,
        "status": status,
        "tick_count": len(rows),
        "ticks_by_provenance": derived["ticks_by_provenance"],
        "violations": [],
        "notes": notes,
        "verification_limits": _VERIFICATION_LIMITS,
    }


def _verify_samples(samples: Any, rows: list[dict[str, Any]], sid: str) -> None:
    _keys(samples, "first last note", "sample_payloads")
    _require(
        samples["note"] == "verbatim stored payloads for human inspection; every other tick is digest-bound",
        "unexpected sample descriptor",
    )
    first, last = samples["first"], samples["last"]
    _require(isinstance(first, list) and isinstance(last, list), "sample endpoints must be lists")
    n = len(first)
    _require(n <= len(rows), "too many first samples")
    # v1 exports a configurable number at each end, not necessarily five.
    # With zero requested samples, the legacy exporter emitted all rows as last.
    expected_last = len(rows) if n == 0 else (n if len(rows) > n else 0)
    _require(len(last) == expected_last, "sample endpoint cardinality contradicts v1 export")
    shared = {
        "event_time": "broker_event_time",
        "receipt_time": "timestamp",
        "broker_time_raw": "broker_time_raw",
        "server_utc_offset_s": "server_utc_offset_s",
        "timestamp_basis": "timestamp_basis",
        "provenance": "provenance",
        "symbol": "symbol",
    }
    pairs = list(zip(rows[:n], first, strict=True)) + list(zip(rows[len(rows) - len(last) :], last, strict=True))
    seen: dict[int, dict[str, Any]] = {}
    stamps: dict[tuple[Any, Any], int] = {}
    ids: dict[str, int] = {}
    for row, sample in pairs:
        _keys(
            sample,
            "id timestamp symbol bid ask mid spread_bps volatility_20 session regime data_freshness_ms "
            "anomaly provenance broker_event_time broker_time_raw server_utc_offset_s timestamp_basis "
            "tick_provenance session_id",
            "sample payload",
        )
        for key in ("id", "session", "regime"):
            _text(sample[key], f"sample.{key}")
        for key in ("volatility_20", "data_freshness_ms"):
            if sample[key] is not None:
                _number(sample[key], f"sample.{key}")
        if sample["anomaly"] is not None:
            _text(sample["anomaly"], "sample.anomaly")
        _number(sample["server_utc_offset_s"], "sample.server_utc_offset_s")
        if sample["broker_time_raw"] is not None:
            _number(sample["broker_time_raw"], "sample.broker_time_raw")
        for row_key, sample_key in shared.items():
            _require(
                sample_key in sample and sample[sample_key] == row[row_key],
                f"sample {row['i']}.{sample_key} contradicts corresponding tick row",
            )
        _require(sample.get("session_id") == sid, "sample session_id contradicts session identity")
        if row["i"] in seen:
            _require(sample == seen[row["i"]], "overlapping endpoint samples disagree")
        seen[row["i"]] = sample
        _require(sample["id"] not in ids or ids[sample["id"]] == row["i"], "duplicate sample record id")
        ids[sample["id"]] = row["i"]
        tp = sample.get("tick_provenance")
        _require(isinstance(tp, dict), "sample tick_provenance must be object")
        _require(
            {"mt5_time", "mt5_time_msc"}
            <= set(tp)
            <= {"mt5_time", "mt5_time_msc", "server_utc_offset_s", "offset_basis", "broker_symbol", "received_at"},
            "sample tick_provenance: missing raw-stamp keys or unknown fields",
        )
        raw, msc = tp.get("mt5_time"), tp.get("mt5_time_msc")
        if raw is not None:
            _number(raw, "sample.mt5_time")
        if msc is not None:
            _number(msc, "sample.mt5_time_msc")
            _require(
                msc >= 0 and float(msc).is_integer(), "sample mt5_time_msc must be nonnegative integer milliseconds"
            )
        _require(raw == row["broker_time_raw"], "sample raw broker stamps contradict row")
        # Match MT5Adapter.ticks timestamp selection, including the seconds
        # fallback when time_msc is absent/zero, and raw millisecond time.
        base = (
            msc / 1000
            if msc is not None and msc > 1e12
            else ((raw / 1000 if raw > 1e12 else raw) if raw is not None else None)
        )
        _require(base is not None and base > 1e9, "sample has no usable raw broker stamp")
        _require(
            abs(base - row["server_utc_offset_s"] - _stamp(row["event_time"], "sample event").timestamp()) < 1e-6,
            "sample millisecond stamp/seconds fallback contradicts normalized event_time",
        )
        if raw is not None and msc is not None and msc > 1e12:
            _require(
                math.floor(msc / 1000) == math.floor(raw / 1000 if raw > 1e12 else raw),
                "sample raw broker stamps disagree",
            )
        if "server_utc_offset_s" in tp:
            _number(tp["server_utc_offset_s"], "sample.tick_provenance.server_utc_offset_s")
        for key, expected in (
            ("server_utc_offset_s", row["server_utc_offset_s"]),
            ("broker_symbol", row["symbol"]),
            ("offset_basis", row["timestamp_basis"][18:-1]),
        ):
            if key in tp:
                _require(tp[key] == expected, f"sample tick_provenance.{key} contradicts row")
        if "received_at" in tp:
            received = _stamp(tp["received_at"], "sample.tick_provenance.received_at")
            _require(
                received <= _stamp(sample["timestamp"], "sample.timestamp"),
                "sample adapter received_at follows observation receipt_time",
            )
        pair = (msc, raw)
        _require(pair not in stamps or stamps[pair] == row["i"], "duplicate raw broker stamps in samples")
        stamps[pair] = row["i"]
        prices = {}
        for key in ("bid", "ask", "mid", "spread_bps"):
            value = sample.get(key)
            if value is not None:
                _require(type(value) in (str, int, float), f"sample.{key}: expected decimal number")
                number = Decimal(str(value))
                _require(number.is_finite(), f"sample.{key}: nonfinite price")
                prices[key] = number
        if "bid" in prices and "ask" in prices:
            bid, ask = prices["bid"], prices["ask"]
            _require(0 < bid <= ask, "sample bid/ask invalid")
            mid = (bid + ask) / 2
            if "mid" in prices:
                _require(prices["mid"] == mid, "sample midpoint contradicts bid/ask")
            if "spread_bps" in prices:
                _require(
                    abs(prices["spread_bps"] - (ask - bid) / mid * 10000) < Decimal("0.000000001"),
                    "sample spread contradicts bid/ask",
                )
