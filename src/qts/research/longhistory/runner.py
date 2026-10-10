"""Walk-forward, holdout, stress and gate evaluation for the frozen protocol.

Stages
------
``dev``    walk-forward folds 2010-2019 and their selections only. Used to debug
           the pipeline. It never evaluates the holdout or the replicate.
``final``  everything, including the untouched holdout (2020-01 -> 2025-02) and
           the Dukascopy replicate. Run once, after the preregistration commit.

Selection for any test window uses only data that ends before the window. The
selection rule is: within each family group, the candidate with the highest
net Sharpe on the training window, among candidates with at least
``MIN_TRAIN_ROUND_TURNS`` round turns there (ties go to the earlier candidate).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from qts.research.longhistory import protocol as P
from qts.research.longhistory import stats as ST
from qts.research.longhistory.engine import CostModel, RunResult, run_plan
from qts.research.longhistory.signals import Plan, realized_vol


@dataclass
class Window:
    start: str
    end: str


def window_positions(df: pd.DataFrame, start: str, end: str) -> tuple[int, int]:
    """Half-open integer positions ``[i0, i1)`` of trading days in ``[start, end]``."""
    idx = pd.DatetimeIndex(df.index)
    i0 = int(idx.searchsorted(pd.Timestamp(start), side="left"))
    i1 = int(idx.searchsorted(pd.Timestamp(end), side="right"))
    if i1 - i0 < 2:
        raise ValueError(f"window {start}..{end} has fewer than two trading days")
    return i0, i1


def build_plans(df: pd.DataFrame) -> dict[str, Plan]:
    return {c.cid: c.builder(df) for c in P.CANDIDATES}


def run_window(
    df: pd.DataFrame,
    plan: Plan,
    start: str,
    end: str,
    costs: CostModel,
) -> RunResult:
    i0, i1 = window_positions(df, start, end)
    return run_plan(df, plan, i0, i1, costs, initial_equity=P.INITIAL_EQUITY, force_close_end=True)


def _metric(run: RunResult) -> dict[str, Any]:
    return ST.summarize(run)


def select_per_group(
    df: pd.DataFrame,
    plans: dict[str, Plan],
    train_start: str,
    train_end: str,
) -> dict[str, dict[str, Any]]:
    """Pick the training-window winner in each family group (base costs)."""
    chosen: dict[str, dict[str, Any]] = {}
    for group in P.FAMILY_GROUPS:
        best: tuple[float, str] | None = None
        table = []
        for cand in P.candidates_in(group):
            run = run_window(df, plans[cand.cid], train_start, train_end, P.COST_BASE)
            sr = ST.sharpe(run.returns)
            turns = len(run.trades)
            eligible = turns >= P.MIN_TRAIN_ROUND_TURNS
            table.append(
                {"cid": cand.cid, "train_sharpe": round(sr, 4), "train_round_turns": turns, "eligible": eligible}
            )
            if eligible and (best is None or sr > best[0] + 1e-12):
                best = (sr, cand.cid)
        chosen[group] = {
            "cid": best[1] if best else None,
            "train_sharpe": round(best[0], 4) if best else None,
            "candidates": table,
        }
    return chosen


def walk_forward(df: pd.DataFrame, plans: dict[str, Plan]) -> dict[str, Any]:
    """Expanding-window selection, one test year per fold, frozen within each fold."""
    years: list[dict[str, Any]] = []
    composite_returns: dict[str, list[np.ndarray]] = {g: [] for g in P.FAMILY_GROUPS}
    composite_pnl: dict[str, list[tuple[pd.DatetimeIndex, np.ndarray]]] = {g: [] for g in P.FAMILY_GROUPS}
    first = str(pd.DatetimeIndex(df.index)[0].date())
    for year in P.WF_TEST_YEARS:
        train_end = f"{year - 1}-12-31"
        test_start, test_end = f"{year}-01-01", f"{year}-12-31"
        selection = select_per_group(df, plans, first, train_end)
        year_rec: dict[str, Any] = {"year": year, "selection": {}}
        for group, sel in selection.items():
            cid = sel["cid"]
            if cid is None:
                year_rec["selection"][group] = {"cid": None, "net_usd": 0.0, "sharpe": 0.0, "round_turns": 0}
                continue
            run = run_window(df, plans[cid], test_start, test_end, P.COST_BASE)
            year_rec["selection"][group] = {
                "cid": cid,
                "train_sharpe": sel["train_sharpe"],
                "net_usd": round(run.net_usd, 2),
                "sharpe": round(ST.sharpe(run.returns), 4),
                "round_turns": len(run.trades),
            }
            composite_returns[group].append(run.returns)
            composite_pnl[group].append((run.days, np.diff(np.concatenate([[run.initial_equity], run.equity]))))
        years.append(year_rec)
    return {"folds": years, "composite_returns": composite_returns, "composite_pnl": composite_pnl}


def holdout(df: pd.DataFrame, plans: dict[str, Plan], end: str) -> dict[str, Any]:
    """Select once on data through DEV_END, then run the frozen choice once on the holdout."""
    first = str(pd.DatetimeIndex(df.index)[0].date())
    selection = select_per_group(df, plans, first, P.DEV_END)
    out: dict[str, Any] = {"selection": selection, "groups": {}}
    for group, sel in selection.items():
        cid = sel["cid"]
        if cid is None:
            out["groups"][group] = {"cid": None}
            continue
        plan = plans[cid]
        base = run_window(df, plan, P.HOLDOUT_START, end, P.COST_BASE)
        stress = {
            f"{m:g}x": run_window(df, plan, P.HOLDOUT_START, end, P.COST_BASE.scaled(m))
            for m in P.COST_STRESS_MULTIPLIERS
        }
        zero = run_window(df, plan, P.HOLDOUT_START, end, P.COST_BASE.scaled(0.0))
        out["groups"][group] = {
            "cid": cid,
            "base": base,
            "stress": stress,
            "gross_zero_cost": zero,
            "break_even_multiplier": break_even_multiplier(df, plan, P.HOLDOUT_START, end),
            "sign_randomisation_p": sign_randomisation_p(base),
        }
    return out


def break_even_multiplier(df: pd.DataFrame, plan: Plan, start: str, end: str, hi: float = 50.0) -> dict[str, Any]:
    """Cost multiplier at which net P&L crosses zero (bisection on a monotone proxy)."""

    def net(m: float) -> float:
        return run_window(df, plan, start, end, P.COST_BASE.scaled(m)).net_usd

    if net(0.0) <= 0.0:
        return {"value": 0.0, "status": "NEGATIVE_EVEN_AT_ZERO_COST"}
    if net(hi) > 0.0:
        return {"value": hi, "status": f"POSITIVE_AT_{hi:g}X"}
    lo_m, hi_m = 0.0, hi
    for _ in range(40):
        mid = 0.5 * (lo_m + hi_m)
        if net(mid) > 0.0:
            lo_m = mid
        else:
            hi_m = mid
    return {"value": round(0.5 * (lo_m + hi_m), 4), "status": "CROSSES_ZERO"}


def sign_randomisation_p(run: RunResult, n_draws: int = 5000, seed: int = 23) -> dict[str, Any]:
    """Trade-level direction null: keep each trade's timing and size, randomise its side.

    Each trade's price-move P&L is ``direction * unsigned_move``. Under the null
    the direction is a fair coin, so the net is ``sum(s_i * m_i) - costs``. The
    p-value is the share of draws at least as good as the observed net. Costs
    and compounding are held fixed (an approximation, stated in the report).
    """
    trades = [t for t in run.trades if t.direction != 0]
    if not trades:
        return {"p_value": 1.0, "trades": 0}
    dirs = np.array([t.direction for t in trades], dtype=float)
    gross = np.array([t.gross_usd for t in trades], dtype=float)
    costs = np.array([t.cost_usd for t in trades], dtype=float)
    unsigned = gross * dirs  # gross = direction * unsigned move
    observed = float(gross.sum() - costs.sum())
    rng = np.random.default_rng(seed)
    signs = rng.choice([-1.0, 1.0], size=(n_draws, len(trades)))
    nulls = (signs * unsigned).sum(axis=1) - costs.sum()
    p = float(np.mean(nulls >= observed))
    return {"p_value": round(p, 4), "trades": len(trades), "observed_net_approx": round(observed, 2)}


def regime_labels(df: pd.DataFrame) -> pd.Series:
    """Causal, mechanical regimes: trend (12-month return sign) x volatility (vs expanding median)."""
    close = df["close"]
    trend = np.sign(close / close.shift(252) - 1.0)
    vol = realized_vol(close)
    vol_med = vol.expanding(min_periods=252).median()
    hi = vol > vol_med
    names = np.where(trend > 0, "UP", "DOWN") + np.where(hi, "_HIVOL", "_LOWVOL")
    labels = pd.Series(names, index=df.index, dtype=object)
    labels[trend.isna() | vol_med.isna()] = None
    return labels


def regime_attribution(pnl_series: list[tuple[pd.DatetimeIndex, np.ndarray]], labels: pd.Series) -> dict[str, Any]:
    days = (
        np.concatenate([np.asarray(d) for d, _ in pnl_series]) if pnl_series else np.array([], dtype="datetime64[ns]")
    )
    pnl = np.concatenate([p for _, p in pnl_series]) if pnl_series else np.array([])
    out: dict[str, Any] = {}
    for regime in ["UP_HIVOL", "UP_LOWVOL", "DOWN_HIVOL", "DOWN_LOWVOL"]:
        mask = (
            np.array([labels.get(pd.Timestamp(d)) == regime for d in days], dtype=bool)
            if len(days)
            else np.array([], dtype=bool)
        )
        out[regime] = {
            "days": int(mask.sum()),
            "net_usd": round(float(pnl[mask].sum()), 2) if mask.any() else 0.0,
        }
    return out


def _pass_fail(flag: bool) -> str:
    return "PASS" if flag else "FAIL"


def evaluate(
    df: pd.DataFrame,
    plans: dict[str, Plan],
    stage: str,
    replicate_df: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Run the protocol and return the full, JSON-serialisable result record."""
    wf = walk_forward(df, plans)
    result: dict[str, Any] = {
        "prereg_id": P.PREREG_ID,
        "stage": stage,
        "n_trials": P.N_TRIALS,
        "cost_base": P.COST_BASE.describe(),
        "windows": {
            "research": [P.RESEARCH_START, P.RESEARCH_END],
            "dev_end": P.DEV_END,
            "holdout": [P.HOLDOUT_START, P.RESEARCH_END],
            "wf_test_years": list(P.WF_TEST_YEARS),
        },
        "walk_forward": {"folds": wf["folds"]},
    }
    labels = regime_labels(df)
    wf_summary: dict[str, Any] = {}
    combined: dict[str, np.ndarray] = {}
    for group in P.FAMILY_GROUPS:
        rets = wf["composite_returns"][group]
        joined = np.concatenate(rets) if rets else np.array([])
        combined[group] = joined
        years_pos = sum(1 for f in wf["folds"] if f["selection"][group]["cid"] and f["selection"][group]["net_usd"] > 0)
        years_traded = sum(
            1 for f in wf["folds"] if f["selection"][group]["cid"] and f["selection"][group]["round_turns"] > 0
        )
        wf_summary[group] = {
            "wf_sharpe": round(ST.sharpe(joined), 4) if joined.size else 0.0,
            "wf_positive_years": years_pos,
            "wf_years_with_trades": years_traded,
            "wf_chained_return": round(float(np.prod(1.0 + joined) - 1.0), 4) if joined.size else 0.0,
            "wf_regimes": regime_attribution(wf["composite_pnl"][group], labels),
        }
    result["walk_forward"]["summary"] = wf_summary

    if stage == "final":
        ho = holdout(df, plans, P.RESEARCH_END)
        ho_summary: dict[str, Any] = {}
        p_values: dict[str, float] = {}
        for group, rec in ho["groups"].items():
            if rec.get("cid") is None:
                ho_summary[group] = {"cid": None}
                continue
            base: RunResult = rec["base"]
            p = ST.mean_p_value_one_sided(base.returns)
            p_values[group] = p
            ho_summary[group] = {
                "cid": rec["cid"],
                "selection_train_sharpe": ho["selection"][group]["train_sharpe"],
                "base": ST.summarize(base, num_trials=P.N_TRIALS),
                "stress": {k: ST.summarize(v) for k, v in rec["stress"].items()},
                "gross_zero_cost_usd": round(rec["gross_zero_cost"].net_usd, 2),
                "break_even_multiplier": rec["break_even_multiplier"],
                "sign_randomisation": rec["sign_randomisation_p"],
                "bootstrap_sharpe": ST.sharpe_interval(base.returns),
                "p_mean_positive_one_sided": round(p, 4),
                "regimes_holdout": regime_attribution(
                    [(base.days, np.diff(np.concatenate([[base.initial_equity], base.equity])))], labels
                ),
            }
        for group, rec in ho["groups"].items():
            if rec.get("cid") is not None:
                combined[group] = np.concatenate([combined[group], rec["base"].returns])
        holm_adj = ST.holm(p_values) if p_values else {}
        for group, rec in ho_summary.items():
            if "p_mean_positive_one_sided" in rec:
                rec["holm_adjusted_p"] = round(holm_adj[group], 4)
        result["holdout"] = {"selection": ho["selection"], "groups": ho_summary}
        result["holdout_selection_summary"] = {g: ho["selection"][g]["cid"] for g in P.FAMILY_GROUPS}

        if replicate_df is not None:
            result["replicate"] = replicate(replicate_df, ho["selection"])

    result["gates"] = gates(result, combined, labels, stage)
    result["verdict"] = verdict(result)
    return result


