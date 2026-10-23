"""Measure MT5 historical-vs-live timestamp basis without touching orders.

The historical request is made through ``copy_ticks_range`` with UTC request
bounds. The live tick and forming M1 bar are sampled in the same session. The
output is intentionally sanitized and contains no account, broker, symbol
path, price, or raw tick payload.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from qts.adapters.mt5_adapter import mt5_initialize_kwargs  # noqa: E402

SCHEMA = "qts.mt5_timestamp_basis.v1"


def _number(value: Any) -> float | None:
    try:
        item = value.item() if hasattr(value, "item") else value
        return float(item) if item is not None else None
    except (TypeError, ValueError):
        return None


def _row_value(row: Any, field: str) -> float | None:
    try:
        if isinstance(row, dict):
            value = row.get(field)
        else:
            try:
                value = row[field]
            except (IndexError, KeyError, TypeError):
                value = getattr(row, field, None)
    except (AttributeError, IndexError, KeyError, TypeError):
        return None
    return _number(value)


def _epoch_msc(value: float | None) -> float | None:
    if value is None:
        return None
    return value / 1000.0 if value > 1e12 else value


def _dataset_digests(paths: list[Path]) -> list[str]:
    digests: list[str] = []
    for path in paths:
        document = json.loads(path.read_text(encoding="utf-8"))
        digest = document.get("dataset_sha256")
        if isinstance(digest, str) and digest:
            digests.append(digest)
    return sorted(set(digests))


def measure(mt5: Any, *, symbol: str, dataset_manifests: list[Path]) -> dict[str, Any]:
    now_utc = time.time()
    start = datetime.fromtimestamp(now_utc - 600.0, UTC)
    end = datetime.fromtimestamp(now_utc, UTC)
    tick = mt5.symbol_info_tick(symbol)
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, 1)
    historical = mt5.copy_ticks_range(symbol, start, end, mt5.COPY_TICKS_ALL)

    live_raw = _epoch_msc(_row_value(tick, "time_msc")) if tick is not None else None
    if live_raw is None and tick is not None:
        live_raw = _epoch_msc(_row_value(tick, "time"))
    m1_raw = _epoch_msc(_row_value(rates[0], "time")) if rates is not None and len(rates) else None
    history_raw = None
    history_count = 0
    if historical is not None:
        history_count = len(historical)
        if history_count:
            history_raw = _epoch_msc(_row_value(historical[-1], "time_msc"))
            if history_raw is None:
                history_raw = _epoch_msc(_row_value(historical[-1], "time"))

    live_offset = live_raw - now_utc if live_raw is not None else None
    m1_live_delta = m1_raw - live_raw if m1_raw is not None and live_raw is not None else None
    history_utc_delta = history_raw - now_utc if history_raw is not None else None
    history_live_delta = history_raw - live_raw if history_raw is not None and live_raw is not None else None
    live_basis_measured = (
        live_offset is not None
        and m1_live_delta is not None
        and abs(m1_live_delta) <= 120.0
        and abs(live_offset) >= 900.0
        and abs(live_offset) <= 14 * 3600.0
    )
    historical_basis_measured = (
        history_utc_delta is not None
        and abs(history_utc_delta) <= 600.0
        and history_live_delta is not None
        and live_offset is not None
        and abs(history_live_delta - (history_utc_delta - live_offset)) <= 120.0
    )
    status = "MEASURED_SAME_SESSION" if live_basis_measured and historical_basis_measured else "INCONCLUSIVE"
    return {
        "schema": SCHEMA,
        "status": status,
        "measured_at_utc": datetime.now(UTC).isoformat(),
        "read_only": True,
        "orders_submitted": 0,
        "order_send_called": False,
        "historical_api": "copy_ticks_range",
        "historical_time_basis": "UTC" if historical_basis_measured else "UNCONFIRMED",
        "live_api": "symbol_info_tick + copy_rates_from_pos",
        "live_time_basis": "SERVER_LOCAL" if live_basis_measured else "UNCONFIRMED",
        "request_window_seconds": 600,
        "history_rows": history_count,
        "dataset_sha256s": _dataset_digests(dataset_manifests),
        "comparison": {
            "live_raw_minus_utc_now_s": round(live_offset, 3) if live_offset is not None else None,
            "m1_raw_minus_live_raw_s": round(m1_live_delta, 3) if m1_live_delta is not None else None,
            "history_last_raw_minus_utc_now_s": round(history_utc_delta, 3)
            if history_utc_delta is not None
            else None,
            "history_last_raw_minus_live_raw_s": round(history_live_delta, 3)
            if history_live_delta is not None
            else None,
            "live_bar_alignment_tolerance_s": 120,
            "historical_request_alignment_tolerance_s": 600,
        },
        "interpretation": (
            "copy_ticks_range time_msc aligns with UTC request time while live/M1 raw times share a non-zero "
            "server-local offset; this evidence applies only to the digest-bound raw acquisitions"
            if status == "MEASURED_SAME_SESSION"
            else "same-session comparison did not satisfy all alignment gates; historical clock remains blocked"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only MT5 timestamp-basis measurement")
    parser.add_argument("--symbol", default=os.getenv("QTS_MT5_SYMBOL", "XAUUSD@"))
    parser.add_argument("--dataset-manifest", action="append", type=Path, default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        import MetaTrader5 as mt5
    except ImportError:
        return 2
    path = os.getenv("QTS_MT5_PATH") or os.getenv("MT5_PATH")
    if not mt5.initialize(**mt5_initialize_kwargs(path)):
        return 2
    try:
        report = measure(mt5, symbol=args.symbol, dataset_manifests=args.dataset_manifest)
    finally:
        mt5.shutdown()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "history_rows": report["history_rows"]}))
    return 0 if report["status"] == "MEASURED_SAME_SESSION" else 1


if __name__ == "__main__":
    raise SystemExit(main())
