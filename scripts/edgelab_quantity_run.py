"""Round 13: money and labour quantities against gold (5 configurations).

Pre-registered before running, in this file:

    DEV     1969-01-02 .. 2000-12-31   (32 yrs) fit and select
    VAL     2001-01-01 .. 2010-12-31   (10 yrs) direction check
    TEST    2011-01-01 .. 2019-12-31   (9 yrs)  confirmation
    SPENT   2020-01-01 .. 2024-12-31           not read by this script; the LBMA
                                               store stops at 2019-12-31 on purpose

Five trials in a new family, so the deflated Sharpe uses 5.

**Why this family is allowed under spent windows.** Rounds 1-12 used the *price*
of money (yields, real yields, inflation, inflation expectations) and the *price*
of risk (credit spreads, implied volatility). No round has used the *quantity* of
money or the quantity of labour slack: `us_m2`, `initial_claims_4wk`,
`unemployment_rate` and `sahm_realtime` were never loaded by any script before
round 13. That is new information about the same asset, not a new transform of an
old series, which is the only justification that survives once every historical
window is spent.

**Timing.** Every input is stamped at its publication date before it is aligned:
M2 and CPI two months after the reference month, unemployment one month, the Sahm
indicator two months, and the weekly claims series one week after its observation
date. That stamp is conservative by construction — it can only understate a
real-time signal. The signals are monthly, so turnover is 13-123 position changes
in 51 years and the round-7 turnover law (>9%/yr per daily flip) cannot bind.

Cost is the realistic ECN model, charged at each bar's own price.
"""

from __future__ import annotations

import json
import warnings
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from qts.research.edgelab import CostModel, deflated_sharpe, hac_alpha
from qts.research.edgelab.longgold import load_long_gold
from qts.research.edgelab.power import detection_summary
from qts.research.edgelab.quantity import quantity_specs
from qts.research.edgelab.reporting import evaluate_period, strip_diagnostics
from qts.research.edgelab.stress import tradable_gold

warnings.filterwarnings("ignore", category=RuntimeWarning)

OUT = Path("data/research/experiments")
BPY = 252.0
TRIALS = 5
GATE_T = 2.5


def _bars(close: pd.Series) -> pd.DataFrame:
    out = pd.DataFrame({"open": close, "high": close, "low": close, "close": close}, index=close.index)
    out["volume"] = 0.0
    return out


def score(bars: pd.DataFrame, sig: pd.Series, cost: CostModel, label: str, family: str) -> dict:
    """Score one configuration on one window.

    A rule that is flat for the whole window carries no evidence there, and the HAC
    regression is genuinely degenerate in that case — returning NaN is the honest
    answer, not a zero that looks like a measured result.
    """
    pos = sig.reindex(bars.index).ffill().fillna(0.0)
    m = evaluate_period(bars, pos, cost, label, family, BPY)
    flat = float(pos.abs().sum()) == 0.0
    try:
        hac_t = float("nan") if flat else hac_alpha(m["net_returns"], m["bench_returns"], BPY, lags=5)["alpha_t"]
    except ValueError:
        hac_t = float("nan")
    return {**strip_diagnostics(m), "alpha_t_hac": hac_t, "flat_window": flat}


def run_basis(close: pd.Series, windows: dict[str, tuple[str, str]], cost: CostModel) -> pd.DataFrame:
    bars = _bars(close)
    rows = []
    for name, fn in quantity_specs().items():
        sig = fn(bars)
        dev = score(bars.loc[windows["DEV"][0] : windows["DEV"][1]], sig, cost, f"{name}_dev", "quantity")
        val = score(bars.loc[windows["VAL"][0] : windows["VAL"][1]], sig, cost, f"{name}_val", "quantity")
        test = score(bars.loc[windows["TEST"][0] : windows["TEST"][1]], sig, cost, f"{name}_test", "quantity")
        dev2 = score(
            bars.loc[windows["DEV"][0] : windows["DEV"][1]], sig, CostModel.stressed(2.0), f"{name}_dev_x2", "quantity"
        )
        try:
            dsr = float(deflated_sharpe(dev["sharpe"], TRIALS, dev["n_obs"], BPY, dev["skew"], dev["kurt"]))
        except (ValueError, ZeroDivisionError):
            dsr = float("nan")
        rows.append(
            {
                "name": name,
                "exposure": float(sig.mean()),
                "flips": int((sig.diff().abs() > 0).sum()),
                "dev_alpha": dev["alpha_ann"],
                "dev_t": dev["alpha_t"],
                "dev_hac": dev["alpha_t_hac"],
                "dev_sharpe": dev["sharpe"],
                "dev_dd": dev["max_dd"],
                "dev_x2_alpha": dev2["alpha_ann"],
                "dsr": dsr,
                "val_alpha": val["alpha_ann"],
                "val_t": val["alpha_t"],
                "test_alpha": test["alpha_ann"],
                "test_t": test["alpha_t"],
                "floor_sr": detection_summary(dev["n_obs"], BPY, GATE_T)["min_detectable_sr"],
                "flat_dev": bool(dev.get("flat_window", False)),
            }
        )
    return pd.DataFrame(rows).set_index("name")


