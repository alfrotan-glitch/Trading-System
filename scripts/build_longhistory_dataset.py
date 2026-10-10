#!/usr/bin/env python3
"""Build the normalised long-history XAUUSD research series and its quality evidence.

Inputs : ``data/raw/longhistory/`` (run ``scripts/fetch_longhistory_sources.py`` first).
Outputs:
  * ``data/raw/longhistory/processed/*.csv`` (gitignored): UTC 15-minute research
    series and UTC daily series, each with a SHA-256 recorded in the evidence;
  * ``data/evidence/longhistory/data_quality.json`` (committed, no prices):
    structural quality, the broker-clock fit, cross-source agreement and coverage.

Every step is deterministic. A bar is never filled, interpolated or repaired.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from qts.research.longhistory import daily as D  # noqa: E402
from qts.research.longhistory import protocol as P  # noqa: E402
from qts.research.longhistory import sources as S  # noqa: E402

RAW = REPO_ROOT / "data" / "raw" / "longhistory"
PROCESSED = RAW / "processed"
EVIDENCE = REPO_ROOT / "data" / "evidence" / "longhistory" / "data_quality.json"


def _clock_by_window(
    reference: pd.DataFrame, candidate_utc: pd.DataFrame, windows: list[tuple[str, str]]
) -> list[dict]:
    rows = []
    for start, end in windows:
        ref = reference.loc[start:end]
        cand = candidate_utc.loc[
            pd.Timestamp(start) - pd.Timedelta(hours=8) : pd.Timestamp(end) + pd.Timedelta(hours=8)
        ]
        if len(ref) < 200 or len(cand) < 200:
            continue
        fit = S.clock_fit(ref, cand, hours=range(-4, 5))
        rows.append(
            {"window": [start, end], "best_shift_hours": fit["best_shift_hours"], "correlations": fit["correlations"]}
        )
    return rows


def main() -> int:
    if not RAW.is_dir():
        raise SystemExit("raw sources missing; run scripts/fetch_longhistory_sources.py first")
    PROCESSED.mkdir(parents=True, exist_ok=True)

    basemax_raw = S.parse_basemax_csv(RAW / "basemax_xauusd_15m" / "XAU_15m_data.csv")
    ejt_raw = S.parse_ejt_m15_csv(RAW / "ejtraderlabs_xauusd_m15_d1" / "XAUUSD" / "XAUUSDm15.csv")
    yuan_raw = S.parse_yuan_dir(RAW / "yuan_public_xauusd_15m" / "OHLC" / "XAUUSD" / "PT15M")
    duka_raw = S.parse_duka_parquet_dir(RAW / "dukascopy_mirror_xauusd_15m" / "data" / "XAUUSD")

    base_utc = S.to_utc(basemax_raw, "server_gmt23_us_dst")
    ejt_utc = S.to_utc(ejt_raw, "server_gmt23_us_dst")  # same export family; same clock as BaseMax (tested below)
    yuan_utc = S.to_utc(yuan_raw, "utc")
    duka_utc = S.to_utc(duka_raw, "utc")

    # ----- clock evidence
    clock_yuan_raw = S.clock_fit(
        yuan_raw.loc["2022-03-09":"2024-04-19"], basemax_raw.loc["2022-03-01":"2024-04-30"], hours=range(-4, 5)
    )
    clock_yuan_utc = S.clock_fit(
        yuan_utc.loc["2022-03-09":"2024-04-19"], base_utc.loc["2022-03-01":"2024-04-30"], hours=range(-4, 5)
    )
    windows = [
        ("2022-03-10", "2022-09-30"),
        ("2022-10-01", "2023-03-15"),
        ("2023-03-20", "2023-10-25"),
        ("2023-10-30", "2024-03-20"),
        ("2024-03-25", "2024-04-19"),
    ]
    clock_by_window = _clock_by_window(yuan_utc, base_utc, windows)

    # ----- cross-source price agreement (not independent evidence; see provenance doc)
    overlap = base_utc.index.intersection(yuan_utc.index)
    yuan_diff = (base_utc.loc[overlap, "close"] - yuan_utc.loc[overlap, "close"]).abs()
    ejt_overlap = base_utc.index.intersection(ejt_utc.index)
    ejt_close_diff = (base_utc.loc[ejt_overlap, "close"] - ejt_utc.loc[ejt_overlap, "close"]).abs()
    ejt_exact_share = float(np.mean(ejt_close_diff.to_numpy() < 1e-9)) if len(ejt_overlap) else None
    price_agreement = {
        "basemax_vs_yuan_overlap_bars": int(len(overlap)),
        "basemax_vs_yuan_median_abs_close_diff_usd": round(float(yuan_diff.median()), 4),
        "basemax_vs_yuan_p90_abs_close_diff_usd": round(float(yuan_diff.quantile(0.9)), 4),
        "basemax_vs_yuan_p99_abs_close_diff_usd": round(float(yuan_diff.quantile(0.99)), 4),
        "basemax_vs_ejt_overlap_bars": int(len(ejt_overlap)),
        "basemax_vs_ejt_exact_close_share": ejt_exact_share,
        "dukascopy_overlap_with_basemax_bars": int(len(base_utc.index.intersection(duka_utc.index))),
        "note": "BaseMax, ejtraderLabs and Yuan agree to cents, so they are one quote stream exported "
        "three times and cannot corroborate prices independently. Dukascopy has no overlap with BaseMax.",
    }

    # ----- research series: BaseMax UTC, complete months only
    research_15m = base_utc.loc[
        P.RESEARCH_START : pd.Timestamp(P.RESEARCH_END) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    ]
    research_path = PROCESSED / f"xauusd_basemax_utc_15m_{P.RESEARCH_START}_{P.RESEARCH_END}.csv".replace("-", "")
    research_sha = S.write_csv_utc(research_15m, research_path)
    replicate_15m = duka_utc.loc[
        P.REPLICATE_START : pd.Timestamp(P.REPLICATE_END) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    ]
    replicate_path = PROCESSED / f"xauusd_dukascopy_utc_15m_{P.REPLICATE_START}_{P.REPLICATE_END}.csv".replace("-", "")
    replicate_sha = S.write_csv_utc(replicate_15m, replicate_path)

    research_daily, research_cov = D.to_daily(research_15m)
    replicate_daily, replicate_cov = D.to_daily(replicate_15m)
    daily_research_path = PROCESSED / "xauusd_basemax_utc_daily_research.csv"
    daily_replicate_path = PROCESSED / "xauusd_dukascopy_utc_daily_replicate.csv"
    daily_research_sha = S.write_csv_utc(
        research_daily[["open", "high", "low", "close", "volume"]], daily_research_path
    )
    daily_replicate_sha = S.write_csv_utc(
        replicate_daily[["open", "high", "low", "close", "volume"]], daily_replicate_path
    )

    # ----- monthly completeness (shows where the source thins out)
    monthly = base_utc.groupby([base_utc.index.year, base_utc.index.month]).size()
    recent_monthly = {f"{y}-{m:02d}": int(v) for (y, m), v in monthly.loc[2024:].items()}

    evidence = {
        "schema": "qts.longhistory.data_quality.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "prereg_id": P.PREREG_ID,
        "sources": {
            "basemax_xauusd_15m": {
                "structure": S.quality_report(basemax_raw, "basemax_raw_server_clock").as_dict(),
                "clock": {
                    "stamp_basis_inferred": "server GMT+2 (winter) / GMT+3 (US DST)",
                    "raw_fit_vs_yuan_utc": clock_yuan_raw,
                    "converted_fit_vs_yuan_utc": clock_yuan_utc,
                    "by_window_after_conversion": clock_by_window,
                },
                "coverage_research_window": {
                    "first_utc": str(research_15m.index[0]),
                    "last_utc": str(research_15m.index[-1]),
                    "bars": int(len(research_15m)),
                },
                "monthly_bars_2024_onward_server_clock": recent_monthly,
                "daily_coverage_research": research_cov.__dict__,
            },
            "ejtraderlabs_xauusd_m15": {
                "structure": S.quality_report(ejt_raw, "ejt_m15_points_div_100").as_dict(),
                "note": "x100 point prices; /100 applied and verified against BaseMax (see price_agreement)",
            },
            "yuan_public_xauusd_15m": {
                "structure": S.quality_report(yuan_raw, "yuan_pt15m_utc").as_dict(),
                "note": "explicit UTC; chunk duplicates checked for conflicts",
            },
            "dukascopy_mirror_xauusd_15m": {
                "structure": S.quality_report(duka_raw, "dukascopy_mirror_utc").as_dict(),
                "daily_coverage_replicate": replicate_cov.__dict__,
            },
        },
        "price_agreement": price_agreement,
        "processed_files": {
            research_path.name: {"sha256": research_sha, "rows": int(len(research_15m))},
            replicate_path.name: {"sha256": replicate_sha, "rows": int(len(replicate_15m))},
            daily_research_path.name: {"sha256": daily_research_sha, "rows": int(len(research_daily))},
            daily_replicate_path.name: {"sha256": daily_replicate_sha, "rows": int(len(replicate_daily))},
        },
        "research_daily_span": {
            "first": str(research_daily.index[0].date()),
            "last": str(research_daily.index[-1].date()),
            "days": int(len(research_daily)),
        },
        "limitations": [
            "Provider and licence of the BaseMax/Kaggle bars are unverified; no broker measurement exists.",
            "Prices in the research window come from one quote stream (see price_agreement); they are not independent.",
            "2025-03 onward is partial in BaseMax; research ends 2025-02-28.",
            "Dukascopy data (2025-08 to 2026-09) is a separate feed but overlaps no BaseMax bar, and an earlier study already used it.",
            "All costs are assumed. Bar volume is a tick count, not traded volume.",
        ],
    }
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(evidence, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(f"research 15m bars: {len(research_15m):,} sha256 {research_sha[:16]}")
    print(f"research daily days: {len(research_daily):,} (partial days excluded: {research_cov.days_partial})")
    print(f"replicate 15m bars: {len(replicate_15m):,}; daily {len(replicate_daily):,}")
    print(f"clock by window: {[(r['window'][0], r['best_shift_hours']) for r in clock_by_window]}")
    print(f"evidence: {EVIDENCE.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
