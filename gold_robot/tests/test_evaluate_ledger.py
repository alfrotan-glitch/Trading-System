"""Tests for evaluate_ledger.py on synthetic ledgers only.

These ledgers are fabricated controls to test the tool's arithmetic
and fail-closed behaviour. They are NOT market results and must never
be quoted as strategy evidence.
"""

import csv
import datetime
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research"))

from evaluate_ledger import evaluate, holm_adjust, deflated_sharpe


def _write_ledger(path, mean, sd, seed=7, n=150, days=60):
    rng = random.Random(seed)
    start = datetime.date(2026, 3, 2)
    dates = []
    d = start
    while len(dates) < days:
        if d.weekday() < 5:
            dates.append(d)
        d += datetime.timedelta(days=1)
    rows = []
    tid = 0
    for i, day in enumerate(dates):
        count = n // days + (1 if i < n % days else 0)
        for _ in range(count):
            tid += 1
            rows.append({
                "trade_id": f"T{tid}", "date": day.isoformat(),
                "gross_usd": f"{rng.gauss(mean, sd):.2f}",
                "commission_usd": "1.00", "slippage_usd": "0.10",
                "swap_charge_usd": "0.00", "broker_fee_usd": "0.00",
                "regime": "trend" if i % 2 == 0 else "range",
            })
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return path


def _run(path, **kw):
    args = {"active_days": 60, "gross_basis": "PRE_SLIPPAGE_REFERENCE",
            "trials_tested": 3, "stress_extra": 1.10,
            "provenance": "SIMULATED"}
    args.update(kw)
    return evaluate(path, **args)


def test_positive_synthetic_screens_positive_but_is_rejected_for_provenance(tmp_path):
    path = _write_ledger(tmp_path / "pos.csv", 3.0, 12.0)
    out = _run(path)
    gate = out["edge_gate"]
    assert gate["trades"] == 150 and gate["days_with_trades"] == 60
    assert gate["net_usd"] > 0 and gate["profit_factor"] > 1.15
    assert gate["bootstrap_multiplicity_adjusted_99pct_lower_expectancy_usd"] > 0
    # Fail-closed: SIMULATED provenance can never pass, even with good metrics.
    assert gate["status"] == "REJECTED_OR_INSUFFICIENT_EVIDENCE"
    assert out["walk_forward_folds"]["positive_folds"] == 5
    assert out["per_regime_decision_time_only"]["trend"]["net"] > 0
    assert out["per_regime_decision_time_only"]["range"]["net"] > 0


def test_negative_synthetic_fails_every_gate(tmp_path):
    path = _write_ledger(tmp_path / "neg.csv", -3.0, 12.0)
    out = _run(path)
    assert out["edge_gate"]["net_usd"] < 0
    assert out["edge_gate"]["profit_factor"] < 1.15
    assert out["dsr"] == 0.0
    assert out["walk_forward_folds"]["mean_oos_sharpe"] < 0.30


def test_holm_is_monotone_and_bounds_p():
    adjusted = holm_adjust([0.01, 0.04, 0.30])
    assert adjusted[0] <= adjusted[1] <= adjusted[2]
    assert all(0.0 <= p <= 1.0 for p in adjusted)
    assert adjusted[0] == 0.03  # 3 * 0.01, smallest first


def test_dsr_needs_enough_days():
    assert deflated_sharpe([1.0] * 10, 3) is None
    assert deflated_sharpe([], 3) is None
