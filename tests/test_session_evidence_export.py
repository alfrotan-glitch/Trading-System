"""Session-evidence export/verify — the Desktop -> auditable-artifact boundary.

Pins the Phase-2 evidence contract:

* Export recomputes every counter from the canonical SQLite store (never
  in-memory state), sanitizes session meta (allowlist + credential redaction),
  and binds every tick to a sha256 digest + ordered hash chain.
* Verify recomputes the chain and all structural contracts from the artifact
  alone, REFUSES tampered/contaminated/order-bearing artifacts, and states
  its own verification limits (it never proves Desktop origin by itself).
* Order-freedom, duplicate handling, timestamp-basis, and provenance-class
  contracts are all enforced.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from qts.observability.forward_observatory import ForwardObservatory, ObservationTick
from qts.observability.session_export import (
    ARTIFACT_VERSION,
    SessionExportError,
    export_session_evidence,
    verify_session_export,
    write_session_evidence,
)


def _demo_tick(i: int, symbol: str = "XAUUSD@") -> ObservationTick:
    """A collector-shaped DEMO tick with full broker-timestamp provenance."""
    base = 1_750_000_000.0 + i
    offset = 10800.0  # +3h, on the 15-minute grid
    t = ObservationTick(
        symbol=symbol,
        bid=Decimal("2000.0") + Decimal(i) / 10,
        ask=Decimal("2000.5") + Decimal(i) / 10,
        provenance="DEMO",
        broker_event_time=datetime.fromtimestamp(base - offset + 0.007, tz=UTC),  # matches mt5_time_msc below
        broker_time_raw=base,
        server_utc_offset_s=offset,
        timestamp_basis="broker-normalized(measured-m1-bar)",
        tick_provenance={"mt5_time": base, "mt5_time_msc": base * 1000 + 7},
    )
    return t


@pytest.fixture()
def observatory(tmp_path: Path) -> ForwardObservatory:
    return ForwardObservatory(db_path=tmp_path / "fwd.db")


@pytest.fixture()
def session(observatory: ForwardObservatory) -> str:
    sid = observatory.start_session(
        meta={
            "kind": "LIVE_OBSERVATION",
            "mode": "DEMO_FORWARD",
            "environment": "DEMO_FORWARD",
            "canonical_symbol": "XAUUSD",
            "broker_symbol": "XAUUSD@",
            "broker": "MT5",
            "timestamp_basis": "broker-normalized(measured-m1-bar)",
            "code_version": "0.1.0+abc123",
            "orders_possible": False,
        }
    )
    for i in range(12):
        tick = _demo_tick(i)
        tick.session_id = sid
        observatory.record_tick(tick)
    observatory.end_session(sid)
    return sid


# ------------------------------------------------------------------ export


def test_export_recomputes_from_store(session: str, observatory: ForwardObservatory):
    art = export_session_evidence(session, db_path=observatory.db_path)
    assert art["artifact"] == ARTIFACT_VERSION
    assert art["session"]["id"] == session
    assert art["session"]["status"] == "ENDED"
    c = art["counters"]
    assert c["tick_count"] == 12
    assert c["ticks_by_provenance"] == {"DEMO": 12}
    assert c["duplicate_raw_stamps_in_store"] == 0
    assert c["symbols"] == ["XAUUSD@"]
    assert c["monotonic_event_time_violations"] == 0
    assert art["order_free"]["orders_possible_flag"] is False
    assert art["order_free"]["signal_records_for_session"] == 0
    assert len(art["tick_rows"]) == 12
    assert all(r["sha256"] for r in art["tick_rows"])


def test_export_sanitizes_credentials_and_unknown_meta(observatory: ForwardObservatory):
    sid = observatory.start_session(
        meta={
            "kind": "LIVE_OBSERVATION",
            "broker_symbol": "XAUUSD@",
            "orders_possible": False,
            "mt5_password": "hunter2",  # credential-shaped -> redacted
            "api_token": "abc",  # credential-shaped -> redacted
            "some_unknown_key": "value",  # not allowlisted -> redacted
            "login": "12345678",  # login -> masked
        }
    )
    tick = _demo_tick(0)
    tick.session_id = sid
    observatory.record_tick(tick)
    observatory.end_session(sid)
    art = export_session_evidence(sid, db_path=observatory.db_path)
    meta = art["session"]["meta_sanitized"]
    assert meta["mt5_password"] == "<REDACTED>"
    assert meta["api_token"] == "<REDACTED>"
    assert meta["some_unknown_key"] == "<REDACTED:non-allowlisted>"
    assert meta["login"] == "****78"
    # No secret value may leak anywhere in the serialized artifact.
    blob = json.dumps(art)
    assert "hunter2" not in blob
    assert "12345678" not in blob


def test_export_refused_for_unknown_session(observatory: ForwardObservatory):
    with pytest.raises(SessionExportError):
        export_session_evidence("FS-deadbe", db_path=observatory.db_path)


def test_export_refused_when_store_missing(tmp_path: Path):
    with pytest.raises(SessionExportError):
        export_session_evidence("FS-aaaaaa", db_path=tmp_path / "nope.db")


# ------------------------------------------------------------------ verify


def test_verify_consistent_roundtrip(session: str, observatory: ForwardObservatory):
    art = export_session_evidence(session, db_path=observatory.db_path)
    rpt = verify_session_export(art)
    assert rpt["verdict"] == "CONSISTENT", rpt["violations"]
    assert rpt["tick_count"] == 12
    assert "verification_limits" in rpt  # never over-claims Desktop origin


def test_verify_detects_row_tamper(session: str, observatory: ForwardObservatory):
    art = export_session_evidence(session, db_path=observatory.db_path)
    art["tick_rows"][5]["provenance"] = "REAL"  # flip a field without fixing the digest
    rpt = verify_session_export(art)
    assert rpt["verdict"] == "REFUSED"
    assert any("sha256 mismatch" in v for v in rpt["violations"])


def test_verify_detects_row_insertion(session: str, observatory: ForwardObservatory):
    art = export_session_evidence(session, db_path=observatory.db_path)
    extra = dict(art["tick_rows"][0])
    extra["i"] = 999
    art["tick_rows"].append(extra)  # chain length/order broken
    rpt = verify_session_export(art)
    assert rpt["verdict"] == "REFUSED"


def test_verify_detects_synthetic_contamination(observatory: ForwardObservatory):
    sid = observatory.start_session(meta={"broker_symbol": "XAUUSD@", "orders_possible": False})
    good = _demo_tick(0)
    good.session_id = sid
    observatory.record_tick(good)
    bad = _demo_tick(1)
    bad.session_id = sid
    bad.provenance = "SYNTHETIC"  # contamination
    observatory.record_tick(bad)
    observatory.end_session(sid)
    art = export_session_evidence(sid, db_path=observatory.db_path)
    rpt = verify_session_export(art)
    assert rpt["verdict"] == "REFUSED"
    assert any("synthetic contamination" in v for v in rpt["violations"])


def test_verify_detects_persisted_duplicates(observatory: ForwardObservatory):
    sid = observatory.start_session(meta={"broker_symbol": "XAUUSD@", "orders_possible": False})
    for _ in range(2):
        t = _demo_tick(0)  # identical raw stamp twice
        t.session_id = sid
        observatory.record_tick(t)
    observatory.end_session(sid)
    art = export_session_evidence(sid, db_path=observatory.db_path)
    assert art["counters"]["duplicate_raw_stamps_in_store"] == 1
    rpt = verify_session_export(art)
    assert rpt["verdict"] == "REFUSED"
    assert any("duplicate raw broker stamps" in v for v in rpt["violations"])


def test_verify_refuses_when_orders_possible(observatory: ForwardObservatory):
    sid = observatory.start_session(meta={"broker_symbol": "XAUUSD@", "orders_possible": True})
    t = _demo_tick(0)
    t.session_id = sid
    observatory.record_tick(t)
    observatory.end_session(sid)
    art = export_session_evidence(sid, db_path=observatory.db_path)
    rpt = verify_session_export(art)
    assert rpt["verdict"] == "REFUSED"
    assert any("orders_possible" in v for v in rpt["violations"])


def test_verify_detects_symbol_drift(observatory: ForwardObservatory):
    sid = observatory.start_session(meta={"broker_symbol": "XAUUSD@", "orders_possible": False})
    t = _demo_tick(0, symbol="EURUSD")  # wrong symbol recorded
    t.session_id = sid
    observatory.record_tick(t)
    observatory.end_session(sid)
    art = export_session_evidence(sid, db_path=observatory.db_path)
    rpt = verify_session_export(art)
    assert rpt["verdict"] == "REFUSED"
    assert any("symbol drift" in v for v in rpt["violations"])


def test_verify_detects_off_grid_offset(observatory: ForwardObservatory):
    sid = observatory.start_session(meta={"broker_symbol": "XAUUSD@", "orders_possible": False})
    t = _demo_tick(0)
    t.session_id = sid
    t.server_utc_offset_s = 10801.0  # not on the 15-minute grid
    observatory.record_tick(t)
    observatory.end_session(sid)
    art = export_session_evidence(sid, db_path=observatory.db_path)
    rpt = verify_session_export(art)
    assert rpt["verdict"] == "REFUSED"
    assert any("15-minute" in v for v in rpt["violations"])


def test_write_and_verify_file_roundtrip(session: str, observatory: ForwardObservatory, tmp_path: Path):
    art, path = write_session_evidence(session, db_path=observatory.db_path, out_path=tmp_path / "x.json")
    assert path.exists()
    rpt = verify_session_export(path)
    assert rpt["verdict"] == "CONSISTENT", rpt["violations"]
    assert isinstance(art["digest"]["chain_root"], str) and len(art["digest"]["chain_root"]) == 64


def test_cli_evidence_export_and_verify(session: str, observatory: ForwardObservatory, tmp_path: Path, monkeypatch):
    from click.testing import CliRunner

    from qts.cli import main

    monkeypatch.chdir(tmp_path)
    out = tmp_path / "evidence.json"
    runner = CliRunner()
    r = runner.invoke(
        main, ["evidence", "export-session", session, "--db", str(observatory.db_path), "--out", str(out)]
    )
    assert r.exit_code == 0, r.output
    assert out.exists()
    r2 = runner.invoke(main, ["evidence", "verify", str(out)])
    assert r2.exit_code == 0, r2.output
    assert '"verdict": "CONSISTENT"' in r2.output


# ------------------------------------------------------------------ adversarial boundary
# All data below is generated by the local test store, NOT Desktop evidence.


@pytest.fixture()
def artifact(session: str, observatory: ForwardObservatory) -> dict:
    return export_session_evidence(session, db_path=observatory.db_path)


def _put(art: dict, path: str, value) -> None:
    parts = path.split(".")
    target = art
    for part in parts[:-1]:
        target = target[int(part)] if isinstance(target, list) else target[part]
    target[int(parts[-1]) if isinstance(target, list) else parts[-1]] = value


def _rehash(art: dict) -> None:
    """Independent hash math: ensure semantic probes aren't merely checksum failures."""
    import hashlib

    chain = hashlib.sha256(f"qts-session-chain:{art['session']['id']}".encode()).hexdigest()
    for row in art["tick_rows"]:
        body = json.dumps({k: v for k, v in row.items() if k != "sha256"}, sort_keys=True, separators=(",", ":"))
        row["sha256"] = hashlib.sha256(body.encode()).hexdigest()
        chain = hashlib.sha256(f"{chain}:{row['sha256']}".encode()).hexdigest()
    art["digest"]["chain_root"] = chain


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("counters.tick_count", 13),
        ("counters.ticks_by_provenance", {"REAL": 1}),
        ("counters.ticks_by_provenance", {"DEMO": 11}),
        ("counters.ticks_by_provenance", {"DEMO": 12, "REAL": 0}),
        ("counters.symbols", []),
        ("counters.symbols", ["EURUSD"]),
        ("counters.timestamp_bases", {}),
        ("counters.timestamp_bases", {"broker-normalized(measured-m1-bar)": 1}),
        ("counters.server_utc_offsets_s", []),
        ("counters.server_utc_offsets_s", [0]),
        ("counters.first_event_time", "2000-01-01T00:00:00Z"),
        ("counters.last_event_time", None),
        ("counters.monotonic_event_time_violations", 1),
        ("counters.distinct_raw_broker_stamps", 11),
        ("counters.duplicate_raw_stamps_in_store", 1),
        ("counters.signal_records_for_session", 1),
        ("order_free.signal_records_for_session", 1),
        ("order_free.orders_possible_flag", True),
        ("session.meta_sanitized.orders_possible", True),
        ("order_free.order_tables_in_store", ["orders"]),
        ("canonical_store.tables", ["observation_sessions", "observation_signals", "observation_ticks", "orders"]),
        ("canonical_store.tables", ["observation_sessions", "observation_ticks"]),
        ("canonical_store.integrity_check", "corrupt"),
        ("session.meta_sanitized.broker_symbol", "EURUSD"),
        ("session.meta_sanitized.timestamp_basis", "broker-normalized(assumed-utc-fallback)"),
        ("session.meta_sanitized.started_at", "2000-01-01T00:00:00Z"),
        ("session.meta_sanitized.ended_at", "2000-01-01T00:00:00Z"),
        ("session.status", "ACTIVE"),
        ("session.end", None),
        ("session.end", "2000-01-01T00:00:00Z"),
        ("exported_at", "2000-01-01T00:00:00Z"),
        ("digest.algorithm", "sha512"),
        ("digest.row_digest_over", "full payloads"),
        ("digest.chain", "signed"),
        ("digest.chain_root", "0" * 64),
        ("session.meta_redacted_keys", ["not-present"]),
    ],
)
def test_refuses_contradictory_declarations(artifact: dict, path: str, value):
    _put(artifact, path, value)
    verdict = verify_session_export(artifact)
    assert verdict["verdict"] == "REFUSED", (path, verdict)
    assert verdict["violations"]
    assert "operator-attested" in verdict["verification_limits"]


