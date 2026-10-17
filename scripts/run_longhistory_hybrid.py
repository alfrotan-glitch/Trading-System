#!/usr/bin/env python3
"""Run the frozen monthly slow-hybrid XAUUSD protocol (LH-XAUUSD-HYB-2026-10-17).

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

Writes ``data/evidence/longhistory/hybrid_research_<stage>.json``. Run
``final`` once, after the preregistration is committed. See
``docs/research/preregistration_longhistory_hybrid_2026-10-17.md``.
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

from qts.research.longhistory import hybrid_protocol as HYB  # noqa: E402
from qts.research.longhistory import runner as R  # noqa: E402
from qts.research.longhistory import stats as ST  # noqa: E402

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


def replicate_with_context(
    context_df: pd.DataFrame, replicate_df: pd.DataFrame, selection: dict, proto=HYB
) -> dict:
    """Frozen selections on BaseMax monthly bars with a research history prefix.

    Plans are built on research months strictly before the replicate window
    followed by the replicate months (builders need warm-up; the run window
    itself is replicate-only and starts flat). Independent quote stream and
    next-open execution convention; informational, never gating.
    """
    prefix = context_df[context_df.index < replicate_df.index[0]]
    combined = pd.concat([prefix, replicate_df])
    out: dict = {}
    for group, sel in selection.items():
        cid = sel.get("cid") if isinstance(sel, dict) else None
        if cid is None:
            out[group] = {"cid": None, "status": "NO_SELECTION"}
            continue
        cand = proto.candidate_by_id(str(cid))
        plan = cand.builder(combined)
        run = R.run_window(combined, plan, proto.REPLICATE_START, proto.REPLICATE_END, proto.COST_BASE)
        out[group] = {
            "cid": cid,
            "status": "EVALUATED",
            "history_prefix_months": int(len(prefix)),
            "execution_convention": "next-open fills on real BaseMax monthly OHLC",
            **ST.summarize(run, periods_per_year=proto.PERIODS_PER_YEAR),
        }
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stage", choices=["dev", "final"], required=True)
    args = parser.parse_args()

    research = load_monthly(RESEARCH_FILE, ("open", "high", "low", "close", "usd"))
    replicate = (
        load_monthly(REPLICATE_FILE, ("open", "high", "low", "close", "usd"))
        if args.stage == "final"
        else None
    )

    plans = R.build_plans(research, HYB)
    # The replicate is attached below with a history prefix (the shared
    # evaluate() would rebuild plans on the replicate frame alone, starving
    # the 12-month builders of warm-up), so evaluate() sees replicate_df=None.
    result = R.evaluate(research, plans, args.stage, replicate_df=None, proto=HYB)
    if args.stage == "final":
        assert replicate is not None
        result["replicate"] = replicate_with_context(
            research, replicate, result["holdout"]["selection"], HYB
        )
        rep_bh = R.buy_and_hold(replicate, HYB.REPLICATE_START, HYB.REPLICATE_END, HYB.COST_BASE)
        result["benchmarks"]["buy_and_hold_long"]["replicate"] = ST.summarize(
            rep_bh, periods_per_year=HYB.PERIODS_PER_YEAR
        )
    result["generated_at"] = datetime.now(UTC).isoformat()
    result["data"] = {
        "research_monthly_rows": int(len(research)),
        "replicate_monthly_rows": int(len(replicate)) if replicate is not None else None,
        "research_source": "World Bank monthly gold average + Fed H.10 USD index (month-end stamps)",
        "replicate_source": "BaseMax monthly OHLC aggregated from 15m bars (next-open fills)",
    }
    out = EVIDENCE_DIR / f"hybrid_research_{args.stage}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    tables = EVIDENCE_DIR / f"hybrid_research_{args.stage}_tables.md"
    if args.stage == "final":
        tables.write_text(R.render_tables(result), encoding="utf-8")
    print(f"stage={args.stage} verdict={result['verdict']['status']} evidence={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
