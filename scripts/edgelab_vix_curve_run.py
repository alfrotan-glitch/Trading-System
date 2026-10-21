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

import argparse
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
FINANCING_STRESS_BPS_PER_CALENDAR_DAY = (0.0, 0.5, 1.0, 2.0)
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


def evaluate(
    bars: pd.DataFrame,
    position: pd.Series,
    label: str,
    *,
    financing_bps_per_calendar_day: float = 0.0,
) -> dict:
    """Compare against exposure-matched static gold and charge funding stress.

    Financing is assessed on the position held during each elapsed calendar-day
    interval; weekends therefore carry more than one day's funding. These are
    *assumed* scenario rates, not measured broker swaps.
    """
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
    if result.net_returns is None or result.held is None:
        raise RuntimeError("run_vector must return held positions and net returns")
    if financing_bps_per_calendar_day < 0 or not math.isfinite(financing_bps_per_calendar_day):
        raise ValueError("funding stress must be finite and nonnegative")
    elapsed = (
        bars.index.to_series()
        .diff()
        .dt.total_seconds()
        .div(86400.0)
        .reindex(result.net_returns.index)
        .fillna(0.0)
    )
    if bool((elapsed <= 0).any()):
        raise ValueError("daily index must be strictly increasing")
    funding = (
        result.held.abs()
        * elapsed
        * (financing_bps_per_calendar_day / 1e4)
    )
    net = result.net_returns - funding
    if bool((1.0 + net <= 0).any()):
        raise ValueError("insolvent return series")
    equity = (1.0 + net).cumprod()
    years = len(net) / BPY
    std = float(net.std(ddof=1))
    sharpe = float(net.mean() / std * math.sqrt(BPY)) if std > 0 else 0.0
    peak = equity.cummax()
    max_dd = float((1.0 - equity / peak).max())
    cagr = float(equity.iloc[-1] ** (1.0 / years) - 1.0)
    bench = benchmark_returns(bars)
    decomposed = alpha_decomposition(net, bench, BPY)
    try:
        hac = hac_alpha(net, bench, BPY, lags=10)
        t = float(hac["alpha_t"])
    except ValueError:
        t = float("nan")
    return {
        "label": label,
        "status": "EVALUATED_SPENT_DATA",
        "observations": len(net),
        "average_exposure": float(position.mean()),
        "financing_bps_per_calendar_day_assumed": financing_bps_per_calendar_day,
        "financing_drag_total": float(funding.sum()),
        "cagr": cagr,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "sides_per_year": result.turnover_per_year,
        "alpha_ann": decomposed.get("alpha_ann"),
        "alpha_t_hac": t if math.isfinite(t) else None,
    }


def load_gold_from_basemax(*, min_bars_per_day: int = 80) -> pd.Series:
    """Reconstruct an executable UTC-day close from verified M15 observations.

    A day with too few bars is not a legitimate daily close. BaseMax carries a
    nearly empty tail after early 2025; rejecting such days prevents a single
    late stale print from becoming a bogus multi-month return.
    """
    from edgelab_prepare_data import load_basemax
    from qts.research.edgelab.intraday import daily_bars

    m15, quality, source = load_basemax()
    if quality.rows_out < 50_000 or quality.bad_ohlc > 0 or quality.non_positive > 0:
        raise ValueError(f"BaseMax quality gate failed: {quality}")
    counts = m15["close"].resample("1D").count()
    complete_days = counts[counts >= min_bars_per_day].index
    prices = daily_bars(m15)["close"].reindex(complete_days).dropna()
    if len(prices) < 500:
        raise ValueError(f"Only {len(prices)} complete daily closes: need >=500")
    if prices.index.tz is None:
        raise ValueError("BaseMax UTC index absent after loader")
    prices.attrs["source"] = f"BaseMax XAUUSD M15, verified SHA256 {source['sha256']}"
    prices.attrs["min_bars_per_day"] = min_bars_per_day
    return prices.rename("gold")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--gold-source",
        choices=("basemax", "tradable_gold"),
        default="basemax",
        help="basemax uses pinned executable M15 daily close; tradable_gold uses futures splice",
    )
    args = parser.parse_args(argv)
    curve = load_curve()
    gold = (load_gold_from_basemax() if args.gold_source == "basemax" else tradable_gold()).sort_index()
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
            # Diagnostic control, matched to candidate's EX-POST average
            # exposure. It is not a deployable allocation.
            matched = pd.Series(float(actual.mean()), index=sub.index)
            for funding_rate in FINANCING_STRESS_BPS_PER_CALENDAR_DAY:
                candidate = evaluate(
                    sub,
                    actual,
                    f"{name}_{direction}",
                    financing_bps_per_calendar_day=funding_rate,
                )
                reference = evaluate(
                    sub,
                    matched,
                    f"{name}_matched_hold",
                    financing_bps_per_calendar_day=funding_rate,
                )
                results.append(
                    {
                        "window": name,
                        "direction": direction,
                        "financing_bps_per_calendar_day_assumed": funding_rate,
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
        "gold_source": args.gold_source,
        "gold_source_details": gold.attrs.get("source", gold.attrs.get("sources", "unknown")),
        "gold_min_bars_per_day": gold.attrs.get("min_bars_per_day"),
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
        "financing_stress_bps_per_calendar_day": list(FINANCING_STRESS_BPS_PER_CALENDAR_DAY),
        "overnight_financing_is_measured": False,
        "overnight_financing_stress_included": True,
        "financing_warning": (
            "Explicit hypothetical financing scenarios are charged, but actual "
            "broker swap and rollover terms are NOT measured. Positive historical "
            "results cannot be promoted without verified broker holding costs."
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
