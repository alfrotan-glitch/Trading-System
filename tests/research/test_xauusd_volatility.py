"""Locks for the volatility economic filter. These do not open the held-out span."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from qts.research.xauusd_volatility import (
    ADJACENT_DOLLARS,
    ADJACENT_RATIO,
    DEGRADED_LIFT,
    DELAY_LIFT,
    DELAY_RATIO,
    EXTREME_VOL,
    HIGH_VOL,
    LOW_VOL,
    MATERIAL_DOLLARS,
    RATIO_FLOOR,
    TIME_RATIO_MAX,
    VolatilityScan,
    apply_verdicts,
    quote_states,
    time_median,
)


def _scan(**kwargs) -> VolatilityScan:
    settings = {
        "horizons": (4, 8),
        "primary": 4,
        "stability": 8,
        "passage_cap": 6,
        "carry": 80,
    }
    settings.update(kwargs)
    return VolatilityScan(0, 10**12, **settings)


def _flat(n: int, bid: float = 2000.0, spread: float = 0.22) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    prices = np.full(n, bid, dtype=np.float64)
    return prices, prices + spread, np.arange(n, dtype=np.int64) * 1000


def _mid(level: int, n: int = 40) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mid = np.zeros(n, dtype=np.int64)
    spread = np.full(n, 22, dtype=np.int64)
    locked = np.zeros(n, dtype=bool)
    return mid, spread, locked


def _passing_item(*, mean_a: float, mean_b: float, kind: str) -> dict:
    n = 1000
    var = 0.01

    def side(mean: float) -> tuple[list[int], list[float], list[float]]:
        return [n, n, n], [n * mean, n * mean, n * mean], [var * (n - 1) + n * mean * mean] * 3

    a_n, a_sum, a_sq = side(mean_a)
    b_n, b_sum, b_sq = side(mean_b)
    item = {
        "a_n": a_n,
        "a_sum": a_sum,
        "a_sumsq": a_sq,
        "b_n": b_n,
        "b_sum": b_sum,
        "b_sumsq": b_sq,
        "delay_a_n": a_n,
        "delay_a_sum": [n * mean_a * 1.2, n * mean_a * 1.2, n * mean_a * 1.2],
        "delay_b_n": b_n,
        "delay_b_sum": b_sum,
        "longer_a_n": 3000,
        "longer_a_sum": 3000 * mean_a * 1.2,
        "longer_b_n": 3000,
        "longer_b_sum": 3000 * mean_b,
    }
    if kind == "economic":
        item.update(
            {
                "a_degraded": [800, 800, 800],
                "b_degraded": [600, 600, 600],
                "delay_a_degraded": [750, 750, 750],
                "delay_b_degraded": [600, 600, 600],
                "a_resolved": 2700,
                "a_censored": 300,
                "a_median": 20.0,
                "b_resolved": 2700,
                "b_censored": 300,
                "b_median": 40.0,
                "delay_a_resolved": 2700,
                "delay_a_censored": 300,
                "delay_a_median": 22.0,
                "delay_b_resolved": 2700,
                "delay_b_censored": 300,
                "delay_b_median": 44.0,
            }
        )
    return item


def _measured() -> dict:
    return {
        "nonmonotonic": 0,
        "tests": {
            "H-VL-01": _passing_item(mean_a=1.10, mean_b=0.70, kind="economic"),
            "H-VL-02": _passing_item(mean_a=1.30, mean_b=1.00, kind="magnitude"),
            "H-VL-03": _passing_item(mean_a=1.20, mean_b=0.70, kind="magnitude"),
            "H-VL-04": _passing_item(mean_a=1.30, mean_b=1.00, kind="magnitude"),
        },
    }


def test_floors_are_the_locked_cuts() -> None:
    assert LOW_VOL == 0.10
    assert HIGH_VOL == 0.20
    assert EXTREME_VOL == 0.40
    assert RATIO_FLOOR == 1.25
    assert ADJACENT_RATIO == 1.15
    assert DELAY_RATIO == 1.10
    assert DEGRADED_LIFT == 0.05
    assert DELAY_LIFT == 0.02
    assert TIME_RATIO_MAX == 0.80
    assert MATERIAL_DOLLARS == 0.22
    assert ADJACENT_DOLLARS == 0.10
    text = Path("docs/xauusd_volatility_preregistration.md").read_text(encoding="utf-8")
    assert "H-ST-02" in text
    assert "not a strategy" in text.lower() or "Not a strategy" in text


def test_extreme_is_a_subset_and_the_boundary_is_a_burst() -> None:
    mid, spread, locked = _mid(0)
    mid[16:] = 40
    states = quote_states(mid, spread, locked)
    assert states["vol_high"][16]
    assert states["vol_high_not_extreme"][16]
    assert not states["vol_extreme"][16]
    mid[16:] = 80
    states = quote_states(mid, spread, locked)
    assert states["vol_extreme"][16] and states["vol_high"][16]
    assert not states["vol_high_not_extreme"][16]
    assert not np.any(states["vol_extreme"] & ~states["vol_high"])
    mid[16:] = 20
    states = quote_states(mid, spread, locked)
    assert states["vol_low"][16] and not states["vol_normal"][16]
    mid[16:] = 30
    states = quote_states(mid, spread, locked)
    assert states["vol_normal"][16]


def test_onset_does_not_read_the_future_and_groups_are_disjoint() -> None:
    mid, spread, locked = _mid(0, 80)
    mid[20] = 20
    states = quote_states(mid, spread, locked)
    assert states["quiet_to_expansion"][20]
    assert not states["stay_quiet"][20]
    mid[20] = 19
    states = quote_states(mid, spread, locked)
    assert states["stay_quiet"][20]
    assert not states["quiet_to_expansion"][20]
    mid[16] = 40
    mid[20] = 80
    states = quote_states(mid, spread, locked)
    assert states["persistent_high"][20]
    assert not states["contraction_onset"][20]
    mid[20] = 40
    states = quote_states(mid, spread, locked)
    assert states["contraction_onset"][20]
    assert not states["persistent_high"][20]
    future = mid.copy()
    future[21] = 999
    before = quote_states(mid, spread, locked)
    after = quote_states(future, spread, locked)
    for name in ("quiet_to_expansion", "stay_quiet", "persistent_high", "contraction_onset", "vol_high"):
        assert np.array_equal(before[name][:21], after[name][:21])


def test_a_locked_quote_inside_the_window_is_not_a_state() -> None:
    mid, spread, locked = _mid(0)
    mid[16] = 80
    locked[10] = True
    states = quote_states(mid, spread, locked)
    assert not states["vol_high"][16]
    assert not states["vol_extreme"][16]


def test_time_median_averages_the_two_middle_hits() -> None:
    counts = np.zeros(6, dtype=np.int64)
    counts[5] = 1
    assert time_median(counts) == 5
    counts = np.zeros(5, dtype=np.int64)
    counts[2] = 2
    counts[4] = 2
    assert time_median(counts) == 3


def test_move_is_dollars_and_two_cents_is_stricter_than_the_spread() -> None:
    bid, ask, stamp = _flat(30)
    bid[9:] += 0.23
    ask = bid + 0.22
    scan = _scan()
    scan.add_batch(bid, ask, stamp)
    cell = scan.finish()["panel"]["4"]["unconditional"]
    assert cell["n"] == 5
    assert cell["mean_abs"] == pytest.approx(0.23 / 5)
    assert cell["p_exceed_spread"] == pytest.approx(0.2)
    assert cell["p_exceed_spread_plus_0_02"] == 0


def test_split_batches_match_one_batch() -> None:
    rng = np.random.default_rng(7)
    n = 220
    bid = 2000.0 + np.cumsum(rng.normal(0, 0.03, n))
    ask = bid + 0.22
    stamp = np.arange(n, dtype=np.int64) * 100
    one = _scan()
    split = _scan()
    one.add_batch(bid, ask, stamp)
    split.add_batch(bid[:100], ask[:100], stamp[:100])
    split.add_batch(bid[100:], ask[100:], stamp[100:])
    assert one.n.tolist() == split.n.tolist()
    assert np.allclose(one.abs_sum, split.abs_sum)
    assert np.allclose(one.t_abs, split.t_abs)
    assert np.allclose(one.d_abs, split.d_abs)
    assert one.hit_resolved.tolist() == split.hit_resolved.tolist()
    assert one.hit_censored.tolist() == split.hit_censored.tolist()
    assert one.delay_resolved.tolist() == split.delay_resolved.tolist()
    assert one.transition.tolist() == split.transition.tolist()
    assert one.persistence_hist.tolist() == split.persistence_hist.tolist()
    assert one.finish()["hypotheses"] == split.finish()["hypotheses"]


def test_locked_prices_do_not_change_discovery_results() -> None:
    bid, ask, stamp = _flat(90)
    bid[20] = 2001.0
    ask = bid + 0.22
    cutoff = 40 * 1000
    changed = bid.copy()
    changed[40:] += 50.0
    changed_ask = changed + 0.22
    kwargs = {"horizons": (4,), "primary": 4, "stability": 8, "passage_cap": 6, "carry": 80}
    first = VolatilityScan(0, cutoff, **kwargs)
    second = VolatilityScan(0, cutoff, **kwargs)
    first.add_batch(bid, ask, stamp)
    second.add_batch(changed, changed_ask, stamp)
    assert first.finish()["panel"] == second.finish()["panel"]
    assert first.finish()["passage"] == second.finish()["passage"]


def test_a_jump_on_the_next_quote_resolves_immediately_and_not_after_delay() -> None:
    bid, ask, stamp = _flat(50)
    bid[32:] += 1.0
    ask = bid + 0.22
    scan = VolatilityScan(0, 10**12, horizons=(4,), primary=30, stability=8, passage_cap=6, carry=80)
    scan.add_batch(bid, ask, stamp)
    report = scan.finish()
    low = report["passage"]["vol_low"]
    assert low["resolved"] == 1
    assert low["median_quotes_spread_plus_0_01"] == 1
    assert low["delay_resolved"] == 0
    assert low["delay_censored"] == 1


def test_backward_time_is_inconclusive_and_does_not_promote() -> None:
    bid, ask, stamp = _flat(30)
    stamp[10] = stamp[9] - 1
    scan = _scan(horizons=(4,), primary=4)
    scan.add_batch(bid, ask, stamp)
    report = scan.finish()
    assert scan.nonmonotonic > 0
    assert report["decision"] == "INCONCLUSIVE"
    assert report["strategy_promoted"] is False
    assert report["held_out_span_opened"] is False
    assert {row["status"] for row in report["hypotheses"].values()} == {"INCONCLUSIVE"}


def test_positive_status_is_tested_not_a_strategy() -> None:
    verdicts = apply_verdicts(_measured())
    assert set(verdicts) == {"H-VL-01", "H-VL-02", "H-VL-03", "H-VL-04"}
    for verdict in verdicts.values():
        assert verdict["status"] == "TESTED"
        assert verdict["status"] not in {"PROMISING", "ROBUST"}
        assert verdict["not_a_strategy"] is True
        assert verdict["held_out_span_opened"] is False
        assert "not a strategy" in verdict["claim"]


def test_failure_to_reproduce_h_st_02_is_not_a_new_rejection() -> None:
    measured = _measured()
    measured["tests"]["H-VL-01"] = _passing_item(mean_a=1.10, mean_b=1.00, kind="economic")
    verdict = apply_verdicts(measured)["H-VL-01"]
    assert verdict["status"] == "INCONCLUSIVE"
    assert "reproduce" in verdict["reason"]


def test_missed_cost_time_and_delay_floors_reject() -> None:
    measured = _measured()
    item = measured["tests"]["H-VL-01"]
    item["a_degraded"] = [610, 610, 610]
    assert apply_verdicts(measured)["H-VL-01"]["status"] == "REJECTED"
    measured = _measured()
    measured["tests"]["H-VL-01"]["a_median"] = 38.0
    measured["tests"]["H-VL-01"]["delay_a_median"] = 38.0
    assert apply_verdicts(measured)["H-VL-01"]["status"] == "REJECTED"
    measured = _measured()
    measured["tests"]["H-VL-02"]["delay_a_sum"] = measured["tests"]["H-VL-02"]["b_sum"]
    assert apply_verdicts(measured)["H-VL-02"]["status"] == "REJECTED"


def test_unresolved_waiting_time_and_small_delay_sample_are_inconclusive() -> None:
    measured = _measured()
    item = measured["tests"]["H-VL-01"]
    item["a_resolved"] = 100
    item["a_censored"] = 2900
    assert apply_verdicts(measured)["H-VL-01"]["status"] == "INCONCLUSIVE"
    measured = _measured()
    measured["tests"]["H-VL-02"]["delay_a_n"] = [10, 10, 10]
    assert apply_verdicts(measured)["H-VL-02"]["status"] == "INCONCLUSIVE"


def test_tercile_and_horizon_disagreement_reject_without_promoting() -> None:
    measured = _measured()
    measured["tests"]["H-VL-03"]["a_sum"][1] = 100
    verdict = apply_verdicts(measured)["H-VL-03"]
    assert verdict["status"] == "REJECTED"
    measured = _measured()
    measured["tests"]["H-VL-04"]["longer_a_sum"] = 1000
    assert apply_verdicts(measured)["H-VL-04"]["status"] == "REJECTED"
    measured = _measured()
    measured["tests"]["H-VL-04"]["longer_a_n"] = 10
    assert apply_verdicts(measured)["H-VL-04"]["status"] == "TESTED"


def test_a_dollar_gap_below_the_floor_rejects() -> None:
    measured = _measured()
    item = _passing_item(mean_a=0.12, mean_b=0.10, kind="magnitude")
    measured["tests"]["H-VL-02"] = item
    verdict = apply_verdicts(measured)["H-VL-02"]
    assert verdict["status"] == "REJECTED"
    assert "dollar" in verdict["reason"]


def test_workflow_cannot_retrigger_the_state_scan() -> None:
    text = Path(".github/workflows/canonical-xauusd-volatility.yml").read_text(encoding="utf-8")
    assert "xauusd_state_scan.py" not in text
    assert "xauusd_volatility_preregistration" not in text
    assert "src/qts/research/xauusd_volatility.py" in text
    assert "scripts/run_xauusd_volatility.py" in text
    assert "arena/01a0c9cc-trading-system" in text
