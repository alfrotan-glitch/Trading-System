"""Evaluate registered Edge Lab candidates against the frozen gate.

Reproduces `docs/research/candidate_xl001_easing_conditions_2026-10-20.md`:
alpha, cost sensitivity, decade stability and the deflated Sharpe, across the
fixed DEV/VAL/TEST split.

This script reports. It never promotes, never changes a threshold, and never
touches live eligibility. Costs are ASSUMED and labelled as such in every row.
"""

from __future__ import annotations

import json
import warnings
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from qts.research.edgelab import CostModel, deflated_sharpe
from qts.research.edgelab.candidates import build_signal_frame, candidates
from qts.research.edgelab.gate import MIN_ALPHA_T_DEV, MIN_DSR
from qts.research.edgelab.power import detection_summary
from qts.research.edgelab.reporting import evaluate_period

warnings.filterwarnings("ignore", category=RuntimeWarning)

OUT = Path("data/research/experiments")
BPY = 252.0
WINDOWS = (
    ("DEV_1971_2000", "1971-01-01", "2000-12-31"),
    ("VAL_2001_2010", "2001-01-01", "2010-12-31"),
    ("TEST_2011_2019", "2011-01-01", "2019-12-31"),
)
COSTS = (
    CostModel(),
    CostModel.realistic_ecn(),
    CostModel.stressed(2.0),
    CostModel.stressed(5.0),
    CostModel.standard_account(),
)


def evaluate(sub: pd.DataFrame, sig: pd.Series, cost: CostModel, name: str, family: str) -> dict:
    """Delegate to the shared path so the holdout script computes the same thing."""
    m = evaluate_period(sub, sig, cost, name, family, bars_per_year=BPY)
    m.pop("net_returns", None)
    m.pop("bench_returns", None)
    return m


def main() -> None:
    bars = build_signal_frame()
    report: dict = {
        "generated_at": datetime.now(UTC).isoformat(),
        "cost_basis": "ASSUMED bps, never measured",
        "gate": {"min_alpha_t_dev": MIN_ALPHA_T_DEV, "min_dsr": MIN_DSR},
        "candidates": {},
    }

    for cand in candidates():
        sig_all = cand.signal(bars)
        block: dict = {"definition_hash": cand.definition_hash(), "params": cand.params, "periods": {}}

        print(f"\n=== {cand.id} {cand.name} (hash {cand.definition_hash()}) ===")
        header = f"{'period':16} {'cost':18} {'bps':>6} {'alpha':>8} {'a_t':>6} {'sharpe':>7} {'maxDD':>7} {'beta':>6}"
        print(header)
        print("-" * len(header))

        for label, lo, hi in WINDOWS:
            sub = bars[(bars.index >= lo) & (bars.index <= hi)]
            sig = sig_all.reindex(sub.index).fillna(0.0)
            block["periods"][label] = {}
            for cost in COSTS:
                m = evaluate(sub, sig, cost, cand.id, cand.family)
                block["periods"][label][cost.name] = m
                print(
                    f"{label:16} {cost.name:18} {cost.per_side_bps():6.2f} "
                    f"{m['alpha_ann']:8.3f} {m['alpha_t']:6.2f} {m['sharpe']:7.3f} "
                    f"{m['max_dd']:7.1%} {m['beta']:6.3f}"
                )

        # Gate evaluation at the realistic cost model.
        realistic = CostModel.realistic_ecn().name
        dev = block["periods"]["DEV_1971_2000"][realistic]
        val = block["periods"]["VAL_2001_2010"][realistic]
        test = block["periods"]["TEST_2011_2019"][realistic]
        stress = block["periods"]["DEV_1971_2000"][CostModel.stressed(2.0).name]
        power = detection_summary(dev["n_obs"], BPY, MIN_ALPHA_T_DEV)

        dsr = {
            str(n): round(
                deflated_sharpe(
                    dev["sharpe"], n, dev["n_obs"], bars_per_year=BPY, skew=dev["skew"], kurt=dev["kurt"]
                ),
                4,
            )
            for n in (1, 7, 11, 15)
        }

        checks = {
            "alpha_t_dev": (dev["alpha_t"], dev["alpha_t"] >= MIN_ALPHA_T_DEV),
            "dsr_11_trials": (dsr["11"], dsr["11"] >= MIN_DSR),
            "alpha_positive_2x_cost": (stress["alpha_ann"], stress["alpha_ann"] > 0),
            "val_sign_preserved": (val["alpha_ann"], val["alpha_ann"] > 0),
            "test_independently_significant": (test["alpha_t"], test["alpha_t"] >= MIN_ALPHA_T_DEV),
        }
        passed = all(ok for _, ok in checks.values())
        block.update(
            {
                "power": power,
                "dsr_by_trials": dsr,
                "gate_checks": {k: {"value": v, "pass": ok} for k, (v, ok) in checks.items()},
                "status": "CANDIDATE" if passed else "REJECTED",
            }
        )
        report["candidates"][cand.id] = block

        print(f"\n  detection floor on DEV: SR {power['min_detectable_sr']:.3f} ({power['years']:.1f} yrs)")
        print(f"  DSR by trial count: {dsr}")
        for k, (v, ok) in checks.items():
            print(f"  [{'PASS' if ok else 'FAIL'}] {k}: {v:.3f}")
        print(f"  STATUS: {block['status']}")

    report["overall"] = "CANDIDATE" if any(b["status"] == "CANDIDATE" for b in report["candidates"].values()) else "NO_VALIDATED_EDGE"
    report["holdout_note"] = (
        "2020-2024 was consumed by another hypothesis and is in-sample here. The "
        "vudo805 Dukascopy series is genuinely unseen but the macro drivers end "
        "2024-05, so this rule cannot be computed over it. Forward observation is "
        "the only remaining source of evidence."
    )

    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = OUT / f"candidate_{stamp}.json"
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nOVERALL: {report['overall']}\nwritten -> {path}")


if __name__ == "__main__":
    main()
