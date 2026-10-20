"""Edge Lab — hypothesis screening on the DEV period only.

Protocol (fixed before looking at results):

* DEV (2004-2018) is the ONLY period used to compare strategies. Everything is
  ranked here.
* VAL (2019-2021) is touched only for the handful of DEV survivors, to check that
  the behaviour is not specific to one decade.
* TEST (2022-2024) and OOS (2025-2026, independent Dukascopy source) are read only
  when a candidate is frozen, and then exactly once.

Running this script prints nothing about TEST/OOS by design.
"""

from __future__ import annotations

import argparse
import warnings
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from qts.research.edgelab import (
    CostModel,
    StrategySpec,
    alpha_decomposition,
    benchmark_returns,
    load_bars,
    resample,
    run_vector,
    side_attribution,
    split,
    yearly_table,
)
from qts.research.edgelab.macro import attach_macro
from qts.research.edgelab.specs import BARS_PER_YEAR, build_specs

warnings.filterwarnings("ignore", category=RuntimeWarning)

OUT = Path("data/research/experiments")


def evaluate(specs: list[StrategySpec], bars: pd.DataFrame, period_idx: pd.DatetimeIndex, period: str,
             cost: CostModel, bpy: float, execution: str = "close"):
    """Run every spec on one period and attribute each result against long gold.

    Ranking on raw Sharpe is how a beta proxy gets mistaken for an edge: gold itself
    scored 0.49 on DEV. Every row therefore carries the alpha regression, and the
    screen is sorted by ``alpha_t`` — evidence of timing skill, not of being long.
    """
    results = []
    alphas: dict[str, dict] = {}
    sub = bars.loc[period_idx]
    if len(sub) < 500:
        return results, alphas
    # The benchmark must use the same fill convention as the strategies.
    bench = benchmark_returns(sub) if execution == "close" else sub["open"].pct_change()

    # Benchmark row: same execution convention, zero cost, always long.
    bench_pos = pd.Series(1.0, index=sub.index)
    bh = run_vector(sub, bench_pos, CostModel.zero(), name="buy_hold", family="benchmark",
                    period=period, bars_per_year=bpy, keep_equity=True, execution=execution)
    results.append(bh)
    alphas["buy_hold"] = {"beta": 1.0, "alpha_ann": 0.0, "alpha_t": 0.0, "ir_vs_bh": 0.0,
                          "long_pnl": bh.net_return, "short_pnl": 0.0}

    for spec in specs:
        try:
            pos = spec.positions(sub)
            if float(np.abs(pos.to_numpy()).sum()) == 0:
                continue
            r = run_vector(
                sub,
                pos,
                cost,
                name=spec.name,
                family=spec.family,
                params=spec.params,
                period=period,
                bars_per_year=bpy,
                keep_equity=True,
                execution=execution,
            )
            if r.net_returns is None or r.held is None:
                continue
            stats = alpha_decomposition(r.net_returns, bench, bpy)
            if not stats:
                continue
            stats.update(side_attribution(r.net_returns.to_numpy(), r.held.to_numpy()))
            alphas[spec.name] = stats
            results.append(r)
        except Exception as exc:  # a broken hypothesis is a finding, not a crash
            print(f"  ! {spec.name}: {type(exc).__name__}: {exc}")
    return results, alphas


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cost", default="ecn", choices=["ecn", "standard", "zero", "stress2", "stress3"])
    ap.add_argument("--timeframe", default="D1")
    ap.add_argument("--period", default="DEV", choices=["DEV", "VAL"])
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--only", default="", help="comma-separated strategy names (VAL protocol: survivors only)")
    ap.add_argument("--execution", default="close", choices=["close", "next_open"])
    args = ap.parse_args()

    cost = {
        "ecn": CostModel(),
        "standard": CostModel.standard_account(),
        "zero": CostModel.zero(),
        "stress2": CostModel.stressed(2.0),
        "stress3": CostModel.stressed(3.0),
    }[args.cost]

    base = load_bars("basemax")
    base = base[base.index <= pd.Timestamp("2024-12-31", tz="UTC")]
    bars = base if args.timeframe == "M15" else resample(base, args.timeframe)
    bpy = BARS_PER_YEAR.get(args.timeframe, 252.0)

    # Macro conditioning is optional: without it the macro family raises and is
    # reported as a skipped hypothesis rather than silently dropping out.
    try:
        bars = attach_macro(bars)
    except FileNotFoundError as exc:
        print(f"  ! macro data unavailable: {exc}")

    spans = split(bars.index)
    period_idx = spans[args.period]
    print(f"timeframe={args.timeframe} cost={cost.name} period={args.period} bars={len(period_idx)} "
          f"span={period_idx[0].date()}..{period_idx[-1].date()}")

    specs = build_specs()
    if args.only:
        keep = {n.strip() for n in args.only.split(",") if n.strip()}
        specs = [sp for sp in specs if sp.name in keep]
        if not specs:
            raise SystemExit(f"no specs matched --only {args.only!r}")
    results, alphas = evaluate(specs, bars, period_idx, args.period, cost, bpy, args.execution)

    df = pd.DataFrame([r.row() for r in results])
    adf = pd.DataFrame(alphas).T.add_prefix("ab_")
    df = df.merge(adf, left_on="name", right_index=True, how="left")
    df = df.sort_values("ab_alpha_t", ascending=False)
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    tag = f"screen_{args.timeframe}_{args.cost}_{args.period}_{args.execution}_{stamp}"
    df.to_csv(OUT / f"{tag}.csv", index=False)

    cols = ["name", "family", "trades", "cagr", "sharpe", "max_dd", "profit_factor",
            "ab_beta", "ab_alpha_ann", "ab_alpha_t", "ab_ir_vs_bh", "ab_long_pnl", "ab_short_pnl"]
    with pd.option_context("display.width", 200, "display.max_columns", 30, "display.float_format", lambda v: f"{v:,.3f}"):
        print(df[cols].head(args.top).to_string(index=False))

    print(f"\n{len(df)} strategies evaluated, {len(specs)} specs defined -> {OUT / (tag + '.csv')}")

    # Best per family, so a family is judged by its best member rather than noise.
    best = df.sort_values("ab_alpha_t", ascending=False).groupby("family", as_index=False).first()
    with pd.option_context("display.width", 200, "display.float_format", lambda v: f"{v:,.3f}"):
        print("\nBest per family (by alpha t-stat):")
        print(best[cols].sort_values("ab_alpha_t", ascending=False).to_string(index=False))

    # The honest question: does anything beat simply holding gold, after costs?
    bh = df[df.name == "buy_hold"].iloc[0]
    print(f"\nbuy_hold: CAGR {bh.cagr:.2%}, Sharpe {bh.sharpe:.3f}, maxDD {bh.max_dd:.1%}")
    beat = df[(df.name != "buy_hold") & (df.ab_alpha_t > 2.0)]
    print(f"strategies with alpha_t > 2.0: {len(beat)} of {len(df) - 1}")

    # Yearly stability for the top 3 by alpha — a single great decade is not an edge.
    top = [r for r in results if r.name in set(df.head(3)["name"])]
    for r in top:
        if r.equity is None:
            continue
        yr = yearly_table(r.equity.pct_change().dropna())
        print(f"\n{r.name}: yearly net return / sharpe")
        print(yr.to_string(index=False))


if __name__ == "__main__":
    main()
