"""XL-001 out-of-sample holdout, using driver data that continues past 2024-05.

Round 6 left the candidate unvalidated for one reason: the dollar and the 10-year
yield both stopped on 2024-05-17, so nothing after the development sample could be
computed. Mirror-driven FRED files (see :mod:`qts.research.edgelab.fred_drivers`)
now run to 2026-10-16, which makes a **holdout** possible.

Holdout is not the same thing as forward, and this script says so out loud:

* The windows below start after 2024-05-17, the last date visible when XL-001 was
  defined and hash-pinned, so no choice in this file can have been informed by
  them. That makes them a legitimate holdout.
* They are **not** forward evidence. Forward means the observation did not exist
  when the rule was frozen; these did, and the operator simply had not fetched
  them. The append-only ledger is the only place forward observations live, and
  this script does not write to it.
* Two years cannot validate anything. At this sample length the detection floor
  (see :func:`qts.research.edgelab.power.detection_summary`) is a Sharpe well above
  one. So the pre-committed reading is:

  - holdout alpha **negative in both blocks** → the mechanism did not survive;
    XL-001 is downgraded, not merely "still pending".
  - holdout alpha **positive but not significant** → status unchanged. No upgrade.
  - no outcome here can promote the candidate; only forward observations can.

Two data caveats are measured rather than asserted:

1. The dollar leg swaps DXY for DTWEXBGS. The swap is quantified on the overlap,
   and XL-001 is re-run on that overlap under both indices before the swap is
   used for anything.
2. Gold post-2024 comes from M15 feeds, not the LBMA fix. BaseMax's tail is
   incomplete after 2025-02 (0 bars in August 2025, 2 in September), so the
   holdout is two disjoint blocks rather than one spliced series.
"""

from __future__ import annotations

import json
import warnings
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from qts.research.edgelab import CostModel, deflated_sharpe, hac_alpha
from qts.research.edgelab.candidates import EASING_6M
from qts.research.edgelab.fred_drivers import (
    align_to_index,
    index_agreement,
    load_broad_dollar,
    load_treasury_10y,
    validate_drivers,
)
from qts.research.edgelab.intraday import daily_bars
from qts.research.edgelab.metals import gold_bars, load_metals
from qts.research.edgelab.power import detection_summary
from qts.research.edgelab.reporting import evaluate_period, strip_diagnostics

warnings.filterwarnings("ignore", category=RuntimeWarning)

OUT = Path("data/research/experiments")
BPY = 252.0
BRIDGE = ("2006-01-03", "2019-12-31")
BLOCKS = {
    "block_a_basemax": ("2024-06-01", "2025-02-28"),
    "block_b_dukascopy": ("2025-08-06", "2026-09-16"),
}
BASEMAX = Path("data/research/xauusd_m15_basemax.parquet")
VUDO = Path("data/research/xauusd_m15_vudo.parquet")


def feed_quality(bars: dict[str, pd.DataFrame]) -> dict:
    """Bars per calendar month, so an incomplete tail is visible as a number."""
    out = {}
    for name, df in bars.items():
        m = df.groupby([df.index.year, df.index.month]).size()
        out[name] = {"months": {f"{y}-{mo:02d}": int(n) for (y, mo), n in m.items()}}
    return out


def driver_frame() -> pd.DataFrame:
    """Both drivers on their own calendar, sorted and de-duplicated."""
    frame = pd.concat(
        [load_broad_dollar().rename("dxy"), load_treasury_10y().rename("y10")], axis=1, sort=True
    ).sort_index()
    if frame.index.tz is None:
        frame.index = frame.index.tz_localize("UTC")
    frame = frame[~frame.index.duplicated(keep="first")]
    return frame.dropna()


