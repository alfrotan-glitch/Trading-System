"""Offline, read-only disposition of long gaps in an acquired MT5 dataset.

No MT5 import or network access is performed.  UTC strings are diagnostics only:
the raw ``time_msc`` basis is never converted or rewritten.
"""
from __future__ import annotations
import argparse, hashlib, json, sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pyarrow.parquet as pq

SCHEMA = "qts.mt5_gap_disposition.v1"
ALLOWED = {"EXPECTED_WEEKEND_CLOSURE", "EXPECTED_DOCUMENTED_MARKET_HOLIDAY", "EXPECTED_DOCUMENTED_MARKET_CLOSURE", "UNEXPECTED_DATA_GAP", "UNRESOLVED"}
BASIS = "UTC rendering is provisional until the historical timestamp basis is independently verified; it is not a timestamp conversion or classification proof."
OFFICIAL_TIMESTAMP_SOURCE = {
    "source_name": "MetaQuotes MQL5 Python Integration: copy_ticks_range",
    "url": "https://www.mql5.com/en/docs/python_metatrader5/mt5copyticksrange_py",
    "accessed_utc": "2026-09-19",
    "publication_or_update_date": "2022-03-21 (page metadata; MetaQuotes page does not state a separate update date)",
    "relevant_wording": "MetaTrader 5 stores tick and bar open time in UTC time zone (without the shift)... The data obtained from MetaTrader 5 have UTC time.",
    "scope": "Directly applies to data returned by the documented Python copy_ticks_range function. The page's return description exposes time and the Python example exposes time_msc; the wording establishes UTC for obtained tick data, but does not separately define time_msc precision semantics.",
    "evidence_type": "official_direct_timestamp_basis",
}

def iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).isoformat()

def weekend(a: int, b: int) -> bool:
    d = datetime.fromtimestamp(a / 1000, UTC).date()
    end = datetime.fromtimestamp(b / 1000, UTC).date()
    while d <= end:
        if d.weekday() >= 5: return True
        d += timedelta(days=1)
    return False

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""): h.update(block)
    return h.hexdigest()

def source_facts(path: Path | None) -> dict[str, Any]:
    if not path: return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value.get("gaps", value) if isinstance(value, dict) else {}

def analyze(dataset: Path, evidence: Path | None = None, threshold_ms: int = 86_400_000, analysis_timestamp: str | None = None) -> dict[str, Any]:
    manifest = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))
    facts = source_facts(evidence)
    gaps: list[dict[str, Any]] = []
    previous: int | None = None
    before_row: int | None = None
    for entry in manifest.get("parts", []):
        table = pq.read_table(dataset / "parts" / entry["part"], columns=["time_msc"])
        for value in table.column("time_msc").to_pylist():
            current = int(value)
            if previous is not None and current - previous > threshold_ms:
                gap_id = f"gap-{len(gaps)+1:04d}"
                fact = facts.get(gap_id, {}) if isinstance(facts, dict) else {}
                classification = fact.get("classification", "UNRESOLVED")
                if classification not in ALLOWED: raise ValueError(f"unsupported classification for {gap_id}: {classification}")
                record = {
                    "gap_id": gap_id,
                    "raw_start_time_msc": previous,
                    "raw_end_time_msc": current,
                    "duration_ms": current - previous,
                    "duration_seconds": (current - previous) / 1000,
                    "provisional_utc": {"start": iso(previous), "end": iso(current)},
                    "overlaps_saturday_or_sunday_under_provisional_utc": weekend(previous, current),
                    "exact_surrounding_tick_timestamps": {"before": previous, "after": current},
                    "rows_immediately_before_and_after": {"before_time_msc": previous, "after_time_msc": current},
                    "calendar_dates_covered_provisional_utc": [
                        (datetime.fromtimestamp(previous / 1000, UTC).date() + timedelta(days=i)).isoformat()
                        for i in range((datetime.fromtimestamp(current / 1000, UTC).date() - datetime.fromtimestamp(previous / 1000, UTC).date()).days + 1)
                    ],
                    "classification": classification,
                    "classification_basis": fact.get("basis", "No external evidence supplied; a tick-arrival spacing observation is not proof of missing data, closure, halt, or acquisition failure."),
                    "evidence_refs": fact.get("evidence_refs", []),
                }
                gaps.append(record)
            previous, before_row = current, current
        del table
    counts = {name: sum(g["classification"] == name for g in gaps) for name in sorted(ALLOWED)}
    return {
        "schema": SCHEMA,
        "dataset_path": str(dataset),
        "dataset_sha256": manifest.get("dataset_sha256"),
        "manifest_sha256": sha256(dataset / "manifest.json"),
        "manifest_dataset_digest": manifest.get("dataset_sha256"),
        "row_count": manifest.get("row_count"),
        "analyzed_gap_threshold_ms": threshold_ms,
        "analyzed_gap_threshold": ">24h",
        "total_gaps_over_24h": len(gaps),
        "counts_by_classification": counts,
        "gaps": gaps,
        "evidence_sources": [OFFICIAL_TIMESTAMP_SOURCE] + (json.loads(evidence.read_text(encoding="utf-8")).get("sources", []) if evidence else []),
        "timestamp_basis_disposition": {
            "status": "VERIFIED_BY_OFFICIAL_MT5_DOCUMENTATION",
            "raw_fields": {"time": "UTC epoch seconds as documented for obtained tick data", "time_msc": "millisecond field returned in the same documented tick structure; precision is represented, but separate precision wording was not found"},
            "source_ref": OFFICIAL_TIMESTAMP_SOURCE["url"],
            "not_established": ["WM Markets broker server-local time", "historical broker offset", "DST/session schedule", "broker-specific closure calendar"],
            "statement": "Official MetaQuotes documentation establishes UTC for data obtained through copy_ticks_range; it does not establish WM Markets session rules or historical broker schedule facts.",
        },
        "unresolved_count": counts["UNRESOLVED"],
        "analysis_timestamp_utc": analysis_timestamp or datetime.now(UTC).isoformat(),
        "analysis_software": {"name": "analyze_mt5_gap_disposition", "version": "1.0.0", "schema": SCHEMA},
        "provisional_timestamp_statement": BASIS,
        "analytical_boundary": "A large gap in tick arrivals is an observation. It is not automatically missing data, market closure, bad acquisition, or a trading halt. Weekend-looking gaps remain UNRESOLVED without documented evidence.",
        "raw_tick_payloads_included": False,
        "privacy_statement": "This bounded report contains no bid, ask, last, volume, flags, or raw Parquet payloads; the immutable raw dataset is neither modified nor copied.",
    }

def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset", type=Path, required=True)
    p.add_argument("--evidence", type=Path, help="optional committed JSON with sources and gap-ID dispositions")
    p.add_argument("--output", type=Path, default=Path("data/evidence/mt5_history_analysis/XAUUSD__730d_gap_disposition.json"))
    p.add_argument("--analysis-timestamp", help="fixed ISO timestamp for reproducible evidence exports")
    a = p.parse_args(argv)
    result = analyze(a.dataset, a.evidence, analysis_timestamp=a.analysis_timestamp)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {a.output} ({len(result['gaps'])} gaps >24h)")
    return 0
if __name__ == "__main__": raise SystemExit(main())
