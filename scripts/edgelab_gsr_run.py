"""Evaluate the gold/silver ratio hypotheses on 56 years of metals data.

Three declared hypotheses, four chronological windows. The 2020-2024 window is
reported here as *diagnostic only*: it has already been used once as the holdout
for the trend study, and re-using it freely would turn it into another in-sample
period. Treat any signal there as unconfirmed.

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
from qts.research.edgelab.metals import attach_ratio, gold_bars, gsr_specs, load_metals
from qts.research.edgelab.power import detection_summary

warnings.filterwarnings("ignore", category=RuntimeWarning)

OUT = Path("data/research/experiments")
BPY = 252.0
WINDOWS = (
    ("DEV_1969_2000", "1969-01-01", "2000-12-31"),
    ("VAL_2001_2010", "2001-01-01", "2010-12-31"),
    ("TEST_2011_2019", "2011-01-01", "2019-12-31"),
    ("DIAG_2020_2024", "2020-01-01", "2024-05-17"),
)


def main() -> None:
    metals = load_metals()
    bars = attach_ratio(gold_bars(metals), metals)
    specs = gsr_specs()
    cost = CostModel()
    rows = []
    for spec in specs:
        for label, lo, hi in WINDOWS:
            sub = bars[(bars.index >= lo) & (bars.index <= hi)]
            if len(sub) < 300:
                continue
            pos = spec.positions(sub)
            if float(np.abs(pos.to_numpy()).sum()) == 0:
                continue
            r = run_vector(sub, pos, cost, name=spec.name, family="gsr", bars_per_year=BPY, keep_equity=True)
            if r.net_returns is None:
                continue
            st = alpha_decomposition(r.net_returns, benchmark_returns(sub), BPY)
            rows.append(
                {
                    "name": spec.name,
                    "window": label,
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
    trials = int((df["window"] == "DEV_1969_2000").sum())
    for w in df["window"].unique():
        m = df["window"] == w
        df.loc[m, "dsr"] = [
            deflated_sharpe(s, trials, o, bars_per_year=BPY, skew=sk, kurt=ku)
            for s, o, sk, ku in zip(df.loc[m, "sharpe"], df.loc[m, "n_obs"], df.loc[m, "skew"], df.loc[m, "kurt"], strict=True)
        ]

    with pd.option_context("display.width", 200, "display.float_format", lambda v: f"{v:,.3f}"):
        print(df[["name", "window", "bars", "alpha_ann", "alpha_t", "beta", "sharpe", "exposure", "dsr"]].to_string(index=False))

    dev = df[df["window"] == "DEV_1969_2000"]
    power = detection_summary(int(dev["bars"].iloc[0]) if not dev.empty else 0, BPY)
    print(f"\nDEV floor: SR {power['min_detectable_sr']:.3f} over {power['years']:.1f} years")
    survivors = dev[(dev["alpha_t"] >= 2.5) & (dev["dsr"] >= 0.95)].name.tolist()
    print(f"DEV survivors: {survivors}")

    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset": "LBMA gold and silver, 1968-01-02..2024-05-17",
        "cost": f"ASSUMED {cost.name} ~{cost.per_side_bps():.2f} bps/side",
        "rows": df.to_dict(orient="records"),
        "dev_survivors": survivors,
        "power": power,
        "verdict": "NO_VALIDATED_EDGE" if not survivors else "PENDING_VALIDATION",
        "caveat": "DIAG_2020_2024 was already consumed as the trend-study holdout; not a clean test.",
    }
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = OUT / f"gsr_{stamp}.json"
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nVERDICT: {report['verdict']}\nwritten -> {path}")


if __name__ == "__main__":
    main()