@pytest.mark.parametrize(
    ("key", "value", "reason"),
    [
        ("provenance", "SYNTHETIC", "synthetic contamination"),
        ("provenance", "REAL", "ticks_by_provenance"),
        ("symbol", "EURUSD", "symbol drift"),
        ("timestamp_basis", "broker-normalized(invented)", "unknown timestamp basis"),
        ("timestamp_basis", "broker-normalized(assumed-utc-fallback)", "nonzero offset"),
        ("server_utc_offset_s", 10801, "15-minute"),
        ("server_utc_offset_s", 0, "raw broker seconds"),
        ("broker_time_raw", 1, "raw broker seconds"),
        ("event_time", "2000-01-01T00:00:00Z", "raw broker seconds"),
        ("event_time", "2026-09-17T00:00:00", "timezone-aware"),
        ("receipt_time", "2000-01-01T00:00:00Z", "outside session/export"),
        ("i", True, "row index"),
    ],
)
def test_refuses_rehashed_unsampled_row_contradictions(artifact: dict, key: str, value, reason: str):
    # Index 5 is outside both endpoint samples; a valid hash cannot hide drift.
    artifact["tick_rows"][5][key] = value
    _rehash(artifact)
    result = verify_session_export(artifact)
    assert result["verdict"] == "REFUSED"
    assert reason in result["violations"][0]