def run_window(bars: pd.DataFrame, sig_all: pd.Series, lo: str, hi: str, label: str) -> dict:
    sub = bars.loc[lo:hi]
    if len(sub) < 60:
        raise ValueError(f"{label}: only {len(sub)} bars in {lo}..{hi}")
    sig = sig_all.reindex(sub.index).ffill().fillna(0.0)
    m = evaluate_period(sub, sig, CostModel.realistic_ecn(), "XL-001", "macro", bars_per_year=BPY)
    net, bench = m["net_returns"], m["bench_returns"]
    hac = hac_alpha(net, bench, BPY, lags=5)
    out = {"label": label, **strip_diagnostics(m)}
    out["alpha_ann_hac"] = hac["alpha_ann"]
    out["alpha_t_hac"] = hac["alpha_t"]
    out["gold_first"] = float(sub["close"].iloc[0])
    out["gold_last"] = float(sub["close"].iloc[-1])
    out["years"] = float(len(sub) / BPY)
    out["min_detectable_sr"] = detection_summary(len(sub), BPY, 2.5)["min_detectable_sr"]
    out["dsr_12_trials"] = float(deflated_sharpe(m["sharpe"], 12, m["n_obs"], BPY, m["skew"], m["kurt"]))
    return out


def print_row(m: dict) -> None:
    print(
        f"  {m['label']:20s} n {m['n_obs']:5d}  alpha {m['alpha_ann']:+7.2%}  a_t {m['alpha_t']:5.2f}  "
        f"HAC {m['alpha_t_hac']:5.2f}  sharpe {m['sharpe']:5.2f}  DD {m['max_dd']:5.1%}  beta {m['beta']:4.2f}  "
        f"exposure {m['exposure']:.2f}"
    )


