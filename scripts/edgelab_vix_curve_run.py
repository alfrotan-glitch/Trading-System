"""Independent research round: Cboe VIX curve shape -> executable gold exposure.

Two PREDECLARED directional hypotheses (contango/backwardation), one fixed
20-observation smoother, one 21-observation rebalance. Cboe close is lagged a
full publication before gold execution. The research seeks low turnover and a
new information set, not another transformation of gold returns.

All historical price windows have been inspected in preceding rounds; even a
positive result here is DISCOVERY ONLY, never untouched OOS confirmation.
No automatic strategy registration or live trade is permitted.

Run:
    python scripts/fetch_cboe_vix_curve.py
    python scripts/edgelab_vix_curve_run.py
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from qts.research.edgelab import CostModel, alpha_decomposition, benchmark_returns, hac_alpha, run_vector
from qts.research.edgelab.stress import tradable_gold
from qts.research.edgelab.vix_curve import align_to_gold, curve_frame, fixed_cadence_signal, read_cboe_history

RAW = Path("data/raw/edgelab/cboe_vix_curve")
OUT = Path("data/research/experiments")
BPY = 252.0
COST = CostModel.realistic_ecn()
DIRECTIONS = ("contango", "backwardation")
BOUNDS = {
    "DEV_SPENT": ("2008-01-01", "2015-12-31"),
    "VAL_SPENT": ("2016-01-01", "2021-12-31"),
    "DIAGNOSTIC_SPENT": ("2022-01-01", "2026-09-30"),
}


def load_curve() -> pd.DataFrame:
    series: dict[str, pd.Series] = {}
    for name in ("VIX", "VIX3M"):
        path = RAW / f"{name}_History.csv"
        if not path.exists():
            raise FileNotFoundError(f"{path} missing; run python scripts/fetch_cboe_vix_curve.py")
        series[name] = read_cboe_history(path.read_text(encoding="utf-8-sig"), name=name)
    return curve_frame(series["VIX"], series["VIX3M"])


def evaluate(bars: pd.DataFrame, position: pd.Series, label: str) -> dict:
    """Compare against exposure-matched static gold to isolate timing from beta."""
    if len(bars) < 250:
        return {"label": label, "status": "INSUFFICIENT", "observations": len(bars)}
    result = run_vector(
        bars,
        position,
        COST,
        name=label,
        family="vix_curve",
        bars_per_year=BPY,
        keep_equity=True,
        execution="close",
    )
    if result.net_returns is None:
        raise RuntimeError("run_vector must return net returns")
    bench = benchmark_returns(bars)
    decomposed = alpha_decomposition(result.net_returns, bench, BPY)
    try:
        hac = hac_alpha(result.net_returns, bench, BPY, lags=10)
        t = float(hac["alpha_t"])
    except ValueError:
        t = float("nan")
    return {
        "label": label,
        "status": "EVALUATED_SPENT_DATA",
        "observations": len(result.net_returns),
        "average_exposure": float(position.mean()),
        "cagr": result.cagr,
        "sharpe": result.sharpe,
        "max_drawdown": result.max_dd,
        "sides_per_year": result.turnover_per_year,
        "alpha_ann": decomposed.get("alpha_ann"),
        "alpha_t_hac": t if math.isfinite(t) else None,
    }


def main() -> int:
    curve = load_curve()
    gold = tradable_gold().sort_index()
    if not isinstance(gold.index, pd.DatetimeIndex) or gold.index.tz is None:
        raise ValueError("tradable gold series needs a timezone-aware daily UTC index")
    if len(gold) < 500:
        raise ValueError("insufficient tradable gold history")
    bars = pd.DataFrame({"close": gold}, index=gold.index)
    results = []
    for direction in DIRECTIONS:
        # This position is determined by information at least one full Cboe
        # observation old; run_vector adds its executable gold holding lag.
        pos = align_to_gold(fixed_cadence_signal(curve, direction=direction), gold.index)
        for name, (start, end) in BOUNDS.items():
            sub = bars.loc[start:end]
            if sub.empty:
                continue
            actual = pos.reindex(sub.index).fillna(0.0)
            candidate = evaluate(sub, actual, f"{name}_{direction}")
            # Diagnostic control, matched to the candidate's EX-POST average
            # exposure. It is not a deployable allocation.
            matched = pd.Series(float(actual.mean()), index=sub.index)
            reference = evaluate(sub, matched, f"{name}_matched_hold")
            results.append(
                {
                    "window": name,
                    "direction": direction,
                    "candidate": candidate,
                    "matched_control": reference,
                    "sharpe_difference": (
                        candidate["sharpe"] - reference["sharpe"]
                        if candidate["status"] == "EVALUATED_SPENT_DATA"
                        and reference["status"] == "EVALUATED_SPENT_DATA"
                        else None
                    ),
                }
            )
    payload = {
        "research_family": "equity_volatility_term_structure",
        "mechanism": "US equity option-implied volatility curve shape predicts gold risk premium",
        "source": "Cboe VIX and VIX3M public daily history",
        "source_available_through": str(curve.index.max()),
        "gold_available_through": str(gold.index.max()),
        "created_at": datetime.now(UTC).isoformat(),
        "windows_are_spent": True,
        "fresh_oos_confirmed": False,
        "validated_edge": False,
        "live_locked": True,
        "parameters_frozen": {"smooth_days": 20, "rebalance_days": 21, "publication_delay": 1, "directions": list(DIRECTIONS)},
        "trials": len(DIRECTIONS),
        "cost_model": COST.name,
        "cost_bps_per_side_at_reference": COST.per_side_bps(),
        "cost_is_measured": False,
        "overnight_financing_is_measured": False,
        "overnight_financing_included": False,
        "financing_warning": (
            "Spot/CFD gold financing and broker swaps are NOT in this cost model. "
            "Positive backtests cannot be promoted without verified holding costs."
        ),
        "results": results,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"vix_curve_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"artifact": str(path), "trials": len(DIRECTIONS), "results": results}, indent=2, allow_nan=False))
    print("Verdict: DISCOVERY_ONLY. All historical windows spent; no validated edge.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
