"""Research-grade full-data observation snapshot — a SEPARATE versioned contract.

The v1 audit artifact (``qts.session_evidence.v1``, ``session_export.py``) binds
a *projection* of each tick plus bounded samples: the right shape for an
auditable structural claim, deliberately not a dataset. FO-R1 needs the other
thing — the complete accepted dataset of one session, together with the
acquisition ledger and the run/clock identity that make the cohort
reproducible — without touching v1.

This module adds that contract:

* ``qts.research_snapshot.v1`` — one session, COMPLETE accepted payloads, the
  complete acquisition ledger, session/run metadata, code + configuration
  identity, schema version and hash-chain integrity.
* Verification recomputes every count and digest from the artifact alone and
  REFUSES any contradiction, so later modification is detectable.
* Credentials, secrets and machine identity never enter the artifact: session
  metadata is allowlisted, credential-shaped keys are redacted and logins are
  masked exactly as the v1 exporter does.

Boundary, stated in every report: this proves the artifact is internally
consistent, complete and unmodified. It cannot prove, by itself, that the
underlying store was produced by a real MT5 terminal.

The v1 contract and verifier are untouched by this module.
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

RESEARCH_SNAPSHOT_VERSION = "qts.research_snapshot.v1"

#: Ledger outcomes a research snapshot may contain (mirrors the canonical
#: acquisition vocabulary; a snapshot with an unknown outcome is refused).
_LEDGER_OUTCOMES = frozenset(
    {
        "SESSION_START",
        "STORED",
        "DUPLICATE",
        "VALIDATION_REJECTED",
        "RETRIEVAL_ERROR",
        "STORAGE_ERROR",
        "UNRESOLVED",
    }
)

#: Provenance classes a genuine observe-only session may contain.
_ALLOWED_PROVENANCE = frozenset({"DEMO", "REAL"})

#: Meta keys transferred by a research snapshot (allowlist — anything else is
#: redacted, never silently dropped). Superset of the v1 allowlist: the
#: research contract additionally carries the run-identity block.
_RESEARCH_META_ALLOWLIST = frozenset(
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
        "run_metadata",
    }
)

_CREDENTIAL_KEY_RE = re.compile(r"(password|passwd|token|secret|api_?key|credential)", re.I)
_SESSION_ID_RE = re.compile(r"^FS-[0-9a-f]{6}$")
_UNAVAILABLE_STATUSES = frozenset({"UNAVAILABLE", "MEASURED", "AVAILABLE"})


class ResearchSnapshotError(RuntimeError):
    """Export refused — the store cannot vouch for this session's dataset."""


# --------------------------------------------------------------------- helpers


def _require(condition: Any, message: str) -> None:
    if not condition:
        raise ResearchSnapshotError(message)


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(obj: Any) -> str:
    return hashlib.sha256(_canonical(obj).encode("utf-8")).hexdigest()


def _chain(session_id: str, digests: list[str]) -> str:
    """Ordered hash chain binding count, order and content of a row set."""
    acc = hashlib.sha256(f"qts-research-chain:{session_id}".encode()).hexdigest()
    for digest in digests:
        acc = hashlib.sha256(f"{acc}:{digest}".encode()).hexdigest()
    return acc


