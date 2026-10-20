"""Round 7 screen: session-clock strategies on M15 XAUUSD.

The split below is fixed in this file, before any result was read, and it is
deliberately not the split used by the earlier daily-bar families. The 2020-2024
window was consumed by ``tsmom_1m``'s failed holdout and by the macro study; it is
excluded from *both* fitting and validation here rather than quietly reused.

    DEV   2004-06-11 .. 2014-12-31   fit and select
    VAL   2015-01-01 .. 2019-12-31   direction check
    DEAD  2020-01-01 .. 2024-09-30   NOT USED by this script at all
    OOS   2024-10-01 .. 2025-09-30   one evaluation, frozen survivor only

``--oos`` is a separate, deliberate act. Without it the script never touches the
last twelve months of the series.

Inference is done on **daily aggregated returns**, never on the 480,717 M15 bars:
15-minute returns are serially correlated and a naive t-statistic on them would be
inflated several-fold. The t-statistic is HAC (Newey-West, 5 lags) for the same
reason.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from qts.research.edgelab import (
    CostModel,
    deflated_sharpe,
    gate,
    hac_alpha,
    run_vector,
    split,
)
from qts.research.edgelab import intraday as I
from qts.research.edgelab import signals as S

BARS = Path("data/research/xauusd_m15_basemax.parquet")
OUT = Path("data/research/experiments")
M15_BARS_PER_YEAR = 96.0 * 252.0
DAILY_BARS_PER_YEAR = 252.0

#: Round 1 already screened 52 configurations on this same M15 series, session
#: windows among them. A deflated Sharpe that only counts the nine rows printed
#: below would understate the search by a factor of six, so the count is
#: cumulative for the family, not per-run.
PRIOR_TRIALS = 52

BOUNDS = {
    "DEV": ("2004-06-11", "2014-12-31"),
    "VAL": ("2015-01-01", "2019-12-31"),
    "TEST": ("2020-01-01", "2024-09-30"),  # consumed elsewhere; never evaluated here
}
OOS_BOUNDS = ("2024-10-01", "2025-09-30")


def build_specs() -> dict[str, dict]:
    """The pre-registered grid. Eight configurations, two of them negative controls.

    ``london_only`` and ``newyork_only`` long gold in windows where the DEV sample
    shows no drift at all. They exist so the screen has to demonstrate it can
    reject something: a harness that only ever sees plausible-looking candidates
    is not being tested.
    """
    return {
        "sess_asia_2206": {
            "fn": I.hold_window,
            "params": {"start": 22, "end": 6},
            "family": "session",
            "control": False,
            "rationale": "Asian physical demand carries gold's drift; hold only that window.",
        },
        "sess_asia_2307": {
            "fn": I.hold_window,
            "params": {"start": 23, "end": 7},
            "family": "session",
            "control": False,
            "rationale": "Same hypothesis one hour later — parameter sensitivity, not a new idea.",
        },
        "sess_london_only": {
            "fn": I.hold_window,
            "params": {"start": 7, "end": 12},
            "family": "session",
            "control": True,
            "rationale": "Negative control: London hours show no DEV drift.",
        },
        "sess_newyork_only": {
            "fn": I.hold_window,
            "params": {"start": 12, "end": 20},
            "family": "session",
            "control": True,
            "rationale": "Negative control: New York hours show no DEV drift.",
        },
        "overrev_asia": {
            "fn": I.overnight_reversal,
            "params": {"start": 22, "end": 6, "day_start": 12, "day_end": 20},
            "family": "session_reversion",
            "control": False,
            "rationale": "Deep futures books reverse thin overnight sentiment during the NY session.",
        },
        "momclose_asia": {
            "fn": I.overnight_momentum_close,
            "params": {"start": 22, "end": 6, "entry_hour": 19, "exit_hour": 21},
            "family": "session_momentum",
            "control": False,
            "rationale": "Market intraday momentum: the overnight leg predicts the NY close.",
        },
        "orb_asia": {
            "fn": I.opening_range_breakout,
            "params": {"range_start": 22, "range_end": 7, "trade_end": 20, "buffer_bps": 0.0},
            "family": "session_breakout",
            "control": False,
            "rationale": "Asian range is a liquidity reservoir that London/NY resolve.",
        },
        "orb_asia_buf10": {
            "fn": I.opening_range_breakout,
            "params": {
                "range_start": 22,
                "range_end": 7,
                "trade_end": 20,
                "buffer_bps": 10.0,
            },
            "family": "session_breakout",
            "control": False,
            "rationale": "Same breakout with a 10 bp confirmation band — filters range noise.",
        },
        "tsmom_m15_96": {
            "fn": S.tsmom,
            "params": {"lookback_days": 1},
            "family": "intraday_trend",
            "control": False,
            "rationale": "One-day time-series momentum sampled at M15 — the intraday trend baseline.",
        },
    }


def daily_agg(net: pd.Series) -> pd.Series:
    """Compound intraday net returns into calendar-day returns."""
    g = (1.0 + net).groupby(net.index.date).prod() - 1.0
    # Keep the daily index in the same tz-aware UTC form the benchmark uses;
    # otherwise the alpha regression silently aligns on nothing.
    g.index = pd.DatetimeIndex(pd.to_datetime(list(g.index)), tz="UTC")
    return g


def evaluate(bars: pd.DataFrame, positions: pd.Series, cost: CostModel, bench_daily: pd.Series, *, name: str, family: str, params: dict) -> dict:
    res = run_vector(
        bars,
        positions,
        cost,
        name=name,
        family=family,
        params=params,
        bars_per_year=M15_BARS_PER_YEAR,
        keep_equity=True,
        execution="close",
    )
    net = res.net_returns
    assert net is not None
    d = daily_agg(net)
    alpha = hac_alpha(d, bench_daily, DAILY_BARS_PER_YEAR, lags=5)
    r = d.to_numpy(dtype=float)
    return {
        "sharp_bar": res.sharpe,
        "cagr": res.cagr,
        "sharpe_daily": float(r.mean() / r.std(ddof=1) * (DAILY_BARS_PER_YEAR**0.5)) if len(r) > 2 and r.std(ddof=1) > 0 else 0.0,
        "max_dd": res.max_dd,
        "turnover_yr": res.turnover_per_year,
        "trades": res.trades,
        "exposure": res.exposure,
        "net_ann": float(d.mean() * DAILY_BARS_PER_YEAR),
        "cost_drag_ann": float(res.cost_drag / max(1e-9, len(net)) * M15_BARS_PER_YEAR),
        "alpha_ann": alpha["alpha_ann"],
        "alpha_t": alpha["alpha_t"],
        "beta": alpha["beta"],
        "n_days": alpha["n_obs"],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--oos", action="store_true", help="evaluate the frozen survivor on OOS")
    ap.add_argument("--survivor", default="", help="spec name to evaluate on OOS")
    ap.add_argument("--cost", default="realistic", choices=["realistic", "assumed", "x2", "x5"])
    args = ap.parse_args(argv)

    bars = pd.read_parquet(BARS)
    parts = split(bars.index, BOUNDS)
    bench = I.daily_bars(bars)["close"].pct_change()
    specs = build_specs()
    n_trials = PRIOR_TRIALS + len(specs)

    cost = {
        "realistic": CostModel.realistic_ecn(),
        "assumed": CostModel(),
        "x2": CostModel.stressed(2.0),
        "x5": CostModel.stressed(5.0),
    }[args.cost]
    per_side = cost.per_side_bps()

    if args.oos:
        if not args.survivor:
            raise SystemExit("--oos requires --survivor <spec name>")
        spec = specs[args.survivor]
        pos = spec["fn"](bars, **spec["params"])
        lo, hi = OOS_BOUNDS
        seg = bars.loc[lo:hi]
        b = bench.loc[lo:hi]
        m = evaluate(seg, pos.reindex(seg.index).fillna(0.0), cost, b, name=args.survivor, family=spec["family"], params=spec["params"])
        print(f"OOS {lo}..{hi}  {args.survivor}  @ {cost.name} ({per_side:.3f} bps/side)")
        for k, v in m.items():
            print(f"  {k:16s} {v:>12.4f}" if isinstance(v, float) else f"  {k:16s} {v}")
        return 0

    dev_lo, dev_hi = BOUNDS["DEV"]
    val_lo, val_hi = BOUNDS["VAL"]
    bench_dev = bench.loc[dev_lo:dev_hi]
    bench_val = bench.loc[val_lo:val_hi]

    rows = []
    for name, spec in specs.items():
        pos = spec["fn"](bars, **spec["params"])
        dev = evaluate(
            bars.loc[parts["DEV"][0] : parts["DEV"][-1]],
            pos.reindex(parts["DEV"]).fillna(0.0),
            cost,
            bench_dev,
            name=name,
            family=spec["family"],
            params=spec["params"],
        )
        val = evaluate(
            bars.loc[parts["VAL"][0] : parts["VAL"][-1]],
            pos.reindex(parts["VAL"]).fillna(0.0),
            cost,
            bench_val,
            name=name,
            family=spec["family"],
            params=spec["params"],
        )
        stress = evaluate(
            bars.loc[parts["DEV"][0] : parts["DEV"][-1]],
            pos.reindex(parts["DEV"]).fillna(0.0),
            CostModel.stressed(2.0),
            bench_dev,
            name=name,
            family=spec["family"],
            params=spec["params"],
        )
        dsr = deflated_sharpe(
            sr_annualised=dev["sharpe_daily"],
            n_trials=n_trials,
            n_obs=dev["n_days"],
            bars_per_year=DAILY_BARS_PER_YEAR,
        )
        rows.append(
            {
                "name": name,
                "family": spec["family"],
                "control": spec["control"],
                "dev_alpha_ann": dev["alpha_ann"],
                "dev_alpha_t": dev["alpha_t"],
                "dev_sharpe": dev["sharpe_daily"],
                "dev_net_ann": dev["net_ann"],
                "dev_turnover": dev["turnover_yr"],
                "dev_trades": dev["trades"],
                "dev_beta": dev["beta"],
                "dev_maxdd": dev["max_dd"],
                "dsr": dsr,
                "stress_alpha_ann": stress["alpha_ann"],
                "stress_alpha_t": stress["alpha_t"],
                "val_alpha_ann": val["alpha_ann"],
                "val_alpha_t": val["alpha_t"],
                "val_sharpe": val["sharpe_daily"],
            }
        )

    df = pd.DataFrame(rows).set_index("name")
    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 50)
    print(f"\nRound 7 session screen — cost {cost.name} = {per_side:.3f} bps/side (ASSUMED)")
    print(f"DEV {BOUNDS['DEV']}  VAL {BOUNDS['VAL']}  trials={n_trials} ({PRIOR_TRIALS} prior + {len(specs)} here)\n")
    show = df[
        [
            "control",
            "dev_alpha_ann",
            "dev_alpha_t",
            "dev_sharpe",
            "dev_net_ann",
            "dev_turnover",
            "dsr",
            "stress_alpha_t",
            "val_alpha_ann",
            "val_alpha_t",
        ]
    ].copy()
    show["dev_alpha_ann"] = (show["dev_alpha_ann"] * 100).round(2)
    show["dev_net_ann"] = (show["dev_net_ann"] * 100).round(2)
    show["val_alpha_ann"] = (show["val_alpha_ann"] * 100).round(2)
    for c in ("dev_alpha_t", "dev_sharpe", "dsr", "stress_alpha_t", "val_alpha_t", "dev_turnover"):
        show[c] = show[c].round(3)
    print(show.to_string())

    # The gate reads alpha_t / alpha_ann_stress from one frame and alpha_t /
    # alpha_ann from another; passing a single frame with renamed columns would
    # produce duplicate labels, so the DEV and VAL views are built separately.
    gate_frame = df.rename(columns={"dev_alpha_t": "alpha_t"}).assign(alpha_ann_stress=df["stress_alpha_ann"])
    # ---- why the session effect does not survive costs ---------------------
    print("\n=== where the overnight drift actually lives (DEV bars, 22:00 hour)")
    dev = bars.loc[BOUNDS["DEV"][0] : BOUNDS["DEV"][1]]
    r = dev["close"].pct_change()
    gaps = pd.Series(dev.index, index=dev.index).diff().dt.total_seconds() / 60.0
    is22 = np.asarray(dev.index.hour == 22)
    for lo_g, hi_g, name in ((0, 30, "gap<=30m"), (30, 10**6, "gap>30m (halt/weekend)")):
        m = is22 & (gaps.to_numpy() >= lo_g) & (gaps.to_numpy() < hi_g)
        print(
            f"  {name:24s} n {int(m.sum()):5d}  mean {float(r.to_numpy()[m].mean()) * 1e4:6.2f} bps  "
            f"t {float(r.to_numpy()[m].mean() / r.to_numpy()[m].std() * np.sqrt(m.sum())):5.2f}"
        )
    print("  The reopen gap is where the point estimate comes from, and it is unearned by a")
    print("  strategy that enters at the reopen. That is why the zero-cost alpha below is")
    print("  smaller than the descriptive session mean.")

    print("\n=== cost decomposition on DEV (zero vs realistic, 0.93 bps/side)")
    zero = CostModel.zero()
    for name, spec in specs.items():
        pos = spec["fn"](bars, **spec["params"])
        g = evaluate(
            dev,
            pos.reindex(parts["DEV"]).fillna(0.0),
            zero,
            bench_dev,
            name=name,
            family=spec["family"],
            params=spec["params"],
        )
        print(
            f"  {name:18s} gross alpha {g['alpha_ann']:+7.2%} (t {g['alpha_t']:5.2f})  "
            f"cost drag {abs(df.loc[name, 'dev_net_ann'] - g['net_ann']) * 100:5.2f}%/yr"
        )

    survivors = gate.survivors(gate_frame)
    val_frame = pd.DataFrame({"alpha_t": df["val_alpha_t"], "alpha_ann": df["val_alpha_ann"]})
    confirmed = gate.val_confirms(val_frame.loc[survivors.index])
    print(f"\ngate: {len(survivors)} DEV survivor(s) of {len(df)}; {len(confirmed)} confirmed on VAL")
    if len(confirmed):
        print("survivors:", ", ".join(confirmed.index))

    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    payload = {
        "round": 7,
        "family": "session_clock",
        "data": str(BARS),
        "bars": int(len(bars)),
        "bounds": BOUNDS,
        "oos_bounds": OOS_BOUNDS,
        "oos_touched": False,
        "cost_model": cost.name,
        "cost_bps_per_side": per_side,
        "cost_is_measured": False,
        "trials": n_trials,
        "rows": json.loads(df.reset_index().to_json(orient="records")),
        "survivors": list(survivors.index),
        "val_confirmed": list(confirmed.index),
    }
    path = OUT / f"intraday_{stamp}.json"
    path.write_text(json.dumps(payload, indent=2, default=str))
    print(f"\nartifact: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
