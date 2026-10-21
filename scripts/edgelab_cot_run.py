"""Round 15: gold positioning (CFTC COT), 2018-03 to 2025-05.

**This round cannot produce a gate-level verdict, and does not pretend to.** 7.2
years of weekly reports puts the detection floor at Sharpe 0.93 for t = 2.5, far
above anything a positioning signal plausibly delivers. What it can do is measure
the effect size with an honest confidence interval, on genuinely new information
(nobody had ever loaded positioning into this programme), and say whether the
channel is worth carrying into forward observation.

Four configurations, pre-registered in `cot.cot_specs`:
`spec_contrarian`, `spec_momentum`, `commercial_contrarian`, `spec_oi_ratio`.

Timing: the report covers Tuesday and is published Friday, so values are stamped
four calendar days forward before they touch a bar. Cost is `ecn_realistic`,
charged per bar; one position change per week at most.
"""

from __future__ import annotations

import json
import warnings
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from qts.research.edgelab import CostModel, alpha_decomposition, benchmark_returns, hac_alpha, run_vector
from qts.research.edgelab.cot import SAMPLE, cot_specs, load_cot
from qts.research.edgelab.power import detection_summary
from qts.research.edgelab.stress import tradable_gold

warnings.filterwarnings("ignore", category=RuntimeWarning)

OUT = Path("data/research/experiments")
BPY = 252.0
TRIALS = 4
SEED = 20261021


def main() -> int:
    cost = CostModel.realistic_ecn()
    cot = load_cot()
    print(f"COT reports: {len(cot)} | {cot.index.min().date()} .. {cot.index.max().date()}")
    print(f"sample {SAMPLE[0]} .. {SAMPLE[1]} | cost {cost.name} {cost.per_side_bps():.3f} bps/side (ASSUMED)")

    gold = tradable_gold()
    lo, hi = pd.Timestamp(SAMPLE[0], tz="UTC"), pd.Timestamp(SAMPLE[1], tz="UTC")
    px = gold.loc[lo:hi]
    bars = pd.DataFrame({"open": px, "high": px, "low": px, "close": px}, index=px.index)
    bars["volume"] = 0.0
    n = len(bars)
    floor = detection_summary(n, BPY, 2.5)["min_detectable_sr"]
    print(f"bars {n} ({n / BPY:.1f} yrs) -> detection floor SR {floor:.2f} for t=2.5\n")

    bench = benchmark_returns(bars)
    rng = np.random.default_rng(SEED)
    rows = []
    for name, fn in cot_specs().items():
        pos = fn(bars).reindex(bars.index).fillna(0.0)
        r = run_vector(bars, pos, cost, name=name, family="positioning", bars_per_year=BPY, keep_equity=True)
        assert r.net_returns is not None
        pair = pd.concat([r.net_returns.rename("net"), bench.rename("bench")], axis=1).dropna()
        try:
            st = alpha_decomposition(pair["net"], pair["bench"], BPY)
            h = hac_alpha(pair["net"], pair["bench"], BPY, lags=5)["alpha_t"]
        except ValueError:
            st, h = {"alpha_ann": float("nan"), "alpha_t": float("nan")}, float("nan")

        # Bootstrap CI on the daily alpha, in blocks, so the interval reflects the
        # real serial dependence rather than an iid assumption.
        d = pair["net"].to_numpy() - pair["bench"].to_numpy() * st.get("beta", 1.0)
        boot = np.empty(1000)
        block = 20
        for b in range(1000):
            starts = rng.integers(0, len(d) - block, size=int(np.ceil(len(d) / block)))
            idx = ((starts[:, None] + np.arange(block)) % len(d)).ravel()[: len(d)]
            boot[b] = d[idx].mean() * BPY
        alpha_ci = (float(np.quantile(boot, 0.025)), float(np.quantile(boot, 0.975)))

        rows.append(
            {
                "name": name,
                "alpha_ann": st["alpha_ann"],
                "alpha_t": st["alpha_t"],
                "alpha_t_hac": h,
                "alpha_ci_lo": alpha_ci[0],
                "alpha_ci_hi": alpha_ci[1],
                "ci_excludes_zero": bool(alpha_ci[0] > 0 or alpha_ci[1] < 0),
                "sharpe": r.sharpe,
                "max_dd": r.max_dd,
                "exposure": r.exposure,
                "flips": int((pos.diff().abs() > 0).sum()),
                "survives_costs": r.net_return > 0,
            }
        )

    df = pd.DataFrame(rows).set_index("name")
    view = df.copy()
    for c in ("alpha_ann", "alpha_ci_lo", "alpha_ci_hi", "max_dd"):
        view[c] = (view[c] * 100).round(2)
    for c in ("alpha_t", "alpha_t_hac", "sharpe", "exposure"):
        view[c] = view[c].round(3)
    pd.set_option("display.width", 220)
    print(view.to_string())
    print(f"\nany CI excluding zero: {bool(df['ci_excludes_zero'].any())}")
    print(f"any clearing the floor: {bool((df['alpha_t'] >= 2.5).any())} (floor SR {floor:.2f})")
    print(
        "\nverdict: NOT TESTABLE at gate level on 7.2 years. Reported as an effect size only; "
        "no candidate is registered from it."
    )

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"cot_{stamp}.json"
    path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat(),
                "round": 15,
                "family": "positioning",
                "source": "CFTC COT gold, yoseph-zemede/gold-cot-scraper via codeload",
                "sample": SAMPLE,
                "reports": int(len(cot)),
                "release_lag_days": 4,
                "cost_model": cost.name,
                "cost_is_measured": False,
                "trials": TRIALS,
                "detection_floor_sr": floor,
                "gate_testable": False,
                "rows": json.loads(df.reset_index().to_json(orient="records")),
            },
            indent=2,
            default=str,
        )
    )
    print(f"artifact: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
