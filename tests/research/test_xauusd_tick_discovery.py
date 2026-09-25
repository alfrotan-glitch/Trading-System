"""Discovery-window rules. These fixtures are not the canonical archive."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from qts.research.xauusd_tick_discovery import (
    _Carry,
    _Facts,
    _Hms01,
    discovery_cutoff,
    hms01_verdict,
    hms02_verdict,
    measure_batch,
    render_research_state,
    scan_dataset,
)


def test_cutoff_is_the_first_60_percent_of_the_raw_span() -> None:
    assert discovery_cutoff(0, 1000) == 600
    time_min = 1726746013452
    time_max = 1789775939790
    cutoff = discovery_cutoff(time_min, time_max)
    assert cutoff == time_min + ((time_max - time_min) * 60) // 100
    assert cutoff < time_min + 0.6 * (time_max - time_min) + 1


def test_validation_touching_triple_is_excluded_and_not_repaired() -> None:
    facts = _Facts()
    hms = _Hms01()
    carry = _Carry()
    # Center at global row 3 is a discovery reversal. The later triple touches cutoff 600.
    bid = np.array([100.0, 100.0, 100.0, 100.4, 100.1, 100.0, 101.0, 100.0], dtype=float)
    ask = bid + 0.1
    stamp = np.array([0, 10, 20, 30, 40, 50, 700, 710], dtype=np.int64)
    measure_batch(
        facts, hms, carry, bid=bid[:4], ask=ask[:4], stamp=stamp[:4], cutoff=600, time_min=0, span=710
    )
    measure_batch(
        facts, hms, carry, bid=bid[4:], ask=ask[4:], stamp=stamp[4:], cutoff=600, time_min=0, span=710
    )
    stats = hms.as_dict()
    assert stats["events"] == 2
    assert stats["reversals"] == 1
    assert stats["excluded_triples_touching_validation_span"] == 1
    assert stats["nonoverlap_events"] == 1
    assert stats["nonoverlap_reversals"] == 1
    assert facts.validation_rows == 2
    assert facts.discovery_rows == 6


def test_inverted_quote_stays_in_the_primary_count() -> None:
    facts = _Facts()
    hms = _Hms01()
    carry = _Carry()
    bid = np.array([100.0, 100.0, 100.0, 100.5, 100.4], dtype=float)
    ask = np.array([100.1, 100.1, 100.1, 100.4, 100.5], dtype=float)
    stamp = np.array([0, 1, 2, 3, 4], dtype=np.int64)
    measure_batch(facts, hms, carry, bid=bid, ask=ask, stamp=stamp, cutoff=100, time_min=0, span=4)
    assert hms.events == 1
    assert hms.inverted_events == 1
    assert ask[3] < bid[3]


def test_hms01_reject_does_not_promote() -> None:
    verdict = hms01_verdict(
        {
            "nonoverlap_events": 200,
            "nonoverlap_reversal_frequency": 0.49,
            "nonoverlap_mean_net_bps": -0.2,
            "gap_mean_net_bps": -0.2,
            "nonoverlap_mean_net_bps_bootstrap": {"lo": -0.3, "hi": -0.1},
            "nonoverlap_inverted_events": 0,
        }
    )
    assert verdict["result"] == "REJECTED"
    assert verdict["promoted"] is False


def test_hms02_does_not_treat_a_mechanism_split_as_a_strategy() -> None:
    verdict = hms02_verdict(
        {
            "nonoverlap_wide_n": 100,
            "nonoverlap_narrow_n": 100,
            "nonoverlap_mean_scaled_difference_wide_minus_narrow": 0.1,
            "median_store_truncated": False,
        }
    )
    assert verdict["result"] == "DISCOVERY_SURVIVED"
    assert verdict["promoted"] is False
    assert verdict["not_validated"] is True


def test_scan_does_not_let_the_locked_span_set_the_median(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    parts = dataset / "parts"
    parts.mkdir(parents=True)
    # Six narrow and four wide discovery spreads. A validation spread of 50 must not move the median.
    bid = np.array([10.0] * 11, dtype=float)
    ask = np.array([10.25, 10.25, 10.25, 10.5, 10.25, 10.25, 10.5, 10.25, 10.5, 10.5, 60.0], dtype=float)
    stamp = np.array([0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 1000], dtype=np.int64)
    table = pa.table(
        {
            "time_msc": stamp,
            "bid": bid,
            "ask": ask,
            "last": bid,
            "volume_real": np.zeros(11),
            "time": stamp // 1000,
            "flags": np.zeros(11, dtype=np.int64),
        }
    )
    pq.write_table(table, parts / "part-000000.parquet")
    manifest = {
        "status": "COMPLETE",
        "parts": [{"part": "part-000000.parquet"}],
        "dataset_sha256": "fixture-not-canonical",
        "symbol": {"actual": "XAUUSD"},
        "timestamp_basis": "UNVERIFIED",
        "timestamp_interpretation_confirmed": False,
    }
    (dataset / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    report = scan_dataset(dataset)
    assert report["window"]["cutoff_time_msc"] == 600
    assert report["window"]["validation_rows_counted_as_data_fact_only"] == 1
    assert report["hypotheses"]["H-MS-02"]["statistics"]["median_spread_price"] == 0.25
    assert report["hypotheses"]["H-TOD-01"]["result"] == "NOT TESTED"
    assert report["decision"] == "INCONCLUSIVE"
    assert report["edge_claim"] == "NOT ESTABLISHED"
    assert report["strategy_promoted"] is False
    assert report["data_facts"]["repairs_applied"] == []
    text = render_research_state(report)
    assert "Decision: INCONCLUSIVE" in text
    assert "Decision: VALIDATED" not in text
    assert "Decision: CANDIDATE" not in text
    assert "H-TOD-01" in text
    assert "DATA FACTS" in text
