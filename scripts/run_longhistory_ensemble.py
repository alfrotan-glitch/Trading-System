#!/usr/bin/env python3
"""Run the frozen monthly ensemble XAUUSD protocol (LH-XAUUSD-ENS-2026-10-17).

``--stage dev``    walk-forward folds 1990-1999 only (pipeline debugging; no
                   evaluation window, no replicate).
``--stage final``  everything: walk-forward, the evaluation window
                   2000-01..2026-09, cost stresses, the financing-charged
                   regime, regime attribution, the BaseMax monthly source
                   replication, and the gate verdict.

Data first::

    python scripts/fetch_longhistory_monthly_sources.py
    python scripts/build_longhistory_dataset.py
    python scripts/build_longhistory_monthly_dataset.py

Writes ``data/evidence/longhistory/ensemble_research_<stage>.json``. Run
``final`` once, after the preregistration is committed. See
``docs/research/preregistration_longhistory_ensemble_2026-10-17.md``.
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

from qts.research.longhistory import ensemble_protocol as ENS  # noqa: E402
from qts.research.longhistory import runner as R  # noqa: E402

PROCESSED = REPO_ROOT / "data" / "raw" / "longhistory" / "processed"
EVIDENCE_DIR = REPO_ROOT / "data" / "evidence" / "longhistory"
RESEARCH_FILE = PROCESSED / "xauusd_worldbank_monthly_utc_197301_202609.csv"
REPLICATE_FILE = PROCESSED / "xauusd_basemax_monthly_utc_200406_202502.csv"


def load_monthly(path: Path, cols: tuple[str, ...]) -> pd.DataFrame:
    raw = pd.read_csv(path)
    missing = {"date", *cols}.difference(raw.columns)
    if missing:
        raise SystemExit(f"{path.name}: missing columns {sorted(missing)}")
    index = pd.to_datetime(raw["date"], utc=True).dt.tz_convert(None)
    bars = raw[list(cols)].astype(float)
    bars.index = pd.DatetimeIndex(index, name="utc")
    if bars.index.duplicated().any() or not bars.index.is_monotonic_increasing:
        raise SystemExit(f"{path.name}: duplicate or unsorted month-end stamps")
    return bars


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stage", choices=["dev", "final"], required=True)
    args = parser.parse_args()

    research = load_monthly(RESEARCH_FILE, ("open", "high", "low", "close", "usd"))
    replicate = (
        load_monthly(REPLICATE_FILE, ("open", "high", "low", "close")) if args.stage == "final" else None
    )

    plans = R.build_plans(research, ENS)
    result = R.evaluate(research, plans, args.stage, replicate_df=replicate, proto=ENS)
    result["generated_at"] = datetime.now(UTC).isoformat()
    result["data"] = {
        "research_monthly_rows": int(len(research)),
        "replicate_monthly_rows": int(len(replicate)) if replicate is not None else None,
        "research_source": "World Bank monthly gold average + Fed H.10 USD index (month-end stamps)",
        "replicate_source": "BaseMax monthly OHLC aggregated from 15m bars (next-open fills)",
    }
    out = EVIDENCE_DIR / f"ensemble_research_{args.stage}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    tables = EVIDENCE_DIR / f"ensemble_research_{args.stage}_tables.md"
    if args.stage == "final":
        tables.write_text(R.render_tables(result), encoding="utf-8")
    print(f"stage={args.stage} verdict={result['verdict']['status']} evidence={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
