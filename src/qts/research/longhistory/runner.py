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
    # the window includes every bar stamped on ``end``: search the next midnight, left side.
    # For a daily (midnight-stamped) index this equals searchsorted(end, side="right").
    i1 = int(idx.searchsorted(pd.Timestamp(end) + pd.Timedelta(days=1), side="left"))
    if i1 - i0 < 2:
        raise ValueError(f"window {start}..{end} has fewer than two trading days")
    return i0, i1


def build_plans(df: pd.DataFrame, proto: Any = P) -> dict[str, Plan]:
    return {c.cid: c.builder(df) for c in proto.CANDIDATES}


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
    proto: Any = P,
) -> dict[str, dict[str, Any]]:
    """Pick the training-window winner in each family group (base costs)."""
    chosen: dict[str, dict[str, Any]] = {}
    for group in proto.FAMILY_GROUPS:
        best: tuple[float, str] | None = None
        table = []
        for cand in proto.candidates_in(group):
            run = run_window(df, plans[cand.cid], train_start, train_end, proto.COST_BASE)
            sr = ST.sharpe(run.returns, proto.PERIODS_PER_YEAR)
            turns = len(run.trades)
            eligible = turns >= proto.MIN_TRAIN_ROUND_TURNS
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


def walk_forward(df: pd.DataFrame, plans: dict[str, Plan], proto: Any = P) -> dict[str, Any]:
    """Expanding-window selection, one test year per fold, frozen within each fold."""
    years: list[dict[str, Any]] = []
    composite_returns: dict[str, list[np.ndarray]] = {g: [] for g in proto.FAMILY_GROUPS}
    composite_pnl: dict[str, list[tuple[pd.DatetimeIndex, np.ndarray]]] = {g: [] for g in proto.FAMILY_GROUPS}
    first = str(pd.DatetimeIndex(df.index)[0].date())
    for year in proto.WF_TEST_YEARS:
        train_end = f"{year - 1}-12-31"
        test_start, test_end = f"{year}-01-01", f"{year}-12-31"
        selection = select_per_group(df, plans, first, train_end, proto)
        year_rec: dict[str, Any] = {"year": year, "selection": {}}
        for group, sel in selection.items():
            cid = sel["cid"]
            if cid is None:
                year_rec["selection"][group] = {"cid": None, "net_usd": 0.0, "sharpe": 0.0, "round_turns": 0}
                continue
            run = run_window(df, plans[cid], test_start, test_end, proto.COST_BASE)
            year_rec["selection"][group] = {
                "cid": cid,
                "train_sharpe": sel["train_sharpe"],
                "net_usd": round(run.net_usd, 2),
                "sharpe": round(ST.sharpe(run.returns, proto.PERIODS_PER_YEAR), 4),
                "round_turns": len(run.trades),
            }
            composite_returns[group].append(run.returns)
            composite_pnl[group].append((run.days, np.diff(np.concatenate([[run.initial_equity], run.equity]))))
        years.append(year_rec)
    return {"folds": years, "composite_returns": composite_returns, "composite_pnl": composite_pnl}


def holdout(df: pd.DataFrame, plans: dict[str, Plan], end: str, proto: Any = P) -> dict[str, Any]:
    """Select once on data through DEV_END, then run the frozen choice once on the holdout."""
    first = str(pd.DatetimeIndex(df.index)[0].date())
    selection = select_per_group(df, plans, first, proto.DEV_END, proto)
    out: dict[str, Any] = {"selection": selection, "groups": {}}
    for group, sel in selection.items():
        cid = sel["cid"]
        if cid is None:
            out["groups"][group] = {"cid": None}
            continue
        plan = plans[cid]
        base = run_window(df, plan, proto.HOLDOUT_START, end, proto.COST_BASE)
        stress = {
            f"{m:g}x": run_window(df, plan, proto.HOLDOUT_START, end, proto.COST_BASE.scaled(m))
            for m in proto.COST_STRESS_MULTIPLIERS
        }
        zero = run_window(df, plan, proto.HOLDOUT_START, end, proto.COST_BASE.scaled(0.0))
        out["groups"][group] = {
            "cid": cid,
            "base": base,
            "stress": stress,
            "gross_zero_cost": zero,
            "break_even_multiplier": break_even_multiplier(df, plan, proto.HOLDOUT_START, end),
            "sign_randomisation_p": sign_randomisation_p(base),
        }
    return out


