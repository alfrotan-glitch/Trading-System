"""Synthetic XAUUSD data generators for testing."""

from __future__ import annotations

import csv
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import numpy as np

from qts.domain.value_objects import AssetClass, Bar, Instrument


def generate_gbm_bars(
    instrument: Instrument | None = None,
    start: datetime = datetime(2020, 1, 1, tzinfo=UTC),
    periods: int = 5000,
    timeframe_minutes: int = 60,
    s0: float = 2000.0,
    mu: float = 0.0,
    sigma: float = 0.015,
    seed: int = 42,
) -> list[Bar]:
    """GBM with OHLC inside bar via high/low noise."""
    rng = np.random.default_rng(seed)
    if instrument is None:
        instrument = Instrument(symbol="XAUUSD", venue="MT5", asset_class=AssetClass.METAL)
    # Simple: each bar close = prev * exp((mu -0.5 sigma2) + sigma * Z)
    prices = [s0]
    for _ in range(1, periods):
        z = rng.standard_normal()
        ret = (mu - 0.5 * sigma**2) + sigma * z
        prices.append(prices[-1] * np.exp(ret))
    bars: list[Bar] = []
    for i, close in enumerate(prices):
        open_p = prices[i - 1] if i > 0 else close
        # high/low as open/close ± abs(noise)
        hl_range = abs(rng.standard_normal()) * sigma * close * 0.5
        high = max(open_p, close) + hl_range
        low = min(open_p, close) - hl_range
        # ensure low not absurd; but keep <= min(open,close)
        low = min(low, min(open_p, close) - 0.01)
        open_time = start + timedelta(minutes=i * timeframe_minutes)
        close_time = open_time + timedelta(minutes=timeframe_minutes)
        bars.append(
            Bar(
                instrument=instrument,
                open=Decimal(f"{open_p:.2f}"),
                high=Decimal(f"{high:.2f}"),
                low=Decimal(f"{low:.2f}"),
                close=Decimal(f"{close:.2f}"),
                volume=Decimal(str(int(rng.integers(800, 2000)))),
                open_time=open_time,
                close_time=close_time,
                data_version="synthetic",
                source="synthetic_gbm",
            )
        )
    return bars


def generate_trending_bars(
    instrument: Instrument | None = None,
    start: datetime = datetime(2020, 1, 1, tzinfo=UTC),
    periods: int = 5000,
    timeframe_minutes: int = 60,
    s0: float = 1800.0,
    trend_bps_per_bar: float = 1.0,
    sigma: float = 0.008,
    seed: int = 7,
) -> list[Bar]:
    """Trending regime to give SMA edge for testing validation."""
    rng = np.random.default_rng(seed)
    if instrument is None:
        instrument = Instrument(symbol="XAUUSD", venue="MT5", asset_class=AssetClass.METAL)
    bars: list[Bar] = []
    price = s0
    for i in range(periods):
        drift = trend_bps_per_bar / 10000 * price
        noise = rng.standard_normal() * sigma * price
        # regime switch every 500 bars
        price = price + drift + noise if (i // 500) % 2 == 0 else price - drift + noise
        price = max(price, 1000)
        open_p = price - noise * 0.3
        high = max(open_p, price) + abs(rng.standard_normal()) * 2
        low = min(open_p, price) - abs(rng.standard_normal()) * 2
        open_time = start + timedelta(minutes=i * timeframe_minutes)
        close_time = open_time + timedelta(minutes=timeframe_minutes)
        bars.append(
            Bar(
                instrument=instrument,
                open=Decimal(f"{open_p:.2f}"),
                high=Decimal(f"{high:.2f}"),
                low=Decimal(f"{low:.2f}"),
                close=Decimal(f"{price:.2f}"),
                volume=Decimal(str(int(rng.integers(500, 1500)))),
                open_time=open_time,
                close_time=close_time,
                data_version="synthetic_trend",
                source="synthetic_trend",
            )
        )
    return bars


def write_csv(bars: list[Bar], path: Path | str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "instrument",
                "venue",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "open_time",
                "close_time",
            ]
        )
        for b in bars:
            w.writerow(
                [
                    b.instrument.symbol,
                    b.instrument.venue,
                    str(b.open),
                    str(b.high),
                    str(b.low),
                    str(b.close),
                    str(b.volume),
                    b.open_time.isoformat(),
                    b.close_time.isoformat(),
                ]
            )
