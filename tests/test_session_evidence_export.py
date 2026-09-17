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
        broker_event_time=datetime.fromtimestamp(base - offset, tz=UTC),  # true UTC
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
