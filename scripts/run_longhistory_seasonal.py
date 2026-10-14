#!/usr/bin/env python3
"""Run the frozen calendar-seasonality XAUUSD protocol (LH-XAUUSD-SES-2026-10-14).

``--stage dev``   walk-forward folds 2010-2019 only (pipeline debugging; no
                  evaluation window, no replicate).
``--stage final``  everything: walk-forward, the reused evaluation window
                  2020-01..2025-02, cost stresses, regime attribution, the
                  Dukascopy replicate (plans with a research-history prefix),
                  the two control diagnostics, the pre-declared cost-regime and
                  swap diagnostics, and the gate verdict.

Only complete trading days (per :mod:`qts.research.longhistory.daily`) are
used, so a partial session can never generate a signal or a fill.

Writes ``data/evidence/longhistory/seasonal_research_<stage>.json``. Run
``final`` once, after the preregistration is committed. See
``docs/research/preregistration_longhistory_seasonal_2026-10-14.md``.
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
from qts.research.longhistory import daily as D  # noqa: E402
from qts.research.longhistory import runner as R  # noqa: E402
from qts.research.longhistory import seasonal_protocol as SES  # noqa: E402
from qts.research.longhistory import signals as G  # noqa: E402
from qts.research.longhistory import sources as S  # noqa: E402
from qts.research.longhistory.engine import CostModel  # noqa: E402
from qts.research.longhistory.signals import Plan  # noqa: E402

PROCESSED = REPO_ROOT / "data" / "raw" / "longhistory" / "processed"
EVIDENCE_DIR = REPO_ROOT / "data" / "evidence" / "longhistory"
RESEARCH_FILE = PROCESSED / "xauusd_basemax_utc_15m_20040611_20250228.csv"
REPLICATE_FILE = PROCESSED / "xauusd_dukascopy_utc_15m_20250806_20260916.csv"

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


def load_complete_m15(path: Path, last_label: str | None = None) -> pd.DataFrame:
    """UTC M15 bars restricted to complete trading days (and to ``last_label``)."""
    bars = S.read_csv_utc(path)
    complete_days, _ = D.to_daily(bars)
    labels = D.trading_day_label(pd.DatetimeIndex(bars.index))
    keep = np.asarray(labels.isin(complete_days.index))
    if last_label is not None:
        keep &= np.asarray(labels <= pd.Timestamp(last_label))
    out = bars.loc[keep]
    if out.index.duplicated().any():
        raise SystemExit(f"duplicate bar timestamps in {path.name}")
    return out


def bias_checks(df: pd.DataFrame) -> dict[str, object]:
    """Truncation (causality) on every candidate/control; warm-up on shared indicators."""
    n = len(df)
    cuts = sorted({int(n * f) for f in (0.25, 0.5, 0.75)})
    truncation: dict[str, Any] = {}
    for cand in SES.CANDIDATES:
        rep = C.truncation_check(cand.builder, df, cuts)
        truncation[cand.cid] = rep.as_dict()
    offset = n // 3
    burn = 2000  # bars; ATR(14) and realised vol(5520) converge far inside this
    atr_rep = C.warmup_check(lambda d: G.atr(d, 14), df, burn, offset)
    vol_rep = C.warmup_check(
        lambda d: G.realized_vol(d["close"], SES.VOL_BARS, SES.PERIODS_PER_YEAR), df, burn, offset
    )
    out: dict[str, object] = {
        "truncation": truncation,
        "warmup": {"atr14": atr_rep.as_dict(), "realized_vol": vol_rep.as_dict(), "burn_in_bars": burn},
        "all_passed": bool(
            all(v["passed"] for v in truncation.values()) and atr_rep.passed and vol_rep.passed
        ),
    }
    return out


def replicate_with_context(
    context_df: pd.DataFrame, replicate_df: pd.DataFrame, selection: dict[str, object], proto=SES
) -> dict[str, object]:
    """Frozen holdout selections run unchanged on the replicate series.

    These builders fit expanding statistics, so the plans are built on the
    concatenation of the research series (history prefix) and the replicate
    series: the frozen rule is "expand from the start of available history,
    warm up, then trade". The run window itself is replicate-only, so the
    engine still starts flat at the replicate's first bar. This mirrors
    :func:`qts.research.longhistory.runner.replicate` otherwise.
    """
    combined = pd.concat([context_df, replicate_df])
    out: dict[str, object] = {}
    for group, sel in selection.items():
        cid = sel.get("cid") if isinstance(sel, dict) else None  # type: ignore[union-attr]
        if cid is None:
            out[group] = {"cid": None, "status": "NO_SELECTION"}
            continue
        cand = proto.candidate_by_id(str(cid))
        plan = cand.builder(combined)
        run = R.run_window(combined, plan, proto.REPLICATE_START, proto.REPLICATE_END, proto.COST_BASE)
        out[group] = {
            "cid": cid,
            "status": "EVALUATED",
            "history_prefix_bars": int(len(context_df)),
            **R.ST.summarize(run, periods_per_year=proto.PERIODS_PER_YEAR),
        }
    return out


def control_diagnostics(df: pd.DataFrame, proto=SES) -> dict[str, object]:
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


def swap_diagnostics(df: pd.DataFrame, selection: dict, proto=SES) -> dict[str, object]:
    """Pre-declared overnight-rollover exposure and ASSUMED swap drag per group."""
    out: dict[str, object] = {}
    for group, sel in selection.items():
        cid = sel.get("cid") if isinstance(sel, dict) else None
        if cid is None:
            continue
        run = R.run_window(df, proto.candidate_by_id(str(cid)).builder(df), proto.HOLDOUT_START, proto.RESEARCH_END, proto.COST_BASE)
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


def cost_regime_diagnostics(df: pd.DataFrame, plans: dict[str, Plan], selection: dict, proto=SES) -> dict:
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

    research = load_complete_m15(RESEARCH_FILE, last_label=SES.RESEARCH_END)
    replicate = load_complete_m15(REPLICATE_FILE) if args.stage == "final" else None

    plans = R.build_plans(research, SES)
    # The replicate is attached below with a history prefix, so the shared
    # evaluate() sees replicate_df=None (its stateless replicate would rebuild
    # fitted plans without history).
    result = R.evaluate(research, plans, args.stage, replicate_df=None, proto=SES)
    if args.stage == "final":
        assert replicate is not None
        result["bias_checks"] = bias_checks(research)
        result["replicate"] = replicate_with_context(research, replicate, result["holdout"]["selection"], SES)
        bh = result["benchmarks"].setdefault("buy_and_hold_long", {})
        rep_bh = R.buy_and_hold(replicate, SES.REPLICATE_START, SES.REPLICATE_END, SES.COST_BASE)
        bh["replicate"] = R.ST.summarize(rep_bh, periods_per_year=SES.PERIODS_PER_YEAR)
        result["control"] = control_diagnostics(research, SES)
        result["swap_diagnostics"] = swap_diagnostics(research, result["holdout"]["selection"], SES)
        result["cost_regime_diagnostics"] = cost_regime_diagnostics(
            research, plans, result["holdout"]["selection"], SES
        )
    result["generated_at"] = datetime.now(UTC).isoformat()
    result["data"] = {
        "research_m15_bars": int(len(research)),
        "research_first_bar": str(research.index[0]),
        "research_last_bar": str(research.index[-1]),
        "replicate_m15_bars": int(len(replicate)) if replicate is not None else None,
        "research_source": "basemax_xauusd_15m (UTC), complete trading days only",
        "replicate_source": "dukascopy mirror (UTC) M15, complete trading days only",
        "bars_per_day": SES.BARS_PER_DAY,
        "periods_per_year": SES.PERIODS_PER_YEAR,
        "stamp_basis": "OPEN (established by data/evidence/longhistory/stamp_basis_probe.json)",
        "holdout_reused_from_parent_cycles": True,
    }
    out = EVIDENCE_DIR / f"seasonal_research_{args.stage}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(f"verdict: {result['verdict']['status']}")
    for group, rec in result.get("gates", {}).items():
        if isinstance(rec, dict) and "failed" in rec:
            print(f"  {group:22s} passes_all={rec.get('passes_all')} failed={rec.get('failed')}")
    if args.stage == "final":
        tables = REPO_ROOT / "docs" / "research" / "seasonal_results_tables_2026-10-14.md"
        tables.write_text(R.render_tables(result), encoding="utf-8")
        print(f"bias checks all_passed={result['bias_checks']['all_passed']}")
        print(f"wrote {tables.relative_to(REPO_ROOT)}")
    print(f"wrote {out.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
