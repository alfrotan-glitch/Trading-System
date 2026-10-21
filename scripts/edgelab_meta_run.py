"""Round 14: does the search as a whole contain any edge at all?

The problem this answers
------------------------
Thirteen rounds, ~110 configurations, thirteen dead families. Every round applied
its own multiple-testing correction (deflated Sharpe within the round), but nobody
has ever tested the *collection*. That matters for two reasons:

* At the detection floors this programme can actually reach (SR 0.44 on 32 years of
  DEV), a genuinely real edge of SR 0.2-0.3 is invisible. Rejecting forty such
  signals one at a time is not the same experiment as asking whether the
  collection is centred on zero.
* The right correction for a search this wide is not a per-round DSR but a reality
  check on the maximum statistic — White (2000), refined by Hansen (2005). This
  script implements the White reality check directly.

Method
------
1. Put every signal the programme has built on **one** frame: the 52-year LBMA
   basis, one cost model, one lag, one set of windows. No per-family tuning.
2. For each signal, alpha is the OLS intercept of net returns on buy-and-hold —
   the same statistic every earlier round reports, so the panel is comparable.
   (An earlier version of this file used ``mean(net − benchmark)`` instead, which
   is a much harsher and non-comparable quantity: it charges a low-beta strategy
   for the beta it *didn't* take. It reported a catalogue mean of −3.4%/yr; the
   intercept-based panel is what the rest of the programme means by alpha.)
3. Test the collection: is the equal-weight blend's alpha positive beyond noise?
   The signals are strongly cross-correlated, so this is *not* 21 independent
   draws; measuring the blend directly is the honest way to ask.
4. White's reality check: under the null of zero alpha for every signal, resample
   the (benchmark, residual) pairs jointly in blocks, fix each signal's beta, and
   record the distribution of the *maximum* alpha t-statistic across all signals.
   Compare with the observed maximum.

If the reality check rejects, there is a real edge somewhere in the catalogue and
the next step is to isolate it. If it does not, further single-signal searching is
not justified, and the programme has to change what it searches over.
"""

from __future__ import annotations

import json
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
BLOCK = 20
REPS = 2000
SEED = 20261021

WINDOWS = {
    "DEV": ("1969-01-02", "2000-12-31"),
    "VAL": ("2001-01-01", "2010-12-31"),
    "TEST": ("2011-01-01", "2019-12-31"),
}


def signals(bars: pd.DataFrame) -> dict[str, tuple[str, pd.Series]]:
    """Every catalogue signal, applied once, on the same bars."""
    out: dict[str, tuple[str, pd.Series]] = {}
    for spec in long_specs():
        out[spec.name] = (spec.family, spec.positions(bars))
    for name, fn in quantity_specs().items():
        out[name] = ("quantity", fn(bars))
    return out


def net_returns(bars: pd.DataFrame, sigs: dict[str, tuple[str, pd.Series]], cost: CostModel) -> pd.DataFrame:
    """Net daily returns for every signal at the executable lag.

    ``run_vector`` applies exactly one bar of lag itself (``held[1:] = pos[:-1]``),
    so the signal is passed unchanged. Shifting here as well would impose two bars.
    """
    cols = {}
    for name, (family, pos) in sigs.items():
        r = run_vector(
            bars, pos.reindex(bars.index).fillna(0.0), cost, name=name, family=family, bars_per_year=BPY, keep_equity=True
        )
        if r.net_returns is not None:
            cols[name] = r.net_returns
    return pd.DataFrame(cols)


def _ols(y: np.ndarray, x: np.ndarray) -> tuple[float, float, np.ndarray]:
    """Return (alpha, alpha_t, residuals) for y = alpha + beta*x + e."""
    n = y.size
    xm, ym = x.mean(), y.mean()
    sxx = float(((x - xm) ** 2).sum())
    beta = float(((x - xm) * (y - ym)).sum()) / sxx
    alpha = ym - beta * xm
    resid = y - alpha - beta * x
    ssr = float(resid @ resid)
    s2 = ssr / (n - 2)
    se = np.sqrt(s2 * (1.0 / n + xm**2 / sxx))
    return alpha, alpha / se, resid