def _view(df: pd.DataFrame) -> pd.DataFrame:
    v = df.copy()
    for c in v.columns:
        if "alpha" in c or c == "dev_dd":
            v[c] = (v[c] * 100).round(2)
        elif "t" in c.split("_") or c in {"dev_hac", "dev_sharpe", "exposure", "dsr", "floor_sr"}:
            v[c] = v[c].round(3) if c in {"dev_sharpe", "exposure", "dsr", "floor_sr"} else v[c].round(2)
    return v


def main() -> int:
    cost = CostModel.realistic_ecn()
    print(f"cost {cost.name} {cost.per_side_bps():.3f} bps/side (ASSUMED, charged per-bar) | trials {TRIALS}")
    print("Timing: every input stamped at publication (M2/CPI +2m, unemployment +1m, Sahm +2m, claims +7d)\n")

    long_close = load_long_gold()["close"]
    long_windows = {
        "DEV": ("1969-01-02", "2000-12-31"),
        "VAL": ("2001-01-01", "2010-12-31"),
        "TEST": ("2011-01-01", "2019-12-31"),
    }
    print(f"=== 51-year basis (LBMA AM fix), {long_close.index.min().date()} .. {long_close.index.max().date()}")
    lm = run_basis(long_close, long_windows, cost)
    cols = ["exposure", "flips", "dev_alpha", "dev_t", "dev_hac", "dev_sharpe", "dev_dd", "dev_x2_alpha", "dsr", "val_alpha", "val_t", "test_alpha", "test_t", "floor_sr", "flat_dev"]
    pd.set_option("display.width", 250)
    print(_view(lm)[cols].to_string())

    survivors = lm[(lm["dev_t"] >= GATE_T) & (lm["dsr"] >= 0.95) & (lm["dev_x2_alpha"] > 0)]
    print(f"\nDEV survivors: {list(survivors.index) or 'none'} (gate: t>={GATE_T}, DSR>=0.95, positive at 2x cost)")
    confirmed = survivors[(survivors["val_t"] > 0) & (survivors["test_t"] > 0)]
    print(f"confirmed on VAL and TEST: {list(confirmed.index) or 'none'}")

    # Independent price basis: the executable 24-hour close, 2000-2025. Shorter, so
    # it is a consistency check rather than a second chance at the gate.
    trad = tradable_gold()
    print(f"\n=== tradable 24h basis (futures spliced to M15), {trad.index.min().date()} .. {trad.index.max().date()}")
    tm = run_basis(trad, {"DEV": ("2000-08-30", "2012-12-31"), "VAL": ("2013-01-01", "2019-12-31"), "TEST": ("2020-01-01", "2024-12-31")}, cost)
    print(_view(tm)[cols].to_string())
    if len(confirmed):
        print("\n-- survivors re-checked on the tradable basis --")
        print(_view(tm.loc[list(confirmed.index)])[["dev_alpha", "dev_t", "val_alpha", "val_t", "test_alpha", "test_t"]].to_string())

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"quantity_{stamp}.json"
    path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat(),
                "round": 13,
                "family": "quantity_macro",
                "trials": TRIALS,
                "cost_model": cost.name,
                "cost_is_measured": False,
                "publication_lags": {"us_m2": "2 months", "cpi": "2 months", "unemployment_rate": "1 month", "sahm_realtime": "2 months", "initial_claims_4wk": "7 days"},
                "long_basis_windows": long_windows,
                "long_basis": json.loads(lm.reset_index().to_json(orient="records")),
                "tradable_basis": json.loads(tm.reset_index().to_json(orient="records")),
                "survivors": list(survivors.index),
                "val_test_confirmed": list(confirmed.index),
            },
            indent=2,
            default=str,
        )
    )
    print(f"\nartifact: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
