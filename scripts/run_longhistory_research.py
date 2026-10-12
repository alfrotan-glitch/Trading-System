#!/usr/bin/env python3
"""Run the frozen long-history XAUUSD protocol.

``--stage dev``   walk-forward folds 2010-2019 only (pipeline debugging; no holdout).
``--stage final`` walk-forward, untouched holdout 2020-01..2025-02, cost stresses,
                  regime attribution, the Dukascopy replicate and the gate verdict.

Writes ``data/evidence/longhistory/research_<stage>.json``. Run ``final`` once,
after the preregistration is committed. See
``docs/research/preregistration_longhistory_2026-10-10.md``.
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

from qts.research.longhistory import protocol as P  # noqa: E402
from qts.research.longhistory import runner as R  # noqa: E402
from qts.research.longhistory import sources as S  # noqa: E402

PROCESSED = REPO_ROOT / "data" / "raw" / "longhistory" / "processed"
EVIDENCE_DIR = REPO_ROOT / "data" / "evidence" / "longhistory"


def load_daily(path: Path) -> pd.DataFrame:
    frame = S.read_csv_utc(path)
    frame.index = pd.DatetimeIndex(frame.index.normalize(), name="day")
    return frame.loc[~frame.index.duplicated()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stage", choices=["dev", "final"], required=True)
    args = parser.parse_args()

    research = load_daily(PROCESSED / "xauusd_basemax_utc_daily_research.csv")
    if research.index[-1] > pd.Timestamp(P.RESEARCH_END):
        raise SystemExit("research series extends past RESEARCH_END; rebuild the dataset")
    replicate = load_daily(PROCESSED / "xauusd_dukascopy_utc_daily_replicate.csv") if args.stage == "final" else None

    plans = R.build_plans(research)
    result = R.evaluate(research, plans, args.stage, replicate_df=replicate)
    result["generated_at"] = datetime.now(UTC).isoformat()
    result["data"] = {
        "research_daily_rows": int(len(research)),
        "replicate_daily_rows": int(len(replicate)) if replicate is not None else None,
        "research_source": "basemax_xauusd_15m (UTC-normalised), complete days only",
        "replicate_source": "dukascopy mirror (UTC), complete days only",
    }
    out = EVIDENCE_DIR / f"research_{args.stage}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(f"verdict: {result['verdict']['status']}")
    for group, rec in result.get("gates", {}).items():
        if isinstance(rec, dict) and "failed" in rec:
            print(f"  {group:22s} passes_all={rec.get('passes_all')} failed={rec.get('failed')}")
    if args.stage == "final":
        tables = REPO_ROOT / "docs" / "research" / "longhistory_results_tables_2026-10-10.md"
        tables.write_text(R.render_tables(result), encoding="utf-8")
        print(f"wrote {tables.relative_to(REPO_ROOT)}")
    print(f"wrote {out.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
