#!/usr/bin/env python3
"""Run the frozen monthly long-history XAUUSD protocol (LH-XAUUSD-MON-2026-10-15).

``--stage dev``    walk-forward folds 1990-1999 only (pipeline debugging; no
                   evaluation window, no replicate).
``--stage final``  everything: walk-forward, the evaluation window
                   2000-01..2026-09, cost stresses, the financing-charged
                   regime, regime attribution, the BaseMax monthly source
                   replication (history-prefix plans), control diagnostics,
                   the pre-declared cost-regime and swap diagnostics, and the
                   gate verdict.

Series: World Bank monthly gold average with open=high=low=close=the monthly
average (preregistered TWAP execution at the next month's published average),
joined to the equal-weight Federal Reserve FX basket USD index. Bars are
month-end stamped. Build the data first:

    python scripts/fetch_longhistory_monthly_sources.py
    python scripts/build_longhistory_monthly_dataset.py

Writes ``data/evidence/longhistory/monthly_research_<stage>.json``. Run
``final`` once, after the preregistration is committed. See
``docs/research/preregistration_longhistory_monthly_2026-10-15.md``.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from qts.research.longhistory import checks as C  # noqa: E402
from qts.research.longhistory import monthly_protocol as MON  # noqa: E402
from qts.research.longhistory import runner as R  # noqa: E402
from qts.research.longhistory import signals as G  # noqa: E402
from qts.research.longhistory.engine import CostModel  # noqa: E402
from qts.research.longhistory.signals import Plan  # noqa: E402

PROCESSED = REPO_ROOT / "data" / "raw" / "longhistory" / "processed"
EVIDENCE_DIR = REPO_ROOT / "data" / "evidence" / "longhistory"
RESEARCH_FILE = PROCESSED / "xauusd_worldbank_monthly_utc_197301_202609.csv"
REPLICATE_FILE = PROCESSED / "xauusd_basemax_monthly_utc_200406_202502.csv"

#: Pre-declared non-gating cost regimes (docs/research/m15_cost_sensitivity_2026-10-11.md).
COST_REGIMES: dict[str, CostModel] = {
    "canonical_xauusd_default": CostModel.from_price_units(
        spread_usd_per_oz=0.30, slippage_usd_per_oz_side=0.10, commission_usd_per_lot_side=0.0, basis="ASSUMED"
    ),
    "wm_measured_median": CostModel.from_price_units(
        spread_usd_per_oz=0.24, slippage_usd_per_oz_side=0.10, commission_usd_per_lot_side=0.0, basis="MIXED"
    ),
    "wm_measured_median_ecn": CostModel.from_price_units(
        spread_usd_per_oz=0.24, slippage_usd_per_oz_side=0.10, commission_usd_per_lot_side=7.0, basis="MIXED"
    ),
    "wm_reopen_hour_stress": CostModel.from_price_units(
        spread_usd_per_oz=0.39, slippage_usd_per_oz_side=0.15, commission_usd_per_lot_side=7.0, basis="MIXED"
    ),
}


def load_monthly(path: Path, last: str | None = None) -> pd.DataFrame:
    """Read a monthly dataset CSV (``date`` column, month-end stamps, OHLC+usd).

    ``sources.read_csv_utc`` only reads the parent cycle's ``time``+OHLC files
    (it would drop the ``usd`` column), so the monthly runner does its own
    reader over the builder's own schema.
    """
    raw = pd.read_csv(path)
    required = {"date", "open", "high", "low", "close", "usd"}
    missing = required.difference(raw.columns)
    if missing:
        raise SystemExit(f"{path.name}: missing columns {sorted(missing)}")
    index = pd.to_datetime(raw["date"], utc=True).dt.tz_convert(None)
    bars = raw[["open", "high", "low", "close", "usd"]].astype(float)
    bars.index = pd.DatetimeIndex(index, name="utc")
    if last is not None:
        bars = bars.loc[:last]
    if bars.index.duplicated().any() or not bars.index.is_monotonic_increasing:
        raise SystemExit(f"{path.name}: duplicate or unsorted month-end stamps")
    return bars


def bias_checks(df: pd.DataFrame) -> dict[str, object]:
    """Truncation (causality) on every candidate/control; warm-up on shared indicators."""
    n = len(df)
    cuts = sorted({int(n * f) for f in (0.25, 0.5, 0.75)})
    truncation: dict[str, Any] = {}
    for cand in MON.CANDIDATES:
        rep = C.truncation_check(cand.builder, df, cuts)
        truncation[cand.cid] = rep.as_dict()
    offset = max(n // 3, 36)
    burn = 36  # bars; 12-month realised vol converges well inside this
    vol_rep = C.warmup_check(
        lambda d: G.realized_vol(d["close"], MON.VOL_BARS, MON.PERIODS_PER_YEAR), df, burn, offset
    )
    out: dict[str, object] = {
        "truncation": truncation,
        "warmup": {"realized_vol_12m": vol_rep.as_dict(), "burn_in_bars": burn},
        "all_passed": bool(all(v["passed"] for v in truncation.values()) and vol_rep.passed),
    }
    return out


def replicate_with_context(
    context_df: pd.DataFrame, replicate_df: pd.DataFrame, selection: dict[str, object], proto=MON
) -> dict[str, object]:
    """Frozen holdout selections run on BaseMax monthly bars (source replication).

    The builders fit expanding statistics, so plans are built on the
    history-prefix concatenation: research months strictly BEFORE the
    replicate window followed by the replicate months (this cycle's research
    series spans the replicate window, so the full research frame cannot be
    prepended — only its pre-window history, which is what "history prefix"
    means here; the builders need far less than the ~31 years available). The
    run window is replicate-only, so the engine still starts flat at the
    replicate's first bar. The replicate uses real OHLC bars and the engine's
    next-open fills — an independent quote stream and an independent
    execution convention versus the research TWAP-average convention.
    """
    prefix = context_df[context_df.index < replicate_df.index[0]]
    combined = pd.concat([prefix, replicate_df])
    out: dict[str, object] = {}
    for group, sel in selection.items():
        cid = sel.get("cid") if isinstance(sel, dict) else None
        if cid is None:
            out[group] = {"cid": None, "status": "NO_SELECTION"}
            continue
        cand = proto.candidate_by_id(str(cid))
        plan = cand.builder(combined)
        run = R.run_window(combined, plan, proto.REPLICATE_START, proto.REPLICATE_END, proto.COST_BASE)
        out[group] = {
            "cid": cid,
            "status": "EVALUATED",
            "history_prefix_months": int(len(prefix)),
            "execution_convention": "next-open fills on real BaseMax monthly OHLC",
            **R.ST.summarize(run, periods_per_year=proto.PERIODS_PER_YEAR),
        }
    return out


def control_diagnostics(df: pd.DataFrame, proto=MON) -> dict[str, object]:
    """Controls: chained walk-forward composite plus the evaluation window.

    Non-gating by construction (controls never enter selection or gates).
    """
    out: dict[str, object] = {}
    for cand in proto.CANDIDATES:
        if cand.role != "CONTROL":
            continue
        plan = cand.builder(df)
        year_nets: list[float] = []
        returns: list[np.ndarray] = []
        for year in proto.WF_TEST_YEARS:
            run = R.run_window(df, plan, f"{year}-01-01", f"{year}-12-31", proto.COST_BASE)
            year_nets.append(run.net_usd)
            returns.append(run.returns)
        joined = np.concatenate(returns) if returns else np.array([])
        ho = R.run_window(df, plan, proto.HOLDOUT_START, proto.RESEARCH_END, proto.COST_BASE)
        ho2x = R.run_window(df, plan, proto.HOLDOUT_START, proto.RESEARCH_END, proto.COST_BASE.scaled(2.0))
        zero = R.run_window(df, plan, proto.HOLDOUT_START, proto.RESEARCH_END, proto.COST_BASE.scaled(0.0))
        out[cand.cid] = {
            "role": "CONTROL",
            "group": cand.group,
            "wf_sharpe": round(R.ST.sharpe(joined, proto.PERIODS_PER_YEAR), 4) if joined.size else 0.0,
            "wf_positive_years": int(sum(1 for v in year_nets if v > 0)),
            "evaluation_window": R.ST.summarize(ho, periods_per_year=proto.PERIODS_PER_YEAR),
            "evaluation_window_2x_net_usd": round(ho2x.net_usd, 2),
            "gross_zero_cost_usd": round(zero.net_usd, 2),
            "break_even_multiplier": R.break_even_multiplier(
                df, plan, proto.HOLDOUT_START, proto.RESEARCH_END
            ),
        }
    return out


def rollover_crossings(entry: pd.Timestamp, exit_: pd.Timestamp) -> int:
    """22:00 UTC boundaries strictly inside (entry, exit_]."""
    if exit_ <= entry:
        return 0
    first = entry.normalize() + pd.Timedelta(hours=22)
    if first <= entry:
        first += pd.Timedelta(days=1)
    count = 0
    t = first
    while t <= exit_:
        count += 1
        t += pd.Timedelta(days=1)
    return count


def swap_diagnostics(df: pd.DataFrame, selection: dict, proto=MON) -> dict[str, object]:
    """Pre-declared overnight-rollover exposure and ASSUMED swap drag per group."""
    out: dict[str, object] = {}
    for group, sel in selection.items():
        cid = sel.get("cid") if isinstance(sel, dict) else None
        if cid is None:
            continue
        run = R.run_window(
            df, proto.candidate_by_id(str(cid)).builder(df), proto.HOLDOUT_START, proto.RESEARCH_END, proto.COST_BASE
        )
        trades = run.trades
        crossings = 0
        drag = 0.0
        for t in trades:
            n_cross = rollover_crossings(pd.Timestamp(t.entry_day), pd.Timestamp(t.exit_day))
            crossings += n_cross
            lots = t.entry_frac * proto.INITIAL_EQUITY / (100.0 * max(t.entry_price, 1e-9))
            drag += n_cross * proto.SWAP_USD_PER_LOT_ROLLOVER * lots
        out[group] = {
            "cid": cid,
            "trades": len(trades),
            "rollover_crossings": int(crossings),
            "mean_crossings_per_trade": round(crossings / len(trades), 4) if trades else 0.0,
            "assumed_swap_drag_usd": round(drag, 2),
            "assumption": f"{proto.SWAP_USD_PER_LOT_ROLLOVER} USD/lot/22:00-UTC rollover (ASSUMED)",
        }
    return out


def cost_regime_diagnostics(df: pd.DataFrame, plans: dict[str, Plan], selection: dict, proto=MON) -> dict:
    """Evaluation-window net/Sharpe under the pre-declared cost regimes (non-gating)."""
    out: dict[str, object] = {}
    for group, sel in selection.items():
        cid = sel.get("cid")
        if cid is None:
            continue
        plan = plans[str(cid)]
        per_regime: dict[str, object] = {}
        for name, costs in COST_REGIMES.items():
            run = R.run_window(df, plan, proto.HOLDOUT_START, proto.RESEARCH_END, costs)
            per_regime[name] = {
                "cost_basis": costs.basis,
                "net_usd": round(run.net_usd, 2),
                "sharpe": round(R.ST.sharpe(run.returns, proto.PERIODS_PER_YEAR), 4),
                "cost_usd": round(run.cost_usd, 2),
            }
        out[group] = {"cid": cid, "regimes": per_regime}
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stage", choices=["dev", "final"], required=True)
    args = parser.parse_args()

    if not RESEARCH_FILE.is_file():
        raise SystemExit(
            "monthly research series missing; run scripts/fetch_longhistory_monthly_sources.py and "
            "scripts/build_longhistory_monthly_dataset.py first"
        )
    research = load_monthly(RESEARCH_FILE, last=f"{MON.RESEARCH_END}")
    replicate = load_monthly(REPLICATE_FILE) if args.stage == "final" else None

    plans = R.build_plans(research, MON)
    # The replicate is attached below with a history prefix, so the shared
    # evaluate() sees replicate_df=None (its stateless replicate would rebuild
    # fitted plans without history).
    result = R.evaluate(research, plans, args.stage, replicate_df=None, proto=MON)
    if args.stage == "final":
        assert replicate is not None
        result["bias_checks"] = bias_checks(research)
        result["replicate"] = replicate_with_context(research, replicate, result["holdout"]["selection"], MON)
        bh = result["benchmarks"].setdefault("buy_and_hold_long", {})
        rep_bh = R.buy_and_hold(replicate, MON.REPLICATE_START, MON.REPLICATE_END, MON.COST_BASE)
        bh["replicate"] = R.ST.summarize(rep_bh, periods_per_year=MON.PERIODS_PER_YEAR)
        result["control"] = control_diagnostics(research, MON)
        result["swap_diagnostics"] = swap_diagnostics(research, result["holdout"]["selection"], MON)
        result["cost_regime_diagnostics"] = cost_regime_diagnostics(
            research, plans, result["holdout"]["selection"], MON
        )
    result["generated_at"] = datetime.now(UTC).isoformat()
    result["data"] = {
        "research_months": int(len(research)),
        "research_first_month": str(research.index[0]),
        "research_last_month": str(research.index[-1]),
        "replicate_months": int(len(replicate)) if replicate is not None else None,
        "research_source": "World Bank monthly gold average + Fed H.10 basket USD index (see monthly_data_quality.json)",
        "replicate_source": "BaseMax XAUUSD 15m aggregated to monthly OHLC (UTC)",
        "periods_per_year": MON.PERIODS_PER_YEAR,
        "execution_convention": (
            "research bars: open=high=low=close=monthly average, decisions fill at the next month's "
            "average (TWAP); replicate bars: real OHLC, next-open fills"
        ),
    }
    out = EVIDENCE_DIR / f"monthly_research_{args.stage}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(f"verdict: {result['verdict']['status']}")
    for group, rec in result.get("gates", {}).items():
        if isinstance(rec, dict) and "failed" in rec:
            print(f"  {group:22s} passes_all={rec.get('passes_all')} failed={rec.get('failed')}")
    if args.stage == "final":
        tables = REPO_ROOT / "docs" / "research" / "monthly_results_tables_2026-10-15.md"
        tables.write_text(R.render_tables(result), encoding="utf-8")
        print(f"bias checks all_passed={result['bias_checks']['all_passed']}")
        print(f"wrote {tables.relative_to(REPO_ROOT)}")
    print(f"wrote {out.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
