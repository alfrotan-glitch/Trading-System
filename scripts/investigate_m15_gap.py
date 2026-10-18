#!/usr/bin/env python3
"""Concrete M15 data gap investigation for the registered Dukascopy 15m dataset.

This script reads the evidence inventory (not the missing raw CSV) and
produces an auditable gap classification: legitimate market closures vs
unexpected missing intervals. It does NOT invent measurements or claim a
valid source exists.

Reference: data/evidence/data_inventory.json shows 5.42% missing intervals
for REAL:dukascopy:vudo805@4d6f155:XAUUSD:15m:mid-from-bid-ask-ticks.
The raw file (data/raw/xauusd_dukascopy_15m_mid_20250806_20260916.csv)
is NOT present in the checkout, confirming incomplete download/acquisition.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).parent.parent.resolve()
EVIDENCE_FILE = REPO / "data" / "evidence" / "data_inventory.json"


def main() -> None:
    if not EVIDENCE_FILE.exists():
        print(f"EVIDENCE MISSING: {EVIDENCE_FILE}")
        return
    data = json.loads(EVIDENCE_FILE.read_text())

    # Find the M15 dataset entry
    m15_entry = None
    for entry in data:
        if entry.get("timeframe") == "15m" and "dukascopy" in (entry.get("source") or ""):
            m15_entry = entry
            break

    if m15_entry is None:
        print("No M15 Dukascopy entry found in inventory.")
        # Print all timeframes for inspection
        for entry in data:
            print(f"  - {entry.get('source')} | tf={entry.get('timeframe')} | missing_pct={entry.get('missingness',{}).get('value',{}).get('missing_pct')}")
        return

    missing = m15_entry.get("missingness", {}).get("value", {})
    gaps = m15_entry.get("gaps", {})

    print("=" * 60)
    print("M15 DATA GAP INVESTIGATION REPORT")
    print("=" * 60)
    print()
    print(f"Dataset ID: {m15_entry.get('source')}")
    print(f"Data class: {m15_entry.get('data_class')}")
    print(f"Timeframe: {m15_entry.get('timeframe')}")
    print(f"Date range: {m15_entry.get('date_range')}")
    print(f"Row count: {m15_entry.get('row_count')}")
    print()
    print("--- GAP METRICS (from evidence inventory) ---")
    print(f"Gap events (unexpected): {gaps.get('gap_count')}")
    print(f"Closure gaps (weekend/holiday): {gaps.get('closure_gap_count')}")
    print(f"Max gap duration (s): {gaps.get('max_gap_s')}")
    print(f"Missing intervals (unexpected): {missing.get('missing_intervals')}")
    print(f"Missing interval % (unexpected): {missing.get('missing_pct')}%")
    print(f"Expected intervals (calendar): {missing.get('calendar_span_expected_intervals')}")
    print()

    # Classification
    unexpected_pct = missing.get("missing_pct", 0)
    closure_count = gaps.get("closure_gap_count", 0)
    unexpected_count = gaps.get("gap_count", 0)

    print("--- CLASSIFICATION ---")
    print(f"Unexpected gap events: {unexpected_count}")
    print(f"Recognized closure gaps: {closure_count}")
    if unexpected_pct > 0.02:
        print(f"VERDICT: FAIL — unexpected missing fraction {unexpected_pct}% exceeds 2% gate (MAX_UNEXPECTED_MISSING_FRACTION).")
        print("This dataset is NOT eligible for real-market claim production without correction or a replacement source.")
    else:
        print(f"VERDICT: PASS — unexpected missing fraction {unexpected_pct}% within 2% gate.")

    print()
    print("--- SOURCE STATUS ---")
    raw_path = REPO / "data" / "raw" / "xauusd_dukascopy_15m_mid_20250806_20260916.csv"
    if raw_path.exists():
        size = raw_path.stat().st_size
        print(f"Raw CSV present: {raw_path} ({size} bytes)")
    else:
        print(f"Raw CSV ABSENT: {raw_path}")
        print("Reason: incomplete download / not acquired in this checkout.")
        print("The evidence references a file that does not exist.")

    print()
    print("--- NEXT ACTIONS ---")
    print("1. The dataset is research-only (MECHANISM_VALIDATION_ONLY / EXECUTION_INELIGIBLE) until the raw file is acquired and the 5.42% unexpected gap rate is explained or corrected.")
    print("2. The 58 recognized closure gaps may be legitimate market closures; the 278 unexpected gaps are NOT explained by the inventory.")
    print("3. The dataset should NOT be used for any live-tradeable claim until a verified replacement or correction is in place.")
    print("4. If a replacement source is unavailable, work continues with the available fixtures and clearly states the limitation (see benchmark_candidates.json notes and docs/research/m15_cost_sensitivity_2026-10-11.md).")
    print()
    print("No measurement fabricated. No claim of validated edge.")


if __name__ == "__main__":
    main()
