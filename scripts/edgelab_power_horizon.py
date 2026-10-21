"""Round 16: how long would forward observation need to settle the question?

Round 14 showed the catalogue has no out-of-sample persistence, and every
historical window is spent, so the only remaining source of evidence is forward
observation through the ledger. Nobody has computed whether that is *feasible*.

This does it, from the measured effect sizes rather than from hope.

Method
------
For each signal, the information ratio is the annualised alpha divided by the
annualised standard deviation of the alpha residual (net minus beta times
benchmark) — i.e. the signal-to-noise of the thing we are actually trying to
detect. Under a stationary null the t-statistic grows as ``IR * sqrt(years)``, so
the horizon needed to reach a given t is::

    years = (t_target / IR) ** 2

That is arithmetic, not modelling. It is the same relationship the detection floor
in :mod:`qts.research.edgelab.power` uses, run in the other direction.

The point of the exercise is a decision: if the horizon is longer than the product's
life, then no amount of further searching in this space can produce a validated
edge, and the programme must change its question rather than its data.
"""

from __future__ import annotations

import json
import warnings
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from qts.research.edgelab import CostModel, alpha_decomposition, benchmark_returns, run_vector
from qts.research.edgelab.longgold import LONG_BOUNDS, load_long_gold, long_specs
from qts.research.edgelab.quantity import quantity_specs

warnings.filterwarnings("ignore", category=RuntimeWarning)

OUT = Path("data/research/experiments")
BPY = 252.0
T_TARGET = 2.5
COST = CostModel.realistic_ecn()


def information_ratio(net: pd.Series, bench: pd.Series) -> tuple[float, float]:
    """(alpha_ann, IR) where IR = alpha / std(net - beta * bench), annualised."""
    pair = pd.concat([net.rename("net"), bench.rename("bench")], axis=1).dropna()
    st = alpha_decomposition(pair["net"], pair["bench"], BPY)
    beta = float(st.get("beta", 1.0))
    resid = pair["net"] - beta * pair["bench"]
    te = float(resid.std(ddof=1) * np.sqrt(BPY))
    alpha = float(st["alpha_ann"])
    return alpha, (alpha / te if te > 0 else float("nan"))


def main() -> int:
    bars = load_long_gold()
    sigs = {s.name: s.positions(bars) for s in long_specs()}
    sigs.update({n: f(bars) for n, f in quantity_specs().items()})
    sigs = {k: v for k, v in sigs.items() if v.abs().sum() > 0}

    lo, hi = LONG_BOUNDS["DEV"]
    dev = bars.loc[lo:hi]
    bench = benchmark_returns(dev)
    yrs_dev = len(dev) / BPY

    rows = []
    nets = {}
    for name, pos in sigs.items():
        r = run_vector(dev, pos.reindex(dev.index).fillna(0.0), COST, name=name, family="x", bars_per_year=BPY, keep_equity=True)
        if r.net_returns is None:
            continue
        nets[name] = r.net_returns
        alpha, ir = information_ratio(r.net_returns, bench)
        years = (T_TARGET / ir) ** 2 if ir and np.isfinite(ir) and ir > 0 else float("inf")
        rows.append({"name": name, "dev_alpha": alpha, "dev_ir": ir, "years_to_t": years, "t_now": ir * np.sqrt(yrs_dev)})

    blend = pd.concat(nets, axis=1).mean(axis=1)
    alpha_b, ir_b = information_ratio(blend, bench)
    rows.append(
        {
            "name": "EQUAL_WEIGHT_BLEND",
            "dev_alpha": alpha_b,
            "dev_ir": ir_b,
            "years_to_t": (T_TARGET / ir_b) ** 2 if ir_b > 0 else float("inf"),
            "t_now": ir_b * np.sqrt(yrs_dev),
        }
    )

    df = pd.DataFrame(rows).set_index("name").sort_values("dev_ir", ascending=False)
    view = df.copy()
    view["dev_alpha"] = (view["dev_alpha"] * 100).round(2)
    for c in ("dev_ir", "years_to_t", "t_now"):
        view[c] = view[c].round(2)
    pd.set_option("display.width", 200)
    print(f"DEV {lo}..{hi} ({yrs_dev:.1f} yrs) | cost {COST.name} | target t {T_TARGET}\n")
    print(view.head(12).to_string())

    finite = df[np.isfinite(df["years_to_t"])]
    best = view.index[0]
    print(f"\nstrongest signal by IR: {best} (IR {df.loc[best, 'dev_ir']:.3f})")
    print(f"  horizon to t={T_TARGET}: {df.loc[best, 'years_to_t']:.1f} years")
    print(f"  blend IR {ir_b:.3f} -> {df.loc['EQUAL_WEIGHT_BLEND', 'years_to_t']:.1f} years")
    print(f"  median across {len(finite)} signals with positive IR: {finite['years_to_t'].median():.1f} years")
    print(f"  signals that would clear t={T_TARGET} within 10 years of forward data: {int((df['years_to_t'] <= 10).sum())}")

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"power_horizon_{stamp}.json"
    path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat(),
                "round": 16,
                "family": "power_analysis",
                "dev_window": list(LONG_BOUNDS["DEV"]),
                "dev_years": yrs_dev,
                "t_target": T_TARGET,
                "cost_model": COST.name,
                "rows": json.loads(df.reset_index().to_json(orient="records")),
                "blend_ir": ir_b,
                "blend_years_to_t": float(df.loc["EQUAL_WEIGHT_BLEND", "years_to_t"]),
            },
            indent=2,
            default=str,
        )
    )
    print(f"\nartifact: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