def buy_and_hold(df: pd.DataFrame, start: str, end: str, costs: CostModel) -> RunResult:
    """Reference baseline: long 1.0x notional through the same engine and cost model.

    The decision sits on the bar before the window, so the fill is the window's
    first open. If the window starts at the first bar of the file there is no
    prior bar, and the entry is one bar later (open of bar 2), which is stated in
    the output via ``entry_delay_bars``.
    """
    i0, i1 = window_positions(df, start, end)
    anchor = i0 - 1 if i0 >= 1 else 0
    n = len(df)
    decision = anchor
    target = np.full(n, np.nan)
    target[decision] = 1.0
    size = np.full(n, np.nan)
    size[decision] = 1.0
    plan = Plan(
        target=target,
        size=size,
        stop_dist=np.full(n, np.nan),
        rebalance=np.zeros(n, dtype=bool),
        family="buy_and_hold",
        params={"long_fraction": 1.0, "entry_delay_bars": int(1 if i0 == 0 else 0)},
    )
    run = run_plan(df, plan, anchor, i1, costs, initial_equity=P.INITIAL_EQUITY, force_close_end=True)
    if i0 >= 1:
        # drop the anchor bar so the reported days start at the window; equity starts at E0
        return RunResult(
            days=run.days[1:],
            equity=run.equity[1:],
            returns=run.returns[1:],
            held=run.held[1:],
            trades=run.trades,
            initial_equity=P.INITIAL_EQUITY,
            turnover_fraction=run.turnover_fraction,
            financing_usd=run.financing_usd,
            cost_usd=run.cost_usd,
            gross_usd=run.gross_usd,
            cost_basis=run.cost_basis,
        )
    return run


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


def regime_labels(df: pd.DataFrame, proto: Any = P) -> pd.Series:
    """Causal, mechanical regimes: trend (12-month return sign) x volatility (vs expanding median)."""
    close = df["close"]
    trend = np.sign(close / close.shift(proto.REGIME_TREND_BARS) - 1.0)
    vol = realized_vol(close, proto.VOL_BARS, proto.PERIODS_PER_YEAR)
    vol_med = vol.expanding(min_periods=proto.REGIME_MIN_BARS).median()
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
    # vectorised lookup: a day with no label (None/NaN) never matches a regime name
    aligned = labels.reindex(pd.DatetimeIndex(days)).to_numpy() if len(days) else np.array([], dtype=object)
    for regime in ["UP_HIVOL", "UP_LOWVOL", "DOWN_HIVOL", "DOWN_LOWVOL"]:
        mask = np.asarray(aligned == regime, dtype=bool)
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
    proto: Any = P,
) -> dict[str, Any]:
    """Run the protocol and return the full, JSON-serialisable result record."""
    ppy = proto.PERIODS_PER_YEAR
    wf = walk_forward(df, plans, proto)
    result: dict[str, Any] = {
        "prereg_id": proto.PREREG_ID,
        "stage": stage,
        "n_trials": proto.N_TRIALS,
        "periods_per_year": ppy,
        "cost_base": proto.COST_BASE.describe(),
        "windows": {
            "research": [proto.RESEARCH_START, proto.RESEARCH_END],
            "dev_end": proto.DEV_END,
            "holdout": [proto.HOLDOUT_START, proto.RESEARCH_END],
            "wf_test_years": list(proto.WF_TEST_YEARS),
        },
        "walk_forward": {"folds": wf["folds"]},
    }
    labels = regime_labels(df, proto)
    wf_summary: dict[str, Any] = {}
    combined: dict[str, np.ndarray] = {}
    for group in proto.FAMILY_GROUPS:
        rets = wf["composite_returns"][group]
        joined = np.concatenate(rets) if rets else np.array([])
        combined[group] = joined
        years_pos = sum(1 for f in wf["folds"] if f["selection"][group]["cid"] and f["selection"][group]["net_usd"] > 0)
        years_traded = sum(
            1 for f in wf["folds"] if f["selection"][group]["cid"] and f["selection"][group]["round_turns"] > 0
        )
        wf_summary[group] = {
            "wf_sharpe": round(ST.sharpe(joined, ppy), 4) if joined.size else 0.0,
            "wf_positive_years": years_pos,
            "wf_years_with_trades": years_traded,
            "wf_chained_return": round(float(np.prod(1.0 + joined) - 1.0), 4) if joined.size else 0.0,
            "wf_regimes": regime_attribution(wf["composite_pnl"][group], labels),
        }
    result["walk_forward"]["summary"] = wf_summary

    if stage == "final":
        ho = holdout(df, plans, proto.RESEARCH_END, proto)
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
                "base": ST.summarize(base, num_trials=proto.N_TRIALS, periods_per_year=ppy),
                "stress": {k: ST.summarize(v, periods_per_year=ppy) for k, v in rec["stress"].items()},
                "gross_zero_cost_usd": round(rec["gross_zero_cost"].net_usd, 2),
                "break_even_multiplier": rec["break_even_multiplier"],
                "sign_randomisation": rec["sign_randomisation_p"],
                "bootstrap_sharpe": ST.sharpe_interval(base.returns, periods_per_year=ppy),
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
        result["holdout_selection_summary"] = {g: ho["selection"][g]["cid"] for g in proto.FAMILY_GROUPS}

        if replicate_df is not None:
            result["replicate"] = replicate(replicate_df, ho["selection"], proto)

    result["benchmarks"] = benchmarks(df, replicate_df if stage == "final" else None, stage, proto)
    result["gates"] = gates(result, combined, labels, stage, proto)
    result["verdict"] = verdict(result)
    return result


