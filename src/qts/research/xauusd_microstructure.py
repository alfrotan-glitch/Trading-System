"""Discovery-window microstructure of the canonical XAUUSD quote stream.

Definitions are locked in docs/xauusd_microstructure_preregistration.md.
The locked span is not aggregated. No row is repaired. No strategy is built.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.parquet as pq
from scipy.stats import norm

from qts.data.mt5_history_acquisition import MANIFEST_FILENAME
from qts.research.impulse.statistics import holm_bonferroni
from qts.research.xauusd_tick_discovery import discovery_cutoff

SCHEMA = "qts.xauusd_microstructure.v1"
CARRY = 65
HORIZONS = (1, 4, 16, 64)
MOVE_CAP = 64
MOVE_HALF_CENTS = 2
SHORT_GAP_MS = 100
LONG_GAP_MS = 1000
SHORT_SENSITIVITY_MS = 50
MID_SENSITIVITY_MS = 200
LONG_SENSITIVITY_MS = 2000
MIN_N = 1000
MIN_N_PROMISING = 10000
EFFECT_RATE = 0.02
EFFECT_LIFT = 0.05
EFFECT_STAY = 0.05
EFFECT_VOL_RATIO = 1.25
EFFECT_SPR_RATIO = 1.10
HOLM_ALPHA = 0.01
RESOLVED_FRACTION_MIN = 0.50
FAMILY = ("H-QD-01", "H-QD-02", "H-INT-01", "H-SP-01", "H-MV-01", "H-VOL-01", "H-SPR-01")
PROCESS_ONLY = frozenset({"H-INT-01", "H-SP-01"})
DIRECTIONAL = frozenset({"H-QD-01", "H-QD-02", "H-MV-01"})
STATE_LABELS = (
    "bid_down_ask_down",
    "bid_down_ask_same",
    "spread_widen",
    "bid_same_ask_down",
    "unchanged",
    "bid_same_ask_up",
    "spread_tighten",
    "bid_up_ask_same",
    "bid_up_ask_up",
)
IMPLIED = np.array([-1, -1, 0, -1, 0, 1, 0, 1, 1], dtype=np.int8)
GAP_EDGES = np.array(
    [0, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 30000, 60000, 300000, 3600000, 86400000],
    dtype=np.int64,
)
PUBLISHED_ROWS = 139_930_971
PUBLISHED_CUTOFF = 1_764_563_969_254
PUBLISHED_DIGEST = "26aee827802066266fc5ef2f4ef30f874b0a7139666caf46f3bcfbec840e3789"
INT_THRESHOLDS = (SHORT_GAP_MS, SHORT_SENSITIVITY_MS, MID_SENSITIVITY_MS)


def classify_states(bid_cents: np.ndarray, ask_cents: np.ndarray) -> np.ndarray:
    """State of each row after the first. Position k describes row k+1."""
    db = np.asarray(bid_cents[1:], dtype=np.int32) - np.asarray(bid_cents[:-1], dtype=np.int32)
    da = np.asarray(ask_cents[1:], dtype=np.int32) - np.asarray(ask_cents[:-1], dtype=np.int32)
    return ((np.sign(db).astype(np.int8) + 1) * 3 + (np.sign(da).astype(np.int8) + 1)).astype(np.int8)


def timestamp_basis_assessment(manifest: dict[str, Any]) -> dict[str, Any]:
    """Do not treat a plausible clock, or a vendor sentence alone, as confirmation."""
    confirmed = manifest.get("timestamp_interpretation_confirmed") is True
    return {
        "timestamp_interpretation_confirmed": confirmed,
        "session_hour_weekday": "UNBLOCKED" if confirmed else "BLOCKED",
        "raw_interarrival_milliseconds": "USABLE_WITHOUT_TIMEZONE",
        "evidence": (
            "MetaQuotes' copy_ticks_range page says obtained tick times are UTC. "
            "The project live-tick path says server-local time and a measured offset. "
            "This archive's manifest does not confirm either reading for these rows."
        ),
        "status": "CONFIRMED" if confirmed else "BLOCKED",
    }


def mutual_information(joint: np.ndarray) -> float | None:
    total = float(np.asarray(joint).sum())
    if total <= 0:
        return None
    pxy = np.asarray(joint, dtype=np.float64) / total
    px = pxy.sum(axis=1, keepdims=True)
    py = pxy.sum(axis=0, keepdims=True)
    mask = pxy > 0
    return float(np.sum(pxy[mask] * np.log2(pxy[mask] / (px * py)[mask])))


def outcome_entropy(joint: np.ndarray) -> float | None:
    total = float(np.asarray(joint).sum())
    if total <= 0:
        return None
    py = np.asarray(joint, dtype=np.float64).sum(axis=0)
    py = py[py > 0] / total
    return float(-np.sum(py * np.log2(py)))


def _add_run(hist: np.ndarray, length: int) -> None:
    if length <= 0:
        return
    hist[min(length, hist.size - 1)] += 1


def accumulate_runs(
    signs: np.ndarray,
    open_sign: int,
    open_len: int,
    hist: np.ndarray,
    *,
    record_sign: int | None = None,
) -> tuple[int, int]:
    """Close completed runs. The run reaching the end of `signs` stays open."""
    if signs.size == 0:
        return open_sign, open_len
    values = np.asarray(signs, dtype=np.int8)
    change = np.empty(values.shape[0], dtype=bool)
    change[0] = True
    if values.size > 1:
        change[1:] = values[1:] != values[:-1]
    starts = np.flatnonzero(change)
    ends = np.empty_like(starts)
    ends[:-1] = starts[1:]
    ends[-1] = values.size
    lengths = (ends - starts).astype(np.int64)
    first_sign = int(values[0])
    if open_len and first_sign == open_sign:
        lengths = lengths.copy()
        lengths[0] += open_len
    elif open_len and (record_sign is None or open_sign == record_sign):
        _add_run(hist, open_len)
    if lengths.size > 1:
        for pos, length in enumerate(lengths[:-1].tolist()):
            sign = int(values[int(starts[pos])])
            if record_sign is None or sign == record_sign:
                _add_run(hist, int(length))
    return int(values[int(starts[-1])]), int(lengths[-1])


def resolve_one_cent(
    mid_half: np.ndarray,
    stamp: np.ndarray,
    signal_idx: np.ndarray,
    cutoff: int,
    *,
    start_k: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return decision index, status, realized sign, and half-cent delta from the base.

    Status 0 is incomplete, 1 resolved, 2 censored at the cap, 3 censored at the cutoff.
    """
    n = int(signal_idx.size)
    decision = np.full(n, -1, dtype=np.int64)
    status = np.zeros(n, dtype=np.int8)
    sign = np.zeros(n, dtype=np.int8)
    delta_out = np.zeros(n, dtype=np.int32)
    if n == 0:
        return decision, status, sign, delta_out
    incomplete = np.ones(n, dtype=bool)
    base_offset = 0 if start_k == 1 else 1
    series_n = int(mid_half.shape[0])
    for k in range(start_k, MOVE_CAP + 1):
        if not incomplete.any():
            break
        idx = signal_idx + k
        base = signal_idx + base_offset
        in_range = incomplete & (idx < series_n) & (base >= 0) & (base < series_n)
        if not in_range.any():
            continue
        active = np.flatnonzero(in_range)
        future = stamp[idx[active]]
        base_stamp = stamp[base[active]]
        blocked = (future >= cutoff) | (base_stamp >= cutoff)
        blocked_idx = active[blocked]
        status[blocked_idx] = 3
        decision[blocked_idx] = np.minimum(idx[blocked_idx], series_n - 1)
        incomplete[blocked_idx] = False
        keep = active[~blocked]
        if keep.size == 0:
            continue
        delta = mid_half[idx[keep]] - mid_half[base[keep]]
        hit = np.abs(delta) >= MOVE_HALF_CENTS
        hit_idx = keep[hit]
        status[hit_idx] = 1
        decision[hit_idx] = idx[hit_idx]
        sign[hit_idx] = np.sign(delta[hit]).astype(np.int8)
        delta_out[hit_idx] = delta[hit]
        incomplete[hit_idx] = False
        if k == MOVE_CAP:
            still = keep[~hit]
            status[still] = 2
            decision[still] = idx[still]
            incomplete[still] = False
    return decision, status, sign, delta_out


