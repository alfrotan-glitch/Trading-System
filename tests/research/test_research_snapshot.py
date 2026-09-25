"""Research snapshot contract — ``qts.research_snapshot.v1``.

Pins the FO-R1 dataset contract:

* the snapshot carries the COMPLETE accepted payloads of one session, the full
  acquisition ledger, run/clock identity and schema/code identity;
* it verifies independently (internal consistency, declared completeness,
  ledger/store agreement, hash integrity) and REFUSES every contradiction:
  missing rows, inconsistent counts, ledger/store disagreement, payload/hash
  disagreement, session mismatch, provenance mismatch, identity conflicts and
  malformed metadata;
* it never carries credentials, secrets or machine paths;
* it is a SEPARATE contract — ``qts.session_evidence.v1`` and its verifier are
  untouched and still pass on the same session.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from test_observe_only_collector import (
    PASSED_READINESS,
    LiveFakeMT5,
    _make_collector,
    _wait_for,
)

from qts.observability.forward_observatory import ForwardObservatory, ObservationTick
from qts.observability.research_snapshot import (
    RESEARCH_SNAPSHOT_VERSION,
    ResearchSnapshotError,
    export_research_snapshot,
    verify_research_snapshot,
    verify_research_snapshot_file,
    write_research_snapshot,
)
from qts.observability.session_export import export_session_evidence, verify_session_export


def _config_hash(config: dict[str, Any]) -> str:
    """The documented run-metadata config hash (canonical JSON -> sha256)."""
    import hashlib

    body = json.dumps(config, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


@pytest.fixture()
def collected(tmp_path: Path) -> tuple[Any, dict[str, Any]]:
    """A real observe-only session with a few accepted ticks + a ledger."""
    collector, _ = _make_collector(tmp_path, LiveFakeMT5("live"), interval_s=0.2, manifest_every_ticks=3)
    collector.start(PASSED_READINESS)
    assert _wait_for(lambda: collector.ticks_recorded >= 4), collector.last_error
    stopped = collector.stop()
    artifact = export_research_snapshot(stopped["session_id"], db_path=collector.observatory.db_path)
    return collector, artifact


# ------------------------------------------------------------------ generation


def test_snapshot_contains_the_complete_dataset_and_verifies(collected: tuple[Any, dict[str, Any]]) -> None:
    collector, art = collected
    assert art["snapshot"] == RESEARCH_SNAPSHOT_VERSION

    rows = art["accepted"]["rows"]
    assert art["accepted"]["count"] == len(rows) == collector.ticks_recorded >= 4
    # FULL payloads, not samples: every row carries its complete stored payload.
    for row in rows:
        payload = row["payload"]
        assert {"id", "symbol", "bid", "ask", "provenance", "broker_event_time", "timestamp_basis"} <= set(payload)
        assert payload["provenance"] == "DEMO"
        assert row["sha256"]

    # The acquisition ledger travels with the dataset.
    outcomes = art["ledger"]["counts_by_outcome"]
    assert outcomes.get("SESSION_START") == 1 and outcomes.get("STORED") == art["accepted"]["count"]
    assert art["reconciliation"]["ledger_store_agreement"] is True
    assert art["ledger"]["rows"][0]["outcome"] == "SESSION_START"

    # Run/clock identity is bound for reproducibility.
    run = art["run_metadata"]
    assert run["version"].startswith("qts.run_metadata.")
    assert run["code"]["git_commit"]
    assert run["config"]["hash"] and run["config"]["collector_policy"]["interval_s"] == 0.2
    assert art["config_identity"]["hash"] == run["config"]["hash"]
    assert art["clock"]["broker_offset_history"]["basis_values"] == ["measured-m1-bar"]
    assert art["clock"]["broker_offset_history"]["distinct_offsets"] == 1
    assert art["schema"]["snapshot_version"] == RESEARCH_SNAPSHOT_VERSION
    assert art["integrity"]["manifest_hash"]

    report = verify_research_snapshot(art)
    assert report["verdict"] == "CONSISTENT", report
    assert report["accepted_rows"] == art["accepted"]["count"]
    assert report["violations"] == []


def test_snapshot_and_v1_are_separate_contracts(collected: tuple[Any, dict[str, Any]]) -> None:
    collector, art = collected
    # v1 is unchanged and still verifies the same session.
    v1 = export_session_evidence(collector.session_id, db_path=collector.observatory.db_path)
    assert v1["artifact"] == "qts.session_evidence.v1"
    assert verify_session_export(v1)["verdict"] == "CONSISTENT"
    # The research snapshot is a different, richer contract.
    assert art["snapshot"] != v1["artifact"]
    assert len(art["accepted"]["rows"]) == v1["counters"]["tick_count"]
    assert "ledger" in art and "ledger" not in v1


def test_snapshot_verification_never_mutates_its_input(collected: tuple[Any, dict[str, Any]]) -> None:
    _, art = collected
    before = copy.deepcopy(art)
    assert verify_research_snapshot(art) == verify_research_snapshot(art)
    assert art == before


# ------------------------------------------------------------------ fail-closed


def test_snapshot_refuses_a_missing_row(collected: tuple[Any, dict[str, Any]]) -> None:
    _, art = collected
    art["accepted"]["rows"].pop()
    report = verify_research_snapshot(art)
    assert report["verdict"] == "REFUSED"
    assert any("accepted.count contradicts" in v for v in report["violations"])


def test_snapshot_refuses_inconsistent_counts(collected: tuple[Any, dict[str, Any]]) -> None:
    _, art = collected
    art["accepted"]["count"] += 1
    assert verify_research_snapshot(art)["verdict"] == "REFUSED"


def test_snapshot_refuses_ledger_store_disagreement(collected: tuple[Any, dict[str, Any]]) -> None:
    _, art = collected
    art["reconciliation"]["ledger_store_agreement"] = False
    report = verify_research_snapshot(art)
    assert report["verdict"] == "REFUSED"
    assert any("ledger/store disagreement" in v for v in report["violations"])


def test_snapshot_refuses_payload_hash_disagreement(collected: tuple[Any, dict[str, Any]]) -> None:
    _, art = collected
    art["accepted"]["rows"][0]["payload"]["bid"] = "9999.99"  # tamper the dataset
    report = verify_research_snapshot(art)
    assert report["verdict"] == "REFUSED"
    assert any("does not match its payload" in v for v in report["violations"])


def test_snapshot_refuses_rehashed_payload_without_root(collected: tuple[Any, dict[str, Any]]) -> None:
    """Re-hashing one row still breaks the chain root — the dataset is bound."""
    _, art = collected
    row = art["accepted"]["rows"][0]
    row["payload"]["bid"] = "9999.99"
    import hashlib

    canonical = json.dumps(row["payload"], sort_keys=True, separators=(",", ":"), default=str)
    row["sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    report = verify_research_snapshot(art)
    assert report["verdict"] == "REFUSED"
    assert any("digest root mismatch" in v for v in report["violations"])


def test_snapshot_refuses_session_mismatch(collected: tuple[Any, dict[str, Any]]) -> None:
    _, art = collected
    art["accepted"]["rows"][0]["payload"]["session_id"] = "FS-000000"
    report = verify_research_snapshot(art)
    assert report["verdict"] == "REFUSED"
    assert any("session_id contradicts" in v for v in report["violations"])


def test_snapshot_refuses_provenance_mismatch(collected: tuple[Any, dict[str, Any]]) -> None:
    _, art = collected
    art["accepted"]["rows"][0]["payload"]["provenance"] = "SYNTHETIC"
    report = verify_research_snapshot(art)
    assert report["verdict"] == "REFUSED"
    assert any("provenance" in v for v in report["violations"])


def test_snapshot_refuses_identity_conflicts(collected: tuple[Any, dict[str, Any]]) -> None:
    _, art = collected
    art["accepted"]["rows"][1]["id"] = art["accepted"]["rows"][0]["id"]
    art["accepted"]["rows"][1]["payload"]["id"] = art["accepted"]["rows"][0]["payload"]["id"]
    report = verify_research_snapshot(art)
    assert report["verdict"] == "REFUSED"
    assert any("duplicate record identity" in v for v in report["violations"])


def test_snapshot_refuses_ledger_sequence_conflicts(collected: tuple[Any, dict[str, Any]]) -> None:
    _, art = collected
    art["ledger"]["rows"][1]["seq"] = art["ledger"]["rows"][0]["seq"]
    assert verify_research_snapshot(art)["verdict"] == "REFUSED"


@pytest.mark.parametrize(
    "mutate,expected",
    [
        (lambda a: a["run_metadata"]["config"].update({"hash": "0" * 64}), "config.hash contradicts"),
        (lambda a: a["session"]["meta_sanitized"].update({"mt5_password": "hunter2"}), "not redacted"),
        (lambda a: a["session"]["meta_sanitized"].update({"some_unknown_key": "secret"}), "not redacted"),
        (
            lambda a: a["run_metadata"]["broker_identity"].update({"server": {"status": "MAYBE", "value": "x"}}),
            "unknown status",
        ),
        (
            lambda a: a["run_metadata"]["broker_identity"].update({"server": {"status": "UNAVAILABLE"}}),
            "without a reason",
        ),
        (
            lambda a: a["reconciliation"].update({"store_rows_without_ledger_entry": ["OT-ghost"]}),
            "without a ledger entry",
        ),
        (lambda a: a.update({"snapshot": "qts.research_snapshot.v2"}), "unknown snapshot version"),
        (
            lambda a: a["session"].update(
                {"status": "ENDED", "meta_sanitized": {"orders_possible": False, "error": "boom"}}
            ),
            "ENDED session",
        ),
    ],
)
def test_snapshot_refuses_malformed_metadata(collected: tuple[Any, dict[str, Any]], mutate: Any, expected: str) -> None:
    _, art = collected
    mutate(art)
    report = verify_research_snapshot(art)
    assert report["verdict"] == "REFUSED"
    assert any(expected in v for v in report["violations"]), report["violations"]


def test_snapshot_refuses_incomplete_run_metadata(collected: tuple[Any, dict[str, Any]]) -> None:
    """A present run-identity block must be complete — partial identity is refused."""
    _, art = collected
    art["run_metadata"] = {"version": "qts.run_metadata.v1"}
    report = verify_research_snapshot(art)
    assert report["verdict"] == "REFUSED"
    assert any("run_metadata.config" in v for v in report["violations"])
    # ...while a session that predates the run-identity contract (null) still verifies.
    art["run_metadata"] = None
    assert verify_research_snapshot(art)["verdict"] == "CONSISTENT"


def test_snapshot_refuses_order_bearing_metadata(collected: tuple[Any, dict[str, Any]]) -> None:
    _, art = collected
    art["session"]["meta_sanitized"]["orders_possible"] = True
    report = verify_research_snapshot(art)
    assert report["verdict"] == "REFUSED"
    assert any("orders_possible" in v for v in report["violations"])


# --------------------------------------------------------------- privacy/IO


def test_snapshot_excludes_credentials_and_machine_identity(tmp_path: Path) -> None:
    observatory = ForwardObservatory(db_path=tmp_path / "obs.db")
    sid = observatory.start_session(
        meta={
            "kind": "LIVE_OBSERVATION",
            "orders_possible": False,
            "broker_symbol": "XAUUSD@",
            "mt5_password": "hunter2",
            "api_token": "abc123",
            "login": "87654321",
            "terminal_path": "C:\\Users\\operator\\MT5\\terminal64.exe",
            "run_metadata": {
                "version": "qts.run_metadata.v1",
                "config": {
                    "collector_policy": {"interval_s": 1.0},
                    "hash": _config_hash({"collector_policy": {"interval_s": 1.0}}),
                },
                "privacy": {"credentials_persisted": False},
                "broker_identity": {"server": {"status": "AVAILABLE", "value": "WMMarkets-Demo"}},
            },
        }
    )
    observatory.end_session(sid)
    art = export_research_snapshot(sid, db_path=observatory.db_path)

    meta = art["session"]["meta_sanitized"]
    assert meta["mt5_password"] == "<REDACTED>"
    assert meta["api_token"] == "<REDACTED>"
    assert meta["login"] == "****21"  # masked, never the full login
    assert meta["terminal_path"] == "<REDACTED:non-allowlisted>"  # machine path not transferred
    assert set(art["session"]["meta_redacted_keys"]) >= {"mt5_password", "api_token", "terminal_path"}
    blob = json.dumps(art).lower()
    for leak in ("hunter2", "abc123", "87654321", "c:\\\\users", "/home/", "terminal64.exe"):
        assert leak not in blob, f"artifact leaked {leak!r}"
    assert art["privacy"]["credentials_included"] is False
    assert verify_research_snapshot(art)["verdict"] == "CONSISTENT"


def test_snapshot_file_roundtrip_and_malformed_input(tmp_path: Path, collected: tuple[Any, dict[str, Any]]) -> None:
    collector, _ = collected
    art, path = write_research_snapshot(
        collector.session_id, db_path=collector.observatory.db_path, out_path=tmp_path / "snap.json"
    )
    assert path.exists()
    report = verify_research_snapshot_file(path)
    assert report["verdict"] == "CONSISTENT", report

    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert verify_research_snapshot_file(bad)["verdict"] == "REFUSED"

    nonfinite = tmp_path / "nan.json"
    nonfinite.write_text('{"snapshot": "qts.research_snapshot.v1", "count": NaN}', encoding="utf-8")
    assert verify_research_snapshot_file(nonfinite)["verdict"] == "REFUSED"

    missing = tmp_path / "nope.json"
    assert verify_research_snapshot_file(missing)["verdict"] == "REFUSED"


def test_snapshot_refuses_unknown_session_and_unparseable_meta(tmp_path: Path) -> None:
    observatory = ForwardObservatory(db_path=tmp_path / "obs.db")
    with pytest.raises(ResearchSnapshotError):
        export_research_snapshot("FS-abcdef", db_path=observatory.db_path)

    sid = observatory.start_session(meta={"orders_possible": False})
    from qts.db import connect as db_connect

    with db_connect(observatory.db_path) as con:
        con.execute("UPDATE observation_sessions SET meta='{not json' WHERE id=?", (sid,))
        con.commit()
    with pytest.raises(ResearchSnapshotError):
        export_research_snapshot(sid, db_path=observatory.db_path)


def test_snapshot_refuses_store_without_canonical_tables(tmp_path: Path) -> None:
    from qts.db import connect as db_connect

    empty = tmp_path / "empty.db"
    with db_connect(empty) as con:
        con.execute("CREATE TABLE unrelated (x TEXT)")
        con.commit()
    with pytest.raises(ResearchSnapshotError):
        export_research_snapshot("FS-abcdef", db_path=empty)


def test_snapshot_of_a_long_session_stays_complete(tmp_path: Path) -> None:
    """Completeness holds at scale: every accepted row is bound, none sampled."""
    observatory = ForwardObservatory(db_path=tmp_path / "obs.db")
    sid = observatory.start_session(meta={"orders_possible": False, "broker_symbol": "XAUUSD@"})
    from datetime import UTC, datetime
    from decimal import Decimal

    ticks = []
    for i in range(150):
        tick = ObservationTick(
            symbol="XAUUSD@",
            bid=Decimal("2000.0") + Decimal(i) / 100,
            ask=Decimal("2000.5") + Decimal(i) / 100,
            provenance="DEMO",
            broker_event_time=datetime.now(UTC),
            broker_time_raw=1_750_000_000.0 + i,
            server_utc_offset_s=10800.0,
            timestamp_basis="broker-normalized(measured-m1-bar)",
            tick_provenance={"mt5_time": 1_750_000_000.0 + i, "mt5_time_msc": (1_750_000_000.0 + i) * 1000},
            session_id=sid,
        )
        observatory.record_tick(tick)
        ticks.append(tick)
        observatory.record_attempt(
            sid,
            i + 1,
            outcome="STORED",
            attempted_at=datetime.now(UTC).isoformat(),
            slot_index=i,
            record_id=tick.id,
            persistence_ok=True,
        )
    observatory.end_session(sid)

    art = export_research_snapshot(sid, db_path=observatory.db_path)
    assert art["accepted"]["count"] == 150
    assert {r["payload"]["id"] for r in art["accepted"]["rows"]} == {t.id for t in ticks}
    assert art["ledger"]["counts_by_outcome"]["STORED"] == 150
    assert verify_research_snapshot(art)["verdict"] == "CONSISTENT"
