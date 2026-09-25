"""Trade-level transparency tests for the existing impulse event outcomes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from qts.research.impulse import render_markdown_report, summarize_event_outcomes
from qts.research.impulse.costs import CostAssumptions


class TestEventOutcomeSummary:
    def test_counts_classification_and_metrics_use_all_measured_outcomes(self):
        # These are net event returns, so zero is a real break-even outcome,
        # not missing data. Win rate denominator is all five outcomes.
        summary = summarize_event_outcomes([10.0, -5.0, 0.0, 20.0, -10.0], declared_round_turn_cost_bps=3.4)

        assert summary["status"] == "AVAILABLE"
        assert summary["unit"] == "measured_directional_event_outcome"
        assert summary["measured_event_count"] == 5
        assert summary["outcome_count"] == 5
        assert summary["wins"] == 2
        assert summary["losses"] == 2
        assert summary["breakeven"] == 1
        assert summary["win_rate"] == pytest.approx(2 / 5)
        assert summary["average_winner_bps"] == pytest.approx(15.0)
        assert summary["average_loser_bps"] == pytest.approx(-7.5)
        assert summary["profit_factor"] == pytest.approx(30 / 15)
        assert summary["expectancy_per_event_bps"] == pytest.approx(3.0)
        assert summary["net_result_bps"] == pytest.approx(15.0)
        assert summary["declared_round_turn_cost_bps"] == pytest.approx(3.4)

    def test_net_result_sums_event_returns_after_declared_cost(self):
        costs = CostAssumptions(
            spread_bps=2.0,
            commission_bps_round_turn=0.4,
            slippage_bps_per_side=0.5,
        )
        gross = [10.0, -5.0, 0.0]
        net = [costs.net_bps(value) for value in gross]
        summary = summarize_event_outcomes(
            net,
            declared_round_turn_cost_bps=costs.round_turn_cost_bps(),
        )

        assert costs.round_turn_cost_bps() == pytest.approx(3.4)
        assert summary["net_result_bps"] == pytest.approx(sum(net))
        assert summary["expectancy_per_event_bps"] == pytest.approx(sum(net) / len(net))

    def test_profit_factor_is_unavailable_without_a_loss_denominator(self):
        summary = summarize_event_outcomes([1.0, 2.0])

        assert summary["wins"] == 2
        assert summary["losses"] == 0
        assert summary["profit_factor"] is None
        assert summary["average_loser_bps"] is None

    def test_missing_outcome_is_unavailable_not_zero(self):
        summary = summarize_event_outcomes([10.0, None, -2.0], declared_round_turn_cost_bps=3.4)

        assert summary["status"] == "UNAVAILABLE"
        assert summary["measured_event_count"] == 3
        assert summary["outcome_count"] is None
        assert summary["wins"] is None
        assert summary["losses"] is None
        assert summary["win_rate"] is None
        assert summary["average_winner_bps"] is None
        assert summary["average_loser_bps"] is None
        assert summary["profit_factor"] is None
        assert summary["expectancy_per_event_bps"] is None
        assert summary["net_result_bps"] is None

    def test_no_outcomes_has_zero_count_but_unavailable_rates(self):
        summary = summarize_event_outcomes([])

        assert summary["status"] == "UNAVAILABLE"
        assert summary["measured_event_count"] == 0
        assert summary["outcome_count"] == 0
        assert summary["wins"] == 0
        assert summary["losses"] == 0
        assert summary["win_rate"] is None
        assert summary["expectancy_per_event_bps"] is None
        assert summary["net_result_bps"] is None


class TestResearchReportOutcomeTransparency:
    def test_legacy_real_evidence_renders_outcomes_without_rewriting_artifact(self):
        evidence_path = Path("data/evidence/impulse_research_xauusd_dukascopy_15m.json")
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        report = render_markdown_report(evidence)

        # The current result and provenance are read, not recalculated into a
        # new evidence artifact. The report must retain both safety conclusion
        # and REAL classification while exposing existing event outcomes.
        assert evidence["conclusion"]["conclusion"] == "REGIME_DEPENDENT"
        assert evidence["conclusion"]["go_block"] == "BLOCK"
        assert evidence["provenance"]["data_class"] == "REAL"
        assert "Event-outcome transparency" in report
        assert "measured directional outcomes: 3759" in report
        assert "100 W/L/BE" in report
        assert "profit factor" in report
        assert "aggregate net" in report
        assert "No single all-family win/loss rate" in report

    def test_synthetic_provenance_and_block_are_not_changed_by_report(self):
        evidence_path = Path("data/evidence/impulse_research.json")
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        report = render_markdown_report(evidence)

        assert evidence["provenance"]["data_class"] == "SYNTHETIC"
        assert evidence["conclusion"]["go_block"] == "BLOCK"
        assert "Event-outcome transparency" in report
        assert "measured directional outcomes" in report
