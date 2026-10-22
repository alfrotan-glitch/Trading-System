"""Research round 22: official CFTC disaggregated gold Managed Money positions.

Extends the earlier round 15 legacy workbook (2018-2025, 7.2 years)
with 2006-onward official disaggregated futures-only history. This is a
distinct classification (Managed Money), NOT interchangeable with legacy
non-commercial positions.

Exactly two frozen rules: low crowding reversal and 13-report trend.
Tuesday snapshot availability is assumed FOURTEEN days later. Exceptional
reporting delays are not verified. Existing gold histories are SPENT; the
result is exploratory only, never a validated edge or live signal.

Run:
    python -m scripts.fetch_cftc_gold
    python -m scripts.edgelab_cot_official_run
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from qts.research.edgelab.cot_disaggregated import (
    ASSUMED_PUBLICATION_LAG_DAYS,
    align_published_positions,
    fixed_positioning_hypotheses,
    parse_official_gold,
)
from scripts.edgelab_online_model_run import _portfolio_evaluate
from scripts.edgelab_vix_curve_run import (
    BOUNDS,
    FINANCING_STRESS_BPS_PER_CALENDAR_DAY,
    load_gold_bars_from_basemax,
    paired_hac_difference,
)

SOURCE = Path("data/raw/edgelab/cftc_gold")
OUT = Path("data/research/experiments")
CONFIG = {
    "report_dataset": "72hh-3qpy",
    "gold_code": "088691",
    "release_lag_calendar_days_ASSUMED": ASSUMED_PUBLICATION_LAG_DAYS,
    "crowded_reversal_window_reports": 104,
    "crowded_reversal_percentile": 0.20,
    "positioning_trend_lag_reports": 13,
    "execution": "next_open",
}


def _load_official():
    source_file = SOURCE / "gold_disaggregated_futures_only.json"
    manifest_file = SOURCE / "source_manifest.json"
    if not source_file.exists() or not manifest_file.exists():
        raise FileNotFoundError("Missing direct CFTC data; run python -m scripts.fetch_cftc_gold")
    raw = source_file.read_bytes()
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    if hashlib.sha256(raw).hexdigest() != manifest.get("sha256"):
        raise ValueError("CFTC bytes differ from pinned source manifest")
    if manifest.get("dataset") != CONFIG["report_dataset"]:
        raise ValueError("unexpected CFTC dataset")
    return parse_official_gold(json.loads(raw)), manifest


def main() -> int:
    official, manifest = _load_official()
    gold = load_gold_bars_from_basemax()
    weekly = fixed_positioning_hypotheses(official)
    daily = align_published_positions(weekly, pd.DatetimeIndex(gold.index))
    results = []
    for window, (lo, hi) in BOUNDS.items():
        bars = gold.loc[lo:hi]
        if len(bars) < 252:
            continue
        for strategy in weekly.columns:
            candidate_target = daily[strategy].reindex(bars.index).fillna(0.0)
            # This is a retrospective CONTROL, not a deployable candidate.
            exposure_control = pd.Series(float(candidate_target.mean()), index=bars.index)
            for financing in FINANCING_STRESS_BPS_PER_CALENDAR_DAY:
                candidate, returns = _portfolio_evaluate(
                    bars, candidate_target, financing_bps_per_calendar_day=financing,
                    label=strategy,
                )
                baseline, baseline_net = _portfolio_evaluate(
                    bars, exposure_control, financing_bps_per_calendar_day=financing,
                    label="matched_static_gold",
                )
                comparison = paired_hac_difference(returns, baseline_net)
                results.append(
                    {
                        "window": window,
                        "strategy": strategy,
                        "financing_bps_day_assumed": financing,
                        "candidate": candidate,
                        "matched_static_gold": baseline,
                        "paired_net_difference_HAC": comparison,
                        "evidence_type": "HISTORICAL_DISCOVERY_ONLY",
                    }
                )
    payload = {
        "research_family": "official_cftc_managed_money_positioning",
        "round": 22,
        "created_at": datetime.now(UTC).isoformat(),
        "source": manifest,
        "gold_source": gold.attrs.get("source", "BaseMax M15 verified"),
        "CFTC_report_start": official.index.min().isoformat(),
        "CFTC_report_end": official.index.max().isoformat(),
        "pre_registered_rules": CONFIG,
        "hypothesis_trials": len(weekly.columns),
        "historical_windows_spent": True,
        "publication_timing_fully_verified": False,
        "broker_costs_measured": False,
        "broker_swap_measured": False,
        "validated_edge": False,
        "live_trading_unlocked": False,
        "results": results,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / f"cot_official_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    target.write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")
    print(f"Official CFTC reports {len(official)}: {official.index.min()} to {official.index.max()}")
    print(f"Artifact: {target}")
    for result in results:
        if result["financing_bps_day_assumed"] != 0.0:
            continue
        stats = result["paired_net_difference_HAC"]
        t = stats.get("t_hac")
        t_text = f"{t:+.2f}" if isinstance(t, (int, float)) and math.isfinite(t) else "UNAVAILABLE"
        print(
            f"{result['window']:18s} {result['strategy']:24s} "
            f"model SR={result['candidate']['sharpe']:+.3f} "
            f"matched SR={result['matched_static_gold']['sharpe']:+.3f} "
            f"paired t={t_text}"
        )
    print("Verdict: DISCOVERY ONLY. All historical gold windows SPENT. LIVE LOCKED.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
