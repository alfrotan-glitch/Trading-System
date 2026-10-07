"""Shadow versus paper divergence — measured fields or explicit unknowns."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass
class ExecutionConsistencyResult:
    missed_entries: int | None
    unexpected_fills: int | None
    avg_price_diff_bps: float | None
    max_price_diff_bps: float | None
    avg_timing_diff_s: float | None
    rejected_trades: int | None
    partial_fills: int | None
    slippage_error_bps: float | None
    error_distribution: list[float]
    paper_represents_live: bool | None
    alignment_status: str = "UNAVAILABLE"


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
        return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt
    except (TypeError, ValueError):
        return None


def _identity(row: dict[str, Any]) -> str | None:
    for key in ("client_order_id", "signal_id", "event_id", "intent_id"):
        value = row.get(key)
        if value is not None and str(value):
            return str(value)
    return None


def _price(row: dict[str, Any]) -> float | None:
    for key in ("price", "fill_price", "actual_price", "entry_price"):
        value = row.get(key)
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number > 0:
            return number
    return None


def compare_shadow_paper(
    shadow_intents: list[dict], paper_fills: list[dict], expected_prices: list[float]
) -> ExecutionConsistencyResult:
    """Compare paired intents/fills without manufacturing prices or timings.

    Identifiers are preferred.  When legacy rows have no identifier, positional
    pairing is retained only as a visibly limited fallback for the local paper
    comparison; the result carries ``alignment_status`` and cannot establish
    live execution realism by itself.
    """
    shadow_valid = [row for row in shadow_intents if _price(row) is not None]
    paper_valid = [row for row in paper_fills if _price(row) is not None]
    if not shadow_valid and not paper_valid:
        return ExecutionConsistencyResult(
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            [],
            None,
            "UNAVAILABLE: no parseable intent or fill prices",
        )

    shadow_by_id = {_identity(row): row for row in shadow_valid if _identity(row) is not None}
    paper_by_id = {_identity(row): row for row in paper_valid if _identity(row) is not None}
    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    alignment_status = "IDENTITY_ALIGNED"
    if shadow_by_id and paper_by_id:
        for key, shadow in shadow_by_id.items():
            paper = paper_by_id.get(key)
            if paper is not None:
                pairs.append((shadow, paper))
        matched_shadow = len(pairs)
        missed = len(shadow_by_id) - matched_shadow
        unexpected = len(paper_by_id) - matched_shadow
    else:
        alignment_status = "POSITIONAL_FALLBACK_LIMITED"
        pairs = list(zip(shadow_valid, paper_valid, strict=False))
        missed = max(0, len(shadow_valid) - len(paper_valid))
        unexpected = max(0, len(paper_valid) - len(shadow_valid))

    differences: list[float] = []
    timing: list[float] = []
    for shadow, paper in pairs:
        sp = _price(shadow)
        pp = _price(paper)
        if sp is not None and pp not in (None, 0):
            differences.append(abs(sp - pp) / abs(pp) * 10_000)
        st = _parse_time(shadow.get("time") or shadow.get("event_time") or shadow.get("bar_time"))
        pt = _parse_time(paper.get("time") or paper.get("event_time") or paper.get("bar_time"))
        if st is not None and pt is not None:
            timing.append(abs((pt - st).total_seconds()))

    statuses = [str(row.get("status", row.get("state", ""))).upper() for row in paper_fills]
    rejected = sum(status in {"REJECTED", "REJECT", "CANCELLED"} for status in statuses) if any(statuses) else None
    partial = sum(status in {"PARTIAL", "PARTIALLY_FILLED"} for status in statuses) if any(statuses) else None
    if differences:
        avg_diff = sum(differences) / len(differences)
        max_diff = max(differences)
        # A paper/shadow comparison cannot establish equivalence to live
        # broker execution. Keep the realism claim unknown even when the local
        # price divergence is small; broker fills, latency, and venue identity
        # are separate evidence requirements.
        represents = None
    else:
        avg_diff = None
        max_diff = None
        represents = None
    avg_timing = sum(timing) / len(timing) if timing else None
    return ExecutionConsistencyResult(
        missed_entries=missed,
        unexpected_fills=unexpected,
        avg_price_diff_bps=avg_diff,
        max_price_diff_bps=max_diff,
        avg_timing_diff_s=avg_timing,
        rejected_trades=rejected,
        partial_fills=partial,
        # A divergence from paper's model price is not broker slippage.
        slippage_error_bps=None,
        error_distribution=differences,
        paper_represents_live=represents,
        alignment_status=alignment_status,
    )
