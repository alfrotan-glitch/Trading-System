"""Edge Lab — pre-registered acceptance gate for an XAUUSD edge.

This is the only script allowed to declare that a strategy is an edge. The
criteria below were fixed *before* any result was read, and every one of them
must pass:

1. **Alpha, not Sharpe.** The candidate's return must not be explained by gold
   itself. Gold scored Sharpe 0.49 on DEV; ranking on raw Sharpe is how beta gets
   mistaken for skill.
2. **alpha_t >= 2.5 on DEV.** With ~45 configurations tried, a t-stat of 2.0 is
   expected by chance. 2.5 is a deliberately conservative screen on top of the
   deflated Sharpe, not a substitute for it.
3. **Deflated Sharpe >= 0.95**, using the true number of trials in that family.
4. **Same sign on VAL.** DEV alpha must not flip to a loss in 2019-2021; a sign
   reversal is the signature of a fitted artefact.
5. **Survives 2x cost stress.** If doubling assumed costs destroys it, the edge is
   a cost-model artefact, not a market effect.

Failing any criterion means ``NO_VALIDATED_EDGE``. That is the expected outcome
for most searches, and reporting it honestly is the point of the harness.

The report writes TEST/OOS *only* for candidates that clear every DEV+VAL gate,
and then exactly once. Nothing here peeks at the holdout.
"""

from __future__ import annotations

import argparse
import json
import warnings
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from qts.research.edgelab import (
    CostModel,
    alpha_decomposition,
    benchmark_returns,
    deflated_sharpe,
    load_bars,
    resample,
    run_vector,
    split,
)
from qts.research.edgelab.gate import MAX_COST_STRESS_FACTOR, MIN_ALPHA_T_DEV, MIN_DSR, survivors, val_confirms
from qts.research.edgelab.macro import attach_macro
from qts.research.edgelab.power import detection_summary
from qts.research.edgelab.specs import BARS_PER_YEAR, build_specs

warnings.filterwarnings("ignore", category=RuntimeWarning)

OUT = Path("data/research/experiments")

# Thresholds live in the package (qts.research.edgelab.gate) so they are imported,
# never re-declared, and covered by the test suite.
GATE = {
    "min_alpha_t_dev": MIN_ALPHA_T_DEV,
    "min_dsr": MIN_DSR,
    "require_positive_val_alpha": True,
    "max_cost_stress_factor": MAX_COST_STRESS_FACTOR,
}