def main() -> int:
    print("=== driver provenance")
    prov = validate_drivers()
    t = prov["treasury_10y"]
    print(f"  DGS10 mirror vs independent copy: n={t['overlap_obs']} identical={t['identical']} max|d|={t['max_abs_diff']}")

    dxy_old = pd.read_csv("data/raw/longgold/macro_daily/DXY.csv", parse_dates=["date"]).set_index("date")["close"]
    agree = index_agreement(dxy_old, load_broad_dollar())
    print("\n=== dollar index swap (DXY -> DTWEXBGS)")
    print(f"  overlap {agree['overlap_from']}..{agree['overlap_to']}  level corr {agree['level_corr']:.3f}  "
          f"6m-change corr {agree['change_corr']:.3f}  flag agreement {agree['flag_agreement']:.1%}  n {agree['n_change_obs']}")

    bm_all = daily_bars(pd.read_parquet(BASEMAX))
    vu_all = daily_bars(pd.read_parquet(VUDO))
    qual = feed_quality({"basemax": bm_all, "vudo": vu_all})
    print("\n=== feed completeness (bars per month, tail only)")
    for name, q in qual.items():
        tail = list(q["months"].items())[-10:]
        print(f"  {name:8s} " + "  ".join(f"{k}:{v}" for k, v in tail))

    # ---- Bridge -----------------------------------------------------------
    # Both indices exist 2006-2019. The window is capped before 2020, which has
    # already been consumed elsewhere. Long LBMA gold bars are used so this test
    # isolates the index swap and nothing else.
    lbma = gold_bars(load_metals()).loc[BRIDGE[0] : BRIDGE[1]]
    if lbma.index.tz is None:
        # The LBMA series carries naive dates; the drivers are localised to UTC by
        # align_to_index, so the bar index has to match it.
        lbma.index = lbma.index.tz_localize("UTC")
    bridge = {}
    for label, usd in (("dxy", dxy_old), ("broad", load_broad_dollar())):
        frame = pd.concat([usd.rename("dxy"), load_treasury_10y().rename("y10")], axis=1, sort=True).sort_index()
        f = align_to_index(frame, lbma.index).dropna()
        b = lbma.loc[f.index]
        sig = EASING_6M.signal(f)
        if float(sig.mean()) <= 0:
            raise RuntimeError(f"bridge_{label}: signal is identically zero — alignment bug")
        bridge[label] = run_window(b, sig, BRIDGE[0], BRIDGE[1], f"bridge_{label}")

    print(f"\n=== bridge {BRIDGE[0]}..{BRIDGE[1]} (identical rule, two dollar indices)")
    for m in bridge.values():
        print_row(m)
    dt = abs(bridge["dxy"]["alpha_t"] - bridge["broad"]["alpha_t"])
    print(f"  |a_t difference| {dt:.2f} -> index choice {'does not drive' if dt < 1.0 else 'DOES drive'} the result")

    # ---- Holdout ----------------------------------------------------------
    print(f"\n=== HOLDOUT (post {dxy_old.index.max().date()}, never used for selection)")
    # The signal is computed once, on the full driver calendar. Computing it
    # inside a block would put 126 warm-up days of forced-zero exposure in every
    # block — which is exactly what an earlier draft of this script did, and it
    # made block A look like a strategy that never traded.
    sig_full = EASING_6M.signal(driver_frame())
    hold = {}
    for label, (lo, hi) in BLOCKS.items():
        bars = (bm_all if "basemax" in label else vu_all).loc[lo:hi]
        hold[label] = run_window(bars, sig_full, lo, hi, label)
        print_row(hold[label])

    # Pooled: concatenating daily returns is valid because each day's return maps
    # to that day's gold move. The five unobserved months simply are not in it, so
    # the pooled Sharpe is not "two years of continuous holding".
    def block_net(label: str) -> pd.Series:
        lo, hi = BLOCKS[label]
        bars = (bm_all if "basemax" in label else vu_all).loc[lo:hi]
        sig = sig_full.reindex(bars.index).ffill().fillna(0.0)
        res = evaluate_period(bars, sig, CostModel.realistic_ecn(), "XL-001", "macro", bars_per_year=BPY)
        return res["net_returns"]

    pooled_net = pd.concat([block_net(k) for k in BLOCKS], axis=0).sort_index()
    pooled_alpha = float(pooled_net.mean() * BPY)
    print(
        f"  pooled               n {len(pooled_net):5d}  net/yr {pooled_alpha:+7.2%}  "
        f"(geometric {float((1 + pooled_net).prod() ** (BPY / len(pooled_net)) - 1):+7.2%})"
    )

    negatives = sum(1 for m in hold.values() if m["alpha_ann"] < 0)
    verdict = "NEGATIVE_HOLDOUT" if negatives == len(hold) else ("MIXED" if negatives else "CONSISTENT_NOT_VALIDATED")
    print(f"\n  blocks with negative alpha: {negatives}/{len(hold)}  -> {verdict}")

    print("\n=== holdout by calendar year")
    for label in BLOCKS:
        net = block_net(label)
        bench = (bm_all if "basemax" in label else vu_all)["close"].pct_change()
        for year, grp in net.groupby(net.index.year):
            b = bench.loc[grp.index]
            try:
                a = hac_alpha(grp, b, BPY, lags=2) if len(grp) > 40 else {"alpha_ann": np.nan, "alpha_t": np.nan}
            except ValueError:
                a = {"alpha_ann": np.nan, "alpha_t": np.nan}
            print(
                f"  {year} {label:18s} n {len(grp):3d}  strat {grp.add(1).prod() - 1:+7.2%}  "
                f"gold {b.add(1).prod() - 1:+7.2%}  alpha {a['alpha_ann']:+7.2%}  t {a['alpha_t']:5.2f}"
            )

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "candidate": EASING_6M.id,
        "definition_hash": EASING_6M.definition_hash(),
        "blocks": BLOCKS,
        "holdout_kind": "post-sample retrospective holdout — NOT forward evidence",
        "cost_model": "ecn_realistic",
        "cost_bps_per_side": CostModel.realistic_ecn().per_side_bps(),
        "cost_is_measured": False,
        "driver_provenance": prov,
        "dollar_index_agreement": agree,
        "feed_quality": qual,
        "bridge": {k: strip_diagnostics(v) for k, v in bridge.items()},
        "holdout": {k: strip_diagnostics(v) for k, v in hold.items()},
        "pooled_net_ann": pooled_alpha,
        "verdict": verdict,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = OUT / f"xl001_holdout_{stamp}.json"
    path.write_text(json.dumps(payload, indent=2, default=str))
    print(f"\nartifact: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
