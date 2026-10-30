"""Python MIRROR of the frozen MQL5 router/SMC rules — screening only.

This is NOT the MT5 EA and NOT a backtest of it. It exists so the
frozen logic (persistence, transition abstention, ATR guard, SMC
construction) can be unit-tested on Linux, where MetaEditor/MT5 do not
exist. Any divergence between this mirror and the MQL5 code invalidates
the mirror, not the EA: native parity (decision-by-decision on Windows)
is required before any MT5 claim. Costs, fills, sizing, session and
broker checks are NOT modelled here.

Rules mirrored exactly from gold_robot/mt5_robot/AdaptiveResearch.mqh,
SmcResearch.mqh and ScalpResearch.mqh, preregistered 2026-10-30:
- raw regime: trend iff ADX>=25 and EMA-gap>=0.12 ATR; range iff
  ADX<=19 or gap<0.07; else transition.
- confirmed regime: raw regime must hold 3 consecutive closed bars.
- transition: only priority-4 candidates with R>=1.0 may clear.
- ATR guard: abstain iff current ATR percentile over the last 50
  closed ATR values (values[0] = most recent closed, as in MQL5
  CopyBuffer start=1) exceeds 0.90.
- SMC (20 closed bars, oldest first): prior 12 bars swing; bar 12
  displacement >0.10 ATR beyond swing; order block = last opposing
  candle before bar 12; FVG = bar 13 low > bar 11 high (longs) or
  bar 13 high < bar 11 low (shorts) when present, else OB zone;
  mitigation = a closed bar 13..18 entering the zone and closing back
  in direction; confirmation = bar 19 closing beyond the swing (BOS).
- M1 scalp (34 closed bars, oldest first; past = bars 1..32, current
  = bar 33): efficiency/volume as in scalp_regimes.py
  propose_scalp_entry; TP 15 bps, SL 12 bps from the last closed close.
"""

from __future__ import annotations

ROUTER_PERSISTENCE_BARS = 3
ROUTER_TRANSITION_MIN_PRIORITY = 4
ROUTER_ATR_LOOKBACK_BARS = 50
ROUTER_ATR_ABSTAIN_PERCENTILE = 0.90

SCALP_BARS = 34
SCALP_EFF_HIGH = 0.43
SCALP_EFF_LOW = 0.28
SCALP_TP_BPS = 15.0
SCALP_SL_BPS = 12.0


def raw_regime(adx: float, ema_gap_atr: float) -> int:
    if adx >= 25.0 and ema_gap_atr >= 0.12:
        return 2
    if adx <= 19.0 or ema_gap_atr < 0.07:
        return 0
    return 1


class RouterState:
    """Persistence state. Mirrors the file-scope globals in AdaptiveResearch.mqh."""

    def __init__(self) -> None:
        self.last_raw = -1
        self.streak = 0
        self.confirmed = -1

    def confirmed_regime(self, raw: int) -> int:
        if raw == self.last_raw:
            self.streak += 1
        else:
            self.last_raw = raw
            self.streak = 1
        if self.streak >= ROUTER_PERSISTENCE_BARS:
            self.confirmed = raw
        return self.confirmed


def atr_guard_pass(atr_values_most_recent_first: list[float]) -> bool:
    """True iff the current ATR is at or below the 90th percentile."""
    if len(atr_values_most_recent_first) != ROUTER_ATR_LOOKBACK_BARS:
        return False
    current = atr_values_most_recent_first[0]
    if not (current and current > 0):
        return False
    if any(not (v and v > 0) for v in atr_values_most_recent_first):
        return False
    at_or_below = sum(1 for v in atr_values_most_recent_first if v <= current)
    return (at_or_below / ROUTER_ATR_LOOKBACK_BARS) <= ROUTER_ATR_ABSTAIN_PERCENTILE


def transition_allowed(priority: int, reward_risk: float) -> bool:
    return priority >= ROUTER_TRANSITION_MIN_PRIORITY and reward_risk >= 1.0


