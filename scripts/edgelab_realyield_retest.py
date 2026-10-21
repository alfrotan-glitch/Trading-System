"""Round 11: does the real-yield residual survive a correct price basis?

Round 9 reported `ry_z252` at DEV alpha_t 2.20 and called the family
"underpowered, not refuted". It was measured on the **LBMA AM fix** with a
**same-day** DFII10 value. The round-10 audit showed both are wrong for a rule
driven by close-of-day macro data:

* the fix is struck at 10:30 London, before the driver settles;
* FRED stamps DFII10 with its observation date but publishes it after that day's
  close, so a decision at the close of ``t`` may only use ``t-1``'s value.

This script re-runs the identical four configurations on **M15 24-hour tradable
closes** with a **one-day publication lag**, over the window where both are
available (2004-06 to 2025-09). Nothing about the signal changes; only the two
defects found in the audit are corrected.

The comparison is the point: if the family's DEV significance survives the
correction it is worth pursuing, and if it evaporates it joins XL-001.
"""

from __future__ import annotations

import json
import warnings
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from qts.research.edgelab import CostModel, hac_alpha
from qts.research.edgelab.fred_drivers import load_treasury_10y_real
from qts.research.edgelab.intraday import daily_bars
from qts.research.edgelab.metals import gold_bars, load_metals
from qts.research.edgelab.realyield import residual_signal
from qts.research.edgelab.reporting import evaluate_period, strip_diagnostics

warnings.filterwarnings("ignore", category=RuntimeWarning)

OUT = Path("data/research/experiments")
BPY = 252.0
TRIALS = 9  # 5 prior in the family + the 4 configurations below

WINDOWS = {
    "DEV_2004_2014": ("2004-06-11", "2014-12-31"),
    "VAL_2015_2019": ("2015-01-01", "2019-12-31"),
    "SPENT_2020_2024": ("2020-01-01", "2024-12-31"),  # spent elsewhere; reported, not used to select
    "OOS_2025": ("2025-01-01", "2025-09-30"),
}
CONFIGS = {
    "ry_z252": {"window": 252, "long_only": False, "discrete": False},
    "ry_z252_long": {"window": 252, "long_only": True, "discrete": False},
    "ry_z504": {"window": 504, "long_only": False, "discrete": False},
    "ry_z252_sign": {"window": 252, "long_only": False, "discrete": True},
}


def score(bars: pd.DataFrame, sig: pd.Series, cost: CostModel, label: str) -> dict:
    m = evaluate_period(bars, sig.reindex(bars.index).ffill().fillna(0.0), cost, label, "real_yield", BPY)
    net, bench = m["net_returns"], m["bench_returns"]
    hac = hac_alpha(net, bench, BPY, lags=5)
    out = {**strip_diagnostics(m), "alpha_t_hac": hac["alpha_t"]}
    return out


def main() -> int:
    real10 = load_treasury_10y_real()
    tradable = daily_bars(pd.read_parquet("data/research/xauusd_m15_basemax.parquet"))
    tradable = tradable.loc["2004-06-11":"2025-09-30"]
    lbma = gold_bars(load_metals())
    if lbma.index.tz is None:
        lbma.index = lbma.index.tz_localize("UTC")

    cost = CostModel.realistic_ecn()
    print(f"Round 11 re-test — tradable 24h closes {tradable.index.min().date()}..{tradable.index.max().date()}")
    print(f"  cost {cost.name} {cost.per_side_bps():.3f} bps/side (ASSUMED) | DFII10 lag 1 day | trials {TRIALS}\n")

    rows = []
    for name, kw in CONFIGS.items():
        # Correct basis + correct lag.
        sig_fixed = residual_signal(tradable, real10, **kw).shift(1)
        # Original basis + original lag, for comparison only.
        sig_orig = residual_signal(lbma, real10, **kw)
        lbma_win = lbma.loc["2004-06-11":"2019-12-31"]

        rec = {"name": name}
        for label in ("DEV_2004_2014", "VAL_2015_2019", "SPENT_2020_2024", "OOS_2025"):
            lo, hi = WINDOWS[label]
            sub = tradable.loc[lo:hi]
            if len(sub) < 250:
                continue
            m = score(sub, sig_fixed, cost, f"{name}_{label}")
            if label == "DEV_2004_2014":
                m_fixed_sharpe = m["sharpe"]
            rec[f"{label}_alpha"] = m["alpha_ann"]
            rec[f"{label}_t"] = m["alpha_t"]
            rec[f"{label}_hac"] = m["alpha_t_hac"]
        lo, hi = WINDOWS["DEV_2004_2014"]
        m0 = score(lbma_win, sig_orig, cost, f"{name}_orig_dev")
        rec["orig_DEV_alpha"] = m0["alpha_ann"]
        rec["orig_DEV_t"] = m0["alpha_t"]
        rec["turnover"] = m0["turnover_per_year"]
        rec["dev_sharpe"] = m_fixed_sharpe
        rows.append(rec)

    df = pd.DataFrame(rows).set_index("name")
    show = df.copy()
    for c in [c for c in show.columns if c.endswith(("_alpha", "_t", "_hac")) or c in ("turnover",)]:
        show[c] = show[c].round(3)
    pd.set_option("display.width", 240)
    print("Alpha/t by window. 'orig_DEV' is the round-9 construction (AM fix, no lag).")
    view = show[[c for c in show.columns if c.startswith(("DEV", "VAL", "orig"))]].copy()
    for c in [c for c in view.columns if c.endswith("alpha")]:
        view[c] = (view[c] * 100).round(2)
    for c in [c for c in view.columns if c.endswith(("_t", "_hac"))]:
        view[c] = view[c].round(2)
    print(view.to_string())
    print("\nSpent window (reported for completeness, not used to select):")
    spent = show[[c for c in show.columns if c.startswith("SPENT")]].copy()
    for c in [c for c in spent.columns if c.endswith("alpha")]:
        spent[c] = (spent[c] * 100).round(2)
    for c in [c for c in spent.columns if c.endswith(("_t", "_hac"))]:
        spent[c] = spent[c].round(2)
    print(spent.to_string())

    survivors = df[(df["DEV_2004_2014_t"] >= 2.5) & (df["DEV_2004_2014_alpha"] > 0) & (df["VAL_2015_2019_t"] > 0)]
    print(f"\ngate (DEV t >= 2.5 and VAL positive) under the corrected construction: {len(survivors)} survivor(s)")
    if len(survivors):
        print("  ", ", ".join(survivors.index))
    best = df["DEV_2004_2014_t"].idxmax()
    print(f"  best DEV t: {df.loc[best, 'DEV_2004_2014_t']:.2f} ({best}); round-9 construction gave {df.loc[best, 'orig_DEV_t']:.2f}")

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "round": 11,
        "purpose": "re-test round 9 on tradable closes with a 1-day DFII10 lag",
        "tradable_window": [str(tradable.index.min().date()), str(tradable.index.max().date())],
        "cost_bps_per_side": cost.per_side_bps(),
        "cost_is_measured": False,
        "trials": TRIALS,
        "rows": json.loads(df.reset_index().to_json(orient="records")),
        "survivors": list(survivors.index),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = OUT / f"realyield_retest_{stamp}.json"
    path.write_text(json.dumps(payload, indent=2, default=str))
    print(f"\nartifact: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
