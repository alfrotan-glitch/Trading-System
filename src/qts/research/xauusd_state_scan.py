"""State-conditional discovery scan for the canonical XAUUSD quote stream.

Definitions are locked in docs/xauusd_state_preregistration.md. The locked span
is not aggregated. No row is repaired. No strategy is built.
"""

from __future__ import annotations

import json
import math
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.parquet as pq
from scipy.stats import norm

from qts.data.mt5_history_acquisition import MANIFEST_FILENAME
from qts.research.impulse.statistics import holm_bonferroni
from qts.research.xauusd_microstructure import timestamp_basis_assessment
from qts.research.xauusd_tick_discovery import discovery_cutoff

SCHEMA = "qts.xauusd_state_scan.v1"
CARRY = 4128
HORIZONS = (4, 16, 64, 256, 1024, 4096)
PRIMARY_H = 256
STABILITY_H = 1024
HIST_LIMIT_HALF = 40_000
SPREAD_TIGHT_MAX = 20
SPREAD_TYPICAL = (21, 26)
SPREAD_WIDE_MIN = 27
SPREAD_MODE_22 = 22
SPREAD_MODE_38 = (37, 41)
ACTIVE_GAP_MS = 100
QUIET_GAP_MS = 500
HIGH_VOL = 0.20
LOW_VOL = 0.10
LONG_RUN = 5
PERSIST_MIN = 4
SLIPPAGE = 0.01
MIN_N = 1000
RATIO_MAIN = 1.25
RATIO_LEAVE = 1.15
RATIO_DELAY = 1.10
LIFT_FLOOR = 0.05
SIGN_FLOOR = 0.02
HOLM_ALPHA = 0.01
FAMILY = ("H-ST-01", "H-ST-02", "H-ST-03", "H-ST-04")
GENERATOR_N = 1000
GENERATOR_SIGNED = 0.25
GENERATOR_RATIO = 1.25
GENERATOR_LIFT = 0.05
PUBLISHED_ROWS = 139_930_971
PUBLISHED_CUTOFF = 1_764_563_969_254
PUBLISHED_DIGEST = "26aee827802066266fc5ef2f4ef30f874b0a7139666caf46f3bcfbec840e3789"
LOCKED_SPREAD = -10**12
STATES = (
    "unconditional",
    "spread_tight",
    "spread_typical",
    "spread_wide",
    "spread_mode_22",
    "spread_mode_38",
    "intensity_active",
    "intensity_normal",
    "intensity_quiet",
    "vol_high",
    "vol_low",
    "run_short",
    "run_long",
    "wide_active",
    "wide_quiet",
    "persist_stay",
    "persist_leave",
    "accel",
    "decel",
    "quiet_to_active",
    "active_to_quiet",
)


def run_lengths(signs: np.ndarray, seed_sign: int, seed_len: int) -> np.ndarray:
    """Run length at each sign. The seed is the run before the first sign."""
    values = np.asarray(signs, dtype=np.int8)
    if values.size == 0:
        return np.empty(0, dtype=np.int32)
    change = np.empty(values.shape[0], dtype=bool)
    change[0] = seed_len == 0 or int(values[0]) != int(seed_sign)
    if values.size > 1:
        change[1:] = values[1:] != values[:-1]
    idx = np.arange(values.size)
    starts = np.maximum.accumulate(np.where(change, idx, 0))
    lengths = (idx - starts + 1).astype(np.int32)
    if (not change[0]) and seed_len:
        nxt = np.flatnonzero(change)
        first_end = int(nxt[0]) if nxt.size else int(values.size)
        lengths[:first_end] += int(seed_len)
    return lengths


def persistence_counts(spread: np.ndarray, seed_spread: int, seed_len: int) -> np.ndarray:
    """How long the current spread level has lasted, including the current row."""
    values = np.asarray(spread)
    if values.size == 0:
        return np.empty(0, dtype=np.int32)
    change = np.empty(values.shape[0], dtype=bool)
    change[0] = seed_len == 0 or int(values[0]) != int(seed_spread)
    if values.size > 1:
        change[1:] = values[1:] != values[:-1]
    idx = np.arange(values.shape[0])
    starts = np.maximum.accumulate(np.where(change, idx, 0))
    lengths = (idx - starts + 1).astype(np.int32)
    if (not change[0]) and seed_len:
        nxt = np.flatnonzero(change)
        first_end = int(nxt[0]) if nxt.size else int(values.size)
        lengths[:first_end] += int(seed_len)
    return lengths


def hist_quantile(hist: np.ndarray, q: float) -> float | None:
    """Price quantile from a half-cent histogram. None when the cell is empty."""
    total = int(hist.sum())
    if total <= 0:
        return None
    target = q * (total - 1)
    pos = int(np.searchsorted(np.cumsum(hist), target, side="left"))
    pos = min(pos, hist.size - 1)
    return float(pos - HIST_LIMIT_HALF) * 0.005


def _ratio(sum_a: float, n_a: int, sum_b: float, n_b: int) -> float | None:
    if n_a <= 0 or n_b <= 0:
        return None
    if sum_b == 0:
        return None if sum_a == 0 else math.inf
    return (sum_a / n_a) / (sum_b / n_b)


def _pool(values: list[float] | np.ndarray) -> float:
    return float(np.asarray(values, dtype=np.float64).sum())


def _mean_diff_p(sum_a: float, sumsq_a: float, n_a: int, sum_b: float, sumsq_b: float, n_b: int) -> float:
    if n_a < 2 or n_b < 2:
        return 1.0
    mean_a, mean_b = sum_a / n_a, sum_b / n_b
    var_a = max((sumsq_a - sum_a * sum_a / n_a) / (n_a - 1), 0.0)
    var_b = max((sumsq_b - sum_b * sum_b / n_b) / (n_b - 1), 0.0)
    se = float(np.sqrt(var_a / n_a + var_b / n_b))
    if se == 0:
        return 0.0 if mean_a > mean_b else 1.0
    return float(norm.sf((mean_a - mean_b) / se))


def _sign_p(success: int, n: int) -> float:
    if n <= 0:
        return 1.0
    se = 0.5 / math.sqrt(n)
    return float(norm.sf((success / n - 0.5) / se))


