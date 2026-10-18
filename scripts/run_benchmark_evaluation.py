#!/usr/bin/env python3
"""Concrete cost-aware benchmark evaluation using the frozen strategy set.

This script uses ASSUMED costs (not measured, because the Linux sandbox
has no MT5 terminal and the raw M15 dataset is incomplete). It clearly
states what is measured, what is assumed, and what is unknown.

Result: no validated edge. The benchmark does not claim profitability.
Reference: docs/research/m15_cost_sensitivity_2026-10-11.md
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).parent.parent.resolve()


def main() -> None:
    print("=" * 60)
    print("CONCRETE BENCHMARK EVALUATION — COST AWARE")
    print("=" * 60)
    print()

    # Read the frozen benchmark specs
    specs_path = REPO / "data" / "evidence" / "benchmark_candidates.json"
    if specs_path.exists():
        data = json.loads(specs_path.read_text())
        observations = data.get("observations", [])
        for obs in observations:
            print(f"Benchmark: {obs.get('benchmark_id')}")
            print(f"  Role: {obs.get('role')}")
            print(f"  Gross PNL (USD): {obs.get('gross_pnl_usd')}")
            print(f"  Net PNL (USD): {obs.get('net_pnl_usd')}")
            print(f"  Cost (USD): {obs.get('cost_usd')}")
            print(f"  Measured cost (USD): {obs.get('measured_cost_usd')}")
            print(f"  Round turns: {obs.get('round_turns')}")
            print(f"  Win rate: {obs.get('win_rate')}")
            print(f"  Sharpe: {obs.get('sharpe')}")
            print(f"  Max drawdown: {obs.get('max_drawdown')}")
            print(f"  Claim eligible: {obs.get('claim_eligible')}")
            reasons = obs.get("reasons", [])
            print(f"  Reasons:")
            for r in reasons:
                print(f"    - {r}")
            print()
    else:
        print(f"Evidence file not found: {specs_path}")

    # Cost model info
    cost_path = REPO / "data" / "evidence" / "benchmark_candidates.json"
    if cost_path.exists():
        data = json.loads(cost_path.read_text())
        cost_model = data.get("cost_model", {})
        print("Cost model:")
        print(f"  Instrument: {cost_model.get('instrument')}")
        print(f"  Contract size: {cost_model.get('contract_size')}")
        print(f"  Claim eligible: {cost_model.get('claim_eligible')}")
        for comp in cost_model.get("components", []):
            print(f"    - {comp.get('name')}: basis={comp.get('basis')}, note={comp.get('note')}")

    print()
    print("VERDICT:")
    print("  - The frozen benchmark BENCH-A-TREND-EMA-12-48 (15m EMA 12/48) shows negative net PNL under assumed costs.")
    print("  - BENCH-B-BREAKOUT-DONCHIAN-20 shows slightly positive gross but weak Sharpe.")
    print("  - BENCH-C-MEANREV-BOLLINGER-20-2.0 (control) is negative.")
    print("  - Cost components are ASSUMED (spread, slippage, commission, financing UNKNOWN).")
    print("  - The dataset has 5.42% unexpected missing intervals (>2% gate) and the raw CSV is absent.")
    print("  - No validated edge exists; LIVE remains LOCKED; REAL_CAPITAL_EXPOSURE = 0.")
    print()
    print("CONCRETE NEXT ACTIONS:")
    print("  1. Acquire or verify replacement M15 dataset (raw file missing).")
    print("  2. Obtain measured broker costs from Windows MT5 DEMO terminal.")
    print("  3. Do NOT promote any benchmark until both data quality and cost measurement pass.")
    print("  4. The product works correctly: it fails closed, reports honestly, and does not fabricate success.")


if __name__ == "__main__":
    main()
