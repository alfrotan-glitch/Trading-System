"""Round 9: gold priced against the real yield (4 configurations).

Fixed before running:

    DEV       2004-01-01 .. 2014-12-31   (real-yield data starts 2003-01, so the
                                          first year is regression warm-up)
    VAL       2015-01-01 .. 2019-12-31
    DEAD      2020-01-01 .. 2024-05-17   consumed in round 3; excluded entirely
    HOLDOUT   2024-06-01 .. 2026-09-16   two blocks (BaseMax feed ends 2025-02,
                                          Dukascopy replay feed starts 2025-08)

Cumulative trial count for the real-yield family is 5 prior (2 momentum
configurations in the round-1 catalogue, 3 level/change configurations in round
3) plus the 4 below. The deflated Sharpe uses 9.

Inference: daily returns, Newey-West(5) t-statistics, realistic ECN cost
(0.925 bps/side). Reproduce: ``python scripts/edgelab_realyield_run.py``.
"""

from __future__ import annotations

import json
import warnings
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from qts.research.edgelab import CostModel, deflated_sharpe, hac_alpha
from qts.research.edgelab.fred_drivers import (
    load_treasury_10y,
    load_treasury_10y_real,
    validate_series,
)
from qts.research.edgelab.intraday import daily_bars
from qts.research.edgelab.metals import gold_bars, load_metals
from qts.research.edgelab.power import detection_summary
from qts.research.edgelab.realyield import residual_signal
from qts.research.edgelab.reporting import evaluate_period, strip_diagnostics

warnings.filterwarnings("ignore", category=RuntimeWarning)

OUT = Path("data/research/experiments")
BPY = 252.0
PRIOR_TRIALS = 5
DEV = ("2004-01-01", "2014-12-31")
VAL = ("2015-01-01", "2019-12-31")
HOLDOUT = {
    "block_a_basemax": ("2024-06-01", "2025-02-28"),
    "block_b_dukascopy": ("2025-08-06", "2026-09-16"),
}
BASEMAX = Path("data/research/xauusd_m15_basemax.parquet")
VUDO = Path("data/research/xauusd_m15_vudo.parquet")

CONFIGS = {
    "ry_z252": {"window": 252, "long_only": False, "discrete": False},
    "ry_z252_long": {"window": 252, "long_only": True, "discrete": False},
    "ry_z504": {"window": 504, "long_only": False, "discrete": False},
    "ry_z252_sign": {"window": 252, "long_only": False, "discrete": True},
}


def score(bars: pd.DataFrame, sig: pd.Series, cost: CostModel, label: str) -> dict:
    m = evaluate_period(bars, sig.reindex(bars.index).ffill().fillna(0.0), cost, label, "real_yield", BPY)
    net, bench = m["net_returns"], m["bench_returns"]
    hac = hac_alpha(net, bench, BPY, lags=5)
    out = {"label": label, **strip_diagnostics(m)}
    out["alpha_t_hac"] = hac["alpha_t"]
    out["alpha_ann_hac"] = hac["alpha_ann"]
    out["min_detectable_sr"] = detection_summary(len(net), BPY, 2.5)["min_detectable_sr"]
    return out