def _z_diff(diff: float, se: float, *, positive: bool) -> float:
    if se <= 0:
        return 0.0 if ((diff > 0) if positive else (diff < 0)) else 1.0
    z = diff / se
    return float(norm.sf(z) if positive else norm.cdf(z))


def _prop_diff_p(success_a: int, n_a: int, success_b: int, n_b: int) -> float:
    if n_a <= 0 or n_b <= 0:
        return 1.0
    p_a, p_b = success_a / n_a, success_b / n_b
    se = float(np.sqrt(p_a * (1.0 - p_a) / n_a + p_b * (1.0 - p_b) / n_b))
    return _z_diff(p_a - p_b, se, positive=True)


def _mean_diff_p(sum_a: float, sumsq_a: float, n_a: int, sum_b: float, sumsq_b: float, n_b: int) -> float:
    if n_a < 2 or n_b < 2:
        return 1.0
    mean_a, mean_b = sum_a / n_a, sum_b / n_b
    var_a = max((sumsq_a - sum_a * sum_a / n_a) / (n_a - 1), 0.0)
    var_b = max((sumsq_b - sum_b * sum_b / n_b) / (n_b - 1), 0.0)
    se = float(np.sqrt(var_a / n_a + var_b / n_b))
    return _z_diff(mean_a - mean_b, se, positive=True)


def _rate(success: int, n: int) -> float | None:
    return (success / n) if n else None


def _sum3(values: np.ndarray) -> int:
    return int(np.asarray(values).sum())


def _agree(values: list[float | None], *, positive: bool, counts: list[int]) -> str:
    seen = False
    for value, count in zip(values, counts, strict=True):
        if count < MIN_N:
            return "INCONCLUSIVE"
        seen = True
        if value is None or ((value <= 0) if positive else (value >= 0)):
            return "REJECTED"
    return "AGREE" if seen else "INCONCLUSIVE"


def _gate(
    *,
    hypothesis: str,
    predicted_effect: float | None,
    floor: float,
    p_value: float,
    tercile_effects: list[float | None],
    tercile_n: list[int],
    artifact_ok: bool,
    residual: float | None,
    overall_n: int,
    nonmonotonic: int,
    extra_fail: str | None = None,
) -> dict[str, Any]:
    if nonmonotonic:
        return {"id": hypothesis, "status": "INCONCLUSIVE", "reason": "backward time_msc steps were measured", "promoted": False}
    if overall_n < MIN_N or predicted_effect is None:
        return {"id": hypothesis, "status": "INCONCLUSIVE", "reason": "inferential sample is below 1000", "promoted": False}
    stability = _agree(tercile_effects, positive=predicted_effect > 0, counts=tercile_n)
    # A negative predicted effect is a failed prediction even before stability.
    if predicted_effect < floor:
        return {
            "id": hypothesis,
            "status": "REJECTED",
            "reason": f"predicted effect {predicted_effect:.6g} is below the floor {floor}",
            "promoted": False,
            "p_value": p_value,
        }
    if stability == "REJECTED":
        return {"id": hypothesis, "status": "REJECTED", "reason": "a discovery tercile disagrees in sign", "promoted": False}
    if stability == "INCONCLUSIVE" or overall_n < MIN_N_PROMISING:
        return {"id": hypothesis, "status": "INCONCLUSIVE", "reason": "stability sample is incomplete", "promoted": False}
    if extra_fail:
        return {"id": hypothesis, "status": "REJECTED", "reason": extra_fail, "promoted": False}
    if not artifact_ok:
        return {"id": hypothesis, "status": "REJECTED", "reason": "pre-declared artifact or delay gate failed", "promoted": False}
    if hypothesis in PROCESS_ONLY:
        return {
            "id": hypothesis,
            "status": "TESTED",
            "reason": "process structure is present; it is not a return predictor and not a strategy",
            "process_structure": True,
            "promoted": False,
            "p_value": p_value,
        }
    if hypothesis in DIRECTIONAL and (residual is None or residual <= 0):
        return {
            "id": hypothesis,
            "status": "TESTED",
            "reason": "direction is large enough to measure and does not survive one spread",
            "economic_edge": False,
            "promoted": False,
            "p_value": p_value,
        }
    if p_value >= HOLM_ALPHA:
        return {"id": hypothesis, "status": "REJECTED", "reason": "Holm-adjusted p-value is not below 0.01", "promoted": False}
    return {
        "id": hypothesis,
        "status": "PROMISING",
        "reason": "discovery gates passed; held-out span was not opened; not a strategy",
        "promoted": False,
        "not_robust": True,
        "executable": False,
        "p_value": p_value,
    }