def benchmarks(df: pd.DataFrame, replicate_df: pd.DataFrame | None, stage: str, proto: Any = P) -> dict[str, Any]:
    """Reference baseline (not a gate): long buy-and-hold through the same engine and costs."""
    ppy = proto.PERIODS_PER_YEAR
    out: dict[str, Any] = {"buy_and_hold_long": {}}
    years_returns: list[np.ndarray] = []
    for year in proto.WF_TEST_YEARS:
        run = buy_and_hold(df, f"{year}-01-01", f"{year}-12-31", proto.COST_BASE)
        years_returns.append(run.returns)
    combined = np.concatenate(years_returns)
    out["buy_and_hold_long"]["wf_2010_2019_composite"] = {
        "sharpe": round(ST.sharpe(combined, ppy), 4),
        "chained_return": round(float(np.prod(1.0 + combined) - 1.0), 4),
        "max_drawdown": round(ST.max_drawdown(np.cumprod(1.0 + combined)), 4),
        "years": len(proto.WF_TEST_YEARS),
    }
    if stage == "final":
        ho = buy_and_hold(df, proto.HOLDOUT_START, proto.RESEARCH_END, proto.COST_BASE)
        out["buy_and_hold_long"]["holdout"] = ST.summarize(ho, periods_per_year=ppy)
        out["buy_and_hold_long"]["holdout_2x_cost_net_usd"] = round(
            buy_and_hold(df, proto.HOLDOUT_START, proto.RESEARCH_END, proto.COST_BASE.scaled(2.0)).net_usd, 2
        )
        if replicate_df is not None:
            rep = buy_and_hold(replicate_df, proto.REPLICATE_START, proto.REPLICATE_END, proto.COST_BASE)
            out["buy_and_hold_long"]["replicate"] = ST.summarize(rep, periods_per_year=ppy)
    return out


