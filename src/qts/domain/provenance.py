"""Evidence provenance & truth semantics — FIRST-CLASS, system-wide.

This module is the single canonical vocabulary for two questions:

1. WHERE did a piece of data come from?  -> :class:`EvidenceProvenance`
2. WHAT does a metric actually measure?  -> :class:`MetricValue` /
   :class:`UnavailableMetric`

Non-negotiable rules encoded here (violations are bugs, not style):

* Ambiguous evidence is NEVER defaulted to REAL. Classification requires an
  explicit, recorded basis; anything else is ``UNVERIFIED`` and excluded from
  every claim that requires fresh real evidence.
* "Not measured" is NEVER represented as ``0``. An unmeasurable metric is
  ``UNAVAILABLE`` (with a machine-readable reason) or
  ``INSUFFICIENT_EVIDENCE`` — never a fabricated numeric placeholder.
* Historical / synthetic-looking records (wrong symbol, stale price regime,
  missing lineage) must be reclassified, not silently presented as current.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class EvidenceProvenance(StrEnum):
    """Canonical provenance classes for every persisted record.

    Ordering is deliberate (``rank``): a claim may only be supported by
    provenance at least as strong as the claim requires. ``UNVERIFIED`` is
    deliberately the weakest class and can never be promoted by accident.
    """

    SYNTHETIC = "SYNTHETIC"  # generated data (fixtures, simulators)
    HISTORICAL = "HISTORICAL"  # real past market data, not from a live session
    PAPER = "PAPER"  # simulated fills on historical data
    SHADOW = "SHADOW"  # would-be intents, no submission
    DEMO = "DEMO"  # real broker infrastructure, demo account
    REAL = "REAL"  # verified live/real-account observation
    UNVERIFIED = "UNVERIFIED"  # missing/broken lineage — excluded from claims

    @property
    def rank(self) -> int:
        """Strength ordering; UNVERIFIED ranks below SYNTHETIC (trusts nothing)."""
        order = {
            EvidenceProvenance.UNVERIFIED: 0,
            EvidenceProvenance.SYNTHETIC: 1,
            EvidenceProvenance.HISTORICAL: 2,
            EvidenceProvenance.PAPER: 3,
            EvidenceProvenance.SHADOW: 4,
            EvidenceProvenance.DEMO: 5,
            EvidenceProvenance.REAL: 6,
        }
        return order[self]

    def supports(self, required: EvidenceProvenance) -> bool:
        """True if this provenance is strong enough to back a claim requiring ``required``."""
        return self.rank >= required.rank


#: Provenance labels considered acceptable for "fresh real-market evidence".
REAL_CLASSES = (EvidenceProvenance.REAL, EvidenceProvenance.DEMO)


class UnavailableReason(StrEnum):
    """Machine-readable reasons a metric cannot be produced."""

    NOT_MEASURED = "NOT_MEASURED"  # nothing ever produced this metric
    NO_DATA = "NO_DATA"  # required inputs absent
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"  # some data, not enough to compute honestly
    PROVENANCE_UNVERIFIED = "PROVENANCE_UNVERIFIED"  # data exists but lineage broken
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"  # authoritative source not reachable
    MISMATCHED_LINEAGE = "MISMATCHED_LINEAGE"  # data exists but belongs to another run/symbol/env


_UNAVAILABLE = "UNAVAILABLE"
_INSUFFICIENT = "INSUFFICIENT_EVIDENCE"


class MetricValue:
    """A measurement OR an explicit unavailability — never a fabricated zero.

    Use :meth:`ok` for real measurements and :meth:`unavailable` /
    :meth:`insufficient` otherwise. Serialization distinguishes the two so
    downstream consumers (UI, reports, gates) can never read a placeholder
    zero as an observed value.
    """

    __slots__ = ("value", "status", "reason")

    def __init__(self, value: Any, status: str, reason: str | None = None) -> None:
        self.value = value
        self.status = status  # MEASURED | UNAVAILABLE | INSUFFICIENT_EVIDENCE
        self.reason = reason

    @classmethod
    def ok(cls, value: Any) -> MetricValue:
        return cls(value=value, status="MEASURED")

    @classmethod
    def unavailable(cls, reason: UnavailableReason | str, detail: str = "") -> MetricValue:
        return cls(value=None, status=_UNAVAILABLE, reason=f"{reason}{(': ' + detail) if detail else ''}")

    @classmethod
    def insufficient(cls, detail: str = "") -> MetricValue:
        return cls(value=None, status=_INSUFFICIENT, reason=f"{_INSUFFICIENT}{(': ' + detail) if detail else ''}")

    @property
    def measured(self) -> bool:
        return self.status == "MEASURED"

    def as_dict(self) -> dict[str, Any]:
        if self.measured:
            return {"status": self.status, "value": self.value}
        return {"status": self.status, "value": None, "reason": self.reason}

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        if self.measured:
            return f"MetricValue({self.value!r})"
        return f"MetricValue({self.status}, reason={self.reason!r})"


def mean_or_unavailable(values: list[float], name: str) -> MetricValue:
    """Mean of real measurements, or an explicit UNAVAILABLE — never 0.0."""
    if not values:
        return MetricValue.unavailable(UnavailableReason.NO_DATA, f"no {name} observations")
    return MetricValue.ok(sum(values) / len(values))


def classify_record_provenance(
    *,
    recorded_provenance: str | None,
    symbol_ok: bool,
    timestamps_fresh_and_ordered: bool,
    lineage_bound: bool,
) -> EvidenceProvenance:
    """Classify a stored record under the fail-closed provenance model.

    A record keeps its claimed provenance ONLY if every integrity condition
    holds; any broken condition downgrades to ``UNVERIFIED``. Callers must
    not present UNVERIFIED records as current real-market evidence.
    """
    try:
        claimed = EvidenceProvenance(str(recorded_provenance).upper()) if recorded_provenance else None
    except ValueError:
        claimed = None
    if claimed is None or claimed is EvidenceProvenance.UNVERIFIED:
        return EvidenceProvenance.UNVERIFIED
    if not (symbol_ok and timestamps_fresh_and_ordered and lineage_bound):
        return EvidenceProvenance.UNVERIFIED
    return claimed