def test_recomputes_monotonicity_instead_of_trusting_zero(artifact: dict):
    a, b = artifact["tick_rows"][5:7]
    for key in ("event_time", "broker_time_raw"):
        a[key], b[key] = b[key], a[key]
    _rehash(artifact)
    assert "monotonic_event_time_violations" in verify_session_export(artifact)["violations"][0]
    artifact["counters"]["monotonic_event_time_violations"] = 1
    assert "non-monotonic" in verify_session_export(artifact)["violations"][0]


def test_detects_duplicate_rows_even_with_recomputed_chain(artifact: dict):
    for key in ("event_time", "broker_time_raw"):
        artifact["tick_rows"][6][key] = artifact["tick_rows"][5][key]
    _rehash(artifact)
    assert "duplicate exported" in verify_session_export(artifact)["violations"][0]


@pytest.mark.parametrize("endpoint", ["first", "last"])
@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("broker_event_time", "2000-01-01T00:00:00Z"),
        ("timestamp", "2000-01-01T00:00:00Z"),
        ("broker_time_raw", 0),
        ("server_utc_offset_s", 0),
        ("timestamp_basis", "broker-normalized(assumed-utc-fallback)"),
        ("provenance", "REAL"),
        ("symbol", "EURUSD"),
        ("session_id", "FS-aaaaaa"),
        ("tick_provenance.mt5_time", 0),
        ("tick_provenance.mt5_time_msc", 0),
        ("tick_provenance.server_utc_offset_s", 0),
        ("tick_provenance.broker_symbol", "EURUSD"),
        ("tick_provenance.offset_basis", "assumed-utc-fallback"),
        ("mid", "1"),
        ("spread_bps", 999),
        ("bid", "-1"),
        ("ask", "1"),
        ("bid", "not-a-number"),
    ],
)
def test_refuses_sample_contradictions(artifact: dict, endpoint: str, key: str, value):
    _put(artifact, f"sample_payloads.{endpoint}.0.{key}", value)
    assert verify_session_export(artifact)["verdict"] == "REFUSED"


