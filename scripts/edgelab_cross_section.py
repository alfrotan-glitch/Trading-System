"""Replicate gold findings on an independent price source and a cross-section.

Two pre-specified questions, both read on data that is NOT the XAUUSD holdout:

1. **Cross-source.** `tsmom_d5` earned +8.26%/yr alpha (t=2.11) on BaseMax gold
   over DEV. Does the same rule, on the same calendar window, earn alpha on a
   different broker's gold series? A finding that exists on one feed and not on
   another belongs to the feed.

2. **Cross-section.** Do these rule families have any consistent sign across 12
   instruments, or is the gold result one draw from a zero-mean distribution?

Only three configurations are tested, fixed before the run. Running all 52 here
would be the multiple-testing trap this whole harness exists to avoid.

Power warning, stated up front rather than discovered afterwards: the shared
window gives ~6.1 years inside DEV, so the per-instrument detection floor is
`2.5/sqrt(6.1) = 1.01` Sharpe. Individually these tests can barely see anything.
A null result here is therefore **inconclusive, not evidence of absence** — and
that limitation is reported rather than buried.
"""

from __future__ import annotations

import argparse
import json
import warnings
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from qts.research.edgelab import (
    CostModel,
    StrategySpec,
    alpha_decomposition,
    benchmark_returns,
    load_bars,
    resample,
    run_vector,
)
from qts.research.edgelab.crosssection import INSTRUMENTS, load_panel
from qts.research.edgelab.power import detection_summary
from qts.research.edgelab.specs import build_specs

warnings.filterwarnings("ignore", category=RuntimeWarning)

OUT = Path("data/research/experiments")

# Fixed before running. Three families, one configuration each.
PROBES = ("tsmom_d5", "ma_50_200", "volman_15_d60")


def probe_specs() -> list[StrategySpec]:
    """The three probes, taken from the canonical catalogue, not redefined."""
    catalogue = {s.name: s for s in build_specs()}
    return [catalogue[name] for name in PROBES]


def measure(bars: pd.DataFrame, spec: StrategySpec, cost: CostModel, bpy: float) -> dict | None:
    """Alpha vs buy-and-hold for one spec on one instrument."""
    if len(bars) < 400:
        return None
    try:
        pos = spec.positions(bars)
        if float(np.abs(pos.to_numpy()).sum()) == 0:
            return None
        r = run_vector(
            bars,
            pos,
            cost,
            name=spec.name,
            family=spec.family,
            params=spec.params,
            bars_per_year=bpy,
            keep_equity=True,
        )
    except Exception as exc:  # a broken instrument is a finding, not a crash
        return {"instrument": None, "error": f"{type(exc).__name__}: {exc}"}
    if r.net_returns is None:
        return None
    stats = alpha_decomposition(r.net_returns, benchmark_returns(bars), bpy)
    if not stats:
        return None
    return {
        "bars": int(len(bars)),
        "trades": int(r.trades),
        "sharpe": float(r.sharpe),
        "cagr": float(r.cagr),
        "alpha_ann": float(stats["alpha_ann"]),
        "alpha_t": float(stats["alpha_t"]),
        "beta": float(stats["beta"]),
    }