def gates(result: dict[str, Any], combined: dict[str, np.ndarray], labels: pd.Series, stage: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if stage != "final":
        return {"status": "NOT_EVALUATED_DEV_STAGE", "reason": "holdout not evaluated in dev stage"}
    ho = result["holdout"]["groups"]
    wf = result["walk_forward"]["summary"]
    for group in P.FAMILY_GROUPS:
        rec = ho.get(group, {})
        if not rec.get("cid"):
            out[group] = {"G0_candidate_selected": "FAIL", "failed": ["no eligible candidate"]}
            continue
        base = rec["base"]
        stress2 = rec["stress"]["2x"]
        oos = combined[group]
        dsr = ST.deflated_sharpe(oos, P.N_TRIALS) if oos.size else {"dsr": float("nan")}
        regimes = dict(wf[group]["wf_regimes"])
        for k, v in rec["regimes_holdout"].items():
            regimes[k] = {
                "days": regimes[k]["days"] + v["days"],
                "net_usd": round(regimes[k]["net_usd"] + v["net_usd"], 2),
            }
        positive_regimes = sum(1 for v in regimes.values() if v["days"] > 0 and v["net_usd"] > 0)
        all_present = all(v["days"] > 0 for v in regimes.values())
        oos_turns = (
            sum(f["selection"][group]["round_turns"] for f in result["walk_forward"]["folds"]) + base["round_turns"]
        )
        checks = {
            "G1_holdout_net_and_sharpe_positive": base["net_usd"] > 0 and base["sharpe"] > 0,
            "G2_holdout_net_positive_at_2x_cost": stress2["net_usd"] > 0,
            "G3_walk_forward_sharpe_and_years": wf[group]["wf_sharpe"] > 0
            and wf[group]["wf_positive_years"] >= P.GATE_WF_MIN_POSITIVE_YEARS,
            "G4_holm_adjusted_p_le_alpha": rec["holm_adjusted_p"] <= P.GATE_HOLM_ALPHA,
            "G5_dsr_ge_threshold": bool(dsr.get("dsr", 0.0) >= P.GATE_DSR_MIN),
            "G6_oos_round_turns_ge_100": oos_turns >= P.MIN_TRADES_OOS_GATE,
            "G7_regime_coverage": all_present and positive_regimes >= P.GATE_REGIMES_MIN_POSITIVE,
        }
        failed = [k for k, v in checks.items() if not v]
        out[group] = {
            "cid": rec["cid"],
            "checks": {k: _pass_fail(v) for k, v in checks.items()},
            "failed": failed,
            "dsr": round(float(dsr.get("dsr", float("nan"))), 4) if dsr.get("dsr") is not None else None,
            "oos_round_turns": oos_turns,
            "positive_regimes": positive_regimes,
            "regimes_oos": regimes,
            "passes_all": not failed,
        }
    return out


def verdict(result: dict[str, Any]) -> dict[str, Any]:
    g = result.get("gates", {})
    if g.get("status") == "NOT_EVALUATED_DEV_STAGE":
        return {"status": "NOT_EVALUATED", "claim": "none"}
    passing = [k for k, v in g.items() if isinstance(v, dict) and v.get("passes_all")]
    if passing:
        return {
            "status": "FORWARD_VALIDATION_CANDIDATE_ONLY",
            "passing_groups": passing,
            "claim": "none. Costs are ASSUMED, so no economic-edge claim is eligible (CLAIM_ELIGIBLE_BASES = MEASURED).",
        }
    return {"status": "NO_VALIDATED_EDGE", "passing_groups": [], "claim": "none"}


def replicate(replicate_df: pd.DataFrame, selection: dict[str, Any]) -> dict[str, Any]:
    """Frozen holdout selections run unchanged on the Dukascopy daily series."""
    out: dict[str, Any] = {}
    start, end = P.REPLICATE_START, P.REPLICATE_END
    for group, sel in selection.items():
        cid = sel["cid"]
        if cid is None:
            out[group] = {"cid": None, "status": "NO_SELECTION"}
            continue
        cand = P.candidate_by_id(cid)
        plan = cand.builder(replicate_df)
        first_valid = int(np.argmax(np.isfinite(plan.target))) if np.isfinite(plan.target).any() else len(plan.target)
        evaluable = first_valid <= 0.25 * len(replicate_df)
        if not evaluable:
            out[group] = {
                "cid": cid,
                "status": "NOT_EVALUABLE_INSUFFICIENT_WARMUP",
                "warmup_bars_required": first_valid,
                "window_bars": int(len(replicate_df)),
            }
            continue
        run = run_window(replicate_df, plan, start, end, P.COST_BASE)
        out[group] = {"cid": cid, "status": "EVALUATED", **ST.summarize(run)}
    return out
