import pytest
from gold_robot.research.sim_limit import Result
from gold_robot.research.target_grid import Trial, compare_targets


def outcome(name, net):
    return Result(name, 10 if name != "pending_unfilled" else None,
                  20 if name in {"target", "stop", "timeout"} else None,
                  net, net)


def test_win_rate_not_selection_objective():
    trials = [
        Trial("a", "2026-10-01", .5, outcome("target", .5)),
        Trial("b", "2026-10-01", .5, outcome("stop", -3)),
        Trial("a", "2026-10-01", 1.0, outcome("target", 2)),
        Trial("b", "2026-10-01", 1.0, outcome("pending_unfilled", 0)),
    ]
    score = compare_targets(trials, 1)
    assert score[0]["target_r"] == 1
    assert score[0]["net_per_signal_usd"] == 1
    assert score[0]["candidate_only"]


def test_comparable_original_signals_required():
    with pytest.raises(ValueError, match="identical"):
        compare_targets([Trial("a", "2026-10-01", 1, outcome("target", 1)),
                         Trial("b", "2026-10-01", 2, outcome("target", 2))], 1)


def test_unresolved_not_qualified():
    x = compare_targets([Trial("a", "2026-10-01", 1, outcome("open_at_end", 0))], 1)[0]
    assert x["unresolved"] == 1 and not x["valid_for_ranking"]


def test_unfilled_excluded_from_tp_reach():
    x = compare_targets([Trial("a", "2026-10-01", 1, outcome("pending_unfilled", 0)),
                         Trial("b", "2026-10-01", 1, outcome("target", 1))], 1)[0]
    assert x["fill_rate"] == .5 and x["tp_first_per_fill"] == 1.0


def test_duplicate_and_nonfinite_refused():
    a = Trial("a", "2026-10-01", 1, outcome("target", 1))
    with pytest.raises(ValueError, match="duplicated"):
        compare_targets([a, a], 1)
    with pytest.raises(ValueError):
        compare_targets([Trial("a", "2026-10-01", float('nan'), outcome("stop", -1))], 1)