def evaluate_period(
    specs,
    bars: pd.DataFrame,
    period_idx: pd.DatetimeIndex,
    period: str,
    cost: CostModel,
    bpy: float,
) -> pd.DataFrame:
    """Alpha-attributed results for every spec on one period."""
    sub = bars.loc[period_idx]
    bench = benchmark_returns(sub)
    rows = []
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
            )
        except Exception as exc:  # a broken hypothesis is a finding, not a crash
            print(f"  ! {spec.name}: {type(exc).__name__}: {exc}")
            continue
        if r.net_returns is None:
            continue
        stats = alpha_decomposition(r.net_returns, bench, bpy)
        if not stats:
            continue
        ret = r.net_returns.to_numpy()
        rows.append(
            {
                "name": spec.name,
                "family": spec.family,
                "trades": r.trades,
                "cagr": r.cagr,
                "sharpe": r.sharpe,
                "max_dd": r.max_dd,
                "alpha_ann": stats["alpha_ann"],
                "alpha_t": stats["alpha_t"],
                "beta": stats["beta"],
                "skew": float(pd.Series(ret).skew()),
                "kurt": float(pd.Series(ret).kurt()) + 3.0,
                "n_obs": len(ret),
            }
        )
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    # Multiple testing: each family is its own search, so count trials per family.
    trials = df.groupby("family")["name"].transform("count").to_numpy()
    df["dsr"] = [
        deflated_sharpe(sr, int(n), int(obs), bars_per_year=bpy, skew=sk, kurt=ku)
        for sr, n, obs, sk, ku in zip(df["sharpe"], trials, df["n_obs"], df["skew"], df["kurt"], strict=True)
    ]
    return df.sort_values("alpha_t", ascending=False)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeframes", default="D1,H1")
    ap.add_argument("--write-test", action="store_true", help="read TEST for candidates that pass every DEV+VAL gate")
    args = ap.parse_args()

    base = load_bars("basemax")
    base = base[base.index <= pd.Timestamp("2024-12-31", tz="UTC")]
    macro_available = True
    specs = build_specs()
    ecn = CostModel()
    stress = CostModel.stressed(GATE["max_cost_stress_factor"])

    report: dict = {
        "generated_at": datetime.now(UTC).isoformat(),
        "gate": GATE,
        "timeframes": {},
        "candidates_passing": [],
        "verdict": "NO_VALIDATED_EDGE",
    }

    for tf in [t.strip() for t in args.timeframes.split(",") if t.strip()]:
        bars = base if tf == "M15" else resample(base, tf)
        # Attach macro *after* resampling: resample() rebuilds OHLCV and would drop
        # any extra column, which silently turned every macro hypothesis into a skip.
        if macro_available:
            try:
                bars = attach_macro(bars)
            except FileNotFoundError as exc:
                macro_available = False
                print(f"! macro data unavailable, macro family will be skipped: {exc}")
        bpy = BARS_PER_YEAR.get(tf, 252.0)
        spans = split(bars.index)

        dev = evaluate_period(specs, bars, spans["DEV"], "DEV", ecn, bpy)
        dev_stress = evaluate_period(specs, bars, spans["DEV"], "DEV_stress", stress, bpy)
        if dev.empty:
            continue
        merged = dev.merge(dev_stress[["name", "alpha_ann", "alpha_t"]], on="name", suffixes=("", "_stress"))

        dev_survivors = survivors(merged)
        tf_block = {
            "bars": int(len(bars)),
            "power": detection_summary(len(spans["DEV"]), bpy, MIN_ALPHA_T_DEV),
            "strategies": int(len(merged)),
            "dev_best_by_alpha": merged.head(5)[
                ["name", "sharpe", "alpha_ann", "alpha_t", "dsr", "beta", "cagr", "max_dd"]
            ].to_dict(orient="records"),
            "dev_survivors": dev_survivors["name"].tolist(),
            "val": {},
        }

        if not dev_survivors.empty:
            name_filter = set(dev_survivors["name"])
            val_specs = [s for s in specs if s.name in name_filter]
            val = evaluate_period(val_specs, bars, spans["VAL"], "VAL", ecn, bpy)
            tf_block["val"] = val.to_dict(orient="records")
            passed = val_confirms(val)
            for _, row in passed.iterrows():
                report["candidates_passing"].append(
                    {
                        "name": row["name"],
                        "timeframe": tf,
                        "val_alpha_ann": float(row["alpha_ann"]),
                        "val_alpha_t": float(row["alpha_t"]),
                    }
                )

        report["timeframes"][tf] = tf_block
        print(
            f"{tf}: {len(merged)} strategies, best DEV alpha_t={merged.alpha_t.max():.2f} "
            f"({merged.iloc[0]['name']}), DEV survivors={len(dev_survivors)}"
        )
        if not dev_survivors.empty:
            print(f"  survivors: {sorted(name_filter)}")

    # A candidate must clear DEV *and* VAL before the holdout is ever read.
    if report["candidates_passing"] and args.write_test:
        print("\nCandidates cleared DEV+VAL — reading TEST once.")
        tf = report["candidates_passing"][0]["timeframe"]
        bars = base if tf == "M15" else resample(base, tf)
        names = {c["name"] for c in report["candidates_passing"]}
        test = evaluate_period([s for s in specs if s.name in names], bars, split(bars.index)["TEST"], "TEST", ecn, BARS_PER_YEAR[tf])
        report["test"] = test.to_dict(orient="records")
        if not test.empty and bool((test.alpha_ann > 0).all()):
            report["verdict"] = "VALIDATED_EDGE"
        elif not test.empty:
            report["verdict"] = "FAILED_TEST"
    elif report["candidates_passing"]:
        report["verdict"] = "PENDING_TEST"
    else:
        report["verdict"] = "NO_VALIDATED_EDGE"

    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = OUT / f"verdict_{stamp}.json"
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    print(f"\nVERDICT: {report['verdict']}")
    print(f"written -> {path}")


if __name__ == "__main__":
    main()