def sign_test(positives: int, total: int) -> float:
    """Two-sided binomial p-value against a fair coin, normal approximation."""
    if total == 0:
        return 1.0
    from math import erf, sqrt

    z = (positives - total / 2) / sqrt(total / 4)
    return float(1 - erf(abs(z) / sqrt(2)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--end", default="2018-12-31", help="do not extend past DEV")
    args = ap.parse_args()

    cost = CostModel()
    bpy = 252.0
    report: dict = {
        "generated_at": datetime.now(UTC).isoformat(),
        "window_end": args.end,
        "probes": list(PROBES),
        "cost": cost.name,
        "cross_source": {},
        "cross_section": {},
    }

    # ---------------------------------------------------------------- cross-source
    print("=== Cross-source: XAUUSD on two independent brokers, same window ===")
    ej = load_panel(end=args.end)["XAUUSD"]
    ej_d1 = resample(ej, "D1")
    bm = load_bars("basemax")
    bm = bm[(bm.index >= ej.index.min().tz_localize("UTC")) & (bm.index <= pd.Timestamp(args.end, tz="UTC"))]
    bm_d1 = resample(bm, "D1")

    for label, bars in (("basemax", bm_d1), ("ejtrader", ej_d1)):
        report["cross_source"][label] = {
            "span": [str(bars.index.min().date()), str(bars.index.max().date())],
            "bars": int(len(bars)),
            "results": {},
        }
        for spec in probe_specs():
            m = measure(bars, spec, cost, bpy)
            if m:
                report["cross_source"][label]["results"][spec.name] = m

    for spec in PROBES:
        row = []
        for label in ("basemax", "ejtrader"):
            m = report["cross_source"][label]["results"].get(spec)
            row.append(
                f"{label}: alpha {m['alpha_ann']*100:+.2f}%/yr t={m['alpha_t']:+.2f} SR={m['sharpe']:+.3f}"
                if m
                else f"{label}: n/a"
            )
        print(f"  {spec:15} " + " | ".join(row))

    agree = sum(
        1
        for spec in PROBES
        if _sign(report["cross_source"]["basemax"]["results"].get(spec)) == _sign(report["cross_source"]["ejtrader"]["results"].get(spec))
    )
    report["cross_source"]["sign_agreement"] = f"{agree}/{len(PROBES)}"

    # ------------------------------------------------------------ sub-period stability
    # The cross-source run above covers 2012-2018 and returns a much weaker alpha
    # than the full 2004-2018 DEV window. That is a stability question, so answer
    # it directly: is the effect present in both halves, or concentrated in one?
    print("\n=== Sub-period stability (BaseMax D1, full DEV split in half) ===")
    full = load_bars("basemax")
    full = full[full.index <= pd.Timestamp("2018-12-31", tz="UTC")]
    halves = {
        "2004-2011": full[full.index < pd.Timestamp("2012-01-01", tz="UTC")],
        "2012-2018": full[full.index >= pd.Timestamp("2012-01-01", tz="UTC")],
    }
    stability: dict = {}
    for label, chunk in halves.items():
        bars = resample(chunk, "D1")
        stability[label] = {spec.name: measure(bars, spec, cost, bpy) for spec in probe_specs()}
    for spec in PROBES:
        cells = []
        for label in halves:
            m = stability[label].get(spec)
            cells.append(f"{label}: {m['alpha_ann']*100:+6.2f}%/yr t={m['alpha_t']:+.2f}" if m else f"{label}: n/a")
        print(f"  {spec:15} " + " | ".join(cells))
    report["sub_period_stability"] = stability

    # --------------------------------------------------------------- cross-section
    print("\n=== Cross-section: same rules, 12 instruments, pre-holdout only ===")
    panel = load_panel(end=args.end)
    grid: dict[str, dict] = {}
    for name in INSTRUMENTS:
        if name not in panel:
            continue
        bars = resample(panel[name], "D1")
        grid[name] = {}
        for spec in probe_specs():
            m = measure(bars, spec, cost, bpy)
            if m:
                grid[name][spec.name] = m
    report["cross_section"] = grid

    print(f"{'instrument':10} " + " ".join(f"{p:>18}" for p in PROBES))
    for name in INSTRUMENTS:
        if name not in grid:
            continue
        cells = []
        for p in PROBES:
            m = grid[name].get(p)
            cells.append(f"{m['alpha_ann']*100:+7.2f}% t{m['alpha_t']:+5.2f}" if m else f"{'n/a':>18}")
        print(f"{name:10} " + " ".join(f"{c:>18}" for c in cells))

    summary = {}
    for p in PROBES:
        vals = [grid[n][p] for n in grid if p in grid[n]]
        pos = sum(1 for v in vals if v["alpha_ann"] > 0)
        summary[p] = {
            "instruments": len(vals),
            "positive_alpha": pos,
            "median_alpha_ann": float(np.median([v["alpha_ann"] for v in vals])) if vals else 0.0,
            "median_alpha_t": float(np.median([v["alpha_t"] for v in vals])) if vals else 0.0,
            "sign_test_p": sign_test(pos, len(vals)),
        }
        print(
            f"  {p:15} positive in {pos}/{len(vals)} instruments, "
            f"median alpha {summary[p]['median_alpha_ann']*100:+.2f}%/yr, "
            f"sign-test p={summary[p]['sign_test_p']:.3f}"
        )
    report["cross_section_summary"] = summary
    report["power"] = detection_summary(len(bm_d1), bpy)
    report["caveats"] = [
        "Cross-section instruments share dominant FX factors; effective N is far "
        "below 12, so sign-test p-values are optimistic upper bounds.",
        "~6.1 years inside DEV gives a per-instrument detection floor near SR 1.0: "
        "a null here is inconclusive, not evidence of absence.",
        "The panel uses broker server time, not UTC; daily boundaries differ by a "
        "few hours from the BaseMax series.",
    ]

    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = OUT / f"cross_section_{stamp}.json"
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nwritten -> {path}")


def _sign(m: dict | None) -> int:
    if not m:
        return 0
    return 1 if m["alpha_ann"] > 0 else (-1 if m["alpha_ann"] < 0 else 0)


if __name__ == "__main__":
    main()
