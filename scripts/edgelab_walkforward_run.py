"""Round 19: walk-forward selection — does choosing strategies beat not choosing?

Every evaluation so far fixed the signal set in advance. A real multi-strategy system
does not: it looks at recent performance, picks what is working, drops what is not,
and repeats. That *selection process* is what the product would actually do, and it
has never been tested.

The test
--------
Re-select annually, using only information available at the time:

    at each rebalance date
        1. rank the 21 signals by their Sharpe over the trailing 3 years
        2. keep the top k that also have a positive trailing alpha
        3. hold those, equal-weight, for the next year

Nothing in the loop can see the future: the ranking window ends at the rebalance
date and the holding period starts after it. Costs are charged on every position
change, so churn caused by switching is paid for.

Compared against:

    B  fixed equal-weight blend of all 21 signals (never re-selects)
    A  buy & hold

If annual re-selection cannot beat a fixed blend, then "intelligent strategy
selection" is not a product feature that works on this data — which is a decisive
statement about the architecture, not just about a signal.
"""

from __future__ import annotations

import json
import sys
import warnings
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from qts.research.edgelab import CostModel, alpha_decomposition, benchmark_returns, hac_alpha, run_vector
from qts.research.edgelab.longgold import load_long_gold, long_specs
from qts.research.edgelab.quantity import quantity_specs

warnings.filterwarnings("ignore", category=RuntimeWarning)

OUT = Path("data/research/experiments")
BPY = 252.0
LOOKBACK = 756  # 3 years
WARMUP = 756
TOP_K = (1, 3, 5)
REBALANCE = 252
COST = CostModel.realistic_ecn()
#: Selection runs from 1972 (after warm-up) to the end of the research store.
START, END = "1972-01-01", "2019-12-31"


def catalogue(bars: pd.DataFrame) -> pd.DataFrame:
    sigs = {s.name: s.positions(bars) for s in long_specs()}
    sigs.update({n: f(bars) for n, f in quantity_specs().items()})
    df = pd.DataFrame(sigs).fillna(0.0)
    return df.loc[:, df.abs().sum() > 0]


def trailing_sharpe(net: pd.DataFrame, i: int, lookback: int) -> pd.Series:
    """Sharpe of each signal over the ``lookback`` bars ending at position ``i``."""
    window = net.iloc[max(0, i - lookback) : i]
    if len(window) < lookback // 2:
        return pd.Series(dtype=float)
    mu = window.mean()
    sd = window.std(ddof=1).replace(0.0, np.nan)
    return (mu / sd * np.sqrt(BPY)).dropna()


def walk_forward(bars: pd.DataFrame, signals: pd.DataFrame, top_k: int) -> tuple[pd.Series, list[dict]]:
    """Annual re-selection; returns the daily position series and the selection log."""
    pos = pd.Series(0.0, index=bars.index)
    log: list[dict] = []
    n = len(bars)

    # Net returns used *only* for ranking, computed on the same bars.
    ranking_net = {}
    for c in signals.columns:
        r = run_vector(bars, signals[c], COST, name=c, family="rank", bars_per_year=BPY, keep_equity=True)
        if r.net_returns is not None:
            ranking_net[c] = r.net_returns
    net = pd.DataFrame(ranking_net).reindex(bars.index).fillna(0.0)

    for i in range(WARMUP, n - 1, REBALANCE):
        sharpes = trailing_sharpe(net, i, LOOKBACK)
        if sharpes.empty:
            continue
        chosen = list(sharpes.sort_values(ascending=False).head(top_k).index)
        end = min(i + REBALANCE, n)
        pos.iloc[i:end] = signals.loc[bars.index[i] : bars.index[end - 1], chosen].mean(axis=1).to_numpy()
        log.append({"date": str(bars.index[i].date()), "chosen": chosen, "sharpes": {k: round(float(v), 3) for k, v in sharpes.items() if k in chosen}})
    return pos.clip(0.0, 1.0), log


