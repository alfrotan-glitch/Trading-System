"""Fail-closed research-only after-cost screen for XAUUSD trading strategies.

This module NEVER submits orders. Explicit gross price basis, trial count,
and trade identifiers prevent optimistic reports from unverifiable inputs.
Each row is one COMPLETED trade, not a partial MT5 close deal.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics
from collections import defaultdict
from datetime import date as Date
from pathlib import Path

BASIS_PRE_SLIPPAGE = "PRE_SLIPPAGE_REFERENCE"
BASIS_ACTUAL_FILLS = "ACTUAL_EXECUTED_FILLS"
PROVENANCE_NATIVE = "BROKER_NATIVE"
PROVENANCE_SIMULATED = "SIMULATED"
BOOTSTRAPS = 2000
BLOCK_TRADE_DAYS = 7


def _date(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("date must be YYYY-MM-DD")
    try:
        parsed = Date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("invalid Gregorian date") from exc
    if parsed.isoformat() != value:
        raise ValueError("date must be YYYY-MM-DD")
    return value


def _number(value: object, field: str, *, signed: bool = False) -> float:
    try:
        result = float(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"invalid {field}") from exc
    if not math.isfinite(result) or (not signed and result < 0):
        raise ValueError(f"invalid {field}")
    return result


def evaluate_trades(
    rows: list[dict],
    active_days: int,
    seed: int = 6241024,
    *,
    gross_basis: str,
    trials_tested: int,
    stress_extra_usd_per_trade: float,
    provenance: str,
) -> dict:
    """Conservative screen; independent future holdout is always required.

    active_days counts independently known active market days, including
    days with no executions. The bootstrap is conditional on trade-days;
    it must not be mistaken for a calendar-day confidence interval.
    """
    if not isinstance(active_days, int) or isinstance(active_days, bool) or not 1 <= active_days <= 36525:
        raise ValueError("active_days must be a positive bounded integer")
    if not isinstance(trials_tested, int) or isinstance(trials_tested, bool) or trials_tested < 1:
        raise ValueError("trials_tested must disclose all attempted variants")
    if gross_basis not in (BASIS_PRE_SLIPPAGE, BASIS_ACTUAL_FILLS):
        raise ValueError("gross_basis must declare exact P&L pricing convention")
    if provenance not in (PROVENANCE_NATIVE, PROVENANCE_SIMULATED):
        raise ValueError("provenance must be explicit")
    stress = _number(stress_extra_usd_per_trade, "additional stress cost")

    by_day: dict[str, list[float]] = defaultdict(list)
    seen_ids: set[str] = set()
    costs = gross = slip_diagnostic = 0.0
    for row in rows:
        day = _date(row.get("date"))
        trade_id = row.get("trade_id")
        if not isinstance(trade_id, str) or not trade_id.strip() or trade_id in seen_ids:
            raise ValueError("missing or duplicate completed trade_id")
        seen_ids.add(trade_id)
        g = _number(row.get("gross_usd"), "gross_usd", signed=True)
        c = _number(row.get("commission_usd"), "commission_usd")
        s = _number(row.get("slippage_usd"), "slippage_usd", signed=True)
        if gross_basis == BASIS_PRE_SLIPPAGE and s < 0:
            raise ValueError("pre-slippage basis requires nonnegative slippage charge")
        # For ACTUAL_EXECUTED_FILLS spread/slippage are ALREADY priced in gross.
        charged = c + (s if gross_basis == BASIS_PRE_SLIPPAGE else 0.0)
        by_day[day].append(g - charged)
        costs += charged
        gross += g
        slip_diagnostic += s
    if len(by_day) > active_days:
        raise ValueError("more trading days than declared active market days")

    ordered_days = sorted(by_day)
    values = [v for day in ordered_days for v in by_day[day]]
    net = sum(values)
    gain = sum(v for v in values if v > 0)
    loss = -sum(v for v in values if v < 0)
    pf = gain / loss if loss > 0 else None
    win_rate = sum(v > 0 for v in values) / len(values) if values else None
    peak = balance = max_dd = 0.0
    for v in values:
        balance += v
        peak = max(peak, balance)
        max_dd = max(max_dd, peak - balance)

    rng = random.Random(seed)
    boots: list[float] = []
    if len(ordered_days) >= 20:
        n = len(ordered_days)
        for _ in range(BOOTSTRAPS):
            sample_days: list[list[float]] = []
            while len(sample_days) < n:
                start = rng.randrange(n)
                sample_days.extend(
                    by_day[ordered_days[(start + offset) % n]]
                    for offset in range(BLOCK_TRADE_DAYS)
                )
            resampled = [v for group in sample_days[:n] for v in group]
            boots.append(statistics.fmean(resampled))
        boots.sort()
    # A corrected one-percent tail cannot be estimated with too few
    # bootstrap draws for the number of tested variants: fail closed.
    tail_fraction = 0.01 / trials_tested
    has_tail_resolution = BOOTSTRAPS * tail_fraction >= 5
    lower = boots[max(0, int(BOOTSTRAPS * tail_fraction) - 1)] if boots and has_tail_resolution else None
    unique_months = len({d[:7] for d in ordered_days})
    stressed_net = net - stress * len(values)
    sufficient = (
        len(values) >= 100 and active_days >= 40
        and len(by_day) >= 20 and unique_months >= 3
        and provenance == PROVENANCE_NATIVE and stress > 0
        and has_tail_resolution
    )
    positive = (
        sufficient and net > 0 and stressed_net > 0 and pf is not None
        and pf > 1.15 and lower is not None and lower > 0
    )
    return {
        "trades": len(values),
        "active_days": active_days,
        "days_with_trades": len(by_day),
        "months_with_trades": unique_months,
        "trades_per_active_day": len(values) / active_days,
        "gross_basis": gross_basis,
        "declared_provenance_unverified": provenance,
        "trials_tested": trials_tested,
        "net_usd": round(net, 4),
        "gross_usd": round(gross, 4),
        "explicit_cost_usd_deducted": round(costs, 4),
        "observed_slippage_usd_already_in_fill_gross": round(slip_diagnostic, 4) if gross_basis == BASIS_ACTUAL_FILLS else None,
        "stress_extra_usd_per_trade": stress,
        "stressed_net_usd": round(stressed_net, 4),
        "win_rate": win_rate,
        "profit_factor": pf,
        "max_closed_equity_drawdown_usd": max_dd,
        "bootstrap_multiplicity_adjusted_99pct_lower_expectancy_usd": lower,
        "status": "RESEARCH_POSITIVE_NOT_VALIDATED" if positive else "REJECTED_OR_INSUFFICIENT_EVIDENCE",
        "warnings": [
            "A positive research screen never proves out-of-sample or live profitability.",
            "Provenance, trial counts, active days, and cost basis are user assertions, not authenticated broker data.",
            "Trade-day bootstrap excludes no-trade days and is NOT a calendar-day confidence interval.",
            "Drawdown is closed-trade only: no floating equity or gap loss measurement.",
            "CSV must contain completed trades with all entry/exit charges, never partial exit deal rows.",
            "Unseen broker ticks and native MT5 execution are still needed; LIVE remains locked.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only after-cost edge screen")
    parser.add_argument("trades", type=Path, help="CSV: trade_id,date,gross_usd,commission_usd,slippage_usd")
    parser.add_argument("--active-days", type=int, required=True)
    parser.add_argument("--gross-basis", choices=(BASIS_PRE_SLIPPAGE, BASIS_ACTUAL_FILLS), required=True)
    parser.add_argument("--trials-tested", type=int, required=True)
    parser.add_argument("--stress-extra-usd-per-trade", type=float, required=True)
    parser.add_argument("--provenance", choices=(PROVENANCE_NATIVE, PROVENANCE_SIMULATED), required=True)
    args = parser.parse_args()
    with args.trades.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        required = {"trade_id", "date", "gross_usd", "commission_usd", "slippage_usd"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("missing required complete-trade or cost fields")
        rows = list(reader)
    print(json.dumps(evaluate_trades(
        rows, args.active_days,
        gross_basis=args.gross_basis,
        trials_tested=args.trials_tested,
        stress_extra_usd_per_trade=args.stress_extra_usd_per_trade,
        provenance=args.provenance,
    ), indent=2))


if __name__ == "__main__":
    main()