def reality_check(
    nets: dict[str, np.ndarray],
    bench: np.ndarray,
    reps: int = REPS,
    block: int = BLOCK,
    seed: int = SEED,
) -> dict:
    """White's reality check on the maximum alpha t-statistic.

    Observed statistics come from the *actual* net returns, alpha included. The
    bootstrap world is rebuilt with alpha forced to zero — ``beta * benchmark* +
    residual*`` — so the null is "no signal in the catalogue has an intercept".
    """
    names = list(nets)
    k = len(names)
    n = bench.size
    betas = np.zeros(k)
    e_mat = np.empty((n, k))
    obs = np.full(k, np.nan)
    for j, m in enumerate(names):
        y = nets[m]
        # Slope and residual from the observed fit; observed t from the real series.
        _a, t_obs, e = _ols(y, bench)
        obs[j] = t_obs
        betas[j] = float(np.polyfit(bench, y, 1)[0])
        e_mat[:, j] = e
    valid = np.isfinite(obs)
    obs_max = float(np.nanmax(obs))

    rng = np.random.default_rng(seed)
    max_null = np.full(reps, -np.inf)
    done = 0
    chunk = 100
    while done < reps:
        m = min(chunk, reps - done)
        nb = int(np.ceil(n / block))
        starts = rng.integers(0, n, size=(m, nb))
        offs = np.arange(block)[None, None, :]
        idx = ((starts[:, :, None] + offs) % n).reshape(m, nb * block)[:, :n]
        bench_star = bench[idx]  # (m, n)
        xm = bench_star.mean(axis=1, keepdims=True)
        sxx = ((bench_star - xm) ** 2).sum(axis=1)
        block_max = np.full(m, -np.inf)
        for j in range(k):
            if not valid[j]:
                continue
            y_star = betas[j] * bench_star + e_mat[:, j][idx]
            ym = y_star.mean(axis=1, keepdims=True)
            beta = ((bench_star - xm) * (y_star - ym)).sum(axis=1) / sxx
            alpha = ym[:, 0] - beta * xm[:, 0]
            resid = y_star - alpha[:, None] - beta[:, None] * bench_star
            ssr = (resid**2).sum(axis=1)
            se = np.sqrt((ssr / (n - 2)) * (1.0 / n + xm[:, 0] ** 2 / sxx))
            block_max = np.maximum(block_max, alpha / se)
        max_null[done : done + m] = block_max
        done += m

    return {
        "observed_max_t": obs_max,
        "best_signal": names[int(np.nanargmax(obs))],
        "p_value": float(np.mean(max_null >= obs_max)),
        "null_quantiles": {str(q): float(np.quantile(max_null, q)) for q in (0.5, 0.9, 0.95, 0.99)},
        "reps": reps,
        "block": block,
        "seed": seed,
    }


