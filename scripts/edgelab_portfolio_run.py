"""Round 17: does regime-aware allocation beat simply holding less?

This is the question the master specification asks and the programme has never
answered. Rounds 1-16 tested whether any *signal* beats buy-and-hold. Nobody tested
whether the system around the signals — regime eligibility, volatility targeting,
no-trade states — produces a better risk-adjusted result than the same signals held
statically.

The trap is obvious and must be closed explicitly. Volatility targeting cuts
exposure when volatility rises. That mechanically cuts drawdown **and** return, and
on a risk-adjusted basis it can look like skill while doing nothing but holding
less. So every configuration is compared against a control scaled to the *same
average exposure*:

    A  buy & hold
    B  static equal-weight blend of all 21 signals   (no regime, no scaling)
    C  B gated by regime eligibility                 (no scaling)
    D  B scaled by volatility target                 (no regime)
    E  full system: eligibility + volatility target + no-trade state
    F  C scaled by a CONSTANT chosen so its average position equals E's
       <-- isolates the volatility-timing decision
    G  B scaled by a CONSTANT chosen so its average position equals E's
       <-- isolates the whole regime + volatility layer

The first version of this script built F by scaling the *raw blend* by E's average
position, which matches the wrong quantity: E's average position is
``average(gross_target x vol_scale)``, not ``average(blend) x k``, so the control was
holding roughly a third of E's risk. A control that is not exposure-matched cannot
test anything. F and G are now scaled from the same object they are compared against.

E only earns the word "intelligent" if it beats F and G. Otherwise the honest
description is "de-risked", and the report says exactly that.

Windows are chronological and unchanged from rounds 12-14. Every position change is
charged at `ecn_realistic`, so the turnover that volatility targeting creates is
paid for rather than assumed away.
"""

from __future__ import annotations

import json
import warnings
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from qts.research.edgelab import CostModel, alpha_decomposition, benchmark_returns, hac_alpha, run_vector
from qts.research.edgelab.longgold import LONG_BOUNDS, load_long_gold, long_specs
from qts.research.edgelab.portfolio import AllocationConfig, allocate
from qts.research.edgelab.quantity import quantity_specs
from qts.research.edgelab.regime import RegimeConfig, classify

warnings.filterwarnings("ignore", category=RuntimeWarning)

OUT = Path("data/research/experiments")
BPY = 252.0
BLOCK = 20
REPS = 1000
SEED = 20261021


def _bars(close: pd.Series) -> pd.DataFrame:
    out = pd.DataFrame({"open": close, "high": close, "low": close, "close": close}, index=close.index)
    out["volume"] = 0.0
    return out


def catalogue(bars: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str]]:
    sigs, fams = {}, {}
    for spec in long_specs():
        sigs[spec.name] = spec.positions(bars)
        fams[spec.name] = spec.family
    for name, fn in quantity_specs().items():
        sigs[name] = fn(bars)
        fams[name] = "quantity"
    df = pd.DataFrame(sigs).fillna(0.0)
    return df.loc[:, df.abs().sum() > 0], fams


def metrics(bars: pd.DataFrame, pos: pd.Series, cost: CostModel, label: str) -> dict:
    r = run_vector(bars, pos.reindex(bars.index).fillna(0.0), cost, name=label, family="portfolio", bars_per_year=BPY, keep_equity=True)
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
        "exposure": r.exposure,
        "avg_size": float(pos.reindex(bars.index).fillna(0.0).abs().mean()),
        "net_returns": r.net_returns,
    }


