"""Ledger evaluation for the preregistered adaptive candidates.

This tool does NOT generate trades and does NOT backtest the EA. It
takes a completed-trade ledger (the format edge_gate.py expects, plus
an optional `regime` column for the per-regime audit) and computes:
- the existing edge_gate screen (reused, not reimplemented),
- chronological fold stability (>=5 folds; with frozen rules there is
  no re-optimisation, so a fold is a time slice, not a training window
  — re-fitting on a fold would be a new trial and is NOT done here),
- Holm-Bonferroni over per-candidate one-sided p-values,
- a deflated Sharpe ratio (DSR) approximation (Bailey & Lopez de
  Prado) for a single candidate given the declared trial count,
- a permutation placebo (daily PnL order shuffled; the actual net
  must beat 99% of shuffles to pass),
- REPAIRED 2x-cost robustness (2026-10-30): the previous code
  reported the 1x net under the name "robustness_2x_costs_net"
  (it read gate["net_usd"], which edge_gate never doubles) and its
  mean-cost stress excluded slippage. The repaired figure is the
  true doubled-charge net: gross - 2 * charged, where charged is
  commission + swap + broker fee (+ slippage iff the gross basis is
  PRE_SLIPPAGE, matching edge_gate exactly). Cost multiples 1x/1.5x/
  2x, a doubled-slippage figure, and a parameterised spread stress
  (caller-supplied per-trade spread USD; absent = NOT_MEASURABLE,
  never invented) are reported alongside.
- genuine expanding-window walk-forward (see walk_forward): each
  OOS segment is judged against ALL earlier data with the rule
  frozen before the first segment (no refit, no peeking). The old
  chronological-slice table is kept under "chronological_slices"
  and "walk_forward_folds" for compatibility, but it is NOT
  walk-forward: it is a set of holdout slices with no in-sample /
  out-of-sample structure, and the report must never call it WF.
- counterfactual comparisons on identical costs and trial
  accounting (best static style, random router, shuffled regime
  labels) when per-candidate ledgers are supplied. With a single
  ledger they are NOT_COMPUTABLE, not fabricated from one series.
- per-regime net/PF by decision-time regime only, when the ledger
  carries one (ex-post regime relabelling is refused by construction:
  the column is used as given and must be decision-time).

Costs are labelled by the caller: this tool never invents a broker
commission. A ledger with ASSUMED costs can at most screen as
RESEARCH_POSITIVE_NOT_VALIDATED, never validated — exactly as
edge_gate enforces via provenance. Native MT5 HTML + forensic CSV
remain the required evidence; a Python ledger evaluation is
SCREENING ONLY.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics
from collections import defaultdict
from pathlib import Path

from edge_gate import (
    BASIS_ACTUAL_FILLS,
    BASIS_PRE_SLIPPAGE,
    PROVENANCE_NATIVE,
    PROVENANCE_SIMULATED,
    evaluate_trades,
)

LEDGER_FIELDS = {"trade_id", "date", "gross_usd", "commission_usd",
                 "slippage_usd", "swap_charge_usd", "broker_fee_usd"}


def load_ledger(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not LEDGER_FIELDS.issubset(reader.fieldnames or []):
            raise ValueError("ledger missing required complete-trade fields")
        return list(reader)


def net_series(rows: list[dict], gross_basis: str) -> list[tuple[str, float, str]]:
    """Return (date, net_usd, regime) per completed trade, in file order."""
    out = []
    for row in rows:
        gross = float(row["gross_usd"])
        charged = float(row["commission_usd"]) + float(row["swap_charge_usd"]) \
            + float(row["broker_fee_usd"])
        if gross_basis == BASIS_PRE_SLIPPAGE:
            charged += float(row["slippage_usd"])
        out.append((row["date"], gross - charged, row.get("regime", "") or ""))
    return out


def daily_series(trades: list[tuple[str, float, str]]) -> list[tuple[str, float]]:
    by_day: dict[str, float] = defaultdict(float)
    for date, net, _regime in trades:
        by_day[date] += net
    return [(d, by_day[d]) for d in sorted(by_day)]


def charged_per_trade(row: dict, gross_basis: str) -> float:
    """Explicit charge for one completed trade, exactly as edge_gate.

    commission + swap (signed: a swap credit is negative) + broker fee,
    plus slippage ONLY when the gross basis is PRE_SLIPPAGE. For
    ACTUAL_EXECUTED_FILLS slippage/spread are already inside gross;
    adding them again would double-count. Costs are ASSUMED unless
    the ledger is backed by a measured broker statement.
    """
    charged = float(row["commission_usd"]) + float(row["swap_charge_usd"]) \
        + float(row["broker_fee_usd"])
    if gross_basis == BASIS_PRE_SLIPPAGE:
        charged += float(row["slippage_usd"])
    return charged


def cost_totals(rows: list[dict], gross_basis: str) -> dict:
    gross = sum(float(r["gross_usd"]) for r in rows)
    charged = sum(charged_per_trade(r, gross_basis) for r in rows)
    slip = sum(float(r["slippage_usd"]) for r in rows)
    other = charged - (slip if gross_basis == BASIS_PRE_SLIPPAGE else 0.0)
    return {"gross_usd": gross, "charged_usd": charged,
            "slippage_usd": slip, "other_charges_usd": other,
            "mean_charged_per_trade": charged / len(rows) if rows else 0.0}


def net_at_cost_multiple(rows: list[dict], gross_basis: str, multiple: float) -> float:
    """Net if every explicit charge were multiplied by `multiple`.

    multiple=1.0 reproduces the ledger net; 2.0 is the repaired 2x
    figure. This is arithmetic on stated charges, not a broker
    measurement: spread inside native fills is not re-multiplied
    here (see spread stress, which needs a per-trade spread input).
    """
    totals = cost_totals(rows, gross_basis)
    return totals["gross_usd"] - multiple * totals["charged_usd"]


def net_with_doubled_slippage(rows: list[dict], gross_basis: str) -> float | None:
    """Net with slippage doubled and all other charges at 1x.

    Only defined for PRE_SLIPPAGE ledgers. For ACTUAL_EXECUTED_FILLS
    slippage is already inside gross and has no separate field to
    double; returning a number there would double-count, so None
    (with a reason in the caller) is the correct answer.
    """
    if gross_basis != BASIS_PRE_SLIPPAGE:
        return None
    totals = cost_totals(rows, gross_basis)
    return totals["gross_usd"] - (totals["other_charges_usd"] + 2.0 * totals["slippage_usd"])


def walk_forward(daily: list[tuple[str, float]], folds: int = 5) -> dict:
    """Genuine expanding-window walk-forward for a FROZEN rule.

    The daily series is split into `folds` chronological segments.
    For each fold k >= 1, the in-sample window is ALL days before
    segment k and the out-of-sample window is segment k itself. No
    parameter is fitted, refitted, or selected on any in-sample
    window: the rule was frozen (preregistered) before the first
    segment, so in-sample here is a stability reference, not a
    training window. A refit-based walk-forward would be a different
    design and a new trial, and must not be claimed from this output.

    WFE (walk-forward efficiency) is defined per fold as
        WFE_net    = OOS net / IS net
        WFE_sharpe = OOS Sharpe / IS Sharpe
    When the in-sample denominator is <= 0 the ratio is UNDEFINED
    (None), never clipped to zero or signed away: a negative
    in-sample base makes "efficiency" meaningless, and the fold is
    then judged on its OOS net alone and flagged. The aggregate
    WFE is the mean of the DEFINED per-fold WFEs only, with the
    count of defined folds reported next to it.

    Pass requires: mean OOS Sharpe >= 0.30, at least folds-2 OOS
    segments positive, every defined WFE_net >= 0, and at least
    one defined WFE_net. A single chronological split is a HOLDOUT,
    not walk-forward, and is labelled as such wherever it appears.
    """
    if folds < 5:
        raise ValueError("walk-forward requires >=5 folds")
    if len(daily) < folds:
        return {"method": "expanding-window walk-forward, frozen rules, no refit",
                "folds": folds, "segments": [], "mean_wfe_net": None,
                "defined_wfe_folds": 0, "mean_oos_sharpe": None,
                "positive_oos_segments": 0, "oos_nets": [],
                "pass": False, "reason": "too few trade days for 5 folds"}
    chunk = len(daily) / folds
    bounds = []
    for i in range(folds):
        lo, hi = int(i * chunk), int((i + 1) * chunk)
        if i == folds - 1:
            hi = len(daily)
        bounds.append((lo, hi))
    segments = []
    for k in range(1, folds):
        lo, hi = bounds[k]
        is_vals = [v for _d, v in daily[:lo]]
        oos_vals = [v for _d, v in daily[lo:hi]]
        is_net, oos_net = sum(is_vals), sum(oos_vals)
        is_sharpe, _ = _sharpe_and_t(is_vals)
        oos_sharpe, _ = _sharpe_and_t(oos_vals)
        segments.append({
            "fold": k, "in_sample_days": len(is_vals), "oos_days": len(oos_vals),
            "in_sample_net": round(is_net, 4), "oos_net": round(oos_net, 4),
            "in_sample_sharpe": round(is_sharpe, 4), "oos_sharpe": round(oos_sharpe, 4),
            "wfe_net": round(oos_net / is_net, 4) if is_net > 0 else None,
            "wfe_sharpe": round(oos_sharpe / is_sharpe, 4) if is_sharpe > 0 else None,
        })
    defined = [sg["wfe_net"] for sg in segments if sg["wfe_net"] is not None]
    oos_sharpes = [sg["oos_sharpe"] for sg in segments]
    mean_oos = statistics.fmean(oos_sharpes) if oos_sharpes else None
    positive_oos = sum(1 for sg in segments if sg["oos_net"] > 0)
    passed = bool(mean_oos is not None and mean_oos >= 0.30
                  and positive_oos >= folds - 2 and defined
                  and all(w >= 0 for w in defined))
    return {"method": "expanding-window walk-forward, frozen rules, no refit",
            "folds": folds, "segments": segments,
            "mean_wfe_net": round(statistics.fmean(defined), 4) if defined else None,
            "defined_wfe_folds": len(defined),
            "mean_oos_sharpe": round(mean_oos, 4) if mean_oos is not None else None,
            "positive_oos_segments": positive_oos,
            "oos_nets": [sg["oos_net"] for sg in segments],
            "pass": passed,
            "reason": ("mean OOS Sharpe >=0.30, at least folds-2 OOS segments "
                       "positive, every defined WFE_net >=0, at least one defined WFE")
            if passed else ("walk-forward pass criteria not met; WFE undefined "
                            "when an in-sample denominator is <=0")}


def counterfactuals(candidate_daily: dict[str, list[tuple[str, float]]],
                    seed: int = 6241024, draws: int = 2000) -> dict:
    """Best-static, random-router and MC random-choice comparisons.

    All candidates must be evaluated on the SAME window, costs and
    trial accounting for the comparison to mean anything; the
    caller supplies per-candidate daily series (e.g. one ledger
    per EntryStyle from the same Windows run). Missing days are
    treated as 0.0 (no trade that day). The random router picks one
    candidate uniformly at random each day: its expected daily
    series is the per-day mean across candidates, and the Monte
    Carlo distribution (fixed seed) shows the spread of that
    lottery. A router that cannot beat both the best static
    candidate and the random router on the same data has not
    demonstrated selection skill.
    """
    if len(candidate_daily) < 2:
        return {"status": "NOT_COMPUTABLE",
                "reason": "need >=2 per-candidate daily series for a counterfactual"}
    dates = sorted({d for series in candidate_daily.values() for d, _v in series})
    by_name: dict[str, dict[str, float]] = {}
    for name, series in candidate_daily.items():
        by_name[name] = {d: v for d, v in series}
    per_candidate = {}
    for name, mapping in by_name.items():
        vals = [mapping.get(d, 0.0) for d in dates]
        sharpe, _t = _sharpe_and_t(vals)
        per_candidate[name] = {"net": round(sum(vals), 4), "sharpe_ann": round(sharpe, 4)}
    best_name = max(per_candidate, key=lambda n: per_candidate[n]["net"])
    expected_daily = [statistics.fmean([by_name[n].get(d, 0.0) for n in by_name])
                      for d in dates]
    exp_sharpe, _ = _sharpe_and_t(expected_daily)
    rng = random.Random(seed)
    names = sorted(by_name)
    mc_nets = []
    for _ in range(draws):
        total = 0.0
        for d in dates:
            total += by_name[rng.choice(names)].get(d, 0.0)
        mc_nets.append(total)
    mc_nets.sort()
    return {"status": "COMPUTED",
            "method": "same window/costs; missing day = 0.0; uniform random choice per day",
            "per_candidate": per_candidate,
            "best_static": {"name": best_name, **per_candidate[best_name]},
            "random_router_expected": {"net": round(sum(expected_daily), 4),
                                       "sharpe_ann": round(exp_sharpe, 4)},
            "random_router_mc": {"draws": draws,
                                 "mean_net": round(statistics.fmean(mc_nets), 4),
                                 "p5_net": round(mc_nets[int(0.05 * draws)], 4),
                                 "p95_net": round(mc_nets[int(0.95 * draws)], 4)}}


def shuffled_regime_placebo(trades: list[tuple[str, float, str]],
                            permutations: int = 2000, seed: int = 6241024) -> dict:
    """Placebo: shuffle decision-time regime labels across trades.

    Trade nets and dates are held fixed; only the regime label
    moves. If a regime's actual net is unremarkable against the
    shuffled distribution (placebo_p near or above 0.5 for a
    positive regime), the regime split explains nothing and must
    not be presented as regime skill. This tests the LABELS, not
    the strategy's edge: total net is invariant under shuffling.
    """
    labelled = [(net, regime) for _date, net, regime in trades if regime]
    if len(labelled) < 20:
        return {"status": "NOT_COMPUTABLE",
                "reason": "fewer than 20 regime-labelled trades"}
    rng = random.Random(seed)
    nets = [n for n, _r in labelled]
    labels = [r for _n, r in labelled]
    actual: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    for net, regime in labelled:
        actual[regime] += net
        counts[regime] += 1
    out: dict[str, dict] = {}
    for regime, actual_net in sorted(actual.items()):
        ge = 0
        for _ in range(permutations):
            shuffled = labels[:]
            rng.shuffle(shuffled)
            shuffled_net = sum(n for n, r in zip(nets, shuffled) if r == regime)
            if shuffled_net >= actual_net:
                ge += 1
        out[regime] = {"trades": counts[regime], "net": round(actual_net, 4),
                       "placebo_p_shuffled_net_ge_actual": round(ge / permutations, 4)}
    return {"status": "COMPUTED",
            "method": "regime labels shuffled across trades, nets fixed",
            "per_regime": out}


def _sharpe_and_t(daily: list[float]) -> tuple[float, float]:
    """Annualised Sharpe (252 trading days) and one-sided t-stat of daily mean."""
    if len(daily) < 2:
        return 0.0, 0.0
    mean = statistics.fmean(daily)
    sd = statistics.pstdev(daily)
    if sd <= 0:
        return 0.0, 0.0
    sharpe = mean / sd * math.sqrt(252.0)
    t_stat = mean / (sd / math.sqrt(len(daily)))
    return sharpe, t_stat


def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def holm_adjust(p_values: list[float]) -> list[float]:
    """Holm-Bonferroni adjusted p-values, in original order."""
    n = len(p_values)
    order = sorted(range(n), key=lambda i: p_values[i])
    adjusted = [0.0] * n
    running_max = 0.0
    for rank, idx in enumerate(order):
        adj = min(1.0, (n - rank) * p_values[idx])
        running_max = max(running_max, adj)
        adjusted[idx] = running_max
    return adjusted


def deflated_sharpe(daily: list[float], trials: int) -> float | None:
    """DSR approximation. Returns None when it cannot be computed."""
    if len(daily) < 20 or trials < 1:
        return None
    sharpe, _t = _sharpe_and_t(daily)
    mean = statistics.fmean(daily)
    sd = statistics.pstdev(daily)
    if sd <= 0:
        return None
    skew = sum(((x - mean) / sd) ** 3 for x in daily) / len(daily)
    kurt = sum(((x - mean) / sd) ** 4 for x in daily) / len(daily)
    n = len(daily)
    sr_var = (1.0 - skew * sharpe + (kurt - 1.0) / 4.0 * sharpe ** 2) / (n - 1.0)
    if sr_var <= 0:
        return None
    # Expected maximum Sharpe under the null over `trials` independent
    # trials (Bailey & Lopez de Prado): sqrt(V) * [(1-gamma)*Phi^-1(1-1/T)
    # + gamma*Phi^-1(1-1/(T*e))], gamma = Euler-Mascheroni constant.
    if trials <= 1:
        expected_max = 0.0
    else:
        nd = statistics.NormalDist()
        gamma = 0.5772156649
        expected_max = math.sqrt(sr_var) * (
            (1.0 - gamma) * nd.inv_cdf(1.0 - 1.0 / trials)
            + gamma * nd.inv_cdf(1.0 - 1.0 / (trials * math.e)))
    dsr = _normal_cdf((sharpe - expected_max) / math.sqrt(sr_var))
    return dsr


def fold_metrics(daily: list[tuple[str, float]], folds: int = 5) -> dict:
    """Chronological fold stability. No fitting happens in any fold."""
    if folds < 5:
        raise ValueError("walk-forward requires >=5 folds")
    if len(daily) < folds:
        return {"folds": folds, "fold_nets": [], "mean_fold_net": None,
                "positive_folds": 0, "mean_oos_sharpe": None,
                "pass": False, "reason": "too few trade days for 5 folds"}
    chunk = len(daily) / folds
    fold_nets, fold_sharpes = [], []
    for i in range(folds):
        lo, hi = int(i * chunk), int((i + 1) * chunk)
        if i == folds - 1:
            hi = len(daily)
        vals = [v for _d, v in daily[lo:hi]]
        fold_nets.append(round(sum(vals), 4))
        s, _t = _sharpe_and_t(vals)
        fold_sharpes.append(round(s, 4))
    mean_sharpe = statistics.fmean(fold_sharpes) if fold_sharpes else None
    return {"folds": folds, "fold_nets": fold_nets,
            "mean_fold_net": round(statistics.fmean(fold_nets), 4),
            "positive_folds": sum(1 for v in fold_nets if v > 0),
            "mean_oos_sharpe": round(mean_sharpe, 4) if mean_sharpe is not None else None,
            "pass": bool(mean_sharpe is not None and mean_sharpe >= 0.30
                         and sum(1 for v in fold_nets if v > 0) >= folds - 1),
            "reason": "mean fold Sharpe >=0.30 and at most one negative fold"}


def placebo_p(daily: list[tuple[str, float]], seed: int = 6241024,
              permutations: int = 2000) -> float | None:
    """Permutation placebo: shuffle daily PnL order, compare total net."""
    if len(daily) < 20:
        return None
    # Shuffling preserves the multiset, so the total net is invariant;
    # the informative placebo statistic is therefore the *sequence*
    # statistic: maximum drawdown of the equity curve. A genuine edge
    # with steady accumulation has a smaller drawdown than most
    # shuffles of the same daily returns; a lucky run of a few large
    # days does not. Returns the fraction of shuffles whose drawdown
    # is at least the actual one (small = sequence skill unproven).
    rng = random.Random(seed)
    values = [v for _d, v in daily]

    def max_dd(seq: list[float]) -> float:
        peak = bal = dd = 0.0
        for v in seq:
            bal += v
            peak = max(peak, bal)
            dd = max(dd, peak - bal)
        return dd

    actual_dd = max_dd(values)
    better = 0
    for _ in range(permutations):
        shuffled = values[:]
        rng.shuffle(shuffled)
        if max_dd(shuffled) >= actual_dd:
            better += 1
    return better / permutations


def per_regime(trades: list[tuple[str, float, str]]) -> dict:
    by_regime: dict[str, list[float]] = defaultdict(list)
    for _date, net, regime in trades:
        if regime:
            by_regime[regime].append(net)
    out = {}
    for regime, vals in sorted(by_regime.items()):
        gain = sum(v for v in vals if v > 0)
        loss = -sum(v for v in vals if v < 0)
        out[regime] = {"trades": len(vals), "net": round(sum(vals), 4),
                       "profit_factor": round(gain / loss, 4) if loss > 0 else None}
    return out


def evaluate(path: Path, *, active_days: int, gross_basis: str,
             trials_tested: int, stress_extra: float,
             provenance: str, candidate_p_values: list[float] | None = None,
             spread_usd_per_trade: float | None = None,
             candidate_ledgers: dict[str, Path] | None = None) -> dict:
    rows = load_ledger(path)
    gate = evaluate_trades(rows, active_days, gross_basis=gross_basis,
                           trials_tested=trials_tested,
                           stress_extra_usd_per_trade=stress_extra,
                           provenance=provenance)
    trades = net_series(rows, gross_basis)
    daily = daily_series(trades)
    daily_vals = [v for _d, v in daily]
    sharpe, t_stat = _sharpe_and_t(daily_vals)
    p_one_sided = 1.0 - _normal_cdf(t_stat) if daily_vals else None
    holm = None
    if candidate_p_values is not None and p_one_sided is not None:
        holm = holm_adjust(candidate_p_values + [p_one_sided])[-1]
    # REPAIRED 2x (2026-10-30): the previous code passed
    # stress_extra + mean_cost (excluding slippage) and then reported
    # gate["net_usd"] — the UNDOUBLED net — as the "2x" figure. The
    # repaired gate passes stress = mean charged per trade (slippage
    # included iff PRE_SLIPPAGE, matching edge_gate), so its
    # stressed_net_usd IS gross - 2*charged. The reported 2x figure
    # is that stressed net, never the 1x net.
    totals = cost_totals(rows, gross_basis)
    mean_charged = totals["mean_charged_per_trade"]
    gate_2x = evaluate_trades(rows, active_days, gross_basis=gross_basis,
                              trials_tested=trials_tested,
                              stress_extra_usd_per_trade=mean_charged,
                              provenance=provenance)
    spread_robustness: dict = {}
    if spread_usd_per_trade is None:
        spread_robustness = {
            "status": "NOT_MEASURABLE",
            "reason": ("ledger carries no per-trade spread USD; spread "
                       "inside native fills cannot be re-stressed without "
                       "inventing a number. Supply --spread-usd-per-trade "
                       "(ASSUMED unless measured) or rerun natively with "
                       "a doubled spread model as a separate trial.")}
    else:
        n_trades = len(rows)
        spread_robustness = {
            "status": "COMPUTED_FROM_SUPPLIED_SPREAD",
            "spread_usd_per_trade": spread_usd_per_trade,
            "note": ("ASSUMED unless the caller asserts a measured "
                     "broker spread; this tool does not verify it."),
            "net_spread_1.5x": round(gate["net_usd"] - 0.5 * spread_usd_per_trade * n_trades, 4),
            "net_spread_2x": round(gate["net_usd"] - 1.0 * spread_usd_per_trade * n_trades, 4)}
    if candidate_ledgers:
        cand_daily = {}
        for name, cpath in candidate_ledgers.items():
            cand_daily[name] = daily_series(net_series(load_ledger(cpath), gross_basis))
        counter = counterfactuals(cand_daily)
    else:
        counter = {"status": "NOT_COMPUTABLE",
                   "reason": ("no per-candidate ledgers supplied; a single "
                              "ledger cannot fabricate a best-static or "
                              "random-router comparison")}
    return {
        "ledger": str(path),
        "edge_gate": gate,
        "daily_sharpe_ann": round(sharpe, 4),
        "daily_t_stat": round(t_stat, 4),
        "one_sided_p": round(p_one_sided, 6) if p_one_sided is not None else None,
        "holm_adjusted_p_including_other_candidates": holm,
        "dsr_trials": trials_tested,
        "dsr": round(d, 4) if (d := deflated_sharpe(daily_vals, trials_tested)) is not None else None,
        "chronological_slices": fold_metrics(daily, 5),
        "walk_forward_folds": fold_metrics(daily, 5),
        "walk_forward": walk_forward(daily, 5),
        "counterfactuals": counter,
        "shuffled_regime_placebo": shuffled_regime_placebo(trades),
        "placebo_maxdd_p": placebo_p(daily),
        "cost_multiples_net": {
            "1.0x": round(net_at_cost_multiple(rows, gross_basis, 1.0), 4),
            "1.5x": round(net_at_cost_multiple(rows, gross_basis, 1.5), 4),
            "2.0x": round(net_at_cost_multiple(rows, gross_basis, 2.0), 4)},
        "robustness_2x_costs_net": gate_2x["stressed_net_usd"],
        "robustness_2x_costs_status": gate_2x["status"],
        "robustness_2x_costs_mean_charged_per_trade": round(mean_charged, 4),
        "robustness_slippage_doubled_net": (
            round(net_with_doubled_slippage(rows, gross_basis), 4)
            if net_with_doubled_slippage(rows, gross_basis) is not None else None),
        "robustness_slippage_doubled_note": (
            "slippage doubled, other charges at 1x (PRE_SLIPPAGE only)"
            if gross_basis == BASIS_PRE_SLIPPAGE else
            "NOT_APPLICABLE: slippage already inside gross for ACTUAL_EXECUTED_FILLS; doubling its diagnostic field would double-count"),
        "robustness_spread": spread_robustness,
        "per_regime_decision_time_only": per_regime(trades),
        "cost_basis_note": "Costs are as stated in the ledger; this tool does not "
                          "verify them against a broker statement.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Ledger evaluation (screening only)")
    parser.add_argument("ledger", type=Path)
    parser.add_argument("--active-days", type=int, required=True)
    parser.add_argument("--gross-basis", choices=(BASIS_PRE_SLIPPAGE, BASIS_ACTUAL_FILLS),
                        default=BASIS_PRE_SLIPPAGE)
    parser.add_argument("--trials-tested", type=int, required=True)
    parser.add_argument("--stress-extra-usd-per-trade", type=float, required=True)
    parser.add_argument("--provenance", choices=(PROVENANCE_NATIVE, PROVENANCE_SIMULATED),
                        default=PROVENANCE_SIMULATED)
    parser.add_argument("--other-candidate-p-values", type=float, nargs="*", default=None)
    parser.add_argument("--spread-usd-per-trade", type=float, default=None,
                        help="ASSUMED per-trade spread USD for spread stress; absent = NOT_MEASURABLE")
    parser.add_argument("--candidate-ledger", action="append", default=[],
                        help="NAME=PATH, repeatable; per-candidate ledgers for counterfactuals")
    args = parser.parse_args()
    cand: dict[str, Path] = {}
    for spec in args.candidate_ledger:
        name, _, cpath = spec.partition("=")
        if not name or not cpath:
            raise ValueError("--candidate-ledger must be NAME=PATH")
        cand[name] = Path(cpath)
    print(json.dumps(evaluate(args.ledger, active_days=args.active_days,
                              gross_basis=args.gross_basis,
                              trials_tested=args.trials_tested,
                              stress_extra=args.stress_extra_usd_per_trade,
                              provenance=args.provenance,
                              candidate_p_values=args.other_candidate_p_values,
                              spread_usd_per_trade=args.spread_usd_per_trade,
                              candidate_ledgers=cand or None),
                     indent=2))


if __name__ == "__main__":
    main()