def _agree(effects: list[float | None], counts: list[int]) -> str:
    seen = False
    for effect, count in zip(effects, counts, strict=True):
        if count < MIN_N:
            return "INCONCLUSIVE"
        seen = True
        if effect is None or effect <= 0:
            return "REJECTED"
    return "AGREE" if seen else "INCONCLUSIVE"


def _verdict(
    key: str,
    *,
    status: str,
    reason: str,
    raw_p: float,
    holm_p: float,
    effect: float | None,
    n_value: int,
    horizon_1024: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stored_effect = effect if effect is not None and math.isfinite(effect) else None
    row = {
        "id": key,
        "status": status,
        "reason": reason,
        "promoted": False,
        "executable": False,
        "not_a_strategy": True,
        "not_robust": True,
        "held_out_opened": False,
        "raw_p_value": raw_p,
        "holm_p_value": holm_p,
        "effect": stored_effect,
        "effect_infinite": effect is not None and not math.isfinite(effect),
        "n": n_value,
        "horizon_1024": horizon_1024,
    }
    if extra:
        row.update(extra)
    return row


def apply_verdicts(measured: dict[str, Any]) -> dict[str, Any]:
    """Apply the locked gates. A passed gate does not open the held-out span."""
    if int(measured.get("nonmonotonic") or 0):
        return {
            key: _verdict(
                key,
                status="INCONCLUSIVE",
                reason="backward time_msc steps were measured",
                raw_p=1.0,
                holm_p=1.0,
                effect=None,
                n_value=0,
                horizon_1024="undefined",
            )
            for key in FAMILY
        }
    raw_p: list[float] = []
    prepared: list[dict[str, Any]] = []
    for key, floor, kind, require_lift in (
        ("H-ST-01", RATIO_MAIN - 1.0, "magnitude", True),
        ("H-ST-02", RATIO_MAIN - 1.0, "magnitude", True),
        ("H-ST-03", SIGN_FLOOR, "directional", False),
        ("H-ST-04", RATIO_LEAVE - 1.0, "magnitude", False),
    ):
        block = measured[key]
        if kind == "magnitude":
            prepared.append(_prepare_magnitude(key, block, floor, require_lift, raw_p))
        else:
            prepared.append(_prepare_fade(key, block, raw_p))
    adjusted = holm_bonferroni(raw_p)
    verdicts = {}
    for pos, item in enumerate(prepared):
        verdicts[item["key"]] = _finish_status(item, adjusted[pos], raw_p[pos])
    return verdicts


def _prepare_magnitude(key: str, block: dict[str, Any], floor: float, require_lift: bool, raw_p: list[float]) -> dict[str, Any]:
    a_n, b_n = int(_pool(block["a_n"])), int(_pool(block["b_n"]))
    ratio = _ratio(_pool(block["a_sum"]), a_n, _pool(block["b_sum"]), b_n)
    effect = None if ratio is None else ratio - 1.0
    terciles: list[float | None] = []
    counts: list[int] = []
    for t in range(3):
        counts.append(min(int(block["a_n"][t]), int(block["b_n"][t])))
        ratio_t = _ratio(block["a_sum"][t], int(block["a_n"][t]), block["b_sum"][t], int(block["b_n"][t]))
        terciles.append(None if ratio_t is None else ratio_t - 1.0)
    lift = None
    if a_n and b_n:
        lift = _pool(block["a_exceed"]) / a_n - _pool(block["b_exceed"]) / b_n
    delay_ratio = _ratio(_pool(block["delay_a_sum"]), int(_pool(block["delay_a_n"])), _pool(block["delay_b_sum"]), int(_pool(block["delay_b_n"])))
    delay_n = min(int(_pool(block["delay_a_n"])), int(_pool(block["delay_b_n"])))
    longer_n = min(int(block["longer_a_n"]), int(block["longer_b_n"]))
    longer_ratio = _ratio(block["longer_a_sum"], int(block["longer_a_n"]), block["longer_b_sum"], int(block["longer_b_n"]))
    longer = None if longer_ratio is None else longer_ratio - 1.0
    raw_p.append(_mean_diff_p(_pool(block["a_sum"]), _pool(block["a_sumsq"]), a_n, _pool(block["b_sum"]), _pool(block["b_sumsq"]), b_n))
    return {
        "key": key,
        "kind": "magnitude",
        "effect": effect,
        "floor": floor,
        "terciles": terciles,
        "counts": counts,
        "n": min(a_n, b_n),
        "lift": lift,
        "require_lift": require_lift,
        "delay_ratio": delay_ratio,
        "delay_n": delay_n,
        "longer": longer,
        "longer_n": longer_n,
        "residual": None,
    }


def _prepare_fade(key: str, block: dict[str, Any], raw_p: list[float]) -> dict[str, Any]:
    n_value = int(_pool(block["n"]))
    fades = int(_pool(block["fade"]))
    effect = (fades / n_value - 0.5) if n_value else None
    terciles = [(block["fade"][t] / block["n"][t] - 0.5) if block["n"][t] else None for t in range(3)]
    counts = [int(v) for v in block["n"]]
    residual = _pool(block["residual"]) / n_value if n_value else None
    delay_n = int(_pool(block["delay_n"]))
    delay_rate = _pool(block["delay_fade"]) / delay_n if delay_n else None
    delay_residual = _pool(block["delay_residual"]) / delay_n if delay_n else None
    longer_n = int(block["longer_n"])
    longer = (block["longer_fade"] / longer_n - 0.5) if longer_n else None
    raw_p.append(_sign_p(fades, n_value))
    return {
        "key": key,
        "kind": "directional",
        "effect": effect,
        "floor": SIGN_FLOOR,
        "terciles": terciles,
        "counts": counts,
        "n": n_value,
        "residual": residual,
        "delay_n": delay_n,
        "delay_rate": delay_rate,
        "delay_residual": delay_residual,
        "up_n": int(_pool(block["up_n"])),
        "down_n": int(_pool(block["down_n"])),
        "up_rate": (_pool(block["up_fade"]) / _pool(block["up_n"])) if _pool(block["up_n"]) else None,
        "down_rate": (_pool(block["down_fade"]) / _pool(block["down_n"])) if _pool(block["down_n"]) else None,
        "up_residual": (_pool(block["up_residual"]) / _pool(block["up_n"])) if _pool(block["up_n"]) else None,
        "down_residual": (_pool(block["down_residual"]) / _pool(block["down_n"])) if _pool(block["down_n"]) else None,
        "longer": longer,
        "longer_n": longer_n,
        "require_lift": False,
    }


def _horizon_note(effect: float | None, longer: float | None, longer_n: int) -> str:
    if effect is None:
        return "undefined"
    if longer_n < MIN_N or longer is None:
        return "underpowered"
    return "agrees" if longer > 0 else "disagrees"


def _finish_status(item: dict[str, Any], holm_p: float, raw_p: float) -> dict[str, Any]:
    key = item["key"]
    note = _horizon_note(item["effect"], item["longer"], item["longer_n"])
    common = {"raw_p": raw_p, "holm_p": holm_p, "effect": item["effect"], "n_value": item["n"], "horizon_1024": note}
    if item["n"] < MIN_N or item["effect"] is None:
        return _verdict(key, status="INCONCLUSIVE", reason="inferential sample is below 1000 or undefined", **common)
    if item["effect"] < item["floor"]:
        return _verdict(key, status="REJECTED", reason=f"predicted effect {item['effect']:.6g} is below the floor {item['floor']}", **common)
    stability = _agree(item["terciles"], item["counts"])
    if stability == "REJECTED":
        return _verdict(key, status="REJECTED", reason="a discovery tercile disagrees in sign", **common)
    if stability == "INCONCLUSIVE":
        return _verdict(key, status="INCONCLUSIVE", reason="a discovery tercile is below 1000", **common)
    if note == "disagrees":
        return _verdict(key, status="REJECTED", reason="horizon 1024 disagrees in sign", **common)
    if item["kind"] == "magnitude":
        return _magnitude_status(item, common)
    return _fade_status(item, common)


def _magnitude_status(item: dict[str, Any], common: dict[str, Any]) -> dict[str, Any]:
    key = item["key"]
    if item["require_lift"] and (item["lift"] is None or item["lift"] < LIFT_FLOOR):
        return _verdict(key, status="REJECTED", reason="exceed-spread lift is below 0.05", **common)
    if item["delay_n"] < MIN_N or item["delay_ratio"] is None:
        return _verdict(key, status="INCONCLUSIVE", reason="delay sample is below 1000 or undefined", **common)
    if item["delay_ratio"] < RATIO_DELAY:
        return _verdict(key, status="REJECTED", reason="delay ratio is below 1.10", **common)
    if common["holm_p"] >= HOLM_ALPHA:
        return _verdict(key, status="REJECTED", reason="Holm-adjusted p-value is not below 0.01", **common)
    return _verdict(
        key,
        status="TESTED",
        reason="magnitude structure is present; it is not a directional trade and not a strategy",
        extra={"magnitude_structure": True, "delay_ratio": item["delay_ratio"]},
        **common,
    )


def _fade_status(item: dict[str, Any], common: dict[str, Any]) -> dict[str, Any]:
    key = item["key"]
    if item["residual"] is None or item["residual"] <= 0:
        return _verdict(key, status="REJECTED", reason="fade residual after one spread plus one cent is not positive", **common)
    if item["up_n"] < MIN_N or item["down_n"] < MIN_N:
        return _verdict(key, status="INCONCLUSIVE", reason="one run direction is below 1000", **common)
    up_ok = item["up_rate"] is not None and item["up_rate"] > 0.5 and item["up_residual"] is not None and item["up_residual"] > 0
    down_ok = item["down_rate"] is not None and item["down_rate"] > 0.5 and item["down_residual"] is not None and item["down_residual"] > 0
    if not up_ok or not down_ok:
        return _verdict(key, status="REJECTED", reason="the two run directions do not both fade after cost", **common)
    if item["delay_n"] < MIN_N or item["delay_rate"] is None or item["delay_residual"] is None:
        return _verdict(key, status="INCONCLUSIVE", reason="delay sample is below 1000 or undefined", **common)
    if item["delay_rate"] <= 0.5 or item["delay_residual"] <= 0:
        return _verdict(key, status="REJECTED", reason="one-quote delay does not agree", **common)
    if common["holm_p"] >= HOLM_ALPHA:
        return _verdict(key, status="REJECTED", reason="Holm-adjusted p-value is not below 0.01", **common)
    return _verdict(
        key,
        status="PROMISING",
        reason="discovery gates passed; held-out span was not opened; not a strategy",
        extra={"residual_bps": item["residual"]},
        **common,
    )


def _blank_magnitude() -> dict[str, Any]:
    return {
        "a_n": np.zeros(3, dtype=np.int64),
        "a_sum": np.zeros(3, dtype=np.float64),
        "a_sumsq": np.zeros(3, dtype=np.float64),
        "a_exceed": np.zeros(3, dtype=np.int64),
        "b_n": np.zeros(3, dtype=np.int64),
        "b_sum": np.zeros(3, dtype=np.float64),
        "b_sumsq": np.zeros(3, dtype=np.float64),
        "b_exceed": np.zeros(3, dtype=np.int64),
        "delay_a_n": np.zeros(3, dtype=np.int64),
        "delay_a_sum": np.zeros(3, dtype=np.float64),
        "delay_b_n": np.zeros(3, dtype=np.int64),
        "delay_b_sum": np.zeros(3, dtype=np.float64),
        "longer_a_n": 0,
        "longer_a_sum": 0.0,
        "longer_b_n": 0,
        "longer_b_sum": 0.0,
    }


def _blank_fade() -> dict[str, Any]:
    return {
        "n": np.zeros(3, dtype=np.int64),
        "fade": np.zeros(3, dtype=np.int64),
        "residual": np.zeros(3, dtype=np.float64),
        "up_n": np.zeros(3, dtype=np.int64),
        "up_fade": np.zeros(3, dtype=np.int64),
        "up_residual": np.zeros(3, dtype=np.float64),
        "down_n": np.zeros(3, dtype=np.int64),
        "down_fade": np.zeros(3, dtype=np.int64),
        "down_residual": np.zeros(3, dtype=np.float64),
        "delay_n": np.zeros(3, dtype=np.int64),
        "delay_fade": np.zeros(3, dtype=np.int64),
        "delay_residual": np.zeros(3, dtype=np.float64),
        "longer_n": 0,
        "longer_fade": 0,
    }


class StateScan:
    def __init__(self, time_min: int, cutoff: int, horizons: tuple[int, ...] = HORIZONS, carry: int = CARRY) -> None:
        if cutoff <= time_min:
            raise ValueError("cutoff must be after time_min")
        if carry < 2:
            raise ValueError("carry must keep the quote before the next batch")
        self.time_min = int(time_min)
        self.cutoff = int(cutoff)
        self.span = self.cutoff - self.time_min
        self.horizons = tuple(horizons)
        self.carry = int(carry)
        self.rows = 0
        self.discovery_rows = 0
        self.validation_rows = 0
        self.nonmonotonic = 0
        self.negative_spread_rows = 0
        self.carry_n = 0
        self.carry_bid = np.empty(0, dtype=np.int32)
        self.carry_ask = np.empty(0, dtype=np.int32)
        self.carry_stamp = np.empty(0, dtype=np.int64)
        self.seed_sign = 0
        self.seed_len = 0
        self.entry_sign = 0
        self.seed_spread = 0
        self.seed_persist = 0
        n_h = len(self.horizons)
        n_s = len(STATES)
        self.n = np.zeros((n_s, n_h), dtype=np.int64)
        self.signed_sum = np.zeros((n_s, n_h), dtype=np.float64)
        self.abs_sum = np.zeros((n_s, n_h), dtype=np.float64)
        self.spread_sum = np.zeros((n_s, n_h), dtype=np.float64)
        self.up_n = np.zeros((n_s, n_h), dtype=np.int64)
        self.down_n = np.zeros((n_s, n_h), dtype=np.int64)
        self.up_sum = np.zeros((n_s, n_h), dtype=np.float64)
        self.down_sum = np.zeros((n_s, n_h), dtype=np.float64)
        self.exceed_n = np.zeros((n_s, n_h), dtype=np.int64)
        self.exceed_slip_n = np.zeros((n_s, n_h), dtype=np.int64)
        self.hist = np.zeros((n_s, n_h, HIST_LIMIT_HALF * 2 + 1), dtype=np.int64)
        self.conf = {key: _blank_magnitude() for key in ("H-ST-01", "H-ST-02", "H-ST-04")}
        self.fade = _blank_fade()

    def add_batch(self, bid: np.ndarray, ask: np.ndarray, stamp: np.ndarray) -> None:
        bid_c = np.rint(np.asarray(bid, dtype=np.float64) * 100.0).astype(np.int32)
        ask_c = np.rint(np.asarray(ask, dtype=np.float64) * 100.0).astype(np.int32)
        stamp_a = np.asarray(stamp, dtype=np.int64)
        n_new = int(bid_c.shape[0])
        if n_new == 0:
            return
        self.rows += n_new
        self.discovery_rows += int(np.count_nonzero(stamp_a < self.cutoff))
        self.validation_rows += int(np.count_nonzero(stamp_a >= self.cutoff))
        self.negative_spread_rows += int(np.count_nonzero(ask_c < bid_c))
        carry_n = self.carry_n
        if carry_n:
            bid_c = np.concatenate((self.carry_bid, bid_c))
            ask_c = np.concatenate((self.carry_ask, ask_c))
            stamp_a = np.concatenate((self.carry_stamp, stamp_a))
        series_n = int(bid_c.shape[0])
        global_base = self.rows - n_new - carry_n
        if series_n >= 2:
            features = self._features(bid_c, ask_c, stamp_a)
            self._consume(features, carry_n, global_base)
            self._commit_seed(features)
        tail = min(self.carry, series_n)
        self.carry_bid = bid_c[-tail:].copy()
        self.carry_ask = ask_c[-tail:].copy()
        self.carry_stamp = stamp_a[-tail:].copy()
        self.carry_n = tail

    def _features(self, bid_c: np.ndarray, ask_c: np.ndarray, stamp_a: np.ndarray) -> dict[str, Any]:
        series_n = int(bid_c.shape[0])
        spread = ask_c.astype(np.int64) - bid_c.astype(np.int64)
        locked = stamp_a >= self.cutoff
        mid_half = bid_c.astype(np.int64) + ask_c.astype(np.int64)
        signs_into = np.zeros(series_n, dtype=np.int8)
        signs_into[0] = 0 if locked[0] else self.entry_sign
        dmid = np.diff(mid_half)
        finite = ~(locked[1:] | locked[:-1])
        signs_into[1:][finite & (dmid > 0)] = 1
        signs_into[1:][finite & (dmid < 0)] = -1
        seed_sign = 0 if locked[0] else self.seed_sign
        seed_len = 0 if locked[0] else self.seed_len
        lengths = run_lengths(signs_into, seed_sign, seed_len)
        spread_p = spread.copy()
        if locked.any():
            spread_p[locked] = -1_000_000_000 - np.flatnonzero(locked)
        persist = persistence_counts(spread_p, 0 if locked[0] else self.seed_spread, 0 if locked[0] else self.seed_persist)
        return {
            "spread": spread,
            "locked": locked,
            "locked_cum": np.cumsum(locked.astype(np.int32)),
            "mid_half": mid_half,
            "stamp": stamp_a,
            "signs_into": signs_into,
            "lengths": lengths,
            "persist": persist,
            "masks": series_masks(spread, locked, stamp_a, mid_half, signs_into, lengths, persist),
        }

    def _commit_seed(self, features: dict[str, Any]) -> None:
        series_n = int(features["spread"].shape[0])
        if series_n <= self.carry:
            return
        start = series_n - self.carry
        prev = start - 1
        locked = features["locked"]
        if locked[prev]:
            self.seed_sign = 0
            self.seed_len = 0
            self.seed_spread = LOCKED_SPREAD
            self.seed_persist = 0
        else:
            self.seed_sign = int(features["signs_into"][prev])
            self.seed_len = int(features["lengths"][prev])
            self.seed_spread = int(features["spread"][prev])
            self.seed_persist = int(features["persist"][prev])
        self.entry_sign = 0 if locked[start] or locked[prev] else int(features["signs_into"][start])

    def _consume(self, features: dict[str, Any], carry_n: int, global_base: int) -> None:
        stamp = features["stamp"]
        series_n = int(stamp.shape[0])
        gap = np.diff(stamp)
        new_gap = np.zeros(gap.shape[0], dtype=bool)
        if carry_n < series_n:
            new_gap[max(carry_n - 1, 0) :] = True
        self.nonmonotonic += int(np.count_nonzero((gap < 0) & new_gap & (stamp[1:] < self.cutoff)))
        for h_index, horizon in enumerate(self.horizons):
            self._horizon(h_index, horizon, features, carry_n, global_base)
        if PRIMARY_H in self.horizons:
            self._delay(features, carry_n, global_base)

    def _horizon(self, h_index: int, horizon: int, features: dict[str, Any], carry_n: int, global_base: int) -> None:
        selected = self._select(horizon, 0, features, carry_n, global_base)
        if selected is None:
            return
        i, move, dmid, spread_i, stamp_i, usable = selected
        self._record_panel(h_index, i, move, dmid, spread_i, usable, features["masks"])
        if horizon == PRIMARY_H:
            tercile = self._tercile(stamp_i, usable)
            self._record_primary(i, move, dmid, spread_i, usable, tercile, features)
        elif horizon == STABILITY_H:
            self._record_stability(i, move, usable, features)

    def _select(self, horizon: int, extra: int, features: dict[str, Any], carry_n: int, global_base: int):
        series_n = int(features["stamp"].shape[0])
        start = max(carry_n, horizon + 1 + extra)
        if start >= series_n:
            return None
        end = np.arange(start, series_n, dtype=np.int64)
        i = end - horizon - extra
        origin = i + extra
        locked_cum = features["locked_cum"]
        stamp = features["stamp"]
        mid = features["mid_half"]
        spread = features["spread"]
        touches = locked_cum[end] > locked_cum[i]
        usable = (
            (i >= 1)
            & ~features["locked"][i]
            & ~features["locked"][origin]
            & ~features["locked"][end]
            & ~touches
            & (spread[i] >= 0)
            & (stamp[i] < self.cutoff)
            & (stamp[origin] < self.cutoff)
            & (stamp[end] < self.cutoff)
            & (stamp[i - 1] < self.cutoff)
            & (((global_base + i) % (horizon + 1)) == 0)
        )
        if not usable.any():
            return None
        dmid = mid[end] - mid[origin]
        move = dmid * 0.005
        return i, move, dmid, spread[i], stamp[i], usable

    def _tercile(self, stamp_i: np.ndarray, usable: np.ndarray) -> np.ndarray:
        tercile = np.zeros(stamp_i.shape[0], dtype=np.int8)
        tercile[usable] = np.clip(((stamp_i[usable] - self.time_min) * 3) // self.span, 0, 2)
        return tercile

    def _record_panel(self, h_index, i, move, dmid, spread_i, usable, masks) -> None:
        chosen_i = i[usable]
        values = move[usable]
        half = dmid[usable]
        sp = spread_i[usable]
        bins = np.clip(half, -HIST_LIMIT_HALF, HIST_LIMIT_HALF) + HIST_LIMIT_HALF
        exceed = np.abs(half) > sp * 2
        exceed_slip = np.abs(half) > sp * 2 + 2
        up = values > 0
        down = values < 0
        for pos, name in enumerate(STATES):
            take = masks[name][chosen_i]
            if not take.any():
                continue
            v = values[take]
            self.n[pos, h_index] += int(v.size)
            self.signed_sum[pos, h_index] += float(v.sum())
            self.abs_sum[pos, h_index] += float(np.abs(v).sum())
            self.spread_sum[pos, h_index] += float((sp[take] * 0.01).sum())
            self.up_n[pos, h_index] += int(np.count_nonzero(up[take]))
            self.down_n[pos, h_index] += int(np.count_nonzero(down[take]))
            if up[take].any():
                self.up_sum[pos, h_index] += float(v[up[take]].sum())
            if down[take].any():
                self.down_sum[pos, h_index] += float(v[down[take]].sum())
            self.exceed_n[pos, h_index] += int(np.count_nonzero(exceed[take]))
            self.exceed_slip_n[pos, h_index] += int(np.count_nonzero(exceed_slip[take]))
            np.add.at(self.hist[pos, h_index], bins[take], 1)

    def _record_primary(self, i, move, dmid, spread_i, usable, tercile, features) -> None:
        masks = features["masks"]
        abs_move = np.abs(move)
        exceed = np.abs(dmid) > spread_i * 2
        self._sides(self.conf["H-ST-01"], masks["wide_active"][i], masks["wide_quiet"][i], usable, tercile, abs_move, exceed)
        self._sides(self.conf["H-ST-02"], masks["vol_high"][i], masks["vol_low"][i], usable, tercile, abs_move, exceed)
        self._sides(self.conf["H-ST-04"], masks["persist_leave"][i], masks["persist_stay"][i], usable, tercile, abs_move, exceed)
        self._record_fade(i, i, move, spread_i, usable, tercile, features, delayed=False)

    def _sides(self, block, mask_a, mask_b, usable, tercile, values, exceed) -> None:
        self._side(block, "a", usable & mask_a, tercile, values, exceed)
        self._side(block, "b", usable & mask_b, tercile, values, exceed)

    def _side(self, block, prefix, mask, tercile, values, exceed) -> None:
        chosen = np.flatnonzero(mask & np.isfinite(values))
        if chosen.size == 0:
            return
        t = tercile[chosen].astype(np.int64)
        v = values[chosen]
        block[f"{prefix}_n"] += np.bincount(t, minlength=3)
        block[f"{prefix}_sum"] += np.bincount(t, weights=v, minlength=3)
        if f"{prefix}_sumsq" in block:
            block[f"{prefix}_sumsq"] += np.bincount(t, weights=v * v, minlength=3)
            block[f"{prefix}_exceed"] += np.bincount(t, weights=exceed[chosen].astype(np.float64), minlength=3).astype(np.int64)

    def _record_fade(self, i, origin_index, move, spread_at_origin, usable, tercile, features, delayed: bool) -> None:
        sign = features["signs_into"][i]
        run_long = features["masks"]["run_long"][i]
        mid = features["mid_half"][origin_index] * 0.005
        chosen = usable & run_long & (sign != 0) & (mid > 0) & (spread_at_origin >= 0) & np.isfinite(move)
        if not chosen.any():
            return
        cost = spread_at_origin * 0.01 + SLIPPAGE
        residual = (-sign * move - cost) / mid * 10000.0
        fade = np.sign(move) == -sign
        block = self.fade
        prefix = "delay_" if delayed else ""
        t = tercile[chosen].astype(np.int64)
        block[f"{prefix}n"] += np.bincount(t, minlength=3)
        block[f"{prefix}fade"] += np.bincount(t, weights=fade[chosen].astype(np.float64), minlength=3).astype(np.int64)
        block[f"{prefix}residual"] += np.bincount(t, weights=residual[chosen], minlength=3)
        if delayed:
            return
        up = chosen & (sign > 0)
        down = chosen & (sign < 0)
        for name, mask in (("up", up), ("down", down)):
            if not mask.any():
                continue
            tt = tercile[mask].astype(np.int64)
            block[f"{name}_n"] += np.bincount(tt, minlength=3)
            block[f"{name}_fade"] += np.bincount(tt, weights=fade[mask].astype(np.float64), minlength=3).astype(np.int64)
            block[f"{name}_residual"] += np.bincount(tt, weights=residual[mask], minlength=3)

    def _record_stability(self, i, move, usable, features) -> None:
        masks = features["masks"]
        abs_move = np.abs(move)
        for key, left, right in (
            ("H-ST-01", "wide_active", "wide_quiet"),
            ("H-ST-02", "vol_high", "vol_low"),
            ("H-ST-04", "persist_leave", "persist_stay"),
        ):
            for prefix, name in (("longer_a", left), ("longer_b", right)):
                take = usable & masks[name][i] & np.isfinite(abs_move)
                block = self.conf[key]
                block[f"{prefix}_n"] += int(np.count_nonzero(take))
                if take.any():
                    block[f"{prefix}_sum"] += float(abs_move[take].sum())
        sign = features["signs_into"][i]
        fade_take = usable & masks["run_long"][i] & (sign != 0) & np.isfinite(move)
        if fade_take.any():
            self.fade["longer_n"] += int(np.count_nonzero(fade_take))
            self.fade["longer_fade"] += int(np.count_nonzero(fade_take & (np.sign(move) == -sign)))

    def _delay(self, features: dict[str, Any], carry_n: int, global_base: int) -> None:
        selected = self._select(PRIMARY_H, 1, features, carry_n, global_base)
        if selected is None:
            return
        i, move, _dmid, _spread_i, stamp_i, usable = selected
        origin = i + 1
        spread_origin = features["spread"][origin]
        abs_move = np.abs(move)
        tercile = self._tercile(stamp_i, usable)
        masks = features["masks"]
        dummy = np.zeros(i.shape[0], dtype=bool)
        self._side(self.conf["H-ST-01"], "delay_a", usable & masks["wide_active"][i], tercile, abs_move, dummy)
        self._side(self.conf["H-ST-01"], "delay_b", usable & masks["wide_quiet"][i], tercile, abs_move, dummy)
        self._side(self.conf["H-ST-02"], "delay_a", usable & masks["vol_high"][i], tercile, abs_move, dummy)
        self._side(self.conf["H-ST-02"], "delay_b", usable & masks["vol_low"][i], tercile, abs_move, dummy)
        self._side(self.conf["H-ST-04"], "delay_a", usable & masks["persist_leave"][i], tercile, abs_move, dummy)
        self._side(self.conf["H-ST-04"], "delay_b", usable & masks["persist_stay"][i], tercile, abs_move, dummy)
        self._record_fade(i, origin, move, spread_origin, usable, tercile, features, delayed=True)

    def finish(self) -> dict[str, Any]:
        measured: dict[str, Any] = {"nonmonotonic": self.nonmonotonic, "H-ST-03": _pack_magnitude(self.fade)}
        for key, block in self.conf.items():
            measured[key] = _pack_magnitude(block)
        return measured

    def summaries(self) -> list[dict[str, Any]]:
        rows = []
        for pos, name in enumerate(STATES):
            for h_index, horizon in enumerate(self.horizons):
                n = int(self.n[pos, h_index])
                if n == 0:
                    continue
                hist = self.hist[pos, h_index]
                overflow = int(hist[0] + hist[-1])
                up_n = int(self.up_n[pos, h_index])
                down_n = int(self.down_n[pos, h_index])
                rows.append(
                    {
                        "state": name,
                        "horizon_quotes": int(horizon),
                        "horizon_role": _horizon_role(int(horizon)),
                        "n": n,
                        "mean_signed": float(self.signed_sum[pos, h_index] / n),
                        "mean_abs": float(self.abs_sum[pos, h_index] / n),
                        "mean_spread": float(self.spread_sum[pos, h_index] / n),
                        "p_up": up_n / n,
                        "p_down": down_n / n,
                        "mean_up": float(self.up_sum[pos, h_index] / up_n) if up_n else None,
                        "mean_down": float(self.down_sum[pos, h_index] / down_n) if down_n else None,
                        "p_exceed_spread": float(self.exceed_n[pos, h_index] / n),
                        "p_exceed_spread_plus_tick": float(self.exceed_slip_n[pos, h_index] / n),
                        "p10": hist_quantile(hist, 0.10),
                        "p50": hist_quantile(hist, 0.50),
                        "p90": hist_quantile(hist, 0.90),
                        "histogram_overflow_fraction": overflow / n,
                        "histogram_limit_price": HIST_LIMIT_HALF * 0.005,
                        "role": "REFERENCE" if name == "unconditional" else "EXPLORATORY",
                    }
                )
        return rows


def series_masks(spread, locked, stamp, mid_half, signs_into, lengths, persist) -> dict[str, np.ndarray]:
    """Backward-looking states. None of these reads the future move."""
    n = int(spread.shape[0])
    gap_into = np.zeros(n, dtype=np.int64)
    gap_into[1:] = np.diff(stamp)
    active = (gap_into > 0) & (gap_into <= ACTIVE_GAP_MS) & ~locked
    quiet = (gap_into > QUIET_GAP_MS) & ~locked
    normal = (gap_into > ACTIVE_GAP_MS) & (gap_into <= QUIET_GAP_MS) & ~locked
    wide = (spread >= SPREAD_WIDE_MIN) & ~locked
    locked_cum = np.cumsum(locked.astype(np.int32))
    vol = np.full(n, np.nan)
    if n > 16:
        valid16 = (~locked[16:]) & (~locked[:-16]) & (locked_cum[16:] == locked_cum[:-16])
        vol[16:] = np.where(valid16, np.abs(mid_half[16:] - mid_half[:-16]) * 0.005, np.nan)
    accel = np.zeros(n, dtype=bool)
    decel = np.zeros(n, dtype=bool)
    if n > 32:
        valid32 = (~locked[32:]) & (~locked[:-32]) & (locked_cum[32:] == locked_cum[:-32])
        recent = np.abs(mid_half[32:] - mid_half[16:-16])
        prior = np.abs(mid_half[16:-16] - mid_half[:-32])
        accel[32:] = valid32 & (recent > prior)
        decel[32:] = valid32 & (recent < prior)
    prev_gap = np.zeros(n, dtype=np.int64)
    prev_gap[2:] = gap_into[1:-1]
    has_prev = np.zeros(n, dtype=bool)
    has_prev[2:] = True
    stay = (persist >= PERSIST_MIN + 1) & ~locked
    leave = np.zeros(n, dtype=bool)
    leave[1:] = (persist[:-1] >= PERSIST_MIN) & (persist[1:] == 1) & ~locked[1:]
    return {
        "unconditional": ~locked & (spread >= 0),
        "spread_tight": (spread >= 0) & (spread <= SPREAD_TIGHT_MAX) & ~locked,
        "spread_typical": (spread >= SPREAD_TYPICAL[0]) & (spread <= SPREAD_TYPICAL[1]) & ~locked,
        "spread_wide": wide,
        "spread_mode_22": (spread == SPREAD_MODE_22) & ~locked,
        "spread_mode_38": (spread >= SPREAD_MODE_38[0]) & (spread <= SPREAD_MODE_38[1]) & ~locked,
        "intensity_active": active,
        "intensity_normal": normal,
        "intensity_quiet": quiet,
        "vol_high": np.isfinite(vol) & (vol >= HIGH_VOL) & ~locked,
        "vol_low": np.isfinite(vol) & (vol <= LOW_VOL) & ~locked,
        "run_short": (signs_into != 0) & (lengths >= 1) & (lengths <= 2) & ~locked,
        "run_long": (signs_into != 0) & (lengths >= LONG_RUN) & ~locked,
        "wide_active": wide & active,
        "wide_quiet": wide & quiet,
        "persist_stay": stay,
        "persist_leave": leave,
        "accel": accel & ~locked,
        "decel": decel & ~locked,
        "quiet_to_active": has_prev & (prev_gap > QUIET_GAP_MS) & active,
        "active_to_quiet": has_prev & (prev_gap > 0) & (prev_gap <= ACTIVE_GAP_MS) & quiet,
    }


def _pack_magnitude(block: dict[str, Any]) -> dict[str, Any]:
    packed = {}
    for key, value in block.items():
        packed[key] = value.tolist() if isinstance(value, np.ndarray) else value
    return packed


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _horizon_role(horizon: int) -> str:
    if horizon == PRIMARY_H:
        return "primary_inference_for_the_confirmatory_family_only"
    if horizon == STABILITY_H:
        return "sign_stability"
    return "descriptive"


def rank_exploratory(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pre-declared ranking. Listed cells are generators, not tests."""
    reference = {row["horizon_quotes"]: row for row in rows if row["state"] == "unconditional"}
    generated = []
    for row in rows:
        if row["state"] == "unconditional" or row["n"] < GENERATOR_N:
            continue
        base = reference.get(row["horizon_quotes"])
        if not base or base["mean_abs"] <= 0:
            continue
        reasons = []
        signed_score = None
        if row["mean_spread"] > 0:
            signed_score = abs(row["mean_signed"]) / row["mean_spread"]
            if signed_score >= GENERATOR_SIGNED:
                reasons.append(f"signed move is {signed_score:.3f} of the cell spread")
        ratio = row["mean_abs"] / base["mean_abs"]
        if ratio >= GENERATOR_RATIO:
            reasons.append(f"absolute move is {ratio:.3f} times the unconditional mean")
        lift = row["p_exceed_spread"] - base["p_exceed_spread"]
        if lift >= GENERATOR_LIFT:
            reasons.append(f"exceed-spread probability is {lift:.3f} above unconditional")
        if not reasons:
            continue
        generated.append(
            {
                "state": row["state"],
                "horizon_quotes": row["horizon_quotes"],
                "n": row["n"],
                "status": "NOT TESTED",
                "role": "HYPOTHESIS_GENERATOR",
                "reason": "; ".join(reasons),
                "mean_signed": row["mean_signed"],
                "mean_abs": row["mean_abs"],
                "mean_spread": row["mean_spread"],
                "p_exceed_spread": row["p_exceed_spread"],
                "signed_score": signed_score,
                "cannot_confirm_on_this_discovery_sample": True,
            }
        )
    generated.sort(key=lambda item: (item["signed_score"] or 0.0, abs(item["mean_abs"])), reverse=True)
    return generated


def scan_dataset(dataset_dir: Path) -> dict[str, Any]:
    dataset_dir = Path(dataset_dir)
    manifest = _read_manifest(dataset_dir)
    parts = manifest.get("parts") or []
    time_min, time_max = _stamp_range(dataset_dir, parts)
    cutoff = discovery_cutoff(time_min, time_max)
    scan = StateScan(time_min, cutoff)
    for part in parts:
        print(f"state-scan {part['part']}", flush=True)
        parquet = pq.ParquetFile(dataset_dir / "parts" / part["part"])
        columns = [name for name in ("time_msc", "bid", "ask") if name in parquet.schema_arrow.names]
        for batch in parquet.iter_batches(batch_size=500_000, columns=columns):
            scan.add_batch(
                batch.column("bid").to_numpy(zero_copy_only=False),
                batch.column("ask").to_numpy(zero_copy_only=False),
                batch.column("time_msc").to_numpy(zero_copy_only=False),
            )
    measured = scan.finish()
    identity_ok = not (
        manifest.get("dataset_sha256") == PUBLISHED_DIGEST and (scan.rows != PUBLISHED_ROWS or cutoff != PUBLISHED_CUTOFF)
    )
    verdicts = apply_verdicts(measured) if identity_ok else {
        key: _verdict(
            key,
            status="INCONCLUSIVE",
            reason="archive identity did not match the verified inventory",
            raw_p=1.0,
            holm_p=1.0,
            effect=None,
            n_value=0,
            horizon_1024="undefined",
        )
        for key in FAMILY
    }
    rows = scan.summaries()
    return {
        "schema": SCHEMA,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "dataset": {
            "release": "dataset-xauusd-730d-20260919",
            "asset": "XAUUSD_730d_20260919T114013Z.zip",
            "expected_zip_sha256": "975b68637be3597aeccd9055c09b98a398cf799fc04a1530164ae6acf108f723",
            "manifest_dataset_sha256": manifest.get("dataset_sha256"),
            "timestamp_interpretation_confirmed": manifest.get("timestamp_interpretation_confirmed") is True,
        },
        "code_identity": {
            "git_sha": os.environ.get("GITHUB_SHA", "UNAVAILABLE"),
            "execution_host": os.environ.get("QTS_DISCOVERY_EXECUTION_HOST", "UNAVAILABLE"),
            "module": "qts.research.xauusd_state_scan",
        },
        "timestamp_basis": timestamp_basis_assessment(manifest),
        "window": {
            "time_msc_min": time_min,
            "time_msc_max": time_max,
            "cutoff_time_msc": cutoff,
            "rule": "discovery: time_msc < cutoff; a window touching the locked span is excluded",
            "discovery_rows": scan.discovery_rows,
            "validation_rows_not_used": scan.validation_rows,
        },
        "research_assumptions": [
            "states are functions of quotes at or before the event, never of the future move",
            "active is a positive gap of at most 100 ms; exactly 100 ms is active; normal is above 100 ms through 500 ms",
            "same-millisecond and non-positive gaps are neither active, normal, nor quiet",
            "the 22-cent occupancy mode is the exact 22-cent spread; 37-41 cents is descriptive only",
            "inferential identity is the global row modulo horizon+1, not the batch index",
            "validation mids are not used; no held-out distribution is computed",
            "a negative spread is counted and is not used as a state; the row is not repaired",
            "one-quote delay enters at the next quote and charges that quote's spread plus one cent",
            "a listed panel cell is a hypothesis generator and is not confirmed on this sample",
        ],
        "horizons": list(scan.horizons),
        "identity_ok": identity_ok,
        "rows": scan.rows,
        "nonmonotonic": scan.nonmonotonic,
        "negative_spread_rows": scan.negative_spread_rows,
        "panel": rows,
        "hypothesis_generators": rank_exploratory(rows),
        "measured": _jsonable(measured),
        "hypotheses": verdicts,
        "prior_hypotheses_not_reopened": {
            "H-MS-01": "REJECTED",
            "H-MS-02": "REJECTED",
            "H-QD-01": "REJECTED",
            "H-QD-02": "REJECTED",
            "H-INT-01": "REJECTED",
            "H-MV-01": "REJECTED",
            "H-VOL-01": "REJECTED",
            "H-SPR-01": "REJECTED",
            "H-SP-01": "TESTED",
            "H-TOD-01": "BLOCKED",
        },
        "held_out_span_opened": False,
        "edge_claim": "NOT ESTABLISHED",
        "strategy_promoted": False,
        "decision": "INCONCLUSIVE",
        "safety": {"confirm_live": False, "orders_submitted": 0, "DEMO_EXECUTION": "DISABLED"},
        "repairs_applied": [],
    }


def _read_manifest(dataset_dir: Path) -> dict[str, Any]:
    import json

    return json.loads((dataset_dir / MANIFEST_FILENAME).read_text(encoding="utf-8"))


def _stamp_range(dataset_dir: Path, parts: list[dict[str, Any]]) -> tuple[int, int]:
    time_min = None
    time_max = None
    for part in parts:
        path = dataset_dir / "parts" / part["part"]
        if not path.exists():
            raise FileNotFoundError(part["part"])
        parquet = pq.ParquetFile(path)
        for batch in parquet.iter_batches(batch_size=500_000, columns=["time_msc"]):
            stamp = np.asarray(batch.column("time_msc").to_numpy(zero_copy_only=False), dtype=np.int64)
            if stamp.size == 0:
                continue
            lo, hi = int(stamp.min()), int(stamp.max())
            time_min = lo if time_min is None else min(time_min, lo)
            time_max = hi if time_max is None else max(time_max, hi)
    if time_min is None or time_max is None:
        raise ValueError("no time_msc values")
    return time_min, time_max


def render_state_report(report: dict[str, Any]) -> str:
    lines = [
        "# XAUUSD state-conditional research state",
        "",
        f"Decision: {report.get('decision')}",
        "",
        "No strategy was promoted. Exploratory cells are hypothesis generators, not tests. The locked span was not opened.",
        "",
        f"Clock: {(report.get('timestamp_basis') or {}).get('status')}",
        "",
        "## HYPOTHESES",
        "",
    ]
    for key in FAMILY:
        verdict = (report.get("hypotheses") or {}).get(key) or {}
        lines.append(f"- {key}: {verdict.get('status')} — {verdict.get('reason')}")
    lines.extend(["", "## HYPOTHESIS GENERATORS", ""])
    generators = report.get("hypothesis_generators") or []
    if not generators:
        lines.append("- None cleared the pre-declared reporting floors.")
    for item in generators:
        lines.append(f"- {item['state']} at {item['horizon_quotes']} quotes: {item['status']} — {item['reason']}")
    lines.extend(
        [
            "",
            "Edge claim: NOT ESTABLISHED",
            "Orders submitted: 0",
            "Held-out span opened: false",
            "",
        ]
    )
    return "\n".join(lines)


def write_report(report: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
