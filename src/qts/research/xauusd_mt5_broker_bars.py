"""Causal, execution-aware discovery on a preserved MT5 XAUUSD M15 export.

This module is deliberately a small assay, not a strategy engine.  It uses a
fixed list of predeclared hypotheses, next-bar-open execution, hard session
boundaries at missing bars, exposure-matched controls, and explicitly assumed
price-distance costs.  The MT5 ``spread`` column is retained as provenance but
is not converted into a cost because its point size and executable bid/ask
history are not present in the OHLC export.

The result is always discovery-only.  It cannot register, promote, authorize,
or submit an order.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

SCHEMA = "qts.xauusd_mt5_broker_bars_discovery.v1"
EXPECTED_BAR_SECONDS = 15 * 60
LOOKBACKS = {"H-MT5-TREND-12": 12, "H-MT5-REVERT-4": 4, "H-MT5-BREAKOUT-32": 32}
ASSUMED_ONE_SIDE_PRICE_COSTS = (0.0, 0.15, 0.30, 0.50)
DEFAULT_INPUT = Path("data/raw/mt5_xauusd_m15_30000.csv")
DEFAULT_EVIDENCE = Path("data/evidence/mt5_bars_30000.json")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_broker_bars(path: Path) -> pd.DataFrame:
    """Load and validate closed broker OHLC bars without repairing them."""
    frame = pd.read_csv(path)
    required = {"timestamp", "open", "high", "low", "close"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"broker bar export is missing required columns: {missing}")
    timestamps = pd.to_datetime(frame.pop("timestamp"), utc=True, errors="raise")
    if timestamps.duplicated().any() or not timestamps.is_monotonic_increasing:
        raise ValueError("broker bar export must be strictly chronological with unique timestamps")
    prices = frame[["open", "high", "low", "close"]].apply(pd.to_numeric, errors="raise")
    values = prices.to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("broker bar export contains non-finite or non-positive OHLC values")
    if (prices["high"] < prices[["open", "close", "low"]].max(axis=1)).any():
        raise ValueError("broker bar high invariant failed")
    if (prices["low"] > prices[["open", "close", "high"]].min(axis=1)).any():
        raise ValueError("broker bar low invariant failed")
    for column in ("open", "high", "low", "close"):
        # Assign the ndarray, not the RangeIndex-labelled Series: the frame's
        # index is replaced with UTC timestamps immediately below.
        frame[column] = prices[column].to_numpy(dtype=float)
    frame.index = pd.DatetimeIndex(timestamps, name="timestamp")
    if "spread" in frame:
        frame["spread"] = pd.to_numeric(frame["spread"], errors="coerce")
        if frame["spread"].isna().any() or (frame["spread"] < 0).any():
            raise ValueError("broker bar spread field contains invalid values")
    return frame


def _consecutive_bar_run(index: pd.DatetimeIndex) -> np.ndarray:
    """Return the length of the current uninterrupted 15-minute bar run."""
    seconds = np.asarray(index.as_unit("s").astype("int64"), dtype=np.int64)
    run = np.ones(len(index), dtype=np.int64)
    if len(index) > 1:
        contiguous = np.diff(seconds) == EXPECTED_BAR_SECONDS
        for idx in range(1, len(index)):
            run[idx] = run[idx - 1] + 1 if contiguous[idx - 1] else 1
    return run


def hypothesis_signals(frame: pd.DataFrame) -> dict[str, pd.Series]:
    """Compute the four frozen signals at bar close, before execution lag."""
    index = pd.DatetimeIndex(frame.index)
    close = frame["close"]
    run = _consecutive_bar_run(index)

    trend = np.sign(close / close.shift(LOOKBACKS["H-MT5-TREND-12"]) - 1.0)
    trend[run < LOOKBACKS["H-MT5-TREND-12"] + 1] = 0.0

    reversal = -np.sign(close / close.shift(LOOKBACKS["H-MT5-REVERT-4"]) - 1.0)
    reversal[run < LOOKBACKS["H-MT5-REVERT-4"] + 1] = 0.0

    prior_high = frame["high"].shift(1).rolling(LOOKBACKS["H-MT5-BREAKOUT-32"], min_periods=32).max()
    prior_low = frame["low"].shift(1).rolling(LOOKBACKS["H-MT5-BREAKOUT-32"], min_periods=32).min()
    breakout = pd.Series(0.0, index=frame.index)
    breakout[close > prior_high] = 1.0
    breakout[close < prior_low] = -1.0
    breakout.loc[run < LOOKBACKS["H-MT5-BREAKOUT-32"] + 1] = 0.0

    session = np.sign(close / close.shift(4) - 1.0)
    session[(index.hour < 7) | (index.hour >= 18) | (run < 5)] = 0.0

    return {
        "H-MT5-TREND-12": trend.astype(float),
        "H-MT5-REVERT-4": reversal.astype(float),
        "H-MT5-BREAKOUT-32": breakout.astype(float),
        "H-MT5-SESSION-MOM-4": session.astype(float),
    }


def _hac_t(values: pd.Series, lags: int = 5) -> float | None:
    clean = pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna().to_numpy(float)
    n = len(clean)
    if n < 10:
        return None
    centered = clean - float(clean.mean())
    variance = float(np.mean(centered * centered))
    for lag in range(1, min(lags, n - 1) + 1):
        weight = 1.0 - lag / (min(lags, n - 1) + 1.0)
        variance += 2.0 * weight * float(np.mean(centered[lag:] * centered[:-lag]))
    if variance <= 0 or not np.isfinite(variance):
        return None
    return float(clean.mean() / np.sqrt(variance / n))


def _daily_returns(values: pd.Series) -> pd.Series:
    index = pd.DatetimeIndex(values.index)
    return (1.0 + values).groupby(index.floor("D")).prod() - 1.0


def _summary(returns: pd.Series, excess: pd.Series, position: pd.Series) -> dict[str, Any]:
    daily = _daily_returns(returns)
    excess_daily = _daily_returns(excess)
    mean = float(daily.mean()) if len(daily) else None
    std = float(daily.std(ddof=1)) if len(daily) > 1 else None
    sharpe = float(mean / std * np.sqrt(252.0)) if mean is not None and std and std > 0 else None
    equity = (1.0 + daily).cumprod() if len(daily) else pd.Series(dtype=float)
    drawdown = equity / equity.cummax() - 1.0 if len(equity) else pd.Series(dtype=float)
    return {
        "observations": int(len(daily)),
        "mean_daily_return": mean,
        "annualized_sharpe_252": sharpe,
        "max_drawdown": float(drawdown.min()) if len(drawdown) else None,
        "mean_daily_excess_vs_control": float(excess_daily.mean()) if len(excess_daily) else None,
        "hac_t_excess_vs_control": _hac_t(excess_daily),
        "average_abs_exposure": float(position.abs().mean()) if len(position) else 0.0,
        "position_changes": int((position.diff().abs().fillna(position.abs()) > 0).sum()),
    }


def execution_position(frame: pd.DataFrame, signal: pd.Series) -> pd.Series:
    """Apply the frozen next-open and hard-gap execution convention."""
    position = signal.shift(1).fillna(0.0).astype(float)
    index = pd.DatetimeIndex(frame.index)
    contiguous = index.to_series().diff().dt.total_seconds().eq(EXPECTED_BAR_SECONDS)
    return position.where(contiguous, 0.0)


def evaluate_hypothesis(
    frame: pd.DataFrame,
    signal: pd.Series,
    start: int,
    end: int,
    one_side_price_cost: float,
) -> dict[str, Any]:
    """Score one fixed signal on one chronological split.

    Signals are known at close ``t`` and held from open ``t+1``.  A missing
    bar is a hard boundary: the next observed bar starts flat, so no unknown
    path across the gap is credited.
    """
    index = pd.DatetimeIndex(frame.index)
    position = execution_position(frame, signal)
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
    excess = net - control
    result = _summary(net.iloc[start:end], excess.iloc[start:end], position.iloc[start:end])
    result.update(
        {
            "gross": _summary(gross.iloc[start:end], gross.iloc[start:end] - control.iloc[start:end], position.iloc[start:end]),
            "one_side_price_cost": float(one_side_price_cost),
            "cost_basis": "ASSUMED_PRICE_DISTANCE_PER_SIDE; not broker-measured",
            "start_timestamp": index[start].isoformat() if start < len(frame) else None,
            "end_timestamp": index[end - 1].isoformat() if end > start else None,
        }
    )
    return result


def run_discovery(path: Path = DEFAULT_INPUT, evidence_path: Path = DEFAULT_EVIDENCE) -> dict[str, Any]:
    """Run the fixed assay and return a JSON-serializable discovery report."""
    frame = load_broker_bars(path)
    signals = hypothesis_signals(frame)
    n = len(frame)
    cuts = (0, int(n * 0.60), int(n * 0.80), n)
    split_names = ("DISCOVERY_60", "VALIDATION_20", "HOLDOUT_20")
    results: dict[str, Any] = {}
    for hypothesis, signal in signals.items():
        results[hypothesis] = {
            "definition": {
                "signal_at": "completed M15 close",
                "execution": "next observed M15 bar open",
                "gap_rule": "flatten before every missing/non-15-minute interval; no gap return credited",
            },
            "splits": {
                name: {
                    f"cost_{cost:.2f}": evaluate_hypothesis(frame, signal, cuts[i], cuts[i + 1], cost)
                    for cost in ASSUMED_ONE_SIDE_PRICE_COSTS
                }
                for i, name in enumerate(split_names)
            },
            "status": "DISCOVERY_ONLY",
            "validated_edge": False,
            "strategy_promoted": False,
        }

    index = pd.DatetimeIndex(frame.index)
    gaps = index.to_series().diff().dt.total_seconds().dropna()
    report = {
        "schema": SCHEMA,
        "status": "DISCOVERY_ONLY",
        "validated_edge": False,
        "strategy_promoted": False,
        "input": {
            "path": str(path),
            "sha256": sha256_file(path),
            "evidence_path": str(evidence_path),
            "rows": n,
            "first_timestamp": frame.index[0].isoformat(),
            "last_timestamp": frame.index[-1].isoformat(),
            "intervals_gt_15m": int((gaps > EXPECTED_BAR_SECONDS).sum()),
            "max_interval_minutes": float(gaps.max() / 60.0) if len(gaps) else None,
            "spread_field": "preserved but not converted; broker points and point size are not sufficient for USD/oz cost",
        },
        "protocol": {
            "split_rule": "chronological 60% discovery / 20% validation / 20% holdout",
            "hypotheses_predeclared": list(signals),
            "cost_scenarios": list(ASSUMED_ONE_SIDE_PRICE_COSTS),
            "cost_status": "ASSUMED; bid/ask, commission, slippage and swaps are unavailable",
            "control": "constant long exposure matched to each strategy's mean absolute exposure within split",
            "no_parameter_sweep": True,
        },
        "hypotheses": results,
        "safety": {"orders_submitted": 0, "order_apis_called": [], "DEMO_EXECUTION": "DISABLED", "LIVE": "LOCKED"},
    }
    return report


def render_report(report: dict[str, Any]) -> str:
    lines = [
        "# XAUUSD@ MT5 M15 broker-bar discovery (2026-10-22)",
        "",
        "**Disposition: DISCOVERY ONLY. No validated edge, no promotion, no orders.**",
        "",
        f"Input rows: `{report['input']['rows']}`; SHA-256: `{report['input']['sha256']}`.",
        f"Observed intervals longer than 15 minutes: `{report['input']['intervals_gt_15m']}`; maximum: `{report['input']['max_interval_minutes']}` minutes.",
        "",
        "Signals were evaluated at a completed-bar close and applied at the next observed bar open. Missing bars flatten the position before the next observed bar; no unknown gap return is credited. Costs are assumed price distances per side, not broker measurements.",
        "",
        "| Hypothesis | Discovery t (cost 0.30) | Validation t | Holdout t | Holdout Sharpe |",
        "|---|---:|---:|---:|---:|",
    ]
    for hypothesis, payload in report["hypotheses"].items():
        splits = payload["splits"]
        row = [hypothesis]
        for split in ("DISCOVERY_60", "VALIDATION_20", "HOLDOUT_20"):
            row.append(str(splits[split]["cost_0.30"].get("hac_t_excess_vs_control")))
        row.append(str(splits["HOLDOUT_20"]["cost_0.30"].get("annualized_sharpe_252")))
        lines.append("| " + " | ".join(row) + " |")
    lines += [
        "",
        "The broker OHLC export does not contain executable bid/ask event history, fill prices, commission, slippage, or swap evidence. The `spread` field is broker points and was not converted. These results cannot support a profitability claim or a DEMO/LIVE decision.",
        "",
        "Safety: `orders_submitted=0`; `DEMO_EXECUTION=DISABLED`; `LIVE=LOCKED`.",
    ]
    return "\n".join(lines) + "\n"


def json_text(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str) + "\n"
