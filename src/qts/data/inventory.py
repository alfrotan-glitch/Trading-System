"""Data landscape audit — derived facts, never fabricated metrics.

The inventory is a report over canonical manifests and readable bars.  It is
not itself authoritative evidence and it never treats an OHLC bar count as a
tick count or a high-low range as a measured spread.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC
from pathlib import Path
from typing import Any

from qts.data.bootstrap import classify_source
from qts.data.quality import validate_bars
from qts.data.store import SqliteParquetDataStore
from qts.domain.value_objects import Instrument


def _assess_gaps(bars: list[Any]) -> dict[str, Any]:
    """Measure gaps relative to the modal bar interval.

    Weekend/market-closure gaps are reported separately from unexplained
    missing intervals.  No guessed number is inserted when the cadence cannot
    be inferred.
    """
    if len(bars) < 2:
        return {
            "gap_count": 0,
            "max_gap_s": None,
            "missing_intervals": None,
            "missing_pct": None,
            "common_delta_s": None,
            "closure_gap_count": 0,
        }
    deltas = [(bars[i + 1].open_time - bars[i].open_time).total_seconds() for i in range(len(bars) - 1)]
    positive = [d for d in deltas if d > 0]
    common = Counter(round(d, 6) for d in positive).most_common(1)[0][0] if positive else 0.0
    if common <= 0:
        return {
            "gap_count": None,
            "max_gap_s": None,
            "missing_intervals": None,
            "missing_pct": None,
            "common_delta_s": None,
            "closure_gap_count": None,
        }

    abnormal = 0
    closures = 0
    missing_intervals = 0
    max_abnormal_gap = 0.0
    for i, delta in enumerate(deltas):
        if delta <= common * 1.5:
            continue
        before = bars[i].close_time.astimezone(UTC)
        after = bars[i + 1].open_time.astimezone(UTC)
        # Friday-to-Sunday gaps and multi-day gaps are market closures, not
        # missing observations.  The report still exposes them explicitly.
        is_closure = before.weekday() == 4 and after.weekday() in (5, 6) or delta >= 2 * 86_400
        if is_closure:
            closures += 1
            continue
        abnormal += 1
        intervals = max(0, int(round(delta / common)) - 1)
        missing_intervals += intervals
        max_abnormal_gap = max(max_abnormal_gap, delta)

    expected = len(bars) + missing_intervals
    return {
        "gap_count": abnormal,
        "closure_gap_count": closures,
        "max_gap_s": int(max_abnormal_gap) if max_abnormal_gap else 0,
        "missing_intervals": missing_intervals,
        "missing_pct": round(missing_intervals / expected * 100, 2) if expected else 0.0,
        "common_delta_s": int(common),
    }


def _resolution(bars: list[Any]) -> str:
    if len(bars) < 2:
        return "UNAVAILABLE: fewer than two bars"
    seconds = (bars[1].open_time - bars[0].open_time).total_seconds()
    return f"{seconds:g}s bar cadence"


def _session_coverage(bars: list[Any]) -> dict[str, Any]:
    if not bars:
        return {"status": "UNAVAILABLE", "value": None, "reason": "no bars"}
    weekdays = sorted({b.open_time.astimezone(UTC).strftime("%a") for b in bars})
    weekend_bars = sum(1 for b in bars if b.open_time.astimezone(UTC).weekday() >= 5)
    return {
        "status": "MEASURED",
        "weekdays_observed": weekdays,
        "weekend_bars": weekend_bars,
        "note": "calendar coverage only; broker session hours require broker tick/session metadata",
    }


def _availability(available: bool, measured_as: str, reason: str) -> dict[str, Any]:
    if available:
        return {"status": "MEASURED", "value": measured_as}
    return {"status": "UNAVAILABLE", "value": None, "reason": reason}


def generate_inventory(root: Path = Path("data")) -> list[dict[str, Any]]:
    """Return one honest inventory entry for every usable/registered dataset."""
    store = SqliteParquetDataStore(root=root)
    versions = store.list_versions()
    inventory: list[dict[str, Any]] = []
    for version in versions:
        manifest = store.manifest(version)
        if not manifest:
            continue
        instr = Instrument(symbol=manifest.instrument, venue=manifest.venue)
        bars = sorted(store.read_bars(instr, manifest.timeframe, version=version), key=lambda b: b.open_time)
        report = validate_bars(bars) if bars else None
        gap_info = _assess_gaps(bars)
        source_label = getattr(manifest, "source", None) or "UNVERIFIED"
        raw_source = getattr(manifest, "source_file", None)
        data_class = getattr(manifest, "provenance_class", None) or classify_source(source_label)
        provider = {
            "SYNTHETIC": "synthetic",
            "HISTORICAL": "historical_import",
            "REAL": "real_market_source",
            "DEMO": "mt5_demo_observation",
            "BROKER-DERIVED": "mt5_history",
            "PAPER": "paper",
            "SHADOW": "shadow",
        }.get(data_class, "unverified")
        duplicates = len(bars) != len({(b.instrument.symbol, b.open_time) for b in bars}) if bars else None
        quality_checks = (
            [{"name": c.name, "passed": c.passed, "details": c.details} for c in report.checks]
            if report
            else []
        )
        quality_passed = report.passed if report else False
        source_note = f"source_label={source_label}; class={data_class}"
        spread: str | dict[str, Any]
        if data_class == "SYNTHETIC":
            spread = "UNAVAILABLE — SYNTHETIC dataset has no measured bid/ask; high-low is not spread"
            volume = "tick-volume field present; real traded volume UNAVAILABLE"
            eligibility = "MECHANISM_VALIDATION_ONLY — synthetic data cannot support real-market claims"
        elif data_class in ("HISTORICAL", "BROKER-DERIVED"):
            spread = {
                "status": "UNAVAILABLE",
                "value": None,
                "reason": "imported OHLC contains no measured bid/ask spread",
            }
            volume = "dataset volume field; real-volume semantics require source metadata"
            eligibility = "HISTORICAL_RESEARCH_WITH_DECLARED_COST_ASSUMPTIONS"
        else:
            spread = _availability(False, "", "bid/ask observations not present in this bar dataset")
            volume = "UNAVAILABLE: bar volume semantics not declared"
            eligibility = "BLOCKED_UNTIL_PROVENANCE_AND_FIELD_SEMANTICS_VERIFIED"

        inventory.append(
            {
                "version": version,
                "source": source_label,
                "source_file": raw_source,
                "data_class": data_class,
                "provider": provider,
                "instrument": manifest.instrument,
                "venue": manifest.venue,
                "timeframe": manifest.timeframe,
                "date_range": {"start": manifest.start.isoformat(), "end": manifest.end.isoformat()},
                "row_count": manifest.rows,
                "tick_count": {
                    "status": "UNAVAILABLE",
                    "value": None,
                    "reason": "canonical dataset contains OHLC bars, not tick records",
                },
                "timezone": getattr(manifest, "timezone", "UTC") or "UTC",
                "timestamp_resolution": _resolution(bars),
                "ohlc_availability": _availability(bool(bars), "MEASURED", "no readable bars"),
                "bid_availability": _availability(False, "", "no bid field in canonical OHLC schema"),
                "ask_availability": _availability(False, "", "no ask field in canonical OHLC schema"),
                "spread_availability": spread,
                "volume_availability": _availability(bool(bars), "field present", "no readable bars"),
                "tick_volume_vs_real_volume": volume,
                "missingness": {
                    "status": "MEASURED" if gap_info.get("missing_pct") is not None else "UNAVAILABLE",
                    "value": gap_info,
                    "reason": None if gap_info.get("missing_pct") is not None else "cadence unavailable",
                },
                "duplicates": duplicates,
                "gaps": gap_info,
                "session_coverage": _session_coverage(bars),
                "market_closure_handling": "closures measured from UTC calendar gaps; broker session schedule UNAVAILABLE",
                "broker_artifacts": "UNAVAILABLE: no broker tick/session diagnostics in OHLC dataset",
                "checksum": manifest.checksum,
                "ingestion_method": f"{source_note} → raw preserved → validation → canonical {version}",
                "preprocessing_version": getattr(manifest, "preprocessing_version", "UNAVAILABLE") or "UNAVAILABLE",
                "provenance": {
                    "class": data_class,
                    "source_label": source_label,
                    "raw_file": raw_source,
                    "checksum": manifest.checksum,
                    "curated_path": str(
                        root
                        / "curated"
                        / f"instrument={manifest.instrument}"
                        / f"venue={manifest.venue}"
                        / f"timeframe={manifest.timeframe}"
                        / f"version={version}"
                        / "part-0.parquet"
                    ),
                },
                "schema_version": manifest.schema_version,
                "quality_report": quality_checks,
                "quality_passed": quality_passed,
                "curated_path": str(
                    root
                    / "curated"
                    / f"instrument={manifest.instrument}"
                    / f"venue={manifest.venue}"
                    / f"timeframe={manifest.timeframe}"
                    / f"version={version}"
                    / "part-0.parquet"
                ),
                "raw_preserved": raw_source,
                "research_eligibility": eligibility,
            }
        )
    return inventory


def write_inventory_json(path: Path = Path("data/evidence/data_inventory.json")) -> list[dict[str, Any]]:
    inv = generate_inventory()
    path.parent.mkdir(parents=True, exist_ok=True)
    import json

    path.write_text(json.dumps(inv, indent=2, default=str), encoding="utf-8")
    return inv
