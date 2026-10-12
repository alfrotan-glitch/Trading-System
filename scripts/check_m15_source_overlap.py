"""Cross-check a candidate XAUUSD M15 source against the Dukascopy replicate.

Purpose: decide whether a candidate series is an *independent* confirmation of the
Dukascopy quote stream before it is used for anything. It reports, it does not
decide. Output is a diagnostic JSON on stdout (or --out), never research evidence.

Checks:
  1. Timestamp alignment: overlap count and close-to-close error at each whole
     and quarter-hour shift in [-6h, +6h]. The best shift should be 0 when both
     series stamp bars at bar open in UTC.
  2. Price-level agreement over the overlap: median/mean/std of (candidate - duka)
     close, and the fraction of bars within $0.01.
  3. Month-by-month level difference, to expose basis or roll effects that a
     single whole-period figure hides.

Candidate CSV must have columns: datetime (ISO-8601 with UTC offset or naive UTC),
open, high, low, close.

Usage:
  python scripts/check_m15_source_overlap.py --candidate path/to.csv \
      [--duka data/raw/longhistory/dukascopy_mirror_xauusd_15m/data/XAUUSD] [--out r.json]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from qts.research.longhistory.sources import (
    bar_integrity_diagnostics,
    parse_duka_parquet_dir,
    to_utc,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DUKA = REPO_ROOT / "data" / "raw" / "longhistory" / "dukascopy_mirror_xauusd_15m" / "data" / "XAUUSD"


def load_candidate(path: Path, stamp_basis: str = "utc") -> pd.DataFrame:
    frame = pd.read_parquet(path) if path.suffix.lower() == ".parquet" else pd.read_csv(path)
    time_col = "datetime" if "datetime" in frame.columns else "time"
    if time_col not in frame.columns:
        raise ValueError(f"candidate {path} must have a 'datetime' or 'time' column")
    if stamp_basis == "utc":
        stamps = pd.to_datetime(frame[time_col], utc=True).dt.tz_localize(None)
    else:
        stamps = pd.to_datetime(frame[time_col])
        if getattr(stamps.dt, "tz", None) is not None:
            stamps = stamps.dt.tz_localize(None)
    cols = ["open", "high", "low", "close"]
    if "volume" in frame.columns:
        cols.append("volume")
    elif "tick_volume" in frame.columns:
        frame = frame.rename(columns={"tick_volume": "volume"})
        cols.append("volume")
    frame = frame.assign(stamp=stamps).set_index("stamp")
    frame = frame[cols].astype(float)
    if frame.index.duplicated().any():
        raise ValueError("candidate has duplicate timestamps")
    frame = frame.sort_index()
    return to_utc(frame, stamp_basis)


def shift_scan(duka: pd.DataFrame, cand: pd.DataFrame) -> list[dict]:
    rows = []
    for hours in np.arange(-6, 6.25, 0.25):
        shifted = cand.copy()
        shifted.index = cand.index + pd.Timedelta(hours=float(hours))
        common = duka.index.intersection(shifted.index)
        if len(common) == 0:
            continue
        err = (duka.loc[common, "close"] - shifted.loc[common, "close"]).abs()
        rows.append(
            {
                "shift_h": round(float(hours), 2),
                "overlap_bars": int(len(common)),
                "median_abs_close_diff": round(float(err.median()), 4),
            }
        )
    return rows


def level_stats(duka: pd.DataFrame, cand: pd.DataFrame) -> dict:
    common = duka.index.intersection(cand.index)
    diff = cand.loc[common, "close"] - duka.loc[common, "close"]
    monthly = diff.groupby(diff.index.to_period("M")).agg(["count", "median", "mean", "std"])
    return {
        "overlap_bars": int(len(common)),
        "candidate_minus_duka_close": {
            "median": round(float(diff.median()), 4),
            "mean": round(float(diff.mean()), 4),
            "std": round(float(diff.std()), 4),
            "frac_within_1_cent": round(float((diff.abs() <= 0.01).mean()), 4),
        },
        "by_month": {
            str(period): {
                "bars": int(row["count"]),
                "median": round(float(row["median"]), 4),
                "std": round(float(row["std"]), 4),
            }
            for period, row in monthly.iterrows()
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument(
        "--stamp-basis",
        choices=["utc", "server_gmt23_us_dst", "server_gmt23_eu_dst"],
        default="utc",
        help="Timestamp basis of candidate before UTC comparison (default: utc)",
    )
    parser.add_argument("--duka", type=Path, default=DEFAULT_DUKA)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    duka = parse_duka_parquet_dir(args.duka)
    cand = load_candidate(args.candidate, stamp_basis=args.stamp_basis)
    scan = shift_scan(duka, cand)
    best = min(scan, key=lambda r: r["median_abs_close_diff"]) if scan else None
    report = {
        "schema": "qts.m15_source_overlap_check.v1",
        "reference": "dukascopy_mirror_xauusd_15m (4d6f155)",
        "candidate_file": str(args.candidate),
        "candidate_stamp_basis": args.stamp_basis,
        "candidate_span": [str(cand.index.min()), str(cand.index.max())],
        "candidate_bars": int(len(cand)),
        "integrity_diagnostics": bar_integrity_diagnostics(cand),
        "best_shift": best,
        "shift_scan": scan,
        "level": level_stats(duka, cand.loc[:, ["open", "high", "low", "close"]]) if best else None,
        "verdict_note": "Diagnostic only. Agreement is needed before any candidate is treated as a replicate.",
    }
    text = json.dumps(report, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
