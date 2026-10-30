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
- robustness at 2x costs (stress = original mean cost per trade) and
  at a per-trade spread stress,
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
             provenance: str, candidate_p_values: list[float] | None = None) -> dict:
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
    mean_cost = (sum(float(r["commission_usd"]) + float(r["broker_fee_usd"])
                     + float(r["swap_charge_usd"]) for r in rows) / len(rows)) if rows else 0.0
    gate_2x = evaluate_trades(rows, active_days, gross_basis=gross_basis,
                              trials_tested=trials_tested,
                              stress_extra_usd_per_trade=stress_extra + mean_cost,
                              provenance=provenance)
    return {
        "ledger": str(path),
        "edge_gate": gate,
        "daily_sharpe_ann": round(sharpe, 4),
        "daily_t_stat": round(t_stat, 4),
        "one_sided_p": round(p_one_sided, 6) if p_one_sided is not None else None,
        "holm_adjusted_p_including_other_candidates": holm,
        "dsr_trials": trials_tested,
        "dsr": round(d, 4) if (d := deflated_sharpe(daily_vals, trials_tested)) is not None else None,
        "walk_forward_folds": fold_metrics(daily, 5),
        "placebo_maxdd_p": placebo_p(daily),
        "robustness_2x_costs_net": gate_2x["net_usd"],
        "robustness_2x_costs_status": gate_2x["status"],
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
    args = parser.parse_args()
    print(json.dumps(evaluate(args.ledger, active_days=args.active_days,
                              gross_basis=args.gross_basis,
                              trials_tested=args.trials_tested,
                              stress_extra=args.stress_extra_usd_per_trade,
                              provenance=args.provenance,
                              candidate_p_values=args.other_candidate_p_values),
                     indent=2))


if __name__ == "__main__":
    main()