def main() -> int:
    real10 = load_treasury_10y_real()
    nominal = load_treasury_10y()
    # The DFII10 mirror has no independent copy to check against; what can be
    # checked is its internal consistency — a real yield above the nominal one
    # would be a data error (inflation expectations cannot be negative for a
    # decade on average), so the share of such days is reported.
    j = pd.concat([real10.rename("real"), nominal.rename("nom")], axis=1, join="inner").dropna()
    inverted = float((j["real"] > j["nom"]).mean())
    print(f"DFII10 span {real10.index.min().date()}..{real10.index.max().date()}  n={len(real10)}")
    print(f"  real > nominal on {inverted:.2%} of overlapping days (expect ~0)")
    print(f"  latest real {real10.iloc[-1]:.2f}%  nominal {nominal.iloc[-1]:.2f}%")
    prov = validate_series(load_treasury_10y(), nominal, "self-check")

    lbma = gold_bars(load_metals())
    if lbma.index.tz is None:
        lbma.index = lbma.index.tz_localize("UTC")
    cost = CostModel.realistic_ecn()
    n_trials = PRIOR_TRIALS + len(CONFIGS)

    print(f"\nRound 9 real-yield residual — cost {cost.name} {cost.per_side_bps():.3f} bps/side (ASSUMED)")
    print(f"DEV {DEV}  VAL {VAL}  trials={n_trials} ({PRIOR_TRIALS} prior + {len(CONFIGS)} here)\n")

    rows = []
    for name, kw in CONFIGS.items():
        sig = residual_signal(lbma, real10, **kw)
        dev = score(lbma.loc[DEV[0] : DEV[1]], sig, cost, f"{name}_dev")
        val = score(lbma.loc[VAL[0] : VAL[1]], sig, cost, f"{name}_val")
        stress = score(lbma.loc[DEV[0] : DEV[1]], sig, CostModel.stressed(2.0), f"{name}_dev_stress")
        dsr = float(deflated_sharpe(dev["sharpe"], n_trials, dev["n_obs"], BPY, dev["skew"], dev["kurt"]))
        rows.append(
            {
                "name": name,
                "dev_alpha": dev["alpha_ann"],
                "dev_alpha_t": dev["alpha_t"],
                "dev_hac_t": dev["alpha_t_hac"],
                "dev_sharpe": dev["sharpe"],
                "dev_turnover": dev["turnover_per_year"],
                "dev_exposure": dev["exposure"],
                "dsr": dsr,
                "stress_alpha_t": stress["alpha_t"],
                "val_alpha": val["alpha_ann"],
                "val_alpha_t": val["alpha_t"],
                "floor_sr": dev["min_detectable_sr"],
            }
        )

    df = pd.DataFrame(rows).set_index("name")
    show = df.copy()
    for c in ("dev_alpha", "val_alpha"):
        show[c] = (show[c] * 100).round(2)
    for c in ("dev_alpha_t", "dev_hac_t", "dev_sharpe", "dev_turnover", "dev_exposure", "dsr", "stress_alpha_t", "val_alpha_t", "floor_sr"):
        show[c] = show[c].round(3)
    pd.set_option("display.width", 220)
    print(show.to_string())

    survivors = df[
        (df["dev_alpha_t"] >= 2.5) & (df["dsr"] >= 0.95) & (df["stress_alpha_t"] > 0) & (df["dev_alpha"] > 0)
    ]
    confirmed = survivors[survivors["val_alpha_t"] > 0]
    print(f"\ngate: {len(survivors)} DEV survivor(s); {len(confirmed)} confirmed on VAL")
    if len(confirmed):
        print("survivors:", ", ".join(confirmed.index))

    # ---- holdout on the survivors only ------------------------------------
    hold = {}
    if len(confirmed):
        bm = daily_bars(pd.read_parquet(BASEMAX))
        vu = daily_bars(pd.read_parquet(VUDO))
        for name in confirmed.index:
            sig_all = residual_signal(
                pd.concat([lbma, pd.concat([bm, vu]).sort_index()]).sort_index(), real10, **CONFIGS[name]
            )
            hold[name] = {}
            for block, (lo, hi) in HOLDOUT.items():
                bars = (bm if "basemax" in block else vu).loc[lo:hi]
                m = score(bars, sig_all, cost, f"{name}_{block}")
                hold[name][block] = strip_diagnostics(m)
                print(
                    f"  HOLDOUT {name} {block:18s} n {m['n_obs']:4d} alpha {m['alpha_ann']:+7.2%} "
                    f"a_t {m['alpha_t']:5.2f} sharpe {m['sharpe']:5.2f}"
                )
    else:
        print("holdout not run: nothing survived DEV and VAL, and reading it would only spend it.")

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "round": 9,
        "family": "real_yield_residual",
        "dev": DEV,
        "val": VAL,
        "holdout": HOLDOUT,
        "cost_model": cost.name,
        "cost_bps_per_side": cost.per_side_bps(),
        "cost_is_measured": False,
        "trials": n_trials,
        "prior_trials": PRIOR_TRIALS,
        "data_check": {"real_gt_nominal_share": inverted, "dfii10_span": [str(real10.index.min().date()), str(real10.index.max().date())]},
        "provenance_selfcheck": prov,
        "rows": json.loads(df.reset_index().to_json(orient="records")),
        "survivors": list(survivors.index),
        "val_confirmed": list(confirmed.index),
        "holdout_results": hold,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = OUT / f"realyield_{stamp}.json"
    path.write_text(json.dumps(payload, indent=2, default=str))
    print(f"\nartifact: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
