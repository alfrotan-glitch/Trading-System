"""Bounded derived aggregation + run/clock identity (FO-R1 prerequisites).

Two contracts:

1. SCALING — periodic manifest publication must not re-scan the session on the
   critical acquisition path. The default path is O(1) (incremental aggregate);
   the authoritative full-session regeneration stays available explicitly
   (``from_store=True``) and the two must agree.
2. RUN IDENTITY — a session carries durable, hashed, privacy-preserving
   run/clock metadata; unavailable facts are explicit UNAVAILABLE markers,
   never invented values and never credentials.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from test_observe_only_collector import (
    PASSED_READINESS,
    LiveFakeMT5,
    _make_collector,
    _wait_for,
)

import qts.observability.demo_collector as dc

# ------------------------------------------------------------------- scaling


class _SqlSpy:
    """Counts SQL executed through the collector's db_connect seam."""

    def __init__(self, real: Any) -> None:
        self.real = real
        self.statements: list[str] = []
        self._lock = threading.Lock()

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        spy = self

        class _Con:
            def __init__(self, con: Any) -> None:
                self._con = con

            def execute(self, sql: str, *a: Any, **k: Any) -> Any:
                with spy._lock:
                    spy.statements.append(sql)
                return self._con.execute(sql, *a, **k)

            def __getattr__(self, name: str) -> Any:
                return getattr(self._con, name)

        import contextlib

        @contextlib.contextmanager
        def _cm(*a: Any, **k: Any) -> Any:
            with spy.real(*a, **k) as con:
                yield _Con(con)

        return _cm(*args, **kwargs)


def _statements_during(fn: Any) -> list[str]:
    import qts.observability.forward_observatory as fo

    real_dc, real_fo = dc.db_connect, fo.db_connect
    spy_dc, spy_fo = _SqlSpy(real_dc), _SqlSpy(real_fo)
    dc.db_connect, fo.db_connect = spy_dc, spy_fo
    try:
        fn()
    finally:
        dc.db_connect, fo.db_connect = real_dc, real_fo
    return spy_dc.statements + spy_fo.statements


def test_periodic_manifest_does_not_scan_the_session(tmp_path: Path) -> None:
    collector, _ = _make_collector(tmp_path, LiveFakeMT5("live"), interval_s=0.2)
    collector.start(PASSED_READINESS)
    assert _wait_for(lambda: collector.ticks_recorded >= 3), collector.last_error

    statements = _statements_during(collector.write_manifest)  # default = periodic path
    assert statements, "the manifest still reads the session row"
    tick_reads = [s for s in statements if "observation_ticks" in s]
    assert tick_reads == [], f"periodic manifest must not touch accepted ticks: {tick_reads}"
    signal_reads = [s for s in statements if "observation_signals" in s]
    assert signal_reads == [], f"periodic manifest must not scan signals: {signal_reads}"
    collector.stop()


def test_periodic_manifest_cost_is_independent_of_session_size(tmp_path: Path) -> None:
    """Same statement footprint for a short and a long session (no O(N) growth)."""
    collector, _ = _make_collector(tmp_path, LiveFakeMT5("live"), interval_s=0.2, manifest_every_ticks=10_000)
    collector.start(PASSED_READINESS)
    assert _wait_for(lambda: collector.ticks_recorded >= 2), collector.last_error
    short = _statements_during(collector.write_manifest)

    # Grow the session substantially, then measure the same operation.
    from datetime import UTC, datetime
    from decimal import Decimal

    from qts.observability.forward_observatory import ObservationTick

    for i in range(400):
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
            session_id=collector.session_id,
        )
        collector.observatory.record_tick(tick)
    long = _statements_during(collector.write_manifest)
    collector.stop()

    assert len(long) == len(short), "the periodic path must not grow with session size"
    assert [s for s in long if "observation_ticks" in s] == []


def test_bounded_and_store_derived_manifests_agree(tmp_path: Path) -> None:
    collector, _ = _make_collector(tmp_path, LiveFakeMT5("live"), interval_s=0.2, manifest_every_ticks=3)
    collector.start(PASSED_READINESS)
    assert _wait_for(lambda: collector.ticks_recorded >= 4), collector.last_error
    stopped = collector.stop()

    bounded = collector.write_manifest()  # O(1) aggregate
    from_store = collector.write_manifest(from_store=True)  # authoritative regeneration

    for key in (
        "ticks_recorded",
        "timestamp_bases",
        "server_utc_offsets_s",
        "spread_bps",
        "first_event_time",
        "last_event_time",
        "symbols",
        "signals_recorded",
        "duplicates_skipped",
    ):
        assert bounded[key] == from_store[key], f"{key}: bounded aggregate disagrees with the store"
    assert bounded["derived_from_aggregate"] is True
    assert from_store["derived_from_aggregate"] is False
    # Both describe the same canonical dataset.
    assert (
        bounded["ticks_recorded"]
        == stopped["ticks_recorded"]
        == len(collector.observatory.list_ticks(limit=1000, session_id=stopped["session_id"]))
    )
    assert bounded["class"] == "DEMO" and bounded["orders_submitted"] == 0
    assert bounded["acquisition_ledger"]["attempts"] >= 1