def test_original_fixture_millisecond_error_is_now_refused(artifact: dict):
    # Previously the fixture used mt5_time_msc=base*1000+7 with event_time=base-offset.
    # Corrected the fixture, not the check: that old contradiction must be rejected.
    artifact["sample_payloads"]["first"][0]["tick_provenance"]["mt5_time_msc"] -= 7
    assert "millisecond stamp" in verify_session_export(artifact)["violations"][0]


def test_sample_reorder_is_refused(artifact: dict):
    artifact["sample_payloads"]["first"].reverse()
    assert verify_session_export(artifact)["verdict"] == "REFUSED"


def test_truncated_samples_are_refused(artifact: dict):
    artifact["sample_payloads"]["last"].pop()
    assert "cardinality" in verify_session_export(artifact)["violations"][0]


def test_overlapping_sample_payloads_must_agree(session: str, observatory: ForwardObservatory):
    art = export_session_evidence(session, db_path=observatory.db_path, samples_each_end=8)
    assert verify_session_export(art)["verdict"] == "CONSISTENT"
    art = json.loads(json.dumps(art))  # on-disk JSON has no shared object references
    # Row 4 appears in first and last. Its id isn't row-hashed but can't disagree.
    art["sample_payloads"]["last"][0]["id"] = "OT-altered"
    assert "overlapping" in verify_session_export(art)["violations"][0]


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("session", []),
        ("counters", []),
        ("digest", []),
        ("order_free", []),
        ("canonical_store", []),
        ("sample_payloads", []),
        ("tick_rows", {}),
        ("tick_rows.0", None),
        ("sample_payloads.first.0", None),
        ("sample_payloads.first.0.tick_provenance", []),
        ("sample_payloads.first", None),
        ("session.meta_sanitized", []),
        ("counters.symbols", {}),
        ("counters.symbols", [None]),
        ("counters.timestamp_bases", []),
        ("counters.server_utc_offsets_s", "10800"),
        ("counters.server_utc_offsets_s", [True]),
        ("counters.tick_count", 12.0),
        ("counters.signal_records_for_session", False),
        ("counters.distinct_raw_broker_stamps", -1),
        ("counters.ticks_by_provenance", {"DEMO": True}),
        ("order_free.orders_possible_flag", 0),
        ("session.meta_sanitized.orders_possible", 0),
        ("order_free.signal_records_for_session", False),
        ("session.meta_sanitized.api_token", 12345),
        ("session.meta_sanitized.login", "12345678"),
        ("session.meta_sanitized.unknown", "unredacted"),
        ("session.start", "not-a-time"),
        ("session.id", "FS-123456\n"),
        ("canonical_store.tables", [1]),
        ("sample_payloads.first.0.bid", "NaN"),
        ("sample_payloads.first.0.mid", "Infinity"),
        ("tick_rows.5.server_utc_offset_s", float("nan")),
        ("tick_rows.5.broker_time_raw", float("inf")),
        ("session.meta_sanitized.error", "inconsistent-with-ENDED"),
    ],
)
def test_malformed_inputs_fail_closed_without_raising(artifact: dict, path: str, value):
    _put(artifact, path, value)
    assert verify_session_export(artifact)["verdict"] == "REFUSED"


