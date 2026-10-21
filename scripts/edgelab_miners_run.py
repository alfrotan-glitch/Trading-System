"""Round 18: gold miners as a cross-market signal for gold.

Pre-registered before running:

    DEV   2006-05-22 .. 2014-12-31   (8.6 yrs)  fit and select
    VAL   2015-01-01 .. 2019-12-31   (5.0 yrs)  direction check
    DIAG  2020-01-01 .. 2024-05-17   spent holdout — reported, never selected on

Four configurations in a new family, so the deflated Sharpe uses 4. The miners ETF
starts in 2006, which caps the sample at 18 years; the detection floor there is
Sharpe ~0.59 for t = 2.5, so this round can only see a large effect and says so.

Signal construction is cross-market but the *trade* is gold: the instrument stays
XAUUSD@, and no miners position is ever taken.

**Timing, and why this round needed the guardrail.** Gold ``AU.csv`` is the LBMA
10:30 London fix. The miners ETF closes at 16:00 New York, about eleven hours
*later* on the same calendar date. Using same-day miners data to trade the gold fix
is therefore look-ahead, and it produces a spectacular fake result: ``miner_momentum``
shows DEV alpha +10.7%/yr at t 5.57 and Sharpe 1.94 — the best number the programme
has ever produced — and **exactly zero** (t 0.01) once the miners close is lagged by
one day. On the tradable 24-hour basis it is +1.3%/yr at t 0.93 and never better.

This is the third occurrence of the same defect (after XL-001 in round 10 and the
real-yield family in round 11). Every reported number here is the executable-lag
number; the lag-0 figure is printed once, labelled, and cannot gate anything.
"""

from __future__ import annotations

import json
import warnings
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from qts.research.edgelab import CostModel, deflated_sharpe, hac_alpha
from qts.research.edgelab.miners import miner_specs
from qts.research.edgelab.power import detection_summary
from qts.research.edgelab.reporting import evaluate_period

warnings.filterwarnings("ignore", category=RuntimeWarning)

OUT = Path("data/research/experiments")
BPY = 252.0
TRIALS = 4
GATE_T = 2.5

WINDOWS = {
    "DEV": ("2006-05-22", "2014-12-31"),
    "VAL": ("2015-01-01", "2019-12-31"),
    "DIAG": ("2020-01-01", "2024-05-17"),
}


#: Miners close after the gold fix, so their information is only usable from the
#: next gold bar onward.
EXECUTABLE_LAG = 1


def main() -> int:
    from qts.research.edgelab.metals import gold_bars, load_metals
    from qts.research.edgelab.timing import audit_required_lag

    cost = CostModel.realistic_ecn()
    metals = load_metals()
    bars = gold_bars(metals)
    print(f"gold bars {bars.index.min().date()} .. {bars.index.max().date()}")
    print(f"cost {cost.name} {cost.per_side_bps():.3f} bps/side (ASSUMED) | trials {TRIALS}")
    guard = audit_required_lag("lbma_am_fix", ("miners_equity_close",))
    print(f"timing guardrail: {guard.get('explanation', 'driver snapshot not registered')}")
    print(f"all gate numbers use a {EXECUTABLE_LAG}-bar lag on the miners close; lag 0 is a labelled diagnostic\n")

    rows = []
    for name, fn in miner_specs().items():
        raw = fn(bars)
        sig_all = raw.shift(EXECUTABLE_LAG).fillna(0.0)
        diag = raw  # look-ahead by construction; printed, never gated
        rec = {"name": name, "flips": int((sig_all.diff().abs() > 0).sum())}
        d_dev = evaluate_period(bars.loc[WINDOWS["DEV"][0] : WINDOWS["DEV"][1]], diag.loc[WINDOWS["DEV"][0] : WINDOWS["DEV"][1]], cost, f"{name}_diag", "miners", BPY)
        rec["lag0_dev_alpha"] = d_dev["alpha_ann"]
        rec["lag0_dev_t"] = d_dev["alpha_t"]
        for label, (lo, hi) in WINDOWS.items():
            sub = bars.loc[lo:hi]
            sig = sig_all.loc[lo:hi]
            if float(sig.abs().sum()) == 0:
                rec[f"{label}_alpha"] = float("nan")
                rec[f"{label}_t"] = float("nan")
                continue
            m = evaluate_period(sub, sig, cost, f"{name}_{label}", "miners", BPY)
            net, bench = m["net_returns"], m["bench_returns"]
            try:
                hac = float(hac_alpha(net, bench, BPY, lags=5)["alpha_t"])
            except ValueError:
                hac = float("nan")
            rec[f"{label}_alpha"] = m["alpha_ann"]
            rec[f"{label}_t"] = m["alpha_t"]
            rec[f"{label}_sr"] = m["sharpe"]
            rec[f"{label}_hac"] = hac
            rec[f"{label}_n"] = m["n_obs"]
        dev_n = rec.get("DEV_n", 0)
        if dev_n:
            rec["floor_sr"] = detection_summary(dev_n, BPY, GATE_T)["min_detectable_sr"]
            try:
                rec["dsr"] = float(deflated_sharpe(rec["DEV_sr"], TRIALS, dev_n, BPY, 0.0, 3.0))
            except (ValueError, ZeroDivisionError):
                rec["dsr"] = float("nan")
        rows.append(rec)

    df = pd.DataFrame(rows).set_index("name")
    view = df.copy()
    for c in view.columns:
        if "alpha" in c:
            view[c] = (view[c] * 100).round(2)
        elif c in {"_t", "hac"} or c.endswith(("_t", "_hac")):
            view[c] = view[c].round(2)
        elif c.endswith(("_sr", "floor_sr", "dsr")):
            view[c] = view[c].round(3)
    pd.set_option("display.width", 240)
    cols = ["flips", "DEV_alpha", "DEV_t", "DEV_sr", "DEV_hac", "dsr", "VAL_alpha", "VAL_t", "DIAG_alpha", "DIAG_t", "lag0_dev_alpha", "lag0_dev_t", "floor_sr"]
    print(view[[c for c in cols if c in view.columns]].to_string())
    print("\nDIAG 2020-2024 is a spent holdout: reported for completeness, never used to select.")
    print("lag0_* columns are LATER information used against an earlier fix — the artifact, not a result.")

    survivors = df[(df["DEV_t"] >= GATE_T) & (df["dsr"] >= 0.95) & (df["DEV_alpha"] > 0)]
    confirmed = survivors[survivors["VAL_t"] > 0]
    print(f"\ngate: {len(survivors)} DEV survivor(s); {len(confirmed)} confirmed on VAL")
    if len(confirmed):
        print("  survivors:", ", ".join(confirmed.index))
    else:
        print("  verdict: family closed — cross-market miners information does not time gold")

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"miners_{stamp}.json"
    path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat(),
                "round": 18,
                "family": "cross_market_miners",
                "source": "AU_MINERS_ETF.csv from teofiloxyz/precious-metals-price",
                "windows": WINDOWS,
                "cost_model": cost.name,
                "cost_is_measured": False,
                "trials": TRIALS,
                "rows": json.loads(df.reset_index().to_json(orient="records")),
                "survivors": list(survivors.index),
                "val_confirmed": list(confirmed.index),
            },
            indent=2,
            default=str,
        )
    )
    print(f"artifact: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