def test_manifest_records_the_acquisition_ledger(tmp_path: Path) -> None:
    collector, _ = _make_collector(tmp_path, LiveFakeMT5("frozen"), interval_s=0.2, manifest_every_ticks=1)
    collector.start(PASSED_READINESS)
    assert _wait_for(lambda: collector.duplicates_skipped >= 2), collector.last_error
    manifest = collector.write_manifest()
    collector.stop()

    ledger = manifest["acquisition_ledger"]
    assert ledger["attempts"] >= 3
    assert ledger["outcomes"].get("DUPLICATE", 0) >= 2
    assert ledger["journal_backlog"] == 0 and ledger["journal_dropped"] == 0
    assert manifest["ticks_recorded"] == 1  # the standing quote was observed once


# ------------------------------------------------------------- run metadata


def test_run_metadata_is_complete_hashed_and_privacy_preserving(tmp_path: Path) -> None:
    collector, _ = _make_collector(tmp_path, LiveFakeMT5("live"), interval_s=0.2)
    collector.start(PASSED_READINESS)
    assert _wait_for(lambda: collector.ticks_recorded >= 1), collector.last_error
    collector.stop()

    session = collector.observatory.session(collector.session_id)
    run = session["meta"]["run_metadata"]
    assert run["version"] == dc.RUN_METADATA_VERSION
    assert run["code"]["git_commit"] and run["code"]["package_version"]
    assert run["environment"]["mode"] and run["environment"]["python"]
    assert run["symbols"] == {"canonical": "XAUUSD", "broker": "XAUUSD@"}
    assert run["config"]["collector_policy"]["interval_s"] == 0.2
    assert run["config"]["validation_thresholds"]["max_tick_age_s"] == 5.0
    assert run["config"]["validation_thresholds"]["max_spread_bps"] == 100.0
    assert run["config"]["validation_thresholds"]["future_guard_s"] == -1.0

    # The config hash is reproducible from its own content.
    config = run["config"]
    assert config["hash"] == dc.ObservationCollector._canonical_hash({k: v for k, v in config.items() if k != "hash"})
    # Deterministic: the same policy hashes identically.
    assert config["hash"] == dc.ObservationCollector._canonical_hash({k: v for k, v in config.items() if k != "hash"})

    # Unavailable facts are explicit, never invented.
    assert run["clock"]["host_clock"]["status"] == "UNAVAILABLE"
    assert run["clock"]["host_clock"]["reason"]
    # Offset state at session start: explicitly unavailable or measured, but
    # in BOTH cases the measurement-time policy is stated (never invented).
    offset_block = run["clock"]["broker_offset_measurement"]
    assert offset_block["status"] in ("MEASURED", "UNAVAILABLE")
    assert offset_block["measurement_time"]["status"] == "UNAVAILABLE"
    assert offset_block["measurement_time"]["reason"]
    assert run["privacy"]["credentials_persisted"] is False

    # No credentials and no machine paths anywhere in the identity block.
    blob = json.dumps(run).lower()
    for leak in ("password", "token", "secret", "c:\\\\", "/home/", "/users/"):
        assert leak not in blob, f"run metadata leaked {leak!r}"


