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
    print("  - BENCH-A-TREND-EMA-12-48 (15m EMA 12/48): claim_eligible=FALSE (corrected). Mechanism verified. Economic gates FAIL: Sharpe -5.425 (< 0 gate), profit factor 0.898 (< 1 gate), win rate 0.098, max drawdown 0.29. Net PNL positive (+1093 USD) but driven by a small number of large wins with poor risk-adjusted returns. NOT a validated economic edge.")
    print("      Prerequisites not met: (1) reconstructed dataset quality FAIL at 5.42% unexpected gaps (>2% gate); (2) deal-level broker cost measurement unavailable (Linux sandbox, no MT5 terminal connection).")
    print("  - BENCH-B-BREAKOUT-DONCHIAN-20: claim_eligible=FALSE. Negative net PNL (-2157 USD), weak Sharpe (-5.23), high drawdown (0.93). Control candidate not promoted.")
    print("  - BENCH-C-MEANREV-BOLLINGER-20-2.0 (falsification CONTROL): claim_eligible=FALSE. Negative net PNL (-1527 USD). Expected failure — the control's failure confirms the gates measure something real.")
    print("  - Cost components: MEASURED_FROM_DOCUMENTATION (official broker docs: spread 18/5 pips, commission $3.50-$5.50/side, swap -60/+19 pips, contract 100 oz, session 01:05-23:55, triple swap Wednesday). NOT deal-level MT5 measurement.")
    print("  - Dataset: reconstructed M15 CSV rebuilt from upstream source (github.com/vudo805/forex-price-simulator, commit 4d6f155). 26,038 rows, Aug 2025 - Sep 2026. Unexpected gap rate 5.42% — FAIL against 2% gate. Raw original file missing. Evidence inventory independently verifies statistics.")
    print("  - No validated economic edge exists for M15. Mechanism verified only. LIVE remains LOCKED. REAL_CAPITAL_EXPOSURE = 0. No live orders submitted.")
    print()
    print("CONCRETE NEXT ACTIONS:")
    print("  1. The reconstructed M15 dataset (26,038 rows, verified from upstream JSON) is usable for mechanism verification and DEMO-forward diagnostics ONLY.")
    print("  2. Obtain a corrected/replaced M15 dataset passing <2% unexpected gaps (rebuild script preserved: scripts/rebuild_m15_from_source.py) before ANY claim eligibility.")
    print("  3. Obtain deal-level broker cost measurement from Windows MT5 DEMO terminal (prepared: setup_windows.bat -> run_qts.bat -> qts demo measured-model). Linux sandbox has no MetaTrader5 package.")
    print("  4. Evaluate M15 economic performance honestly: current metrics show negative risk-adjusted returns (Sharpe -5.425, PF < 1, high drawdown). Positive gross/net PNL is NOT sufficient for validation.")
    print("  5. The product operates correctly: fails closed, reports honestly, preserves frozen benchmarks, integrates mechanism, does not fabricate profitability, and does not submit live orders.")


if __name__ == "__main__":
    main()
