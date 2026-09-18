"""Data Source Audit — licensing, depth, timestamp quality, bid/ask, spread, tick, survivorship."""

from __future__ import annotations

import json
from pathlib import Path
from datetime import UTC, datetime
from typing import Any

from qts.data.store import SqliteParquetDataStore


def audit_data_sources() -> dict[str, Any]:
    """Inspect available data, report limitation explicitly if only one dataset."""
    store = SqliteParquetDataStore()
    versions = store.list_versions()
    manifests = [store.manifest(v).model_dump() for v in versions] if versions else []
    # Check directories
    sources = []
    for v in manifests:
        sources.append({
            "version": v["version"],
            "instrument": v["instrument"],
            "timeframe": v["timeframe"],
            "rows": v["rows"],
            "start": v["start"],
            "end": v["end"],
            "checksum": v["checksum"],
            "source": v.get("source", "unknown"),
            "bid_ask_available": False,  # our sample only has OHLC, no bid/ask
            "spread_available": "proxy via high-low only",
            "tick_available": False,
            "timestamp_quality": v.get("timezone", "UTC"),
            "survivorship": "single symbol XAUUSD, no survivorship issue for FX/metal",
            "corporate_adjustments": "not applicable (XAUUSD)",
            "broker_differences": "mock vs real MT5 not distinguished in sample — limitation",
            "historical_depth": f"{v['rows']} bars (~{v['rows']/24:.1f} days for 1H)",
            "market_regimes": "limited to 2020-01 sample, not multi-regime",
            "execution_conditions": "not real tick, spread proxy only",
            "licensing": "synthetic_or_csv — internal, no external licensing, not production market data",
        })
    comparison = {
        "available_sources": sources,
        "count": len(sources),
        "limitation": "Only 1-2 XAUUSD 1H 500-row samples available — minimum depth for credible research is >> 5000 bars across multiple years/regimes. Current data insufficient for generality; results are illustrative, not production. Do not increase data until strategy looks good — expansion only for reducing uncertainty.",
        "recommendation": "Acquire at least 2 years XAUUSD 1H (or 1M) with real bid/ask, true spread, tick, multiple symbols (EURUSD, BTC), multiple timeframes, from broker MT5 history or dukascopy/first-rate, with licensing cleared, timestamp UTC, survivorship documented.",
        "minimum_expansion_needed": {
            "historical_depth": "5000+ bars (6 months 1H) ideally 2 years",
            "symbols": "XAUUSD + 1-2 majors for cross-asset check",
            "timeframes": "1H + 15m or 1M for multi-timeframe structure",
            "regimes": "include 2020-2024 varied volatility",
            "execution": "real spread/bid-ask/tick for execution-aware research",
        },
        "never_substitute": "Do not silently substitute convenient synthetic for real market data — structural difference (GBM vs real microstructure) invalidates execution assumptions.",
    }
    # Also check raw tick availability
    raw_files = list(Path("data/raw").glob("*")) if Path("data/raw").exists() else []
    comparison["raw_files"] = [str(p) for p in raw_files]
    return comparison
