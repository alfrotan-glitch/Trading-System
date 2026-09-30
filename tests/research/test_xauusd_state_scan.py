"""Locked state-conditional rules. Fixtures are not the canonical archive."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from qts.research.xauusd_state_scan import (
    StateScan,
    apply_verdicts,
    hist_quantile,
    persistence_counts,
    rank_exploratory,
    render_state_report,
    run_lengths,
    scan_dataset,
    series_masks,
)


def test_run_length_keeps_only_the_continued_seed() -> None:
    lengths = run_lengths(np.array([1, 1, -1, -1], dtype=np.int8), 1, 3)
    assert lengths.tolist() == [4, 5, 1, 2]


def test_persistence_keeps_only_the_continued_level() -> None:
    lengths = persistence_counts(np.array([22, 22, 22, 30]), 22, 4)
    assert lengths.tolist() == [5, 6, 7, 1]


def test_same_millisecond_gap_is_not_an_intensity_state() -> None:
    spread = np.array([22, 22, 22, 22, 30, 30])
    locked = np.zeros(6, dtype=bool)
    stamp = np.array([0, 0, 100, 600, 1200, 1800])
    mid = np.arange(6)
    signs = np.array([0, 1, 1, 1, 1, 1], dtype=np.int8)
    lengths = np.array([1, 1, 2, 3, 4, 5], dtype=np.int32)
    persist = persistence_counts(spread, 0, 0)
    masks = series_masks(spread, locked, stamp, mid, signs, lengths, persist)
    assert not masks["intensity_active"][1]
    assert masks["intensity_active"][2]
    assert masks["intensity_normal"][3]
    assert masks["intensity_quiet"][4]
    assert not masks["intensity_active"][0]


def test_inferential_identity_is_the_global_row() -> None:
    bid, ask, stamp = _series(20)
    scan = StateScan(0, 10**9, horizons=(4,), carry=8)
    scan.add_batch(bid, ask, stamp)
    # i = 5, 10, 15. Row 0 is divisible too, but it has no incoming state.
    assert int(scan.n[0, 0]) == 3


def test_split_batches_match_one_batch_and_keep_the_open_run() -> None:
    bid, ask, stamp = _series(40)
    one = StateScan(0, 10**9, horizons=(4,), carry=8)
    split = StateScan(0, 10**9, horizons=(4,), carry=8)
    one.add_batch(bid, ask, stamp)
    split.add_batch(bid[:15], ask[:15], stamp[:15])
    split.add_batch(bid[15:], ask[15:], stamp[15:])
    assert one.n.tolist() == split.n.tolist()
    assert np.allclose(one.abs_sum, split.abs_sum)
    assert np.allclose(one.signed_sum, split.signed_sum)
    assert one.finish() == split.finish()
    # Every inferential row of a 40-quote rise is still a long run after the split.
    assert int(split.n[split_state("run_long"), 0]) == 7


def test_locked_prices_do_not_enter_discovery_sums() -> None:
    bid, ask, stamp = _series(30)
    prefix = StateScan(0, 10_000, horizons=(4,), carry=8)
    prefix.add_batch(bid, ask, stamp)
    locked_bid = np.concatenate((bid, np.array([500.0, 500.0])))
    locked_ask = np.concatenate((ask, np.array([500.3, 500.3])))
    locked_stamp = np.concatenate((stamp, np.array([10_000, 10_100])))
    full = StateScan(0, 10_000, horizons=(4,), carry=8)
    full.add_batch(locked_bid[:12], locked_ask[:12], locked_stamp[:12])
    full.add_batch(locked_bid[12:], locked_ask[12:], locked_stamp[12:])
    assert full.validation_rows == 2
    assert full.n.tolist() == prefix.n.tolist()
    assert np.allclose(full.abs_sum, prefix.abs_sum)
    assert full.finish() == prefix.finish()


def test_window_touching_a_locked_middle_quote_is_excluded() -> None:
    bid, ask, stamp = _series(12, gap=10)
    stamp = stamp.copy()
    stamp[7] = 9_000
    touched = StateScan(0, 5_000, horizons=(4,), carry=20)
    touched.add_batch(bid, ask, stamp)
    clean = StateScan(0, 5_000, horizons=(4,), carry=20)
    clean_stamp = np.arange(12) * 10
    clean.add_batch(bid, ask, clean_stamp)
    assert int(touched.n[0, 0]) == 0
    assert int(clean.n[0, 0]) == 1


def test_delay_window_starts_at_the_next_quote() -> None:
    # The only inferential row at horizon 256 is global row 257.
    n = 515
    bid = np.full(n, 100.0)
    ask = np.full(n, 100.30)
    bid[513] = 110.0
    ask[513] = 110.30
    bid[514] = 100.50
    ask[514] = 100.80
    stamp = np.arange(n) * 50
    scan = StateScan(0, 10**9, horizons=(256,), carry=300)
    scan.add_batch(bid, ask, stamp)
    measured = scan.finish()
    assert measured["H-ST-01"]["a_n"] == [1, 0, 0]
    assert measured["H-ST-01"]["a_sum"][0] == 10.0
    assert measured["H-ST-01"]["delay_a_sum"][0] == 0.5


def test_floor_binds_when_the_p_value_is_small() -> None:
    measured = _empty_measured()
    measured["H-ST-03"]["n"] = [40_000, 40_000, 40_000]
    measured["H-ST-03"]["fade"] = [20_200, 20_200, 20_200]
    measured["H-ST-03"]["residual"] = [1.0, 1.0, 1.0]
    verdict = apply_verdicts(measured)["H-ST-03"]
    assert verdict["status"] == "REJECTED"
    assert verdict["promoted"] is False
    assert "floor" in verdict["reason"]


def test_leave_contrast_does_not_require_the_exceed_lift() -> None:
    measured = _empty_measured()
    _fill_magnitude(measured["H-ST-04"], mean_a=1.20, mean_b=1.0, lift=0.0, delay_ratio=1.15)
    _fill_magnitude(measured["H-ST-01"], mean_a=1.30, mean_b=1.0, lift=0.0, delay_ratio=1.15)
    verdicts = apply_verdicts(measured)
    assert verdicts["H-ST-04"]["status"] == "TESTED"
    assert verdicts["H-ST-04"]["promoted"] is False
    assert verdicts["H-ST-01"]["status"] == "REJECTED"
    assert "lift" in verdicts["H-ST-01"]["reason"]


def test_promising_fade_requires_cost_delay_directions_and_terciles() -> None:
    measured = _empty_measured()
    _fill_fade(measured["H-ST-03"])
    verdict = apply_verdicts(measured)["H-ST-03"]
    assert verdict["status"] == "PROMISING"
    assert verdict["promoted"] is False
    assert verdict["not_robust"] is True
    assert verdict["held_out_opened"] is False
    assert verdict["horizon_1024"] == "underpowered"

    costly = _empty_measured()
    _fill_fade(costly["H-ST-03"], residual=-1.0)
    assert apply_verdicts(costly)["H-ST-03"]["status"] == "REJECTED"

    delayed = _empty_measured()
    _fill_fade(delayed["H-ST-03"], delay_rate=0.40)
    assert apply_verdicts(delayed)["H-ST-03"]["status"] == "REJECTED"


def test_horizon_1024_disagreement_rejects_and_underpowered_does_not() -> None:
    rejected = _empty_measured()
    _fill_magnitude(rejected["H-ST-04"], mean_a=1.20, mean_b=1.0, lift=0.0, delay_ratio=1.15)
    rejected["H-ST-04"]["longer_a_n"] = 2_000
    rejected["H-ST-04"]["longer_a_sum"] = 1_000.0
    rejected["H-ST-04"]["longer_b_n"] = 2_000
    rejected["H-ST-04"]["longer_b_sum"] = 2_000.0
    assert apply_verdicts(rejected)["H-ST-04"]["status"] == "REJECTED"
    assert apply_verdicts(rejected)["H-ST-04"]["horizon_1024"] == "disagrees"

    noted = _empty_measured()
    _fill_magnitude(noted["H-ST-04"], mean_a=1.20, mean_b=1.0, lift=0.0, delay_ratio=1.15)
    noted["H-ST-04"]["longer_a_n"] = 100
    noted["H-ST-04"]["longer_b_n"] = 100
    verdict = apply_verdicts(noted)["H-ST-04"]
    assert verdict["status"] == "TESTED"
    assert verdict["horizon_1024"] == "underpowered"


def test_backward_timestamp_is_inconclusive() -> None:
    measured = _empty_measured()
    measured["nonmonotonic"] = 1
    _fill_fade(measured["H-ST-03"])
    verdicts = apply_verdicts(measured)
    assert {item["status"] for item in verdicts.values()} == {"INCONCLUSIVE"}


def test_ranked_cells_are_generators_not_tests() -> None:
    rows = [
        _panel_row("unconditional", 0.0, 0.10, 0.22, 0.20),
        _panel_row("spread_wide", 0.10, 0.10, 0.30, 0.20),
        _panel_row("vol_low", 0.01, 0.11, 0.22, 0.21),
    ]
    generated = rank_exploratory(rows)
    assert [item["state"] for item in generated] == ["spread_wide"]
    assert generated[0]["status"] == "NOT TESTED"
    assert generated[0]["cannot_confirm_on_this_discovery_sample"] is True


def test_scan_does_not_open_the_locked_span_or_promote(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    parts = dataset / "parts"
    parts.mkdir(parents=True)
    bid = np.array([100.0, 100.01, 100.02, 100.03, 100.02, 100.01, 100.0, 100.0, 500.0], dtype=float)
    ask = bid + 0.22
    stamp = np.array([0, 10, 20, 30, 40, 50, 60, 70, 1000], dtype=np.int64)
    pq.write_table(pa.table({"time_msc": stamp, "bid": bid, "ask": ask}), parts / "part-000000.parquet")
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
    assert report["window"]["validation_rows_not_used"] == 1
    assert report["decision"] == "INCONCLUSIVE"
    assert report["strategy_promoted"] is False
    assert report["held_out_span_opened"] is False
    assert report["timestamp_basis"]["status"] == "BLOCKED"
    assert report["prior_hypotheses_not_reopened"]["H-QD-02"] == "REJECTED"
    assert "H-MS-02" not in report["hypotheses"]
    assert all(row["mean_abs"] < 5 for row in report["panel"])
    assert all(item["status"] != "ROBUST" for item in report["hypotheses"].values())
    text = render_state_report(report)
    assert "Decision: INCONCLUSIVE" in text
    assert "Decision: VALIDATED" not in text


def test_histogram_quantile_is_a_price() -> None:
    hist = np.zeros(80_001, dtype=np.int64)
    hist[40_000 + 4] = 10
    assert hist_quantile(hist, 0.50) == 0.02


def _series(n: int, gap: int = 50) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    bid = 100.0 + np.arange(n) * 0.01
    ask = bid + 0.22
    stamp = np.arange(n, dtype=np.int64) * gap
    return bid, ask, stamp


def split_state(name: str) -> int:
    from qts.research.xauusd_state_scan import STATES

    return STATES.index(name)


def _zeros() -> list[int]:
    return [0, 0, 0]


def _floats() -> list[float]:
    return [0.0, 0.0, 0.0]


def _empty_measured() -> dict:
    return {
        "nonmonotonic": 0,
        "H-ST-01": _empty_magnitude(),
        "H-ST-02": _empty_magnitude(),
        "H-ST-04": _empty_magnitude(),
        "H-ST-03": {
            "n": _zeros(),
            "fade": _zeros(),
            "residual": _floats(),
            "up_n": _zeros(),
            "up_fade": _zeros(),
            "up_residual": _floats(),
            "down_n": _zeros(),
            "down_fade": _zeros(),
            "down_residual": _floats(),
            "delay_n": _zeros(),
            "delay_fade": _zeros(),
            "delay_residual": _floats(),
            "longer_n": 0,
            "longer_fade": 0,
        },
    }


def _empty_magnitude() -> dict:
    return {
        "a_n": _zeros(),
        "a_sum": _floats(),
        "a_sumsq": _floats(),
        "a_exceed": _zeros(),
        "b_n": _zeros(),
        "b_sum": _floats(),
        "b_sumsq": _floats(),
        "b_exceed": _zeros(),
        "delay_a_n": _zeros(),
        "delay_a_sum": _floats(),
        "delay_b_n": _zeros(),
        "delay_b_sum": _floats(),
        "longer_a_n": 0,
        "longer_a_sum": 0.0,
        "longer_b_n": 0,
        "longer_b_sum": 0.0,
    }


def _fill_magnitude(block: dict, *, mean_a: float, mean_b: float, lift: float, delay_ratio: float) -> None:
    n = 5_000
    block["a_n"] = [n, n, n]
    block["b_n"] = [n, n, n]
    block["a_sum"] = [mean_a * n, mean_a * n, mean_a * n]
    block["b_sum"] = [mean_b * n, mean_b * n, mean_b * n]
    block["a_sumsq"] = [mean_a * mean_a * n, mean_a * mean_a * n, mean_a * mean_a * n]
    block["b_sumsq"] = [mean_b * mean_b * n, mean_b * mean_b * n, mean_b * mean_b * n]
    block["a_exceed"] = [int(lift * n), int(lift * n), int(lift * n)]
    block["b_exceed"] = [0, 0, 0]
    block["delay_a_n"] = [n, n, n]
    block["delay_b_n"] = [n, n, n]
    block["delay_a_sum"] = [delay_ratio * n, delay_ratio * n, delay_ratio * n]
    block["delay_b_sum"] = [n, n, n]


def _fill_fade(block: dict, *, residual: float = 1.0, delay_rate: float = 0.60) -> None:
    n = 8_000
    fades = 5_200
    block["n"] = [n, n, n]
    block["fade"] = [fades, fades, fades]
    block["residual"] = [residual * n, residual * n, residual * n]
    block["up_n"] = [4_000, 4_000, 4_000]
    block["down_n"] = [4_000, 4_000, 4_000]
    block["up_fade"] = [2_600, 2_600, 2_600]
    block["down_fade"] = [2_600, 2_600, 2_600]
    block["up_residual"] = [residual * 4_000, residual * 4_000, residual * 4_000]
    block["down_residual"] = [residual * 4_000, residual * 4_000, residual * 4_000]
    block["delay_n"] = [n, n, n]
    block["delay_fade"] = [int(delay_rate * n), int(delay_rate * n), int(delay_rate * n)]
    block["delay_residual"] = [residual * n, residual * n, residual * n]
    block["longer_n"] = 100
    block["longer_fade"] = 60


def _panel_row(state: str, signed: float, absolute: float, spread: float, exceed: float) -> dict:
    return {
        "state": state,
        "horizon_quotes": 256,
        "n": 2_000,
        "mean_signed": signed,
        "mean_abs": absolute,
        "mean_spread": spread,
        "p_exceed_spread": exceed,
    }