def test_run_metadata_marks_absent_broker_identity_explicitly(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.delenv("QTS_MT5_LOGIN", raising=False)
    monkeypatch.delenv("QTS_MT5_SERVER", raising=False)
    collector, _ = _make_collector(tmp_path, LiveFakeMT5("live"))
    run = collector._build_run_metadata(mode="DEVELOPMENT")
    identity = run["broker_identity"]
    assert identity["login_masked"]["status"] == "UNAVAILABLE"
    assert identity["login_masked"]["reason"]
    assert identity["server"]["status"] == "UNAVAILABLE"
    # The fake MT5 exposes no terminal_info()/spec through the adapter either -> explicit.
    assert identity["terminal_build"]["status"] in ("AVAILABLE", "UNAVAILABLE")
    assert run["symbol_spec"]["status"] in ("AVAILABLE", "UNAVAILABLE")


def test_run_metadata_only_masks_a_present_login(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("QTS_MT5_LOGIN", "87654321")
    monkeypatch.setenv("QTS_MT5_SERVER", "WMMarkets-Demo")
    collector, _ = _make_collector(tmp_path, LiveFakeMT5("live"))
    identity = collector._build_run_metadata(mode="DEMO_FORWARD")["broker_identity"]
    assert identity["login_masked"] == {"status": "AVAILABLE", "value": "****21"}
    assert identity["server"] == {"status": "AVAILABLE", "value": "WMMarkets-Demo"}
    assert "87654321" not in json.dumps(identity)


def test_symbol_spec_snapshot_is_hashed_and_path_free(tmp_path: Path) -> None:
    collector, _ = _make_collector(tmp_path, LiveFakeMT5("live"))
    snapshot = collector._symbol_spec_snapshot()
    assert snapshot["status"] == "AVAILABLE"  # the fake broker exposes a spec
    fields = snapshot["value"]
    assert fields["digits"] == 2 and fields["contract_size"] == "100.0"
    assert snapshot["hash"] == dc.ObservationCollector._canonical_hash(fields)
    assert "path" not in fields and "raw" not in fields
    assert "Metals" not in json.dumps(snapshot)  # broker machine path never transferred


def test_clock_history_is_derived_from_the_durable_ledger(tmp_path: Path) -> None:
    collector, _ = _make_collector(tmp_path, LiveFakeMT5("live"), interval_s=0.2)
    collector.start(PASSED_READINESS)
    assert _wait_for(lambda: collector.ticks_recorded >= 3), collector.last_error
    collector.stop()

    history = collector.observatory.clock_history(collector.session_id)
    assert history["distinct_offsets"] == 1
    entry = history["offsets"][0]
    assert entry["server_utc_offset_s"] == 10800.0
    assert entry["basis"] == "measured-m1-bar"
    assert entry["first_seen_at"] and entry["last_seen_at"]
    assert entry["observations"] >= 3
    assert history["offset_changed_mid_session"] is False
    assert history["measurement_time"]["status"] == "UNAVAILABLE"


def test_offset_change_is_visible_in_clock_history(tmp_path: Path) -> None:
    """A mid-session offset change (DST boundary) is recorded, not hidden.

    A real DST shift moves the broker stamps AND the measured offset together.
    """
    collector, fake = _make_collector(tmp_path, LiveFakeMT5("live"), interval_s=0.2)
    collector.start(PASSED_READINESS)
    assert _wait_for(lambda: collector.ticks_recorded >= 1), collector.last_error
    before = collector.ticks_recorded

    # Consistent +3h -> +2h shift: broker stamps move and the cached measurement is dropped.
    adapter = collector.provider.broker
    fake.offset_s = 7200
    adapter._server_offset_cache = {}
    assert _wait_for(lambda: collector.ticks_recorded >= before + 2), collector.last_error
    collector.stop()

    history = collector.observatory.clock_history(collector.session_id)
    assert history["distinct_offsets"] == 2
    assert history["offset_changed_mid_session"] is True
    assert sorted(o["server_utc_offset_s"] for o in history["offsets"]) == [7200.0, 10800.0]
    assert all(o["basis"] == "measured-m1-bar" for o in history["offsets"])
    assert history["measurement_time"]["status"] == "UNAVAILABLE"


def test_inconsistent_offset_shift_is_still_rejected_by_the_future_guard(tmp_path: Path) -> None:
    """The unchanged future guard still refuses a broker/offset mismatch."""
    collector, _ = _make_collector(tmp_path, LiveFakeMT5("live"), interval_s=0.2, max_consecutive_failures=3)
    collector.start(PASSED_READINESS)
    assert _wait_for(lambda: collector.ticks_recorded >= 1), collector.last_error
    # Broker stamps stay +3h while the measured offset claims +2h -> future ticks.
    collector.provider.broker.server_utc_offset = lambda symbol: (7200.0, "measured-m1-bar")
    collector.provider.broker._server_offset_cache = {"XAUUSD@": (7200.0, "measured-m1-bar", time.time() + 10**6)}
    assert _wait_for(lambda: collector.state == "STOPPED_ON_ERRORS"), collector.last_error
    assert "tick from future" in (collector.last_error or "")
    outcomes = [r["outcome"] for r in collector.observatory.list_attempts(collector.session_id)]
    assert "VALIDATION_REJECTED" in outcomes
    assert collector.observatory.attempt_reconciliation(collector.session_id)["ledger_store_agreement"] is True


def test_long_session_manifest_stays_bounded_and_fast(tmp_path: Path) -> None:
    """A grown session still publishes a manifest promptly (acceptance condition)."""
    collector, _ = _make_collector(tmp_path, LiveFakeMT5("live"), interval_s=0.2, manifest_every_ticks=10_000)
    collector.start(PASSED_READINESS)
    assert _wait_for(lambda: collector.ticks_recorded >= 1), collector.last_error

    from datetime import UTC, datetime
    from decimal import Decimal

    from qts.observability.forward_observatory import ObservationTick

    for i in range(2_000):
        collector.observatory.record_tick(
            ObservationTick(
                symbol="XAUUSD@",
                bid=Decimal("2000.0"),
                ask=Decimal("2000.5"),
                provenance="DEMO",
                broker_event_time=datetime.now(UTC),
                broker_time_raw=1_750_000_000.0 + i,
                server_utc_offset_s=10800.0,
                timestamp_basis="broker-normalized(measured-m1-bar)",
                tick_provenance={"mt5_time": 1_750_000_000.0 + i, "mt5_time_msc": (1_750_000_000.0 + i) * 1000},
                session_id=collector.session_id,
            )
        )
    start = time.perf_counter()
    for _ in range(20):
        collector.write_manifest()
    elapsed = time.perf_counter() - start
    collector.stop()
    # 20 publications over a 2k-row session: the bounded path is milliseconds,
    # while a per-call full scan would be ~40k payload parses.
    assert elapsed < 5.0, f"periodic manifest path is not bounded: {elapsed:.2f}s"
