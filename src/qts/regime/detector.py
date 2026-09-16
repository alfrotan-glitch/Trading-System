"""Regime detectors — hypothesis, not mandate."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol

import numpy as np

from qts.domain.value_objects import Bar


class Regime(StrEnum):
    TREND = "TREND"
    RANGE = "RANGE"
    HIGH_VOL = "HIGH_VOL"
    LOW_VOL = "LOW_VOL"
    UNKNOWN = "UNKNOWN"


class RegimeDetector(Protocol):
    def label(self, bars: list[Bar]) -> Regime: ...
    def confidence(self) -> float: ...


class VolatilityRegimeDetector:
    """Simple vol quantile detector — hypothesis."""

    def __init__(self, window: int = 20, high_quantile: float = 0.7):
        self.window = window
        self.high_quantile = high_quantile
        self._conf = 0.0

    def label(self, bars: list[Bar]) -> Regime:
        if len(bars) < self.window + 1:
            self._conf = 0.0
            return Regime.UNKNOWN
        closes = np.array([float(b.close) for b in bars], dtype=float)
        rets = np.diff(closes) / closes[:-1]
        vols = np.array([np.std(rets[max(0, i - self.window) : i]) for i in range(1, len(rets) + 1)])
        cur_vol = vols[-1]
        thresh = np.quantile(vols, self.high_quantile)
        self._conf = float(min(1.0, cur_vol / (thresh + 1e-12)))
        return Regime.HIGH_VOL if cur_vol >= thresh else Regime.LOW_VOL

    def confidence(self) -> float:
        return self._conf