def apply_verdicts(measured: dict[str, Any]) -> dict[str, Any]:
    """Apply the locked gates. Does not invent a test that was not measured."""
    nonmonotonic = int(measured.get("nonmonotonic") or 0)
    raw_p = []
    effects: dict[str, float] = {}

    def pooled(rows: list[int]) -> int:
        return int(sum(rows))

    qd = measured["H-QD-01"]
    one_n, two_n = pooled(qd["one_n"]), pooled(qd["two_n"])
    one_c, two_c = pooled(qd["one_cont"]), pooled(qd["two_cont"])
    qd_effect = (two_c / two_n - one_c / one_n) if one_n and two_n else None
    effects["H-QD-01"] = qd_effect if qd_effect is not None else -1.0
    raw_p.append(_prop_diff_p(two_c, two_n, one_c, one_n))
    qd_tercile = []
    qd_tn = []
    for t in range(3):
        qd_tn.append(min(qd["one_n"][t], qd["two_n"][t]))
        if qd["one_n"][t] and qd["two_n"][t]:
            qd_tercile.append(qd["two_cont"][t] / qd["two_n"][t] - qd["one_cont"][t] / qd["one_n"][t])
        else:
            qd_tercile.append(None)
    delay_one = pooled(qd["delay_one_n"])
    delay_two = pooled(qd["delay_two_n"])
    delay_effect = None
    if delay_one and delay_two:
        delay_effect = pooled(qd["delay_two_cont"]) / delay_two - pooled(qd["delay_one_cont"]) / delay_one
    one_fade = pooled_mean(qd["one_fade"], qd["one_n"])
    two_follow = pooled_mean(qd["two_follow"], qd["two_n"])
    qd_artifact = delay_effect is not None and qd_effect is not None and delay_effect > 0

    q2 = measured["H-QD-02"]
    q2_n, q2_c = pooled(q2["n"]), pooled(q2["cont"])
    q2_indep = _independence(pooled(q2["cur_up"]), pooled(q2["cur_down"]), pooled(q2["next_up"]), pooled(q2["next_down"]), q2_n)
    q2_effect = (q2_c / q2_n - q2_indep) if q2_n and q2_indep is not None else None
    effects["H-QD-02"] = abs(q2_effect) if q2_effect is not None else -1.0
    se = np.sqrt((q2_c / q2_n) * (1 - q2_c / q2_n) / q2_n) if q2_n else 1.0
    raw_p.append(_z_diff(q2_effect or 0.0, float(se), positive=True) if q2_effect and q2_effect > 0 else _z_diff(-(q2_effect or 0.0), float(se), positive=True))
    q2_tercile = []
    q2_tn = list(q2["n"])
    for t in range(3):
        indep_t = _independence(q2["cur_up"][t], q2["cur_down"][t], q2["next_up"][t], q2["next_down"][t], q2["n"][t])
        q2_tercile.append((q2["cont"][t] / q2["n"][t] - indep_t) if q2["n"][t] and indep_t is not None else None)
    direction = 1.0 if (q2_effect or 0.0) >= 0 else -1.0
    q2_aligned = [None if value is None else direction * value for value in q2_tercile]
    delay_n = pooled(q2["delay_n"])
    delay_indep = _independence(
        pooled(q2["delay_cur_up"]), pooled(q2["delay_cur_down"]), pooled(q2["delay_next_up"]), pooled(q2["delay_next_down"]), delay_n
    )
    delay_excess = None
    if delay_n and delay_indep is not None:
        delay_excess = pooled(q2["delay_cont"]) / delay_n - delay_indep
    follow = pooled_mean(q2["follow"], q2["n"])
    fade = pooled_mean(q2["fade"], q2["n"])
    residual = follow if (q2_effect or 0) > 0 else fade
    q2_artifact = (
        q2_effect is not None
        and delay_excess is not None
        and ((q2_effect > 0 and delay_excess > 0) or (q2_effect < 0 and delay_excess < 0))
    )

    intensity = measured["H-INT-01"]
    lift, lift_p = _lift(intensity, 0)
    effects["H-INT-01"] = lift if lift is not None else -1.0
    raw_p.append(lift_p)
    int_tercile = [_lift_tercile(intensity, 0, t) for t in range(3)]
    int_tn = [int(intensity["short"][0][t]) for t in range(3)]
    lift_50, _ = _lift(intensity, 1)
    lift_200, _ = _lift(intensity, 2)
    int_artifact = lift_50 is not None and lift_200 is not None and lift_50 > 0 and lift_200 > 0

    stay = measured["H-SP-01"]
    stay_n = pooled(stay["n"])
    stay_rate = pooled(stay["hit"]) / stay_n if stay_n else None
    bench = stay.get("independence")
    stay_effect = (stay_rate - bench) if stay_rate is not None and bench is not None else None
    effects["H-SP-01"] = stay_effect if stay_effect is not None else -1.0
    stay_se = np.sqrt(stay_rate * (1 - stay_rate) / stay_n) if stay_n and stay_rate is not None else 1.0
    raw_p.append(_z_diff(stay_effect or 0.0, float(stay_se), positive=True))
    stay_tercile = []
    for t in range(3):
        if stay["n"][t] and stay["independence_tercile"][t] is not None:
            stay_tercile.append(stay["hit"][t] / stay["n"][t] - stay["independence_tercile"][t])
        else:
            stay_tercile.append(None)

    mv = measured["H-MV-01"]
    mv_n = pooled(mv["resolved"]) + pooled(mv["censored"])
    mv_resolved = pooled(mv["resolved"])
    mv_rate = pooled(mv["up_hit"]) / mv_resolved if mv_resolved else None
    mv_effect = (mv_rate - 0.5) if mv_rate is not None else None
    effects["H-MV-01"] = mv_effect if mv_effect is not None else -1.0
    mv_se = np.sqrt(mv_rate * (1 - mv_rate) / mv_resolved) if mv_resolved and mv_rate is not None else 1.0
    raw_p.append(_z_diff(mv_effect or 0.0, float(mv_se), positive=True))
    mv_tercile = [(mv["up_hit"][t] / mv["resolved"][t] - 0.5) if mv["resolved"][t] else None for t in range(3)]
    mv_tn = [int(mv["resolved"][t] + mv["censored"][t]) for t in range(3)]
    mirror_n = pooled(mv["down_resolved"])
    mirror = pooled(mv["down_hit"]) / mirror_n if mirror_n else None
    delay_res = pooled(mv["delay_resolved"])
    delay_rate = pooled(mv["delay_hit"]) / delay_res if delay_res else None
    fraction = mv_resolved / mv_n if mv_n else 0.0
    mv_artifact = mirror is not None and mirror > 0.5 and delay_rate is not None and delay_rate > 0.5
    mv_residual = pooled_mean(mv["residual"], mv["resolved"])

    vol = measured["H-VOL-01"]
    vol_effect, vol_p = _ratio_and_p(vol["short_sum"], vol["short_sumsq"], vol["short_n"], vol["long_sum"], vol["long_sumsq"], vol["long_n"])
    effects["H-VOL-01"] = vol_effect if vol_effect is not None else -1.0
    raw_p.append(vol_p)
    vol_tercile = [_ratio(vol["short_sum"][t], vol["short_n"][t], vol["long_sum"][t], vol["long_n"][t]) for t in range(3)]
    vol_tn = [min(vol["short_n"][t], vol["long_n"][t]) for t in range(3)]
    sens = _ratio(pooled(vol["sens_short_sum"]), pooled(vol["sens_short_n"]), pooled(vol["sens_long_sum"]), pooled(vol["sens_long_n"]))
    vol_artifact = sens is not None and sens > 1.0

    spr = measured["H-SPR-01"]
    spr_effect, spr_p = _ratio_and_p(spr["widen_sum"], spr["widen_sumsq"], spr["widen_n"], spr["tight_sum"], spr["tight_sumsq"], spr["tight_n"])
    effects["H-SPR-01"] = spr_effect if spr_effect is not None else -1.0
    raw_p.append(spr_p)
    spr_tercile = [_ratio(spr["delay_widen_sum"][t], spr["delay_widen_n"][t], spr["delay_tight_sum"][t], spr["delay_tight_n"][t]) for t in range(3)]
    spr_tn = [min(spr["delay_widen_n"][t], spr["delay_tight_n"][t]) for t in range(3)]
    delay_ratio = _ratio(pooled(spr["delay_widen_sum"]), pooled(spr["delay_widen_n"]), pooled(spr["delay_tight_sum"]), pooled(spr["delay_tight_n"]))
    spr_artifact = delay_ratio is not None and delay_ratio >= EFFECT_SPR_RATIO

    adjusted = holm_bonferroni(raw_p)
    specs = {
        "H-QD-01": (qd_effect, EFFECT_RATE, qd_tercile, qd_tn, qd_artifact, min(one_fade, two_follow), min(one_n, two_n), None),
        "H-QD-02": (abs(q2_effect) if q2_effect is not None else None, EFFECT_RATE, q2_aligned, q2_tn, q2_artifact, residual, q2_n, None),
        "H-INT-01": (lift, EFFECT_LIFT, int_tercile, int_tn, int_artifact, None, pooled(intensity["short"][0]), None),
        "H-SP-01": (stay_effect, EFFECT_STAY, stay_tercile, list(stay["n"]), True, None, stay_n, None),
        "H-MV-01": (mv_effect, EFFECT_RATE, mv_tercile, mv_tn, mv_artifact, mv_residual, mv_resolved, None),
        "H-VOL-01": ((vol_effect - 1.0) if vol_effect is not None else None, EFFECT_VOL_RATIO - 1.0, [None if v is None else v - 1.0 for v in vol_tercile], vol_tn, vol_artifact, None, min(pooled(vol["short_n"]), pooled(vol["long_n"])), None),
        "H-SPR-01": ((spr_effect - 1.0) if spr_effect is not None else None, EFFECT_SPR_RATIO - 1.0, [None if v is None else v - 1.0 for v in spr_tercile], spr_tn, spr_artifact, None, min(pooled(spr["widen_n"]), pooled(spr["tight_n"])), None),
    }
    # H-SPR stability is judged on the delayed ratio, which is the artifact-proof contrast.
    verdicts = {}
    for pos, hypothesis in enumerate(FAMILY):
        effect, floor, terciles, counts, artifact, residual_value, n_value, extra = specs[hypothesis]
        verdict = _gate(
            hypothesis=hypothesis,
            predicted_effect=effect,
            floor=floor,
            p_value=adjusted[pos],
            tercile_effects=terciles,
            tercile_n=counts,
            artifact_ok=artifact,
            residual=residual_value,
            overall_n=n_value,
            nonmonotonic=nonmonotonic,
            extra_fail=extra,
        )
        verdict["raw_p_value"] = raw_p[pos]
        verdict["holm_p_value"] = adjusted[pos]
        if hypothesis == "H-MV-01" and fraction < RESOLVED_FRACTION_MIN and verdict["status"] != "REJECTED":
            verdict["status"] = "INCONCLUSIVE"
            verdict["reason"] = "resolved fraction is below 0.50"
            verdict["promoted"] = False
        verdicts[hypothesis] = verdict
    return verdicts


def pooled_mean(sums: list[float], counts: list[int]) -> float:
    n = sum(counts)
    if not n:
        return 0.0
    return float(sum(sums) / n)


