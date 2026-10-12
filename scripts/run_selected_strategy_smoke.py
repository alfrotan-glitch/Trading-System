#!/usr/bin/env python3
"""Reproduce a synthetic, mechanism-only smoke run of the selected candidate.

This is not a market backtest. It deliberately builds a deterministic price
path so the selected research plan, next-open fills, risk sizing and assumed
cost accounting have a small checked-in output even when licensed historical
inputs are unavailable. It cannot validate performance or support a claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from qts.research.longhistory import protocol as P
from qts.research.longhistory.selected import (
    SELECTED_CANDIDATE_ID,
    SELECTED_PROTOCOL_ID,
    build_selected_plan,
    run_selected_window,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "reports" / "selected_strategy_smoke_2026-10-11.json"


def synthetic_daily_bars() -> pd.DataFrame:
    """260 deterministic daily bars with flat, rising, flat and falling phases."""
    n = 260
    index = pd.bdate_range("2020-01-02", periods=n)
    close = np.full(n, 2000.0)
    close[100:180] = 2000.0 + 0.75 * (np.arange(100, 180) - 99)
    close[180:220] = 2060.0
    close[220:] = 2060.0 - 0.5 * (np.arange(220, n) - 219)
    open_ = np.concatenate(([close[0]], close[:-1]))
    high = np.maximum(open_, close) + 0.2
    low = np.minimum(open_, close) - 0.2
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": 1.0},
        index=index,
    )


def _ohlc_sha256(bars: pd.DataFrame) -> str:
    rows = [
        f"{timestamp:%Y-%m-%d},{open_:.8f},{high:.8f},{low:.8f},{close:.8f}"
        for timestamp, (open_, high, low, close) in zip(
            bars.index, bars[["open", "high", "low", "close"]].to_numpy(dtype=float), strict=True
        )
    ]
    return hashlib.sha256(("\n".join(rows) + "\n").encode("ascii")).hexdigest()


def _trade_output(trade) -> dict[str, object]:
    return {
        "direction": "LONG" if trade.direction > 0 else "SHORT",
        "entry_day": trade.entry_day.strftime("%Y-%m-%d"),
        "exit_day": trade.exit_day.strftime("%Y-%m-%d"),
        "entry_price": round(float(trade.entry_price), 4),
        "exit_price": round(float(trade.exit_price), 4),
        "gross_usd": round(float(trade.gross_usd), 4),
        "cost_usd": round(float(trade.cost_usd), 4),
        "net_usd": round(float(trade.net_usd), 4),
        "bars_held": int(trade.bars_held),
        "stopped": bool(trade.stopped),
        "forced_exit": bool(trade.forced_exit),
    }


def _run_output(run) -> dict[str, object]:
    return {
        "round_turns": len(run.trades),
        "gross_usd": round(float(run.gross_usd), 4),
        "cost_usd": round(float(run.cost_usd), 4),
        "financing_usd": round(float(run.financing_usd), 4),
        "net_usd": round(float(run.net_usd), 4),
        "final_equity_usd": round(float(run.final_equity), 4),
        "cost_basis": run.cost_basis,
        "trades": [_trade_output(trade) for trade in run.trades],
    }


def build_smoke_report() -> dict[str, object]:
    """Return a deterministic JSON-compatible smoke result."""
    bars = synthetic_daily_bars()
    start, end = str(bars.index[0].date()), str(bars.index[-1].date())
    plan = build_selected_plan(bars)
    base = run_selected_window(bars, start, end)
    double_cost_model = P.COST_BASE.scaled(2.0)
    double_cost = run_selected_window(bars, start, end, costs=double_cost_model)
    first_signal = int(np.flatnonzero(np.isfinite(plan.target))[0])

    return {
        "schema": "qts.selected_strategy_smoke.v1",
        "run_id": "agent3-xauusd-ma20-100-atr3-smoke-2026-10-11",
        "candidate": {
            "protocol_id": SELECTED_PROTOCOL_ID,
            "candidate_id": SELECTED_CANDIDATE_ID,
            "timeframe": "1D",
            "signal": "long when SMA(20) > SMA(100), otherwise short after warmup",
            "stop": "3 x ATR(14); size from the frozen 1% stop-risk rule, capped at 1.0x",
        },
        "data": {
            "symbol": "XAUUSD_SYNTHETIC",
            "class": "SYNTHETIC_MECHANISM_ONLY",
            "bars": len(bars),
            "first_day": start,
            "last_day": end,
            "ohlc_sha256": _ohlc_sha256(bars),
            "purpose": "signal, execution-timing, risk-sizing, cost and determinism regression only",
        },
        "execution": {
            "decision": "completed daily close",
            "fill": "following daily open",
            "stop_fill": "daily high/low; stop level or open on a gap through the stop",
            "first_signal_day": bars.index[first_signal].strftime("%Y-%m-%d"),
            "first_fill_day": bars.index[first_signal + 1].strftime("%Y-%m-%d"),
            "first_fill_price": round(float(bars["open"].iloc[first_signal + 1]), 4),
        },
        "cost_model": P.COST_BASE.describe(),
        "base_cost_run": _run_output(base),
        "double_cost_sensitivity": {
            "cost_model": double_cost_model.describe(),
            **_run_output(double_cost),
        },
        "validation": {
            "performance_validation": "BLOCKED",
            "claim": "NONE",
            "claim_eligible": False,
            "reason": "synthetic input only; reliable independent market data and measured broker costs are unavailable",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="JSON output path")
    args = parser.parse_args()
    report = build_smoke_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {args.output}")
    print("evidence: SYNTHETIC_MECHANISM_ONLY; performance validation BLOCKED; claim NONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
