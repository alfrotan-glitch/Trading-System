"""Locked microstructure rules. Fixtures are not the canonical archive."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from qts.research.xauusd_microstructure import (
    DiscoveryScan,
    accumulate_runs,
    apply_verdicts,
    classify_states,
    render_microstructure,
    resolve_one_cent,
    scan_dataset,
    timestamp_basis_assessment,
)


def test_state_partition_is_the_bid_ask_sign_pair() -> None:
    bid = np.array([100, 99, 99, 98, 99, 100, 100, 101, 102], dtype=np.int32)
    ask = np.array([101, 100, 101, 100, 100, 101, 102, 102, 103], dtype=np.int32)
    assert classify_states(bid, ask).tolist() == [0, 5, 0, 7, 8, 5, 7, 8]


def test_run_length_keeps_the_open_run() -> None:
    hist = np.zeros(33, dtype=np.int64)
    sign, length = accumulate_runs(np.array([1, 1, -1, -1, -1], dtype=np.int8), 1, 2, hist)
    assert (sign, length) == (-1, 3)
    assert hist[4] == 1


def test_one_cent_resolution_does_not_read_the_locked_span() -> None:
    mid = np.array([0, 0, 0, 4], dtype=np.int32)
    stamp = np.array([0, 10, 20, 700], dtype=np.int64)
    decision, status, _sign, _delta = resolve_one_cent(mid, stamp, np.array([0]), 600, start_k=1)
    assert status[0] == 3
    assert decision[0] == 3


def test_validation_outcome_is_excluded_and_boundary_is_counted_once() -> None:
    scan = DiscoveryScan(0, 600)
    bid = np.array([100.0, 100.0, 100.0, 100.02, 100.04, 100.0, 110.0], dtype=float)
    ask = bid + 0.02
    stamp = np.array([0, 10, 20, 30, 40, 50, 700], dtype=np.int64)
    scan.add_batch(bid[:3], ask[:3], stamp[:3])
    scan.add_batch(bid[3:], ask[3:], stamp[3:])
    measured = scan.finish()
    assert scan.validation_rows == 1
    assert scan.discovery_rows == 6
    assert measured["nonmonotonic"] == 0
    # The locked quote is not an inferential discovery outcome.
    assert sum(measured["H-QD-02"]["n"]) < 6


def test_deferred_one_cent_move_is_counted_once_and_not_from_the_locked_span() -> None:
    scan = DiscoveryScan(0, 10_000)
    n = 70
    bid = np.full(n, 100.0)
    ask = np.full(n, 100.02)
    bid[65] = 100.01
    bid[68] = 100.03
    stamp = np.arange(n, dtype=np.int64) * 10
    stamp[-1] = 20_000
    bid[-1] = 200.0
    scan.add_batch(bid[:40], ask[:40], stamp[:40])
    scan.add_batch(bid[40:68], ask[40:68], stamp[40:68])
    scan.add_batch(bid[68:], ask[68:], stamp[68:])
    measured = scan.finish()
    assert sum(measured["H-MV-01"]["resolved"]) == 1
    assert sum(measured["H-MV-01"]["up_hit"]) == 1
    assert sum(measured["H-MV-01"]["censored"]) == 0


def test_floor_failure_is_not_promising() -> None:
    measured = _empty_measured()
    measured["H-QD-01"]["one_n"] = [4000, 4000, 4000]
    measured["H-QD-01"]["two_n"] = [4000, 4000, 4000]
    measured["H-QD-01"]["one_cont"] = [2000, 2000, 2000]
    measured["H-QD-01"]["two_cont"] = [2040, 2040, 2040]
    verdict = apply_verdicts(measured)["H-QD-01"]
    assert verdict["status"] == "REJECTED"
    assert verdict["promoted"] is False


def test_cost_failure_is_tested_not_promising() -> None:
    measured = _empty_measured()
    for t in range(3):
        measured["H-QD-01"]["one_n"][t] = 5000
        measured["H-QD-01"]["two_n"][t] = 5000
        measured["H-QD-01"]["one_cont"][t] = 2000
        measured["H-QD-01"]["two_cont"][t] = 3000
        measured["H-QD-01"]["one_fade"][t] = -1000.0
        measured["H-QD-01"]["two_follow"][t] = -1000.0
        measured["H-QD-01"]["delay_one_n"][t] = 5000
        measured["H-QD-01"]["delay_two_n"][t] = 5000
        measured["H-QD-01"]["delay_one_cont"][t] = 2000
        measured["H-QD-01"]["delay_two_cont"][t] = 3000
    verdict = apply_verdicts(measured)["H-QD-01"]
    assert verdict["status"] == "TESTED"
    assert verdict["promoted"] is False
    assert "spread" in verdict["reason"]


def test_clock_stays_blocked_without_manifest_confirmation() -> None:
    assessment = timestamp_basis_assessment({"timestamp_interpretation_confirmed": False})
    assert assessment["status"] == "BLOCKED"
    assert assessment["session_hour_weekday"] == "BLOCKED"


def test_scan_does_not_promote_or_use_the_locked_median(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    parts = dataset / "parts"
    parts.mkdir(parents=True)
    bid = np.array([10.0, 10.01, 10.02, 10.03, 10.02, 10.01, 10.0, 10.0, 10.0, 20.0], dtype=float)
    ask = bid + 0.02
    stamp = np.array([0, 10, 20, 30, 40, 50, 60, 70, 80, 1000], dtype=np.int64)
    pq.write_table(
        pa.table({"time_msc": stamp, "bid": bid, "ask": ask}),
        parts / "part-000000.parquet",
    )
    (dataset / "manifest.json").write_text(
        json.dumps(
            {
                "parts": [{"part": "part-000000.parquet"}],
                "dataset_sha256": "fixture",
                "timestamp_interpretation_confirmed": False,
            }
        ),
        encoding="utf-8",
    )
    report = scan_dataset(dataset)
    assert report["window"]["cutoff_time_msc"] == 600
    assert report["window"]["validation_rows_not_used_in_hypotheses"] == 1
    assert report["decision"] == "INCONCLUSIVE"
    assert report["strategy_promoted"] is False
    assert report["timestamp_basis"]["status"] == "BLOCKED"
    assert "H-MS-02" not in report["hypotheses"]
    text = render_microstructure(report)
    assert "Decision: INCONCLUSIVE" in text
    assert "Decision: VALIDATED" not in text


def _zeros(n: int = 3) -> list[int]:
    return [0] * n


def _empty_measured() -> dict:
    z = _zeros()
    f = [0.0, 0.0, 0.0]
    return {
        "nonmonotonic": 0,
        "H-QD-01": {
            "one_n": z.copy(),
            "one_cont": z.copy(),
            "two_n": z.copy(),
            "two_cont": z.copy(),
            "one_fade": f.copy(),
            "two_follow": f.copy(),
            "delay_one_n": z.copy(),
            "delay_one_cont": z.copy(),
            "delay_two_n": z.copy(),
            "delay_two_cont": z.copy(),
        },
        "H-QD-02": {
            "n": z.copy(),
            "cont": z.copy(),
            "cur_up": z.copy(),
            "cur_down": z.copy(),
            "next_up": z.copy(),
            "next_down": z.copy(),
            "follow": f.copy(),
            "fade": f.copy(),
            "delay_n": z.copy(),
            "delay_cont": z.copy(),
            "delay_cur_up": z.copy(),
            "delay_cur_down": z.copy(),
            "delay_next_up": z.copy(),
            "delay_next_down": z.copy(),
        },
        "H-INT-01": {"n": [z.copy() for _ in range(3)], "short": [z.copy() for _ in range(3)], "next_short": [z.copy() for _ in range(3)], "both": [z.copy() for _ in range(3)]},
        "H-SP-01": {"n": z.copy(), "hit": z.copy(), "independence": 0.0, "independence_tercile": [0.0, 0.0, 0.0]},
        "H-MV-01": {
            "resolved": z.copy(),
            "censored": z.copy(),
            "up_hit": z.copy(),
            "residual": f.copy(),
            "down_resolved": z.copy(),
            "down_hit": z.copy(),
            "delay_resolved": z.copy(),
            "delay_hit": z.copy(),
        },
        "H-VOL-01": {
            "short_n": z.copy(),
            "short_sum": f.copy(),
            "short_sumsq": f.copy(),
            "long_n": z.copy(),
            "long_sum": f.copy(),
            "long_sumsq": f.copy(),
            "sens_short_n": z.copy(),
            "sens_short_sum": f.copy(),
            "sens_long_n": z.copy(),
            "sens_long_sum": f.copy(),
        },
        "H-SPR-01": {
            "widen_n": z.copy(),
            "widen_sum": f.copy(),
            "widen_sumsq": f.copy(),
            "tight_n": z.copy(),
            "tight_sum": f.copy(),
            "tight_sumsq": f.copy(),
            "delay_widen_n": z.copy(),
            "delay_widen_sum": f.copy(),
            "delay_tight_n": z.copy(),
            "delay_tight_sum": f.copy(),
        },
    }
