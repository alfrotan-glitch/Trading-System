"""Focused P0 lifecycle contracts for the observe-only evidence boundary."""

from __future__ import annotations

import json
from pathlib import Path

from test_observe_only_collector import (
    PASSED_READINESS,
    LiveFakeMT5,
    _make_collector,
    _session_rows,
    _wait_for,
)


def test_demo_identity_readiness_and_authoritative_end_are_exported(tmp_path: Path) -> None:
    collector, _ = _make_collector(tmp_path, LiveFakeMT5("live"))
    collector.start(PASSED_READINESS)
    assert _wait_for(lambda: collector.ticks_recorded >= 1)
    stopped = collector.stop()

    row = _session_rows(tmp_path / "obs.db")[0]
    meta = json.loads(row["meta"])
    assert meta["product_mode"] == "DEMO_FORWARD"
    assert meta["observation_mode"] == "OBSERVE_ONLY"
    assert meta["environment"] == "DEMO_FORWARD"
    assert meta["readiness_report"] == PASSED_READINESS
    assert stopped["stopped_at"] == row["end"]
    assert stopped["authoritative_end"] == row["end"]

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["product_mode"] == "DEMO_FORWARD"
    assert manifest["observation_mode"] == "OBSERVE_ONLY"
    assert manifest["environment"] == "DEMO_FORWARD"
    assert manifest["stopped_at"] == row["end"]
    assert manifest["authoritative_end"] == row["end"]
    assert manifest["session"]["end"] == row["end"]


def test_terminal_failure_details_are_canonical_and_timestamped(tmp_path: Path) -> None:
    collector, _ = _make_collector(
        tmp_path, LiveFakeMT5("disconnect"), max_consecutive_failures=3
    )
    collector.start(PASSED_READINESS)
    assert _wait_for(lambda: collector.state == "STOPPED_ON_ERRORS")

    stopped = collector.status()
    row = _session_rows(tmp_path / "obs.db")[0]
    meta = json.loads(row["meta"])
    failure = meta["terminal_failure"]
    assert failure["category"] == "RETRIEVAL_UNAVAILABLE"
    assert failure["consecutive_failures"] == 3
    assert failure["timestamp"]
    assert stopped["terminal_failure"] == failure
    assert stopped["stopped_at"] == row["end"]

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["state"] == "STOPPED_ON_ERRORS"
    assert manifest["stopped_at"] == row["end"]
    assert manifest["terminal_failure"] == failure


def test_worker_crash_is_terminally_accounted(tmp_path: Path) -> None:
    collector, _ = _make_collector(
        tmp_path, LiveFakeMT5("live"), max_consecutive_failures=1
    )
    collector.start(PASSED_READINESS)

    def crash() -> None:
        raise RuntimeError("worker body exploded")

    collector._poll_once = crash  # type: ignore[method-assign]
    assert _wait_for(lambda: collector.state == "STOPPED_ON_ERRORS")
    row = _session_rows(tmp_path / "obs.db")[0]
    meta = json.loads(row["meta"])
    assert meta["terminal_failure"]["category"] == "WORKER_CRASH"
    assert row["status"] == "ENDED_ON_ERRORS"
    assert collector.stopped_at == row["end"]


def test_repeated_end_session_returns_original_timestamp(tmp_path: Path) -> None:
    collector, _ = _make_collector(tmp_path, LiveFakeMT5("live"))
    collector.start(PASSED_READINESS)
    assert _wait_for(lambda: collector.ticks_recorded >= 1)
    stopped = collector.stop()
    first_end = stopped["stopped_at"]
    second_end = collector.observatory.end_session(collector.session_id or "", status="ENDED")
    assert second_end == first_end
    assert collector.stop()["stopped_at"] == first_end
