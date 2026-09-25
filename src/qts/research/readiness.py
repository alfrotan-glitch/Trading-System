"""Research-data readiness: one honest answer to "can this claim run?".

The backtest engine can operate on a small synthetic fixture, but a number
produced by that run is not evidence about a broker market.  This module keeps
that distinction explicit and gives research callers a structured, reusable
assessment instead of each campaign inventing its own data checks.

The assessment is deliberately conservative:

* a manifest row without readable bars is unavailable;
* synthetic, paper, shadow, demo, and unverified datasets may support labelled
  mechanism/replay work but cannot support a real-market claim;
* a dataset that fails depth, span, or quality requirements is blocked rather
  than silently downgraded to a warning;
* no missing value is represented by zero.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC
from typing import TYPE_CHECKING, Any

from qts.data.bootstrap import classify_source
from qts.data.quality import validate_bars
from qts.domain.value_objects import Bar, Instrument

if TYPE_CHECKING:
    from qts.data.store import SqliteParquetDataStore


@dataclass(frozen=True)
class ResearchDataRequirements:
    """Minimum data contract for a meaningful historical research claim."""

    min_bars: int = 5_000
    min_span_days: float = 180.0
    # ``REAL`` is a verified real-account observation class. ``HISTORICAL`` is
    # imported real market history. ``BROKER-DERIVED`` remains accepted for
    # compatibility with the broker History Center import label.
    allowed_claim_classes: tuple[str, ...] = ("REAL", "HISTORICAL", "BROKER-DERIVED")


@dataclass(frozen=True)
class ResearchDataReadiness:
    data_version: str
    status: str  # READY | BLOCKED_INSUFFICIENT_DATA | UNAVAILABLE
    data_class: str
    source_label: str
    instrument: str | None
    timeframe: str | None
    rows: int | None
    span_days: float | None
    quality_passed: bool | None
    reasons: tuple[str, ...] = field(default_factory=tuple)
    requirements: ResearchDataRequirements = field(default_factory=ResearchDataRequirements)

    @property
    def available(self) -> bool:
        return self.status != "UNAVAILABLE"

    @property
    def ready_for_claims(self) -> bool:
        return self.status == "READY"

    @property
    def mechanism_validation_only(self) -> bool:
        return self.available and not self.ready_for_claims

    def as_dict(self) -> dict[str, Any]:
        return {
            "data_version": self.data_version,
            "status": self.status,
            "data_class": self.data_class,
            "source_label": self.source_label,
            "instrument": self.instrument,
            "timeframe": self.timeframe,
            "rows": self.rows,
            "span_days": self.span_days,
            "quality_passed": self.quality_passed,
            "ready_for_claims": self.ready_for_claims,
            "mechanism_validation_only": self.mechanism_validation_only,
            "reasons": list(self.reasons),
            "requirements": {
                "min_bars": self.requirements.min_bars,
                "min_span_days": self.requirements.min_span_days,
                "allowed_claim_classes": list(self.requirements.allowed_claim_classes),
            },
        }


def assess_bars(
    bars: list[Bar] | tuple[Bar, ...],
    *,
    data_version: str,
    source_label: str | None,
    requirements: ResearchDataRequirements | None = None,
    provenance_class: str | None = None,
) -> ResearchDataReadiness:
    """Assess already-read canonical bars without inventing or imputing data."""
    req = requirements or ResearchDataRequirements()
    label = source_label or ""
    data_class = provenance_class or classify_source(label)
    instrument = bars[0].instrument.symbol if bars else None
    timeframe = _infer_timeframe(bars)
    rows = len(bars)
    span_days = (
        (bars[-1].close_time.astimezone(UTC) - bars[0].open_time.astimezone(UTC)).total_seconds() / 86_400.0
        if rows >= 2
        else 0.0
    )
    if not bars:
        return ResearchDataReadiness(
            data_version=data_version,
            status="UNAVAILABLE",
            data_class=data_class,
            source_label=label,
            instrument=None,
            timeframe=None,
            rows=0,
            span_days=0.0,
            quality_passed=False,
            reasons=("NO_DATA: no readable bars for the requested version",),
            requirements=req,
        )

    quality = validate_bars(list(bars))
    reasons: list[str] = []
    if data_class not in req.allowed_claim_classes:
        reasons.append(
            f"PROVENANCE_NOT_CLAIM_ELIGIBLE: data_class={data_class}; "
            f"allowed={','.join(req.allowed_claim_classes)}"
        )
    if rows < req.min_bars:
        reasons.append(f"INSUFFICIENT_DEPTH: {rows} bars < required {req.min_bars}")
    if span_days < req.min_span_days:
        reasons.append(f"INSUFFICIENT_SPAN: {span_days:.2f} days < required {req.min_span_days:.2f}")
    if not quality.passed:
        failed = "; ".join(f"{c.name}: {c.details}" for c in quality.checks if not c.passed)
        reasons.append(f"DATA_QUALITY_FAILED: {failed}")

    return ResearchDataReadiness(
        data_version=data_version,
        status="READY" if not reasons else "BLOCKED_INSUFFICIENT_DATA",
        data_class=data_class,
        source_label=label,
        instrument=instrument,
        timeframe=timeframe,
        rows=rows,
        span_days=span_days,
        quality_passed=quality.passed,
        reasons=tuple(reasons),
        requirements=req,
    )


def assess_dataset(
    store: SqliteParquetDataStore,
    data_version: str,
    *,
    instrument: Instrument | None = None,
    timeframe: str | None = None,
    requirements: ResearchDataRequirements | None = None,
) -> ResearchDataReadiness:
    """Read one immutable manifest and assess the exact bars it resolves to."""
    manifest = store.manifest(data_version)
    if manifest is None or not store.version_usable(data_version):
        return ResearchDataReadiness(
            data_version=data_version,
            status="UNAVAILABLE",
            data_class="UNVERIFIED",
            source_label="",
            instrument=instrument.symbol if instrument else None,
            timeframe=timeframe,
            rows=None,
            span_days=None,
            quality_passed=None,
            reasons=("NO_USABLE_DATASET: manifest missing or curated bars are unreadable",),
            requirements=requirements or ResearchDataRequirements(),
        )
    resolved_instrument = instrument or Instrument(symbol=manifest.instrument, venue=manifest.venue)
    resolved_timeframe = timeframe or manifest.timeframe
    bars = store.read_bars(resolved_instrument, resolved_timeframe, version=data_version)
    return assess_bars(
        bars,
        data_version=data_version,
        source_label=manifest.source,
        requirements=requirements,
        provenance_class=(
            getattr(manifest, "provenance_class", None)
            if getattr(manifest, "provenance_class", "UNVERIFIED") != "UNVERIFIED"
            else None
        ),
    )


def _infer_timeframe(bars: list[Bar] | tuple[Bar, ...]) -> str | None:
    if len(bars) < 2:
        return None
    seconds = (bars[1].open_time - bars[0].open_time).total_seconds()
    candidates = {60: "1m", 300: "5m", 900: "15m", 1800: "30m", 3600: "1H", 14_400: "4H", 86_400: "1D"}
    return candidates.get(int(seconds), f"{seconds:g}s")
