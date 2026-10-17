#!/usr/bin/env python3
"""Run the frozen weekly slow-hybrid XAUUSD protocol (LH-XAUUSD-WHYB-2026-10-17).

Weekly bars: W-FRI resamples of the complete-day daily series, joined to a
weekly USD index from the pinned Fed H.10 daily FX basket (equal-weight
geometric, last daily observation per W-FRI week; days with < 6 of 8
basket quotes are excluded then last-valid-carried within the daily
index construction — the same basket and convention as the monthly
cycle, at weekly sampling). Data first::

    python scripts/fetch_longhistory_sources.py
    python scripts/fetch_longhistory_monthly_sources.py
    python scripts/build_longhistory_dataset.py

Writes ``data/evidence/longhistory/weekly_hybrid_research_<stage>.json``.
Run ``final`` once, after the preregistration is committed.
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

from qts.research.longhistory import runner as R  # noqa: E402
from qts.research.longhistory import stats as ST  # noqa: E402
from qts.research.longhistory import weekly_hybrid_protocol as WH  # noqa: E402

PROCESSED = REPO_ROOT / "data" / "raw" / "longhistory" / "processed"
FX_DAILY = REPO_ROOT / "data" / "raw" / "fx" / "data" / "daily.csv"
EVIDENCE_DIR = REPO_ROOT / "data" / "evidence" / "longhistory"
BASKET = (
    "Australia", "Canada", "Denmark", "Japan",
    "New Zealand", "Sweden", "Switzerland", "United Kingdom",
)


def weekly_usd_index() -> pd.Series:
    """Weekly (W-FRI) equal-weight USD index from the pinned daily FX file."""
    fx = pd.read_csv(FX_DAILY, parse_dates=["Date"]).rename(
        columns={"Date": "date", "Exchange rate": "v"}
    )
    fx = fx[fx["Country"].isin(BASKET)].dropna(subset=["v"]).sort_values(["Country", "date"])
    fx["base"] = fx.groupby("Country")["v"].transform("first")
    fx["logret"] = np.log(fx["v"] / fx["base"])
    pivot = fx.pivot_table(index="date", columns="Country", values="logret")
    coverage = pivot.notna().sum(axis=1)
    daily_index = np.exp(pivot.mean(axis=1))
    daily_index[coverage < 6] = np.nan
    daily_index = daily_index.ffill()
    weekly = daily_index.resample("W-FRI").last()
    weekly.name = "usd"
    return weekly


def to_weekly_usd(daily: pd.DataFrame, usd_w: pd.Series) -> pd.DataFrame:
    weekly = daily.resample("W-FRI").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}
    )
    weekly = weekly.dropna(subset=["open", "high", "low", "close"])
    weekly.index = pd.DatetimeIndex(weekly.index).tz_localize(None)
    weekly["usd"] = usd_w.reindex(weekly.index)
    out = weekly.dropna(subset=["usd"])
    out.index.name = "utc"
    return out


def load_daily(path: Path) -> pd.DataFrame:
    raw = pd.read_csv(path, parse_dates=["time"])
    frame = raw.set_index("time")[["open", "high", "low", "close"]].astype(float)
    frame.index.name = "utc"
    return frame


def replicate_with_context(context_df, replicate_df, selection, proto=WH):
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
            "history_prefix_weeks": int(len(prefix)),
            **ST.summarize(run, periods_per_year=proto.PERIODS_PER_YEAR),
        }
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stage", choices=["dev", "final"], required=True)
    args = parser.parse_args()

    usd_w = weekly_usd_index()
    research = to_weekly_usd(load_daily(PROCESSED / "xauusd_basemax_utc_daily_research.csv"), usd_w)
    replicate = (
        to_weekly_usd(load_daily(PROCESSED / "xauusd_dukascopy_utc_daily_replicate.csv"), usd_w)
        if args.stage == "final"
        else None
    )

    plans = R.build_plans(research, WH)
    result = R.evaluate(research, plans, args.stage, replicate_df=None, proto=WH)
    if args.stage == "final":
        assert replicate is not None
        result["replicate"] = replicate_with_context(
            research, replicate, result["holdout"]["selection"], WH
        )
        rep_bh = R.buy_and_hold(replicate, WH.REPLICATE_START, WH.REPLICATE_END, WH.COST_BASE)
        result["benchmarks"]["buy_and_hold_long"]["replicate"] = ST.summarize(
            rep_bh, periods_per_year=WH.PERIODS_PER_YEAR
        )
    result["generated_at"] = datetime.now(UTC).isoformat()
    result["data"] = {
        "research_weekly_rows": int(len(research)),
        "replicate_weekly_rows": int(len(replicate)) if replicate is not None else None,
        "research_source": "BaseMax complete-day daily resampled W-FRI + Fed H.10 weekly USD index",
        "replicate_source": "Dukascopy complete-day daily resampled W-FRI + same USD index",
    }
    out = EVIDENCE_DIR / f"weekly_hybrid_research_{args.stage}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    if args.stage == "final":
        (EVIDENCE_DIR / "weekly_hybrid_research_final_tables.md").write_text(
            R.render_tables(result), encoding="utf-8"
        )
    print(f"stage={args.stage} verdict={result['verdict']['status']} evidence={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
