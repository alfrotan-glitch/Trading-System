"""Data-adequacy gate for impulse research — fail closed, never substitute.

Before ANY claim about real-market impulse behavior, the dataset must satisfy
the requirements below. If it does not, the research layer:

* reports the unmet requirements explicitly (what is missing, what the
  minimum is), and
* forces the conclusion to ``BLOCKED_INSUFFICIENT_DATA``.

Synthetic data is NEVER quietly substituted for real data. It may only be
used in an explicitly labeled ``mechanism_validation`` mode whose outputs
cannot support real-market claims (the classifier enforces this).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from qts.data.bootstrap import classify_source
from qts.domain.value_objects import Bar

# ---------------------------------------------------------------------------
# Pre-registered minimum data requirements for real-market impulse claims.
# Short-horizon impulse research on 1H bars is already at the edge of what
# bar data can support; anything less is inadmissible.
# ---------------------------------------------------------------------------
MIN_BARS_REAL_CLAIMS = 5000  # ~8 months of 1H; below this, event counts cannot support inference
TARGET_BARS_REAL_CLAIMS = 17520  # 2 years of 1H (target, not blocking minimum)
MIN_SPAN_DAYS = 180  # multi-regime coverage requires at least half a year
MIN_EVENTS_FOR_INFERENCE = 100  # measured events per aggregated hypothesis space
MIN_EVENTS_PER_SIDE = 30  # LONG and SHORT separately
MAX_STALENESS_DAYS = 7  # "real-time impulse" claims require recent data


@dataclass(frozen=True)
class RequirementCheck:
    requirement_id: str
    description: str
    minimum: str
    observed: str
    passed: bool
    blocking_for_real_claims: bool


@dataclass(frozen=True)
class DataAdequacyReport:
    data_version: str
    data_class: str  # REAL | SYNTHETIC | ... (qts.data.bootstrap.DATA_CLASSES)
    source_label: str
    checks: tuple[RequirementCheck, ...] = field(default_factory=tuple)
    measured_events_total: int = 0
    measured_events_long: int = 0
    measured_events_short: int = 0

    @property
    def adequate_for_real_claims(self) -> bool:
        return all(c.passed for c in self.checks if c.blocking_for_real_claims)

    @property
    def unmet_requirements(self) -> list[RequirementCheck]:
        return [c for c in self.checks if not c.passed]

    def as_dict(self) -> dict[str, object]:
        return {
            "data_version": self.data_version,
            "data_class": self.data_class,
            "source_label": self.source_label,
            "adequate_for_real_claims": self.adequate_for_real_claims,
            "measured_events_total": self.measured_events_total,
            "measured_events_long": self.measured_events_long,
            "measured_events_short": self.measured_events_short,
            "checks": [
                {
                    "requirement_id": c.requirement_id,
                    "description": c.description,
                    "minimum": c.minimum,
                    "observed": c.observed,
                    "passed": c.passed,
                    "blocking_for_real_claims": c.blocking_for_real_claims,
                }
                for c in self.checks
            ],
        }


def assess_data_adequacy(
    bars: list[Bar] | tuple[Bar, ...],
    data_version: str,
    source_label: str | None,
    now: datetime | None = None,
    measured_events_total: int = 0,
    measured_events_long: int = 0,
    measured_events_short: int = 0,
) -> DataAdequacyReport:
    """Evaluate a dataset against the pre-registered minimum requirements.

    ``source_label`` is the manifest's provenance string; it is mapped through
    ``qts.data.bootstrap.classify_source`` — the same classifier used by the
    data bootstrap, so labels cannot drift between subsystems.
    """
    now = now or datetime.now(UTC)
    data_class = classify_source(source_label)
    checks: list[RequirementCheck] = []

    checks.append(
        RequirementCheck(
            "R1-REAL-PROVENANCE",
            "Data must be REAL broker/exchange history — synthetic or simulated data cannot "
            "support claims about real-market behavior",
            "data_class == REAL",
            f"data_class={data_class} (source={source_label!r})",
            data_class == "REAL",
            True,
        )
    )

    n = len(bars)
    checks.append(
        RequirementCheck(
            "R2-DEPTH",
            "Minimum number of bars for event-count sufficiency",
            f">= {MIN_BARS_REAL_CLAIMS} bars (target {TARGET_BARS_REAL_CLAIMS})",
            f"{n} bars",
            n >= MIN_BARS_REAL_CLAIMS,
            True,
        )
    )

    span = (bars[-1].close_time - bars[0].open_time).total_seconds() / 86400.0 if n >= 2 else 0.0
    checks.append(
        RequirementCheck(
            "R3-REGIME-COVERAGE",
            "Series must span enough calendar time to contain multiple volatility regimes",
            f">= {MIN_SPAN_DAYS} days",
            f"{span:.1f} days",
            span >= MIN_SPAN_DAYS,
            True,
        )
    )

    staleness = (now - bars[-1].close_time).total_seconds() / 86400.0 if n >= 1 else float("inf")
    checks.append(
        RequirementCheck(
            "R4-FRESHNESS",
            "Real-time impulse claims require recent data (stale data cannot describe current market microstructure)",
            f"last bar within {MAX_STALENESS_DAYS} days of assessment time",
            f"last bar {staleness:.1f} days old" if staleness != float("inf") else "no bars",
            staleness <= MAX_STALENESS_DAYS,
            True,
        )
    )

    checks.append(
        RequirementCheck(
            "R5-EXECUTION-DATA",
            "Real spread/bid-ask/tick history is required to replace declared cost "
            "ASSUMPTIONS with broker-observed costs (bar high-low range is only a proxy)",
            "bid/ask or tick data with real spread history available",
            "OHLC bars only — no bid/ask, no ticks (costs remain ESTIMATED assumptions)",
            False,  # bar-only datasets never satisfy R5; tick ingestion is a future capability
            # Non-blocking: with bar data, cost-based conclusions remain admissible IF the
            # edge survives the full declared cost/latency/spread sensitivity sweep. R5 is
            # reported prominently as a standing limitation of every bar-data conclusion.
            False,
        )
    )

    checks.append(
        RequirementCheck(
            "R6-EVENT-SUFFICIENCY",
            "Enough measured events (per side) for statistical inference after multiple-testing correction",
            f">= {MIN_EVENTS_FOR_INFERENCE} total, >= {MIN_EVENTS_PER_SIDE} per side",
            f"total={measured_events_total} long={measured_events_long} short={measured_events_short}",
            measured_events_total >= MIN_EVENTS_FOR_INFERENCE
            and measured_events_long >= MIN_EVENTS_PER_SIDE
            and measured_events_short >= MIN_EVENTS_PER_SIDE,
            True,
        )
    )

    return DataAdequacyReport(
        data_version=data_version,
        data_class=data_class,
        source_label=source_label or "",
        checks=tuple(checks),
        measured_events_total=measured_events_total,
        measured_events_long=measured_events_long,
        measured_events_short=measured_events_short,
    )
