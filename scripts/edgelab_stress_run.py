"""Round 12: gold and the stress complex (5 configurations).

Pre-registered before running, in this file:

    DEV    2000-08-30 .. 2012-12-31   (12.3 yrs) fit and select
    VAL    2013-01-01 .. 2019-12-31   (7.0 yrs) direction check
    SPENT  2020-01-01 .. 2024-12-31   consumed elsewhere; reported, never used to select
    OOS    2025-01-01 .. 2025-09-30   (0.75 yrs) far too short to decide anything

Five trials in a new family, so the deflated Sharpe uses 5.

**Timing, per the round-10 audit.** Gold is a 24-hour tradable close (futures to
2024-05, then M15). Every driver is close-of-day, but FRED stamps an observation
with its observation date and publishes after the close, so the decision is lagged
one full bar. `qts.research.edgelab.timing` computes that requirement rather than
this script asserting it. The lag-0 numbers are printed as a diagnostic only — they
are not executable and cannot pass the gate.

Cost is the realistic ECN model, charged at each bar's own price.
"""

from __future__ import annotations

import json
import warnings
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from qts.research.edgelab import CostModel, deflated_sharpe, hac_alpha
from qts.research.edgelab import stress as S
from qts.research.edgelab.power import detection_summary
from qts.research.edgelab.reporting import evaluate_period, strip_diagnostics
from qts.research.edgelab.timing import audit_required_lag, verdict_at_lag

warnings.filterwarnings("ignore", category=RuntimeWarning)

OUT = Path("data/research/experiments")
BPY = 252.0
TRIALS = 6  # five directional configs plus the reverse hypothesis
GATE_T = 2.5

WINDOWS = {
    "DEV": ("2000-08-30", "2012-12-31"),
    "VAL": ("2013-01-01", "2019-12-31"),
    "SPENT": ("2020-01-01", "2024-12-31"),
    "OOS": ("2025-01-01", "2025-09-30"),
}

CONFIGS = {
    "vix_trend": lambda idx: S.vix_trend(idx),
    "vix_regime": lambda idx: S.vix_regime(idx),
    "credit_trend": lambda idx: S.credit_trend(idx),
    "credit_regime": lambda idx: S.credit_regime(idx),
    "stress_composite": lambda idx: S.stress_composite(idx),
    # Declared *after* the five directional configs all came out negative, so it is
    # a data-derived hypothesis and the weakest evidence in the round. It is a
    # sixth trial, not a free second look at the same five.
    "stress_composite_reverse": lambda idx: 1.0 - S.stress_composite(idx),
}


def score(bars: pd.DataFrame, sig: pd.Series, cost: CostModel, label: str, lag: int) -> dict:
    """Score one configuration at a stated lag.

    ``run_vector`` already applies exactly one bar of lag (``held[1:] = pos[:-1]``),
    so ``lag=1`` — "decide on today's close, earn tomorrow's move" — means passing
    the signal unchanged. Only additional lag is an explicit shift. Getting this
    wrong silently doubles the lag; an earlier version of this file did.
    """
    # lag=0 is a diagnostic only: it undoes the engine's own one-bar lag so the
    # position can see the bar it is earning. That is look-ahead by construction and
    # exists solely to show how much of a result is timing artifact.
    delayed = sig.shift(-1) if lag == 0 else (sig.shift(lag - 1) if lag > 1 else sig)
    m = evaluate_period(bars, delayed.reindex(bars.index).ffill().fillna(0.0), cost, label, "stress", BPY)
    net, bench = m["net_returns"], m["bench_returns"]
    hac = hac_alpha(net, bench, BPY, lags=5)
    return {**strip_diagnostics(m), "alpha_t_hac": hac["alpha_t"]}


