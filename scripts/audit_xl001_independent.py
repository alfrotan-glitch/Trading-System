"""Independent audit of XL-001 and the cost model.

Deliberately shares **no code** with `qts.research.edgelab`. Everything is
reimplemented from the raw CSVs with plain numpy/pandas so that agreement between
this script and the production path is evidence, not tautology.

What it checks, in order:

1. **Cost arithmetic.** Recompute per-side bps from the published spread/commission/
   slippage figures with no reference to `CostModel`.
2. **Signal timing.** Confirm the signal at date ``t`` uses only data available at
   ``t``: recomputing it on a truncated history must reproduce it exactly up to the
   truncation point. This is the single most common way a macro backtest leaks.
3. **Return convention.** Rebuild P&L by hand — position at ``t`` earns the
   ``t -> t+1`` close-to-close return — and compare to the harness.
4. **Alpha / t-stat.** Independent OLS with a hand-computed HAC standard error.
5. **Deflated Sharpe.** Independent computation.
6. **Sensitivity the harness does not print.** What happens if the macro data is
   lagged one extra day (the honest assumption if FRED's timestamp is the
   observation date rather than the publication date)?

Exit code is non-zero if any headline number disagrees beyond tolerance, so this
can be wired into CI rather than read as a one-off report.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

BARS_PER_YEAR = 252.0
METALS = Path("data/raw/longgold/metals/AU.csv")
DXY = Path("data/raw/longgold/macro_daily/DXY.csv")
Y10 = Path("data/raw/longgold/macro_daily/US_10Y_TREASURY_YIELD.csv")
LOOKBACK = 126

# Published production numbers this audit is checking against.
EXPECTED = {
    "DEV_1971_2000": {"alpha_ann": 0.033, "alpha_t": 2.70, "sharpe": 0.62},
    "VAL_2001_2010": {"alpha_ann": 0.014, "alpha_t": 0.65, "sharpe": 0.92},
    "TEST_2011_2019": {"alpha_ann": 0.049, "alpha_t": 2.94, "sharpe": 0.66},
}
WINDOWS = {
    "DEV_1971_2000": ("1971-01-01", "2000-12-31"),
    "VAL_2001_2010": ("2001-01-01", "2010-12-31"),
    "TEST_2011_2019": ("2011-01-01", "2019-12-31"),
}

failures: list[str] = []
notes: list[str] = []


def check(name: str, ok: bool, detail: str) -> None:
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] {name}: {detail}")
    if not ok:
        failures.append(f"{name}: {detail}")


# --------------------------------------------------------------------------- 1. costs


def cost_per_side_bps(spread_usd: float, commission_per_lot_side: float, contract_oz: float,
                      slippage_usd: float, price: float) -> float:
    """Per-side cost in bps, written from the definition rather than copied."""
    half_spread = (spread_usd / 2.0) / price
    commission = commission_per_lot_side / (contract_oz * price)
    slippage = slippage_usd / price
    return (half_spread + commission + slippage) * 1e4


def audit_costs() -> None:
    print("\n=== 1. cost arithmetic")
    models = {
        "ecn_assumed (default)": (0.05, 3.50, 100.0, 0.02),
        "ecn_realistic": (0.20, 3.50, 100.0, 0.05),
        "stressed x2": (0.10, 7.00, 100.0, 0.04),
        "standard_account": (0.18, 0.00, 100.0, 0.02),
    }
    published = {"ecn_assumed (default)": 0.40, "ecn_realistic": 0.925,
                 "stressed x2": 0.80, "standard_account": 0.55}
    for name, (sp, cm, oz, sl) in models.items():
        got = cost_per_side_bps(sp, cm, oz, sl, 2000.0)
        want = published[name]
        check(f"{name} @ $2000/oz", abs(got - want) < 0.01, f"computed {got:.4f} bps/side vs published {want}")

    # The 4.0-vs-0.40 error that was found and fixed: a 10x gap would be visible.
    check(
        "no factor-of-ten error remains",
        not (3.9 < cost_per_side_bps(0.05, 3.50, 100.0, 0.02, 2000.0) < 4.1),
        "default model is ~0.40 bps/side, not ~4.0",
    )

    # Cost is price-dependent, and the backtest charges it per bar at the actual
    # price. At gold's 2004 price the same spread is far more expensive in bps.
    for px in (400.0, 1000.0, 2000.0, 3300.0):
        bps = cost_per_side_bps(0.20, 3.50, 100.0, 0.05, px)
        print(f"    realistic ECN at ${px:>6.0f}/oz -> {bps:5.2f} bps/side")
    notes.append(
        "cost is charged at the bar's own price, so early-sample bps are much "
        "higher than the $2000 reference; this is correct (a fixed dollar spread "
        "is a larger fraction of a cheaper metal) but means the published 0.925 "
        "figure understates early-period cost."
    )


# --------------------------------------------------------------------------- 2. data


def load_raw() -> tuple[pd.Series, pd.Series, pd.Series]:
    gold = pd.read_csv(METALS, parse_dates=["date"]).set_index("date")["price"].astype(float)
    dxy = pd.read_csv(DXY, parse_dates=["date"]).set_index("date")["close"].astype(float)
    y10 = pd.read_csv(Y10, parse_dates=["date"]).set_index("date")["yield"].astype(float)
    for name, s in (("gold", gold), ("dxy", dxy), ("y10", y10)):
        if s.index.has_duplicates:
            raise SystemExit(f"{name} has duplicate dates")
        if not s.index.is_monotonic_increasing:
            raise SystemExit(f"{name} is not sorted")
    return gold.sort_index(), dxy.sort_index(), y10.sort_index()


def on_calendar(series: pd.Series, index: pd.DatetimeIndex) -> pd.Series:
    """Forward-fill a driver onto the bar calendar.

    Order matters and getting it wrong silently invalidates the audit: computing
    the signal on the raw union of driver dates and *then* reindexing leaves NaN
    wherever one driver was missing, which turns into spurious flat periods and
    extra churn. A missing observation on a holiday carries no new information, so
    the fill has to happen first — which is what the production path does.
    """
    return series.reindex(series.index.union(index)).ffill().reindex(index)


def build_signal(dxy: pd.Series, y10: pd.Series, index: pd.DatetimeIndex) -> pd.Series:
    """XL-001 from scratch: average of two 126-day direction-of-travel flags.

    Both drivers are forward-filled onto ``index`` (the gold calendar) *before* the
    comparison, matching the production alignment.
    """
    d = on_calendar(dxy, index)
    y = on_calendar(y10, index)
    usd = (d < d.shift(LOOKBACK)).astype(float)
    yld = (y < y.shift(LOOKBACK)).astype(float)
    sig = (usd + yld) / 2.0
    # The first LOOKBACK bars have no comparison; that is unknown, not "not
    # falling", so they stay NaN rather than being scored as zero exposure.
    sig[d.shift(LOOKBACK).isna() | y.shift(LOOKBACK).isna()] = np.nan
    return sig.rename("signal")


# --------------------------------------------------------------------------- 3. timing


def audit_signal_timing(gold: pd.Series, dxy: pd.Series, y10: pd.Series) -> None:
    """The signal must be a function of the past only."""
    print("\n=== 2. signal timing (look-ahead)")

    full = build_signal(dxy, y10, pd.DatetimeIndex(gold.index))
    cut = pd.Timestamp("1995-06-15")
    trunc = build_signal(dxy.loc[:cut], y10.loc[:cut], pd.DatetimeIndex(gold.loc[:cut].index))
    overlap = trunc.dropna().index.intersection(full.dropna().index)
    same = np.allclose(trunc.loc[overlap].to_numpy(), full.loc[overlap].to_numpy(), equal_nan=True)
    check(
        "signal is not affected by future data",
        same,
        f"{len(overlap)} dates identical when the series is truncated at {cut.date()}",
    )

    # Verify the first valid date is exactly 126 bars into the gold calendar.
    first_valid_gold = full.dropna().index.min()
    pos = gold.index.get_loc(first_valid_gold)
    check(
        "first valid signal is exactly LOOKBACK bars in",
        pos == LOOKBACK,
        f"index position {pos} (expected {LOOKBACK})",
    )

    # DXY and the 10y are published with a lag. The rule uses the same-day level,
    # so a one-day implementation delay is a real possibility. Quantified below.
    notes.append(
        "XL-001 uses the same-day macro close, matching the harness. If FRED's "
        "date is the observation date and publication is later, a real "
        "implementation must trade one day later; that variant is measured in "
        "section 6."
    )


# --------------------------------------------------------------------------- 4. backtest


def backtest(price: pd.Series, signal: pd.Series, cost_bps_at: pd.Series, *,
             lag: int = 0, charge_costs: bool = True) -> pd.Series:
    """Hand-rolled P&L.

    ``position[t]`` is set from ``signal[t - lag]`` and earns
    ``price[t+1]/price[t] - 1``. Costs are charged on the change in position,
    at the per-side rate in force at bar ``t``.
    """
    sig = signal.shift(lag).reindex(price.index)
    pos = sig.fillna(0.0).clip(0.0, 1.0).to_numpy(dtype=float)
    px = price.to_numpy(dtype=float)
    n = len(px)
    ret = np.zeros(n)
    ret[1:] = px[1:] / px[:-1] - 1.0
    held = np.zeros(n)
    held[1:] = pos[:-1]
    gross = held * ret
    if charge_costs:
        # dpos[t] is the position change executed at the close of t.
        dpos = np.abs(np.diff(np.concatenate([[0.0], pos])))
        gross = gross - dpos * cost_bps_at.to_numpy(dtype=float) / 1e4
    out = pd.Series(gross, index=price.index)
    return out.iloc[1:]  # bar 0 has no prior decision


def ols_alpha_t(strategy: pd.Series, bench: pd.Series, lags: int = 0) -> dict:
    """Alpha vs buy-and-hold. ``lags=0`` is plain OLS, ``lags>0`` is Newey-West."""
    j = pd.concat([strategy.rename("s"), bench.rename("b")], axis=1).dropna()
    y = j["s"].to_numpy()
    x = j["b"].to_numpy()
    X = np.column_stack([np.ones(len(y)), x])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    xtx_inv = np.linalg.inv(X.T @ X)
    if lags <= 0:
        sigma2 = resid @ resid / (len(y) - 2)
        cov = sigma2 * xtx_inv
    else:
        u = X * resid[:, None]
        meat = u.T @ u
        for L in range(1, lags + 1):
            w = 1.0 - L / (lags + 1.0)
            g = u[L:].T @ u[:-L]
            meat += w * (g + g.T)
        cov = xtx_inv @ meat @ xtx_inv
    se_alpha = float(np.sqrt(cov[0, 0]))
    alpha_bar = float(beta[0])
    resid_sd = float(np.std(resid, ddof=2))
    return {
        "alpha_ann": alpha_bar * BARS_PER_YEAR,
        "alpha_t": alpha_bar / se_alpha,
        "beta": float(beta[1]),
        "n": len(y),
        "sharpe": float(np.mean(y) / np.std(y, ddof=1) * np.sqrt(BARS_PER_YEAR)) if np.std(y, ddof=1) > 0 else 0.0,
        "resid_sd": resid_sd,
    }


def deflated_sharpe_independent(sr: float, n_trials: int, n_obs: int, skew: float, kurt: float) -> float:
    """Bailey/López de Prado, from the formula, with no local helpers."""
    from scipy.stats import norm

    if n_trials < 1:
        raise ValueError("n_trials must be >= 1")
    e = 0.5772156649015329
    if n_trials == 1:
        sr0 = 0.0
    else:
        z1 = norm.ppf(1.0 - 1.0 / n_trials)
        z2 = norm.ppf(1.0 - 1.0 / (n_trials * np.e))
        sr0 = (1.0 - e) * z1 + e * z2
    # sr is annualised; convert to per-observation.
    sr_p = sr / np.sqrt(BARS_PER_YEAR)
    denom = np.sqrt(1.0 - skew * sr_p + (kurt - 1.0) / 4.0 * sr_p**2)
    if denom <= 0:
        return 0.0
    t = (sr_p - sr0 / np.sqrt(n_obs)) * np.sqrt(n_obs - 1) / denom
    return float(norm.cdf(t))


def audit_backtest(gold: pd.Series, dxy: pd.Series, y10: pd.Series) -> dict:
    print("\n=== 3-5. backtest, alpha, deflated Sharpe")
    price = gold
    sig = build_signal(dxy, y10, pd.DatetimeIndex(price.index))
    # Costs at each bar's own price, realistic ECN (0.20 spread, 3.50/lot, 0.05 slip).
    cost_bps_at = price.map(lambda p: cost_per_side_bps(0.20, 3.50, 100.0, 0.05, float(p)))
    bench_all = price.pct_change()

    results = {}
    for label, (lo, hi) in WINDOWS.items():
        mask = (price.index >= lo) & (price.index <= hi)
        p = price[mask]
        s = sig.reindex(p.index)
        net = backtest(p, s, cost_bps_at.reindex(p.index))
        stats = ols_alpha_t(net, bench_all.reindex(net.index), lags=0)
        results[label] = stats
        exp = EXPECTED[label]
        tol_alpha = 0.004  # 0.4 pp — loose enough for alignment detail, tight enough to catch a bug
        tol_t = 0.15
        check(
            f"{label} alpha",
            abs(stats["alpha_ann"] - exp["alpha_ann"]) < tol_alpha,
            f"independent {stats['alpha_ann']:+.3%}/yr vs published {exp['alpha_ann']:+.3%}",
        )
        check(
            f"{label} alpha_t",
            abs(stats["alpha_t"] - exp["alpha_t"]) < tol_t,
            f"independent {stats['alpha_t']:.2f} vs published {exp['alpha_t']:.2f}",
        )
        check(
            f"{label} sharpe",
            abs(stats["sharpe"] - exp["sharpe"]) < 0.08,
            f"independent {stats['sharpe']:.2f} vs published {exp['sharpe']:.2f}",
        )
        notes.append(
            f"{label}: n={stats['n']}, beta={stats['beta']:.2f}, HAC(5) t={ols_alpha_t(net, bench_all.reindex(net.index), lags=5)['alpha_t']:.2f}"
        )

    dev = results["DEV_1971_2000"]
    kurt_free = deflated_sharpe_independent(dev["sharpe"], 1, dev["n"], 0.0, 3.0)
    dsr11 = deflated_sharpe_independent(dev["sharpe"], 11, dev["n"], 0.0, 3.0)
    check("DSR at 1 trial is ~1.0", kurt_free > 0.99, f"{kurt_free:.4f}")
    check("DSR at 11 trials near published 0.962", abs(dsr11 - 0.962) < 0.03, f"independent {dsr11:.3f} vs published 0.962")
    return results


# --------------------------------------------------------------------------- 6. sensitivity


def audit_sensitivities(gold: pd.Series, dxy: pd.Series, y10: pd.Series) -> None:
    print("\n=== 6. sensitivities the scorecard does not print")
    price = gold
    bench = price.pct_change()
    cost_bps_at = price.map(lambda p: cost_per_side_bps(0.20, 3.50, 100.0, 0.05, float(p)))
    sig = build_signal(dxy, y10, pd.DatetimeIndex(price.index))

    rows = []
    for lag in (0, 1, 2):
        for label, (lo, hi) in WINDOWS.items():
            mask = (price.index >= lo) & (price.index <= hi)
            p = price[mask]
            net = backtest(p, sig.reindex(p.index), cost_bps_at.reindex(p.index), lag=lag)
            st = ols_alpha_t(net, bench.reindex(net.index), lags=0)
            rows.append({"lag": lag, "window": label, "alpha": st["alpha_ann"], "t": st["alpha_t"]})
    df = pd.DataFrame(rows)
    print("  implementation delay (days):")
    for label in WINDOWS:
        a0, a1, a2 = (df[(df.window == label) & (df.lag == k)]["alpha"].iloc[0] for k in (0, 1, 2))
        t0, t1, t2 = (df[(df.window == label) & (df.lag == k)]["t"].iloc[0] for k in (0, 1, 2))
        print(f"    {label:16s} lag0 {a0:+.2%} (t {t0:4.2f})   lag1 {a1:+.2%} (t {t1:4.2f})   lag2 {a2:+.2%} (t {t2:4.2f})")

    dev1 = df[(df.window == "DEV_1971_2000") & (df.lag == 1)].iloc[0]
    check(
        "DEV survives a one-day implementation delay",
        dev1["t"] >= 2.5,
        f"lag-1 DEV alpha {dev1['alpha']:+.2%}, t {dev1['t']:.2f} (gate 2.5)",
    )
    test1 = df[(df.window == "TEST_2011_2019") & (df.lag == 1)].iloc[0]
    print(f"    TEST at lag 1: {test1['alpha']:+.2%} (t {test1['t']:.2f})")

    # Zero-cost, to show what share of the result costs consume.
    print("  zero-cost vs realistic cost (DEV):")
    mask = (price.index >= WINDOWS["DEV_1971_2000"][0]) & (price.index <= WINDOWS["DEV_1971_2000"][1])
    p = price[mask]
    for nm, cc in (("zero", False), ("realistic", True)):
        net = backtest(p, sig.reindex(p.index), cost_bps_at.reindex(p.index), charge_costs=cc)
        st = ols_alpha_t(net, bench.reindex(net.index), lags=0)
        print(f"    {nm:10s} {st['alpha_ann']:+.2%}/yr  t {st['alpha_t']:.2f}")


def main() -> int:
    print("Independent audit of XL-001 (no shared code with qts.research.edgelab)")
    audit_costs()
    gold, dxy, y10 = load_raw()
    print(f"\n  data: gold {gold.index.min().date()}..{gold.index.max().date()} (n={len(gold)}), "
          f"DXY {dxy.index.min().date()}..{dxy.index.max().date()}, "
          f"10y {y10.index.min().date()}..{y10.index.max().date()}")
    audit_signal_timing(gold, dxy, y10)
    results = audit_backtest(gold, dxy, y10)
    audit_sensitivities(gold, dxy, y10)

    print("\n=== notes worth carrying forward")
    for n in notes:
        print(f"  - {n}")

    out = Path("data/research/experiments")
    out.mkdir(parents=True, exist_ok=True)
    (out / "xl001_independent_audit.json").write_text(
        json.dumps({"results": {k: {kk: float(vv) for kk, vv in v.items()} for k, v in results.items()},
                    "notes": notes, "failures": failures}, indent=2)
    )
    print(f"\n{'AUDIT PASSED' if not failures else 'AUDIT FAILED'}: {len(failures)} failing check(s)")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