def smc_signal(bars: list[dict], atr: float, h1_close: float | None = None,
               h1_ma: float | None = None) -> dict:
    """Return {'side': 1/-1/0, 'level': float, 'anchor': float, 'reason': str}.

    bars: 20 dicts with open/high/low/close, oldest first, all closed.
    level = zone edge nearest price (future limit), anchor = zone extreme
    behind the entry (stop anchor), mirroring CompletedSmcSignal.
    """
    if len(bars) != 20 or atr <= 0:
        return {"side": 0, "level": 0.0, "anchor": 0.0, "reason": "bad input"}
    # contiguity is enforced in MQL5 by time checks; here we require
    # strictly positive, sane bars as the minimum sanity equivalent.
    for b in bars:
        if not (b["low"] > 0 and b["high"] >= b["low"]):
            return {"side": 0, "level": 0.0, "anchor": 0.0, "reason": "bad bar"}
    swing_high = max(b["high"] for b in bars[:12])
    swing_low = min(b["low"] for b in bars[:12])
    disp = bars[12]
    buffer = atr * 0.10
    if disp["close"] > swing_high + buffer and disp["close"] > disp["open"]:
        side = 1
    elif disp["close"] < swing_low - buffer and disp["close"] < disp["open"]:
        side = -1
    else:
        return {"side": 0, "level": 0.0, "anchor": 0.0, "reason": "no displacement"}
    ob_low = ob_high = None
    for i in range(11, -1, -1):
        b = bars[i]
        if (side > 0 and b["close"] < b["open"]) or (side < 0 and b["close"] > b["open"]):
            ob_low, ob_high = b["low"], b["high"]
            break
    if ob_low is None:
        return {"side": 0, "level": 0.0, "anchor": 0.0, "reason": "no order block"}
    zone_low, zone_high = ob_low, ob_high
    if side > 0 and bars[13]["low"] > bars[11]["high"]:
        zone_low, zone_high = bars[11]["high"], bars[13]["low"]
    elif side < 0 and bars[13]["high"] < bars[11]["low"]:
        zone_low, zone_high = bars[13]["high"], bars[11]["low"]
    if zone_high <= zone_low:
        return {"side": 0, "level": 0.0, "anchor": 0.0, "reason": "empty zone"}
    mitigated = False
    for i in range(13, 19):
        b = bars[i]
        if side > 0 and b["low"] <= zone_high and b["close"] >= zone_low and b["close"] > b["open"]:
            mitigated = True
        if side < 0 and b["high"] >= zone_low and b["close"] <= zone_high and b["close"] < b["open"]:
            mitigated = True
    if not mitigated:
        return {"side": 0, "level": 0.0, "anchor": 0.0, "reason": "no mitigation"}
    confirm = bars[19]
    if side > 0 and not (confirm["close"] > swing_high and confirm["close"] > confirm["open"]):
        return {"side": 0, "level": 0.0, "anchor": 0.0, "reason": "no BOS"}
    if side < 0 and not (confirm["close"] < swing_low and confirm["close"] < confirm["open"]):
        return {"side": 0, "level": 0.0, "anchor": 0.0, "reason": "no BOS"}
    if h1_close is not None and h1_ma is not None:
        if (side > 0 and h1_close <= h1_ma) or (side < 0 and h1_close >= h1_ma):
            return {"side": 0, "level": 0.0, "anchor": 0.0, "reason": "H1 veto"}
    if side > 0:
        return {"side": 1, "level": zone_high, "anchor": zone_low, "reason": "SMC buy"}
    return {"side": -1, "level": zone_low, "anchor": zone_high, "reason": "SMC sell"}


def scalp_signal(closes: list[float]) -> dict:
    """Mirror of CompletedScalpSignal + PrepareScalpLimit (price math only).

    closes: 34 closed M1 closes, oldest first. Returns side, level (last
    closed close), stop and target prices from the frozen bps exits.
    Sizing, spread, broker gap, session and pending checks are NOT
    modelled here — they live in the EA pipeline.
    """
    if len(closes) != SCALP_BARS or any(not (c and c > 0) for c in closes):
        return {"side": 0, "level": 0.0, "stop": 0.0, "target": 0.0, "reason": "bad input"}
    past = closes[1:33]
    current = closes[33]
    abs_steps = sum(abs(past[i] - past[i - 1]) for i in range(1, len(past)))
    if abs_steps <= 0:
        return {"side": 0, "level": 0.0, "stop": 0.0, "target": 0.0, "reason": "zero movement"}
    volatility = abs_steps / 31.0
    efficiency = abs(past[-1] - past[0]) / abs_steps
    drift = past[-1] - past[0]
    low, high = min(past), max(past)
    width = high - low
    if width <= volatility:
        return {"side": 0, "level": 0.0, "stop": 0.0, "target": 0.0, "reason": "range narrower than step"}
    if efficiency >= SCALP_EFF_HIGH and drift > 0:
        regime = 1
    elif efficiency >= SCALP_EFF_HIGH and drift < 0:
        regime = -1
    elif efficiency <= SCALP_EFF_LOW:
        regime = 2
    else:
        regime = 0
    recent = past[-9:]
    past20 = past[-20:]
    side = 0
    if regime == 1 and past[-1] < past[-2] and current > past[-1] \
            and max(recent) - past[-1] >= volatility and current < max(recent):
        side = 1
    elif regime == -1 and past[-1] > past[-2] and current < past[-1] \
            and past[-1] - min(recent) >= volatility and current > min(recent):
        side = -1
    elif regime == 2 and low <= current <= low + width * 0.25 and current > past[-1]:
        side = 1
    elif regime == 2 and high - width * 0.25 <= current <= high and current < past[-1]:
        side = -1
    elif regime in (1, 0) and current > max(past20) + volatility * 0.2:
        side = 1
    elif regime in (-1, 0) and current < min(past20) - volatility * 0.2:
        side = -1
    if side == 0:
        return {"side": 0, "level": 0.0, "stop": 0.0, "target": 0.0, "reason": "no setup"}
    if side > 0:
        stop = current * (1.0 - SCALP_SL_BPS / 10000.0)
        target = current * (1.0 + SCALP_TP_BPS / 10000.0)
    else:
        stop = current * (1.0 + SCALP_SL_BPS / 10000.0)
        target = current * (1.0 - SCALP_TP_BPS / 10000.0)
    return {"side": side, "level": current, "stop": stop, "target": target,
            "reason": f"scalp regime {regime} eff {efficiency:.3f}"}
