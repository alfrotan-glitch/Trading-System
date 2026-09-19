"""Read-only MT5 historical XAUUSD tick/bid/ask capability probe.

This script intentionally produces a bounded metadata report rather than a
market-data export. It never calls an order API and never writes credentials or
raw tick payloads. Run it on the Windows machine where the already-running
MetaTrader 5 terminal is connected to the DEMO account.

Heavy per-row auditing (JSON serialization + SHA-256 per row, duplicate
analysis, spread statistics) used to run here, while MT5 was still being
queried; a multi-hour run was interrupted inside that audit.  That work now
lives exclusively in the deferred analysis layer
(:mod:`qts.data.mt5_history_analysis`), which reads the stored raw dataset
after acquisition — see ``scripts/acquire_mt5_history.py`` and
``docs/mt5_history_acquisition.md``.  This probe answers only the capability
question: does the terminal serve historical tick bid/ask at all, for which
fields, in which count range.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import time
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

_REQUIRED_TICK_FIELDS = ("time", "time_msc", "bid", "ask")
_OPTIONAL_TICK_FIELDS = ("last", "volume", "time", "time_msc", "flags", "volume_real")

DEFERRED_ANALYSIS_NOTE = (
    "No per-row audit runs in this probe. Row-level duplicate/spread/digest "
    "analysis is deliberately deferred to qts.data.mt5_history_analysis over "
    "the persisted raw dataset (scripts/acquire_mt5_history.py), so capability "
    "queries stay cheap and interruptible."
)


def _last_error(mt5: Any) -> str | None:
    try:
        value = mt5.last_error()
    except Exception as exc:  # noqa: BLE001 — diagnostic path
        return f"last_error unavailable: {type(exc).__name__}: {exc}"
    return repr(value)


def _field_names(rows: Any) -> list[str]:
    """Extract field names from numpy structured arrays or tuple/dict rows."""
    dtype = getattr(rows, "dtype", None)
    names = getattr(dtype, "names", None)
    if names:
        return [str(name) for name in names]
    try:
        first = rows[0]
    except (IndexError, KeyError, TypeError):
        return []
    if isinstance(first, dict):
        return sorted(str(key) for key in first)
    fields = getattr(first, "_fields", None)
    if fields:
        return [str(field) for field in fields]
    return [name for name in _OPTIONAL_TICK_FIELDS if hasattr(first, name)]


def _value(row: Any, field: str) -> Any:
    try:
        if isinstance(row, dict):
            value = row.get(field)
        else:
            try:
                value = row[field]
            except (IndexError, KeyError, TypeError):
                value = getattr(row, field, None)
    except Exception:  # noqa: BLE001 — malformed provider row
        return None
    item = getattr(value, "item", None)
    if callable(item):
        with contextlib.suppress(Exception):
            value = item()
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _row_projection(row: Any, fields: Iterable[str]) -> dict[str, Any]:
    return {field: _value(row, field) for field in fields}


def _raw_time_msc_bounds(rows: Any, fields: list[str], row_count: int) -> tuple[float | None, float | None]:
    """Vectorized raw time_msc min/max for provenance; no row transformation."""
    if not row_count or "time_msc" not in fields:
        return None, None
    try:
        import numpy as np

        if isinstance(rows, np.ndarray) and rows.dtype.names:
            stamps = rows["time_msc"].astype(np.float64, copy=False)
            return float(np.min(stamps)), float(np.max(stamps))
    except Exception:  # noqa: BLE001 — fall back to the bounded loop below
        pass
    values = [_numeric(_value(row, "time_msc")) for row in rows]
    clean = [value for value in values if value is not None]
    if not clean:
        return None, None
    return min(clean), max(clean)


def _numeric(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _account_report(mt5: Any) -> dict[str, Any]:
    try:
        account = mt5.account_info()
    except Exception as exc:  # noqa: BLE001 — diagnostic path
        return {"status": "UNAVAILABLE", "reason": f"{type(exc).__name__}: {exc}"}
    if account is None:
        return {"status": "UNAVAILABLE", "reason": _last_error(mt5)}
    raw_mode = getattr(account, "trade_mode", None)
    demo_constant = getattr(mt5, "ACCOUNT_TRADE_MODE_DEMO", None)
    return {
        "status": "AVAILABLE",
        "server": getattr(account, "server", None),
        "trade_mode_raw": raw_mode,
        "is_demo": (raw_mode == demo_constant) if demo_constant is not None and raw_mode is not None else None,
        "demo_constant_available": demo_constant is not None,
        "login_persisted": False,
    }


def _symbol_candidates(mt5: Any, query: str) -> list[str]:
    try:
        symbols = mt5.symbols_get()
    except Exception:  # noqa: BLE001 — optional discovery path
        return []
    if not symbols:
        return []
    needle = query.upper()
    out: list[str] = []
    for item in symbols:
        name = str(getattr(item, "name", item if isinstance(item, str) else ""))
        if needle in name.upper() or "XAU" in name.upper():
            out.append(name)
    return sorted(set(out))[:50]


def _symbol_report(mt5: Any, symbol: str) -> dict[str, Any]:
    try:
        info = mt5.symbol_info(symbol)
    except Exception as exc:  # noqa: BLE001 — diagnostic path
        return {"status": "ERROR", "requested_symbol": symbol, "reason": f"{type(exc).__name__}: {exc}"}
    if info is None:
        return {
            "status": "NOT_FOUND",
            "requested_symbol": symbol,
            "candidates": _symbol_candidates(mt5, symbol),
            "reason": _last_error(mt5),
        }
    selected = None
    try:
        selected = bool(mt5.symbol_select(symbol, True))
    except Exception as exc:  # noqa: BLE001 — diagnostic path
        return {
            "status": "ERROR",
            "requested_symbol": symbol,
            "reason": f"symbol_select failed: {type(exc).__name__}: {exc}",
        }
    return {
        "status": "AVAILABLE" if selected else "NOT_SELECTED",
        "requested_symbol": symbol,
        "actual_symbol": getattr(info, "name", symbol),
        "selected": selected,
        "visible": getattr(info, "visible", None),
        "path": getattr(info, "path", None),
        "digits": getattr(info, "digits", None),
        "point": _value(info, "point"),
        "trade_mode": getattr(info, "trade_mode", None),
        "currency_base": getattr(info, "currency_base", None),
        "currency_profit": getattr(info, "currency_profit", None),
    }


def _live_offset_report(mt5: Any, symbol: str) -> dict[str, Any]:
    """Measure the existing QTS broker-server offset contract, read-only."""
    getter = getattr(mt5, "copy_rates_from_pos", None)
    if not callable(getter):
        return {
            "status": "UNAVAILABLE",
            "reason": "copy_rates_from_pos unavailable; no live M1 basis check performed",
            "historical_compatibility": "UNVERIFIED",
        }
    try:
        rates = getter(symbol, getattr(mt5, "TIMEFRAME_M1", 1), 0, 1)
        bar = rates[0] if rates else None
        raw = _value(bar, "time") if bar is not None else None
        bar_time = _numeric(raw)
    except Exception as exc:  # noqa: BLE001 — basis check must not guess
        return {
            "status": "ERROR",
            "reason": f"{type(exc).__name__}: {exc}",
            "historical_compatibility": "UNVERIFIED",
        }
    if bar_time is None:
        return {
            "status": "UNAVAILABLE",
            "reason": "latest M1 bar has no usable raw time",
            "historical_compatibility": "UNVERIFIED",
        }
    if bar_time > 1e12:
        bar_time /= 1000.0
    now_epoch = time.time()
    lower = bar_time - now_epoch
    upper = lower + 60.0
    grid = math.ceil(lower / 900.0) * 900.0
    if not (lower <= grid < upper) or abs(grid) > 14 * 3600:
        return {
            "status": "UNAVAILABLE",
            "bar_time_raw": bar_time,
            "utc_now_epoch": now_epoch,
            "reason": "no unambiguous 15-minute UTC offset grid point in the forming M1 window",
            "historical_compatibility": "UNVERIFIED",
        }
    return {
        "status": "MEASURED",
        "bar_time_raw": bar_time,
        "utc_now_epoch": now_epoch,
        "server_utc_offset_s": float(grid),
        "offset_basis": "measured-m1-bar",
        "historical_compatibility": "REQUIRES_COMPARISON_WITH_HISTORICAL_RAW_TIME",
        "note": "This measures the current live-bar basis only; it does not silently normalize historical rows.",
    }


def _window_report(mt5: Any, symbol: str, days: int, end_utc: datetime, flags: Any) -> dict[str, Any]:
    start_utc = end_utc - timedelta(days=days)
    request = {
        "window_days": days,
        "start_utc": start_utc.isoformat(),
        "end_utc": end_utc.isoformat(),
        "flags": flags,
    }
    try:
        rows = mt5.copy_ticks_range(symbol, start_utc, end_utc, flags)
    except Exception as exc:  # noqa: BLE001 — capability probe must report, not guess
        return {
            **request,
            "status": "QUERY_ERROR",
            "reason": f"{type(exc).__name__}: {exc}",
            "last_error": _last_error(mt5),
        }
    if rows is None:
        return {
            **request,
            "status": "NO_RESPONSE",
            "row_count": 0,
            "reason": _last_error(mt5),
        }
    try:
        row_count = len(rows)
    except TypeError:
        return {**request, "status": "MALFORMED_RESPONSE", "reason": "response has no length"}
    fields = _field_names(rows)
    required_present = {field: field in fields for field in _REQUIRED_TICK_FIELDS}
    has_bid_ask = required_present["bid"] and required_present["ask"]
    first = _row_projection(rows[0], fields) if row_count else None
    last = _row_projection(rows[-1], fields) if row_count else None
    raw_min, raw_max = _raw_time_msc_bounds(rows, fields, row_count)
    return {
        **request,
        "status": "RESPONSE_RECEIVED_BID_ASK_PRESENT" if row_count and has_bid_ask else (
            "RESPONSE_RECEIVED_BID_ASK_ABSENT" if row_count else "EMPTY_RESPONSE"
        ),
        "row_count": row_count,
        "fields": fields,
        "required_fields": required_present,
        "bid_ask_present": has_bid_ask,
        "first_row": first,
        "last_row": last,
        "raw_time_msc_min": raw_min,
        "raw_time_msc_max": raw_max,
        "timestamp_basis": "RAW_MT5_FIELDS_ONLY; no UTC normalization or broker-offset inference performed",
        "deferred_analysis": DEFERRED_ANALYSIS_NOTE,
        "sample": {"first": first, "last": last},
    }


def probe_mt5_history(
    mt5: Any,
    *,
    symbol: str,
    windows_days: list[int],
    end_utc: datetime | None = None,
) -> dict[str, Any]:
    """Run a read-only capability probe against an initialized MT5 module."""
    end_utc = end_utc or datetime.now(UTC)
    report: dict[str, Any] = {
        "schema": "qts.mt5_history_capability_probe.v2",
        "probe_started_at_utc": end_utc.isoformat(),
        "read_only": True,
        "orders_submitted": 0,
        "order_send_called": False,
        "requested_symbol": symbol,
        "account": _account_report(mt5),
        "terminal": {},
        "symbol": {},
        "live_timestamp_basis": {},
        "capability": {},
        "windows": [],
        "deferred_analysis": DEFERRED_ANALYSIS_NOTE,
    }
    try:
        terminal = mt5.terminal_info()
    except Exception as exc:  # noqa: BLE001 — diagnostic path
        terminal = None
        report["terminal"] = {"status": "ERROR", "reason": f"{type(exc).__name__}: {exc}"}
    if terminal is not None:
        report["terminal"] = {
            "status": "AVAILABLE",
            "build": getattr(terminal, "build", None),
            "community_account": getattr(terminal, "community_account", None),
        }
    report["symbol"] = _symbol_report(mt5, symbol)
    if report["symbol"].get("status") == "AVAILABLE":
        report["live_timestamp_basis"] = _live_offset_report(mt5, symbol)
    copy_ticks = getattr(mt5, "copy_ticks_range", None)
    if not callable(copy_ticks):
        report["capability"] = {
            "status": "CAPABILITY_NOT_EXPOSED",
            "historical_tick_api": "copy_ticks_range unavailable",
            "bid_ask_status": "UNVERIFIED",
        }
        return report
    flags = getattr(mt5, "COPY_TICKS_ALL", None)
    if flags is None:
        report["capability"] = {
            "status": "CAPABILITY_UNVERIFIED",
            "historical_tick_api": "copy_ticks_range exposed but COPY_TICKS_ALL constant unavailable",
            "bid_ask_status": "UNVERIFIED",
        }
        return report
    if report["symbol"].get("status") not in {"AVAILABLE"}:
        report["capability"] = {
            "status": "SYMBOL_UNAVAILABLE",
            "historical_tick_api": "copy_ticks_range exposed",
            "bid_ask_status": "UNVERIFIED",
        }
        return report
    for days in windows_days:
        report["windows"].append(_window_report(mt5, symbol, int(days), end_utc, flags))
    received = [window for window in report["windows"] if window["status"].startswith("RESPONSE_RECEIVED")]
    report["capability"] = {
        "status": "RESPONSE_RECEIVED" if received else "NO_TICK_RESPONSE",
        "historical_tick_api": "copy_ticks_range",
        "bid_ask_status": (
            "PRESENT" if any(window.get("bid_ask_present") for window in received) else "ABSENT_OR_UNAVAILABLE"
        ),
        "timestamp_fields": sorted({field for window in received for field in window.get("fields", [])}),
        "timestamp_basis": "RAW_MT5_FIELDS_ONLY; direct server/UTC basis remains unverified",
        "reproducibility": (
            "Each window records exact UTC request bounds, response count, fields and raw time_msc bounds. "
            "Row-level SHA-256 is produced by the deferred analysis over the persisted dataset, not here."
        ),
    }
    return report


def _parse_windows(value: str) -> list[int]:
    values = sorted({int(part.strip()) for part in value.split(",") if part.strip()})
    if not values or any(value <= 0 for value in values):
        raise argparse.ArgumentTypeError("windows must be positive day counts, for example 1,7,30,365")
    return values


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only MT5 historical tick/bid/ask capability probe")
    parser.add_argument("--symbol", default=os.getenv("QTS_MT5_SYMBOL", "XAUUSD"))
    parser.add_argument("--windows-days", type=_parse_windows, default=_parse_windows("1,7,30,365"))
    parser.add_argument("--output", type=Path, help="optional JSON report path; never contains raw tick rows")
    args = parser.parse_args(argv)
    try:
        import MetaTrader5 as mt5
    except ImportError:
        print(
            json.dumps(
                {"schema": "qts.mt5_history_capability_probe.v2", "status": "MT5_PACKAGE_UNAVAILABLE"}, indent=2
            )
        )
        return 2

    path = os.getenv("QTS_MT5_PATH") or os.getenv("MT5_PATH")
    initialized = bool(mt5.initialize(path=path) if path else mt5.initialize())
    if not initialized:
        report = {
            "schema": "qts.mt5_history_capability_probe.v2",
            "status": "INITIALIZE_FAILED",
            "read_only": True,
            "orders_submitted": 0,
            "order_send_called": False,
            "reason": repr(mt5.last_error()),
        }
    else:
        try:
            report = probe_mt5_history(mt5, symbol=args.symbol, windows_days=args.windows_days)
        finally:
            mt5.shutdown()
    rendered = json.dumps(report, indent=2, sort_keys=True, default=str) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report.get("status") not in {"INITIALIZE_FAILED", "MT5_PACKAGE_UNAVAILABLE"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