def _independence(cur_up: int, cur_down: int, next_up: int, next_down: int, n: int) -> float | None:
    if n <= 0:
        return None
    return (cur_up / n) * (next_up / n) + (cur_down / n) * (next_down / n)


def _lift(block: dict[str, Any], threshold: int) -> tuple[float | None, float]:
    short = pooled_count(block["short"][threshold])
    both = pooled_count(block["both"][threshold])
    n_all = pooled_count(block["n"][threshold])
    next_short = pooled_count(block["next_short"][threshold])
    if not short or not n_all:
        return None, 1.0
    cond = both / short
    base = next_short / n_all
    se = float(np.sqrt(cond * (1.0 - cond) / short))
    return cond - base, _z_diff(cond - base, se, positive=True)


def _lift_tercile(block: dict[str, Any], threshold: int, tercile: int) -> float | None:
    short = block["short"][threshold][tercile]
    n_all = block["n"][threshold][tercile]
    if not short or not n_all:
        return None
    return block["both"][threshold][tercile] / short - block["next_short"][threshold][tercile] / n_all


def pooled_count(values: list[int] | np.ndarray) -> int:
    return int(np.asarray(values).sum())


def _ratio(sum_a: float, n_a: int, sum_b: float, n_b: int) -> float | None:
    if not n_a or not n_b or sum_b == 0:
        return None
    return (sum_a / n_a) / (sum_b / n_b)


def _ratio_and_p(
    sum_a: list[float], sumsq_a: list[float], n_a: list[int], sum_b: list[float], sumsq_b: list[float], n_b: list[int]
) -> tuple[float | None, float]:
    ratio = _ratio(sum(sum_a), sum(n_a), sum(sum_b), sum(n_b))
    p_value = _mean_diff_p(sum(sum_a), sum(sumsq_a), sum(n_a), sum(sum_b), sum(sumsq_b), sum(n_b))
    return ratio, p_value


