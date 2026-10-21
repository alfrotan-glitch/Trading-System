"""Does XL-001 survive the price-snapshot problem?

The audit found a timing asymmetry the scorecard never showed. XL-001's drivers are
**close-of-day** series (DXY and the 10y yield both settle around 21:00-22:00
London), but the gold series every macro round has used is the **10:30 London AM
fix** (confirmed in the source dataset's own README). The harness therefore credits
a position entered at 10:30 with information that only existed at 22:00.

Two consequences, both testable:

1. **Lag sensitivity.** Shifting the decision by one bar (enter at the next fix)
   removes the overlap. If a rule only works at lag 0, it was trading on
   information it could not have had.
2. **Price-basis sensitivity.** The M15 feed gives a genuine 24-hour tradable
   close. Running the identical rule on the fix and on the tradable close over the
   same dates isolates the artifact directly — this is the same test that halved
   `tsmom_1m`'s alpha in round 3.

The comparison is deliberately run only where both price series exist
(2005-06 onward, after the 126-bar warm-up), so nothing is being extrapolated.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from qts.research.edgelab import CostModel
from qts.research.edgelab.intraday import daily_bars

BPY = 252.0
LOOKBACK = 126
OUT = Path("data/research/experiments")


def cost_bps(price: float) -> float:
    """Realistic ECN per-side bps at a given price (0.20 spread, 3.50/lot, 0.05 slip)."""
    return ((0.20 / 2.0) / price + 3.50 / (100.0 * price) + 0.05 / price) * 1e4


def signal_on(index: pd.DatetimeIndex) -> pd.Series:
    dxy = pd.read_csv("data/raw/longgold/macro_daily/DXY.csv", parse_dates=["date"]).set_index("date")["close"]
    y10 = pd.read_csv("data/raw/longgold/macro_daily/US_10Y_TREASURY_YIELD.csv", parse_dates=["date"]).set_index("yield")["yield"] if False else None
    y10 = pd.read_csv("data/raw/longgold/macro_daily/US_10Y_TREASURY_YIELD.csv", parse_dates=["date"]).set_index("date")["yield"]

    def cal(s: pd.Series) -> pd.Series:
        s = s.copy()
        if s.index.tz is None:
            s.index = s.index.tz_localize("UTC")
        return s.reindex(s.index.union(index)).ffill().reindex(index)

    d, y = cal(dxy), cal(y10)
    usd = (d < d.shift(LOOKBACK)).astype(float)
    yld = (y < y.shift(LOOKBACK)).astype(float)
    sig = (usd + yld) / 2.0
    sig[d.shift(LOOKBACK).isna() | y.shift(LOOKBACK).isna()] = np.nan
    return sig


def run(price: pd.Series, sig: pd.Series, lag: int, charge: bool = True) -> dict:
    """Hand-rolled backtest: position[t] = sig[t-lag] earns price[t]/price[t-1]."""
    idx = price.index
    pos = sig.shift(lag).reindex(idx).fillna(0.0).clip(0.0, 1.0).to_numpy(dtype=float)
    px = price.to_numpy(dtype=float)
    n = len(px)
    ret = np.zeros(n)
    ret[1:] = px[1:] / px[:-1] - 1.0
    held = np.zeros(n)
    held[1:] = pos[:-1]
    net = held * ret
    if charge:
        dpos = np.abs(np.diff(np.concatenate([[0.0], pos])))
        net = net - dpos * np.array([cost_bps(p) for p in px]) / 1e4
    net = pd.Series(net[1:], index=idx[1:])
    bench = pd.Series(px, index=idx).pct_change().iloc[1:]

    j = pd.concat([net.rename("s"), bench.rename("b")], axis=1).dropna()
    y_, x_ = j["s"].to_numpy(), j["b"].to_numpy()
    X = np.column_stack([np.ones(len(y_)), x_])
    coef, *_ = np.linalg.lstsq(X, y_, rcond=None)
    resid = y_ - X @ coef
    u = X * resid[:, None]
    meat = u.T @ u
    for L in range(1, 6):
        w = 1.0 - L / 6.0
        g = u[L:].T @ u[:-L]
        meat += w * (g + g.T)
    xtx = np.linalg.inv(X.T @ X)
    cov = xtx @ meat @ xtx
    se = float(np.sqrt(cov[0, 0]))
    return {
        "n": len(y_),
        "alpha_ann": float(coef[0]) * BPY,
        "alpha_t": float(coef[0]) / se,
        "beta": float(coef[1]),
        "sharpe": float(np.mean(y_) / np.std(y_, ddof=1) * np.sqrt(BPY)),
        "total_net": float(np.prod(1 + y_) - 1),
        "turnover_yr": float(np.abs(np.diff(pos)).sum() / (len(pos) / BPY)),
        "exposure": float(np.mean(pos != 0)),
    }


def main() -> int:
    au = pd.read_csv("data/raw/longgold/metals/AU.csv", parse_dates=["date"]).set_index("date")["price"].astype(float)
    au.index = au.index.tz_localize("UTC")
    m15 = daily_bars(pd.read_parquet("data/research/xauusd_m15_basemax.parquet"))["close"].astype(float)

    # Common window where both price series exist and the signal is warm.
    lo, hi = "2005-06-01", "2024-05-17"
    fix = au.loc[lo:hi]
    close = m15.loc[lo:hi]
    common = fix.index.intersection(close.index)
    fix, close = fix.loc[common], close.loc[common]
    print(f"common window {common.min().date()}..{common.max().date()}  n={len(common)}")
    print("  the fix is 10:30 London; the M15 close is a 24h tradable close.")
    print(f"  daily-return correlation between them: {fix.pct_change().corr(close.pct_change()):.3f}\n")

    sig = signal_on(pd.DatetimeIndex(common))
    rows = []
    for basis, px in (("LBMA AM fix", fix), ("M15 tradable close", close)):
        for lag in (0, 1, 2):
            m = run(px, sig, lag)
            rows.append({"basis": basis, "lag": lag, **m})
    df = pd.DataFrame(rows)
    show = df.copy()
    show["alpha_ann"] = (show["alpha_ann"] * 100).round(2)
    show["total_net"] = (show["total_net"] * 100).round(1)
    for c in ("alpha_t", "beta", "sharpe", "turnover_yr", "exposure"):
        show[c] = show[c].round(2)
    pd.set_option("display.width", 200)
    print(show[["basis", "lag", "n", "alpha_ann", "alpha_t", "sharpe", "total_net", "turnover_yr", "exposure"]].to_string(index=False))

    # The decisive contrast: same rule, same dates, two price snapshots, honest lag.
    a = df[(df.basis == "LBMA AM fix") & (df.lag == 1)].iloc[0]
    b = df[(df.basis == "M15 tradable close") & (df.lag == 1)].iloc[0]
    print("\nAt the implementable lag (1 bar):")
    print(f"  LBMA fix          alpha {a.alpha_ann:+.2%}  t {a.alpha_t:.2f}")
    print(f"  tradable close    alpha {b.alpha_ann:+.2%}  t {b.alpha_t:.2f}")
    ratio = b.alpha_ann / a.alpha_ann if a.alpha_ann != 0 else float("nan")
    print(f"  ratio tradable/fix: {ratio:.2f}")

    verdict = (
        "SURVIVES" if b.alpha_t >= 2.5 and b.alpha_ann > 0
        else "WEAKENED" if b.alpha_ann > 0
        else "FAILS"
    )
    print(f"\n  => tradable-price verdict: {verdict}")

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "window": [lo, hi],
        "n_common": int(len(common)),
        "rows": json.loads(df.to_json(orient="records")),
        "verdict": verdict,
        "cost_model": CostModel.realistic_ecn().name,
        "note": (
            "LBMA AM fix is 10:30 London. DXY and the 10y are close-of-day series, "
            "so the lag-0 harness earns part of its return before the signal exists. "
            "Lag 1 is the implementable version."
        ),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = OUT / f"xl001_price_basis_{stamp}.json"
    path.write_text(json.dumps(payload, indent=2, default=str))
    print(f"\nartifact: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
