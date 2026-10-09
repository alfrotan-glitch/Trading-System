"""Readiness gate for evaluating the FROZEN benchmark set — fail closed.

Why this exists
---------------
The three preregistered candidates (``qts.research.benchmarks``) are defined on
**15-minute** bars. The only canonical dataset in the repository is a synthetic
1-hour fixture. Running the candidates on it produces numbers, and those numbers
are worthless as evidence — but they *look* like evidence in a report.

This module answers, before any compute is spent, one question: **can this
dataset support a claim about these candidates?** It answers it against
pre-registered minimums so the answer cannot be negotiated after seeing
results.

It also answers the acquisition question, which is the expensive one: given a
history source with a known retention ceiling, is it even *possible* to obtain
enough data? Computing that before an acquisition run is the difference between
a day's work and a dead end discovered at the end of it.

Nothing here promotes a candidate, and nothing here can be satisfied by
synthetic data: ``REAL`` provenance is a blocking requirement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from qts.data.bootstrap import CLAIM_INADMISSIBLE_REASONS, claim_admissible, classify_source

# --------------------------------------------------------------------------- #
# Pre-registered minimums for evaluating the frozen set.
#
# These are deliberately the SAME thresholds the impulse research layer already
# enforces (qts.research.impulse.adequacy). Two gates with two different
# answers to "is this enough data?" would let a dataset be inadmissible for one
# kind of claim and admissible for another, which is not a distinction that
# survives scrutiny.
# --------------------------------------------------------------------------- #
MIN_BARS_REAL_CLAIMS = 5000
TARGET_BARS_REAL_CLAIMS = 17520
MIN_SPAN_DAYS = 180
#: Per candidate. Three candidates are evaluated at once, so the effective
#: multiple-testing burden is higher than for a single hypothesis.
MIN_ROUND_TURNS_PER_CANDIDATE = 100
#: An out-of-sample split is meaningless below this many bars in the held-out
#: portion: a handful of trades in one month is one regime, not a test.
MIN_OOS_BARS = 500

#: The frozen set is defined on 15m. Evaluation on any other timeframe is
#: mechanism-only and is reported as such (never silently, never as a claim).
FROZEN_TIMEFRAME = "15m"

#: Bars per unit of calendar time, used to convert a retention ceiling into a
#: bar count. XAUUSD trades ~23h/day, 5 days/week.
TRADING_SESSIONS_PER_WEEK = 5
TRADING_HOURS_PER_SESSION = 23.0

_BARS_PER_MINUTE: dict[str, float] = {}


def bars_per_day(timeframe: str, *, hours_per_session: float = TRADING_HOURS_PER_SESSION,
                 sessions_per_week: float = TRADING_SESSIONS_PER_WEEK) -> float:
    """Expected bars per CALENDAR day for a timeframe, session-adjusted."""
    minutes = _timeframe_minutes(timeframe)
    bars_per_session = (hours_per_session * 60.0) / minutes
    return bars_per_session * sessions_per_week / 7.0


def _timeframe_minutes(timeframe: str) -> float:
    text = str(timeframe or "").strip().lower()
    if not text:
        raise ValueError("timeframe is required")
    unit = text[-1]
    try:
        count = float(text[:-1])
    except ValueError as exc:
        raise ValueError(f"unrecognised timeframe {timeframe!r}") from exc
    return count * {"m": 1.0, "h": 60.0, "d": 1440.0, "w": 10080.0}.get(unit, float("nan"))


def _fmt(value: float) -> str:
    return f"{value:,.0f}"


@dataclass(frozen=True)
class RequirementCheck:
    requirement_id: str
    description: str
    minimum: str
    observed: str
    passed: bool
    blocking_for_claims: bool


@dataclass(frozen=True)
class BenchmarkReadinessReport:
    """Whether the frozen candidates may be evaluated for a claim on a dataset."""

    subject: str
    timeframe: str
    checks: tuple[RequirementCheck, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ready_for_claims(self) -> bool:
        return all(c.passed for c in self.checks if c.blocking_for_claims)

    @property
    def unmet_blocking(self) -> list[RequirementCheck]:
        return [c for c in self.checks if c.blocking_for_claims and not c.passed]

    @property
    def mechanism_only(self) -> bool:
        """Mechanism evidence is always admissible; a claim is not."""
        return True

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": "qts.benchmark_readiness.v1",
            "subject": self.subject,
            "timeframe": self.timeframe,
            "ready_for_claims": self.ready_for_claims,
            "mechanism_only": self.mechanism_only,
            "unmet_blocking_requirements": [c.requirement_id for c in self.unmet_blocking],
            "checks": [
                {
                    "requirement_id": c.requirement_id,
                    "description": c.description,
                    "minimum": c.minimum,
                    "observed": c.observed,
                    "passed": c.passed,
                    "blocking_for_claims": c.blocking_for_claims,
                }
                for c in self.checks
            ],
            "notes": list(self.notes),
        }


# --------------------------------------------------------------------------- #
# Gate 1: is an EXISTING dataset adequate?
# --------------------------------------------------------------------------- #


def assess_dataset_readiness(
    *,
    bar_count: int,
    span_days: float,
    timeframe: str,
    source_label: str | None,
    round_turns_per_candidate: dict[str, int] | None = None,
    oos_bar_count: int | None = None,
    subject: str = "dataset",
) -> BenchmarkReadinessReport:
    """Evaluate a dataset against the pre-registered minimums.

    ``source_label`` is mapped through the bootstrap classifier, so provenance
    cannot be relabelled here to make an inadmissible dataset admissible.
    """
    data_class = classify_source(source_label or "")
    admissible = claim_admissible(data_class)
    refusal = CLAIM_INADMISSIBLE_REASONS.get(data_class, "not an observed-data class")
    notes: list[str] = []
    checks: list[RequirementCheck] = [RequirementCheck(
        "B1-REAL-PROVENANCE",
        "Data must be OBSERVED broker/exchange history — synthetic data cannot support "
        "a claim about real-market behaviour, only demonstrate mechanism",
        "data_class in {REAL, BROKER-DERIVED, HISTORICAL}",
        (
            f"data_class={data_class} (source={source_label!r})"
            if admissible
            else f"data_class={data_class} (source={source_label!r}) — {refusal}"
        ),
        admissible,
        True,
    )]

    if timeframe != FROZEN_TIMEFRAME:
        notes.append(
            f"the frozen candidates are defined on {FROZEN_TIMEFRAME}; results on "
            f"{timeframe} are mechanism evidence and cannot test the stated hypotheses"
        )
    checks.append(RequirementCheck(
        "B2-TIMEFRAME-MATCH",
        "The dataset timeframe must match the timeframe the candidates are defined on",
        f"timeframe == {FROZEN_TIMEFRAME}",
        f"timeframe={timeframe}",
        timeframe == FROZEN_TIMEFRAME,
        True,
    ))

    checks.append(RequirementCheck(
        "B3-DEPTH",
        "Enough bars for the trade counts to mean anything after multiple-testing correction",
        f">= {_fmt(MIN_BARS_REAL_CLAIMS)} bars (target {_fmt(TARGET_BARS_REAL_CLAIMS)})",
        f"{_fmt(float(bar_count))} bars",
        bar_count >= MIN_BARS_REAL_CLAIMS,
        True,
    ))

    checks.append(RequirementCheck(
        "B4-REGIME-COVERAGE",
        "The series must span enough calendar time to contain more than one regime; "
        "a single month is one regime, not an out-of-sample test",
        f">= {MIN_SPAN_DAYS} days",
        f"{span_days:,.1f} days",
        span_days >= MIN_SPAN_DAYS,
        True,
    ))

    if round_turns_per_candidate:
        worst = min(round_turns_per_candidate.values())
        detail = ", ".join(f"{k}={v}" for k, v in sorted(round_turns_per_candidate.items()))
        checks.append(RequirementCheck(
            "B5-TRADE-COUNT",
            "Every candidate needs enough round turns for inference; the weakest one "
            "sets the bar, because reporting only the busiest candidate is cherry-picking",
            f">= {MIN_ROUND_TURNS_PER_CANDIDATE} round turns per candidate",
            f"{detail} (min {worst})",
            worst >= MIN_ROUND_TURNS_PER_CANDIDATE,
            True,
        ))

    if oos_bar_count is not None:
        checks.append(RequirementCheck(
            "B6-OOS-SIZE",
            "The held-out portion must be large enough that out-of-sample means "
            "something more than 'a different month'",
            f">= {_fmt(MIN_OOS_BARS)} bars out of sample",
            f"{_fmt(float(oos_bar_count))} bars",
            oos_bar_count >= MIN_OOS_BARS,
            True,
        ))

    return BenchmarkReadinessReport(
        subject=subject, timeframe=timeframe, checks=tuple(checks), notes=tuple(notes)
    )


# --------------------------------------------------------------------------- #
# Gate 2: is an acquisition even capable of producing adequate data?
# --------------------------------------------------------------------------- #


def assess_acquisition_ceiling(
    *,
    max_history_days: float,
    timeframe: str = FROZEN_TIMEFRAME,
    source_label: str | None = None,
    subject: str = "prospective acquisition",
) -> BenchmarkReadinessReport:
    """Can a source with a known retention ceiling EVER supply enough data?

    This is the check that should run before an acquisition is attempted. A
    source capped at N days cannot produce more than N days, and if N is below
    the span minimum then no amount of engineering will make its output
    claim-eligible. Discovering that after the download is the expensive way.
    """
    per_day = bars_per_day(timeframe)
    projected_bars = max_history_days * per_day
    notes = [
        f"projection assumes {TRADING_HOURS_PER_SESSION:g}h sessions, "
        f"{TRADING_SESSIONS_PER_WEEK:g} days/week → {per_day:,.1f} {timeframe} bars per calendar day",
        "a ceiling is an upper bound: the achievable window may be shorter still",
    ]
    if source_label:
        notes.append(f"source: {source_label}")

    report = assess_dataset_readiness(
        bar_count=int(projected_bars),
        span_days=float(max_history_days),
        timeframe=timeframe,
        source_label=source_label,
        subject=subject,
    )
    # Carry the projection into the report so the arithmetic is auditable.
    combined = list(report.checks) + [RequirementCheck(
        "B7-CEILING-PROJECTION",
        "Bars obtainable at the source's retention ceiling "
        "(informational — the depth check above already applies it)",
        f">= {_fmt(MIN_BARS_REAL_CLAIMS)} bars",
        f"{_fmt(projected_bars)} bars from {max_history_days:,.0f} days at {timeframe}",
        projected_bars >= MIN_BARS_REAL_CLAIMS,
        False,
    )]
    return BenchmarkReadinessReport(
        subject=subject,
        timeframe=timeframe,
        checks=tuple(combined),
        notes=tuple(notes) + report.notes,
    )


def days_needed_for_depth(timeframe: str = FROZEN_TIMEFRAME, *,
                          bars: int = MIN_BARS_REAL_CLAIMS) -> float:
    """Calendar days of history required to reach ``bars`` — the honest ask."""
    return bars / bars_per_day(timeframe)


def readiness_markdown(report: BenchmarkReadinessReport) -> str:
    lines = [
        f"# Benchmark readiness — {report.subject}",
        "",
        f"**Timeframe:** {report.timeframe}  ",
        f"**Ready for claims:** {'YES' if report.ready_for_claims else 'NO'}  ",
        "**Mechanism evidence only:** yes (always)  ",
        "",
        "| ID | Requirement | Minimum | Observed | Blocking | Result |",
        "|:---|:---|:---|:---|:---|:---|",
    ]
    for check in report.checks:
        lines.append(
            f"| {check.requirement_id} | {check.description} | {check.minimum} | "
            f"{check.observed} | {'yes' if check.blocking_for_claims else 'no'} | "
            f"{'PASS' if check.passed else 'FAIL'} |"
        )
    if report.notes:
        lines += ["", "## Notes", ""] + [f"- {note}" for note in report.notes]
    return "\n".join(lines) + "\n"


def current_status() -> dict[str, Any]:
    """The standing readiness status of the frozen set, as of this build."""
    from qts.research.benchmarks import BENCHMARKS, verify_frozen

    frozen_ok, frozen_problems = verify_frozen()
    return {
        "schema": "qts.benchmark_readiness_status.v1",
        "assessed_at": datetime.now(UTC).isoformat(),
        "frozen_set_intact": frozen_ok,
        "frozen_problems": list(frozen_problems),
        "candidates": [
            {
                "benchmark_id": spec.benchmark_id,
                "role": spec.role.value,
                "timeframe": spec.timeframe,
                "params": dict(spec.params),
            }
            for spec in BENCHMARKS
        ],
        "minimums": {
            "bars": MIN_BARS_REAL_CLAIMS,
            "target_bars": TARGET_BARS_REAL_CLAIMS,
            "span_days": MIN_SPAN_DAYS,
            "round_turns_per_candidate": MIN_ROUND_TURNS_PER_CANDIDATE,
            "oos_bars": MIN_OOS_BARS,
            "timeframe": FROZEN_TIMEFRAME,
        },
    }
