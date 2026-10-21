"""Round 21: one predeclared, leak-free monthly adaptive gold strategy.

This is a research-only learned model, NOT a profitable product strategy.
VIX slope alone failed round 20; the new economic hypothesis is that the
relationship between gold trend and market stress is INTERACTIVE rather than
a fixed directional indicator.

PREDECLARED:
- Five trailing features, one linear ridge model with penalty 20.
- 120-month rolling fit (minimum 60), monthly rebalance.
- All training labels resolved before each prediction; same-month exogenous
  close is lagged a complete extra publication.
- Long/flat, forecast hurdle 0.3% per following month, max leverage 1.
- Test executable next-open prices, ECN turnover costs + funding scenarios.
- Compare against buy-and-hold, 3-month momentum and exposure-matched static
  gold on paired NET returns with Newey-West/HAC errors.
- No tuning after observing the results; all historical windows are SPENT.
- Never register as live or validated, even if this round looks positive.

Run after the Cboe/raw-BaseMax data collector has executed:
    python scripts/edgelab_online_model_run.py
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from qts.research.edgelab import CostModel, run_vector
from qts.research.edgelab.causal_ml import (
    FEATURES,
    OnlineModelConfig,
    daily_long_position,
    prequential_monthly_predictions,
    trailing_feature_frame,
)
from scripts.edgelab_vix_curve_run import (
    BOUNDS,
    FINANCING_STRESS_BPS_PER_CALENDAR_DAY,
    load_curve,
    load_gold_bars_from_basemax,
    paired_hac_difference,
)

COST = CostModel.realistic_ecn()
OUT = Path("data/research/experiments")
BPY = 252.0
MIN_ACTIVE_MONTHS_PER_WINDOW = 6


def _portfolio_evaluate(
    bars: pd.DataFrame,
    targets: pd.Series,
    *,
    financing_bps_per_calendar_day: float,
    label: str,
) -> tuple[dict, pd.Series]:
    """Actual next-open fills plus hypothetical calendar-day financing."""
    result = run_vector(
        bars,
        targets.reindex(bars.index).fillna(0.0),
        COST,
        name=label,
        family="online_ridge",
        bars_per_year=BPY,
        keep_equity=True,
        execution="next_open",
    )
    if result.net_returns is None or result.held is None:
        raise RuntimeError("net equity/holdings not returned by run_vector")
    gap = (
        bars.index.to_series()
        .diff()
        .dt.total_seconds()
        .div(86400.0)
        .reindex(result.net_returns.index)
    )
    if bool(gap.isna().any()) or bool((gap <= 0).any()):
        raise ValueError("missing/invalid calendar gap in gold bars")
    funding = result.held.abs() * gap * (financing_bps_per_calendar_day / 1e4)
    net = result.net_returns - funding
    if bool((net <= -1.0).any()):
        raise ValueError("return depleted below -100%")
    sd = float(net.std(ddof=1))
    cum = (1.0 + net).cumprod()
    dd = 1.0 - cum / cum.cummax()
    return {
        "label": label,
        "cagr": float(cum.iloc[-1] ** (BPY / len(net)) - 1.0),
        "sharpe": float(net.mean() / sd * np.sqrt(BPY)) if sd > 0 else 0.0,
        "max_drawdown": float(dd.max()),
        "avg_held_exposure": float(result.held.abs().mean()),
        "turnover_per_year": result.turnover_per_year,
        "funding_drag_total": float(funding.sum()),
        "net_compound_return": float(cum.iloc[-1] - 1.0),
        "funding_assumption_bps_per_calendar_day": financing_bps_per_calendar_day,
    }, net


def main() -> int:
    bars = load_gold_bars_from_basemax()
    curve = load_curve()
    cfg = OnlineModelConfig()
    features = trailing_feature_frame(bars["close"], curve)
    predictions = prequential_monthly_predictions(features, cfg)
    if not bool(predictions["usable"].any()):
        raise RuntimeError("no usable model predictions: insufficient causal training data")
    targets = daily_long_position(predictions, bars.index)
    # Fixed, economically familiar passive baseline: three-month momentum.
    # Month-end momentum decisions use only prior closes and fill next open.
    mom_target_monthly = (features["mom_3m"] > 0).astype(float)
    mom_target = mom_target_monthly.reindex(bars.index, method="ffill").fillna(0.0)
    buy_hold = pd.Series(1.0, index=bars.index)

    results = []
    for window, (lo, hi) in BOUNDS.items():
        sub = bars.loc[lo:hi]
        if len(sub) < 252:
            continue
        model = targets.reindex(sub.index).fillna(0.0)
        mom = mom_target.reindex(sub.index).fillna(0.0)
        hold = buy_hold.reindex(sub.index).fillna(0.0)
        matched = pd.Series(float(model.mean()), index=sub.index)
        active_months = int(
            predictions.loc[lo:hi, "target_long"].sum()
        )
        for funding_rate in FINANCING_STRESS_BPS_PER_CALENDAR_DAY:
            model_metrics, model_net = _portfolio_evaluate(
                sub, model, financing_bps_per_calendar_day=funding_rate, label="adaptive_ridge"
            )
            benchmark, benchmark_net = _portfolio_evaluate(
                sub, matched, financing_bps_per_calendar_day=funding_rate, label="matched_gold"
            )
            mom_metrics, mom_net = _portfolio_evaluate(
                sub, mom, financing_bps_per_calendar_day=funding_rate, label="fixed_momentum_3m"
            )
            hold_metrics, _ = _portfolio_evaluate(
                sub, hold, financing_bps_per_calendar_day=funding_rate, label="buy_hold"
            )
            paired = paired_hac_difference(model_net, benchmark_net)
            vs_momentum = paired_hac_difference(model_net, mom_net)
            results.append(
                {
                    "window": window,
                    "financing_bps_calendar_day_assumed": funding_rate,
                    "monthly_long_decisions": active_months,
                    "minimum_active_months_required": MIN_ACTIVE_MONTHS_PER_WINDOW,
                    "valid_for_signal_screen": active_months >= MIN_ACTIVE_MONTHS_PER_WINDOW,
                    "model": model_metrics,
                    "exposure_matched_control": benchmark,
                    "momentum_3m_control": mom_metrics,
                    "buy_hold": hold_metrics,
                    "model_minus_matched_net_hac": paired,
                    "model_minus_momentum_net_hac": vs_momentum,
                }
            )

    artifact = {
        "round": 21,
        "family": "learned_gold_stress_interaction",
        "created_at": datetime.now(UTC).isoformat(),
        "training_protocol": "strict monthly prequential/rolling OLS-ridge",
        "fixed_config": {
            "lookback_months": cfg.lookback_months,
            "min_train_months": cfg.min_train_months,
            "ridge_strength": cfg.ridge_strength,
            "entry_threshold": cfg.entry_threshold,
            "feature_columns": list(FEATURES),
            "extra_exogenous_publication_lag": 1,
            "execution": "next_open",
        },
        "monthly_predictions": len(predictions),
        "usable_predictions": int(predictions["usable"].sum()),
        "first_usable_prediction": str(predictions.index[predictions["usable"]][0].date()),
        "last_prediction": str(predictions.index[-1].date()),
        "source": "Cboe VIX/VIX3M + pinned BaseMax XAUUSD M15 open/close",
        "gold_source_hash": bars.attrs.get("source"),
        "transactions_cost_model": COST.name,
        "transaction_cost_measured": False,
        "financing_measured": False,
        "historical_windows_all_spent": True,
        "validated_edge": False,
        "demo_only": True,
        "live_locked": True,
        "results": results,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / f"online_ridge_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    target.write_text(json.dumps(artifact, indent=2, allow_nan=False), encoding="utf-8")

    print(f"Artifact: {target}")
    print(f"Monthly model observations: {len(predictions)}; prequential predictions: {artifact['usable_predictions']}")
    for row in results:
        if row["financing_bps_calendar_day_assumed"] != 0.0:
            continue
        print(
            f"{row['window']:17s} "
            f"model Sharpe={row['model']['sharpe']:+.3f} "
            f"matched={row['exposure_matched_control']['sharpe']:+.3f} "
            f"fixed momentum={row['momentum_3m_control']['sharpe']:+.3f} "
            f"paired t={row['model_minus_matched_net_hac']['t_hac']} "
            f"exposure={row['model']['avg_held_exposure']:.1%}"
        )
    print("Verdict: DISCOVERY_ONLY — NO independent clean OOS, broker costs not measured, LIVE LOCKED.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
