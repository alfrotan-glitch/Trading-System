"""Contract tests: no positive performance claims from distorted trade inputs."""
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research"))
from edge_gate import (
    evaluate_trades,
    BASIS_ACTUAL_FILLS,
    BASIS_PRE_SLIPPAGE,
    PROVENANCE_NATIVE,
    PROVENANCE_SIMULATED,
)

DEFAULT = {
    "gross_basis": BASIS_PRE_SLIPPAGE,
    "trials_tested": 1,
    "stress_extra_usd_per_trade": .10,
    "provenance": PROVENANCE_NATIVE,
}


def row(day, gross, fee=.10, slip=.05, trade_id="a", swap=0.0, broker_fee=0.0):
    return {
        "trade_id": trade_id,
        "date": day,
        "gross_usd": gross,
        "commission_usd": fee,
        "slippage_usd": slip,
        "swap_charge_usd": swap,
        "broker_fee_usd": broker_fee,
    }


def check(rows, days, **override):
    return evaluate_trades(rows, days, **(DEFAULT | override))


def test_no_trades_do_not_validate():
    r = check([], 20)
    assert r["status"] == "REJECTED_OR_INSUFFICIENT_EVIDENCE"
    assert r["trades_per_active_day"] == 0


def test_many_trades_but_negative_net_cannot_validate():
    x = [row(f"2026-08-{1+i//5:02d}", .1, trade_id=str(i)) for i in range(100)]
    r = check(x, 20)
    assert r["trades"] == 100
    assert r["net_usd"] < 0
    assert r["status"] == "REJECTED_OR_INSUFFICIENT_EVIDENCE"


def test_actual_fill_slippage_diagnostic_not_double_charged():
    x = [row("2026-08-01", 2, .2, .1)]
    pre = check(x, 1, gross_basis=BASIS_PRE_SLIPPAGE)
    native = check(x, 1, gross_basis=BASIS_ACTUAL_FILLS)
    assert pre["net_usd"] == 1.7
    assert native["net_usd"] == 1.8
    assert native["explicit_cost_usd_deducted"] == .2
    assert native["observed_slippage_usd_already_in_fill_gross"] == .1


def test_reject_invalid_money_and_unknown_basis():
    with pytest.raises(ValueError):
        check([row("2026-08-01", 2, fee=-1)], 1)
    with pytest.raises(ValueError):
        check([row("2026-08-01", 2)], 1, gross_basis="UNVERIFIED")


def test_reproducible_block_bootstrap():
    rows = [row(f"2026-08-{i+1:02d}", 1 if i % 2 else -1,
                trade_id=str(i)) for i in range(20)]
    assert check(rows, 20) == check(rows, 20)


def test_concentrated_winning_day_is_not_a_valid_edge():
    x = [row("2026-08-01", 1, trade_id=str(i)) for i in range(150)]
    r = check(x, 60)
    assert r["net_usd"] > 0
    assert r["status"] == "REJECTED_OR_INSUFFICIENT_EVIDENCE"
    assert r["days_with_trades"] == 1
    assert r["bootstrap_multiplicity_adjusted_99pct_lower_expectancy_usd"] is None


def test_not_inflate_counts_with_duplicate_ids():
    with pytest.raises(ValueError, match="duplicate"):
        check([row("2026-08-01", 2), row("2026-08-02", 2)], 10)


def test_invalid_calendar_day_is_rejected():
    with pytest.raises(ValueError, match="invalid Gregorian"):
        check([row("2026-02-30", 2)], 5)


def test_active_day_count_cannot_be_fewer_than_traded_days():
    with pytest.raises(ValueError, match="more trading days"):
        check([row("2026-08-01", 2),
               row("2026-08-02", 2, trade_id="b")], 1)


