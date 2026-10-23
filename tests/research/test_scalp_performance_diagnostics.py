"""Guardrail and decomposition tests for existing scalp tick reports."""

from __future__ import annotations

from copy import deepcopy

import pytest

from qts.research.scalp_performance_diagnostics import analyze_scalp_tick_report


def trade(entry: int, net: str, *, side: str = "BUY", reason: str = "scalp_take_profit"):
    return {
        "signal_time_msc": entry - 60000,
        "entry_time_msc": entry, "exit_time_msc": entry + 500,
        "net_bps": net, "side": side, "family": "pre_breakout",
        "exit_reason": reason,
    }


def source():
    base = 1760918400000
    def mode(name, trades):
        return {
            "schema": "qts.scalp_tick_sequenced_replay.v1",
            "status": "RESEARCH_ONLY_QUOTE_EXECUTION_ASSUMED",
            "entry_mode": name, "raw_quote_rows": 20, "orders_submitted": 0,
            "strategy_promoted": False, "LIVE": "LOCKED",
            "trades": trades, "metrics": {"trades": len(trades)},
        }
    return {
        "source": {
            "manifest_dataset_sha256": "sha-synthetic",
            "holdout_excluded": True, "data_start_time_msc": base - 60000,
            "discovery_cutoff_time_msc": base + 22 * 86400000,
        },
        "tick_execution_replay": mode("confirmed", [
            trade(base, "3"),
            trade(base + 86400000, "-7", side="SELL", reason="tick_stop_quote_crossing"),
        ]),
        "anticipatory_comparison": {
            "tick_execution_replay": mode("anticipatory", [
                trade(base, "5"),
                trade(base + 8 * 86400000, "-5", reason="tick_stop_quote_crossing"),
            ]),
        },
    }


def test_diagnostics_reconcile_all_trades_and_exit_contributions():
    result = analyze_scalp_tick_report(source())
    confirmed = result["modes"]["confirmed"]
    early = result["modes"]["anticipatory"]
    assert confirmed["overall"]["mean_net_bps"] == -2
    assert confirmed["overall"]["win_rate"] == 0.5
    assert confirmed["overall"]["break_even_win_rate_for_observed_payoffs"] == 0.7
    assert confirmed["by_exit_reason"]["tick_stop_quote_crossing"]["sum_trade_bps_not_portfolio_return"] == -7
    assert early["overall"]["mean_net_bps"] == 0
    assert sum(x["trades"] for x in confirmed["fixed_calendar_thirds"].values()) == 2
    assert result["matched_utc_weeks"]["weeks_with_both_modes"] >= 1
    assert result["strategy_promoted"] is False and result["LIVE"] == "LOCKED"


def test_reject_holdout_exposure_and_missing_tick_modes():
    bad = source()
    bad["source"]["holdout_excluded"] = False
    with pytest.raises(ValueError, match="discovery-only"):
        analyze_scalp_tick_report(bad)
    bad = source()
    del bad["anticipatory_comparison"]
    with pytest.raises(ValueError, match="both completed"):
        analyze_scalp_tick_report(bad)


def test_reject_future_and_overlapping_trades():
    bad = source()
    bad["tick_execution_replay"]["trades"][1]["entry_time_msc"] = bad["source"]["discovery_cutoff_time_msc"]
    with pytest.raises(ValueError, match="noncausal"):
        analyze_scalp_tick_report(bad)
    bad = source()
    bad["tick_execution_replay"]["trades"][1]["entry_time_msc"] = (
        bad["tick_execution_replay"]["trades"][0]["entry_time_msc"]
    )
    with pytest.raises(ValueError, match="noncausal"):
        analyze_scalp_tick_report(bad)


def test_reject_mutated_unsafe_or_incomplete_reports():
    bad = source()
    bad["tick_execution_replay"]["LIVE"] = "UNLOCKED"
    with pytest.raises(ValueError, match="unsafe"):
        analyze_scalp_tick_report(bad)
    bad = source()
    bad["tick_execution_replay"]["metrics"]["trades"] = 3
    with pytest.raises(ValueError, match="counts disagree"):
        analyze_scalp_tick_report(bad)
    bad = source()
    bad["anticipatory_comparison"]["tick_execution_replay"]["raw_quote_rows"] = 19
    with pytest.raises(ValueError, match="identical quote histories"):
        analyze_scalp_tick_report(bad)


def test_no_trades_cannot_invent_performance():
    bad = source()
    bad["tick_execution_replay"]["trades"] = []
    bad["tick_execution_replay"]["metrics"]["trades"] = 0
    out = analyze_scalp_tick_report(bad)
    assert out["modes"]["confirmed"]["overall"]["mean_net_bps"] is None
    assert out["matched_utc_weeks"]["weeks_with_both_modes"] == 0