def _research_meta(meta: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Allowlist-sanitize session meta for the research contract.

    Same discipline as v1 (credential-shaped keys redacted, logins masked,
    unknown keys redacted rather than transferred) with one difference: the
    run-identity block is allowlisted because the research contract needs it
    to make a cohort reproducible.
    """
    out: dict[str, Any] = {}
    redacted: list[str] = []
    for key, value in (meta or {}).items():
        if _CREDENTIAL_KEY_RE.search(str(key)):
            out[key] = "<REDACTED>"
            redacted.append(key)
            continue
        if "login" in str(key).lower():
            text = str(value)
            out[key] = f"****{text[-2:]}" if len(text) > 2 else "****"
            continue
        if key not in _RESEARCH_META_ALLOWLIST:
            out[key] = "<REDACTED:non-allowlisted>"
            redacted.append(key)
            continue
        out[key] = value
    return out, redacted


def _row_digest(payload: dict[str, Any]) -> str:
    return _sha256(payload)


# ---------------------------------------------------------------------- export


def export_research_snapshot(
    session_id: str,
    *,
    db_path: Path | str = "data/sqlite/forward_observatory.db",
) -> dict[str, Any]:
    """Build the complete research snapshot for ONE session from the store.

    Fail-closed: unknown session, unparseable metadata, a stored payload that
    is not an object, or a ledger that disagrees with the accepted rows all
    refuse the export rather than emitting a partial dataset.
    """
    db_path = Path(db_path)
    _require(db_path.exists(), f"canonical observation store not found: {db_path}")

    with db_connect(db_path) as con:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        _require(
            {"observation_ticks", "observation_sessions"} <= tables,
            f"store {db_path} lacks canonical observation tables",
        )
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        _require(integrity == "ok", f"store failed PRAGMA integrity_check: {integrity}")

        srow = con.execute(
            "SELECT id, start, end, status, meta FROM observation_sessions WHERE id=?", (session_id,)
        ).fetchone()
        _require(srow is not None, f"session {session_id} not found in canonical store")
        sid, start, end, status, meta_json = srow
        try:
            meta = json.loads(meta_json) if meta_json else {}
        except ValueError:
            raise ResearchSnapshotError(f"session {session_id} meta unparseable — store cannot vouch") from None

        tick_rows = con.execute(
            "SELECT id, payload, created_at, provenance, session_id, symbol, event_time"
            " FROM observation_ticks WHERE session_id=? ORDER BY rowid",
            (session_id,),
        ).fetchall()
        attempt_rows = con.execute(
            "SELECT seq, outcome, attempted_at, scheduled_at, slot_index, interval_s, monotonic_s,"
            " record_id, dup_key, reason, persistence_ok, deferred, gap_slots, payload"
            " FROM observation_attempts WHERE session_id=? ORDER BY seq",
            (session_id,),
        ).fetchall()

    accepted: list[dict[str, Any]] = []
    digests: list[str] = []
    identities: set[str] = set()
    for index, row in enumerate(tick_rows):
        rid, payload_json, created_at, provenance, row_session, symbol, event_time = row
        try:
            payload = json.loads(payload_json)
        except ValueError:
            raise ResearchSnapshotError(f"row {index} payload unparseable — export refused") from None
        _require(isinstance(payload, dict), f"row {index} payload is not an object — export refused")
        record = {
            "i": index,
            "id": rid,
            "created_at": created_at,
            "provenance": provenance,
            "session_id": row_session,
            "symbol": symbol,
            "event_time": event_time,
            "payload": payload,
            "sha256": _row_digest(payload),
        }
        identities.add(rid)
        digests.append(record["sha256"])
        accepted.append(record)

    ledger: list[dict[str, Any]] = []
    ledger_digests: list[str] = []
    for row in attempt_rows:
        (
            seq,
            outcome,
            attempted_at,
            scheduled_at,
            slot_index,
            interval_s,
            monotonic_s,
            record_id,
            dup_key,
            reason,
            persistence_ok,
            deferred,
            gap_slots,
            payload_json,
        ) = row
        extra: dict[str, Any] = {}
        try:
            parsed = json.loads(payload_json) if payload_json else {}
            if isinstance(parsed, dict) and isinstance(parsed.get("extra"), dict):
                extra = parsed["extra"]
        except ValueError:
            extra = {}
        entry = {
            "seq": seq,
            "outcome": outcome,
            "attempted_at": attempted_at,
            "scheduled_at": scheduled_at,
            "slot_index": slot_index,
            "interval_s": interval_s,
            "monotonic_s": monotonic_s,
            "record_id": record_id,
            "dup_key": dup_key,
            "reason": reason,
            "persistence_ok": None if persistence_ok is None else bool(persistence_ok),
            "deferred": bool(deferred),
            "gap_slots": gap_slots,
            "extra": extra,
        }
        ledger.append(entry)
        ledger_digests.append(_sha256(entry))

    meta_sanitized, redacted_keys = _research_meta(meta)
    counts: dict[str, int] = {}
    for entry in ledger:
        counts[str(entry["outcome"])] = counts.get(str(entry["outcome"]), 0) + 1
    stored_ids = [str(e["record_id"]) for e in ledger if e["outcome"] == "STORED" and e["record_id"]]

    reconciliation = {
        "accepted_rows": len(accepted),
        "distinct_accepted_ids": len(identities),
        "ledger_rows": len(ledger),
        "counts_by_outcome": counts,
        "stored_ledger_ids": len(set(stored_ids)),
        "store_rows_without_ledger_entry": sorted(identities - set(stored_ids)),
        "ledger_entries_without_store_row": sorted(set(stored_ids) - identities),
        "ledger_store_agreement": (len(identities) == len(set(stored_ids)))
        and not (identities - set(stored_ids))
        and not (set(stored_ids) - identities),
    }

    run_metadata = meta_sanitized.get("run_metadata") if isinstance(meta_sanitized, dict) else None
    offset_values = {
        float(entry["extra"]["server_utc_offset_s"])
        for entry in ledger
        if isinstance(entry.get("extra"), dict) and entry["extra"].get("server_utc_offset_s") is not None
    }
    basis_values = {
        str(entry["extra"]["offset_basis"])
        for entry in ledger
        if isinstance(entry.get("extra"), dict) and entry["extra"].get("offset_basis") is not None
    }
    first_seen: dict[float, str] = {}
    last_seen: dict[float, str] = {}
    for entry in ledger:
        entry_extra = entry.get("extra") if isinstance(entry, dict) else None
        if not isinstance(entry_extra, dict) or entry_extra.get("server_utc_offset_s") is None:
            continue
        offset = float(entry_extra["server_utc_offset_s"])
        stamp = entry.get("attempted_at") or ""
        if stamp:
            first_seen.setdefault(offset, stamp)
            last_seen[offset] = stamp
    clock_history = {
        "distinct_offsets": len(offset_values),
        "offset_changed_mid_session": len(offset_values) > 1,
        "offsets": [
            {
                "server_utc_offset_s": offset,
                "first_seen_at": first_seen.get(offset),
                "last_seen_at": last_seen.get(offset),
            }
            for offset in sorted(offset_values)
        ],
        "basis_values": sorted(basis_values),
        "measurement_time": {
            "status": "UNAVAILABLE",
            "value": None,
            "reason": "the adapter exposes the offset and its basis, not the measurement timestamp",
        },
    }

    artifact: dict[str, Any] = {
        "snapshot": RESEARCH_SNAPSHOT_VERSION,
        "exported_at": datetime.now(UTC).isoformat(),
        "exporter_code_version": code_version(),
        "export_scope": (
            "ONE observe-only session: every accepted tick payload in full, the complete acquisition "
            "ledger, session metadata and run/clock identity — not a sample"
        ),
        "schema": {
            "snapshot_version": RESEARCH_SNAPSHOT_VERSION,
            "source_tables": ["observation_sessions", "observation_ticks", "observation_attempts"],
            "canonical_store": str(db_path),
            "row_fields": [
                "i",
                "id",
                "created_at",
                "provenance",
                "session_id",
                "symbol",
                "event_time",
                "payload",
                "sha256",
            ],
        },
        "code_identity": {
            "package_version": code_version(),
            "session_code_version": meta_sanitized.get("code_version"),
        },
        "config_identity": (run_metadata or {}).get("config") if isinstance(run_metadata, dict) else None,
        "run_metadata": run_metadata,
        "session": {
            "id": sid,
            "status": status,
            "start": start,
            "end": end or None,
            "meta_sanitized": meta_sanitized,
            "meta_redacted_keys": sorted(redacted_keys),
        },
        "accepted": {
            "count": len(accepted),
            "rows": accepted,
            "row_digest_root": _chain(sid, digests),
        },
        "ledger": {
            "count": len(ledger),
            "counts_by_outcome": counts,
            "rows": ledger,
            "row_digest_root": _chain(sid, ledger_digests),
        },
        "reconciliation": reconciliation,
        "clock": {
            "broker_offset_history": clock_history,
            "normalization_rule": (
                "event_time = broker_stamp - measured_server_offset (single application, true UTC = system clock)"
            ),
        },
        "privacy": {
            "credentials_included": False,
            "machine_paths_included": False,
            "redaction": "session meta allowlisted; credential-shaped keys redacted; logins masked",
        },
        "verification_limits": (
            "Proves this snapshot is internal-consistent, complete for the declared session and unmodified "
            "since export. It does not prove the store was produced by a real MT5 terminal, does not "
            "authenticate the exporter, and does not make the data promotion- or LIVE-grade evidence."
        ),
    }
    artifact["integrity"] = {
        "algorithm": "sha256",
        "accepted_row_digest_root": artifact["accepted"]["row_digest_root"],
        "ledger_row_digest_root": artifact["ledger"]["row_digest_root"],
        "manifest_hash": _snapshot_manifest_hash(artifact),
    }
    return artifact


def _snapshot_manifest_hash(artifact: dict[str, Any]) -> str:
    """Hash over the declared content identity (not the generated timestamp)."""
    body = {
        "snapshot": artifact.get("snapshot"),
        "session_id": (artifact.get("session") or {}).get("id"),
        "accepted": artifact.get("accepted", {}).get("row_digest_root"),
        "ledger": artifact.get("ledger", {}).get("row_digest_root"),
        "accepted_count": artifact.get("accepted", {}).get("count"),
        "ledger_count": artifact.get("ledger", {}).get("count"),
        "schema": artifact.get("schema", {}).get("snapshot_version"),
    }
    return _sha256(body)


def write_research_snapshot(
    session_id: str,
    *,
    db_path: Path | str = "data/sqlite/forward_observatory.db",
    out_path: Path | str | None = None,
) -> tuple[dict[str, Any], Path]:
    """Export + persist the research snapshot. Returns (artifact, path)."""
    artifact = export_research_snapshot(session_id, db_path=db_path)
    path = Path(out_path) if out_path else Path("data/evidence/exports") / f"{session_id}.research_snapshot.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, indent=2, default=str) + "\n", encoding="utf-8")
    return artifact, path


# -------------------------------------------------------------------- verify


def _fail(violations: list[str]) -> dict[str, Any]:
    return {
        "verdict": "REFUSED",
        "snapshot": RESEARCH_SNAPSHOT_VERSION,
        "violations": violations,
        "verification_limits": (
            "Artifact-only verification: proves internal consistency, declared completeness and integrity. "
            "It cannot prove Desktop origin, exporter authenticity or terminal reality."
        ),
    }


def verify_research_snapshot(artifact: Any) -> dict[str, Any]:
    """Independently verify a research snapshot. Never mutates its input."""
    violations: list[str] = []

    def check(condition: Any, message: str) -> None:
        if not condition:
            violations.append(message)

    if not isinstance(artifact, dict):
        return _fail(["artifact is not an object"])
    check(artifact.get("snapshot") == RESEARCH_SNAPSHOT_VERSION, "unknown snapshot version")

    session = artifact.get("session")
    check(isinstance(session, dict), "session: expected object")
    if not isinstance(session, dict):
        return _fail(violations)
    raw_sid = session.get("id")
    check(
        isinstance(raw_sid, str) and _SESSION_ID_RE.fullmatch(raw_sid or "") is not None,
        "session.id not canonical FS-<6 hex>",
    )
    sid: str = raw_sid if isinstance(raw_sid, str) else ""
    check(session.get("status") in ("ACTIVE", "ENDED", "ENDED_ON_ERRORS"), "unexpected session status")

    meta = session.get("meta_sanitized")
    check(isinstance(meta, dict), "session.meta_sanitized: expected object")
    if isinstance(meta, dict):
        check(meta.get("orders_possible") is False, "orders_possible must be false for an observe-only session")
        for key, value in meta.items():
            if _CREDENTIAL_KEY_RE.search(str(key)):
                check(value == "<REDACTED>", f"credential-shaped meta key {key!r} not redacted")
            elif "login" in str(key).lower():
                check(
                    isinstance(value, str) and re.fullmatch(r"\*{4}(?:.{0,2})", value) is not None,
                    f"login-shaped meta key {key!r} not masked",
                )
            elif key not in _RESEARCH_META_ALLOWLIST:
                check(value == "<REDACTED:non-allowlisted>", f"non-allowlisted meta key {key!r} not redacted")

    if isinstance(meta, dict) and session.get("status") == "ENDED":
        check("error" not in meta, "ENDED session declares a terminal error")
    if isinstance(meta, dict) and session.get("status") == "ENDED_ON_ERRORS":
        check(bool(meta.get("error")), "ENDED_ON_ERRORS session declares no terminal error")

    run_metadata = artifact.get("run_metadata")
    check(run_metadata is None or isinstance(run_metadata, dict), "run_metadata: expected object or null")
    if isinstance(run_metadata, dict):
        check(
            run_metadata.get("version", "").startswith("qts.run_metadata."),
            "run_metadata.version missing or unknown",
        )
        config = run_metadata.get("config")
        check(isinstance(config, dict), "run_metadata.config: expected object")
        if isinstance(config, dict):
            expected = {k: v for k, v in config.items() if k != "hash"}
            check(config.get("hash") == _sha256(expected), "run_metadata.config.hash contradicts config content")
        check(
            (run_metadata.get("privacy") or {}).get("credentials_persisted") is False,
            "run_metadata.privacy must declare no credentials persisted",
        )
        for label, value in (run_metadata.get("broker_identity") or {}).items():
            if isinstance(value, dict) and "status" in value:
                check(
                    value["status"] in _UNAVAILABLE_STATUSES,
                    f"broker_identity.{label} has an unknown status",
                )
                check(
                    value["status"] != "UNAVAILABLE" or bool(value.get("reason")),
                    f"broker_identity.{label} is UNAVAILABLE without a reason",
                )

    accepted = artifact.get("accepted")
    ledger = artifact.get("ledger")
    check(isinstance(accepted, dict), "accepted: expected object")
    check(isinstance(ledger, dict), "ledger: expected object")
    if not isinstance(accepted, dict) or not isinstance(ledger, dict):
        return _fail(violations)

    rows = accepted.get("rows")
    check(isinstance(rows, list), "accepted.rows: expected list")
    rows = rows if isinstance(rows, list) else []
    check(accepted.get("count") == len(rows), "accepted.count contradicts accepted.rows")
    digests: list[str] = []
    ids: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            violations.append(f"accepted row {index}: expected object")
            continue
        check(row.get("i") == index, f"accepted row {index}: index gap or reorder")
        payload = row.get("payload")
        check(isinstance(payload, dict), f"accepted row {index}: payload missing or not an object")
        if isinstance(payload, dict):
            check(
                row.get("sha256") == _row_digest(payload),
                f"accepted row {index}: sha256 does not match its payload (tampered or corrupted)",
            )
            check(
                payload.get("session_id") == sid,
                f"accepted row {index}: payload session_id contradicts session identity",
            )
            check(
                payload.get("provenance") in _ALLOWED_PROVENANCE,
                f"accepted row {index}: unexpected provenance class {payload.get('provenance')!r}",
            )
            check(payload.get("id") == row.get("id"), f"accepted row {index}: payload id contradicts row id")
        rid = row.get("id")
        if rid in ids:
            violations.append(f"accepted row {index}: duplicate record identity {rid!r}")
        ids.add(str(rid))
        digests.append(str(row.get("sha256")))
    check(accepted.get("row_digest_root") == _chain(sid, digests), "accepted row digest root mismatch")

    ledger_rows = ledger.get("rows")
    check(isinstance(ledger_rows, list), "ledger.rows: expected list")
    ledger_rows = ledger_rows if isinstance(ledger_rows, list) else []
    check(ledger.get("count") == len(ledger_rows), "ledger.count contradicts ledger.rows")
    ledger_digests: list[str] = []
    seqs: set[int] = set()
    counts: dict[str, int] = {}
    stored_ids: set[str] = set()
    for index, entry in enumerate(ledger_rows):
        if not isinstance(entry, dict):
            violations.append(f"ledger row {index}: expected object")
            continue
        outcome = entry.get("outcome")
        check(outcome in _LEDGER_OUTCOMES, f"ledger row {index}: unknown outcome {outcome!r}")
        counts[str(outcome)] = counts.get(str(outcome), 0) + 1
        seq = entry.get("seq")
        check(isinstance(seq, int), f"ledger row {index}: seq must be an integer")
        if isinstance(seq, int):
            if seq in seqs:
                violations.append(f"ledger row {index}: duplicate sequence {seq}")
            seqs.add(seq)
        if outcome == "STORED":
            check(entry.get("persistence_ok") is True, f"ledger row {index}: STORED without persistence_ok")
            if entry.get("record_id"):
                stored_ids.add(str(entry["record_id"]))
        if outcome in ("STORAGE_ERROR", "UNRESOLVED"):
            check(bool(entry.get("reason")), f"ledger row {index}: {outcome} requires a structured reason")
        ledger_digests.append(_sha256(dict(entry)))
    check(ledger.get("row_digest_root") == _chain(sid, ledger_digests), "ledger row digest root mismatch")
    check(ledger.get("counts_by_outcome", counts) == counts, "ledger.counts_by_outcome contradicts ledger rows")

    reconciliation = artifact.get("reconciliation")
    check(isinstance(reconciliation, dict), "reconciliation: expected object")
    if isinstance(reconciliation, dict):
        check(reconciliation.get("accepted_rows") == len(rows), "reconciliation.accepted_rows contradicts accepted")
        check(reconciliation.get("ledger_rows") == len(ledger_rows), "reconciliation.ledger_rows contradicts ledger")
        check(
            reconciliation.get("ledger_store_agreement") is True,
            "reconciliation declares ledger/store disagreement",
        )
        check(
            not reconciliation.get("store_rows_without_ledger_entry"),
            "accepted rows exist without a ledger entry",
        )
        check(
            not reconciliation.get("ledger_entries_without_store_row"),
            "ledger entries reference rows absent from the snapshot",
        )
        check(len(ids) == len(rows), "duplicate record identity in accepted rows")
        check(len(stored_ids) == len(rows), "accepted row count contradicts STORED ledger entries")

    integrity = artifact.get("integrity")
    check(isinstance(integrity, dict), "integrity: expected object")
    if isinstance(integrity, dict):
        check(integrity.get("algorithm") == "sha256", "integrity algorithm must be sha256")
        check(
            integrity.get("accepted_row_digest_root") == accepted.get("row_digest_root"),
            "integrity/accepted root mismatch",
        )
        check(
            integrity.get("ledger_row_digest_root") == ledger.get("row_digest_root"), "integrity/ledger root mismatch"
        )
        check(integrity.get("manifest_hash") == _snapshot_manifest_hash(artifact), "manifest hash mismatch")

    if violations:
        return _fail(violations)
    return {
        "verdict": "CONSISTENT",
        "snapshot": RESEARCH_SNAPSHOT_VERSION,
        "session_id": sid,
        "status": session.get("status"),
        "accepted_rows": len(rows),
        "ledger_rows": len(ledger_rows),
        "counts_by_outcome": counts,
        "accepted_row_digest_root": accepted.get("row_digest_root"),
        "ledger_row_digest_root": ledger.get("row_digest_root"),
        "violations": [],
        "notes": [
            "complete accepted payloads and the full acquisition ledger are bound by ordered hash chains",
            "this proves internal consistency, declared completeness and integrity — not terminal reality",
        ],
        "verification_limits": artifact.get("verification_limits"),
    }


def _reject_json_constant(constant: str) -> Any:
    """Reject NaN/Infinity: a research snapshot carries no non-finite numbers."""
    raise ValueError(f"non-finite JSON constant {constant!r}")


def verify_research_snapshot_file(path: Path | str) -> dict[str, Any]:
    """Load + verify a snapshot file (fail-closed on unreadable/malformed JSON)."""
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError as e:
        return _fail([f"snapshot unreadable: {type(e).__name__}: {e}"])
    try:
        artifact = json.loads(raw, parse_constant=_reject_json_constant)
    except ValueError as e:
        return _fail([f"snapshot is not valid JSON: {e}"])
    return verify_research_snapshot(artifact)