class DiscoveryScan:
    """One streaming pass. Hypothesis counters are discovery-window only."""

    def __init__(self, time_min: int, cutoff: int) -> None:
        if cutoff <= time_min:
            raise ValueError("cutoff must be after time_min")
        self.time_min = int(time_min)
        self.cutoff = int(cutoff)
        self.span = self.cutoff - self.time_min
        self.rows = 0
        self.discovery_rows = 0
        self.validation_rows = 0
        self.nonmonotonic = 0
        self.invalid_price_rows = 0
        self.negative_spread_rows = 0
        self.carry_n = 0
        self.carry_bid = np.empty(0, dtype=np.int32)
        self.carry_ask = np.empty(0, dtype=np.int32)
        self.carry_stamp = np.empty(0, dtype=np.int64)
        self.transition = np.zeros((9, 9), dtype=np.int64)
        self.transition_nonoverlap = np.zeros((9, 9), dtype=np.int64)
        self.state_counts = np.zeros(9, dtype=np.int64)
        self.half_cent = np.zeros(4, dtype=np.int64)
        self.bid_magnitude = np.zeros(21, dtype=np.int64)
        self.ask_magnitude = np.zeros(21, dtype=np.int64)
        self.gap_hist = np.zeros(GAP_EDGES.size, dtype=np.int64)
        self.nonpositive_gaps = 0
        self.run_hist = np.zeros(33, dtype=np.int64)
        self.short_gap_run_hist = np.zeros(33, dtype=np.int64)
        self.open_sign = 0
        self.open_len = 0
        self.open_short_sign = 0
        self.open_short_len = 0
        self.spread_curve_n = np.zeros((2, 81), dtype=np.int64)
        self.spread_curve_abs = np.zeros((2, 81), dtype=np.float64)
        self.panel_n = np.zeros((2, 9, 4), dtype=np.int64)
        self.panel_abs = np.zeros((2, 9, 4), dtype=np.float64)
        self.panel_signed = np.zeros((2, 9, 4), dtype=np.float64)
        self.panel_cont = np.zeros((2, 9, 4), dtype=np.int64)
        self.qd01_one_n = np.zeros(3, dtype=np.int64)
        self.qd01_one_cont = np.zeros(3, dtype=np.int64)
        self.qd01_two_n = np.zeros(3, dtype=np.int64)
        self.qd01_two_cont = np.zeros(3, dtype=np.int64)
        self.qd01_one_fade = np.zeros(3, dtype=np.float64)
        self.qd01_two_follow = np.zeros(3, dtype=np.float64)
        self.qd01_delay_one_n = np.zeros(3, dtype=np.int64)
        self.qd01_delay_one_cont = np.zeros(3, dtype=np.int64)
        self.qd01_delay_two_n = np.zeros(3, dtype=np.int64)
        self.qd01_delay_two_cont = np.zeros(3, dtype=np.int64)
        self.qd02_n = np.zeros(3, dtype=np.int64)
        self.qd02_cont = np.zeros(3, dtype=np.int64)
        self.qd02_cur_up = np.zeros(3, dtype=np.int64)
        self.qd02_cur_down = np.zeros(3, dtype=np.int64)
        self.qd02_next_up = np.zeros(3, dtype=np.int64)
        self.qd02_next_down = np.zeros(3, dtype=np.int64)
        self.qd02_follow = np.zeros(3, dtype=np.float64)
        self.qd02_fade = np.zeros(3, dtype=np.float64)
        self.qd02_delay_n = np.zeros(3, dtype=np.int64)
        self.qd02_delay_cont = np.zeros(3, dtype=np.int64)
        self.qd02_delay_cur_up = np.zeros(3, dtype=np.int64)
        self.qd02_delay_cur_down = np.zeros(3, dtype=np.int64)
        self.qd02_delay_next_up = np.zeros(3, dtype=np.int64)
        self.qd02_delay_next_down = np.zeros(3, dtype=np.int64)
        self.int_n = np.zeros((3, 3), dtype=np.int64)
        self.int_short = np.zeros((3, 3), dtype=np.int64)
        self.int_next_short = np.zeros((3, 3), dtype=np.int64)
        self.int_both = np.zeros((3, 3), dtype=np.int64)
        self.stay_n = np.zeros(3, dtype=np.int64)
        self.stay_hit = np.zeros(3, dtype=np.int64)
        self.spread_marginal: list[dict[int, int]] = [{}, {}, {}]
        self.mv_resolved = np.zeros(3, dtype=np.int64)
        self.mv_censored = np.zeros(3, dtype=np.int64)
        self.mv_up_hit = np.zeros(3, dtype=np.int64)
        self.mv_residual = np.zeros(3, dtype=np.float64)
        self.mv_down_resolved = np.zeros(3, dtype=np.int64)
        self.mv_down_hit = np.zeros(3, dtype=np.int64)
        self.mv_delay_resolved = np.zeros(3, dtype=np.int64)
        self.mv_delay_hit = np.zeros(3, dtype=np.int64)
        self.vol_short_n = np.zeros(3, dtype=np.int64)
        self.vol_short_sum = np.zeros(3, dtype=np.float64)
        self.vol_short_sumsq = np.zeros(3, dtype=np.float64)
        self.vol_long_n = np.zeros(3, dtype=np.int64)
        self.vol_long_sum = np.zeros(3, dtype=np.float64)
        self.vol_long_sumsq = np.zeros(3, dtype=np.float64)
        self.vol_sens_short_n = np.zeros(3, dtype=np.int64)
        self.vol_sens_short_sum = np.zeros(3, dtype=np.float64)
        self.vol_sens_long_n = np.zeros(3, dtype=np.int64)
        self.vol_sens_long_sum = np.zeros(3, dtype=np.float64)
        self.spr_widen_n = np.zeros(3, dtype=np.int64)
        self.spr_widen_sum = np.zeros(3, dtype=np.float64)
        self.spr_widen_sumsq = np.zeros(3, dtype=np.float64)
        self.spr_tight_n = np.zeros(3, dtype=np.int64)
        self.spr_tight_sum = np.zeros(3, dtype=np.float64)
        self.spr_tight_sumsq = np.zeros(3, dtype=np.float64)
        self.spr_delay_widen_n = np.zeros(3, dtype=np.int64)
        self.spr_delay_widen_sum = np.zeros(3, dtype=np.float64)
        self.spr_delay_tight_n = np.zeros(3, dtype=np.int64)
        self.spr_delay_tight_sum = np.zeros(3, dtype=np.float64)

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
        self.invalid_price_rows += int(np.count_nonzero((bid_c <= 0) | (ask_c <= 0)))
        self.negative_spread_rows += int(np.count_nonzero(ask_c < bid_c))
        carry_n = self.carry_n
        if carry_n:
            bid_c = np.concatenate((self.carry_bid, bid_c))
            ask_c = np.concatenate((self.carry_ask, ask_c))
            stamp_a = np.concatenate((self.carry_stamp, stamp_a))
        series_n = int(bid_c.shape[0])
        global_base = self.rows - n_new - carry_n
        if series_n >= 2:
            self._consume(bid_c, ask_c, stamp_a, carry_n, global_base)
        tail = min(CARRY, series_n)
        self.carry_bid = bid_c[-tail:].copy()
        self.carry_ask = ask_c[-tail:].copy()
        self.carry_stamp = stamp_a[-tail:].copy()
        self.carry_n = tail

    def _consume(self, bid_c: np.ndarray, ask_c: np.ndarray, stamp_a: np.ndarray, carry_n: int, global_base: int) -> None:
        series_n = int(bid_c.shape[0])
        state_into = classify_states(bid_c, ask_c)
        db = bid_c[1:] - bid_c[:-1]
        da = ask_c[1:] - ask_c[:-1]
        dmid = db + da
        gap = stamp_a[1:] - stamp_a[:-1]
        valid = (bid_c > 0) & (ask_c > 0) & (ask_c >= bid_c)
        new_into = np.zeros(series_n, dtype=bool)
        if carry_n < series_n:
            new_into[max(carry_n, 1) :] = True
        self.nonmonotonic += int(np.count_nonzero((gap < 0) & new_into[1:]))
        self._descriptive(state_into, dmid, db, da, gap, stamp_a, valid, new_into, global_base)
        self._runs(dmid, gap, stamp_a, new_into)
        mid_half = bid_c.astype(np.int32) + ask_c.astype(np.int32)
        spread_cents = ask_c.astype(np.int32) - bid_c.astype(np.int32)
        for h_index, horizon in enumerate(HORIZONS):
            self._horizon(horizon, h_index, state_into, mid_half, spread_cents, stamp_a, valid, carry_n, global_base, series_n)
        self._qd_delay(state_into, mid_half, spread_cents, stamp_a, valid, carry_n, global_base, series_n)
        self._intensity(stamp_a, valid, carry_n, global_base, series_n)
        self._spread_stay(spread_cents, stamp_a, valid, carry_n, global_base, series_n)
        self._move(state_into, mid_half, spread_cents, stamp_a, valid, carry_n, global_base, series_n)
        self._vol_spr(state_into, mid_half, stamp_a, valid, carry_n, global_base, series_n)

    def _bucket(self, mask: np.ndarray, tercile: np.ndarray, n_arr: np.ndarray, success: np.ndarray | None = None, ok: np.ndarray | None = None) -> None:
        for t in range(3):
            chosen = mask & (tercile == t)
            if not chosen.any():
                continue
            n_arr[t] += int(np.count_nonzero(chosen))
            if success is not None and ok is not None:
                success[t] += int(np.count_nonzero(chosen & ok))

    def _add_values(self, mask: np.ndarray, tercile: np.ndarray, values: np.ndarray, n_arr: np.ndarray, sum_arr: np.ndarray, sumsq: np.ndarray | None = None) -> None:
        for t in range(3):
            chosen = mask & (tercile == t)
            if not chosen.any():
                continue
            v = values[chosen]
            n_arr[t] += int(v.size)
            sum_arr[t] += float(v.sum())
            if sumsq is not None:
                sumsq[t] += float(np.dot(v, v))

    def _descriptive(self, state_into, dmid, db, da, gap, stamp_a, valid, new_into, global_base: int) -> None:
        row = np.arange(1, state_into.size + 1)
        use = new_into[row] & valid[row] & valid[row - 1] & (stamp_a[row] < self.cutoff) & (stamp_a[row - 1] < self.cutoff)
        if use.any():
            states = state_into[np.flatnonzero(use)]
            self.state_counts += np.bincount(states, minlength=9)
            abs_half = np.abs(dmid[use])
            self.half_cent[0] += int(np.count_nonzero(abs_half == 0))
            self.half_cent[1] += int(np.count_nonzero(abs_half == 1))
            self.half_cent[2] += int(np.count_nonzero(abs_half == 2))
            self.half_cent[3] += int(np.count_nonzero(abs_half >= 3))
            self.bid_magnitude += np.bincount(np.clip(np.abs(db[use]), 0, 20), minlength=21)
            self.ask_magnitude += np.bincount(np.clip(np.abs(da[use]), 0, 20), minlength=21)
            gaps = gap[use]
            self.nonpositive_gaps += int(np.count_nonzero(gaps <= 0))
            positive = gaps[gaps > 0]
            if positive.size:
                bins = np.searchsorted(GAP_EDGES, positive, side="right") - 1
                self.gap_hist += np.bincount(bins, minlength=self.gap_hist.size)
        if state_into.size < 2:
            return
        later = np.arange(1, state_into.size)
        earlier = later - 1
        later_row = later + 1
        earlier_row = earlier + 1
        pair = (
            new_into[later_row]
            & valid[later_row]
            & valid[earlier_row]
            & valid[earlier_row - 1]
            & (stamp_a[later_row] < self.cutoff)
            & (stamp_a[earlier_row] < self.cutoff)
        )
        if not pair.any():
            return
        left = state_into[earlier[pair]]
        right = state_into[later[pair]]
        np.add.at(self.transition, (left, right), 1)
        chosen = pair & (((global_base + earlier_row) % 2) == 0)
        if chosen.any():
            np.add.at(self.transition_nonoverlap, (state_into[earlier[chosen]], state_into[later[chosen]]), 1)

    def _runs(self, dmid, gap, stamp_a, new_into) -> None:
        row = np.arange(1, dmid.size + 1)
        new = new_into[row]
        if not new.any():
            return
        new_idx = np.flatnonzero(new)
        locked = np.flatnonzero(stamp_a[row[new_idx]] >= self.cutoff)
        close_after = bool(locked.size)
        if close_after:
            new_idx = new_idx[: int(locked[0])]
        if new_idx.size:
            signs = np.sign(dmid[new_idx]).astype(np.int8)
            self.open_sign, self.open_len = accumulate_runs(signs, self.open_sign, self.open_len, self.run_hist)
            short = ((gap[new_idx] > 0) & (gap[new_idx] <= SHORT_GAP_MS)).astype(np.int8)
            self.open_short_sign, self.open_short_len = accumulate_runs(
                short, self.open_short_sign, self.open_short_len, self.short_gap_run_hist, record_sign=1
            )
        if close_after:
            if self.open_sign != 0:
                _add_run(self.run_hist, self.open_len)
            self.open_sign, self.open_len = 0, 0
            if self.open_short_sign == 1:
                _add_run(self.short_gap_run_hist, self.open_short_len)
            self.open_short_sign, self.open_short_len = 0, 0

    def _pair(self, series_n: int, carry_n: int, horizon: int) -> tuple[np.ndarray, np.ndarray]:
        start = max(carry_n, horizon + 1)
        if start >= series_n:
            empty = np.empty(0, dtype=np.int64)
            return empty, empty
        j = np.arange(start, series_n, dtype=np.int64)
        return j - horizon, j

    def _event_mask(self, i, j, stamp_a, valid, global_base: int, step: int) -> tuple[np.ndarray, np.ndarray]:
        mask = valid[i] & valid[i - 1] & valid[j] & (stamp_a[i] < self.cutoff) & (stamp_a[i - 1] < self.cutoff) & (stamp_a[j] < self.cutoff)
        infer = mask & (((global_base + i) % step) == 0)
        tercile = np.zeros(i.shape[0], dtype=np.int8)
        if infer.any():
            tercile[infer] = np.clip(((stamp_a[i[infer]] - self.time_min) * 3) // self.span, 0, 2)
        return infer, tercile

    def _horizon(self, horizon, h_index, state_into, mid_half, spread_cents, stamp_a, valid, carry_n, global_base, series_n) -> None:
        i, j = self._pair(series_n, carry_n, horizon)
        if i.size == 0:
            return
        state = state_into[i - 1]
        dmid = mid_half[j] - mid_half[i]
        current = mid_half[i] - mid_half[i - 1]
        infer, tercile = self._event_mask(i, j, stamp_a, valid, global_base, horizon + 1)
        all_mask = valid[i] & valid[i - 1] & valid[j] & (stamp_a[i] < self.cutoff) & (stamp_a[j] < self.cutoff)
        for sample, mask in ((0, all_mask), (1, infer)):
            if not mask.any():
                continue
            abs_move = np.abs(dmid[mask]) * 0.005
            states = state[mask]
            self.panel_n[sample, :, h_index] += np.bincount(states, minlength=9)
            for code in range(9):
                chosen = states == code
                if not chosen.any():
                    continue
                self.panel_abs[sample, code, h_index] += float(abs_move[chosen].sum())
                implied = int(IMPLIED[code])
                if implied:
                    signed = implied * dmid[mask][chosen] * 0.005
                    self.panel_signed[sample, code, h_index] += float(signed.sum())
                    self.panel_cont[sample, code, h_index] += int(np.count_nonzero(np.sign(dmid[mask][chosen]) == implied))
        if horizon == 1:
            self._qd(i, state, current, dmid, spread_cents, mid_half, infer, tercile)
        if horizon in (1, 16):
            curve_i = 0 if horizon == 1 else 1
            spread = spread_cents[i]
            curve = infer & (spread >= 0)
            if curve.any():
                bins = np.clip(spread[curve], 0, 80)
                weights = np.abs(dmid[curve]) * 0.005
                self.spread_curve_n[curve_i] += np.bincount(bins, minlength=81)
                self.spread_curve_abs[curve_i] += np.bincount(bins, weights=weights, minlength=81)

    def _qd(self, i, state, current, dmid, spread_cents, mid_half, infer, tercile) -> None:
        nonzero = infer & (current != 0)
        if not nonzero.any():
            return
        continued = np.sign(dmid) == np.sign(current)
        one = nonzero & np.isin(state, (1, 3, 5, 7))
        two = nonzero & np.isin(state, (0, 8))
        self._bucket(one, tercile, self.qd01_one_n, self.qd01_one_cont, continued)
        self._bucket(two, tercile, self.qd01_two_n, self.qd01_two_cont, continued)
        self._bucket(nonzero, tercile, self.qd02_n, self.qd02_cont, continued)
        self._bucket(nonzero & (current > 0), tercile, self.qd02_cur_up)
        self._bucket(nonzero & (current < 0), tercile, self.qd02_cur_down)
        self._bucket(nonzero & (dmid > 0), tercile, self.qd02_next_up)
        self._bucket(nonzero & (dmid < 0), tercile, self.qd02_next_down)
        mid = mid_half[i] * 0.005
        spread = spread_cents[i] * 0.01
        move = dmid * 0.005
        safe = nonzero & (mid > 0)
        follow = np.zeros(i.shape[0])
        fade = np.zeros(i.shape[0])
        follow[safe] = (np.sign(current[safe]) * move[safe] - spread[safe]) / mid[safe] * 10000.0
        fade[safe] = (-np.sign(current[safe]) * move[safe] - spread[safe]) / mid[safe] * 10000.0
        self._residual(one & safe, tercile, fade, self.qd01_one_fade)
        self._residual(two & safe, tercile, follow, self.qd01_two_follow)
        self._residual(safe, tercile, follow, self.qd02_follow)
        self._residual(safe, tercile, fade, self.qd02_fade)

    def _residual(self, mask, tercile, values, sum_arr) -> None:
        for t in range(3):
            chosen = mask & (tercile == t)
            if chosen.any():
                sum_arr[t] += float(values[chosen].sum())

    def _qd_delay(self, state_into, mid_half, spread_cents, stamp_a, valid, carry_n, global_base, series_n) -> None:
        start = max(carry_n, 3)
        if start >= series_n:
            return
        j = np.arange(start, series_n, dtype=np.int64)
        i = j - 2
        prev = i - 1
        nxt = i + 1
        state = state_into[i - 1]
        current = mid_half[i] - mid_half[prev]
        dmid = mid_half[j] - mid_half[nxt]
        infer, tercile = self._event_mask(i, j, stamp_a, valid, global_base, 3)
        infer = infer & valid[nxt] & (stamp_a[nxt] < self.cutoff) & (current != 0)
        continued = np.sign(dmid) == np.sign(current)
        self._bucket(infer & np.isin(state, (1, 3, 5, 7)), tercile, self.qd01_delay_one_n, self.qd01_delay_one_cont, continued)
        self._bucket(infer & np.isin(state, (0, 8)), tercile, self.qd01_delay_two_n, self.qd01_delay_two_cont, continued)
        self._bucket(infer, tercile, self.qd02_delay_n, self.qd02_delay_cont, continued)
        self._bucket(infer & (current > 0), tercile, self.qd02_delay_cur_up)
        self._bucket(infer & (current < 0), tercile, self.qd02_delay_cur_down)
        self._bucket(infer & (dmid > 0), tercile, self.qd02_delay_next_up)
        self._bucket(infer & (dmid < 0), tercile, self.qd02_delay_next_down)

    def _intensity(self, stamp_a, valid, carry_n, global_base, series_n) -> None:
        i, j = self._pair(series_n, carry_n, 1)
        if i.size == 0:
            return
        gap_in = stamp_a[i] - stamp_a[i - 1]
        gap_out = stamp_a[j] - stamp_a[i]
        infer, tercile = self._event_mask(i, j, stamp_a, valid, global_base, 2)
        infer = infer & (gap_in > 0) & (gap_out > 0)
        for pos, threshold in enumerate(INT_THRESHOLDS):
            short = gap_in <= threshold
            next_short = gap_out <= threshold
            self._bucket(infer, tercile, self.int_n[pos])
            self._bucket(infer & short, tercile, self.int_short[pos])
            self._bucket(infer & next_short, tercile, self.int_next_short[pos])
            self._bucket(infer & short & next_short, tercile, self.int_both[pos])

    def _spread_stay(self, spread_cents, stamp_a, valid, carry_n, global_base, series_n) -> None:
        i, j = self._pair(series_n, carry_n, 1)
        if i.size == 0:
            return
        infer, tercile = self._event_mask(i, j, stamp_a, valid, global_base, 2)
        infer = infer & (spread_cents[i] >= 0) & (spread_cents[j] >= 0)
        same = spread_cents[j] == spread_cents[i]
        self._bucket(infer, tercile, self.stay_n, self.stay_hit, same)
        if infer.any():
            for t in range(3):
                chosen = infer & (tercile == t)
                if not chosen.any():
                    continue
                values, counts = np.unique(spread_cents[i[chosen]], return_counts=True)
                bucket = self.spread_marginal[t]
                for value, count in zip(values.tolist(), counts.tolist(), strict=True):
                    if len(bucket) >= 500 and int(value) not in bucket:
                        continue
                    bucket[int(value)] = bucket.get(int(value), 0) + int(count)

    def _move(self, state_into, mid_half, spread_cents, stamp_a, valid, carry_n, global_base, series_n) -> None:
        state_of_row = np.full(series_n, -1, dtype=np.int8)
        state_of_row[1:] = state_into
        rows = np.flatnonzero((state_of_row == 1) | (state_of_row == 7))
        if rows.size == 0:
            return
        rows = rows[((global_base + rows) % (MOVE_CAP + 1)) == 0]
        rows = rows[(rows >= 1) & valid[rows] & valid[rows - 1] & (stamp_a[rows] < self.cutoff)]
        if rows.size == 0:
            return
        self._emit_move(rows, state_of_row, mid_half, spread_cents, stamp_a, carry_n, global_base, start_k=1, delayed=False)
        self._emit_move(rows, state_of_row, mid_half, spread_cents, stamp_a, carry_n, global_base, start_k=2, delayed=True)

    def _emit_move(self, rows, state_of_row, mid_half, spread_cents, stamp_a, carry_n, global_base, *, start_k: int, delayed: bool) -> None:
        decision, status, _sign, delta = resolve_one_cent(mid_half, stamp_a, rows, self.cutoff, start_k=start_k)
        emit = (status != 0) & (decision >= carry_n)
        if not emit.any():
            return
        idx = np.flatnonzero(emit)
        signals = rows[idx]
        tercile = np.clip(((stamp_a[signals] - self.time_min) * 3) // self.span, 0, 2)
        up = state_of_row[signals] == 7
        down = state_of_row[signals] == 1
        resolved = status[idx] == 1
        censored = (status[idx] == 2) | (status[idx] == 3)
        if not delayed:
            self._bucket(up & resolved, tercile, self.mv_resolved)
            self._bucket(up & censored, tercile, self.mv_censored)
            hit_up = up & resolved & (delta[idx] > 0)
            self._bucket(hit_up, tercile, self.mv_up_hit)
            self._bucket(down & resolved, tercile, self.mv_down_resolved)
            self._bucket(down & resolved & (delta[idx] < 0), tercile, self.mv_down_hit)
            mid = mid_half[signals] * 0.005
            spread = spread_cents[signals] * 0.01
            residual = np.zeros(signals.shape[0])
            safe = up & resolved & (mid > 0)
            residual[safe] = (delta[idx][safe] * 0.005 - spread[safe]) / mid[safe] * 10000.0
            self._residual(safe, tercile, residual, self.mv_residual)
        else:
            self._bucket(up & resolved, tercile, self.mv_delay_resolved)
            self._bucket(up & resolved & (delta[idx] > 0), tercile, self.mv_delay_hit)

    def _vol_spr(self, state_into, mid_half, stamp_a, valid, carry_n, global_base, series_n) -> None:
        i, j = self._pair(series_n, carry_n, 16)
        if i.size == 0:
            return
        gap = stamp_a[i] - stamp_a[i - 1]
        infer, tercile = self._event_mask(i, j, stamp_a, valid, global_base, 17)
        infer = infer & (gap > 0)
        abs_move = np.abs(mid_half[j] - mid_half[i]) * 0.005
        self._add_values(infer & (gap <= SHORT_GAP_MS), tercile, abs_move, self.vol_short_n, self.vol_short_sum, self.vol_short_sumsq)
        self._add_values(infer & (gap >= LONG_GAP_MS), tercile, abs_move, self.vol_long_n, self.vol_long_sum, self.vol_long_sumsq)
        self._add_values(infer & (gap <= SHORT_SENSITIVITY_MS), tercile, abs_move, self.vol_sens_short_n, self.vol_sens_short_sum)
        self._add_values(infer & (gap >= LONG_SENSITIVITY_MS), tercile, abs_move, self.vol_sens_long_n, self.vol_sens_long_sum)
        state = state_into[i - 1]
        self._add_values(infer & (state == 2), tercile, abs_move, self.spr_widen_n, self.spr_widen_sum, self.spr_widen_sumsq)
        self._add_values(infer & (state == 6), tercile, abs_move, self.spr_tight_n, self.spr_tight_sum, self.spr_tight_sumsq)
        delayed = self._pair(series_n, carry_n, 17)
        if delayed[0].size == 0:
            return
        base, end = delayed
        # Window from base+1 to end, which is 16 quotes after the quote following the signal.
        signal = base
        after = base + 1
        mask = (
            valid[signal]
            & valid[signal - 1]
            & valid[after]
            & valid[end]
            & (stamp_a[signal] < self.cutoff)
            & (stamp_a[after] < self.cutoff)
            & (stamp_a[end] < self.cutoff)
            & (((global_base + signal) % 17) == 0)
        )
        if not mask.any():
            return
        tercile_d = np.zeros(signal.shape[0], dtype=np.int8)
        tercile_d[mask] = np.clip(((stamp_a[signal[mask]] - self.time_min) * 3) // self.span, 0, 2)
        delayed_abs = np.abs(mid_half[end] - mid_half[after]) * 0.005
        state = state_into[signal - 1]
        self._add_values(mask & (state == 2), tercile_d, delayed_abs, self.spr_delay_widen_n, self.spr_delay_widen_sum)
        self._add_values(mask & (state == 6), tercile_d, delayed_abs, self.spr_delay_tight_n, self.spr_delay_tight_sum)

    def finish(self) -> dict[str, Any]:
        if self.open_len and self.open_sign != 0:
            _add_run(self.run_hist, self.open_len)
        if self.open_short_sign == 1:
            _add_run(self.short_gap_run_hist, self.open_short_len)
        self.open_len = 0
        self.open_short_len = 0
        independence, independence_tercile = self._stay_benchmark()
        measured = {
            "nonmonotonic": self.nonmonotonic,
            "H-QD-01": {
                "one_n": self.qd01_one_n.tolist(),
                "one_cont": self.qd01_one_cont.tolist(),
                "two_n": self.qd01_two_n.tolist(),
                "two_cont": self.qd01_two_cont.tolist(),
                "one_fade": self.qd01_one_fade.tolist(),
                "two_follow": self.qd01_two_follow.tolist(),
                "delay_one_n": self.qd01_delay_one_n.tolist(),
                "delay_one_cont": self.qd01_delay_one_cont.tolist(),
                "delay_two_n": self.qd01_delay_two_n.tolist(),
                "delay_two_cont": self.qd01_delay_two_cont.tolist(),
            },
            "H-QD-02": {
                "n": self.qd02_n.tolist(),
                "cont": self.qd02_cont.tolist(),
                "cur_up": self.qd02_cur_up.tolist(),
                "cur_down": self.qd02_cur_down.tolist(),
                "next_up": self.qd02_next_up.tolist(),
                "next_down": self.qd02_next_down.tolist(),
                "follow": self.qd02_follow.tolist(),
                "fade": self.qd02_fade.tolist(),
                "delay_n": self.qd02_delay_n.tolist(),
                "delay_cont": self.qd02_delay_cont.tolist(),
                "delay_cur_up": self.qd02_delay_cur_up.tolist(),
                "delay_cur_down": self.qd02_delay_cur_down.tolist(),
                "delay_next_up": self.qd02_delay_next_up.tolist(),
                "delay_next_down": self.qd02_delay_next_down.tolist(),
            },
            "H-INT-01": {
                "n": self.int_n.tolist(),
                "short": self.int_short.tolist(),
                "next_short": self.int_next_short.tolist(),
                "both": self.int_both.tolist(),
            },
            "H-SP-01": {
                "n": self.stay_n.tolist(),
                "hit": self.stay_hit.tolist(),
                "independence": independence,
                "independence_tercile": independence_tercile,
            },
            "H-MV-01": {
                "resolved": self.mv_resolved.tolist(),
                "censored": self.mv_censored.tolist(),
                "up_hit": self.mv_up_hit.tolist(),
                "residual": self.mv_residual.tolist(),
                "down_resolved": self.mv_down_resolved.tolist(),
                "down_hit": self.mv_down_hit.tolist(),
                "delay_resolved": self.mv_delay_resolved.tolist(),
                "delay_hit": self.mv_delay_hit.tolist(),
            },
            "H-VOL-01": {
                "short_n": self.vol_short_n.tolist(),
                "short_sum": self.vol_short_sum.tolist(),
                "short_sumsq": self.vol_short_sumsq.tolist(),
                "long_n": self.vol_long_n.tolist(),
                "long_sum": self.vol_long_sum.tolist(),
                "long_sumsq": self.vol_long_sumsq.tolist(),
                "sens_short_n": self.vol_sens_short_n.tolist(),
                "sens_short_sum": self.vol_sens_short_sum.tolist(),
                "sens_long_n": self.vol_sens_long_n.tolist(),
                "sens_long_sum": self.vol_sens_long_sum.tolist(),
            },
            "H-SPR-01": {
                "widen_n": self.spr_widen_n.tolist(),
                "widen_sum": self.spr_widen_sum.tolist(),
                "widen_sumsq": self.spr_widen_sumsq.tolist(),
                "tight_n": self.spr_tight_n.tolist(),
                "tight_sum": self.spr_tight_sum.tolist(),
                "tight_sumsq": self.spr_tight_sumsq.tolist(),
                "delay_widen_n": self.spr_delay_widen_n.tolist(),
                "delay_widen_sum": self.spr_delay_widen_sum.tolist(),
                "delay_tight_n": self.spr_delay_tight_n.tolist(),
                "delay_tight_sum": self.spr_delay_tight_sum.tolist(),
            },
        }
        return measured

    def _stay_benchmark(self) -> tuple[float | None, list[float | None]]:
        terciles = []
        pooled: dict[int, int] = {}
        for bucket in self.spread_marginal:
            total = sum(bucket.values())
            terciles.append(sum((count / total) ** 2 for count in bucket.values()) if total else None)
            for key, count in bucket.items():
                pooled[key] = pooled.get(key, 0) + count
        total = sum(pooled.values())
        overall = sum((count / total) ** 2 for count in pooled.values()) if total else None
        return overall, terciles


def _list3(values: np.ndarray) -> list[int]:
    return [int(v) for v in values.tolist()]


def scan_dataset(dataset_dir: Path) -> dict[str, Any]:
    dataset_dir = Path(dataset_dir)
    manifest = json.loads((dataset_dir / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    parts = manifest.get("parts") or []
    time_min: int | None = None
    time_max: int | None = None
    for part in parts:
        path = dataset_dir / "parts" / part["part"]
        if not path.exists():
            raise FileNotFoundError(f"ledgered part missing: {part['part']}")
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
    cutoff = discovery_cutoff(time_min, time_max)
    scan = DiscoveryScan(time_min, cutoff)
    for part in parts:
        print(f"microstructure {part['part']}", flush=True)
        parquet = pq.ParquetFile(dataset_dir / "parts" / part["part"])
        columns = [name for name in ("time_msc", "bid", "ask") if name in parquet.schema_arrow.names]
        for batch in parquet.iter_batches(batch_size=500_000, columns=columns):
            scan.add_batch(
                batch.column("bid").to_numpy(zero_copy_only=False),
                batch.column("ask").to_numpy(zero_copy_only=False),
                batch.column("time_msc").to_numpy(zero_copy_only=False),
            )
    measured = scan.finish()
    identity_ok = True
    if manifest.get("dataset_sha256") == PUBLISHED_DIGEST and (
        scan.rows != PUBLISHED_ROWS or cutoff != PUBLISHED_CUTOFF
    ):
        identity_ok = False
    verdicts = apply_verdicts(measured) if identity_ok else {
        hypothesis: {"id": hypothesis, "status": "INCONCLUSIVE", "reason": "archive identity did not match the verified inventory", "promoted": False}
        for hypothesis in FAMILY
    }
    mi = mutual_information(scan.transition_nonoverlap)
    entropy = outcome_entropy(scan.transition_nonoverlap)
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
            "module": "qts.research.xauusd_microstructure",
        },
        "timestamp_basis": timestamp_basis_assessment(manifest),
        "window": {
            "time_msc_min": time_min,
            "time_msc_max": time_max,
            "cutoff_time_msc": cutoff,
            "discovery_rows": scan.discovery_rows,
            "validation_rows_not_used_in_hypotheses": scan.validation_rows,
        },
        "identity_ok": identity_ok,
        "rows": scan.rows,
        "nonmonotonic": scan.nonmonotonic,
        "invalid_price_rows": scan.invalid_price_rows,
        "negative_spread_rows": scan.negative_spread_rows,
        "nonpositive_gaps": scan.nonpositive_gaps,
        "state_counts": {STATE_LABELS[i]: int(scan.state_counts[i]) for i in range(9)},
        "half_cent_counts": {
            "zero": int(scan.half_cent[0]),
            "one_half_cent": int(scan.half_cent[1]),
            "one_cent": int(scan.half_cent[2]),
            "larger": int(scan.half_cent[3]),
        },
        "bid_change_cents_histogram": [int(v) for v in scan.bid_magnitude.tolist()],
        "ask_change_cents_histogram": [int(v) for v in scan.ask_magnitude.tolist()],
        "gap_edges_ms": [int(v) for v in GAP_EDGES.tolist()],
        "gap_histogram": [int(v) for v in scan.gap_hist.tolist()],
        "run_length_histogram": [int(v) for v in scan.run_hist.tolist()],
        "short_gap_run_histogram": [int(v) for v in scan.short_gap_run_hist.tolist()],
        "transition_nonoverlap": scan.transition_nonoverlap.tolist(),
        "mutual_information_bits": mi,
        "next_state_entropy_bits": entropy,
        "information_gain_bits": None if mi is None or entropy is None else mi,
        "spread_curve": _curve(scan),
        "panel": _panel(scan),
        "measured": measured,
        "hypotheses": verdicts,
        "prior_hypotheses_not_reopened": {"H-MS-01": "REJECTED", "H-MS-02": "REJECTED", "H-TOD-01": "BLOCKED"},
        "edge_claim": "NOT ESTABLISHED",
        "strategy_promoted": False,
        "decision": "INCONCLUSIVE",
        "safety": {"confirm_live": False, "orders_submitted": 0, "DEMO_EXECUTION": "DISABLED"},
        "repairs_applied": [],
    }


def _curve(scan: DiscoveryScan) -> list[dict[str, Any]]:
    rows = []
    for cents in range(81):
        n1 = int(scan.spread_curve_n[0, cents])
        n16 = int(scan.spread_curve_n[1, cents])
        if not n1 and not n16:
            continue
        rows.append(
            {
                "spread_cents": cents if cents < 80 else "80+",
                "n_h1": n1,
                "mean_abs_h1": (float(scan.spread_curve_abs[0, cents] / n1) if n1 else None),
                "n_h16": n16,
                "mean_abs_h16": (float(scan.spread_curve_abs[1, cents] / n16) if n16 else None),
                "role": "EXPLORATORY",
            }
        )
    return rows


def _panel(scan: DiscoveryScan) -> list[dict[str, Any]]:
    rows = []
    for code, label in enumerate(STATE_LABELS):
        for h_index, horizon in enumerate(HORIZONS):
            n = int(scan.panel_n[1, code, h_index])
            n_all = int(scan.panel_n[0, code, h_index])
            rows.append(
                {
                    "state": label,
                    "horizon_quotes": horizon,
                    "inferential_n": n,
                    "dependent_n": n_all,
                    "mean_abs": (float(scan.panel_abs[1, code, h_index] / n) if n else None),
                    "mean_signed_in_implied_direction": (float(scan.panel_signed[1, code, h_index] / n) if n else None),
                    "continuation_rate": (float(scan.panel_cont[1, code, h_index] / n) if n else None),
                    "role": "EXPLORATORY",
                }
            )
    return rows


def render_microstructure(report: dict[str, Any]) -> str:
    lines = [
        "# XAUUSD microstructure research state",
        "",
        f"Decision: {report.get('decision')}",
        "",
        "No strategy was promoted. Exploratory cells are not confirmatory. The locked span was not used to choose a test.",
        "",
        "## CLOCK",
        "",
        f"- Status: {(report.get('timestamp_basis') or {}).get('status')}",
        f"- {(report.get('timestamp_basis') or {}).get('evidence')}",
        "",
        "## HYPOTHESES",
        "",
    ]
    for hypothesis in FAMILY:
        verdict = (report.get("hypotheses") or {}).get(hypothesis) or {}
        lines.append(f"- {hypothesis}: {verdict.get('status')} — {verdict.get('reason')}")
    lines.extend(
        [
            "",
            "## DESCRIPTIVE",
            "",
            f"- Rows: {report.get('rows')}",
            f"- Discovery rows: {(report.get('window') or {}).get('discovery_rows')}",
            f"- Mutual information of the next quote state, bits: {report.get('mutual_information_bits')}",
            f"- Half-cent composition: {report.get('half_cent_counts')}",
            f"- State counts: {report.get('state_counts')}",
            "",
            "Edge claim: NOT ESTABLISHED",
            "Orders submitted: 0",
            "",
        ]
    )
    return "\n".join(lines)


def write_report(report: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
