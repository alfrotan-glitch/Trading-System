"""Guards on the committed benchmark evidence file.

``data/evidence/benchmark_candidates.json`` is evidence. A row in it must not
claim eligibility that the code's own rules would deny, must use only cost bases
the code can produce, and must keep its money fields arithmetically consistent.

These tests exist because on 2026-10-18 a row was edited by hand to say
``claim_eligible: true`` while its own gates failed, and its money fields no
longer matched its own expectancy field. Nothing in the suite caught it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from qts.research.costs import CostBasis

REPO = Path(__file__).resolve().parents[2]
EVIDENCE = REPO / "data" / "evidence" / "benchmark_candidates.json"


@pytest.fixture(scope="module")
def payload() -> dict:
    return json.loads(EVIDENCE.read_text(encoding="utf-8"))


def test_no_row_is_claim_eligible_when_its_own_gates_fail(payload):
    """The code's rule: claim needs trades, a matching timeframe, a claim-eligible dataset and MEASURED costs."""
    for obs in payload["observations"]:
        if not obs["claim_eligible"]:
            continue
        assert obs["round_turns"] > 0, obs["benchmark_id"]
        assert obs["timeframe_matches"] is True, obs["benchmark_id"]
        assert obs["mechanism_only"] is False, obs["benchmark_id"]
        assert payload["dataset_claim_eligible"] is True, obs["benchmark_id"]


def test_the_file_currently_declares_no_claim(payload):
    assert payload["dataset_claim_eligible"] is False
    assert all(o["claim_eligible"] is False for o in payload["observations"])
    assert payload["cost_model"]["claim_eligible"] is False


def test_cost_bases_are_the_bases_the_code_defines(payload):
    valid = {b.value for b in CostBasis}
    for comp in payload["cost_model"]["components"]:
        assert comp["basis"] in valid, comp["name"]


def test_model_claim_flag_matches_its_components(payload):
    comps = payload["cost_model"]["components"]
    all_measured = bool(comps) and all(c["basis"] == CostBasis.MEASURED.value for c in comps)
    assert payload["cost_model"]["claim_eligible"] is all_measured


def test_money_fields_are_arithmetically_consistent(payload):
    """Net = gross - modelled cost; expectancy = net / round turns; break-even = gross / cost."""
    for obs in payload["observations"]:
        n = obs["round_turns"]
        if n == 0:
            continue
        gross, cost, net = obs["gross_pnl_usd"], obs["cost_usd"], obs["net_pnl_usd"]
        assert net == pytest.approx(gross - cost, abs=0.01), obs["benchmark_id"]
        assert obs["net_expectancy_per_trade"] == pytest.approx(net / n, abs=0.001), obs["benchmark_id"]
        if cost > 0:
            assert obs["break_even_cost_multiple"] == pytest.approx(gross / cost, abs=0.01), obs["benchmark_id"]


def test_a_not_evaluated_row_carries_no_numbers(payload):
    for obs in payload["observations"]:
        if any("NOT EVALUATED" in r for r in obs["reasons"]):
            assert obs["round_turns"] == 0
            assert obs["gross_pnl_usd"] == 0.0
            assert obs["net_pnl_usd"] == 0.0
            assert obs["claim_eligible"] is False


def test_no_hand_written_claim_text_remains():
    text = EVIDENCE.read_text(encoding="utf-8").upper()
    for banned in ("VALIDATED CLAIM", "USER-AUTHORIZED", "MEASURED_FROM_DOCUMENTATION"):
        assert banned not in text, banned
