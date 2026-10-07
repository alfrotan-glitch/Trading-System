"""Read-only MT5 quote forensics probe (Windows only).

Prints live clock/timestamp facts from the connected MetaTrader 5 terminal so
the WMMarkets-Demo quote-freshness refusal can be diagnosed from live evidence
(see artifacts/QTS_WINDOWS_QUOTE_FORENSIC_REPORT.md).

Strictly read-only:
- No order is submitted. No file is written. No QTS source is modified.
- No timestamp or timezone offset is hard-coded: every value is read live.
- No gate or threshold is changed: the FRESH/STALE/NO_TICK label reuses
  QTS's own gate constants (imported, never copied) purely to LABEL what
  the freshness gate would decide. It is diagnostic output, not a control
  path — the gate itself is untouched.

Usage (Windows, from the repository root, terminal signed in to the demo
account):

    .venv\\Scripts\\python.exe scripts\\probe_quote_forensics.py
"""

from __future__ import annotations

import sys
import time
from datetime import UTC, datetime

try:
    import MetaTrader5 as mt5
except ImportError:
    print("FATAL: MetaTrader5 package not installed in this environment.")
    sys.exit(2)

try:
    from qts.lifecycle.demo_gate import FUTURE_TOLERANCE_S, MAX_TICK_AGE_S
except Exception as exc:  # pragma: no cover - environment guard
    print(f"FATAL: cannot import qts.lifecycle.demo_gate ({exc}) — run via the QTS venv.")
    sys.exit(2)

SYMBOL = "XAUUSD@"


def iso_utc(epoch: float | None) -> str:
    if epoch is None:
        return "N/A"
    return datetime.fromtimestamp(float(epoch), tz=UTC).isoformat()


def main() -> int:
    print("=" * 74)
    print("QTS read-only MT5 quote forensics probe — no orders, no writes")
    print("=" * 74)

    if not mt5.initialize():
        print("FATAL: mt5.initialize() failed:", mt5.last_error())
        return 2

    try:
        # [1] local UTC clock (the basis every QTS freshness check compares to)
        now_utc = time.time()
        print(f"[1] time.time() (UTC epoch)              : {now_utc:.3f}")
        print(f"    time.time() (UTC ISO)                : {iso_utc(now_utc)}")

        # [9] terminal / connection status
        ti = mt5.terminal_info()
        if ti is None:
            print(f"[9] terminal_info()                      : None — {mt5.last_error()}")
            server_time = None
        else:
            d = ti._asdict()
            print("[9] terminal_info()                      :")
            for k in (
                "connected",
                "server",
                "name",
                "company",
                "build",
                "language",
                "ping_last",
                "trade_allowed",
                "dlls_allowed",
            ):
                if k in d:
                    print(f"    {k:<16} : {d[k]}")
            server_time = getattr(ti, "time", None)

        # [2] terminal-reported server time
        print(f"[2] terminal_info().time                 : {server_time}  ({iso_utc(server_time)})")

        # [7] terminal time minus UTC
        if server_time is not None:
            off = float(server_time) - now_utc
            hh, rem = divmod(abs(off), 3600)
            mm = rem // 60
            sign = "+" if off >= 0 else "-"
            print(f"[7] terminal time - UTC now              : {off:+.1f}s  ({sign}{int(hh)}h{int(mm):02d}m)")
        else:
            print("[7] terminal time - UTC now              : UNAVAILABLE")

        # [3][4][8] latest tick
        tick = mt5.symbol_info_tick(SYMBOL)
        if tick is None:
            print(f"[3] symbol_info_tick('{SYMBOL}').time     : None — {mt5.last_error()}")
            print(f"[4] symbol_info_tick('{SYMBOL}').time_msc : None")
            print("[8] bid / ask / last / volume            : NO TICK")
            print("[6] latest tick vs current M1 bar        : NO TICK")
            print("[10] CLASSIFICATION                      : NO_TICK")
            return 0

        print(f"[3] symbol_info_tick('{SYMBOL}').time     : {tick.time}")
        print(f"[4] symbol_info_tick('{SYMBOL}').time_msc : {tick.time_msc}")
        print(
            "[8] bid / ask / last / volume            : "
            f"bid={tick.bid} ask={tick.ask} last={tick.last} volume={tick.volume}"
        )

        # Tick epoch exactly as the QTS gate derives it (time_msc preferred).
        tick_epoch = tick.time_msc / 1000.0 if tick.time_msc > 1e12 else float(tick.time)
        raw_age = now_utc - tick_epoch
        print(f"    tick epoch (gate basis)              : {tick_epoch:.3f}")
        print(f"    raw local age (now - epoch)          : {raw_age:+.1f}s")

        # [5][6] current M1 bar
        rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 0, 1)
        if rates is None or len(rates) == 0:
            print(
                f"[5] copy_rates_from_pos('{SYMBOL}', M1, 0, 1)[0]['time'] : UNAVAILABLE — {mt5.last_error()}"
            )
            print("[6] latest tick vs current M1 bar        : UNAVAILABLE (no bar)")
            verdict = "STALE" if raw_age > MAX_TICK_AGE_S else "FRESH (raw-age only; bar probe unavailable)"
            print(f"[10] CLASSIFICATION                      : {verdict}")
            return 0

        bar_time = int(rates[0]["time"])
        print(f"[5] copy_rates_from_pos('{SYMBOL}', M1, 0, 1)[0]['time'] : {bar_time}")
        delta = float(bar_time) - tick_epoch
        note = f"tick OLDER than current bar by {delta:.0f}s" if delta > 0 else "tick inside/ahead of current bar"
        print(f"[6] current M1 bar open - tick epoch     : {delta:+.1f}s  ({note})")

        # [10] classification — the gate's own contract, used read-only as a label
        if raw_age > MAX_TICK_AGE_S or tick_epoch < bar_time:
            verdict = "STALE"
        elif tick_epoch > bar_time + 60.0 + FUTURE_TOLERANCE_S:
            verdict = "FUTURE/CORRUPT (gate fails closed; not FRESH)"
        else:
            verdict = "FRESH"
        print(f"[10] CLASSIFICATION                      : {verdict}")
        print(
            "     gate constants imported live: "
            f"MAX_TICK_AGE_S={MAX_TICK_AGE_S}, FUTURE_TOLERANCE_S={FUTURE_TOLERANCE_S}"
        )
        return 0
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
