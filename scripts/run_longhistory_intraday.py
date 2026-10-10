#!/usr/bin/env python3
"""Run the frozen M15 intraday XAUUSD protocol (LH-XAUUSD-M15-2026-10-10).

``--stage dev``   walk-forward folds 2010-2019 only (no holdout, no replicate).
``--stage final`` walk-forward, untouched holdout 2020-01..2025-02, cost
                  stresses, regime attribution, Dukascopy M15 replicate, and
                  the gate verdict. Also runs bias checks on every candidate.

Only complete trading days (per :mod:`qts.research.longhistory.daily`) are used,
so a partial session can never generate a signal or a fill.

Writes ``data/evidence/longhistory/intraday_research_<stage>.json``. Run
``final`` once, after the intraday preregistration is committed. See
``docs/research/preregistration_longhistory_m15_2026-10-10.md``.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from qts.research.longhistory import checks as C  # noqa: E402
from qts.research.longhistory import daily as D  # noqa: E402
from qts.research.longhistory import intraday_protocol as I  # noqa: E402
from qts.research.longhistory import runner as R  # noqa: E402
from qts.research.longhistory import signals as G  # noqa: E402
from qts.research.longhistory import sources as S  # noqa: E402

PROCESSED = REPO_ROOT / "data" / "raw" / "longhistory" / "processed"
EVIDENCE_DIR = REPO_ROOT / "data" / "evidence" / "longhistory"
RESEARCH_FILE = PROCESSED / "xauusd_basemax_utc_15m_20040611_20250228.csv"
REPLICATE_FILE = PROCESSED / "xauusd_dukascopy_utc_15m_20250806_20260916.csv"


def load_complete_m15(path: Path, last_label: str | None = None) -> pd.DataFrame:
    """UTC M15 bars restricted to complete trading days (and to ``last_label``)."""
    bars = S.read_csv_utc(path)
    complete_days, _ = D.to_daily(bars)
    labels = D.trading_day_label(pd.DatetimeIndex(bars.index))
    keep = np.asarray(labels.isin(complete_days.index))
    if last_label is not None:
        keep &= np.asarray(labels <= pd.Timestamp(last_label))
    out = bars.loc[keep]
    if out.index.duplicated().any():
        raise SystemExit(f"duplicate bar timestamps in {path.name}")
    return out


def bias_checks(df: pd.DataFrame) -> dict[str, object]:
    """Truncation (causality) on every candidate, and warm-up on the shared indicators."""
    n = len(df)
    cuts = sorted({int(n * f) for f in (0.25, 0.5, 0.75)})
    out: dict[str, object] = {"truncation": {}, "warmup": {}}
    for cand in I.CANDIDATES:
        rep = C.truncation_check(cand.builder, df, cuts)
        out["truncation"][cand.cid] = rep.as_dict()
    offset = n // 3
    burn = 2000  # bars; ATR(14) and realised vol(5520) converge far inside this
    atr_rep = C.warmup_check(lambda d: G.atr(d, 14), df, burn, offset)
    vol_rep = C.warmup_check(lambda d: G.realized_vol(d["close"], I.VOL_BARS, I.PERIODS_PER_YEAR), df, burn, offset)
    out["warmup"] = {"atr14": atr_rep.as_dict(), "realized_vol": vol_rep.as_dict(), "burn_in_bars": burn}
    out["all_passed"] = bool(all(v["passed"] for v in out["truncation"].values()) and atr_rep.passed and vol_rep.passed)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stage", choices=["dev", "final"], required=True)
    args = parser.parse_args()

    research = load_complete_m15(RESEARCH_FILE, last_label=I.RESEARCH_END)
    replicate = load_complete_m15(REPLICATE_FILE) if args.stage == "final" else None

    plans = R.build_plans(research, I)
    result = R.evaluate(research, plans, args.stage, replicate_df=replicate, proto=I)
    if args.stage == "final":
        result["bias_checks"] = bias_checks(research)
    result["generated_at"] = datetime.now(UTC).isoformat()
    result["data"] = {
        "research_m15_bars": int(len(research)),
        "research_first_bar": str(research.index[0]),
        "research_last_bar": str(research.index[-1]),
        "replicate_m15_bars": int(len(replicate)) if replicate is not None else None,
        "research_source": "basemax_xauusd_15m (UTC), complete trading days only",
        "replicate_source": "dukascopy mirror (UTC) M15, complete trading days only",
        "bars_per_day": I.BARS_PER_DAY,
        "periods_per_year": I.PERIODS_PER_YEAR,
    }
    out = EVIDENCE_DIR / f"intraday_research_{args.stage}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(f"verdict: {result['verdict']['status']}")
    for group, rec in result.get("gates", {}).items():
        if isinstance(rec, dict) and "failed" in rec:
            print(f"  {group:22s} passes_all={rec.get('passes_all')} failed={rec.get('failed')}")
    if args.stage == "final":
        tables = REPO_ROOT / "docs" / "research" / "longhistory_intraday_results_tables_2026-10-10.md"
        tables.write_text(R.render_tables(result), encoding="utf-8")
        print(f"bias checks all_passed={result['bias_checks']['all_passed']}")
        print(f"wrote {tables.relative_to(REPO_ROOT)}")
    print(f"wrote {out.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
