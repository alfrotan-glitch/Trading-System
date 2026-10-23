"""Contracts for digest-bound MT5 timestamp-basis evidence."""

from __future__ import annotations

from qts.data.mt5_timestamp_basis import timestamp_basis_assessment, validate_timestamp_basis_evidence


def _manifest() -> dict[str, object]:
    return {
        "schema": "qts.mt5_raw_tick_acquisition.v1",
        "dataset_sha256": "digest-a",
        "timestamp_interpretation_confirmed": False,
    }


def _evidence() -> dict[str, object]:
    return {
        "schema": "qts.mt5_timestamp_basis.v1",
        "status": "MEASURED_SAME_SESSION",
        "read_only": True,
        "orders_submitted": 0,
        "order_send_called": False,
        "historical_api": "copy_ticks_range",
        "historical_time_basis": "UTC",
        "live_time_basis": "SERVER_LOCAL",
        "dataset_sha256s": ["digest-a"],
    }


def test_evidence_unlocks_only_bound_raw_dataset() -> None:
    ok, reason = validate_timestamp_basis_evidence(_evidence(), _manifest())
    assert ok is True
    assert "binds" in reason
    assessment = timestamp_basis_assessment(_manifest(), _evidence())
    assert assessment["status"] == "CONFIRMED"
    assert assessment["session_hour_weekday"] == "UNBLOCKED"
    assert assessment["independent_evidence_confirmation"] is True


def test_unbound_or_non_read_only_evidence_stays_blocked() -> None:
    evidence = _evidence()
    evidence["dataset_sha256s"] = ["other-digest"]
    ok, _ = validate_timestamp_basis_evidence(evidence, _manifest())
    assert ok is False
    evidence["dataset_sha256s"] = ["digest-a"]
    evidence["orders_submitted"] = 1
    assessment = timestamp_basis_assessment(_manifest(), evidence)
    assert assessment["status"] == "BLOCKED"
    assert assessment["session_hour_weekday"] == "BLOCKED"
