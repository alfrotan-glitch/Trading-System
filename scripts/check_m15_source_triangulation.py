"""Triangulate the XAUUSD price basis across the sources that overlap in time.

Diagnostic only. It NEVER selects, tunes, or evaluates the reserved holdout:

  A. Weekly / 3-day open prices (getdata-finance samples, 2024-09 to 2026-09) compared
     at identical UTC stamps against the BaseMax M15 bar opening at the same instant
     (primary research series) and against the Dukascopy M15 bar (replicate).
  B. The frozen holdout selections (from ``intraday_research_final.json``) applied
     unchanged to the getdata 15-minute sample and to the Dukascopy replicate over
     their common window, at the protocol's assumed base cost. Same window, two
     streams. Informational: short window, few round turns, not gating.

Inputs (all machine-local, gitignored under data/raw/):
  data/raw/longhistory/ (BaseMax, Dukascopy: run scripts/fetch_longhistory_sources.py)
  data/raw/external_checks/getdata_15m|getdata_1w|getdata_3d/ (git clones of the
  getdata-finance sample repos, pinned by the commit printed in the report).

Usage: python scripts/check_m15_source_triangulation.py [--out report.json]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from qts.research.longhistory import daily as D  # noqa: E402
from qts.research.longhistory import intraday_protocol as I  # noqa: E402
from qts.research.longhistory import runner as R  # noqa: E402
from qts.research.longhistory import sources as S  # noqa: E402
from qts.research.longhistory import stats as ST  # noqa: E402

EXTERNAL = REPO_ROOT / "data" / "raw" / "external_checks"
BASEMAX = REPO_ROOT / "data" / "raw" / "longhistory" / "basemax_xauusd_15m" / "XAU_15m_data.csv"
DUKA = REPO_ROOT / "data" / "raw" / "longhistory" / "dukascopy_mirror_xauusd_15m" / "data" / "XAUUSD"
SELECTION = REPO_ROOT / "data" / "evidence" / "longhistory" / "intraday_research_final.json"


def load_utc_ohlcv(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, parse_dates=["datetime"])
    frame["datetime"] = pd.to_datetime(frame["datetime"], utc=True).dt.tz_localize(None)
    frame = frame.set_index("datetime")
    return frame[["open", "high", "low", "close", "volume"]].astype(float)


def complete_days(frame: pd.DataFrame) -> pd.DataFrame:
    complete, _ = D.to_daily(frame)
    labels = D.trading_day_label(pd.DatetimeIndex(frame.index))
    return frame.loc[np.asarray(labels.isin(complete.index))]


def open_agreement(sample: pd.DataFrame, ref: pd.DataFrame) -> dict:
    common = sample.index.intersection(ref.index)
    if len(common) == 0:
        return {"overlap_bars": 0}
    diff = sample.loc[common, "open"] - ref.loc[common, "open"]
    quarters = diff.groupby(diff.index.to_period("Q")).median()
    return {
        "overlap_bars": int(len(common)),
        "span": [str(common.min().date()), str(common.max().date())],
        "median_diff_usd": round(float(diff.median()), 2),
        "median_abs_diff_usd": round(float(diff.abs().median()), 2),
        "share_within_50c": round(float((diff.abs() <= 0.5).mean()), 3),
        "median_diff_by_quarter_usd": {str(k): round(float(v), 2) for k, v in quarters.items()},
    }


def frozen_selection_on_stream(frame: pd.DataFrame, selection: dict[str, str], start: str, end: str) -> dict:
    window = frame.loc[start:end]
    out: dict[str, object] = {"bars": int(len(window)), "span": [str(window.index.min()), str(window.index.max())]}
    rows: dict[str, object] = {}
    for group, cid in selection.items():
        plan = I.candidate_by_id(cid).builder(window)
        first_valid = int(np.argmax(np.isfinite(plan.target))) if np.isfinite(plan.target).any() else len(plan.target)
        if first_valid > 0.25 * len(window):
            rows[group] = {"cid": cid, "status": "NOT_EVALUABLE_INSUFFICIENT_WARMUP"}
            continue
        run = R.run_window(window, plan, str(window.index.min().date()), str(window.index.max().date()), I.COST_BASE)
        summary = ST.summarize(run, periods_per_year=I.PERIODS_PER_YEAR)
        rows[group] = {
            "cid": cid,
            "net_usd": summary["net_usd"],
            "sharpe": summary["sharpe"],
            "round_turns": summary["round_turns"],
        }
    bh = ST.summarize(
        R.buy_and_hold(window, str(window.index.min().date()), str(window.index.max().date()), I.COST_BASE),
        periods_per_year=I.PERIODS_PER_YEAR,
    )
    rows["buy_and_hold"] = {"net_usd": bh["net_usd"], "sharpe": bh["sharpe"]}
    out["results"] = rows
    return out


def git_commit(path: Path) -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    basemax = S.parse_basemax_csv(BASEMAX)
    basemax.index = S.server_gmt23_to_utc(basemax.index)
    duka = complete_days(S.parse_duka_parquet_dir(DUKA).assign(volume=1.0))
    getdata_15m = complete_days(load_utc_ohlcv(EXTERNAL / "getdata_15m" / "XAUUSD_15m.csv"))
    getdata_1w = load_utc_ohlcv(EXTERNAL / "getdata_1w" / "XAUUSD_1w.csv")
    getdata_3d = load_utc_ohlcv(EXTERNAL / "getdata_3d" / "XAUUSD_3d.csv")

    selection_raw = json.loads(SELECTION.read_text(encoding="utf-8"))["holdout"]["selection"]
    selection = {g: v["cid"] for g, v in selection_raw.items() if v.get("cid")}

    # Exact common timestamp range, so both streams are evaluated on identical bars.
    overlap_start = str(max(duka.index.min(), getdata_15m.index.min()))
    overlap_end = str(min(duka.index.max(), getdata_15m.index.max()))

    report = {
        "schema": "qts.m15_source_triangulation.v1",
        "diagnostic_only": True,
        "not_used_for_selection": True,
        "holdout_touched": False,
        "getdata_commits": {
            name: git_commit(EXTERNAL / name) for name in ("getdata_15m", "getdata_1w", "getdata_3d")
        },
        "A_open_agreement": {
            "getdata_1w_vs_basemax": open_agreement(getdata_1w, basemax),
            "getdata_1w_vs_dukascopy": open_agreement(getdata_1w, duka),
            "getdata_3d_vs_basemax": open_agreement(getdata_3d, basemax),
            "getdata_3d_vs_dukascopy": open_agreement(getdata_3d, duka),
        },
        "B_frozen_selection_same_window": {
            "window": [overlap_start, overlap_end],
            "dukascopy": frozen_selection_on_stream(duka, selection, overlap_start, overlap_end),
            "getdata_15m": frozen_selection_on_stream(getdata_15m, selection, overlap_start, overlap_end),
        },
        "caveats": [
            "A and B are short windows (about six months). Round-turn counts are low for some candidates.",
            "Costs are ASSUMED. The comparison is of relative behaviour across streams, not of a net result.",
            "getdata is an undisclosed-provenance sample. Neither stream is validated as the reference.",
        ],
    }
    text = json.dumps(report, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
