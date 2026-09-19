"""P1 inventory contracts: catalog opportunities stay separate from evidence."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_data_gap_matrix_covers_required_families_and_status_dimensions() -> None:
    matrix = json.loads((ROOT / "data/evidence/data_gap_matrix.json").read_text(encoding="utf-8"))
    assert matrix["schema"] == "qts.data_gap_matrix.v1"
    assert "raw/canonical tick-level evidence is not present in the repository" in matrix["global_evidence_boundary"]
    rows = {row["dataset_id"]: row for row in matrix["rows"]}
    required = {
        "mt5_broker_history_ticks_bid_ask",
        "mt5_demo_xauusd_forward_execution_evidence",
        "xauusd_dukascopy_15m_history",
        "comex_gc_futures",
        "xagusd_spot",
        "eurusd_spot",
        "usdjpy_spot",
        "dollar_indexes",
        "treasury_nominal_yields",
        "treasury_real_yields",
        "cftc_commitments_of_traders",
        "macro_release_timestamps",
        "optional_licensed_market_datasets",
    }
    assert required <= rows.keys()
    dimensions = {
        "acquisition_status",
        "quality_status",
        "provenance_status",
        "licensing_status",
        "research_eligibility_status",
    }
    for row in rows.values():
        assert dimensions <= row.keys(), row["dataset_id"]
        assert row["evidence_refs"]
        if row["acquisition_status"] != "ACQUIRED":
            assert row["research_eligibility_status"] not in {
                "RESEARCH_ELIGIBLE",
                "QUALITY_PASSED",
            }


def test_hedge_spec_is_a_gate_not_a_claim() -> None:
    spec = json.loads((ROOT / "data/evidence/hedge_research_spec.json").read_text(encoding="utf-8"))
    assert spec["status"] == "SPECIFICATION_ONLY"
    assert spec["claim_status"] == "NO_HEDGE_CLAIM"
    assert "multiple_testing_correction" in spec["required_gates"]
    assert "untouched_out_of_sample_validation" in spec["required_gates"]
    assert "correlation alone is insufficient" in spec["eligibility_rule"]