def main() -> int:
    gold = S.tradable_gold()
    idx = pd.DatetimeIndex(gold.index)
    bars_all = pd.DataFrame({"open": gold, "high": gold, "low": gold, "close": gold}, index=idx)
    bars_all["volume"] = 0.0
    cost = CostModel.realistic_ecn()

    timing = audit_required_lag("m15_utc_close", ("dxy_close",))
    required = 1  # FRED publishes after the close regardless of the price snapshot
    print(f"Gold basis: {gold.attrs.get('sources', 'unknown')}")
    print(f"  price snapshot check: {timing['explanation']}")
    print(f"  FRED publication lag imposes {required} extra bar(s); all gate numbers use lag={required}")
    print(f"  cost {cost.name} {cost.per_side_bps():.3f} bps/side (ASSUMED, charged per-bar) | trials {TRIALS}\n")

    rows = []
    for name, fn in CONFIGS.items():
        sig = fn(idx)
        dev = score(bars_all.loc[WINDOWS["DEV"][0] : WINDOWS["DEV"][1]], sig, cost, f"{name}_dev", required)
        val = score(bars_all.loc[WINDOWS["VAL"][0] : WINDOWS["VAL"][1]], sig, cost, f"{name}_val", required)
        stress = score(
            bars_all.loc[WINDOWS["DEV"][0] : WINDOWS["DEV"][1]], sig, CostModel.stressed(2.0), f"{name}_dev_x2", required
        )
        dev0 = score(bars_all.loc[WINDOWS["DEV"][0] : WINDOWS["DEV"][1]], sig, cost, f"{name}_dev_lag0", 0)
        spent = score(bars_all.loc[WINDOWS["SPENT"][0] : WINDOWS["SPENT"][1]], sig, cost, f"{name}_spent", required)
        dsr = float(deflated_sharpe(dev["sharpe"], TRIALS, dev["n_obs"], BPY, dev["skew"], dev["kurt"]))
        rows.append(
            {
                "name": name,
                "dev_alpha": dev["alpha_ann"],
                "dev_t": dev["alpha_t"],
                "dev_hac": dev["alpha_t_hac"],
                "dev_sharpe": dev["sharpe"],
                "dev_dd": dev["max_dd"],
                "dev_turnover": dev["turnover_per_year"],
                "dev_exposure": dev["exposure"],
                "dsr": dsr,
                "stress_alpha": stress["alpha_ann"],
                "stress_t": stress["alpha_t"],
                "val_alpha": val["alpha_ann"],
                "val_t": val["alpha_t"],
                "lag0_dev_t": dev0["alpha_t"],
                "spent_alpha": spent["alpha_ann"],
                "spent_t": spent["alpha_t"],
                "floor_sr": dev["min_detectable_sr"] if "min_detectable_sr" in dev else detection_summary(dev["n_obs"], BPY, GATE_T)["min_detectable_sr"],
            }
        )

    df = pd.DataFrame(rows).set_index("name")
    view = df.copy()
    for c in [c for c in view.columns if c.endswith(("_alpha", "dev_alpha", "val_alpha", "stress_alpha", "spent_alpha")) or c == "dev_dd"]:
        view[c] = (view[c] * 100).round(2)
    for c in [c for c in view.columns if c.endswith(("_t", "_hac", "dev_hac", "lag0_dev_t", "stress_t", "val_t", "spent_t"))]:
        view[c] = view[c].round(2)
    for c in ("dev_sharpe", "dev_turnover", "dev_exposure", "dsr", "floor_sr"):
        view[c] = view[c].round(3)
    pd.set_option("display.width", 250)
    print("Windows: DEV 2000-2012, VAL 2013-2019. 'lag0' is diagnostic only (not executable).")
    print(view[["dev_alpha", "dev_t", "dev_hac", "dev_sharpe", "dev_dd", "dev_turnover", "dev_exposure", "dsr", "stress_t", "val_alpha", "val_t", "lag0_dev_t", "floor_sr"]].to_string())
    print("\nSpent window 2020-2024 (reported for completeness; never used to select):")
    print(view[["spent_alpha", "spent_t"]].to_string())

    survivors = df[(df["dev_t"] >= GATE_T) & (df["dsr"] >= 0.95) & (df["stress_alpha"] > 0) & (df["dev_alpha"] > 0)]
    confirmed = survivors[survivors["val_t"] > 0]
    print(f"\ngate: {len(survivors)} DEV survivor(s) of {len(df)}; {len(confirmed)} confirmed on VAL")
    if len(confirmed):
        print("  survivors:", ", ".join(confirmed.index))

    # Timing robustness on anything that survived.
    for name in confirmed.index:
        table = pd.DataFrame(
            {
                "alpha_ann": [score(bars_all.loc[WINDOWS["DEV"][0] : WINDOWS["DEV"][1]], CONFIGS[name](idx), CostModel.realistic_ecn(), f"{name}_l{k}", k)["alpha_ann"] for k in (0, 1, 2, 3)],
                "alpha_t": [score(bars_all.loc[WINDOWS["DEV"][0] : WINDOWS["DEV"][1]], CONFIGS[name](idx), CostModel.realistic_ecn(), f"{name}_l{k}", k)["alpha_t"] for k in (0, 1, 2, 3)],
            },
            index=[0, 1, 2, 3],
        )
        print(f"  {name} timing robustness:", verdict_at_lag(table, required=1, threshold=GATE_T))

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "round": 12,
        "family": "stress_complex",
        "price_basis": gold.attrs.get("sources", ""),
        "windows": WINDOWS,
        "required_lag": required,
        "cost_model": cost.name,
        "cost_bps_per_side_reference": cost.per_side_bps(),
        "cost_is_measured": False,
        "trials": TRIALS,
        "rows": json.loads(df.reset_index().to_json(orient="records")),
        "survivors": list(survivors.index),
        "val_confirmed": list(confirmed.index),
        "spent_window_used_for_selection": False,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = OUT / f"stress_{stamp}.json"
    path.write_text(json.dumps(payload, indent=2, default=str))
    print(f"\nartifact: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
