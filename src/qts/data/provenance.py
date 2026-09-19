"""Explicit provenance roles for market data manifests.

The legacy ``venue`` field is retained as a storage/instrument namespace for
backward compatibility.  It is never sufficient to identify the source feed or
to prove broker execution history.
"""

from __future__ import annotations

from typing import Any


def describe_source(source: str | None, namespace_venue: str | None = None) -> dict[str, Any]:
    """Return conservative source/execution roles for a source label.

    Known labels receive only facts encoded by the repository's acquisition
    contract.  Unknown labels remain explicit ``None`` rather than being
    upgraded to a broker or REAL interpretation.
    """
    label = (source or "").strip()
    lowered = label.lower()
    result: dict[str, Any] = {
        "source_provider": None,
        "source_feed": None,
        "source_venue": None,
        "execution_target": None,
        "execution_venue": None,
        "venue_semantics": "legacy_dataset_namespace_only",
    }
    if "dukascopy" in lowered:
        result.update(
            {
                "source_provider": "Dukascopy-derived upstream mirror",
                "source_feed": "Dukascopy XAU/USD tick feed; exported mid-price OHLC",
                "source_venue": "Dukascopy XAU/USD feed",
            }
        )
    elif "synthetic" in lowered or "fixture" in lowered or "gbm" in lowered:
        result.update(
            {
                "source_provider": "QTS synthetic fixture",
                "source_feed": "generated fixture bars",
                "source_venue": None,
            }
        )
    elif "mt5_history" in lowered or "broker" in lowered:
        result.update(
            {
                "source_provider": "broker history import",
                "source_feed": "broker-provided historical bars; field semantics require source evidence",
                "source_venue": "broker-specific MT5 history",
            }
        )
    return result