def sharpe_diff_test(a: pd.Series, b: pd.Series, reps: int = REPS, block: int = BLOCK, seed: int = SEED) -> dict:
    """Block bootstrap of Sharpe(a) - Sharpe(b), paired in time."""
    pair = pd.concat([a.rename("a"), b.rename("b")], axis=1).dropna()
    x, y = pair["a"].to_numpy(), pair["b"].to_numpy()
    n = x.size

    def sh(v: np.ndarray) -> float:
        s = v.std(ddof=1)
        return float(v.mean() / s * np.sqrt(BPY)) if s > 0 else float("nan")

    obs = sh(x) - sh(y)
    rng = np.random.default_rng(seed)
    nb = int(np.ceil(n / block))
    diffs = np.empty(reps)
    for i in range(reps):
        starts = rng.integers(0, n, size=nb)
        idx = ((starts[:, None] + np.arange(block)) % n).ravel()[:n]
        diffs[i] = sh(x[idx]) - sh(y[idx])
    lo, hi = np.quantile(diffs, [0.025, 0.975])
    return {"sharpe_diff": obs, "ci_lo": float(lo), "ci_hi": float(hi), "p_two_sided": float(2 * min((diffs <= 0).mean(), (diffs >= 0).mean()))}


def main() -> int:
    cost = CostModel.realistic_ecn()
    bars_all = load_long_gold()
    sigs, fams = catalogue(bars_all)
    regimes = classify(bars_all, RegimeConfig())
    alloc = allocate(sigs, regimes, fams, AllocationConfig())

    print(f"catalogue {sigs.shape[1]} signals | {bars_all.index.min().date()} .. {bars_all.index.max().date()}")
    print(f"regime mix: {regimes['regime'].value_counts(normalize=True).round(3).to_dict()}")
    print(f"cost {cost.name} {cost.per_side_bps():.3f} bps/side (ASSUMED), charged on every position change\n")

    blend = sigs.mean(axis=1).clip(0.0, 1.0)
    rows, series = [], {}
    for label, (lo, hi) in LONG_BOUNDS.items():
        sub = bars_all.loc[lo:hi]

        a = alloc.loc[lo:hi]
        e_pos = a["position"]
        c_pos = a["gross_target"].where(a["allowed"], 0.0)
        avg_e, avg_c, avg_b = float(e_pos.mean()), float(c_pos.mean()), float(blend.loc[lo:hi].mean())
        k_vol = avg_e / avg_c if avg_c > 0 else 0.0
        k_all = avg_e / avg_b if avg_b > 0 else 0.0

        configs = {
            "A_buy_hold": pd.Series(1.0, index=sub.index),
            "B_static_blend": blend.loc[lo:hi],
            "C_regime_gated": c_pos,
            "D_vol_target": (blend.loc[lo:hi] * a["vol_scale"]).clip(0.0, 1.0),
            "E_full_system": e_pos,
            # Exposure-matched controls, built from the object they are testing.
            "F_gated_const_leverage": (c_pos * k_vol).clip(0.0, 1.0),
            "G_blend_const_leverage": (blend.loc[lo:hi] * k_all).clip(0.0, 1.0),
        }

        for name, pos in configs.items():
            m = metrics(sub, pos, cost, f"{label}_{name}")
            series[(label, name)] = m.pop("net_returns")
            rows.append({"window": label, "config": name, **m})

    df = pd.DataFrame(rows)
    view = df.copy()
    for c in ("cagr", "max_dd", "alpha_ann", "exposure", "avg_size"):
        view[c] = (view[c] * 100).round(2)
    for c in ("sharpe", "calmar", "alpha_t", "alpha_t_hac", "turnover"):
        view[c] = view[c].round(3)
    pd.set_option("display.width", 240)

    for label in LONG_BOUNDS:
        print(f"--- {label}")
        print(view[view["window"] == label].drop(columns="window").to_string(index=False))
        print()

    # The decisive comparisons, both exposure-matched.
    print("Volatility timing — E vs F (same gating, same average exposure, constant vs timed):")
    decisive = []
    for label in LONG_BOUNDS:
        test = sharpe_diff_test(series[(label, "E_full_system")], series[(label, "F_gated_const_leverage")])
        decisive.append({"window": label, "vs": "F_vol_timing", **test})
        verdict = "vol timing adds" if test["p_two_sided"] < 0.05 and test["sharpe_diff"] > 0 else "no gain from vol timing"
        print(f"  {label:5s} dSharpe {test['sharpe_diff']:+.3f}  CI [{test['ci_lo']:+.3f}, {test['ci_hi']:+.3f}]  p {test['p_two_sided']:.3f}  -> {verdict}")

    print("\nWhole layer — E vs G (gating + vol timing vs the plain blend at the same risk):")
    for label in LONG_BOUNDS:
        test = sharpe_diff_test(series[(label, "E_full_system")], series[(label, "G_blend_const_leverage")])
        decisive.append({"window": label, "vs": "G_whole_layer", **test})
        verdict = "layer adds" if test["p_two_sided"] < 0.05 and test["sharpe_diff"] > 0 else "no gain from the layer"
        print(f"  {label:5s} dSharpe {test['sharpe_diff']:+.3f}  CI [{test['ci_lo']:+.3f}, {test['ci_hi']:+.3f}]  p {test['p_two_sided']:.3f}  -> {verdict}")

    # And the risk-management claim that does not require alpha.
    print("\nRisk profile vs buy & hold (the defensible product claim):")
    for label in LONG_BOUNDS:
        b = df[(df.window == label) & (df.config == "A_buy_hold")].iloc[0]
        e = df[(df.window == label) & (df.config == "E_full_system")].iloc[0]
        print(
            f"  {label:5s} maxDD {b['max_dd']:.1%} -> {e['max_dd']:.1%}  "
            f"Sharpe {b['sharpe']:.2f} -> {e['sharpe']:.2f}  "
            f"CAGR {b['cagr']:.2%} -> {e['cagr']:.2%}  "
            f"Calmar {b['calmar']:.2f} -> {e['calmar']:.2f}"
        )

    # The layer's core mechanism, tested on the asset itself with no signal at all.
    print("\nVolatility targeting on gold itself vs exposure-matched constant leverage:")
    vt_rows = []
    vol = regimes["realized_vol"]
    for target in (0.10, 0.12, 0.15, 0.20):
        for label, (lo, hi) in LONG_BOUNDS.items():
            sub = bars_all.loc[lo:hi]
            scale = (target / vol.loc[lo:hi]).clip(0.0, 1.0).fillna(0.0)
            ctl = pd.Series(float(scale.mean()), index=sub.index)
            mt = metrics(sub, scale, cost, f"{label}_vt{target}_timed")
            mc = metrics(sub, ctl, cost, f"{label}_vt{target}_const")
            vt_rows.append({"window": label, "target": target, "sharpe_timed": mt["sharpe"], "sharpe_const": mc["sharpe"],
                            "d_sharpe": mt["sharpe"] - mc["sharpe"], "dd_timed": mt["max_dd"], "dd_const": mc["max_dd"],
                            "calmar_timed": mt["calmar"], "calmar_const": mc["calmar"]})
    vt = pd.DataFrame(vt_rows)
    print(vt.round(3).to_string(index=False))
    wins = int((vt["d_sharpe"] > 0).sum())
    print(f"  vol timing improves Sharpe in {wins}/{len(vt)} target-window pairs")

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"portfolio_{stamp}.json"
    path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat(),
                "round": 17,
                "family": "portfolio_allocation",
                "signals": int(sigs.shape[1]),
                "windows": {k: list(v) for k, v in LONG_BOUNDS.items()},
                "cost_model": cost.name,
                "cost_is_measured": False,
                "allocation_config": {"target_vol": 0.12, "max_leverage": 1.0, "vol_window": 21},
                "regime_config": {"trend_window": 63, "trend_quantile": 0.70, "high_vol_quantile": 0.80, "no_trade_quantile": 0.95},
                "rows": json.loads(df.to_json(orient="records")),
                "e_vs_f": decisive,
                "vol_target_gold": json.loads(vt.to_json(orient="records")),
            },
            indent=2,
            default=str,
        )
    )
    print(f"\nartifact: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