@pytest.mark.parametrize(
    "section", ["session", "counters", "digest", "order_free", "canonical_store", "sample_payloads"]
)
def test_every_required_nested_field_is_checked(artifact: dict, section: str):
    import copy

    for field in artifact[section]:
        a = copy.deepcopy(artifact)
        del a[section][field]
        assert verify_session_export(a)["verdict"] == "REFUSED", (section, field)


def test_required_row_fields_and_unknown_fields(artifact: dict):
    import copy

    for field in artifact["tick_rows"][0]:
        a = copy.deepcopy(artifact)
        del a["tick_rows"][0][field]
        if field != "sha256":
            _rehash(a)
        assert verify_session_export(a)["verdict"] == "REFUSED", field
    artifact["tick_rows"][0]["orders_possible"] = True
    _rehash(artifact)
    assert verify_session_export(artifact)["verdict"] == "REFUSED"


@pytest.mark.parametrize("bad", [None, [], 1, True, {"artifact": ARTIFACT_VERSION}])
def test_invalid_top_level(bad):
    assert verify_session_export(bad)["verdict"] == "REFUSED"


@pytest.mark.parametrize("refuse", [False, True])
def test_verifier_is_idempotent_and_never_mutates_input(artifact: dict, refuse: bool):
    import copy

    if refuse:
        artifact["order_free"]["orders_possible_flag"] = True
    before = copy.deepcopy(artifact)
    first = verify_session_export(artifact)
    assert first == verify_session_export(artifact)
    assert artifact == before
    assert len(artifact["sample_payloads"]["first"]) == 5


