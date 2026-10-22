"""Causal volatility-conditioned discovery on a preserved XAUUSD M15 export.

This is a bounded research assay, not a strategy engine.  It tests a
predeclared family that is materially different from the existing unconditional
trend, reversal, breakout, session, impulse, and macro studies: directional
signals are allowed only when range and broker tick-volume state agrees with
the mechanism.  No parameter is selected from the output.

The assay uses completed-bar signals and next-observed-bar execution.  Missing
15-minute intervals are hard boundaries; no return across a gap is credited.
The raw ``spread`` field remains provenance only because its point value is not
verified.  All price-distance costs are explicit assumptions.  The result can
never register, promote, authorize, or submit an order.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from qts.research.xauusd_mt5_broker_bars import (
    EXPECTED_BAR_SECONDS,
    _summary,
    load_broker_bars,
    sha256_file,
)

SCHEMA = "qts.xauusd_conditioned_m15_discovery.v1"
DEFAULT_INPUT = Path("data/raw/mt5_xauusd_m15_30000.csv")
ASSUMED_ONE_SIDE_PRICE_COSTS = (0.0, 0.15, 0.30, 0.50)
HYPOTHESES: dict[str, dict[str, Any]] = {
    "H-VOL-EXP-MOM-4": {
        "family": "range_and_tick_volume_expansion_momentum",
        "hold_bars": 4,
        "definition": "current body direction after 1.5x prior 32-bar range median and 1.5x prior 32-bar tick-volume median",
    },
    "H-VOL-EXP-FADE-4": {
        "family": "range_and_tick_volume_expansion_reversal",
        "hold_bars": 4,
        "definition": "fade the same fixed range-and-tick-volume expansion event for 4 bars",
    },
    "H-VOL-COMP-BREAK-8": {
        "family": "compressed_range_breakout",
        "hold_bars": 8,
        "definition": "prior 32-bar range median below its trailing 256-bar median, then close breaks the prior 32-bar high or low",
    },
    "H-VOL-QUIET-DRIFT-16": {
        "family": "low_range_trend_conditioning",
        "hold_bars": 16,
        "definition": "sign of the prior 96-bar return only while prior 32-bar range median is below its trailing 256-bar median",
    },
}


def _causal_features(frame: pd.DataFrame) -> dict[str, pd.Series]:
    """Return backward-looking features; the current close is only used for a signal."""
    close = frame["close"]
    bar_range = (frame["high"] - frame["low"]) / close
    tick_volume = pd.to_numeric(frame["tick_volume"], errors="raise")
    prior_range_median = bar_range.shift(1).rolling(32, min_periods=32).median()
    prior_volume_median = tick_volume.shift(1).rolling(32, min_periods=32).median()
    trailing_range_median = prior_range_median.shift(1).rolling(256, min_periods=128).median()
    prior_high = frame["high"].shift(1).rolling(32, min_periods=32).max()
    prior_low = frame["low"].shift(1).rolling(32, min_periods=32).min()
    expansion = (bar_range >= 1.5 * prior_range_median) & (tick_volume >= 1.5 * prior_volume_median)
    bar_direction = np.sign(close / frame["open"] - 1.0)
    breakout_direction = pd.Series(0.0, index=frame.index)
    breakout_direction[close > prior_high] = 1.0
    breakout_direction[close < prior_low] = -1.0
    quiet = prior_range_median < trailing_range_median
    # Build the slow direction from observed intrabar returns only.  A direct
    # close-to-close lookback would silently include an untradeable maintenance
    # gap; execution still treats every gap as a hard boundary.
    observed_log_return = pd.Series(np.log(close / frame["open"]), index=frame.index)
    trend_direction = np.sign(observed_log_return.rolling(96, min_periods=96).sum())
    return {
        "expansion": expansion,
        "bar_direction": bar_direction.astype(float),
        "breakout_direction": breakout_direction,
        "quiet": quiet,
        "trend_direction": trend_direction.astype(float),
        "available_32": prior_range_median.notna() & prior_volume_median.notna(),
        "available_96": trend_direction.notna(),
        "available_256": trailing_range_median.notna(),
    }


def hypothesis_signals(frame: pd.DataFrame) -> dict[str, pd.Series]:
    """Compute the four fixed signals at completed-bar close."""
    if "tick_volume" not in frame:
        raise ValueError("conditioned M15 assay requires tick_volume")
    features = _causal_features(frame)
    expansion = features["expansion"] & features["available_32"]
    breakout = features["breakout_direction"].where(features["available_32"], 0.0)
    quiet_drift = features["trend_direction"].where(features["available_96"] & features["available_256"], 0.0)
    return {
        "H-VOL-EXP-MOM-4": features["bar_direction"].where(expansion, 0.0).fillna(0.0),
        "H-VOL-EXP-FADE-4": (-features["bar_direction"]).where(expansion, 0.0).fillna(0.0),
        "H-VOL-COMP-BREAK-8": breakout.fillna(0.0),
        "H-VOL-QUIET-DRIFT-16": quiet_drift.fillna(0.0),
    }


def execution_position(frame: pd.DataFrame, signal: pd.Series, hold_bars: int) -> pd.Series:
    """Schedule a fixed-hold position one observed bar after each signal."""
    if hold_bars <= 0:
        raise ValueError("hold_bars must be positive")
    index = pd.DatetimeIndex(frame.index)
    contiguous = index.to_series().diff().dt.total_seconds().eq(EXPECTED_BAR_SECONDS).to_numpy()
    position = np.zeros(len(frame), dtype=float)
    current = 0.0
    remaining = 0
    values = signal.to_numpy(dtype=float)
    for idx in range(len(frame)):
        if idx > 0 and not contiguous[idx]:
            current = 0.0
            remaining = 0
        position[idx] = current
        if current != 0.0:
            remaining -= 1
            if remaining <= 0:
                current = 0.0
        if current == 0.0 and idx + 1 < len(frame) and contiguous[idx + 1] and values[idx] != 0.0:
            current = float(values[idx])
            remaining = hold_bars
    return pd.Series(position, index=frame.index)


def evaluate_hypothesis(
    frame: pd.DataFrame,
    signal: pd.Series,
    hold_bars: int,
    start: int,
    end: int,
    one_side_price_cost: float,
) -> dict[str, Any]:
    """Evaluate one fixed signal against a split using daily active returns."""
    position = execution_position(frame, signal, hold_bars)
    index = pd.DatetimeIndex(frame.index)
    contiguous = index.to_series().diff().dt.total_seconds().eq(EXPECTED_BAR_SECONDS)
    delta = position.diff().fillna(position.abs()).abs()
    intrabar = frame["close"] / frame["open"] - 1.0
    gross = position * intrabar
    costs = delta * float(one_side_price_cost) / frame["open"]
    net = gross - costs
    exposure = float(position.iloc[start:end].abs().mean()) if end > start else 0.0
    control_position = pd.Series(exposure, index=frame.index).where(contiguous, 0.0)
    control_delta = control_position.diff().fillna(control_position.abs()).abs()
    control = control_position * intrabar - control_delta * float(one_side_price_cost) / frame["open"]
    result = _summary(net.iloc[start:end], net.iloc[start:end], control.iloc[start:end], position.iloc[start:end])
    result.update(
        {
            "gross": _summary(
                gross.iloc[start:end],
                gross.iloc[start:end],
                (control_position * intrabar).iloc[start:end],
                position.iloc[start:end],
            ),
            "hold_bars": hold_bars,
            "one_side_price_cost": float(one_side_price_cost),
            "cost_basis": "ASSUMED_PRICE_DISTANCE_PER_SIDE; not broker-measured",
            "start_timestamp": index[start].isoformat() if start < len(frame) else None,
            "end_timestamp": index[end - 1].isoformat() if end > start else None,
        }
    )
    return result


def run_discovery(path: Path = DEFAULT_INPUT) -> dict[str, Any]:
    """Run the preregistered conditioned-volatility assay."""
    frame = load_broker_bars(path)
    signals = hypothesis_signals(frame)
    n = len(frame)
    cuts = (0, int(n * 0.60), int(n * 0.80), n)
    split_names = ("DISCOVERY_60", "VALIDATION_20", "HOLDOUT_20")
    hypotheses: dict[str, Any] = {}
    for hypothesis, metadata in HYPOTHESES.items():
        signal = signals[hypothesis]
        hypotheses[hypothesis] = {
            "definition": metadata,
            "splits": {
                name: {
                    f"cost_{cost:.2f}": evaluate_hypothesis(
                        frame, signal, int(metadata["hold_bars"]), cuts[idx], cuts[idx + 1], cost
                    )
                    for cost in ASSUMED_ONE_SIDE_PRICE_COSTS
                }
                for idx, name in enumerate(split_names)
            },
            "status": "DISCOVERY_ONLY",
            "validated_edge": False,
            "strategy_promoted": False,
        }
    index = pd.DatetimeIndex(frame.index)
    gaps = index.to_series().diff().dt.total_seconds().dropna()
    return {
        "schema": SCHEMA,
        "status": "DISCOVERY_ONLY",
        "validated_edge": False,
        "strategy_promoted": False,
        "input": {
            "path": str(path),
            "sha256": sha256_file(path),
            "rows": n,
            "first_timestamp": frame.index[0].isoformat(),
            "last_timestamp": frame.index[-1].isoformat(),
            "intervals_gt_15m": int((gaps > EXPECTED_BAR_SECONDS).sum()),
            "max_interval_minutes": float(gaps.max() / 60.0) if len(gaps) else None,
            "spread_field": "preserved but not converted; broker points and point size are not sufficient for USD/oz cost",
            "tick_volume_field": "used as a causal broker-bar activity feature; it is not executable order flow",
        },
        "protocol": {
            "split_rule": "chronological 60% discovery / 20% validation / 20% holdout",
            "hypotheses_predeclared": list(HYPOTHESES),
            "cost_scenarios": list(ASSUMED_ONE_SIDE_PRICE_COSTS),
            "cost_status": "ASSUMED; bid/ask, commission, slippage and swaps unavailable",
            "control": "constant long exposure matched to each strategy's mean absolute exposure within split",
            "execution": "signal at completed M15 close; next observed M15 open; fixed hold; hard gap boundary",
            "no_parameter_sweep": True,
            "overlap_warning": "the two local MT5 exports overlap and are not independent confirmation",
        },
        "hypotheses": hypotheses,
        "safety": {"orders_submitted": 0, "order_apis_called": [], "DEMO_EXECUTION": "DISABLED", "LIVE": "LOCKED"},
    }


def render_report(report: dict[str, Any]) -> str:
    lines = [
        "# XAUUSD@ conditioned-volatility M15 discovery (2026-10-23)",
        "",
        "**Disposition: DISCOVERY ONLY. No validated edge, no promotion, no orders.**",
        "",
        "This preregistered screen tests range/tick-volume conditioning, not an unconditional trend, reversal, breakout, session, impulse, macro, or ML rule.",
        "",
        f"Input rows: `{report['input']['rows']}`; SHA-256: `{report['input']['sha256']}`.",
        f"Observed intervals longer than 15 minutes: `{report['input']['intervals_gt_15m']}`; maximum: `{report['input']['max_interval_minutes']}` minutes.",
        "",
        "| Hypothesis | Validation t (cost 0.30) | Holdout t | Holdout Sharpe | Holdout changes |",
        "|---|---:|---:|---:|---:|",
    ]
    for hypothesis, payload in report["hypotheses"].items():
        validation = payload["splits"]["VALIDATION_20"]["cost_0.30"]
        holdout = payload["splits"]["HOLDOUT_20"]["cost_0.30"]
        lines.append(
            f"| {hypothesis} | {validation.get('hac_t_excess_vs_control')} | "
            f"{holdout.get('hac_t_excess_vs_control')} | {holdout.get('annualized_sharpe_252')} | "
            f"{holdout.get('position_changes')} |"
        )
    lines += [
        "",
        "Costs are assumed price distances, not measurements. The overlapping local exports cannot provide independent confirmation; a positive holdout is only a candidate for genuinely unseen forward observation.",
        "",
        "Safety: `orders_submitted=0`; `DEMO_EXECUTION=DISABLED`; `LIVE=LOCKED`.",
    ]
    return "\n".join(lines) + "\n"


def json_text(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str) + "\n"
