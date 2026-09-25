"""Canonical hypothesis catalog.

Scientific hypotheses stay in their own modules. This catalog is only the
invocation index: one command, one id, no second copy of the research logic.

Current research conclusion is ``NO_VALIDATED_EDGE``. Listing or running a
hypothesis never promotes it.
"""

from __future__ import annotations

import importlib
from typing import Any

CURRENT_EDGE_STATUS = "NO_VALIDATED_EDGE"

# id -> import path of the existing runner. The runner remains the tested
# entry point; the catalog does not reimplement the hypothesis.
HYPOTHESES: dict[str, dict[str, str]] = {
    "H-1M-01": {
        "module": "scripts.run_xauusd_1m",
        "question": "Does a 1-minute Donchian breakout survive realistic costs?",
    },
    "H-XF-01": {
        "module": "scripts.run_xauusd_cross",
        "question": "Does volatility times spread magnitude predict a tradable move?",
    },
    "H-XF-02": {
        "module": "scripts.run_xauusd_cross_activity",
        "question": "Does volatility times activity magnitude predict a tradable move?",
    },
    "H-DIR-01": {
        "module": "scripts.run_xauusd_directional",
        "question": "Is there a directional edge on the attested discovery view?",
    },
    "H-DIR-02": {
        "module": "scripts.run_xauusd_directional_verifiable",
        "question": "Does the directional result replicate on the verifiable discovery view?",
    },
    "H-DIR-03": {
        "module": "scripts.run_xauusd_spread_directional",
        "question": "Does spread state add a directional edge?",
    },
    "H-MM-01": {
        "module": "scripts.run_xauusd_marketmaking",
        "question": "Does spread capture survive adverse selection?",
    },
    "H-MM-02": {
        "module": "scripts.run_xauusd_marketmaking_wf",
        "question": "Does any market-making result survive walk-forward?",
    },
    "H-TEMP-01": {
        "module": "scripts.run_xauusd_temporal",
        "question": "Does hour-of-day magnitude survive costs?",
    },
    "H-ST-02": {
        "module": "scripts.run_xauusd_walkforward",
        "question": "Does a magnitude signal survive walk-forward validation?",
    },
    "H-DISC": {
        "module": "scripts.run_xauusd_discovery",
        "question": "Preregistered discovery-window scan on the canonical zip.",
    },
    "H-MICRO": {
        "module": "scripts.run_xauusd_microstructure",
        "question": "Preregistered microstructure scan on the canonical zip.",
    },
    "H-STATE": {
        "module": "scripts.run_xauusd_state_scan",
        "question": "Preregistered state-conditional scan on the canonical zip.",
    },
    "H-VOL": {
        "module": "scripts.run_xauusd_volatility",
        "question": "Preregistered volatility-state scan on the canonical zip.",
    },
    "H-TEMP-DISC": {
        "module": "scripts.run_xauusd_temporal_discovery",
        "question": "Temporal descriptive discovery. Not a trading authorization.",
    },
}


def list_hypotheses() -> list[dict[str, str]]:
    """Registered hypotheses. None of them is a validated trading opportunity."""
    rows = []
    for hypothesis_id, spec in HYPOTHESES.items():
        rows.append(
            {
                "id": hypothesis_id,
                "question": spec["question"],
                "runner": spec["module"],
                "edge_status": CURRENT_EDGE_STATUS,
                "trading_authorization": "NONE",
            }
        )
    return rows


def resolve_hypothesis(hypothesis_id: str) -> dict[str, str] | None:
    key = hypothesis_id.strip().upper()
    if key in HYPOTHESES:
        return {"id": key, **HYPOTHESES[key]}
    return None


def dispatch_hypothesis(hypothesis_id: str, argv: list[str] | None = None) -> int:
    """Run one registered hypothesis. Unknown ids fail closed. Never promotes."""
    spec = resolve_hypothesis(hypothesis_id)
    if spec is None:
        known = ", ".join(HYPOTHESES)
        raise SystemExit(f"unknown hypothesis {hypothesis_id!r}. Known: {known}")
    module = importlib.import_module(spec["module"])
    runner: Any = getattr(module, "main", None)
    if not callable(runner):
        raise SystemExit(f"{spec['module']} has no main(); refusing to invent a runner")
    result = runner(list(argv or []))
    return int(result or 0)
