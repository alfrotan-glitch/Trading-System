"""Shared raw MT5 tick-to-minute bid/ask aggregation for research assays."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.parquet as pq

from qts.research.xauusd_broker_ml import BrokerBars


@dataclass
class _BarBuilder:
    times: list[int] = field(default_factory=list)
    open_bid: list[float] = field(default_factory=list)
    open_ask: list[float] = field(default_factory=list)
    high_mid: list[float] = field(default_factory=list)
    low_mid: list[float] = field(default_factory=list)
    close_bid: list[float] = field(default_factory=list)
    close_ask: list[float] = field(default_factory=list)
    mean_spread: list[float] = field(default_factory=list)
    _minute: int | None = None
    _open_bid: float = 0.0
    _open_ask: float = 0.0
    _high_mid: float = 0.0
    _low_mid: float = 0.0
    _close_bid: float = 0.0
    _close_ask: float = 0.0
    _spread_sum: float = 0.0
    _count: int = 0

    def _start(self, minute: int, bid: np.ndarray, ask: np.ndarray) -> None:
        mid = (bid + ask) / 2.0
        self._minute = minute
        self._open_bid = float(bid[0])
        self._open_ask = float(ask[0])
        self._high_mid = float(mid.max())
        self._low_mid = float(mid.min())
        self._close_bid = float(bid[-1])
        self._close_ask = float(ask[-1])
        self._spread_sum = float((ask - bid).sum())
        self._count = len(bid)

    def _finish(self) -> None:
        if self._minute is None or self._count == 0:
            return
        self.times.append(self._minute * 60_000)
        self.open_bid.append(self._open_bid)
        self.open_ask.append(self._open_ask)
        self.high_mid.append(self._high_mid)
        self.low_mid.append(self._low_mid)
        self.close_bid.append(self._close_bid)
        self.close_ask.append(self._close_ask)
        self.mean_spread.append(self._spread_sum / self._count)

    def consume(self, minute: int, bid: np.ndarray, ask: np.ndarray) -> None:
        if self._minute is None:
            self._start(minute, bid, ask)
            return
        if minute == self._minute:
            mid = (bid + ask) / 2.0
            self._high_mid = max(self._high_mid, float(mid.max()))
            self._low_mid = min(self._low_mid, float(mid.min()))
            self._close_bid = float(bid[-1])
            self._close_ask = float(ask[-1])
            self._spread_sum += float((ask - bid).sum())
            self._count += len(bid)
            return
        self._finish()
        self._start(minute, bid, ask)

    def finish(self) -> BrokerBars:
        self._finish()
        return BrokerBars(
            time_msc=np.asarray(self.times, dtype=np.int64),
            open_bid=np.asarray(self.open_bid, dtype=np.float64),
            open_ask=np.asarray(self.open_ask, dtype=np.float64),
            high_mid=np.asarray(self.high_mid, dtype=np.float64),
            low_mid=np.asarray(self.low_mid, dtype=np.float64),
            close_bid=np.asarray(self.close_bid, dtype=np.float64),
            close_ask=np.asarray(self.close_ask, dtype=np.float64),
            mean_spread=np.asarray(self.mean_spread, dtype=np.float64),
        )


def read_broker_bars(dataset_dir: Path, parts: list[dict[str, Any]]) -> BrokerBars:
    """Read validated Parquet quote parts without reordering or repairing them."""
    builder = _BarBuilder()
    for part in parts:
        parquet = pq.ParquetFile(dataset_dir / "parts" / part["part"])
        for batch in parquet.iter_batches(batch_size=500_000, columns=["time_msc", "bid", "ask"]):
            stamp = np.asarray(batch.column("time_msc").to_numpy(zero_copy_only=False), dtype=np.int64)
            bid = np.asarray(batch.column("bid").to_numpy(zero_copy_only=False), dtype=np.float64)
            ask = np.asarray(batch.column("ask").to_numpy(zero_copy_only=False), dtype=np.float64)
            if not (np.isfinite(stamp).all() and np.isfinite(bid).all() and np.isfinite(ask).all()):
                raise ValueError("raw broker ledger contains non-finite quote fields")
            if np.any((bid <= 0.0) | (ask < bid)):
                raise ValueError("raw broker ledger contains invalid bid/ask ordering")
            minutes = stamp // 60_000
            starts = np.concatenate(([0], np.flatnonzero(minutes[1:] != minutes[:-1]) + 1))
            ends = np.concatenate((starts[1:], [len(minutes)]))
            for start, end in zip(starts.tolist(), ends.tolist(), strict=True):
                builder.consume(int(minutes[start]), bid[start:end], ask[start:end])
    bars = builder.finish()
    if len(bars.time_msc) < 100:
        raise ValueError("insufficient one-minute bars")
    return bars