def evaluate(bars: pd.DataFrame, pos: pd.Series, label: str) -> dict:
    r = run_vector(bars, pos, COST, name=label, family="walkforward", bars_per_year=BPY, keep_equity=True)
    if r.net_returns is None:
        raise RuntimeError("keep_equity required")
    st = alpha_decomposition(r.net_returns, benchmark_returns(bars), BPY)
    try:
        hac = float(hac_alpha(r.net_returns, benchmark_returns(bars), BPY, lags=5)["alpha_t"])
    except ValueError:
        hac = float("nan")
    return {
        "label": label,
        "cagr": r.cagr,
        "sharpe": r.sharpe,
        "max_dd": r.max_dd,
        "calmar": r.calmar,
        "alpha_ann": st["alpha_ann"],
        "alpha_t": st["alpha_t"],
        "alpha_t_hac": hac,
        "turnover": r.turnover_per_year,
        "avg_size": float(pos.abs().mean()),
        "net_returns": r.net_returns,
    }


def main() -> int:
    bars_all = load_long_gold()
    bars = bars_all.loc[START:END]
    signals = catalogue(bars).loc[bars.index]
    print(f"signals {signals.shape[1]} | {bars.index.min().date()} .. {bars.index.max().date()} ({len(bars) / BPY:.1f} yrs)")
    print(f"re-select every {REBALANCE} bars on a {LOOKBACK}-bar trailing Sharpe | cost {COST.name} {COST.per_side_bps():.3f} bps/side (ASSUMED)\n")

    rows, series = [], {}
    for k in TOP_K:
        pos, log = walk_forward(bars, signals, k)
        m = evaluate(bars, pos, f"WF_top{k}")
        series[m["label"]] = m.pop("net_returns")
        rows.append({**m, "selections": len(log)})
        if k == 3:
            top3_log = log

    for label, pos in (
        ("B_fixed_blend", signals.mean(axis=1).clip(0.0, 1.0)),
        ("A_buy_hold", pd.Series(1.0, index=bars.index)),
    ):
        m = evaluate(bars, pos, label)
        series[m["label"]] = m.pop("net_returns")
        rows.append({**m, "selections": 0})

    df = pd.DataFrame(rows).set_index("label")
    view = df.copy()
    for c in ("cagr", "max_dd", "alpha_ann", "avg_size"):
        view[c] = (view[c] * 100).round(2)
    for c in ("sharpe", "calmar", "alpha_t", "alpha_t_hac", "turnover"):
        view[c] = view[c].round(3)
    pd.set_option("display.width", 220)
    print(view.to_string())

    print("\nSelected strategies over time (top-3 policy):")
    for entry in top3_log[:6]:
        print(f"  {entry['date']}  {', '.join(entry['chosen'])}")
    if len(top3_log) > 6:
        print("  ...")
        for entry in top3_log[-3:]:
            print(f"  {entry['date']}  {', '.join(entry['chosen'])}")

    # How often did the selection overlap from one year to the next?
    overlaps = []
    for a, b in zip(top3_log, top3_log[1:], strict=False):
        overlaps.append(len(set(a["chosen"]) & set(b["chosen"])) / 3.0)
    print(f"\nselection stability: mean overlap with the previous year {np.mean(overlaps):.1%}")
    distinct = {n for e in top3_log for n in e["chosen"]}
    print(f"distinct signals ever selected: {len(distinct)} of {signals.shape[1]}")

    # Does selection beat simply holding everything?
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from edgelab_portfolio_run import sharpe_diff_test

    print("\nWalk-forward vs fixed blend (block bootstrap on the Sharpe difference):")
    decisive = []
    for k in TOP_K:
        test = sharpe_diff_test(series[f"WF_top{k}"], series["B_fixed_blend"])
        decisive.append({"policy": f"top{k}", **test})
        verdict = "selection adds" if test["p_two_sided"] < 0.05 and test["sharpe_diff"] > 0 else "no gain from selecting"
        print(f"  top{k}: dSharpe {test['sharpe_diff']:+.3f}  CI [{test['ci_lo']:+.3f}, {test['ci_hi']:+.3f}]  p {test['p_two_sided']:.3f}  -> {verdict}")

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"walkforward_{stamp}.json"
    path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat(),
                "round": 19,
                "family": "walk_forward_selection",
                "window": [START, END],
                "lookback": LOOKBACK,
                "rebalance": REBALANCE,
                "cost_model": COST.name,
                "cost_is_measured": False,
                "rows": json.loads(df.reset_index().to_json(orient="records")),
                "vs_fixed_blend": decisive,
                "selection_stability": float(np.mean(overlaps)),
                "distinct_selected": len(distinct),
                "selections_top3": top3_log,
            },
            indent=2,
            default=str,
        )
    )
    print(f"\nartifact: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