def main() -> int:
    cost = CostModel.realistic_ecn()
    bars_all = load_long_gold()
    sigs = signals(bars_all)
    print(f"catalogue: {len(sigs)} signals on {bars_all.index.min().date()} .. {bars_all.index.max().date()}")
    print(f"cost {cost.name} {cost.per_side_bps():.3f} bps/side (ASSUMED) | lag 1 bar | 52y basis\n")

    rows = []
    dev_nets: pd.DataFrame | None = None
    dev_bench: pd.Series | None = None
    for label, (lo, hi) in WINDOWS.items():
        sub = bars_all.loc[lo:hi]
        nets = net_returns(sub, sigs, cost)
        bench = benchmark_returns(sub).reindex(nets.index)
        if label == "DEV":
            dev_nets, dev_bench = nets, bench
        for name in nets.columns:
            pair = pd.concat([nets[name].rename("net"), bench.rename("bench")], axis=1).dropna()
            st = alpha_decomposition(pair["net"], pair["bench"], BPY)
            try:
                h_t = float(hac_alpha(pair["net"], pair["bench"], BPY, lags=5)["alpha_t"])
            except ValueError:
                # A rule that never takes a position in this window has a
                # degenerate regression; NaN is the honest answer.
                h_t = float("nan")
            rows.append(
                {
                    "name": name,
                    "family": sigs[name][0],
                    "window": label,
                    "alpha_ann": float(st["alpha_ann"]),
                    "t": float(st["alpha_t"]),
                    "t_hac": h_t,
                    "n": int(len(pair)),
                }
            )

    panel = pd.DataFrame(rows)
    wide_a = panel.pivot(index="name", columns="window", values="alpha_ann")
    wide_t = panel.pivot(index="name", columns="window", values="t")
    view = pd.concat([wide_a.mul(100).round(2).add_suffix("_a%"), wide_t.round(2).add_suffix("_t")], axis=1)
    view["family"] = panel.groupby("name")["family"].first()
    print(view.sort_values(("DEV_a%"), ascending=False).to_string())

    assert dev_nets is not None and dev_bench is not None
    pair_all = pd.concat([dev_nets.mean(axis=1).rename("net"), dev_bench.rename("bench")], axis=1).dropna()
    blend = alpha_decomposition(pair_all["net"], pair_all["bench"], BPY)
    try:
        blend_h_t = float(hac_alpha(pair_all["net"], pair_all["bench"], BPY, lags=5)["alpha_t"])
    except ValueError:
        blend_h_t = float("nan")

    # Common sample across the whole panel, then the reality check on DEV.
    common = dev_nets.dropna(how="any").copy()
    bench_common = dev_bench.reindex(common.index).dropna()
    common = common.loc[bench_common.index]
    bench_vec = bench_common.to_numpy()
    nets_vec = {c: common[c].to_numpy() for c in common.columns if common[c].abs().sum() > 0}
    rc = reality_check(nets_vec, bench_vec)

    print(f"\nDEV panel: {len(wide_a)} signals")
    print(f"  equal-weight blend alpha  : {blend['alpha_ann'] * 100:+.2f}%/yr  (t {blend['alpha_t']:.2f}, HAC {blend_h_t:.2f})")
    print(f"  mean standalone alpha     : {wide_a['DEV'].mean() * 100:+.2f}%/yr")
    print(f"  positive on DEV           : {int((wide_a['DEV'] > 0).sum())}/{len(wide_a)}")
    print(
        f"  positive on DEV+VAL+TEST  : {int(((wide_a > 0).all(axis=1)).sum())}/{len(wide_a)}"
        f"  (chance if independent: {len(wide_a) * 0.125:.1f})"
    )
    print("\nWhite reality check (DEV, block bootstrap, null = zero alpha for every signal):")
    print(f"  observed max t : {rc['observed_max_t']:.2f}  ({rc['best_signal']})")
    print(f"  null 95% / 99% : {rc['null_quantiles']['0.95']:.2f} / {rc['null_quantiles']['0.99']:.2f}")
    print(f"  p-value        : {rc['p_value']:.3f}   ({rc['reps']} reps, block {rc['block']})")
    verdict = "REJECT — an edge exists somewhere in the catalogue" if rc["p_value"] < 0.05 else "DO NOT REJECT — no evidence of edge"
    print(f"  verdict        : {verdict}")

    # Cost sensitivity: how much of the catalogue's apparent edge is the cost
    # assumption? Round 3's survivor list was built on the cheaper default model.
    print("\nCost sensitivity on DEV (max t, and count clearing t>=2.5):")
    cost_rows = {}
    for cname, cmodel in (("default", CostModel()), ("ecn_realistic", cost)):
        sub = bars_all.loc[WINDOWS["DEV"][0] : WINDOWS["DEV"][1]]
        nets_c = net_returns(sub, sigs, cmodel)
        bench_c = benchmark_returns(sub).reindex(nets_c.index)
        ts = []
        for name in nets_c.columns:
            pair = pd.concat([nets_c[name].rename("net"), bench_c.rename("bench")], axis=1).dropna()
            if float(pair["net"].abs().sum()) == 0.0 or len(pair) < 100:
                continue
            try:
                ts.append(float(alpha_decomposition(pair["net"], pair["bench"], BPY)["alpha_t"]))
            except (ValueError, ZeroDivisionError):
                continue
        cost_rows[cname] = {"max_t": max(ts), "n_clearing_2.5": int(sum(t >= 2.5 for t in ts)), "bps_per_side": cmodel.per_side_bps()}
        print(f"  {cname:14s} {cmodel.per_side_bps():.3f} bps/side -> max t {max(ts):.2f}, clearing 2.5: {sum(t >= 2.5 for t in ts)}/{len(ts)}")

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"meta_{stamp}.json"
    path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat(),
                "round": 14,
                "family": "pooled_evidence",
                "signals": len(wide_a),
                "windows": WINDOWS,
                "cost_model": cost.name,
                "cost_is_measured": False,
                "panel": json.loads(panel.to_json(orient="records")),
                "blend_alpha_dev": float(blend["alpha_ann"]),
                "blend_t_dev": float(blend["alpha_t"]),
                "blend_t_hac_dev": blend_h_t,
                "reality_check": rc,
                "cost_sensitivity": cost_rows,
                "verdict": verdict,
            },
            indent=2,
            default=str,
        )
    )
    print(f"\nartifact: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
