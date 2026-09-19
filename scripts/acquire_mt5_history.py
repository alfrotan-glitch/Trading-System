"""CLI for read-only, lossless MT5 historical tick acquisition.

Run this on the Windows machine with the already-connected WM Markets DEMO
terminal.  It writes a private Parquet dataset and private sidecar metadata;
it never calls an order API.  Quality analysis is intentionally a separate
command (``analyze_mt5_history.py``).
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from qts.data.mt5_history import acquire_mt5_ticks


def _parse_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("use an ISO-8601 UTC timestamp, for example 2026-09-19T00:00:00Z") from exc
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("historical bounds must include a UTC offset")
    return parsed.astimezone(UTC)


def _context(mt5: Any, symbol: str) -> dict[str, Any]:
    account = mt5.account_info()
    terminal = mt5.terminal_info()
    info = mt5.symbol_info(symbol)
    return {
        "requested_symbol": symbol,
        "actual_symbol": getattr(info, "name", None) if info is not None else None,
        "broker_server": getattr(account, "server", None) if account is not None else None,
        "environment": "DEMO" if getattr(account, "trade_mode", None) == getattr(mt5, "ACCOUNT_TRADE_MODE_DEMO", object()) else "UNVERIFIED",
        "account_trade_mode_raw": getattr(account, "trade_mode", None) if account is not None else None,
        "terminal_build": getattr(terminal, "build", None) if terminal is not None else None,
        "mt5_package_version": getattr(mt5, "__version__", None),
        "observation_mode": "OBSERVE_ONLY",
        "execution_policy": "DEMO_EXECUTION = DISABLED BY POLICY; LIVE = LOCKED",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Acquire raw MT5 historical ticks without deferred analysis")
    parser.add_argument("--symbol", default=os.getenv("QTS_MT5_SYMBOL", "XAUUSD@"))
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--days", type=int, help="request the interval ending now, in UTC")
    group.add_argument("--start", type=_parse_datetime, help="requested UTC start")
    parser.add_argument("--end", type=_parse_datetime, help="requested UTC end; required with --start")
    parser.add_argument("--output", type=Path, required=True, help="private Parquet dataset directory")
    parser.add_argument("--chunk-hours", type=int, default=24)
    parser.add_argument("--overwrite", action="store_true", help="replace this exact output only when intentionally rebuilding")
    args = parser.parse_args(argv)
    if args.start is not None and args.end is None:
        parser.error("--end is required with --start")
    if args.days is not None and args.days <= 0:
        parser.error("--days must be positive")
    if args.days is not None:
        end = datetime.now(UTC)
        start = end - timedelta(days=args.days)
    else:
        start, end = args.start, args.end
    if start >= end:
        parser.error("--start must be before --end")
    try:
        import MetaTrader5 as mt5
    except ImportError:
        print(json.dumps({"schema": "qts.mt5_raw_tick_acquisition.v1", "status": "MT5_PACKAGE_UNAVAILABLE"}, indent=2))
        return 2

    terminal_path = os.getenv("QTS_MT5_PATH") or os.getenv("MT5_PATH")
    initialized = bool(mt5.initialize(path=terminal_path) if terminal_path else mt5.initialize())
    if not initialized:
        print(json.dumps({
            "schema": "qts.mt5_raw_tick_acquisition.v1",
            "status": "INITIALIZE_FAILED",
            "read_only": True,
            "mt5_last_error": repr(mt5.last_error()),
        }, indent=2))
        return 2
    try:
        info = _context(mt5, args.symbol)
        report = acquire_mt5_ticks(
            mt5,
            symbol=args.symbol,
            start_utc=start,
            end_utc=end,
            output_path=args.output,
            chunk_hours=args.chunk_hours,
            context=info,
        )
    except Exception as exc:  # noqa: BLE001 - CLI reports machine-readable failure
        partial_reports = sorted(args.output.parent.glob(f".{args.output.name}.partial-*.metadata.json"))
        if partial_reports:
            report = json.loads(partial_reports[-1].read_text(encoding="utf-8"))
        else:
            report = {"schema": "qts.mt5_raw_tick_acquisition.v1", "status": "FAILED", "error": f"{type(exc).__name__}: {exc}"}
    finally:
        mt5.shutdown()
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0 if report.get("status") in {"COMPLETE", "NO_DATA"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
