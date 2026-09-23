"""Preregistered volatility-state measurement.

See ``docs/xauusd_volatility_preregistration.md``. This stresses the known
high-versus-low magnitude contrast and measures two new splits. It does not
retest H-ST-02 and does not construct a directional signal.
"""

from __future__ import annotations

import json
import math
import os
from collections.abc import Mapping
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

SCHEMA = "qts.xauusd_volatility.v1"
PRIMARY_H = 256
STABILITY_H = 1024
HORIZONS: tuple[int, ...] = (16, 64, 256, 1024, 4096)
PASSAGE_CAP = 4096
CARRY = PASSAGE_CAP + 32
MIN_N = 1000
ALPHA = 0.01
LOW_VOL = 0.10
HIGH_VOL = 0.20
EXTREME_VOL = 0.40
BURST_VOL = 0.10
MATERIAL_DOLLARS = 0.22
ADJACENT_DOLLARS = 0.10
DEGRADED_LIFT = 0.05
DELAY_LIFT = 0.02
TIME_RATIO_MAX = 0.80
RESOLVED_FRACTION = 0.50
RATIO_FLOOR = 1.25
ADJACENT_RATIO = 1.15
DELAY_RATIO = 1.10
HIST_LIMIT_HALF = 40_000
GENERATOR_N = 1000
GENERATOR_SIGNED = 0.25
GENERATOR_RATIO = 1.25
GENERATOR_LIFT = 0.05
PUBLISHED_ROWS = 139_930_971
PUBLISHED_CUTOFF = 1_764_563_969_254
PUBLISHED_DIGEST = "26aee827802066266fc5ef2f4ef30f874b0a7139666caf46f3bcfbec840e3789"
EXPECTED_ZIP_SHA256 = "975b68637be3597aeccd9055c09b98a398cf799fc04a1530164ae6acf108f723"
STATES: tuple[str, ...] = (
    "unconditional",
    "vol_low",
    "vol_normal",
    "vol_high",
    "vol_extreme",
    "vol_high_not_extreme",
    "quiet_to_expansion",
    "stay_quiet",
    "contraction_onset",
    "persistent_high",
    "repeated_burst",
)
FAMILY: tuple[dict[str, Any], ...] = (
    {
        "hypothesis_id": "H-VL-01",
        "kind": "economic",
        "group_a": "vol_high",
        "group_b": "vol_low",
        "ratio_floor": RATIO_FLOOR,
        "dollar_floor": MATERIAL_DOLLARS,
        "degraded_lift": DEGRADED_LIFT,
        "delay_lift": DELAY_LIFT,
        "time_ratio_max": TIME_RATIO_MAX,
        "positive_claim": "cost-qualified magnitude difference, not a strategy",
    },
    {
        "hypothesis_id": "H-VL-02",
        "kind": "magnitude",
        "group_a": "vol_extreme",
        "group_b": "vol_high_not_extreme",
        "ratio_floor": ADJACENT_RATIO,
        "dollar_floor": ADJACENT_DOLLARS,
        "delay_ratio": DELAY_RATIO,
        "positive_claim": "extreme continues beyond ordinary high volatility, not a strategy",
    },
    {
        "hypothesis_id": "H-VL-03",
        "kind": "magnitude",
        "group_a": "quiet_to_expansion",
        "group_b": "stay_quiet",
        "ratio_floor": RATIO_FLOOR,
        "dollar_floor": MATERIAL_DOLLARS,
        "delay_ratio": DELAY_RATIO,
        "positive_claim": "quiet-to-expansion transition, not a strategy",
    },
    {
        "hypothesis_id": "H-VL-04",
        "kind": "magnitude",
        "group_a": "persistent_high",
        "group_b": "contraction_onset",
        "ratio_floor": ADJACENT_RATIO,
        "dollar_floor": ADJACENT_DOLLARS,
        "delay_ratio": DELAY_RATIO,
        "positive_claim": "persistence versus contraction onset, not a strategy",
    },
)
BIN_NAMES = ("low", "normal", "high_not_extreme", "extreme")


def run_ages(values: np.ndarray, seed_bin: int, seed_age: int) -> np.ndarray:
    """Age of the current bin. The seed is the run before the first value."""
    if values.size == 0:
        return np.empty(0, dtype=np.int64)
    change = np.empty(values.size, dtype=bool)
    change[0] = seed_age == 0 or int(values[0]) != int(seed_bin)
    if values.size > 1:
        change[1:] = values[1:] != values[:-1]
    idx = np.arange(values.size)
    starts = np.maximum.accumulate(np.where(change, idx, 0))
    ages = (idx - starts + 1).astype(np.int64)
    if (not bool(change[0])) and seed_age:
        nxt = np.flatnonzero(change)
        first_end = int(nxt[0]) if nxt.size else int(values.size)
        ages[:first_end] += int(seed_age)
    return ages


def hist_quantile(hist: np.ndarray, q: float) -> float | None:
    """Signed price quantile from a centered half-cent histogram."""
    total = int(hist.sum())
    if total <= 0:
        return None
    target = q * (total - 1)
    pos = int(np.searchsorted(np.cumsum(hist), target, side="left"))
    pos = min(pos, hist.size - 1)
    return float(pos - HIST_LIMIT_HALF) * 0.005


