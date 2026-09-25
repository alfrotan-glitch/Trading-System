"""Post-event path measurement — deliberately independent of detection logic.

This module knows nothing about impulse definitions: it receives an event
index, a direction, and pre-registered measurement parameters, then measures
the subsequent path. Keeping measurement separate from detection prevents the
classic contamination where a detector's own statistics leak into the outcome
definition.

Honest bar-data limitations (recorded in every evidence file)
-------------------------------------------------------------
* Intra-bar sequencing is UNKNOWN from OHLC bars. When the target and the
  adverse threshold are both touched within the same bar, we resolve the race
  ADVERSE-FIRST (conservative). We never claim a target was hit when the bar
  data cannot prove ordering.
* Entry/exit are modeled at bar CLOSES only (with an explicit latency in
  bars). No fill is ever assumed because an order was submitted.
* Events whose measurement window extends past the end of the series are
  EXCLUDED and counted — never measured on truncated paths, never padded.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from qts.domain.value_objects import Bar


class RaceOutcome(StrEnum):
    TARGET = "TARGET"
    ADVERSE = "ADVERSE"  # includes same-bar ambiguity, resolved conservatively
    NEITHER = "NEITHER"  # horizon expired without touching either threshold


class EventExclusion(StrEnum):
    NONE = "NONE"
    INSUFFICIENT_FORWARD_BARS = "INSUFFICIENT_FORWARD_BARS"


@dataclass(frozen=True)
class MeasurementParams:
    """Pre-registered measurement configuration (no tuning inside analysis)."""

    horizon_bars: int = 12
    latency_bars: int = 1
    atr_window: int = 14
    target_atr_multiple: float = 1.0  # symmetric race: target = adverse = 1.0 ATR
    adverse_atr_multiple: float = 1.0

    def as_dict(self) -> dict[str, object]:
        return {
            "horizon_bars": self.horizon_bars,
            "latency_bars": self.latency_bars,
            "atr_window": self.atr_window,
            "target_atr_multiple": self.target_atr_multiple,
            "adverse_atr_multiple": self.adverse_atr_multiple,
        }


@dataclass(frozen=True)
class EventMeasurement:
    """Complete post-event path record for one event."""

    family_id: str
    detection_index: int
    detection_time: datetime  # close_time of the detection bar
    direction: str  # LONG | SHORT
    decision_state: str  # DETECTED_MEASURED | DETECTED_EXCLUDED
    exclusion: EventExclusion
    entry_index: int | None
    entry_price: float | None
    atr_at_detection: float | None
    target_bps: float | None
    adverse_bps: float | None
    horizon_return_bps: float | None  # directional, gross of costs
    net_return_bps: float | None  # gross minus declared round-turn cost
    mfe_bps: float | None  # maximum favorable excursion over the path
    mae_bps: float | None  # maximum adverse excursion over the path
    race_outcome: RaceOutcome | None
    time_to_target_bars: int | None  # None = censored (target never hit)
    time_to_adverse_bars: int | None
    duration_bars: int | None  # bars from entry to race resolution or horizon end
    target_hit: bool | None
    adverse_hit: bool | None
    continuation: bool | None  # horizon_return_bps > 0
    reversal: bool | None  # horizon_return_bps < 0
    regime_label: str | None  # causal vol regime at detection time


def true_range(bars: list[Bar] | tuple[Bar, ...], i: int) -> float:
    """True range of bar i (uses close of bar i-1; causal at close of bar i)."""
    hi, lo = float(bars[i].high), float(bars[i].low)
    if i == 0:
        return hi - lo
    prev_close = float(bars[i - 1].close)
    return max(hi - lo, abs(hi - prev_close), abs(lo - prev_close))


def atr_at(bars: list[Bar] | tuple[Bar, ...], i: int, window: int) -> float | None:
    """ATR over bars [i-window+1 .. i] — all known at the close of bar i."""
    if i + 1 < window:
        return None
    trs = [true_range(bars, j) for j in range(i - window + 1, i + 1)]
    return sum(trs) / len(trs)


def measure_event(
    bars: list[Bar] | tuple[Bar, ...],
    detection_index: int,
    direction: str,
    family_id: str,
    params: MeasurementParams,
    round_turn_cost_bps: float,
    regime_label: str | None = None,
) -> EventMeasurement:
    """Measure the post-event path of one detected impulse.

    Entry occurs at the close of bar ``detection_index + latency_bars``. The
    measurement path covers bars entry+1 .. entry+horizon (inclusive). If the
    series ends before the path completes, the event is EXCLUDED (counted,
    never measured on a truncated path).
    """
    if direction not in ("LONG", "SHORT"):
        raise ValueError(f"direction must be LONG or SHORT, got {direction!r}")
    det_bar = bars[detection_index]
    entry_index = detection_index + params.latency_bars
    path_end = entry_index + params.horizon_bars

    if path_end >= len(bars):
        return EventMeasurement(
            family_id=family_id,
            detection_index=detection_index,
            detection_time=det_bar.close_time,
            direction=direction,
            decision_state="DETECTED_EXCLUDED",
            exclusion=EventExclusion.INSUFFICIENT_FORWARD_BARS,
            entry_index=None,
            entry_price=None,
            atr_at_detection=None,
            target_bps=None,
            adverse_bps=None,
            horizon_return_bps=None,
            net_return_bps=None,
            mfe_bps=None,
            mae_bps=None,
            race_outcome=None,
            time_to_target_bars=None,
            time_to_adverse_bars=None,
            duration_bars=None,
            target_hit=None,
            adverse_hit=None,
            continuation=None,
            reversal=None,
            regime_label=regime_label,
        )

    atr = atr_at(bars, detection_index, params.atr_window)
    if atr is None or atr <= 0:
        # Warmup guarantees make this practically unreachable; fail closed by
        # excluding rather than inventing a threshold.
        return EventMeasurement(
            family_id=family_id,
            detection_index=detection_index,
            detection_time=det_bar.close_time,
            direction=direction,
            decision_state="DETECTED_EXCLUDED",
            exclusion=EventExclusion.INSUFFICIENT_FORWARD_BARS,
            entry_index=None,
            entry_price=None,
            atr_at_detection=None,
            target_bps=None,
            adverse_bps=None,
            horizon_return_bps=None,
            net_return_bps=None,
            mfe_bps=None,
            mae_bps=None,
            race_outcome=None,
            time_to_target_bars=None,
            time_to_adverse_bars=None,
            duration_bars=None,
            target_hit=None,
            adverse_hit=None,
            continuation=None,
            reversal=None,
            regime_label=regime_label,
        )

    entry_price = float(bars[entry_index].close)
    if entry_price <= 0:
        raise ValueError("entry price must be positive")
    sign = 1.0 if direction == "LONG" else -1.0
    target_price_dist = params.target_atr_multiple * atr
    adverse_price_dist = params.adverse_atr_multiple * atr
    target_bps = target_price_dist / entry_price * 1e4
    adverse_bps = adverse_price_dist / entry_price * 1e4

    mfe = 0.0
    mae = 0.0
    time_to_target: int | None = None
    time_to_adverse: int | None = None
    for step in range(1, params.horizon_bars + 1):
        b = bars[entry_index + step]
        hi, lo = float(b.high), float(b.low)
        if direction == "LONG":
            fav = max(0.0, hi - entry_price)
            adv = max(0.0, entry_price - lo)
        else:
            fav = max(0.0, entry_price - lo)
            adv = max(0.0, hi - entry_price)
        mfe = max(mfe, fav)
        mae = max(mae, adv)
        touched_target = fav >= target_price_dist
        touched_adverse = adv >= adverse_price_dist
        if touched_target and time_to_target is None:
            time_to_target = step
        if touched_adverse and time_to_adverse is None:
            time_to_adverse = step
        # Same-bar ambiguity resolves ADVERSE-first (conservative; documented).
        if touched_adverse:
            break
        if touched_target:
            break

    if time_to_adverse is not None and (time_to_target is None or time_to_adverse <= time_to_target):
        race = RaceOutcome.ADVERSE
        duration = time_to_adverse
    elif time_to_target is not None:
        race = RaceOutcome.TARGET
        duration = time_to_target
    else:
        race = RaceOutcome.NEITHER
        duration = params.horizon_bars

    exit_close = float(bars[path_end].close)
    horizon_return_bps = sign * (exit_close - entry_price) / entry_price * 1e4
    net_return_bps = horizon_return_bps - round_turn_cost_bps
    mfe_bps = mfe / entry_price * 1e4
    mae_bps = mae / entry_price * 1e4

    return EventMeasurement(
        family_id=family_id,
        detection_index=detection_index,
        detection_time=det_bar.close_time,
        direction=direction,
        decision_state="DETECTED_MEASURED",
        exclusion=EventExclusion.NONE,
        entry_index=entry_index,
        entry_price=entry_price,
        atr_at_detection=atr,
        target_bps=target_bps,
        adverse_bps=adverse_bps,
        horizon_return_bps=horizon_return_bps,
        net_return_bps=net_return_bps,
        mfe_bps=mfe_bps,
        mae_bps=mae_bps,
        race_outcome=race,
        time_to_target_bars=time_to_target,
        time_to_adverse_bars=time_to_adverse,
        duration_bars=duration,
        target_hit=race == RaceOutcome.TARGET,
        adverse_hit=race == RaceOutcome.ADVERSE,
        continuation=horizon_return_bps > 0,
        reversal=horizon_return_bps < 0,
        regime_label=regime_label,
    )


def causal_vol_regime_labels(bars: list[Bar] | tuple[Bar, ...], window: int = 24, min_history: int = 96) -> list[str]:
    """Per-bar volatility regime label using ONLY information up to that bar.

    Label at bar i: realized vol over [i-window+1 .. i] compared against the
    33/67 percentiles of realized vols over all PRIOR bars with at least
    ``min_history`` of past. Labels: LOW | MID | HIGH | UNKNOWN (warmup).
    """
    n = len(bars)
    labels: list[str] = ["UNKNOWN"] * n
    if n == 0:
        return labels
    import numpy as np

    closes = np.array([float(b.close) for b in bars], dtype=float)
    rets = np.diff(closes) / closes[:-1]  # rets[j] = return of bar j+1
    vols: list[float | None] = [None] * n
    for i in range(window, n):
        vols[i] = float(np.std(rets[i - window : i]))
    for i in range(n):
        v = vols[i]
        if v is None or i < min_history:
            continue
        prior = [x for x in vols[:i] if x is not None]
        if len(prior) < min_history - window:
            continue
        q33 = float(np.quantile(prior, 1.0 / 3.0))
        q67 = float(np.quantile(prior, 2.0 / 3.0))
        if v <= q33:
            labels[i] = "LOW"
        elif v <= q67:
            labels[i] = "MID"
        else:
            labels[i] = "HIGH"
    return labels
