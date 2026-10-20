"""Evaluate the daily dollar and yield-trend hypotheses on 53 years of data.

Important honesty note carried in the output and the artifact: **2020-2024 is no
longer a clean holdout.** It was spent rejecting `tsmom_1m` in the 51-year study,
and once a window has been read, any later hypothesis evaluated on it is
in-sample. This script reports it, labels it `SPENT`, and refuses to treat a pass
there as validation.

That is the conservative reading and it costs this study its only modern holdout.
The alternative — quietly reusing a consumed window because a new candidate likes
the answer — is exactly the failure mode the whole register exists to prevent.

Costs are ASSUMED bps, never measured.
"""

from __future__ import annotations

import json
import warnings
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from qts.research.edgelab import CostModel, alpha_decomposition, benchmark_returns, deflated_sharpe, run_vector
from qts.research.edgelab.macro_daily import attach_macro_daily, macro_daily_specs
from qts.research.edgelab.metals import gold_bars, load_metals
from qts.research.edgelab.power import detection_summary

warnings.filterwarnings("ignore", category=RuntimeWarning)

OUT = Path("data/research/experiments")
BPY = 252.0
WINDOWS = (
    ("DEV_1971_2000", "1971-01-01", "2000-12-31", "in-sample"),
    ("VAL_2001_2010", "2001-01-01", "2010-12-31", "in-sample"),
    ("TEST_2011_2019", "2011-01-01", "2019-12-31", "in-sample"),
    ("SPENT_2020_2024", "2020-01-01", "2024-05-17", "holdout already consumed"),
)


def main() -> None:
    metals = load_metals()
    bars = attach_macro_daily(gold_bars(metals))
    specs = macro_daily_specs()
    cost = CostModel()
    rows = []
    for spec in specs:
        for label, lo, hi, status in WINDOWS:
            sub = bars[(bars.index >= lo) & (bars.index <= hi)].dropna(subset=["dxy", "y10"])
            if len(sub) < 300:
                continue
            pos = spec.positions(sub)
            if float(np.abs(pos.to_numpy()).sum()) == 0:
                continue
            r = run_vector(sub, pos, cost, name=spec.name, family=spec.family, bars_per_year=BPY, keep_equity=True)
            if r.net_returns is None:
                continue
            st = alpha_decomposition(r.net_returns, benchmark_returns(sub), BPY)
            rows.append(
                {
                    "name": spec.name,
                    "family": spec.family,
                    "window": label,
                    "status": status,
                    "bars": int(len(sub)),
                    "alpha_ann": st["alpha_ann"],
                    "alpha_t": st["alpha_t"],
                    "beta": st["beta"],
                    "sharpe": r.sharpe,
                    "exposure": r.exposure,
                    "skew": float(r.net_returns.skew()),
                    "kurt": float(r.net_returns.kurt()) + 3.0,
                    "n_obs": int(len(r.net_returns)),
                }
            )

    df = pd.DataFrame(rows)
    trials = int((df["window"] == "DEV_1971_2000").sum())
    for i, row in df.iterrows():
        df.loc[i, "dsr"] = deflated_sharpe(
            row["sharpe"], trials, row["n_obs"], bars_per_year=BPY, skew=row["skew"], kurt=row["kurt"]
        )

    show = ["name", "window", "bars", "alpha_ann", "alpha_t", "beta", "sharpe", "exposure", "dsr"]
    with pd.option_context("display.width", 200, "display.float_format", lambda v: f"{v:,.3f}"):
        print(df[show].to_string(index=False))

    dev = df[df["window"] == "DEV_1971_2000"]
    power = detection_summary(int(dev["bars"].iloc[0]), BPY) if not dev.empty else {}
    survivors = dev[(dev["alpha_t"] >= 2.5) & (dev["dsr"] >= 0.95)]

    # Cross-window consistency: sign agreement with DEV across the later windows.
    consistency = {}
    for name in survivors["name"]:
        later = df[(df["name"] == name) & (df["window"] != "DEV_1971_2000")]
        consistency[name] = {
            "positive_windows": int((later["alpha_ann"] > 0).sum()),
            "of": int(len(later)),
            "t_stats": [round(float(t), 2) for t in later["alpha_t"]],
        }

    # A DEV pass alone is not a candidate: it must also hold sign out of sample.
    forward = {
        name: c for name, c in consistency.items()
        if c["positive_windows"] == c["of"]
    }
    print(f"\nDEV floor: SR {power.get('min_detectable_sr', float('nan')):.3f} over {power.get('years', 0):.1f} years")
    print(f"DEV survivors: {survivors['name'].tolist()}")
    for name, c in consistency.items():
        flag = "HOLDS" if c["positive_windows"] == c["of"] else "fails sign test"
        print(f"  {name}: positive in {c['positive_windows']}/{c['of']} later windows, t={c['t_stats']} -> {flag}")

    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset": "LBMA gold (AU.csv) + DXY (1971+) + US 10y (1962+)",
        "cost": f"ASSUMED {cost.name} ~{cost.per_side_bps():.2f} bps/side",
        "trial_count_dev": trials,
        "rows": df.to_dict(orient="records"),
        "dev_survivors": survivors["name"].tolist(),
        "cross_window_consistency": consistency,
        "power": power,
        "survivors_holding_sign_out_of_sample": sorted(forward),
        "verdict": "CANDIDATE_REQUIRES_FORWARD_TEST" if forward else "NO_VALIDATED_EDGE",
        "holdout_note": (
            "2020-2024 was consumed rejecting tsmom_1m and is therefore in-sample for "
            "these hypotheses. No candidate here is validated; any survivor must "
            "accumulate genuinely forward evidence before promotion."
        ),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = OUT / f"macro_daily_{stamp}.json"
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nVERDICT: {report['verdict']}\nwritten -> {path}")


if __name__ == "__main__":
    main()