def time_median(counts: np.ndarray) -> float | None:
    """Sample median of a hit-time histogram. Index is the event count."""
    total = int(counts.sum())
    if total <= 0:
        return None
    cdf = np.cumsum(counts)

    def at(rank: int) -> int:
        return int(np.searchsorted(cdf, rank, side="right"))

    return 0.5 * (at((total - 1) // 2) + at(total // 2))


def quote_states(mid_half: np.ndarray, spread: np.ndarray, locked: np.ndarray) -> dict[str, np.ndarray]:
    """Backward-looking volatility states. None of these reads a future price."""
    n = int(mid_half.shape[0])
    locked_cum = np.cumsum(locked.astype(np.int32))
    vol = np.full(n, np.nan)
    vol4 = np.full(n, np.nan)
    prior = np.full(n, np.nan)
    if n > 16:
        valid = (~locked[16:]) & (~locked[:-16]) & (locked_cum[16:] == locked_cum[:-16])
        vol[16:] = np.where(valid, np.abs(mid_half[16:] - mid_half[:-16]) * 0.005, np.nan)
    if n > 4:
        valid4 = (~locked[4:]) & (~locked[:-4]) & (locked_cum[4:] == locked_cum[:-4])
        vol4[4:] = np.where(valid4, np.abs(mid_half[4:] - mid_half[:-4]) * 0.005, np.nan)
    if n > 20:
        valid_prior = (~locked[16:-4]) & (~locked[:-20]) & (locked_cum[16:-4] == locked_cum[:-20])
        prior[20:] = np.where(valid_prior, np.abs(mid_half[16:-4] - mid_half[:-20]) * 0.005, np.nan)
    finite = np.isfinite(vol)
    bins = np.full(n, -1, dtype=np.int8)
    bins[finite & (vol <= LOW_VOL)] = 0
    bins[finite & (vol > LOW_VOL) & (vol < HIGH_VOL)] = 1
    bins[finite & (vol >= HIGH_VOL) & (vol < EXTREME_VOL)] = 2
    bins[finite & (vol >= EXTREME_VOL)] = 3
    quiet_prior = np.isfinite(prior) & (prior <= LOW_VOL)
    hot_prior = np.isfinite(prior) & (prior >= HIGH_VOL)
    burst = np.isfinite(vol4) & (vol4 >= BURST_VOL)
    quiet_now = np.isfinite(vol4) & (vol4 < BURST_VOL)
    contracting = np.isfinite(vol4) & (vol4 <= LOW_VOL)
    hot_now = np.isfinite(vol4) & (vol4 >= HIGH_VOL)
    onset = quiet_prior & burst
    onset_i = onset.astype(np.int32)
    recent = np.cumsum(onset_i)
    if n > 64:
        recent = recent.copy()
        recent[64:] = recent[64:] - np.cumsum(onset_i)[:-64]
    return {
        "bins": bins,
        "unconditional": ~locked & (spread >= 0),
        "vol_low": bins == 0,
        "vol_normal": bins == 1,
        "vol_high": (bins == 2) | (bins == 3),
        "vol_extreme": bins == 3,
        "vol_high_not_extreme": bins == 2,
        "quiet_to_expansion": onset & ~locked,
        "stay_quiet": quiet_prior & quiet_now & ~locked,
        "contraction_onset": hot_prior & contracting & ~locked,
        "persistent_high": hot_prior & hot_now & ~locked,
        "repeated_burst": onset & (recent >= 2) & ~locked,
    }


def _ratio(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    if right <= 0.0:
        if left > 0.0:
            return math.inf
        return None
    return left / right


def _mean(total: float, count: int) -> float | None:
    if count <= 0:
        return None
    return total / count


def _pool(values: list[float] | np.ndarray) -> float:
    return float(np.asarray(values, dtype=np.float64).sum())


def _mean_diff_p(sum_a: float, sumsq_a: float, n_a: int, sum_b: float, sumsq_b: float, n_b: int) -> float:
    if n_a < 2 or n_b < 2:
        return 1.0
    mean_a = sum_a / n_a
    mean_b = sum_b / n_b
    var_a = max((sumsq_a - sum_a * sum_a / n_a) / (n_a - 1), 0.0)
    var_b = max((sumsq_b - sum_b * sum_b / n_b) / (n_b - 1), 0.0)
    se = math.sqrt(var_a / n_a + var_b / n_b)
    if se == 0.0:
        return 0.0 if mean_a > mean_b else 1.0
    return float(norm.sf((mean_a - mean_b) / se))


def _proportion_p(hits_a: int, n_a: int, hits_b: int, n_b: int) -> float:
    if n_a <= 0 or n_b <= 0:
        return 1.0
    p1 = hits_a / n_a
    p2 = hits_b / n_b
    pooled = (hits_a + hits_b) / (n_a + n_b)
    se = math.sqrt(max(pooled * (1.0 - pooled), 0.0) * (1.0 / n_a + 1.0 / n_b))
    if se == 0.0:
        return 0.0 if p1 > p2 else 1.0
    return float(norm.sf((p1 - p2) / se))


class VolatilityScan:
    """One forward pass. The locked span is excluded, not aggregated."""

    def __init__(
        self,
        time_min: int,
        cutoff: int,
        *,
        horizons: tuple[int, ...] = HORIZONS,
        primary: int = PRIMARY_H,
        stability: int = STABILITY_H,
        passage_cap: int = PASSAGE_CAP,
        carry: int | None = None,
    ) -> None:
        if cutoff <= time_min:
            raise ValueError("cutoff must be after time_min")
        self.time_min = int(time_min)
        self.cutoff = int(cutoff)
        self.span = self.cutoff - self.time_min
        self.horizons = tuple(horizons)
        self.primary = int(primary)
        self.stability = int(stability)
        self.passage_cap = int(passage_cap)
        self.carry = int(CARRY if carry is None else carry)
        if self.carry < 64:
            raise ValueError("carry must cover the 64-quote repeated-burst count")
        if self.carry < self.passage_cap + 2:
            raise ValueError("carry must cover a delayed passage path")
        self.rows = 0
        self.discovery_rows = 0
        self.validation_rows = 0
        self.nonmonotonic = 0
        self.negative_spread_rows = 0
        self.carry_n = 0
        self.carry_bid = np.empty(0, dtype=np.int32)
        self.carry_ask = np.empty(0, dtype=np.int32)
        self.carry_stamp = np.empty(0, dtype=np.int64)
        self.seed_bin = 0
        self.seed_age = 0
        n_s = len(STATES)
        n_h = len(self.horizons)
        width = HIST_LIMIT_HALF * 2 + 1
        self.state_index = {name: pos for pos, name in enumerate(STATES)}
        self.n = np.zeros((n_s, n_h), dtype=np.int64)
        self.signed_sum = np.zeros((n_s, n_h), dtype=np.float64)
        self.abs_sum = np.zeros((n_s, n_h), dtype=np.float64)
        self.spread_sum = np.zeros((n_s, n_h), dtype=np.float64)
        self.up_n = np.zeros((n_s, n_h), dtype=np.int64)
        self.down_n = np.zeros((n_s, n_h), dtype=np.int64)
        self.up_sum = np.zeros((n_s, n_h), dtype=np.float64)
        self.down_sum = np.zeros((n_s, n_h), dtype=np.float64)
        self.exceed = np.zeros((n_s, n_h), dtype=np.int64)
        self.plus1 = np.zeros((n_s, n_h), dtype=np.int64)
        self.plus2 = np.zeros((n_s, n_h), dtype=np.int64)
        self.fixed = np.zeros((n_s, n_h, 3), dtype=np.int64)
        self.overflow = np.zeros((n_s, n_h), dtype=np.int64)
        self.hist = np.zeros((n_s, n_h, width), dtype=np.int64)
        self.t_n = np.zeros((n_s, 3), dtype=np.int64)
        self.t_abs = np.zeros((n_s, 3), dtype=np.float64)
        self.t_sq = np.zeros((n_s, 3), dtype=np.float64)
        self.t_plus2 = np.zeros((n_s, 3), dtype=np.int64)
        self.d_n = np.zeros((n_s, 3), dtype=np.int64)
        self.d_abs = np.zeros((n_s, 3), dtype=np.float64)
        self.d_plus2 = np.zeros((n_s, 3), dtype=np.int64)
        self.longer_n = np.zeros(n_s, dtype=np.int64)
        self.longer_abs = np.zeros(n_s, dtype=np.float64)
        self.hit_hist = np.zeros((n_s, self.passage_cap + 1), dtype=np.int64)
        self.hit_hist_2 = np.zeros((n_s, self.passage_cap + 1), dtype=np.int64)
        self.delay_hit_hist = np.zeros((n_s, self.passage_cap + 1), dtype=np.int64)
        self.delay_hit_hist_2 = np.zeros((n_s, self.passage_cap + 1), dtype=np.int64)
        self.hit_resolved = np.zeros(n_s, dtype=np.int64)
        self.hit_censored = np.zeros(n_s, dtype=np.int64)
        self.hit_resolved_2 = np.zeros(n_s, dtype=np.int64)
        self.hit_censored_2 = np.zeros(n_s, dtype=np.int64)
        self.delay_resolved = np.zeros(n_s, dtype=np.int64)
        self.delay_censored = np.zeros(n_s, dtype=np.int64)
        self.delay_resolved_2 = np.zeros(n_s, dtype=np.int64)
        self.delay_censored_2 = np.zeros(n_s, dtype=np.int64)
        self.persistence_hist = np.zeros(129, dtype=np.int64)
        self.transition = np.zeros((4, 4), dtype=np.int64)
        self.expansion = np.zeros(4, dtype=np.int64)
        self.expansion_n = np.zeros(4, dtype=np.int64)

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
            self._count_backward(features, carry_n)
            self._consume(features, carry_n, global_base)
            self._commit_persistence(features, carry_n, global_base)
        tail = min(self.carry, series_n)
        self.carry_bid = bid_c[-tail:].copy()
        self.carry_ask = ask_c[-tail:].copy()
        self.carry_stamp = stamp_a[-tail:].copy()
        self.carry_n = tail

    def _features(self, bid_c: np.ndarray, ask_c: np.ndarray, stamp_a: np.ndarray) -> dict[str, Any]:
        spread = ask_c.astype(np.int64) - bid_c.astype(np.int64)
        locked = stamp_a >= self.cutoff
        mid = bid_c.astype(np.int64) + ask_c.astype(np.int64)
        states = quote_states(mid, spread, locked)
        return {
            "spread": spread,
            "locked": locked,
            "locked_cum": np.cumsum(locked.astype(np.int32)),
            "mid": mid,
            "stamp": stamp_a,
            "bins": states.pop("bins"),
            "masks": states,
        }

    def _count_backward(self, features: dict[str, Any], carry_n: int) -> None:
        stamp = features["stamp"]
        series_n = int(stamp.shape[0])
        gap = np.diff(stamp)
        new_gap = np.zeros(gap.shape[0], dtype=bool)
        if carry_n < series_n:
            new_gap[max(carry_n - 1, 0) :] = True
        self.nonmonotonic += int(np.count_nonzero((gap < 0) & new_gap & (stamp[1:] < self.cutoff)))

    def _consume(self, features: dict[str, Any], carry_n: int, global_base: int) -> None:
        for h_index, horizon in enumerate(self.horizons):
            self._horizon(h_index, horizon, features, carry_n, global_base, extra=0, role="panel")
        if self.primary in self.horizons:
            self._horizon(0, self.primary, features, carry_n, global_base, extra=1, role="delay")
        self._transitions(features, carry_n, global_base)
        self._passage(features, carry_n, global_base)

    def _horizon(
        self,
        h_index: int,
        horizon: int,
        features: dict[str, Any],
        carry_n: int,
        global_base: int,
        *,
        extra: int,
        role: str,
    ) -> None:
        selected = self._select(horizon, extra, features, carry_n, global_base)
        if selected is None:
            return
        if role == "delay":
            self._record_delay(selected, features)
            return
        self._record_panel(h_index, selected, features, primary=horizon == self.primary)
        if horizon == self.stability:
            self._record_longer(selected, features)

    def _select(
        self,
        horizon: int,
        extra: int,
        features: dict[str, Any],
        carry_n: int,
        global_base: int,
    ) -> dict[str, np.ndarray] | None:
        series_n = int(features["stamp"].shape[0])
        start = max(carry_n, horizon + 1 + extra)
        if start >= series_n:
            return None
        end = np.arange(start, series_n, dtype=np.int64)
        i = end - horizon - extra
        origin = i + extra
        locked = features["locked"]
        locked_cum = features["locked_cum"]
        stamp = features["stamp"]
        spread = features["spread"]
        usable = (
            (i >= 1)
            & ~locked[i]
            & ~locked[origin]
            & ~locked[end]
            & (locked_cum[end] <= locked_cum[i])
            & (spread[i] >= 0)
            & (stamp[i] < self.cutoff)
            & (stamp[origin] < self.cutoff)
            & (stamp[end] < self.cutoff)
            & (stamp[i - 1] < self.cutoff)
            & (((global_base + i) % (horizon + 1)) == 0)
        )
        if not np.any(usable):
            return None
        chosen = np.flatnonzero(usable)
        i = i[chosen]
        origin = origin[chosen]
        end = end[chosen]
        dmid = features["mid"][end] - features["mid"][origin]
        return {
            "i": i,
            "origin": origin,
            "move": dmid * 0.005,
            "dmid": dmid,
            "spread_i": spread[i],
            "spread_origin": spread[origin],
            "stamp": stamp[i],
        }

    def _tercile(self, stamp: np.ndarray) -> np.ndarray:
        return np.clip(((stamp - self.time_min) * 3) // self.span, 0, 2).astype(np.int64)

    def _record_panel(self, h_index: int, selected: Mapping[str, np.ndarray], features: dict[str, Any], *, primary: bool) -> None:
        i = selected["i"]
        move = selected["move"]
        dmid = selected["dmid"]
        spread_i = selected["spread_i"]
        tercile = self._tercile(selected["stamp"]) if primary else None
        for pos, name in enumerate(STATES):
            take = features["masks"][name][i]
            if not np.any(take):
                continue
            self._add_cell(
                pos,
                h_index,
                move[take],
                dmid[take],
                spread_i[take],
                None if tercile is None else tercile[take],
                primary=primary,
            )

    def _add_cell(
        self,
        pos: int,
        h_index: int,
        move: np.ndarray,
        dmid: np.ndarray,
        spread_cents: np.ndarray,
        tercile: np.ndarray | None,
        *,
        primary: bool,
    ) -> None:
        half = dmid.astype(np.int64)
        bins = np.clip(half, -HIST_LIMIT_HALF, HIST_LIMIT_HALF) + HIST_LIMIT_HALF
        self.overflow[pos, h_index] += int(np.count_nonzero((half < -HIST_LIMIT_HALF) | (half > HIST_LIMIT_HALF)))
        np.add.at(self.hist[pos, h_index], bins, 1)
        self.n[pos, h_index] += int(move.size)
        self.signed_sum[pos, h_index] += float(move.sum())
        absolute = np.abs(move)
        self.abs_sum[pos, h_index] += float(absolute.sum())
        self.spread_sum[pos, h_index] += float(spread_cents.sum() * 0.01)
        up = move > 0
        down = move < 0
        self.up_n[pos, h_index] += int(np.count_nonzero(up))
        self.down_n[pos, h_index] += int(np.count_nonzero(down))
        if np.any(up):
            self.up_sum[pos, h_index] += float(move[up].sum())
        if np.any(down):
            self.down_sum[pos, h_index] += float(move[down].sum())
        width = np.abs(half)
        self.exceed[pos, h_index] += int(np.count_nonzero(width > spread_cents * 2))
        self.plus1[pos, h_index] += int(np.count_nonzero(width > spread_cents * 2 + 2))
        plus2 = width > spread_cents * 2 + 4
        self.plus2[pos, h_index] += int(np.count_nonzero(plus2))
        self.fixed[pos, h_index, 0] += int(np.count_nonzero(absolute > 0.20))
        self.fixed[pos, h_index, 1] += int(np.count_nonzero(absolute > 0.50))
        self.fixed[pos, h_index, 2] += int(np.count_nonzero(absolute > 1.00))
        if primary and tercile is not None:
            np.add.at(self.t_n[pos], tercile, 1)
            np.add.at(self.t_abs[pos], tercile, absolute)
            np.add.at(self.t_sq[pos], tercile, absolute * absolute)
            np.add.at(self.t_plus2[pos], tercile, plus2.astype(np.int64))

    def _record_delay(self, selected: Mapping[str, np.ndarray], features: dict[str, Any]) -> None:
        keep = selected["spread_origin"] >= 0
        if not np.any(keep):
            return
        i = selected["i"][keep]
        move = selected["move"][keep]
        dmid = selected["dmid"][keep]
        spread_origin = selected["spread_origin"][keep]
        tercile = self._tercile(selected["stamp"][keep])
        width = np.abs(dmid.astype(np.int64))
        plus2 = width > spread_origin * 2 + 4
        absolute = np.abs(move)
        for pos, name in enumerate(STATES):
            take = features["masks"][name][i]
            if not np.any(take):
                continue
            np.add.at(self.d_n[pos], tercile[take], 1)
            np.add.at(self.d_abs[pos], tercile[take], absolute[take])
            np.add.at(self.d_plus2[pos], tercile[take], plus2[take].astype(np.int64))

    def _record_longer(self, selected: Mapping[str, np.ndarray], features: dict[str, Any]) -> None:
        i = selected["i"]
        absolute = np.abs(selected["move"])
        for pos, name in enumerate(STATES):
            take = features["masks"][name][i]
            count = int(np.count_nonzero(take))
            if count == 0:
                continue
            self.longer_n[pos] += count
            self.longer_abs[pos] += float(absolute[take].sum())

    def _transitions(self, features: dict[str, Any], carry_n: int, global_base: int) -> None:
        n = int(features["mid"].shape[0])
        if n <= 32:
            return
        i = np.arange(20, n - 16, dtype=np.int64)
        i = i[((global_base + i) % 17 == 0) & ((i + 16) >= carry_n)]
        if i.size == 0:
            return
        bins = features["bins"]
        locked = features["locked"]
        locked_cum = features["locked_cum"]
        current = bins[i]
        nxt = bins[i + 16]
        clean = (
            (current >= 0)
            & (nxt >= 0)
            & ~locked[i]
            & ~locked[i + 16]
            & ~locked[i - 16]
            & (locked_cum[i + 16] == locked_cum[i - 16])
        )
        if not np.any(clean):
            return
        i = i[clean]
        current = current[clean].astype(np.int64)
        nxt = nxt[clean].astype(np.int64)
        np.add.at(self.transition, (current, nxt), 1)
        mid = features["mid"]
        expanded = np.abs(mid[i + 16] - mid[i]) > np.abs(mid[i] - mid[i - 16])
        np.add.at(self.expansion_n, current, 1)
        np.add.at(self.expansion, current, expanded.astype(np.int64))

    def _commit_persistence(self, features: dict[str, Any], carry_n: int, global_base: int) -> None:
        n = int(features["bins"].shape[0])
        local = np.arange(n)
        grid = np.flatnonzero(((global_base + local) % 17) == 0)
        grid = grid[grid >= carry_n]
        if grid.size == 0:
            return
        values = features["bins"][grid]
        ages = run_ages(values, self.seed_bin, self.seed_age)
        defined = values >= 0
        if np.any(defined):
            np.add.at(self.persistence_hist, np.minimum(ages[defined], 128), 1)
        self.seed_bin = int(values[-1])
        self.seed_age = int(ages[-1])

    def _passage(self, features: dict[str, Any], carry_n: int, global_base: int) -> None:
        step = self.primary + 1
        self._passage_side(features, carry_n, global_base, step, delayed=False)
        self._passage_side(features, carry_n, global_base, step, delayed=True)

    def _passage_side(
        self,
        features: dict[str, Any],
        carry_n: int,
        global_base: int,
        step: int,
        *,
        delayed: bool,
    ) -> None:
        n = int(features["mid"].shape[0])
        extra = 1 if delayed else 0
        start = max(carry_n, self.passage_cap + extra)
        if start >= n:
            return
        path_end = np.arange(start, n, dtype=np.int64)
        i = path_end - self.passage_cap - extra
        origin = i + extra
        locked = features["locked"]
        spread = features["spread"]
        stamp = features["stamp"]
        usable = (
            (i >= 1)
            & (((global_base + i) % step) == 0)
            & ~locked[i]
            & ~locked[origin]
            & (spread[i] >= 0)
            & (spread[origin] >= 0)
            & (stamp[i] < self.cutoff)
            & (stamp[origin] < self.cutoff)
            & (stamp[i - 1] < self.cutoff)
        )
        chosen = np.flatnonzero(usable)
        if chosen.size == 0:
            return
        i = i[chosen]
        origin = origin[chosen]
        resolved1, first1, resolved2, first2 = self._hits(features["mid"], locked, origin, spread[origin])
        for pos, name in enumerate(STATES):
            take = features["masks"][name][i]
            if not np.any(take):
                continue
            self._record_hits(pos, take, resolved1, first1, delayed, degraded=False)
            self._record_hits(pos, take, resolved2, first2, delayed, degraded=True)

    def _hits(
        self,
        mid: np.ndarray,
        locked: np.ndarray,
        base_i: np.ndarray,
        spread_cents: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        cap = self.passage_cap
        offsets = np.arange(1, cap + 1, dtype=np.int64)
        resolved1 = np.zeros(base_i.size, dtype=bool)
        resolved2 = np.zeros(base_i.size, dtype=bool)
        first1 = np.ones(base_i.size, dtype=np.int64)
        first2 = np.ones(base_i.size, dtype=np.int64)
        for start in range(0, int(base_i.size), 512):
            sl = slice(start, start + 512)
            base_index = base_i[sl]
            path_index = base_index[:, None] + offsets[None, :]
            locked_path = locked[path_index]
            base = mid[base_index]
            path = np.where(locked_path, base[:, None], mid[path_index])
            valid = np.cumsum(locked_path, axis=1) == 0
            diff = np.abs(path - base[:, None])
            threshold = spread_cents[sl].astype(np.int64)
            hit1 = (diff > (threshold * 2 + 2)[:, None]) & valid
            hit2 = (diff > (threshold * 2 + 4)[:, None]) & valid
            resolved1[sl] = hit1.any(axis=1)
            resolved2[sl] = hit2.any(axis=1)
            first1[sl] = np.argmax(hit1, axis=1) + 1
            first2[sl] = np.argmax(hit2, axis=1) + 1
        return resolved1, first1, resolved2, first2

    def _record_hits(
        self,
        pos: int,
        take: np.ndarray,
        resolved: np.ndarray,
        first: np.ndarray,
        delayed: bool,
        *,
        degraded: bool,
    ) -> None:
        got = take & resolved
        missed = int(np.count_nonzero(take & ~resolved))
        hits = int(np.count_nonzero(got))
        if delayed and degraded:
            hist, resolved_n, censored_n = self.delay_hit_hist_2, self.delay_resolved_2, self.delay_censored_2
        elif delayed:
            hist, resolved_n, censored_n = self.delay_hit_hist, self.delay_resolved, self.delay_censored
        elif degraded:
            hist, resolved_n, censored_n = self.hit_hist_2, self.hit_resolved_2, self.hit_censored_2
        else:
            hist, resolved_n, censored_n = self.hit_hist, self.hit_resolved, self.hit_censored
        if hits:
            np.add.at(hist[pos], first[got], 1)
        resolved_n[pos] += hits
        censored_n[pos] += missed

    def finish(self) -> dict[str, Any]:
        panel = {}
        rows = []
        for h_index, horizon in enumerate(self.horizons):
            panel[str(horizon)] = {}
            for pos, name in enumerate(STATES):
                cell = self._cell(pos, h_index, horizon)
                panel[str(horizon)][name] = cell
                rows.append(cell)
        passage = {}
        for pos, name in enumerate(STATES):
            resolved = int(self.hit_resolved[pos])
            censored = int(self.hit_censored[pos])
            total = resolved + censored
            dresolved = int(self.delay_resolved[pos])
            dcensored = int(self.delay_censored[pos])
            dtotal = dresolved + dcensored
            passage[name] = {
                "resolved": resolved,
                "censored": censored,
                "resolved_fraction": None if total == 0 else resolved / total,
                "median_quotes_spread_plus_0_01": time_median(self.hit_hist[pos]),
                "median_quotes_spread_plus_0_02": time_median(self.hit_hist_2[pos]),
                "delay_resolved": dresolved,
                "delay_censored": dcensored,
                "delay_resolved_fraction": None if dtotal == 0 else dresolved / dtotal,
                "delay_median_quotes_spread_plus_0_01": time_median(self.delay_hit_hist[pos]),
                "delay_median_quotes_spread_plus_0_02": time_median(self.delay_hit_hist_2[pos]),
            }
        measured = self._measured()
        return {
            "schema": SCHEMA,
            "decision": "INCONCLUSIVE",
            "decision_note": (
                "A TESTED volatility hypothesis is not an edge, not a strategy, "
                "and not a reason to open the held-out span."
            ),
            "edge_claim": "NOT ESTABLISHED",
            "strategy_promoted": False,
            "held_out_span_opened": False,
            "rows": self.rows,
            "discovery_rows": self.discovery_rows,
            "validation_rows_not_used": self.validation_rows,
            "nonmonotonic": self.nonmonotonic,
            "negative_spread_rows": self.negative_spread_rows,
            "panel": panel,
            "hypothesis_generators": rank_exploratory(rows),
            "persistence_blocks": {
                "counts_capped_at_128": [int(x) for x in self.persistence_hist],
                "note": "Descriptive age of the current bin on the global step-17 grid. Not a hypothesis.",
            },
            "transition_counts": {
                "from": list(BIN_NAMES),
                "to": list(BIN_NAMES),
                "counts": [[int(x) for x in row] for row in self.transition],
                "p_next_window_larger_than_current": [
                    None if int(self.expansion_n[i]) == 0 else int(self.expansion[i]) / int(self.expansion_n[i])
                    for i in range(4)
                ],
                "note": (
                    "Descriptive. A very small window is mechanically easier to exceed than a very large one. "
                    "This is not a confirmatory test."
                ),
            },
            "passage": passage,
            "measured": _jsonable(measured),
            "hypotheses": apply_verdicts(measured),
            "ranking_rule": (
                "Panel cells are NOT TESTED generators. A signed score is not a directional signal. "
                "Nothing in this phase opens the held-out span."
            ),
            "session_clock": "BLOCKED",
            "safety": {"confirm_live": False, "orders_submitted": 0, "DEMO_EXECUTION": "DISABLED"},
            "repairs_applied": [],
        }

    def _cell(self, pos: int, h_index: int, horizon: int) -> dict[str, Any]:
        n = int(self.n[pos, h_index])
        up_n = int(self.up_n[pos, h_index])
        down_n = int(self.down_n[pos, h_index])
        hist = self.hist[pos, h_index]
        return {
            "state": STATES[pos],
            "horizon_quotes": int(horizon),
            "n": n,
            "mean_abs": _mean(float(self.abs_sum[pos, h_index]), n),
            "mean_signed": _mean(float(self.signed_sum[pos, h_index]), n),
            "mean_spread": _mean(float(self.spread_sum[pos, h_index]), n),
            "p_up": _mean(float(up_n), n),
            "p_down": _mean(float(down_n), n),
            "mean_up": _mean(float(self.up_sum[pos, h_index]), up_n),
            "mean_down": _mean(float(self.down_sum[pos, h_index]), down_n),
            "p_exceed_spread": _mean(float(self.exceed[pos, h_index]), n),
            "p_exceed_spread_plus_0_01": _mean(float(self.plus1[pos, h_index]), n),
            "p_exceed_spread_plus_0_02": _mean(float(self.plus2[pos, h_index]), n),
            "p_abs_gt_0_20": _mean(float(self.fixed[pos, h_index, 0]), n),
            "p_abs_gt_0_50": _mean(float(self.fixed[pos, h_index, 1]), n),
            "p_abs_gt_1_00": _mean(float(self.fixed[pos, h_index, 2]), n),
            "p05": hist_quantile(hist, 0.05),
            "p10": hist_quantile(hist, 0.10),
            "p50": hist_quantile(hist, 0.50),
            "p90": hist_quantile(hist, 0.90),
            "p95": hist_quantile(hist, 0.95),
            "histogram_overflow": int(self.overflow[pos, h_index]),
        }

    def _measured(self) -> dict[str, Any]:
        tests = {}
        for spec in FAMILY:
            a = self.state_index[spec["group_a"]]
            b = self.state_index[spec["group_b"]]
            item = {
                "a_n": [int(x) for x in self.t_n[a]],
                "a_sum": [float(x) for x in self.t_abs[a]],
                "a_sumsq": [float(x) for x in self.t_sq[a]],
                "b_n": [int(x) for x in self.t_n[b]],
                "b_sum": [float(x) for x in self.t_abs[b]],
                "b_sumsq": [float(x) for x in self.t_sq[b]],
                "delay_a_n": [int(x) for x in self.d_n[a]],
                "delay_a_sum": [float(x) for x in self.d_abs[a]],
                "delay_b_n": [int(x) for x in self.d_n[b]],
                "delay_b_sum": [float(x) for x in self.d_abs[b]],
                "longer_a_n": int(self.longer_n[a]),
                "longer_a_sum": float(self.longer_abs[a]),
                "longer_b_n": int(self.longer_n[b]),
                "longer_b_sum": float(self.longer_abs[b]),
            }
            if spec["kind"] == "economic":
                item.update(
                    {
                        "a_degraded": [int(x) for x in self.t_plus2[a]],
                        "b_degraded": [int(x) for x in self.t_plus2[b]],
                        "delay_a_degraded": [int(x) for x in self.d_plus2[a]],
                        "delay_b_degraded": [int(x) for x in self.d_plus2[b]],
                        "a_resolved": int(self.hit_resolved[a]),
                        "a_censored": int(self.hit_censored[a]),
                        "a_median": time_median(self.hit_hist[a]),
                        "b_resolved": int(self.hit_resolved[b]),
                        "b_censored": int(self.hit_censored[b]),
                        "b_median": time_median(self.hit_hist[b]),
                        "delay_a_resolved": int(self.delay_resolved[a]),
                        "delay_a_censored": int(self.delay_censored[a]),
                        "delay_a_median": time_median(self.delay_hit_hist[a]),
                        "delay_b_resolved": int(self.delay_resolved[b]),
                        "delay_b_censored": int(self.delay_censored[b]),
                        "delay_b_median": time_median(self.delay_hit_hist[b]),
                    }
                )
            tests[spec["hypothesis_id"]] = item
        return {"nonmonotonic": self.nonmonotonic, "tests": tests}


def _resolved_fraction(resolved: int, censored: int) -> float | None:
    total = resolved + censored
    if total == 0:
        return None
    return resolved / total


def _tercile_status(item: Mapping[str, Any], *, economic: bool) -> str:
    for t in range(3):
        if int(item["a_n"][t]) < MIN_N or int(item["b_n"][t]) < MIN_N:
            return "underpowered"
        if item["a_sum"][t] / item["a_n"][t] <= item["b_sum"][t] / item["b_n"][t]:
            return "disagrees"
        if economic and item["a_degraded"][t] / item["a_n"][t] <= item["b_degraded"][t] / item["b_n"][t]:
            return "disagrees"
    return "agrees"


def _longer_status(item: Mapping[str, Any]) -> str:
    if int(item["longer_a_n"]) < MIN_N or int(item["longer_b_n"]) < MIN_N:
        return "underpowered"
    ratio = _ratio(_mean(item["longer_a_sum"], int(item["longer_a_n"])), _mean(item["longer_b_sum"], int(item["longer_b_n"])))
    if ratio is None or ratio <= 1.0:
        return "disagrees"
    return "agrees"


def _time_status(item: Mapping[str, Any], limit: float) -> tuple[str, str]:
    checks = (
        ("a_resolved", "a_censored", "a_median", "b_resolved", "b_censored", "b_median"),
        ("delay_a_resolved", "delay_a_censored", "delay_a_median", "delay_b_resolved", "delay_b_censored", "delay_b_median"),
    )
    for left_r, left_c, left_m, right_r, right_c, right_m in checks:
        left_frac = _resolved_fraction(int(item[left_r]), int(item[left_c]))
        right_frac = _resolved_fraction(int(item[right_r]), int(item[right_c]))
        if left_frac is None or right_frac is None or left_frac < RESOLVED_FRACTION or right_frac < RESOLVED_FRACTION:
            return "INCONCLUSIVE", "fewer than half of the waiting times resolved"
        ratio = _ratio(item[left_m], item[right_m])
        if ratio is None or ratio > limit:
            return "REJECTED", "the high state did not reach spread plus one cent materially sooner"
    return "pass", ""


def apply_verdicts(measured: Mapping[str, Any]) -> dict[str, Any]:
    """Apply the locked gates. A pass does not open the held-out span."""
    if int(measured.get("nonmonotonic") or 0):
        return {
            spec["hypothesis_id"]: _status(
                spec,
                "INCONCLUSIVE",
                "backward time_msc steps were measured",
                raw_p=1.0,
                holm_p=1.0,
            )
            for spec in FAMILY
        }
    prepared: list[dict[str, Any]] = []
    pvalues: list[float] = []
    for spec in FAMILY:
        item = measured["tests"][spec["hypothesis_id"]]
        a_n = int(_pool(item["a_n"]))
        b_n = int(_pool(item["b_n"]))
        a_mean = _mean(_pool(item["a_sum"]), a_n)
        b_mean = _mean(_pool(item["b_sum"]), b_n)
        ratio = _ratio(a_mean, b_mean)
        gap = None if a_mean is None or b_mean is None else a_mean - b_mean
        delay_n = min(int(_pool(item["delay_a_n"])), int(_pool(item["delay_b_n"])))
        delay_ratio = _ratio(
            _mean(_pool(item["delay_a_sum"]), int(_pool(item["delay_a_n"]))),
            _mean(_pool(item["delay_b_sum"]), int(_pool(item["delay_b_n"]))),
        )
        if spec["kind"] == "economic":
            a_hits = int(_pool(item["a_degraded"]))
            b_hits = int(_pool(item["b_degraded"]))
            lift = None if a_n == 0 or b_n == 0 else a_hits / a_n - b_hits / b_n
            d_hits_a = int(_pool(item["delay_a_degraded"]))
            d_hits_b = int(_pool(item["delay_b_degraded"]))
            d_n_a = int(_pool(item["delay_a_n"]))
            d_n_b = int(_pool(item["delay_b_n"]))
            delay_lift = None if d_n_a == 0 or d_n_b == 0 else d_hits_a / d_n_a - d_hits_b / d_n_b
            pvalue = _proportion_p(a_hits, a_n, b_hits, b_n)
            detail = {
                "degraded_lift": lift,
                "delay_degraded_lift": delay_lift,
                "waiting_ratio": _ratio(item.get("a_median"), item.get("b_median")),
                "delay_waiting_ratio": _ratio(item.get("delay_a_median"), item.get("delay_b_median")),
            }
        else:
            lift = None
            delay_lift = None
            pvalue = _mean_diff_p(
                _pool(item["a_sum"]),
                _pool(item["a_sumsq"]),
                a_n,
                _pool(item["b_sum"]),
                _pool(item["b_sumsq"]),
                b_n,
            )
            detail = {"delay_ratio": delay_ratio}
        pvalues.append(pvalue)
        prepared.append(
            {
                "spec": spec,
                "item": item,
                "a_n": a_n,
                "b_n": b_n,
                "a_mean": a_mean,
                "b_mean": b_mean,
                "ratio": ratio,
                "gap": gap,
                "delay_n": delay_n,
                "delay_ratio": delay_ratio,
                "lift": lift,
                "delay_lift": delay_lift,
                "detail": detail,
                "longer": _longer_status(item),
                "tercile": _tercile_status(item, economic=spec["kind"] == "economic"),
            }
        )
    adjusted = holm_bonferroni(pvalues)
    verdicts = {}
    for row, holm_p, raw_p in zip(prepared, adjusted, pvalues, strict=True):
        verdicts[row["spec"]["hypothesis_id"]] = _finish(row, float(holm_p), float(raw_p))
    return verdicts


def _finish(row: Mapping[str, Any], holm_p: float, raw_p: float) -> dict[str, Any]:
    spec = row["spec"]
    status, reason = _gate(row, holm_p)
    if status not in {"TESTED", "REJECTED", "INCONCLUSIVE"}:
        raise RuntimeError("volatility phase cannot promote a hypothesis")
    return _status(
        spec,
        status,
        reason,
        raw_p=raw_p,
        holm_p=holm_p,
        n_a=row["a_n"],
        n_b=row["b_n"],
        mean_a=row["a_mean"],
        mean_b=row["b_mean"],
        ratio=row["ratio"],
        dollar_gap=row["gap"],
        horizon_1024=row["longer"],
        **row["detail"],
    )


def _gate(row: Mapping[str, Any], holm_p: float) -> tuple[str, str]:
    spec = row["spec"]
    if row["a_n"] < MIN_N or row["b_n"] < MIN_N:
        return "INCONCLUSIVE", "fewer than 1000 events on a side"
    if spec["kind"] == "economic" and not _reproduced(row):
        return "INCONCLUSIVE", "this scan did not reproduce the locked H-ST-02 magnitude"
    if spec["kind"] == "economic" and (row["lift"] is None or row["lift"] < spec["degraded_lift"]):
        return "REJECTED", "spread plus two cents did not clear the locked lift"
    if spec["kind"] == "magnitude" and (row["ratio"] is None or row["ratio"] < spec["ratio_floor"]):
        return "REJECTED", "the absolute-move ratio missed its floor"
    if spec["kind"] == "magnitude" and (row["gap"] is None or row["gap"] < spec["dollar_floor"]):
        return "REJECTED", "the dollar gap is below the locked economic size"
    if row["tercile"] == "disagrees":
        return "REJECTED", "a discovery tercile disagrees in sign"
    if row["tercile"] == "underpowered":
        return "INCONCLUSIVE", "a discovery tercile has fewer than 1000 events"
    if row["longer"] == "disagrees":
        return "REJECTED", "horizon 1024 disagrees in sign"
    if row["delay_n"] < MIN_N:
        return "INCONCLUSIVE", "delay sample is below 1000"
    if spec["kind"] == "economic":
        return _economic_gate(row, holm_p)
    if row["delay_ratio"] is None or row["delay_ratio"] < spec["delay_ratio"]:
        return "REJECTED", "the one-quote delay missed its ratio floor"
    if holm_p >= ALPHA:
        return "REJECTED", "the Holm-adjusted p-value is not below 0.01"
    return "TESTED", spec["positive_claim"]


def _reproduced(row: Mapping[str, Any]) -> bool:
    return row["ratio"] is not None and row["gap"] is not None and row["ratio"] >= RATIO_FLOOR and row["gap"] >= MATERIAL_DOLLARS


def _economic_gate(row: Mapping[str, Any], holm_p: float) -> tuple[str, str]:
    spec = row["spec"]
    if row["delay_lift"] is None or row["delay_lift"] < spec["delay_lift"]:
        return "REJECTED", "the one-quote-delayed cost filter did not survive"
    time_status, time_reason = _time_status(row["item"], spec["time_ratio_max"])
    if time_status != "pass":
        return time_status, time_reason
    if holm_p >= ALPHA:
        return "REJECTED", "the Holm-adjusted p-value is not below 0.01"
    return "TESTED", spec["positive_claim"]


def _status(spec: Mapping[str, Any], status: str, reason: str, **fields: Any) -> dict[str, Any]:
    claim = spec["positive_claim"] if status == "TESTED" else reason
    return {
        "hypothesis_id": spec["hypothesis_id"],
        "status": status,
        "reason": reason,
        "claim": claim,
        "group_a": spec["group_a"],
        "group_b": spec["group_b"],
        "not_a_strategy": True,
        "held_out_span_opened": False,
        **fields,
    }


def rank_exploratory(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pre-declared ranking. Listed cells are generators, not tests."""
    reference = {row["horizon_quotes"]: row for row in rows if row["state"] == "unconditional" and row["n"] > 0}
    generated = []
    for row in rows:
        if row["state"] == "unconditional" or row["n"] < GENERATOR_N:
            continue
        base = reference.get(row["horizon_quotes"])
        if not base or not base["mean_abs"] or base["mean_abs"] <= 0:
            continue
        reasons = []
        signed_score = None
        if row["mean_spread"] and row["mean_spread"] > 0 and row["mean_signed"] is not None:
            signed_score = abs(row["mean_signed"]) / row["mean_spread"]
            if signed_score >= GENERATOR_SIGNED:
                reasons.append(f"signed move is {signed_score:.3f} of the cell spread; this is not a directional signal")
        ratio = row["mean_abs"] / base["mean_abs"] if row["mean_abs"] is not None else None
        if ratio is not None and ratio >= GENERATOR_RATIO:
            reasons.append(f"absolute move is {ratio:.3f} times the unconditional mean")
        if row["p_exceed_spread"] is not None and base["p_exceed_spread"] is not None:
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
                "signed_score": signed_score,
                "known_high_low_structure": row["state"] in {"vol_high", "vol_low"},
                "cannot_confirm_on_this_discovery_sample": True,
                "not_a_directional_signal": True,
            }
        )
    generated.sort(key=lambda item: (item["signed_score"] or 0.0, item["horizon_quotes"]), reverse=True)
    return generated


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, np.ndarray):
        return _jsonable(value.tolist())
    if isinstance(value, np.floating):
        value = float(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def scan_dataset(dataset_dir: Path) -> dict[str, Any]:
    dataset_dir = Path(dataset_dir)
    manifest = json.loads((dataset_dir / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    parts = manifest.get("parts") or []
    time_min, time_max = _stamp_range(dataset_dir, parts)
    cutoff = discovery_cutoff(time_min, time_max)
    scan = VolatilityScan(time_min, cutoff)
    for part in parts:
        print(f"volatility-scan {part['part']}", flush=True)
        parquet = pq.ParquetFile(dataset_dir / "parts" / part["part"])
        columns = [name for name in ("time_msc", "bid", "ask") if name in parquet.schema_arrow.names]
        for batch in parquet.iter_batches(batch_size=500_000, columns=columns):
            scan.add_batch(
                batch.column("bid").to_numpy(zero_copy_only=False),
                batch.column("ask").to_numpy(zero_copy_only=False),
                batch.column("time_msc").to_numpy(zero_copy_only=False),
            )
    report = scan.finish()
    identity_ok = not (
        manifest.get("dataset_sha256") == PUBLISHED_DIGEST and (scan.rows != PUBLISHED_ROWS or cutoff != PUBLISHED_CUTOFF)
    )
    if not identity_ok:
        report["hypotheses"] = {
            spec["hypothesis_id"]: _status(
                spec,
                "INCONCLUSIVE",
                "archive identity did not match the verified inventory",
                raw_p=1.0,
                holm_p=1.0,
            )
            for spec in FAMILY
        }
    report.update(
        {
            "generated_at_utc": datetime.now(UTC).isoformat(),
            "preregistration": "docs/xauusd_volatility_preregistration.md",
            "dataset": {
                "release": "dataset-xauusd-730d-20260919",
                "asset": "XAUUSD_730d_20260919T114013Z.zip",
                "expected_zip_sha256": EXPECTED_ZIP_SHA256,
                "manifest_dataset_sha256": manifest.get("dataset_sha256"),
                "timestamp_interpretation_confirmed": manifest.get("timestamp_interpretation_confirmed") is True,
            },
            "code_identity": {
                "git_sha": os.environ.get("GITHUB_SHA", "UNAVAILABLE"),
                "execution_host": os.environ.get("QTS_DISCOVERY_EXECUTION_HOST", "UNAVAILABLE"),
                "module": "qts.research.xauusd_volatility",
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
            "identity_ok": identity_ok,
            "prior_hypotheses_not_reopened": {
                "H-ST-01": "REJECTED",
                "H-ST-02": "TESTED",
                "H-ST-03": "REJECTED",
                "H-ST-04": "REJECTED",
            },
            "research_assumptions": [
                "states are functions of quotes at or before the event, never of the future move",
                "low, high, and extreme use the locked dollar cuts, not a search of future returns",
                "the $0.10 burst boundary belongs to quiet-to-expansion; stay-quiet is below that cut",
                "inferential identity is the global row modulo horizon+1, not the batch index",
                "waiting time is censored at the locked span or at 4096 quotes and does not use a locked price",
                "spread plus one cent was already visible in the state panel and is not a new confirmatory result",
                "a listed panel cell is a hypothesis generator and is not confirmed on this sample",
                "no directional hypothesis is registered",
            ],
        }
    )
    return _jsonable(report)


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


def render_volatility_report(report: dict[str, Any]) -> str:
    lines = [
        "# XAUUSD volatility-state measurement",
        "",
        f"Decision: {report.get('decision')}",
        "",
        "No strategy was promoted. A TESTED cell is not a trade. The locked span was not opened.",
        "",
        f"Clock: {(report.get('timestamp_basis') or {}).get('status', report.get('session_clock'))}",
        "",
        "## HYPOTHESES",
        "",
    ]
    hypotheses = report.get("hypotheses") or {}
    for spec in FAMILY:
        verdict = hypotheses.get(spec["hypothesis_id"]) or {}
        lines.append(f"- {spec['hypothesis_id']}: {verdict.get('status')} — {verdict.get('reason')}")
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
    output.write_text(json.dumps(_jsonable(report), indent=2) + "\n", encoding="utf-8")
