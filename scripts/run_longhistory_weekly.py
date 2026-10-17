#!/usr/bin/env python3
"""Run the frozen weekly ensemble XAUUSD protocol (LH-XAUUSD-W1-2026-10-17).

``--stage dev``    walk-forward folds 2010-2019 only (pipeline debugging; no
                   holdout, no replicate).
``--stage final``  everything: walk-forward, the holdout 2020-01..2025-02,
                   cost stresses, regime attribution, the Dukascopy weekly
                   replicate, and the gate verdict.

Weekly bars are W-FRI resamples of the complete-day daily series built by
``scripts/build_longhistory_dataset.py`` (open=first, high=max, low=min,
close=last). Data first::

    python scripts/fetch_longhistory_sources.py
    python scripts/build_longhistory_dataset.py

Writes ``data/evidence/longhistory/weekly_research_<stage>.json``. Run
``final`` once, after the preregistration is committed. See
``docs/research/preregistration_longhistory_weekly_2026-10-17.md``.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from qts.research.longhistory import runner as R  # noqa: E402
from qts.research.longhistory import weekly_protocol as WK  # noqa: E402

PROCESSED = REPO_ROOT / "data" / "raw" / "longhistory" / "processed"
EVIDENCE_DIR = REPO_ROOT / "data" / "evidence" / "longhistory"


def to_weekly(daily: pd.DataFrame) -> pd.DataFrame:
    """W-FRI weekly OHLC from a complete-day daily frame (causal resample)."""
    weekly = daily.resample("W-FRI").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}
    )
    weekly = weekly.dropna(subset=["open", "high", "low", "close"])
    weekly.index.name = "utc"
    return weekly


def load_daily(path: Path) -> pd.DataFrame:
    raw = pd.read_csv(path, parse_dates=["time"])
    frame = raw.set_index("time")[["open", "high", "low", "close"]].astype(float)
    frame.index = pd.DatetimeIndex(frame.index).tz_localize(None)
    frame.index.name = "utc"
    if frame.index.duplicated().any() or not frame.index.is_monotonic_increasing:
        raise SystemExit(f"{path.name}: duplicate or unsorted daily stamps")
    return frame


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stage", choices=["dev", "final"], required=True)
    args = parser.parse_args()

    research = to_weekly(load_daily(PROCESSED / "xauusd_basemax_utc_daily_research.csv"))
    replicate = (
        to_weekly(load_daily(PROCESSED / "xauusd_dukascopy_utc_daily_replicate.csv"))
        if args.stage == "final"
        else None
    )

    plans = R.build_plans(research, WK)
    result = R.evaluate(research, plans, args.stage, replicate_df=replicate, proto=WK)
    result["generated_at"] = datetime.now(UTC).isoformat()
    result["data"] = {
        "research_weekly_rows": int(len(research)),
        "replicate_weekly_rows": int(len(replicate)) if replicate is not None else None,
        "research_source": "BaseMax complete-day daily resampled W-FRI (UTC)",
        "replicate_source": "Dukascopy complete-day daily resampled W-FRI (UTC)",
    }
    out = EVIDENCE_DIR / f"weekly_research_{args.stage}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    if args.stage == "final":
        (EVIDENCE_DIR / "weekly_research_final_tables.md").write_text(
            R.render_tables(result), encoding="utf-8"
        )
    print(f"stage={args.stage} verdict={result['verdict']['status']} evidence={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
