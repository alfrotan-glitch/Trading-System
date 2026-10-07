"""Data source audit derived from canonical manifests and bars.

Every limitation in this report is a measured property of the datasets that
are actually registered.  Unknown broker/tick/licensing facts remain explicit
unknowns; this module does not turn an OHLC fixture into market evidence.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from qts.data.inventory import generate_inventory


def audit_data_sources(root: Path = Path("data")) -> dict[str, Any]:
    """Inspect every registered dataset and report what is still unavailable."""
    inventory = generate_inventory(root)
    rows = [int(i["row_count"]) for i in inventory if isinstance(i.get("row_count"), int)]
    classes = sorted({str(i.get("data_class", "UNVERIFIED")) for i in inventory})
    max_rows = max(rows) if rows else None
    total_rows = sum(rows) if rows else None
    sources: list[dict[str, Any]] = []
    for item in inventory:
        sources.append(
            {
                "version": item["version"],
                "instrument": item["instrument"],
                "venue": item["venue"],
                "timeframe": item["timeframe"],
                "rows": item["row_count"],
                "date_range": item["date_range"],
                "checksum": item["checksum"],
                "source": item["source"],
                "data_class": item["data_class"],
                "source_provider": item.get("source_provider"),
                "source_feed": item.get("source_feed"),
                "source_venue": item.get("source_venue"),
                "execution_target": item.get("execution_target"),
                "execution_venue": item.get("execution_venue"),
                "venue_semantics": item.get("venue_semantics", "legacy_dataset_namespace_only"),
                "bid_ask_available": item["bid_availability"],
                "spread_available": item["spread_availability"],
                "tick_available": item["tick_count"],
                "timestamp_quality": {
                    "timezone": item["timezone"],
                    "resolution": item["timestamp_resolution"],
                    "missingness": item["missingness"],
                    "gap_semantics": item.get("gaps", {}),
                },
                "survivorship": "UNAVAILABLE: survivorship requires a multi-instrument universe and membership history",
                "corporate_adjustments": "NOT_APPLICABLE for the registered instrument" if item["instrument"] else "UNAVAILABLE",
                "broker_differences": "UNAVAILABLE: broker session/fill metadata is not in canonical OHLC bars",
                "historical_depth": {
                    "status": "MEASURED",
                    "rows": item["row_count"],
                    "span": item["date_range"],
                },
                "market_regimes": "UNAVAILABLE: regime coverage needs a declared regime taxonomy and sufficient span",
                "execution_conditions": {
                    "status": "UNAVAILABLE",
                    "reason": "no measured bid/ask, latency, slippage, or fill history in OHLC dataset",
                },
                "licensing": "UNAVAILABLE: licensing metadata is not encoded in the manifest",
            }
        )

    if inventory:
        limitation = (
            f"{len(inventory)} canonical dataset version(s), classes={classes}, total_rows={total_rows}, "
            f"largest_dataset_rows={max_rows}; claim eligibility remains dataset-specific and requires measured provenance, depth, span, quality, and costs"
        )
    else:
        limitation = "No canonical dataset versions are registered; depth, provenance, and market coverage are UNAVAILABLE"
    return {
        "available_sources": sources,
        "count": len(sources),
        "limitation": limitation,
        "recommendation": (
            "Acquire provenance-qualified history with licensing, broker/session semantics, bid/ask or measured cost data, "
            "UTC timestamp evidence, multiple regimes, and a declared cross-instrument population before generalizing a claim."
        ),
        "minimum_expansion_needed": {
            "historical_depth": "UNAVAILABLE until the target claim specifies horizon, population, and power requirement",
            "symbols": "UNAVAILABLE until the target population is declared",
            "timeframes": "UNAVAILABLE until the mechanism specifies a timeframe",
            "regimes": "UNAVAILABLE until a regime taxonomy and sufficient history are measured",
            "execution": "measured bid/ask/tick/fill evidence required for execution claims",
        },
        "never_substitute": "Do not substitute synthetic, paper, shadow, demo, imputed, estimated, or model-derived data for claim-eligible market observations.",
        "raw_files": [str(p) for p in sorted((root / "raw").glob("*"))] if (root / "raw").exists() else [],
    }
