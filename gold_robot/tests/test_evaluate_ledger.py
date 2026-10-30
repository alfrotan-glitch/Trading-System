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


def _write_hand_ledger(path, rows):
    import csv as _csv
    with path.open("w", newline="") as handle:
        writer = _csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_repaired_2x_costs_use_doubled_charges_including_slippage(tmp_path):
    # REPAIR 2026-10-30: the old code reported the 1x net (120) as the
    # "2x" figure and excluded slippage from its mean-cost stress.
    # Hand arithmetic, PRE_SLIPPAGE basis:
    #   gross 150, charged 15+15=30 -> 1x net 120, 1.5x net 105, 2x net 90.
    #   Slippage doubled (other charges 1x): 150 - (20 + 2*10) = 110.
    rows = [
        {"trade_id": "T1", "date": "2026-03-02", "gross_usd": "100",
         "commission_usd": "10", "slippage_usd": "5",
         "swap_charge_usd": "0", "broker_fee_usd": "0"},
        {"trade_id": "T2", "date": "2026-03-03", "gross_usd": "50",
         "commission_usd": "10", "slippage_usd": "5",
         "swap_charge_usd": "0", "broker_fee_usd": "0"},
    ]
    out = _run(_write_hand_ledger(tmp_path / "h.csv", rows),
               active_days=2, trials_tested=1, stress_extra=0.0)
    assert out["cost_multiples_net"]["1.0x"] == 120.0
    assert out["cost_multiples_net"]["1.5x"] == 105.0
    assert out["cost_multiples_net"]["2.0x"] == 90.0
    assert out["robustness_2x_costs_net"] == 90.0
    assert out["robustness_2x_costs_net"] != out["edge_gate"]["net_usd"]
    assert out["robustness_2x_costs_mean_charged_per_trade"] == 15.0
    assert out["robustness_slippage_doubled_net"] == 110.0
    assert out["robustness_spread"]["status"] == "NOT_MEASURABLE"


def test_2x_costs_do_not_double_count_actual_fill_slippage(tmp_path):
    # ACTUAL_EXECUTED_FILLS: slippage is already inside gross, so the
    # diagnostic slippage field must NOT be charged again at 1x or 2x.
    # gross 150, charged 20 -> 1x 130, 2x 110; slippage stress N/A.
    rows = [
        {"trade_id": "T1", "date": "2026-03-02", "gross_usd": "100",
         "commission_usd": "10", "slippage_usd": "5",
         "swap_charge_usd": "0", "broker_fee_usd": "0"},
        {"trade_id": "T2", "date": "2026-03-03", "gross_usd": "50",
         "commission_usd": "10", "slippage_usd": "5",
         "swap_charge_usd": "0", "broker_fee_usd": "0"},
    ]
    out = _run(_write_hand_ledger(tmp_path / "a.csv", rows),
               active_days=2, trials_tested=1, stress_extra=0.0,
               gross_basis="ACTUAL_EXECUTED_FILLS")
    assert out["cost_multiples_net"]["1.0x"] == 130.0
    assert out["robustness_2x_costs_net"] == 110.0
    assert out["robustness_slippage_doubled_net"] is None


def test_walk_forward_wfe_formula_and_undefined_negative_base():
    from evaluate_ledger import walk_forward
    daily = [(f"2026-03-{i + 1:02d}", v) for i, v in
             enumerate([10.0] * 5 + [20.0] * 5)]
    wf = walk_forward(daily, 5)
    assert wf["segments"][0]["wfe_net"] == 1.0  # OOS 20 / IS 20
    assert wf["segments"][1]["wfe_net"] == 0.75  # OOS 30 / IS 40
    assert wf["method"].startswith("expanding-window")
    assert wf["segments"][0]["in_sample_days"] == 2
    # Negative in-sample base: WFE is undefined, never fabricated.
    bad = [(f"2026-03-{i + 1:02d}", v) for i, v in
           enumerate([-10.0] * 2 + [10.0] * 8)]
    wf_bad = walk_forward(bad, 5)
    assert wf_bad["segments"][0]["wfe_net"] is None
    assert wf_bad["segments"][0]["oos_net"] == 20.0  # OOS judged on its own


def test_counterfactuals_best_static_and_random_router():
    from evaluate_ledger import counterfactuals
    cf = counterfactuals({
        "A": [("2026-03-02", 60.0), ("2026-03-03", 40.0)],
        "B": [("2026-03-02", 20.0), ("2026-03-03", 30.0)],
    }, draws=2000)
    assert cf["best_static"]["name"] == "A"
    assert cf["best_static"]["net"] == 100.0
    assert cf["random_router_expected"]["net"] == 75.0
    # Monte Carlo mean of a symmetric lottery: near 75, not exactly 75.
    assert abs(cf["random_router_mc"]["mean_net"] - 75.0) < 2.0
    single = counterfactuals({"A": [("2026-03-02", 1.0)]})
    assert single["status"] == "NOT_COMPUTABLE"


def test_shuffled_regime_placebo_detects_real_split(tmp_path):
    # 40 trades: regime X always +10, regime Y always -10. Under label
    # shuffling, X's net (+200) is essentially never reproduced, so
    # its placebo p must be ~0; a fabricated split would sit near 1.
    from evaluate_ledger import shuffled_regime_placebo
    trades = []
    for i in range(20):
        trades.append((f"2026-03-{(i % 20) + 1:02d}", 10.0, "X"))
    for i in range(20):
        trades.append((f"2026-03-{(i % 20) + 1:02d}", -10.0, "Y"))
    out = shuffled_regime_placebo(trades, permutations=200)
    assert out["status"] == "COMPUTED"
    assert out["per_regime"]["X"]["placebo_p_shuffled_net_ge_actual"] == 0.0
