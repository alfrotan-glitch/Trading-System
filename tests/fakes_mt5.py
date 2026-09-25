"""Deterministic fake MetaTrader5 module for MT5 history acquisition tests.

No broker is contacted.  The fake emits numpy structured arrays with the exact
dtype layout MetaTrader5 returns for ticks (time, bid, ask, last, volume,
time_msc, flags, volume_real) so tests exercise the real preservation path —
including future-field preservation, duplicates, collisions and failures —
without a live terminal (CI-safe by design).
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import numpy as np

# Exact field layout + dtypes returned by the real MetaTrader5 package for ticks.
TICK_DTYPE = np.dtype(
    [
        ("time", "<i8"),
        ("bid", "<f8"),
        ("ask", "<f8"),
        ("last", "<f8"),
        ("volume", "<u8"),
        ("time_msc", "<i8"),
        ("flags", "<u4"),
        ("volume_real", "<f8"),
    ]
)

TICK_DTYPE_WITH_FUTURE_FIELD = np.dtype(
    TICK_DTYPE.descr
    + [
        ("spread_points", "<u2"),  # hypothetical future/never-seen broker field
    ]
)


def _to_ms(value: datetime) -> int:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return int(value.timestamp() * 1000)


def generate_chunk_rows(start_utc: datetime, end_utc: datetime, *, spacing_ms: int = 30_000) -> np.ndarray:
    """Deterministic half-open [start, end) tick series with embedded edge cases.

    Rows are a pure function of (start, end), so a resumed acquisition
    re-querying a chunk receives identical bytes.

    Structure baked in on purpose:
    * every 97th tick emits a second row with the SAME time_msc but a different
      bid (same-millisecond distinct payload — must be retained);
    * every 499th tick emits an exact full-row duplicate (must be retained);
    * bid only changes every 24 ticks (consecutive identical quote states);
    * spread cycles deterministically.
    """
    start_ms = _to_ms(start_utc)
    end_ms = _to_ms(end_utc)
    if end_ms <= start_ms:
        return np.empty(0, dtype=TICK_DTYPE)
    count = (end_ms - start_ms) // spacing_ms
    rows: list[tuple[Any, ...]] = []
    i = 0
    while i < count:
        stamp = start_ms + i * spacing_ms
        bid = round(1900.0 + (i // 24) * 0.10, 2)
        spread = round(0.10 + (i % 7) * 0.033, 3)
        ask = round(bid + spread, 3)
        base_row = (stamp // 1000, bid, ask, 0.0, 0, stamp, 6, 0.0)
        rows.append(base_row)
        if i and i % 499 == 0:
            rows.append(base_row)  # exact full-row duplicate
        if i and i % 97 == 0:
            rows.append((stamp // 1000, round(bid + 0.01, 2), ask, 0.0, 0, stamp, 6, 0.0))  # same ms, new payload
        i += 1
    out = np.empty(len(rows), dtype=TICK_DTYPE)
    for idx, name in enumerate(TICK_DTYPE.names or ()):
        out[name] = [row[idx] for row in rows]
    return out


class FakeMT5:
    """Minimal MT5 stand-in: DEMO account, XAUUSD@ symbol, deterministic ticks."""

    ACCOUNT_TRADE_MODE_DEMO = 0
    COPY_TICKS_ALL = 7
    __version__ = "5.0.9999-fake"

    def __init__(
        self,
        *,
        demo: bool = True,
        spacing_ms: int = 30_000,
        fail_spans_above_ms: int | None = None,
        fail_call_numbers: set[int] | None = None,
        none_response: bool = False,
        empty_response: bool = False,
        future_fields: bool = False,
        raise_keyboard_interrupt_calls: set[int] | None = None,
    ) -> None:
        self.demo = demo
        self.spacing_ms = spacing_ms
        self.fail_spans_above_ms = fail_spans_above_ms
        self.fail_call_numbers = set(fail_call_numbers or set())
        self.none_response = none_response
        self.empty_response = empty_response
        self.future_fields = future_fields
        self.raise_keyboard_interrupt_calls = set(raise_keyboard_interrupt_calls or set())
        self.copy_ticks_range_calls: list[tuple[int, int]] = []
        self.order_send_calls = 0
        self.initialized = 0
        self.shutdown_calls = 0
        self._call_index = 0

    # -- driver lifecycle ------------------------------------------------------

    def initialize(self, path: str | None = None) -> bool:
        self.initialized += 1
        return True

    def shutdown(self) -> None:
        self.shutdown_calls += 1

    def last_error(self):
        if self.none_response:
            return (-1, "Terminal: Call failed")
        return (1, "ok")

    # -- read-only facility ------------------------------------------------------

    def account_info(self):
        return SimpleNamespace(
            trade_mode=0 if self.demo else 1,
            server="WMMarkets-Demo" if self.demo else "RealServer-Whatever",
            login=5550101 if self.demo else 6660202,
        )

    def terminal_info(self):
        return SimpleNamespace(build=5000, name="MetaTrader 5", company="WM Markets", path="C:/MT5")

    def symbol_info(self, symbol: str):
        if symbol != "XAUUSD@":
            return None
        return SimpleNamespace(
            name="XAUUSD@",
            visible=True,
            path="Metals\\XAUUSD@",
            digits=2,
            point=0.01,
            trade_mode=4,
        )

    def symbol_select(self, symbol: str, selected: bool) -> bool:
        return True

    # -- the one data API -------------------------------------------------------

    def copy_ticks_range(self, symbol: str, start: datetime, end: datetime, flags: int):
        self._call_index += 1
        start_ms = _to_ms(start)
        end_ms = _to_ms(end)
        self.copy_ticks_range_calls.append((start_ms, end_ms))
        if self._call_index in self.raise_keyboard_interrupt_calls:
            raise KeyboardInterrupt
        if self._call_index in self.fail_call_numbers:
            raise RuntimeError("simulated terminal call failure")
        if self.fail_spans_above_ms is not None and (end_ms - start_ms) > self.fail_spans_above_ms:
            return None  # server-side span cap, like the observed 365d 'Call failed'
        if self.none_response:
            return None
        if self.empty_response:
            return np.empty(0, dtype=TICK_DTYPE)
        rows = generate_chunk_rows(start, end, spacing_ms=self.spacing_ms)
        if self.future_fields:
            extended = np.empty(rows.shape[0], dtype=TICK_DTYPE_WITH_FUTURE_FIELD)
            for name in TICK_DTYPE.names or ():
                extended[name] = rows[name]
            extended["spread_points"] = np.arange(rows.shape[0], dtype="<u2") % 17
            return extended
        return rows

    # -- sentinel: any order API must NEVER be called -----------------------------

    def order_send(self, *args: Any, **kwargs: Any):  # pragma: no cover - sentinel only
        self.order_send_calls += 1
        raise AssertionError("MT5 history acquisition must never submit orders")
