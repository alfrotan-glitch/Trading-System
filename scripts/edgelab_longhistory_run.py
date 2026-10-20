"""Evaluate the 51-year gold catalogue under the existing acceptance gate.

Protocol, fixed before running:

* **DEV 1969-2000** — the only period used to rank. 32 years, detection floor
  Sharpe 0.44 at alpha_t 2.5.
* **VAL 2001-2010** — survivors only. A sign reversal here is fatal.
* **TEST 2011-2019** — survivors only, after VAL.
* **HOLDOUT 2020-2024** — never read by this script. It lives in a different
  file (the M15-derived store) and is only touched if a candidate clears DEV,
  VAL and TEST, exactly once.

Reuses the tested machinery: ``run_vector`` for execution and costs,
``alpha_decomposition`` for alpha vs gold beta, ``deflated_sharpe`` with the
corrected units convention, and ``gate.survivors`` for the thresholds. Nothing
here relaxes a criterion to make a result appear.

Costs are ASSUMED at the ECN rate of 4.0 bps/side and are stressed at 2x. They
are never reported as measured.
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
    run_vector,
)
from qts.research.edgelab.gate import MAX_COST_STRESS_FACTOR, MIN_ALPHA_T_DEV, MIN_DSR
from qts.research.edgelab.longgold import (
    BARS_PER_YEAR,
    load_long_gold,
    long_specs,
    long_split,
)
from qts.research.edgelab.power import detection_summary

warnings.filterwarnings("ignore", category=RuntimeWarning)

OUT = Path("data/research/experiments")


def evaluate(specs, bars, idx, period, cost, bpy):
    """Alpha-attributed metrics for every spec on one period."""
    sub = bars.loc[idx]
    if len(sub) < 250:
        return pd.DataFrame()
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
        except Exception as exc:
            print(f"  ! {spec.name}: {type(exc).__name__}: {exc}")
            continue
        if r.net_returns is None:
            continue
        stats = alpha_decomposition(r.net_returns, bench, bpy)
        if not stats:
            continue
        ret = r.net_returns
        rows.append(
            {
                "name": spec.name,
                "family": spec.family,
                "trades": r.trades,
                "exposure": r.exposure,
                "cagr": r.cagr,
                "sharpe": r.sharpe,
                "max_dd": r.max_dd,
                "alpha_ann": stats["alpha_ann"],
                "alpha_t": stats["alpha_t"],
                "beta": stats["beta"],
                "ir_vs_bh": stats["ir_vs_bh"],
                "skew": float(ret.skew()),
                "kurt": float(ret.kurt()) + 3.0,
                "n_obs": int(len(ret)),
            }
        )
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    trials = df.groupby("family")["name"].transform("count").to_numpy()
    df["dsr"] = [
        deflated_sharpe(sr, int(n), int(o), bars_per_year=bpy, skew=sk, kurt=ku)
        for sr, n, o, sk, ku in zip(df["sharpe"], trials, df["n_obs"], df["skew"], df["kurt"], strict=True)
    ]
    return df.sort_values("alpha_t", ascending=False)


def show(df: pd.DataFrame, title: str, n: int = 14) -> None:
    print(f"\n--- {title}")
    if df.empty:
        print("  (no rows)")
        return
    cols = ["name", "family", "trades", "exposure", "cagr", "sharpe", "max_dd", "alpha_ann", "alpha_t", "dsr", "beta"]
    with pd.option_context("display.width", 240, "display.max_columns", 30, "display.float_format", lambda v: f"{v:,.3f}"):
        print(df[cols].head(n).to_string(index=False))


def _confirm_holdout(specs, long_bars, cost, bpy, report) -> str:
    """Read the untouched 2020-2024 window on tradable closes, exactly once.

    The long store is a 10:30 London fixing; the holdout is built from M15 bars, so
    this is also a test of whether the effect survives a change of price
    construction. That comparison already showed fixing-based alpha is roughly
    double the tradable figure, which is precisely why the holdout must not be a
    fixing series.
    """
    from qts.research.edgelab import load_bars, resample

    try:
        base = load_bars("basemax")
    except FileNotFoundError as exc:
        print(f"! holdout unavailable: {exc}")
        report["holdout"] = {"status": "unavailable", "detail": str(exc)}
        return "PENDING_HOLDOUT"
    base = base[base.index <= pd.Timestamp("2024-12-31", tz="UTC")]
    d1 = resample(base, "D1")
    idx = d1.index[d1.index >= pd.Timestamp("2020-01-01", tz="UTC")]
    df = evaluate(specs, d1, idx, "HOLDOUT_2020_2024", cost, bpy)
    show(df, "HOLDOUT 2020-2024 (tradable closes, read once)", len(specs))
    report["holdout"] = {
        "window": "2020-01-01..2024-12-31",
        "source": "BaseMax M15 -> D1 (tradable closes)",
        "rows": df.to_dict(orient="records"),
    }
    if df.empty:
        return "NO_VALIDATED_EDGE"
    passed = df[(df["alpha_ann"] > 0) & (df["alpha_t"] > 0)]["name"].tolist()
    report["holdout"]["confirmed"] = passed
    if passed:
        return "VALIDATED_EDGE"
    return "FAILED_HOLDOUT"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=14)
    ap.add_argument("--out", default="")
    ap.add_argument("--confirm-holdout", action="store_true",
                    help="evaluate surviving candidates once on tradable 2020-2024")
    args = ap.parse_args()

    bars = load_long_gold()
    specs = long_specs()
    bpy = BARS_PER_YEAR
    ecn = CostModel()
    stress = CostModel.stressed(MAX_COST_STRESS_FACTOR)
    spans = long_split(bars.index)

    print(f"bars={len(bars)} span={bars.index.min().date()}..{bars.index.max().date()} specs={len(specs)}")
    report: dict = {
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset": "LBMA AM fix, 1969-2019, macro lagged 2 months",
        "cost": f"ASSUMED {ecn.name} ~{ecn.per_side_bps():.2f} bps/side",
        "gate": {"min_alpha_t_dev": MIN_ALPHA_T_DEV, "min_dsr": MIN_DSR},
        "periods": {},
        "verdict": "NO_VALIDATED_EDGE",
    }

    dev = evaluate(specs, bars, spans["DEV"], "DEV", ecn, bpy)
    dev_stress = evaluate(specs, bars, spans["DEV"], "DEV_stress", stress, bpy)
    if dev.empty:
        print("no results")
        return
    merged = dev.merge(dev_stress[["name", "alpha_ann", "alpha_t"]], on="name", suffixes=("", "_stress"))
    merged = merged.sort_values("alpha_t", ascending=False)
    show(merged, f"DEV 1969-2000, cost={ecn.name}", args.top)

    bh = benchmark_returns(bars.loc[spans["DEV"]])
    sd = float(bh.std()) * np.sqrt(bpy)
    report["periods"]["DEV"] = {
        "bars": int(len(spans["DEV"])),
        "power": detection_summary(len(spans["DEV"]), bpy, MIN_ALPHA_T_DEV),
        "buy_hold_sharpe": sd,
        "buy_hold_cagr": float(np.prod(1 + bh.dropna()) ** (bpy / len(bh)) - 1),
    }
    print(f"\nbuy-and-hold DEV: CAGR {report['periods']['DEV']['buy_hold_cagr']:.2%}, Sharpe {sd:.3f}")
    print(f"detection floor: SR {report['periods']['DEV']['power']['min_detectable_sr']:.3f}")

    survivors = merged[
        (merged["alpha_t"] >= MIN_ALPHA_T_DEV)
        & (merged["dsr"] >= MIN_DSR)
        & (merged["alpha_ann_stress"] > 0)
    ]
    report["periods"]["DEV"]["survivors"] = survivors["name"].tolist()
    print(f"\nDEV survivors (alpha_t>={MIN_ALPHA_T_DEV}, DSR>={MIN_DSR}, 2x cost): {survivors['name'].tolist()}")

    if not survivors.empty:
        names = set(survivors["name"])
        sub_specs = [s for s in specs if s.name in names]
        for period in ("VAL", "TEST"):
            df = evaluate(sub_specs, bars, spans[period], period, ecn, bpy)
            show(df, f"{period} {spans[period][0].date()}..{spans[period][-1].date()}", len(sub_specs))
            confirmed = df[(df["alpha_ann"] > 0) & (df["alpha_t"] > 0)]["name"].tolist()
            report["periods"][period] = {
                "rows": df.to_dict(orient="records"),
                "confirmed": confirmed,
            }
            names = names & set(confirmed)
        if names:
            report["candidates"] = sorted(names)
            print(f"\ncandidates cleared DEV+VAL+TEST: {sorted(names)}")
            if not args.confirm_holdout:
                report["verdict"] = "PENDING_HOLDOUT"
                print("HOLDOUT 2020-2024 remains unread; run with --confirm-holdout to evaluate once.")
            else:
                report["verdict"] = _confirm_holdout([s for s in specs if s.name in names], bars, ecn, bpy, report)
    else:
        print("\nNo candidate cleared DEV. VAL/TEST/holdout not read.")

    # Decade stability for the DEV leader(s): a single great decade is not an edge.
    focus = merged.head(3)["name"].tolist()
    focus_specs = [s for s in specs if s.name in focus]
    decades = []
    for start in range(1969, 2020, 10):
        lo, hi = pd.Timestamp(f"{start}-01-01"), pd.Timestamp(f"{min(start + 9, 2019)}-12-31")
        didx = bars.index[(bars.index >= lo) & (bars.index <= hi)]
        if len(didx) < 250:
            continue
        d = evaluate(focus_specs, bars, didx, str(start), ecn, bpy)
        if d.empty:
            continue
        d = d.assign(decade=f"{start}s")
        decades.append(d)
    if decades:
        dec = pd.concat(decades, ignore_index=True)
        print("\n--- decade stability (alpha/yr, alpha_t) for DEV leaders")
        piv = dec.pivot_table(index="name", columns="decade", values="alpha_ann", aggfunc="first")
        with pd.option_context("display.width", 200, "display.float_format", lambda v: f"{v:+.3f}"):
            print(piv.to_string())
        report["decade_alpha"] = {c: {r: float(v) for r, v in piv[c].dropna().items()} for c in piv.columns}

    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = Path(args.out) if args.out else OUT / f"longgold_{stamp}.json"
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nVERDICT: {report['verdict']}\nwritten -> {path}")


if __name__ == "__main__":
    main()
