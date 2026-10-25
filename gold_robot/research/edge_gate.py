"""Independent performance gate for frequent XAUUSD scalping candidates.

Requires explicit gross P&L plus separate cost fields. A high fill count is
not evidence of profitability. Historical screening is never live approval.
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


def evaluate_trades(rows: list[dict], active_days: int, seed: int = 6241024) -> dict:
    """Day-block bootstrap; independent future holdout still required."""
    if active_days < 1:
        raise ValueError("active_days must be positive")
    by_day: dict[str, list[float]] = defaultdict(list)
    costs = gross = 0.0
    for row in rows:
        date = str(row["date"])
        if len(date) != 10 or date[4] != "-" or date[7] != "-":
            raise ValueError("date must be YYYY-MM-DD")
        g = float(row["gross_usd"])
        c = float(row["commission_usd"])
        s = float(row["slippage_usd"])
        if not all(math.isfinite(x) for x in (g, c, s)) or c < 0 or s < 0:
            raise ValueError("invalid gross or cost")
        by_day[date].append(g - c - s)
        gross += g
        costs += c + s
    values = [n for day in sorted(by_day) for n in by_day[day]]
    net = sum(values)
    gain = sum(v for v in values if v > 0)
    loss = -sum(v for v in values if v < 0)
    pf = gain / loss if loss > 0 else None
    win_rate = sum(v > 0 for v in values) / len(values) if values else None
    peak = balance = dd = 0.0
    for v in values:
        balance += v
        peak = max(peak, balance)
        dd = max(dd, peak - balance)
    blocks = [by_day[d] for d in sorted(by_day)]
    rng = random.Random(seed)
    boots = []
    if blocks:
        for _ in range(2000):
            sample = [v for block in rng.choices(blocks, k=len(blocks)) for v in block]
            if sample:
                boots.append(statistics.fmean(sample))
    boots.sort()
    lower = boots[max(0, int(len(boots) * 0.01) - 1)] if boots else None
    return {
        "trades": len(values),
        "active_days": active_days,
        "days_with_trades": len(by_day),
        "trades_per_active_day": len(values) / active_days,
        "net_usd": round(net, 4),
        "gross_usd": round(gross, 4),
        "explicit_cost_usd": round(costs, 4),
        "win_rate": win_rate,
        "profit_factor": pf,
        "max_closed_equity_drawdown_usd": dd,
        "bootstrap_99pct_lower_expectancy_usd": lower,
        "status": "RESEARCH_POSITIVE_NOT_VALIDATED" if (
            len(values) >= 100 and net > 0 and pf is not None and pf > 1.15
            and lower is not None and lower > 0
        ) else "REJECTED_OR_INSUFFICIENT_EVIDENCE",
        "note": "Historical screen only; independent future data and native MT5 fills required.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("trades", type=Path, help="CSV: date,gross_usd,commission_usd,slippage_usd")
    parser.add_argument("--active-days", type=int, required=True)
    args = parser.parse_args()
    with args.trades.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        needed = {"date", "gross_usd", "commission_usd", "slippage_usd"}
        if not needed.issubset(reader.fieldnames or []):
            raise ValueError("missing required trade ledger fields")
        rows = list(reader)
    print(json.dumps(evaluate_trades(rows, args.active_days), indent=2))


if __name__ == "__main__":
    main()