@pytest.mark.parametrize("n", [0, 1, 5, 8, 12, 20])
def test_positive_configurable_sample_counts(session: str, observatory: ForwardObservatory, n: int):
    art = export_session_evidence(session, db_path=observatory.db_path, samples_each_end=n)
    verdict = verify_session_export(art)
    assert verdict["verdict"] == "CONSISTENT", verdict


@pytest.mark.parametrize("count", [0, 1, 3, 5])
@pytest.mark.parametrize("status", ["ACTIVE", "ENDED", "ENDED_ON_ERRORS"])
def test_positive_empty_short_and_lifecycle_variants(observatory: ForwardObservatory, count: int, status: str):
    sid = observatory.start_session(meta={"orders_possible": False, "broker_symbol": "XAUUSD@"})
    for i in range(count):
        tick = _demo_tick(i)
        tick.session_id = sid
        observatory.record_tick(tick)
    if status != "ACTIVE":
        observatory.end_session(sid, status=status, error="collector failure" if status == "ENDED_ON_ERRORS" else None)
    verdict = verify_session_export(export_session_evidence(sid, db_path=observatory.db_path))
    assert verdict["verdict"] == "CONSISTENT", verdict
    assert bool(verdict["notes"]) == (status != "ENDED")


def test_positive_mixed_allowed_provenance_and_canonical_symbol_alias(artifact: dict):
    # Canonical and broker symbols need not be identical (XAUUSD vs XAUUSD@).
    artifact["tick_rows"][5]["provenance"] = "REAL"
    artifact["counters"]["ticks_by_provenance"] = {"DEMO": 11, "REAL": 1}
    _rehash(artifact)
    assert verify_session_export(artifact)["verdict"] == "CONSISTENT"


def test_positive_sanitized_metadata_can_be_verified(observatory: ForwardObservatory):
    sid = observatory.start_session(
        meta={"orders_possible": False, "api_token": "secret", "login": "123456", "extra": 1}
    )
    observatory.end_session(sid)
    assert verify_session_export(export_session_evidence(sid, db_path=observatory.db_path))["verdict"] == "CONSISTENT"


@pytest.mark.parametrize("mutation", ["duplicate-key", "nan", "wrong-shape", "counter", "bad-utf8"])
def test_cli_malformed_artifacts_exit_one(artifact: dict, tmp_path: Path, mutation: str):
    from click.testing import CliRunner

    from qts.cli import main

    path = tmp_path / "evidence.json"
    text = json.dumps(artifact)
    if mutation == "duplicate-key":
        text = text.replace('"tick_count": 12', '"tick_count": 999, "tick_count": 12')
    elif mutation == "nan":
        text = text.replace('"tick_count": 12', '"tick_count": NaN')
    elif mutation == "wrong-shape":
        text = "[]"
    elif mutation == "counter":
        text = text.replace('"tick_count": 12', '"tick_count": 13')
    path.write_bytes(b"\xff" if mutation == "bad-utf8" else text.encode())
    result = CliRunner().invoke(main, ["evidence", "verify", str(path)])
    assert result.exit_code == 1
    assert json.loads(result.output)["verdict"] == "REFUSED"
    assert "verification_limits" in json.loads(result.output)