def test_simulated_and_zero_stress_cannot_pass_even_with_strong_pnl():
    first = date(2026, 6, 1)
    # 60 different dates across >=3 months, 3 completed trades each day.
    rows = [
        row((first + timedelta(days=2 * i)).isoformat(),
            3 if k < 2 else -1, trade_id=f"{i}-{k}")
        for i in range(60) for k in range(3)
    ]
    assert len({x["date"][:7] for x in rows}) >= 3
    simulated = check(rows, 120, provenance=PROVENANCE_SIMULATED)
    no_stress = check(rows, 120, stress_extra_usd_per_trade=0.0)
    assert simulated["status"] == "REJECTED_OR_INSUFFICIENT_EVIDENCE"
    assert no_stress["status"] == "REJECTED_OR_INSUFFICIENT_EVIDENCE"


def test_multiple_testing_cannot_fabricate_precision():
    first = date(2026, 6, 1)
    rows = [
        row((first + timedelta(days=2 * i)).isoformat(),
            3 if k < 2 else -1, trade_id=f"{i}-{k}")
        for i in range(60) for k in range(3)
    ]
    result = check(rows, 120, trials_tested=304)
    assert result["status"] == "REJECTED_OR_INSUFFICIENT_EVIDENCE"
    assert result["bootstrap_multiplicity_adjusted_99pct_lower_expectancy_usd"] is None


def test_missing_required_explicit_evidence_rejected():
    with pytest.raises(TypeError):
        evaluate_trades([], 1, gross_basis=BASIS_ACTUAL_FILLS,
                        trials_tested=1, provenance=PROVENANCE_NATIVE)


def test_favorable_fill_slippage_is_only_diagnostic():
    result = check([row("2026-08-01", 2, slip=-.2)], 1,
                   gross_basis=BASIS_ACTUAL_FILLS)
    assert result["net_usd"] == 1.9
    assert result["observed_slippage_usd_already_in_fill_gross"] == -.2
    with pytest.raises(ValueError):
        check([row("2026-08-01", 2, slip=-.2)], 1,
              gross_basis=BASIS_PRE_SLIPPAGE)


def test_swap_fee_costs_counted_exactly_once():
    x = [row("2026-08-01", 10, fee=.8, slip=.1,
             swap=.3, broker_fee=.2)]
    actual = check(x, 1, gross_basis=BASIS_ACTUAL_FILLS)
    estimated = check(x, 1, gross_basis=BASIS_PRE_SLIPPAGE)
    assert actual["net_usd"] == 8.7
    assert estimated["net_usd"] == 8.6
    credited = check([row("2026-08-01", 10, fee=.8, slip=0,
                         swap=-.5, broker_fee=.2)], 1)
    assert credited["net_usd"] == 9.5


def test_missing_broker_fees_or_swap_not_turned_into_zero():
    for missing in ("swap_charge_usd", "broker_fee_usd"):
        r = row("2026-08-01", 10)
        r.pop(missing)
        with pytest.raises(ValueError, match=missing):
            check([r], 1)


def _strong_rows():
    first = date(2026, 6, 1)
    return [
        row((first + timedelta(days=2 * i)).isoformat(), 3 if k < 2 else -1, trade_id=f"{i}-{k}")
        for i in range(60) for k in range(3)
    ]


def test_twenty_trials_now_have_tail_resolution():
    # Regression: at 2,000 bootstraps, trials_tested > 4 could never
    # resolve a tail, so a real 7-style search was unresolvable by
    # construction. At 20,000 bootstraps, 20 trials resolve.
    result = check(_strong_rows(), 120, trials_tested=20)
    assert result["max_trials_with_tail_resolution"] == 40
    assert result["bootstrap_multiplicity_adjusted_99pct_lower_expectancy_usd"] is not None
    assert result["bootstrap_multiplicity_adjusted_99pct_lower_expectancy_usd"] > 0
    assert result["status"] == "RESEARCH_POSITIVE_NOT_VALIDATED"


def test_forty_one_trials_stay_unresolved_and_warned():
    result = check(_strong_rows(), 120, trials_tested=41)
    assert result["bootstrap_multiplicity_adjusted_99pct_lower_expectancy_usd"] is None
    assert result["status"] == "REJECTED_OR_INSUFFICIENT_EVIDENCE"
    assert any("exceeds the bootstrap tail resolution" in w for w in result["warnings"])