def gates(
    result: dict[str, Any], combined: dict[str, np.ndarray], labels: pd.Series, stage: str, proto: Any = P
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if stage != "final":
        return {"status": "NOT_EVALUATED_DEV_STAGE", "reason": "holdout not evaluated in dev stage"}
    ho = result["holdout"]["groups"]
    wf = result["walk_forward"]["summary"]
    ppy = proto.PERIODS_PER_YEAR
    for group in proto.FAMILY_GROUPS:
        rec = ho.get(group, {})
        if not rec.get("cid"):
            out[group] = {"G0_candidate_selected": "FAIL", "failed": ["no eligible candidate"]}
            continue
        base = rec["base"]
        stress2 = rec["stress"]["2x"]
        oos = combined[group]
        dsr = ST.deflated_sharpe(oos, proto.N_TRIALS, ppy) if oos.size else {"dsr": float("nan")}
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
            and wf[group]["wf_positive_years"] >= proto.GATE_WF_MIN_POSITIVE_YEARS,
            "G4_holm_adjusted_p_le_alpha": rec["holm_adjusted_p"] <= proto.GATE_HOLM_ALPHA,
            "G5_dsr_ge_threshold": bool(dsr.get("dsr", 0.0) >= proto.GATE_DSR_MIN),
            "G6_oos_round_turns_ge_100": oos_turns >= proto.MIN_TRADES_OOS_GATE,
            "G7_regime_coverage": all_present and positive_regimes >= proto.GATE_REGIMES_MIN_POSITIVE,
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


def replicate(replicate_df: pd.DataFrame, selection: dict[str, Any], proto: Any = P) -> dict[str, Any]:
    """Frozen holdout selections run unchanged on the replicate series (daily or M15)."""
    out: dict[str, Any] = {}
    start, end = proto.REPLICATE_START, proto.REPLICATE_END
    for group, sel in selection.items():
        cid = sel["cid"]
        if cid is None:
            out[group] = {"cid": None, "status": "NO_SELECTION"}
            continue
        cand = proto.candidate_by_id(cid)
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
        run = run_window(replicate_df, plan, start, end, proto.COST_BASE)
        out[group] = {"cid": cid, "status": "EVALUATED", **ST.summarize(run, periods_per_year=proto.PERIODS_PER_YEAR)}
    return out


def render_tables(result: dict[str, Any]) -> str:
    """Markdown tables generated from the result record (no numbers typed by hand)."""
    lines: list[str] = []
    lines.append(f"# Long-history XAUUSD results — generated tables ({result['prereg_id']}, stage {result['stage']})")
    lines.append("")
    lines.append(f"Verdict: **{result['verdict']['status']}**. Claim: {result['verdict']['claim']}")
    lines.append("")
    lines.append("## Holdout 2020-01-01 → 2025-02-28 (selection frozen on data through 2019-12-31)")
    lines.append("")
    lines.append(
        "| Group | Selected | Net USD | Sharpe | 95% CI (Sharpe) | Max DD | Round turns | Win rate | Cost USD | Net @2x | Net @3x | Break-even cost x | Holm p | Exposure |"
    )
    lines.append("|---|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---|---:|---:|")
    for group, rec in result["holdout"]["groups"].items():
        if not rec.get("cid"):
            continue
        b = rec["base"]
        ci = rec["bootstrap_sharpe"]
        be = rec["break_even_multiplier"]
        be_txt = f"{be['value']} ({be['status']})"
        lines.append(
            f"| {group} | {rec['cid']} | {b['net_usd']:,.2f} | {b['sharpe']:.3f} | "
            f"[{ci['ci95_low']:.2f}, {ci['ci95_high']:.2f}] | {b['max_drawdown']:.1%} | {b['round_turns']} | "
            f"{b['win_rate']:.0%} | {b['cost_usd']:,.2f} | {rec['stress']['2x']['net_usd']:,.2f} | "
            f"{rec['stress']['3x']['net_usd']:,.2f} | {be_txt} | {rec['holm_adjusted_p']:.2f} | {b['exposure']:.0%} |"
        )
    bh = result.get("benchmarks", {}).get("buy_and_hold_long", {})
    if "holdout" in bh:
        h = bh["holdout"]
        lines.append(
            f"| **buy_and_hold_long (reference)** | 1.0x long | {h['net_usd']:,.2f} | {h['sharpe']:.3f} | — | "
            f"{h['max_drawdown']:.1%} | {h['round_turns']} | — | {h['cost_usd']:,.2f} | "
            f"{bh['holdout_2x_cost_net_usd']:,.2f} | — | — | — | 100% |"
        )
    lines.append("")
    lines.append("## Walk-forward 2010–2019 (per-year selection, frozen within each year)")
    lines.append("")
    lines.append("| Group | WF Sharpe | Positive years | Years traded | Chained return |")
    lines.append("|---|---:|---:|---:|---:|")
    for group, rec in result["walk_forward"]["summary"].items():
        lines.append(
            f"| {group} | {rec['wf_sharpe']:.3f} | {rec['wf_positive_years']}/10 | {rec['wf_years_with_trades']} | "
            f"{rec['wf_chained_return']:.1%} |"
        )
    wb = bh.get("wf_2010_2019_composite", {})
    if wb:
        lines.append(f"| **buy_and_hold_long (reference)** | {wb['sharpe']:.3f} | — | — | {wb['chained_return']:.1%} |")
    lines.append("")
    lines.append("## Gates (G1–G7; all must pass)")
    lines.append("")
    lines.append("| Group | Candidate | G1 | G2 | G3 | G4 | G5 | G6 | G7 | DSR | OOS round turns | Passes |")
    lines.append("|---|---|---|---|---|---|---|---|---|---:|---:|---|")
    for group, rec in result["gates"].items():
        if not isinstance(rec, dict) or "checks" not in rec:
            continue
        c = rec["checks"]
        cells = [c[k] for k in sorted(c)]
        lines.append(
            f"| {group} | {rec['cid']} | " + " | ".join(cells) + f" | {rec['dsr']:.3f} | {rec['oos_round_turns']} | "
            f"{'YES' if rec['passes_all'] else 'no'} |"
        )
    lines.append("")
    lines.append("## Regimes (out-of-sample net USD, WF 2010–2019 plus holdout)")
    lines.append("")
    regime_names = ["UP_HIVOL", "UP_LOWVOL", "DOWN_HIVOL", "DOWN_LOWVOL"]
    lines.append("| Group | " + " | ".join(regime_names) + " |")
    lines.append("|---|" + "---:|" * len(regime_names))
    for group, rec in result["gates"].items():
        if not isinstance(rec, dict) or "regimes_oos" not in rec:
            continue
        cells = [f"{rec['regimes_oos'][r]['net_usd']:,.2f} ({rec['regimes_oos'][r]['days']}d)" for r in regime_names]
        lines.append(f"| {group} | " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("## Dukascopy replicate 2025-08-06 → 2026-09-16 (frozen holdout selections, unchanged)")
    lines.append("")
    lines.append("| Group | Candidate | Status | Net USD | Sharpe | Round turns |")
    lines.append("|---|---|---|---:|---:|---:|")
    for group, rec in result.get("replicate", {}).items():
        if rec.get("status") == "EVALUATED":
            lines.append(
                f"| {group} | {rec['cid']} | EVALUATED | {rec['net_usd']:,.2f} | {rec['sharpe']:.3f} | {rec['round_turns']} |"
            )
        else:
            lines.append(f"| {group} | {rec.get('cid')} | {rec['status']} | — | — | — |")
    rb = bh.get("replicate")
    if rb:
        lines.append(
            f"| **buy_and_hold_long (reference)** | 1.0x long | EVALUATED | {rb['net_usd']:,.2f} | {rb['sharpe']:.3f} | {rb['round_turns']} |"
        )
    lines.append("")
    lines.append("## Sign-randomisation null (trade-level, approximate)")
    lines.append("")
    lines.append("| Group | Trades | Observed net (approx.) | p-value |")
    lines.append("|---|---:|---:|---:|")
    for group, rec in result["holdout"]["groups"].items():
        if rec.get("cid"):
            sr = rec["sign_randomisation"]
            lines.append(f"| {group} | {sr['trades']} | {sr['observed_net_approx']:,.2f} | {sr['p_value']:.3f} |")
    lines.append("")
    return "\n".join(lines) + "\n"
