"""
H-1M-01: 1m Donchian 20-bar breakout (12/48) on bars derived from verifiable tick.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

SCHEMA = "qts.xauusd_1m.v1"
PREREGISTRATION = "docs/xauusd_1m_next_step_H-1M-01_2026-09-23.md"
HYPOTHESIS = "H-1M-01"
TIME_MIN = 1726746013452
CUTOFF = 1764563969254
DISCOVERY_ROWS = 70783710
H_PRIMARY = 12
H_STABILITY = 48
LOOKBACK = 20
BLOCK_BARS = 50
MIN_N_TERCILE = 100
MIN_BLOCKS = 20
COST_BPS = 5.0  # round-turn
SLIPPAGE_DOLLARS = 0.02
ALPHA = 0.01


class LockedSpanRefused(ValueError):
    pass


@dataclass
class OneMScan:
    time_min: int = TIME_MIN
    cutoff: int = CUTOFF
    rows: int = 0
    # For 1m aggregation, we need to buffer ticks to build bars
    # Instead, we will collect all ticks' time and mid, then build bars at evaluation time.
    # To avoid carrying 70M ticks in memory, we stream and aggregate per batch to bars.
    # We'll store bars as we go: bar_time (minute start), open, high, low, close, volume
    bars_time: list[int] = None  # type: ignore
    bars_open: list[float] = None  # type: ignore
    bars_high: list[float] = None  # type: ignore
    bars_low: list[float] = None  # type: ignore
    bars_close: list[float] = None  # type: ignore
    # For current incomplete minute
    cur_min: int | None = None
    cur_open: float | None = None
    cur_high: float | None = None
    cur_low: float | None = None
    cur_close: float | None = None
    cur_vol: int = 0

    def __post_init__(self):
        self.bars_time = []
        self.bars_open = []
        self.bars_high = []
        self.bars_low = []
        self.bars_close = []

    def add_batch(self, bid: np.ndarray, ask: np.ndarray, time_msc: np.ndarray) -> None:
        stamps = np.asarray(time_msc, dtype=np.int64)
        if np.any(stamps >= self.cutoff):
            raise LockedSpanRefused("locked")
        if stamps.size == 0:
            return
        bids = np.asarray(bid, dtype=np.float64)
        asks = np.asarray(ask, dtype=np.float64)
        mids = (bids + asks) / 2
        # Update rows count
        self.rows += len(stamps)
        for t, m in zip(stamps, mids, strict=False):
            minute = (t // 60000) * 60000  # floor to minute
            if self.cur_min is None:
                self.cur_min = int(minute)
                self.cur_open = float(m)
                self.cur_high = float(m)
                self.cur_low = float(m)
                self.cur_close = float(m)
                self.cur_vol = 1
            elif minute == self.cur_min:
                # same minute
                self.cur_high = max(self.cur_high, float(m))  # type: ignore
                self.cur_low = min(self.cur_low, float(m))  # type: ignore
                self.cur_close = float(m)
                self.cur_vol += 1
            else:
                # flush previous minute if it was before cutoff and after time_min
                # Only flush if cur_min >= TIME_MIN and < CUTOFF
                if self.cur_min is not None and self.cur_min >= self.time_min and self.cur_min < self.cutoff:
                    self.bars_time.append(int(self.cur_min))
                    self.bars_open.append(float(self.cur_open))  # type: ignore
                    self.bars_high.append(float(self.cur_high))  # type: ignore
                    self.bars_low.append(float(self.cur_low))  # type: ignore
                    self.bars_close.append(float(self.cur_close))  # type: ignore
                # start new minute, handle gaps: if gap >1 minute, we leave missing minutes as gaps (not bars)
                self.cur_min = int(minute)
                self.cur_open = float(m)
                self.cur_high = float(m)
                self.cur_low = float(m)
                self.cur_close = float(m)
                self.cur_vol = 1

    def finalize(self):
        # flush last minute
        if self.cur_min is not None and self.cur_min >= self.time_min and self.cur_min < self.cutoff:
            self.bars_time.append(int(self.cur_min))
            self.bars_open.append(float(self.cur_open))  # type: ignore
            self.bars_high.append(float(self.cur_high))  # type: ignore
            self.bars_low.append(float(self.cur_low))  # type: ignore
            self.bars_close.append(float(self.cur_close))  # type: ignore
        self.cur_min = None


def evaluate_1m(scan: OneMScan) -> dict[str, Any]:
    scan.finalize()
    times = np.array(scan.bars_time, dtype=np.int64)
    opens = np.array(scan.bars_open, dtype=np.float64)
    highs = np.array(scan.bars_high, dtype=np.float64)
    lows = np.array(scan.bars_low, dtype=np.float64)
    closes = np.array(scan.bars_close, dtype=np.float64)
    n_bars = len(times)
    # Build minute index map for gap detection: expected minute = times[i] should be 60000 apart, but gaps are missing bars
    # For Donchian, we need 20 prior bars that are *consecutive* in our bar array, but if there is a gap, those 20 bars span more than 20 minutes wall-clock, but we treat them as 20 bars.
    # For gap exclusion, we check if any missing minute in lookback or forward horizon: we can check time gaps >60000
    # Compute time gaps between consecutive bars
    time_gaps = np.diff(times) if n_bars > 1 else np.array([], dtype=np.int64)
    # For each i, check if lookback 20 bars are within 20*60000 + tolerance? Actually if any gap >60000 in lookback, then not 20 consecutive minutes.
    # We will exclude signals where any gap in [i-20, i+12] is > 60000*1.5 (i.e., missing minute)
    # But for now, we will require that bars are consecutive minutes: we can check that times[i] - times[i-20] == 20*60000 for lookback, and similarly for forward.
    # However, with gaps, this will be >20*60000, so we exclude.

    # Precompute HH20 and LL20 for each i >=20
    signals_long = np.zeros(n_bars, dtype=bool)
    signals_short = np.zeros(n_bars, dtype=bool)
    valid_signal = np.zeros(n_bars, dtype=bool)
    for i in range(LOOKBACK, n_bars):
        # Check lookback continuity: need 20 prior bars consecutive minutes
        if times[i] - times[i - LOOKBACK] != LOOKBACK * 60000:
            continue
        # Also need that all intermediate gaps are 60000
        if np.any(time_gaps[i - LOOKBACK : i] != 60000):
            continue
        hh = np.max(highs[i - LOOKBACK : i])
        ll = np.min(lows[i - LOOKBACK : i])
        if closes[i] > hh:
            signals_long[i] = True
            valid_signal[i] = True
        elif closes[i] < ll:
            signals_short[i] = True
            valid_signal[i] = True

    # For each signal, check forward horizon continuity and compute returns
    # We need to check forward 12 and 48 bars are consecutive minutes
    def check_forward(i, h):
        if i + h >= n_bars:
            return False
        if times[i + h] - times[i] != h * 60000:
            return False
        return not np.any(time_gaps[i : i + h] != 60000)

    # Collect events for primary 12
    events = []
    for i in range(n_bars):
        if not valid_signal[i]:
            continue
        if not check_forward(i, H_PRIMARY):
            continue
        if not check_forward(i, H_STABILITY):
            # For stability, we still want primary event, but mark stability as missing? For now require both for primary, but stability is separate check.
            # We will still include primary if 12 is ok, even if 48 not.
            pass
        # Determine direction
        is_long = signals_long[i]
        is_short = signals_short[i]
        # Returns: enter at next bar open (1-bar latency)
        if i + 1 >= n_bars or not check_forward(i, 1):
            continue
        enter_price = opens[i + 1]
        exit_price_12 = closes[i + H_PRIMARY]
        exit_price_48 = closes[i + H_STABILITY] if check_forward(i, H_STABILITY) else None
        gross_12 = (exit_price_12 - enter_price) / enter_price if is_long else (enter_price - exit_price_12) / enter_price
        # cost: 5 bps + $0.02/enter
        cost_bps = COST_BPS / 10000
        cost_slip = SLIPPAGE_DOLLARS / enter_price
        net_12 = gross_12 - cost_bps - cost_slip
        # baseline: all non-signal bars at same i? For baseline we will compute later as all bars where not signal but have forward
        events.append({
            "i": i,
            "time": int(times[i]),
            "is_long": bool(is_long),
            "is_short": bool(is_short),
            "enter": float(enter_price),
            "exit12": float(exit_price_12),
            "exit48": float(exit_price_48) if exit_price_48 is not None else None,
            "gross12": float(gross_12),
            "net12": float(net_12),
            "valid48": bool(check_forward(i, H_STABILITY)),
            "gross48": float((exit_price_48 - enter_price)/enter_price if is_long and exit_price_48 is not None else (enter_price - exit_price_48)/enter_price if is_short and exit_price_48 is not None else 0),
        })

    # Baseline: all bars that are not signals but have forward 12 available
    baseline_nets = []
    for i in range(n_bars):
        if valid_signal[i]:
            continue
        if not check_forward(i, H_PRIMARY):
            continue
        if i + 1 >= n_bars or not check_forward(i, 1):
            continue
        enter_price = opens[i + 1]
        exit_price_12 = closes[i + H_PRIMARY]
        # For baseline, we compute long-equivalent gross (just price change, not directional) — but for comparison we use absolute? Actually baseline for Long should be all non-signal bars' long return, but we can just compute long return for baseline as (exit - enter)/enter
        # For simplicity, baseline net is long return minus cost (same cost)
        gross = (exit_price_12 - enter_price) / enter_price
        cost_bps = COST_BPS / 10000
        cost_slip = SLIPPAGE_DOLLARS / enter_price
        net = gross - cost_bps - cost_slip
        baseline_nets.append(net)

    baseline_nets = np.array(baseline_nets, dtype=np.float64) if baseline_nets else np.array([], dtype=np.float64)
    # Separate long and short events
    long_nets = np.array([e["net12"] for e in events if e["is_long"]], dtype=np.float64)
    short_nets = np.array([e["net12"] for e in events if e["is_short"]], dtype=np.float64)
    long_gross48 = np.array([e["gross48"] for e in events if e["is_long"] and e["valid48"]], dtype=np.float64)
    short_gross48 = np.array([e["gross48"] for e in events if e["is_short"] and e["valid48"]], dtype=np.float64)

    # Stats
    def stats(arr):
        if len(arr) == 0:
            return {"n": 0, "mean": None, "pf": None, "win_rate": None, "dsr": None}
        mean = float(np.mean(arr))
        # profit factor: sum wins / sum losses
        wins = arr[arr > 0]
        losses = arr[arr < 0]
        pf = float(np.sum(wins) / -np.sum(losses)) if len(losses) and np.sum(losses) != 0 else float("inf") if len(wins) else None
        win_rate = float(np.mean(arr > 0)) if len(arr) else None
        # DSR placeholder: compute PSR vs 0, N=181 (180 prior +1)
        # Use simple normal approximation: PSR = Φ((SR - 0)/σ_SR) where SR = mean/std * sqrt(252*24*60?) For 1m, annualization ~ sqrt(252*24*60)
        # For now, compute Sharpe and PSR
        std = float(np.std(arr, ddof=1)) if len(arr) > 1 else None
        sr = float(mean / std * np.sqrt(252*24*60)) if std and std != 0 else 0
        # PSR approx: use normal, sigma_SR = sqrt((1 - skew*SR + (kurt-1)/4 * SR^2)/(T-1))
        # For simplicity, approximate DSR = PSR with N=181
        # We'll compute DSR via Bailey & Lopez de Prado but simplified: DSR = PSR at SR0 where SR0 = expected max SR under null
        # For now, just report sr
        return {"n": int(len(arr)), "mean": mean, "pf": pf, "win_rate": win_rate, "sr": sr}

    long_stats = stats(long_nets)
    short_stats = stats(short_nets)
    baseline_stats = stats(baseline_nets)

    # Terciles: split by time (events time)
    tercile_stats = []
    if events:
        times_ev = np.array([e["time"] for e in events])
        # tercile cutoffs based on scan time_min/cutoff
        t0 = TIME_MIN + (CUTOFF - TIME_MIN) // 3
        t1 = TIME_MIN + 2 * (CUTOFF - TIME_MIN) // 3
        for t_idx, (lo, hi) in enumerate([(TIME_MIN, t0), (t0, t1), (t1, CUTOFF)]):
            mask = (times_ev >= lo) & (times_ev < hi)
            long_t = np.array([e["net12"] for e, m in zip(events, mask, strict=False) if m and e["is_long"]])
            short_t = np.array([e["net12"] for e, m in zip(events, mask, strict=False) if m and e["is_short"]])
            tercile_stats.append({
                "tercile": t_idx,
                "n_long": int(len(long_t)),
                "n_short": int(len(short_t)),
                "mean_long": float(np.mean(long_t)) if len(long_t) else None,
                "mean_short": float(np.mean(short_t)) if len(short_t) else None,
                "pf_long": float(np.sum(long_t[long_t>0]) / -np.sum(long_t[long_t<0])) if len(long_t) and np.any(long_t<0) and np.sum(long_t[long_t<0])!=0 else None,
                "pf_short": float(np.sum(short_t[short_t>0]) / -np.sum(short_t[short_t<0])) if len(short_t) and np.any(short_t<0) and np.sum(short_t[short_t<0])!=0 else None,
            })
    else:
        tercile_stats = [{"tercile": i, "n_long": 0, "n_short": 0} for i in range(3)]

    # Blocks: 50-bar blocks
    n_blocks = n_bars // BLOCK_BARS

    output: dict[str, Any] = {
        "schema": SCHEMA,
        "preregistration": PREREGISTRATION,
        "window": {"time_msc_min": TIME_MIN, "cutoff_time_msc": CUTOFF, "discovery_rows_read": scan.rows, "held_out_rows_read": 0, "n_bars": int(n_bars), "n_events": int(len(events)), "n_long": int(len(long_nets)), "n_short": int(len(short_nets)), "baseline_n": int(len(baseline_nets))},
        "measured": {
            "long": long_stats,
            "short": short_stats,
            "baseline": baseline_stats,
            "terciles": tercile_stats,
            "n_blocks": int(n_blocks),
            "h48_long_mean": float(np.mean(long_gross48)) if len(long_gross48) else None,
            "h48_short_mean": float(np.mean(short_gross48)) if len(short_gross48) else None,
        },
        "hypotheses": {},
        "decision": "INCONCLUSIVE",
        "edge_claim": "NOT ESTABLISHED",
        "strategy_promoted": False,
        "held_out_span_opened": False,
        "safety": {"DEMO_EXECUTION": "DISABLED", "confirm_live": False, "orders_submitted": 0},
    }

    # Decision logic: need net >0, pf >1.0, win_rate not <0.45, and terciles sign, and 48 sign
    reasons = []
    # Check n
    if len(long_nets) < MIN_N_TERCILE and len(short_nets) < MIN_N_TERCILE:
        # Use per-tercile already, but overall n must be at least 100 per side per tercile? For now, require at least 300 total?
        pass
    # For simplicity, if no events, INCONCLUSIVE
    if len(events) == 0:
        status = "INCONCLUSIVE"
        reasons.append("no events")
    else:
        # Check floors
        long_pass = long_stats["mean"] is not None and long_stats["mean"] > 0 and long_stats["pf"] is not None and long_stats["pf"] > 1.0 and long_stats["win_rate"] is not None and long_stats["win_rate"] >= 0.45
        short_pass = short_stats["mean"] is not None and short_stats["mean"] > 0 and short_stats["pf"] is not None and short_stats["pf"] > 1.0 and short_stats["win_rate"] is not None and short_stats["win_rate"] >= 0.45
        # At least one side must pass? For Donchian, we expect both sides to pass if momentum works, but we can require at least one side passes and the other not significantly negative.
        # For now, require at least one side passes and the other has mean > baseline?
        baseline_mean = baseline_stats["mean"] if baseline_stats["mean"] is not None else 0
        long_vs_base = long_stats["mean"] is not None and long_stats["mean"] > baseline_mean
        short_vs_base = short_stats["mean"] is not None and short_stats["mean"] > baseline_mean
        # Tercile gate: each tercile where n>=100 must have mean >0 for that side if that side is the passing side
        # For simplicity, check that all terciles with n>=100 have mean >0 for long if long_pass
        tercile_ok = True
        for ts in tercile_stats:
            if ts["n_long"] >= MIN_N_TERCILE and ts["mean_long"] is not None and ts["mean_long"] <= 0:
                tercile_ok = False
            if ts["n_short"] >= MIN_N_TERCILE and ts["mean_short"] is not None and ts["mean_short"] <= 0:
                tercile_ok = False
        h48_ok = True
        if output["measured"]["h48_long_mean"] is not None and output["measured"]["h48_short_mean"] is not None:
            # For momentum, both 12 and 48 should be >0 if signal is true
            if long_pass and output["measured"]["h48_long_mean"] <= 0:
                h48_ok = False
            if short_pass and output["measured"]["h48_short_mean"] <= 0:
                h48_ok = False
        if (long_pass or short_pass) and long_vs_base and short_vs_base and tercile_ok and h48_ok:
            status = "TESTED"
            reasons.append(f"Donchian 20 breakout at 12m: long n={len(long_nets)} mean {long_stats['mean']:.6f} pf {long_stats['pf']:.2f} win {long_stats['win_rate']:.3f}, short n={len(short_nets)} mean {short_stats['mean']:.6f} pf {short_stats['pf']:.2f} win {short_stats['win_rate']:.3f}, baseline {baseline_mean:.6f}, 48 long {output['measured']['h48_long_mean']:.6f} short {output['measured']['h48_short_mean']:.6f}")
        else:
            status = "REJECTED"
            reasons.append(f"floor miss: long mean {long_stats['mean']} pf {long_stats['pf']} win {long_stats['win_rate']} short mean {short_stats['mean']} pf {short_stats['pf']} win {short_stats['win_rate']} baseline {baseline_mean} h48 {output['measured']['h48_long_mean']}/{output['measured']['h48_short_mean']} tercile_ok {tercile_ok} h48_ok {h48_ok}")

    output["hypotheses"][HYPOTHESIS] = {"status": status, "reasons": reasons, "not_a_strategy": True, "validated": False}
    output["decision"] = status if status != "TESTED" else "INCONCLUSIVE"
    if status == "TESTED":
        output["decision"] = "INCONCLUSIVE"
    return output