def test_dictionary_cycles_refused():
    artifact = {}
    artifact["cycle"] = artifact
    assert verify_session_export(artifact)["verdict"] == "REFUSED"


@pytest.mark.parametrize("raw_kind", ["seconds-only", "zero-ms", "milliseconds-only", "raw-ms"])
def test_positive_adapter_timestamp_fallbacks(observatory: ForwardObservatory, raw_kind: str):
    sid = observatory.start_session(meta={"orders_possible": False, "broker_symbol": "XAUUSD@"})
    tick = _demo_tick(0)
    tick.session_id = sid
    base = 1_750_000_000.0
    tick.server_utc_offset_s = 0
    tick.timestamp_basis = "broker-normalized(assumed-utc-fallback)"
    tick.broker_event_time = datetime.fromtimestamp(base, tz=UTC)
    tick.broker_time_raw = None if raw_kind == "milliseconds-only" else (base * 1000 if raw_kind == "raw-ms" else base)
    tick.tick_provenance = {
        "mt5_time": tick.broker_time_raw,
        "mt5_time_msc": base * 1000 if raw_kind == "milliseconds-only" else (0 if raw_kind == "zero-ms" else None),
        "offset_basis": "assumed-utc-fallback",
        "server_utc_offset_s": 0,
        "broker_symbol": "XAUUSD@",
    }
    observatory.record_tick(tick)
    observatory.end_session(sid)
    verdict = verify_session_export(export_session_evidence(sid, db_path=observatory.db_path))
    assert verdict["verdict"] == "CONSISTENT", verdict


def test_duplicate_sample_record_id(artifact: dict):
    artifact["sample_payloads"]["last"][0]["id"] = artifact["sample_payloads"]["first"][0]["id"]
    assert "duplicate sample record id" in verify_session_export(artifact)["violations"][0]


def test_adapter_receipt_after_observation_receipt(artifact: dict):
    artifact["sample_payloads"]["first"][0]["tick_provenance"]["received_at"] = "2999-01-01T00:00:00Z"
    assert "received_at follows" in verify_session_export(artifact)["violations"][0]


def test_unknown_provenance_fields_refused(artifact: dict):
    artifact["sample_payloads"]["first"][0]["tick_provenance"]["orders_possible"] = True
    assert "unknown fields" in verify_session_export(artifact)["violations"][0]


def test_every_required_top_level_field(artifact: dict):
    import copy

    for field in artifact:
        a = copy.deepcopy(artifact)
        del a[field]
        assert verify_session_export(a)["verdict"] == "REFUSED", field


def test_monotonicity_compares_instants_not_iso_string_sort_order(artifact: dict):
    # Equivalent offsets must not manufacture a time reversal (rows 5/6 aren't sampled).
    from datetime import timedelta, timezone

    for i, offset in ((5, 9), (6, -9)):
        row = artifact["tick_rows"][i]
        row["event_time"] = (
            datetime.fromisoformat(row["event_time"].replace("Z", "+00:00"))
            .astimezone(timezone(timedelta(hours=offset)))
            .isoformat()
        )
    assert artifact["tick_rows"][5]["event_time"] > artifact["tick_rows"][6]["event_time"]
    _rehash(artifact)
    assert verify_session_export(artifact)["verdict"] == "CONSISTENT"


def test_empty_endpoint_lists_cannot_hide_nonempty_rows(artifact: dict):
    artifact["sample_payloads"]["first"] = []
    artifact["sample_payloads"]["last"] = []
    assert "cardinality" in verify_session_export(artifact)["violations"][0]


def test_decimal_arithmetic_overflow_is_refused_not_an_exception(artifact: dict):
    sample = artifact["sample_payloads"]["first"][0]
    sample["bid"] = sample["ask"] = "1e999999999"
    assert verify_session_export(artifact)["verdict"] == "REFUSED"
