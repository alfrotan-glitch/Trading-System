"""Impulse event-study analysis — detection, measurement, baseline comparison,
multiplicity correction, cost/latency/spread sensitivity, regime conditioning,
placebo controls, and research-ledger recording.

Scientific rules enforced here
------------------------------
* The LOCKED test partition is never measured (only discovery + validation).
* Every (family, horizon, split) trial is recorded in the ExperimentStore
  ledger — including rejected ones. Nothing is silently discarded.
* Multiplicity: Holm-Bonferroni across the 10 pre-registered families per
  (horizon, split); the deflated Sharpe ratio additionally penalizes with the
  FULL ledger trial count (research memory is cumulative and never reset).
* Baseline: non-event bars outside every event's measurement window, with
  seeded random directions, measured with identical parameters.
* Placebo: seeded random-timing events (same count as real events) measured
  identically; the observed continuation advantage is compared against the
  placebo distribution (empirical one-sided p-value).
* Costs: declared assumptions only (see costs.py); sensitivity sweeps over
  cost/spread multipliers and entry latency are part of every evidence file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from scipy import stats as sps

from qts.domain.value_objects import Bar
from qts.research.impulse.costs import (
    BASE_COSTS,
    COST_MULTIPLIERS,
    LATENCY_BARS,
    SPREAD_MULTIPLIERS,
    CostAssumptions,
)
from qts.research.impulse.definitions import (
    ALL_HORIZONS_BARS,
    PRE_REGISTERED_FAMILIES,
    PRIMARY_HORIZON_BARS,
    WARMUP_BARS,
    detect_events,
)
from qts.research.impulse.measurement import (
    EventMeasurement,
    MeasurementParams,
    causal_vol_regime_labels,
    measure_event,
)
from qts.research.impulse.statistics import (
    binomial_test_vs_baseline,
    bootstrap_ci_mean,
    event_series_sharpe,
    holm_bonferroni,
    two_proportion_diff_ci,
)

SIGNIFICANCE_ALPHA = 0.05


@dataclass(frozen=True)
class ImpulseResearchConfig:
    seed: int = 42
    costs: CostAssumptions = BASE_COSTS
    n_boot: int = 2000
    discovery_ratio: float = 0.6
    validation_ratio: float = 0.2
    horizons: tuple[int, ...] = ALL_HORIZONS_BARS
    primary_horizon: int = PRIMARY_HORIZON_BARS


@dataclass
class FamilyHorizonSplitResult:
    family_id: str
    horizon: int
    split: str  # discovery | validation | pooled
    direction_mix: dict[str, int] = field(default_factory=dict)
    n_detected: int = 0
    n_measured: int = 0
    n_excluded_insufficient_forward: int = 0
    continuation_k: int = 0
    continuation_rate: float = 0.0
    reversal_rate: float = 0.0
    baseline_n: int = 0
    baseline_continuation_rate: float = 0.0
    p_raw: float = 1.0
    p_holm: float = 1.0  # filled in per (horizon, split) across families
    diff_vs_baseline: float = 0.0
    diff_ci: tuple[float, float] = (0.0, 0.0)
    placebo_p_one_sided: float = 1.0
    gross_mean_bps: float = 0.0
    net_mean_bps: float = 0.0
    net_ci: tuple[float, float] = (0.0, 0.0)
    trade_outcomes: dict[str, Any] = field(default_factory=dict)
    net_sharpe_per_event: float = 0.0
    dsr_per_event: float | None = None  # pooled discovery+validation only
    mfe_mean_bps: float = 0.0
    mae_mean_bps: float = 0.0
    race_counts: dict[str, int] = field(default_factory=dict)
    target_hit_rate: float = 0.0
    time_to_target_mean_bars: float | None = None  # among hits; censored excluded
    time_to_target_censored_rate: float = 0.0
    duration_mean_bars: float = 0.0
    regime_breakdown: dict[str, dict[str, float]] = field(default_factory=dict)
    long_net_mean_bps: float | None = None
    short_net_mean_bps: float | None = None
    events: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        d = self.__dict__.copy()
        d["net_ci"] = list(self.net_ci)
        d["diff_ci"] = list(self.diff_ci)
        return d


@dataclass
class ImpulseAnalysisResult:
    data_version: str
    provenance: dict[str, Any]
    config_snapshot: dict[str, Any]
    split_boundaries: dict[str, int]
    locked_untouched: bool
    regime_labels_available: int
    results: list[FamilyHorizonSplitResult]
    sensitivity: dict[str, Any]
    ledger: dict[str, Any]
    totals: dict[str, Any]

    def primary_results(self) -> list[FamilyHorizonSplitResult]:
        return [r for r in self.results if r.horizon == self.config_snapshot["primary_horizon"] and r.split == "pooled"]

    def as_dict(self) -> dict[str, Any]:
        return {
            "data_version": self.data_version,
            "provenance": self.provenance,
            "config_snapshot": self.config_snapshot,
            "split_boundaries": self.split_boundaries,
            "locked_untouched": self.locked_untouched,
            "regime_labels_available": self.regime_labels_available,
            "results": [r.as_dict() for r in self.results],
            "sensitivity": self.sensitivity,
            "ledger": self.ledger,
            "totals": self.totals,
        }


def _eligible_indices(n: int, horizon: int, latency: int) -> set[int]:
    """Indices with enough forward bars to measure a (horizon, latency) path."""
    return set(range(WARMUP_BARS, n - (latency + horizon)))


def _measure_all(
    bars: list[Bar],
    indices_directions: list[tuple[int, str]],
    family_id: str,
    params: MeasurementParams,
    cost_bps: float,
    regime_labels: list[str],
) -> list[EventMeasurement]:
    return [
        measure_event(
            bars,
            i,
            d,
            family_id,
            params,
            cost_bps,
            regime_label=regime_labels[i],
        )
        for i, d in indices_directions
    ]


def summarize_trade_outcomes(
    net_returns_bps: list[float | None],
    *,
    declared_round_turn_cost_bps: float | None = None,
) -> dict[str, Any]:
    """Summarize the canonical measured event outcomes for human reporting.

    The impulse study does not contain executed broker trades or fills. Its
    canonical unit is one measured directional outcome for one family-scoped
    detected event at one horizon. ``net_returns_bps`` is therefore the
    existing event-level outcome data, already calculated by
    :func:`measure_event` as gross horizon return minus the declared cost.

    A missing return is never interpreted as zero. In that case the event
    count remains visible, while all outcome metrics that require a complete
    return series are explicitly unavailable.
    """
    measured_count = len(net_returns_bps)
    missing = 0
    values: list[float] = []
    for value in net_returns_bps:
        if value is None:
            missing += 1
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            missing += 1
            continue
        if not np.isfinite(numeric):
            missing += 1
            continue
        values.append(numeric)

    base: dict[str, Any] = {
        "unit": "measured_directional_event_outcome",
        "return_basis": "net_return_bps",
        "winner_definition": "net_return_bps > 0",
        "loser_definition": "net_return_bps < 0",
        "breakeven_definition": "net_return_bps == 0",
        "measured_event_count": measured_count,
        "declared_round_turn_cost_bps": declared_round_turn_cost_bps,
    }
    if missing or not values:
        base.update(
            {
                "status": "UNAVAILABLE",
                "outcome_count": 0 if not net_returns_bps else None,
                "wins": None if missing or net_returns_bps else 0,
                "losses": None if missing or net_returns_bps else 0,
                "breakeven": None if missing or net_returns_bps else 0,
                "win_rate": None,
                "average_winner_bps": None,
                "average_loser_bps": None,
                "profit_factor": None,
                "expectancy_per_trade_bps": None,
                "net_result_bps": None,
                "unavailable_reason": (
                    "no measured event outcomes"
                    if not net_returns_bps
                    else f"net return unavailable for {missing} measured event(s)"
                ),
            }
        )
        return base

    winners = [value for value in values if value > 0]
    losers = [value for value in values if value < 0]
    breakeven = [value for value in values if value == 0]
    gross_wins = sum(winners)
    gross_losses = abs(sum(losers))
    base.update(
        {
            "status": "AVAILABLE",
            "outcome_count": len(values),
            "wins": len(winners),
            "losses": len(losers),
            "breakeven": len(breakeven),
            "win_rate": len(winners) / len(values),
            "average_winner_bps": float(np.mean(winners)) if winners else None,
            "average_loser_bps": float(np.mean(losers)) if losers else None,
            # Profit factor is undefined when there is no loss denominator;
            # do not emit infinity or turn that case into zero.
            "profit_factor": (gross_wins / gross_losses) if gross_losses > 0 else None,
            "expectancy_per_trade_bps": float(np.mean(values)),
            "net_result_bps": float(sum(values)),
            "unavailable_reason": None,
        }
    )
    return base


def _summarize(
    measured: list[EventMeasurement],
    baseline_measured: list[EventMeasurement],
    placebo_diffs: list[float],
    cfg: ImpulseResearchConfig,
) -> dict[str, Any]:
    ok = [m for m in measured if m.decision_state == "DETECTED_MEASURED"]
    ok_base = [m for m in baseline_measured if m.decision_state == "DETECTED_MEASURED"]
    n = len(ok)
    k = sum(1 for m in ok if m.continuation)
    base_n = len(ok_base)
    base_k = sum(1 for m in ok_base if m.continuation)
    base_rate = base_k / base_n if base_n else 0.5
    gross = [float(m.horizon_return_bps or 0.0) for m in ok]
    net = [float(m.net_return_bps or 0.0) for m in ok]
    trade_outcomes = summarize_trade_outcomes(
        [m.net_return_bps for m in ok],
        declared_round_turn_cost_bps=cfg.costs.round_turn_cost_bps(),
    )
    net_mean, net_lo, net_hi = bootstrap_ci_mean(net, n_boot=cfg.n_boot, seed=cfg.seed)
    diff, diff_lo, diff_hi = two_proportion_diff_ci(k, n, base_k, base_n, seed=cfg.seed, n_boot=cfg.n_boot)
    obs_diff = (k / n - base_rate) if n else 0.0
    placebo_p = float(np.mean([1.0 if pd >= obs_diff else 0.0 for pd in placebo_diffs])) if placebo_diffs else 1.0
    longs = [float(m.net_return_bps or 0.0) for m in ok if m.direction == "LONG"]
    shorts = [float(m.net_return_bps or 0.0) for m in ok if m.direction == "SHORT"]
    ttt_hits = [m.time_to_target_bars for m in ok if m.time_to_target_bars is not None]
    races: dict[str, int] = {}
    for m in ok:
        if m.race_outcome is not None:
            races[str(m.race_outcome)] = races.get(str(m.race_outcome), 0) + 1
    regimes: dict[str, dict[str, float]] = {}
    for label in ("LOW", "MID", "HIGH", "UNKNOWN"):
        sub = [m for m in ok if m.regime_label == label]
        if not sub:
            continue
        sub_net = [float(m.net_return_bps or 0.0) for m in sub]
        sub_cont = sum(1 for m in sub if m.continuation)
        regimes[label] = {
            "n": float(len(sub)),
            "net_mean_bps": float(np.mean(sub_net)),
            "continuation_rate": sub_cont / len(sub),
        }
    return {
        "direction_mix": {
            "LONG": sum(1 for m in measured if m.direction == "LONG"),
            "SHORT": sum(1 for m in measured if m.direction == "SHORT"),
        },
        "n_detected": len(measured),
        "n_measured": n,
        "n_excluded_insufficient_forward": sum(1 for m in measured if m.decision_state == "DETECTED_EXCLUDED"),
        "continuation_k": k,
        "continuation_rate": k / n if n else 0.0,
        "reversal_rate": (sum(1 for m in ok if m.reversal) / n) if n else 0.0,
        "baseline_n": base_n,
        "baseline_continuation_rate": base_rate,
        "p_raw": binomial_test_vs_baseline(k, n, base_rate),
        "diff_vs_baseline": diff,
        "diff_ci": (diff_lo, diff_hi),
        "placebo_p_one_sided": placebo_p,
        "gross_mean_bps": float(np.mean(gross)) if gross else 0.0,
        "net_mean_bps": net_mean,
        "net_ci": (net_lo, net_hi),
        "trade_outcomes": trade_outcomes,
        "net_sharpe_per_event": event_series_sharpe(net),
        "mfe_mean_bps": float(np.mean([float(m.mfe_bps or 0.0) for m in ok])) if ok else 0.0,
        "mae_mean_bps": float(np.mean([float(m.mae_bps or 0.0) for m in ok])) if ok else 0.0,
        "race_counts": races,
        "target_hit_rate": (races.get("TARGET", 0) / n) if n else 0.0,
        "time_to_target_mean_bars": float(np.mean(ttt_hits)) if ttt_hits else None,
        "time_to_target_censored_rate": ((n - len(ttt_hits)) / n) if n else 0.0,
        "duration_mean_bars": float(np.mean([float(m.duration_bars or 0.0) for m in ok])) if ok else 0.0,
        "regime_breakdown": regimes,
        "long_net_mean_bps": float(np.mean(longs)) if longs else None,
        "short_net_mean_bps": float(np.mean(shorts)) if shorts else None,
        "_gross_values": gross,
        "_net_values": net,
    }


def run_impulse_analysis(
    bars: list[Bar],
    data_version: str,
    provenance: dict[str, Any],
    cfg: ImpulseResearchConfig | None = None,
    ledger_db_path: Path | str | None = None,
    data_root_db_path: Path | str | None = None,
) -> ImpulseAnalysisResult:
    """Run the complete pre-registered impulse event study.

    ``ledger_db_path``: SQLite path for the ExperimentStore trial ledger.
    ``data_root_db_path``: SQLite path for the LockedTestPartitioner registry.
    Both should point at tmp databases in tests and at the repo database in
    CLI research runs (the ledger is cumulative and never reset).
    """
    cfg = cfg or ImpulseResearchConfig()
    bars = sorted(bars, key=lambda b: b.open_time)
    n = len(bars)
    if n <= WARMUP_BARS + cfg.primary_horizon + cfg.costs.latency_bars + 2:
        raise ValueError(
            f"series too short for impulse research: {n} bars "
            f"(need > {WARMUP_BARS + cfg.primary_horizon + cfg.costs.latency_bars + 2})"
        )

    # --- chronological partitions via the existing locked-test machinery ----
    from qts.data.locked_test import LockedTestPartitioner

    partitioner = LockedTestPartitioner(db_path=data_root_db_path or "data/sqlite/qts.db")
    parts = partitioner.partition(bars, data_version, cfg.discovery_ratio, cfg.validation_ratio)
    d_end = len(parts["discovery"])
    v_end = d_end + len(parts["validation"])
    # The locked partition is NEVER measured by this research layer.
    split_of = ["discovery"] * d_end + ["validation"] * (v_end - d_end) + ["locked"] * (n - v_end)

    regime_labels = causal_vol_regime_labels(bars)
    rng = np.random.default_rng(cfg.seed)

    results: list[FamilyHorizonSplitResult] = []
    gross_by_family_primary: dict[str, list[float]] = {}
    net_by_family_primary: dict[str, list[float]] = {}
    totals: dict[str, Any] = {
        "bars": n,
        "families": len(PRE_REGISTERED_FAMILIES),
        "horizons": list(cfg.horizons),
        "primary_horizon": cfg.primary_horizon,
        "trials_recorded": 0,
        "events_detected_total": 0,
        "events_measured_total": 0,
        "events_excluded_total": 0,
        "events_locked_discarded": 0,
        "event_unit": "family-scoped detected impulse event; not an executed broker trade",
        "outcome_unit": "one measured directional event outcome per family and horizon",
        "events_detected_total_scope": "sum across pre-registered families; not de-duplicated across family definitions",
        "events_measured_total_scope": "sum across pre-registered families and configured horizons",
    }

    family_events_all: dict[str, list[tuple[int, str]]] = {}
    for fam in PRE_REGISTERED_FAMILIES:
        evs = detect_events(bars, fam)
        # discard events detected inside the locked partition (never measured)
        usable = [(i, d) for (i, d) in evs if split_of[i] != "locked"]
        totals["events_locked_discarded"] += len(evs) - len(usable)
        family_events_all[fam.family_id] = usable

    # occupied windows per family (for baseline exclusion), per horizon
    for fam in PRE_REGISTERED_FAMILIES:
        evs = family_events_all[fam.family_id]
        totals["events_detected_total"] += len(evs)
        for horizon in cfg.horizons:
            params = MeasurementParams(horizon_bars=horizon, latency_bars=cfg.costs.latency_bars)
            cost_bps = cfg.costs.round_turn_cost_bps()
            measured_all = _measure_all(bars, evs, fam.family_id, params, cost_bps, regime_labels)
            # ---- baseline + placebo pools (family- and horizon-specific) ----
            occupied: set[int] = set()
            for i, _d in evs:
                occupied.update(range(i, i + cfg.costs.latency_bars + horizon + 1))
            pool = sorted(_eligible_indices(n, horizon, cfg.costs.latency_bars) - occupied)
            pool = [i for i in pool if split_of[i] != "locked"]
            base_dirs = [(i, "LONG" if rng.random() < 0.5 else "SHORT") for i in pool]
            baseline_measured_all = _measure_all(bars, base_dirs, "BASELINE", params, cost_bps, regime_labels)
            n_measured_fam = sum(1 for m in measured_all if m.decision_state == "DETECTED_MEASURED")
            placebo_draws = 200
            placebo_diffs: list[float] = []
            if pool and n_measured_fam > 0:
                for _ in range(placebo_draws):
                    sel = rng.choice(len(pool), size=min(n_measured_fam, len(pool)), replace=False)
                    placebo_pairs = [(pool[j], "LONG" if rng.random() < 0.5 else "SHORT") for j in sel]
                    pm = _measure_all(bars, placebo_pairs, "PLACEBO", params, cost_bps, regime_labels)
                    pm_ok = [m for m in pm if m.decision_state == "DETECTED_MEASURED"]
                    b_ok = [m for m in baseline_measured_all if m.decision_state == "DETECTED_MEASURED"]
                    if pm_ok and b_ok:
                        placebo_diffs.append(
                            sum(1 for m in pm_ok if m.continuation) / len(pm_ok)
                            - sum(1 for m in b_ok if m.continuation) / len(b_ok)
                        )

            # ---- per-split + pooled summaries -------------------------------
            for split in ("discovery", "validation", "pooled"):
                if split == "pooled":
                    sel_m = measured_all
                    sel_b = baseline_measured_all
                else:
                    sel_m = [m for m in measured_all if split_of[m.detection_index] == split]
                    sel_b = [m for m in baseline_measured_all if split_of[m.detection_index] == split]
                summary = _summarize(sel_m, sel_b, placebo_diffs, cfg)
                gross_vals = summary.pop("_gross_values")
                net_vals = summary.pop("_net_values")
                if split == "pooled" and horizon == cfg.primary_horizon:
                    gross_by_family_primary[fam.family_id] = gross_vals
                    net_by_family_primary[fam.family_id] = net_vals
                res = FamilyHorizonSplitResult(
                    family_id=fam.family_id,
                    horizon=horizon,
                    split=split,
                    **summary,
                )
                if split == "pooled":
                    res.events = [
                        {
                            "detection_index": m.detection_index,
                            "detection_time": m.detection_time.isoformat(),
                            "direction": m.direction,
                            "decision_state": m.decision_state,
                            "exclusion": str(m.exclusion),
                            "race_outcome": str(m.race_outcome) if m.race_outcome else None,
                            "horizon_return_bps": m.horizon_return_bps,
                            "net_return_bps": m.net_return_bps,
                            "split": split_of[m.detection_index],
                        }
                        for m in measured_all
                    ]
                    totals["events_measured_total"] += res.n_measured
                    totals["events_excluded_total"] += res.n_excluded_insufficient_forward
                results.append(res)

    # Make the two denominators explicit. ``events_measured_total`` includes
    # every configured horizon, while the report's primary outcome count is
    # the pooled primary-horizon total. Neither aggregate is a broker-trade
    # count or a de-duplicated count across different hypothesis families.
    primary_pooled = [r for r in results if r.horizon == cfg.primary_horizon and r.split == "pooled"]
    totals["primary_events_detected_total"] = sum(r.n_detected for r in primary_pooled)
    totals["primary_outcomes_measured_total"] = sum(r.n_measured for r in primary_pooled)
    totals["all_horizon_outcomes_measured_total"] = totals["events_measured_total"]

    # --- Holm correction per (horizon, split) across families ---------------
    for horizon in cfg.horizons:
        for split in ("discovery", "validation", "pooled"):
            group = [r for r in results if r.horizon == horizon and r.split == split]
            adjusted = holm_bonferroni([r.p_raw for r in group])
            for r, adj in zip(group, adjusted, strict=True):
                r.p_holm = adj

    # --- sensitivity sweeps (pooled, primary horizon) -----------------------
    sensitivity: dict[str, Any] = {"cost_multiplier": {}, "spread_multiplier": {}, "latency_bars": {}}
    for fam in PRE_REGISTERED_FAMILIES:
        fid = fam.family_id
        gross = gross_by_family_primary.get(fid, [])
        cm: dict[str, float] = {}
        for mult in COST_MULTIPLIERS:
            c = cfg.costs.with_cost_multiplier(mult).round_turn_cost_bps()
            cm[f"{mult}x"] = float(np.mean([g - c for g in gross])) if gross else 0.0
        sensitivity["cost_multiplier"][fid] = cm
        sm: dict[str, float] = {}
        for mult in SPREAD_MULTIPLIERS:
            c = cfg.costs.with_spread_multiplier(mult).round_turn_cost_bps()
            sm[f"{mult}x"] = float(np.mean([g - c for g in gross])) if gross else 0.0
        sensitivity["spread_multiplier"][fid] = sm
        lm: dict[str, float] = {}
        evs = family_events_all[fid]
        for lat in LATENCY_BARS:
            params = MeasurementParams(horizon_bars=cfg.primary_horizon, latency_bars=lat)
            mm = _measure_all(bars, evs, fid, params, cfg.costs.round_turn_cost_bps(), regime_labels)
            vals = [float(m.net_return_bps or 0.0) for m in mm if m.decision_state == "DETECTED_MEASURED"]
            lm[f"{lat}"] = float(np.mean(vals)) if vals else 0.0
        sensitivity["latency_bars"][fid] = lm

    # --- ledger recording (every trial, including rejected) -----------------
    ledger_info: dict[str, Any] = {"recorded": 0, "ledger_trials_total": None}
    if ledger_db_path is not None:
        from qts.research.experiment import Experiment, ExperimentStore, Hypothesis

        store = ExperimentStore(db_path=ledger_db_path)
        hyp = Hypothesis(
            statement=(
                "Real-time market impulses (unusually strong directional moves detected "
                "causally) exhibit short-horizon continuation with positive net expectancy "
                "after declared spread, commission, slippage, and latency costs, beyond the "
                "non-impulse baseline."
            ),
            rationale="Pre-registered event-study research capability; not a trading strategy.",
            falsifiability=(
                "Rejected when, after Holm correction across all pre-registered families, no "
                "family shows continuation above baseline AND positive net expectancy CI in "
                "BOTH discovery and validation partitions."
            ),
            created_by="impulse_research",
        )
        store.put_hypothesis(hyp)
        recorded = 0
        for r in results:
            if r.split == "pooled":
                continue  # trials are the per-split tests; pooled is a summary view
            exp = Experiment(
                hypothesis_id=hyp.id,
                strategy_id=f"impulse_research:{r.family_id}",
                params={
                    "horizon": r.horizon,
                    "split": r.split,
                    "family": r.family_id,
                    "seed": cfg.seed,
                },
                data_version=data_version,
                seed=cfg.seed,
                status="CREATED",
            )
            store.put(exp)
            recorded += 1
            significant = r.p_holm < SIGNIFICANCE_ALPHA and r.net_ci[0] > 0
            if significant:
                exp.status = "CONFIRMED"
                store.put(exp)
            else:
                store.reject(
                    exp.id,
                    reason=(
                        f"no corrected significance or non-positive net CI "
                        f"(p_holm={r.p_holm:.4f}, net_ci=[{r.net_ci[0]:.2f},{r.net_ci[1]:.2f}]bps)"
                    ),
                )
        ledger_info["recorded"] = recorded
        ledger_info["hypothesis_id"] = hyp.id
        ledger_info["ledger_trials_total"] = store.count_trials()
        totals["trials_recorded"] = recorded

    # --- DSR penalized by the FULL cumulative ledger ------------------------
    num_trials_for_dsr = int(
        ledger_info.get("ledger_trials_total")
        or max(totals["trials_recorded"], len(PRE_REGISTERED_FAMILIES) * len(cfg.horizons))
    )
    from qts.validation.metrics import deflated_sharpe_ratio

    for r in results:
        if r.split == "pooled" and r.horizon == cfg.primary_horizon:
            net_vals = net_by_family_primary.get(r.family_id, [])
            if len(net_vals) >= 3:
                arr = np.asarray(net_vals)
                skew = float(sps.skew(arr))
                kurt = float(sps.kurtosis(arr, fisher=False))
                r.dsr_per_event = deflated_sharpe_ratio(
                    observed_sr=r.net_sharpe_per_event,
                    num_trials=max(num_trials_for_dsr, 1),
                    n=len(net_vals),
                    skewness=skew,
                    kurtosis=kurt,
                    annualized=False,
                )

    totals["num_trials_for_dsr"] = num_trials_for_dsr

    return ImpulseAnalysisResult(
        data_version=data_version,
        provenance=provenance,
        config_snapshot={
            "seed": cfg.seed,
            "horizons": list(cfg.horizons),
            "primary_horizon": cfg.primary_horizon,
            "costs": cfg.costs.as_dict(),
            "n_boot": cfg.n_boot,
            "discovery_ratio": cfg.discovery_ratio,
            "validation_ratio": cfg.validation_ratio,
            "warmup_bars": WARMUP_BARS,
            "alpha": SIGNIFICANCE_ALPHA,
            "pre_registered_families": [
                {"family_id": f.family_id, "definition": f.definition, "params": f.params, "role": f.role}
                for f in PRE_REGISTERED_FAMILIES
            ],
        },
        split_boundaries={"discovery_end": d_end, "validation_end": v_end, "total": n},
        locked_untouched=True,
        regime_labels_available=sum(1 for x in regime_labels if x != "UNKNOWN"),
        results=results,
        sensitivity=sensitivity,
        ledger=ledger_info,
        totals=totals,
    )
