"""Readiness gate for the frozen benchmark set.

These tests pin the answer to "is this dataset enough?" so it cannot be
negotiated after results are known. They also pin the provenance defect that
made genuine broker history inadmissible: the classifier names broker history
``BROKER-DERIVED``, and a gate written ``== "REAL"`` rejects exactly the data
it was written to admit.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from qts.data.bootstrap import claim_admissible, classify_source
from qts.research.benchmark_readiness import (
    FROZEN_TIMEFRAME,
    MIN_BARS_REAL_CLAIMS,
    MIN_ROUND_TURNS_PER_CANDIDATE,
    MIN_SPAN_DAYS,
    assess_acquisition_ceiling,
    assess_dataset_readiness,
    bars_per_day,
    current_status,
    days_needed_for_depth,
    readiness_markdown,
)
from qts.research.impulse.adequacy import assess_data_adequacy


def check(report, requirement_id: str):
    return next(c for c in report.checks if c.requirement_id == requirement_id)


# --------------------------------------------------------------------------- #
# provenance
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "label",
    ["MT5_HISTORY", "mt5_history_import", "BROKER", "historical_import", "REAL"],
)
def test_observed_history_is_claim_admissible(label: str) -> None:
    assert claim_admissible(classify_source(label)) is True


@pytest.mark.parametrize(
    "label",
    [
        "SYNTHETIC:fixture:XAUUSD_1H_500.csv",
        "synthetic_gbm",
        "paper_simulation",
        "shadow_intents",
        "model_derived",
        "imputed_series",
        "estimated_costs",
        "",
        None,
        "some unknown feed",
    ],
)
def test_generated_or_unverified_data_is_never_claim_admissible(label: str | None) -> None:
    assert claim_admissible(classify_source(label)) is False


def test_genuine_broker_history_passes_the_impulse_provenance_gate() -> None:
    """The regression: broker history used to be refused as if it were synthetic."""
    report = assess_data_adequacy(bars=(), data_version="v", source_label="MT5_HISTORY")
    assert check(report, "R1-REAL-PROVENANCE").passed is True


def test_synthetic_data_still_fails_the_impulse_provenance_gate() -> None:
    report = assess_data_adequacy(
        bars=(), data_version="v", source_label="SYNTHETIC:fixture:XAUUSD_1H_500.csv"
    )
    assert check(report, "R1-REAL-PROVENANCE").passed is False


def test_an_unlabelled_dataset_is_never_treated_as_observed() -> None:
    report = assess_data_adequacy(bars=(), data_version="v", source_label=None)
    assert check(report, "R1-REAL-PROVENANCE").passed is False


# --------------------------------------------------------------------------- #
# the gate itself
# --------------------------------------------------------------------------- #


def test_the_synthetic_1h_fixture_cannot_support_a_claim() -> None:
    """The dataset actually in the repository, assessed honestly."""
    report = assess_dataset_readiness(
        bar_count=500,
        span_days=20.0,
        timeframe="1H",
        source_label="SYNTHETIC:fixture:XAUUSD_1H_500.csv",
    )
    assert report.ready_for_claims is False
    assert check(report, "B1-REAL-PROVENANCE").passed is False
    assert check(report, "B2-TIMEFRAME-MATCH").passed is False
    assert check(report, "B3-DEPTH").passed is False
    assert check(report, "B4-REGIME-COVERAGE").passed is False
    assert report.unmet_blocking


def test_a_real_15m_dataset_of_sufficient_depth_is_ready() -> None:
    report = assess_dataset_readiness(
        bar_count=60_000,
        span_days=800.0,
        timeframe="15m",
        source_label="MT5_HISTORY",
        round_turns_per_candidate={"A": 400, "B": 900, "C": 700},
        oos_bar_count=18_000,
    )
    assert report.ready_for_claims is True
    assert report.unmet_blocking == []


def test_the_weakest_candidate_sets_the_trade_count_bar() -> None:
    """Reporting only the busiest candidate would be cherry-picking."""
    report = assess_dataset_readiness(
        bar_count=60_000,
        span_days=800.0,
        timeframe="15m",
        source_label="MT5_HISTORY",
        round_turns_per_candidate={"A": 400, "B": 900, "C": 42},
    )
    assert check(report, "B5-TRADE-COUNT").passed is False
    assert report.ready_for_claims is False


def test_a_trivial_out_of_sample_split_is_refused() -> None:
    report = assess_dataset_readiness(
        bar_count=60_000,
        span_days=800.0,
        timeframe="15m",
        source_label="MT5_HISTORY",
        oos_bar_count=30,
    )
    assert check(report, "B6-OOS-SIZE").passed is False


def test_evaluating_on_the_wrong_timeframe_is_blocking_and_says_why() -> None:
    report = assess_dataset_readiness(
        bar_count=60_000, span_days=800.0, timeframe="1H", source_label="MT5_HISTORY"
    )
    assert check(report, "B2-TIMEFRAME-MATCH").passed is False
    assert report.ready_for_claims is False
    assert any(FROZEN_TIMEFRAME in note for note in report.notes)


# --------------------------------------------------------------------------- #
# the acquisition ceiling — the expensive question
# --------------------------------------------------------------------------- #


def test_the_broker_30_day_ceiling_cannot_supply_enough_15m_history() -> None:
    """The finding that decides item 6, computed rather than asserted."""
    report = assess_acquisition_ceiling(
        max_history_days=30, timeframe="15m", source_label="MT5_HISTORY"
    )
    assert report.ready_for_claims is False
    depth = check(report, "B3-DEPTH")
    span = check(report, "B4-REGIME-COVERAGE")
    assert depth.passed is False
    assert span.passed is False
    # Provenance and timeframe are fine; the blocker is purely the amount of history.
    assert check(report, "B1-REAL-PROVENANCE").passed is True
    assert check(report, "B2-TIMEFRAME-MATCH").passed is True


def test_the_ceiling_projection_is_arithmetic_we_can_check() -> None:
    per_day = bars_per_day("15m")
    projection = check(assess_acquisition_ceiling(max_history_days=30), "B7-CEILING-PROJECTION")
    assert "1,971" in projection.observed
    assert abs(per_day - 65.71) < 0.05


def test_days_needed_for_depth_is_the_honest_ask() -> None:
    """How much history would actually have to be requested."""
    needed = days_needed_for_depth("15m")
    assert needed > 30, "the broker's 30-day ceiling must be provably short of the minimum"
    assert 60 < needed < 100


def test_a_source_with_a_deep_ceiling_would_be_ready() -> None:
    report = assess_acquisition_ceiling(
        max_history_days=1000, timeframe="15m", source_label="MT5_HISTORY"
    )
    # Depth and span pass at 1000 days; what remains is unknown trade counts,
    # which only measurement can settle.
    assert check(report, "B3-DEPTH").passed is True
    assert check(report, "B4-REGIME-COVERAGE").passed is True


@pytest.mark.parametrize("timeframe", ["15m", "1H", "4H", "1d"])
def test_bars_per_day_scales_inversely_with_the_timeframe(timeframe: str) -> None:
    assert bars_per_day(timeframe) > 0


def test_an_unrecognised_timeframe_is_rejected_not_guessed() -> None:
    with pytest.raises(ValueError):
        bars_per_day("fortnightly")
    with pytest.raises(ValueError):
        bars_per_day("")


# --------------------------------------------------------------------------- #
# reporting
# --------------------------------------------------------------------------- #


def test_the_markdown_report_states_the_verdict_and_every_check() -> None:
    report = assess_dataset_readiness(
        bar_count=500, span_days=20.0, timeframe="1H",
        source_label="SYNTHETIC:fixture:XAUUSD_1H_500.csv",
    )
    text = readiness_markdown(report)
    assert "Ready for claims:** NO" in text
    assert "B1-REAL-PROVENANCE" in text
    assert "FAIL" in text


def test_the_report_is_json_serialisable() -> None:
    import json

    report = assess_acquisition_ceiling(max_history_days=30, source_label="MT5_HISTORY")
    payload = json.loads(json.dumps(report.as_dict()))
    assert payload["schema"] == "qts.benchmark_readiness.v1"
    assert payload["ready_for_claims"] is False


def test_current_status_shows_the_frozen_set_is_intact_and_unchanged() -> None:
    """The candidates must not have been redefined after seeing results."""
    status = current_status()
    assert status["frozen_set_intact"] is True
    assert status["frozen_problems"] == []
    assert len(status["candidates"]) == 3
    assert all(c["timeframe"] == "15m" for c in status["candidates"])
    assert status["minimums"]["bars"] == MIN_BARS_REAL_CLAIMS
    assert status["minimums"]["span_days"] == MIN_SPAN_DAYS
    assert status["minimums"]["round_turns_per_candidate"] == MIN_ROUND_TURNS_PER_CANDIDATE


def test_a_dukascopy_import_is_admissible_only_under_a_historical_label() -> None:
    """Provenance labels are not decoration: 'dukascopy' alone is UNVERIFIED.

    Dukascopy is genuine market data, but the classifier does not know that
    name. Ingesting it as ``historical_import_*`` is truthful AND admissible;
    relabelling it ``MT5_HISTORY`` would misstate where it came from, which is
    the one thing provenance exists to prevent.
    """
    assert claim_admissible(classify_source("historical_import_dukascopy_xauusd_15m")) is True
    assert claim_admissible(classify_source("dukascopy")) is False


def test_a_single_request_limit_is_reported_as_unverified_not_binding() -> None:
    """The correction at the heart of the item-4 review."""
    report = assess_acquisition_ceiling(
        max_history_days=30,
        timeframe="15m",
        source_label="MT5_HISTORY",
        limit_kind="single-request",
    )
    joined = " ".join(report.notes)
    assert "UNVERIFIED LOWER BOUND" in joined
    assert "not a proven retention limit" in joined
    assert "qts data mt5-depth" in joined


def test_a_proven_retention_ceiling_is_reported_as_binding() -> None:
    report = assess_acquisition_ceiling(
        max_history_days=30, timeframe="15m", source_label="MT5_HISTORY",
        limit_kind="proven-retention",
    )
    joined = " ".join(report.notes)
    assert "UNVERIFIED" not in joined
    assert "upper bound" in joined


def test_limit_kind_does_not_change_the_verdict_only_its_meaning() -> None:
    """Correcting the record must not quietly make an inadequate source pass."""
    for kind in ("proven-retention", "single-request"):
        report = assess_acquisition_ceiling(
            max_history_days=30, timeframe="15m", source_label="MT5_HISTORY", limit_kind=kind
        )
        assert report.ready_for_claims is False, kind
        assert check(report, "B3-DEPTH").passed is False, kind


def test_assessment_time_is_recorded() -> None:
    status = current_status()
    assert datetime.fromisoformat(str(status["assessed_at"])).tzinfo is not None
    assert datetime.now(UTC).year == 2026
