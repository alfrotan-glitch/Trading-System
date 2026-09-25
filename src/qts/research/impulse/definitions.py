"""Pre-registered impulse definitions — strictly causal detectors.

Design rules (enforced structurally, not by convention)
-------------------------------------------------------
* A detector receives ``history = bars[: i + 1]`` — the prefix of the series
  ending AT the candidate detection bar. It is physically impossible for a
  detector to see future bars; the analysis loop never passes more.
* The detection timestamp is the CLOSE TIME of the last bar in ``history``.
* Baseline statistics (median range, move dispersion, long vol, local range
  extremes) are computed from bars STRICTLY BEFORE the detection bar, so a
  bar cannot inflate its own threshold.
* Definitions are PRE-REGISTERED below in ``PRE_REGISTERED_FAMILIES``: one
  baseline parameterization and exactly one sensitivity variant per
  definition. There is no data-driven parameter search anywhere in this
  module — searching would be multiple testing we cannot account for.
* Every family supports LONG and SHORT impulses symmetrically.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import cast

import numpy as np

from qts.domain.value_objects import Bar

LONG = "LONG"
SHORT = "SHORT"

# Minimum history (bars) required before any detection is attempted.
# Largest lookback used below is 61 (velocity dispersion window 60 + move 3 - overlap),
# rounded up for safety margin.
WARMUP_BARS = 64


@dataclass(frozen=True)
class ImpulseFamily:
    """One pre-registered (definition, parameterization) pair."""

    family_id: str
    definition: str  # human-readable definition name
    params: dict[str, float]
    role: str  # "baseline" | "variant" — both are reported, neither is 'chosen'

    @property
    def trial_key(self) -> str:
        return self.family_id


def _ranges(bars: Sequence[Bar]) -> np.ndarray:
    return np.array([float(b.high) - float(b.low) for b in bars], dtype=float)


def _closes(bars: Sequence[Bar]) -> np.ndarray:
    return np.array([float(b.close) for b in bars], dtype=float)


def detect_range_expansion(history: Sequence[Bar], k: float, lookback: float = 20.0) -> str | None:
    """Current bar range > k * median range of the previous ``lookback`` bars.

    Direction: sign of the current bar's close-open move (must be non-zero).
    """
    n = len(history)
    lb = int(lookback)
    if n < lb + 1:
        return None
    cur = history[-1]
    prior = _ranges(history[-1 - lb : -1])
    baseline = float(np.median(prior))
    if baseline <= 0:
        return None
    cur_range = float(cur.high) - float(cur.low)
    if cur_range <= k * baseline:
        return None
    move = float(cur.close) - float(cur.open)
    if move > 0:
        return LONG
    if move < 0:
        return SHORT
    return None


def detect_price_velocity(history: Sequence[Bar], k: float, m: float = 3.0, window: float = 60.0) -> str | None:
    """|close_i - close_{i-m}| > k * dispersion of m-bar moves over the PRIOR window.

    The dispersion baseline uses only moves fully completed before bar i, so
    the triggering move never inflates its own threshold.
    """
    n = len(history)
    mi, wi = int(m), int(window)
    if n < mi + wi + 1:
        return None
    closes = _closes(history)
    move = closes[-1] - closes[-1 - mi]
    # prior m-bar moves ending at or before bar i-m (fully completed before the
    # triggering move): the trigger never inflates its own dispersion baseline.
    completed = closes[: n - mi]
    prior_moves = (completed[mi:] - completed[:-mi])[-wi:]
    if prior_moves.size < 10:
        return None
    sigma = float(np.std(prior_moves))
    if sigma <= 0:
        return None
    if abs(move) <= k * sigma:
        return None
    return LONG if move > 0 else SHORT


def detect_vol_expansion(
    history: Sequence[Bar], k: float, short_win: float = 6.0, long_win: float = 18.0
) -> str | None:
    """Realized vol over the last ``short_win`` returns > k * vol over the preceding ``long_win``.

    Both windows end at the detection bar (causal). Direction: sign of the
    cumulative close-to-close move over the short window.
    """
    n = len(history)
    sw, lw = int(short_win), int(long_win)
    if n < sw + lw + 1:
        return None
    closes = _closes(history)
    rets = np.diff(closes) / closes[:-1]
    short_vol = float(np.std(rets[-sw:]))
    long_vol = float(np.std(rets[-sw - lw : -sw]))
    if long_vol <= 0:
        return None
    if short_vol <= k * long_vol:
        return None
    move = closes[-1] - closes[-1 - sw]
    if move > 0:
        return LONG
    if move < 0:
        return SHORT
    return None


def detect_range_breakout(history: Sequence[Bar], lookback: float = 20.0) -> str | None:
    """Close breaks the extremes of the previous ``lookback`` bars (Donchian-style).

    Extremes exclude the current bar.
    """
    n = len(history)
    lb = int(lookback)
    if n < lb + 1:
        return None
    cur = history[-1]
    prior = history[-1 - lb : -1]
    hi = max(float(b.high) for b in prior)
    lo = min(float(b.low) for b in prior)
    c = float(cur.close)
    if c > hi:
        return LONG
    if c < lo:
        return SHORT
    return None


def detect_breakout_with_expansion(
    history: Sequence[Bar], k: float, lookback: float = 20.0, range_lookback: float = 20.0
) -> str | None:
    """Combination: local-range breakout AND range expansion, same direction."""
    brk = detect_range_breakout(history, lookback=lookback)
    exp = detect_range_expansion(history, k=k, lookback=range_lookback)
    if brk is not None and brk == exp:
        return brk
    return None


_DETECTORS = {
    "range_expansion": detect_range_expansion,
    "price_velocity": detect_price_velocity,
    "vol_expansion": detect_vol_expansion,
    "range_breakout": detect_range_breakout,
    "breakout_with_expansion": detect_breakout_with_expansion,
}

# ---------------------------------------------------------------------------
# PRE-REGISTRATION: the complete hypothesis space for this research question.
# 5 definitions x 2 parameterizations = 10 families. Nothing else is ever
# evaluated; the trial ledger and the multiplicity correction account for all
# 10 (times the 2 pre-registered horizons in analysis = 20 recorded trials).
# ---------------------------------------------------------------------------
PRE_REGISTERED_FAMILIES: tuple[ImpulseFamily, ...] = (
    ImpulseFamily("IMP-RE-B", "range_expansion", {"k": 2.5, "lookback": 20.0}, "baseline"),
    ImpulseFamily("IMP-RE-V", "range_expansion", {"k": 3.5, "lookback": 20.0}, "variant"),
    ImpulseFamily("IMP-PV-B", "price_velocity", {"k": 2.5, "m": 3.0, "window": 60.0}, "baseline"),
    ImpulseFamily("IMP-PV-V", "price_velocity", {"k": 3.5, "m": 3.0, "window": 60.0}, "variant"),
    ImpulseFamily("IMP-VE-B", "vol_expansion", {"k": 2.0, "short_win": 6.0, "long_win": 18.0}, "baseline"),
    ImpulseFamily("IMP-VE-V", "vol_expansion", {"k": 3.0, "short_win": 6.0, "long_win": 18.0}, "variant"),
    ImpulseFamily("IMP-RB-B", "range_breakout", {"lookback": 20.0}, "baseline"),
    ImpulseFamily("IMP-RB-V", "range_breakout", {"lookback": 40.0}, "variant"),
    ImpulseFamily(
        "IMP-BE-B", "breakout_with_expansion", {"k": 2.0, "lookback": 20.0, "range_lookback": 20.0}, "baseline"
    ),
    ImpulseFamily(
        "IMP-BE-V", "breakout_with_expansion", {"k": 2.0, "lookback": 40.0, "range_lookback": 20.0}, "variant"
    ),
)

PRIMARY_HORIZON_BARS = 12
SECONDARY_HORIZONS_BARS: tuple[int, ...] = (4,)
ALL_HORIZONS_BARS: tuple[int, ...] = (PRIMARY_HORIZON_BARS, *SECONDARY_HORIZONS_BARS)


def detect_events(bars: Sequence[Bar], family: ImpulseFamily) -> list[tuple[int, str]]:
    """Run one family over the series. Returns [(index, direction)] with index
    = detection bar position and detection timestamp = bars[index].close_time.

    Only ``bars[: i + 1]`` is ever handed to a detector — lookahead is
    structurally impossible. Events within the measurement overlap of a
    previous event of the SAME family are suppressed (non-overlapping event
    study; suppression count is reported by the analysis layer).
    """
    detector = cast(Callable[..., "str | None"], _DETECTORS[family.definition])
    events: list[tuple[int, str]] = []
    blocked_until = -1
    for i in range(WARMUP_BARS, len(bars)):
        if i <= blocked_until:
            continue
        direction = detector(bars[: i + 1], **family.params)
        if direction is not None:
            events.append((i, direction))
            # Suppress re-detection while a prior event's primary measurement
            # window is still open (prevents overlapping, correlated events
            # from double-counting the same path).
            blocked_until = i + PRIMARY_HORIZON_BARS
    return events
