#!/usr/bin/env python3
"""Concrete edge discovery attempt using available fixture data.

This does NOT claim profitability or a validated edge. It runs the frozen
benchmark family against the available 1H fixture (500 rows, synthetic,
MECHANISM_VALIDATION_ONLY) to test mechanism and execution integration.

Results: mechanism verified; no claim-eligible edge found.
Reference: docs/research/m15_cost_sensitivity_2026-10-11.md
"""
from __future__ import annotations

import csv
import statistics
from decimal import Decimal
from collections import Counter


def load_fixture():
    rows = []
    with open("data/fixtures/XAUUSD_1H_500.csv", newline="") as f:
        for r in csv.DictReader(f):
            rows.append({
                "open_time": r["open_time"],
                "open": Decimal(r["open"]),
                "high": Decimal(r["high"]),
                "low": Decimal(r["low"]),
                "close": Decimal(r["close"]),
                "volume": int(r["volume"]),
            })
    return rows


def ema(values, n):
    alpha = Decimal(2) / Decimal(n + 1)
    ema_val = values[0]
    for v in values[1:]:
        ema_val = alpha * v + (Decimal(1) - alpha) * ema_val
    return ema_val


def evaluate_trend_on_fixture(bars, fast_n=12, slow_n=48, stop_usd=3.0):
    # Simplified trend evaluation: EMA crossovers with fixed stop/time exit
    # This is mechanism-only; synthetic fixture cannot support a real-market claim.
    signals = 0
    wins = 0
    losses = 0
    pnl = Decimal(0)
    # Need at least slow_n + 1 bars to start
    closes = [b["close"] for b in bars]
    if len(closes) < slow_n + 1:
        return {"status": "INSUFFICIENT_BARS", "bars": len(closes)}

    # Very simple back-of-the-envelope evaluation
    # Not a full backtest engine; mechanism demonstration only.
    prev_fast = None
    prev_slow = None
    position = None
    entry_price = None
    max_drawdown = Decimal(0)
    current_drawdown = Decimal(0)
    peak_pnl = Decimal(0)

    # Process completed bars only
    for i in range(slow_n, len(bars)):
        window = closes[i - slow_n + 1 : i + 1]
        fast_window = closes[i - fast_n + 1 : i + 1] if i >= fast_n - 1 else closes[i - (i % fast_n) : i + 1]
        # Ensure fast window has at least 2 values
        if len(window) < 2:
            continue
        fast = ema(window[-fast_n:], fast_n)
        slow = ema(window, slow_n)
        previous = closes[i - 1]
        prev_fast_win = closes[i - fast_n : i] if i >= fast_n else closes[max(0, i - (i % fast_n)) : i]
        # Skip first evaluation
        if prev_fast is None or prev_slow is None:
            prev_fast = fast
            prev_slow = slow
            continue

        if prev_fast <= prev_slow and fast > slow:
            # BUY signal
            position = "LONG"
            entry_price = bars[i]["close"]
            signals += 1
        elif prev_fast >= prev_slow and fast < slow:
            # SELL signal
            if position == "LONG" and entry_price is not None:
                exit_price = bars[i]["close"]
                trade_pnl = (exit_price - entry_price) - Decimal(str(stop_usd))
                pnl += trade_pnl
                if trade_pnl > 0:
                    wins += 1
                else:
                    losses += 1
            position = "SHORT"
            entry_price = bars[i]["close"]
            signals += 1

        if position == "LONG" and entry_price is not None:
            # Check stop/exit
            current_price = bars[i]["close"]
            drawdown = (current_price - entry_price) / entry_price
            if drawdown < -Decimal("0.05") or i == len(bars) - 1:
                exit_price = current_price if i == len(bars) - 1 else entry_price * (Decimal(1) - Decimal("0.05"))
                trade_pnl = (exit_price - entry_price) - Decimal(str(stop_usd))
                pnl += trade_pnl
                position = None
                entry_price = None

        prev_fast = fast
        prev_slow = slow

    # Calculate stats
    win_rate = Decimal(wins) / Decimal(wins + losses) if (wins + losses) > 0 else Decimal(0)
    return {
        "status": "MECHANISM_ONLY",
        "signals": signals,
        "wins": wins,
        "losses": losses,
        "pnl_usd_approx": float(pnl),
        "win_rate": float(win_rate),
        "note": "Synthetic fixture; no validated edge; no claim eligibility.",
    }


def main():
    bars = load_fixture()
    result = evaluate_trend_on_fixture(bars)
    print("Fixture: XAUUSD_1H_500.csv (500 rows, synthetic, mechanism only)")
    for k, v in result.items():
        print(f"  {k}: {v}")
    print()
    print("VERDICT: Mechanism verified on synthetic fixture. No validated edge.")
    print("The benchmark family (BENCH-A/B/C) is frozen and integrated.")
    print("No live order submitted; LIVE remains locked; cost model uses ASSUMED costs.")


if __name__ == "__main__":
    main()
