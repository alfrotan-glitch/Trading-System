"""Prequential, leakage-safe monthly gold research model (RESEARCH ONLY).

This is deliberately small, explainable machine learning, not an AI edge claim.
A single fixed-spec regularized linear model learns from realised historical
monthly outcomes only. It estimates the next month's gold return from trailing
gold momentum/volatility and PREVIOUSLY RELEASED Cboe volatility-curve data.

Key invariants
--------------
* Feature at month t reads gold and exogenous values knowable by that month end.
* Training response for month k is close[k+1]/close[k]-1. At the decision for
  month t the fit sees training k <= t-1 (last response ends at close[t]).
* Rolling means/stds are FIT to historical training rows, never the full sample.
* Fixed training length, ridge penalty, feature list and threshold are not tuned.
* Model output is long (1) or flat (0), with a strong independent no-trade state.
* The final investment decision is applied on the NEXT OPEN by run_vector.
* Historical gold windows are spent. Scores are DISCOVERY, never untouched OOS.

The input data need strict provenance and correct timestamps. Missing features
must not be treated as positive or filled from future observations.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

FEATURES = ("mom_1m", "mom_3m", "realized_vol_21d", "vix_slope", "mom_x_slope")


@dataclass(frozen=True)
class OnlineModelConfig:
    lookback_months: int = 120
    min_train_months: int = 60
    ridge_strength: float = 20.0
    entry_threshold: float = 0.003
    max_feature_zscore: float = 5.0

    def __post_init__(self) -> None:
        if self.lookback_months < self.min_train_months or self.min_train_months < 24:
            raise ValueError("insufficient training history")
        if self.ridge_strength <= 0.0 or self.entry_threshold < 0.0:
            raise ValueError("invalid ridge strength or entry threshold")
        if self.max_feature_zscore < 1.0:
            raise ValueError("max feature z-score must be >= 1")


def trailing_feature_frame(daily_gold_close: pd.Series, cboe_curve: pd.DataFrame) -> pd.DataFrame:
    """Monthly signals on real last trading-day timestamps, all past-only.

    At historical gold close t, Cboe data with the same reference date may not
    yet have been published. Therefore even after the preceding publication
    lag the exogenous variable is only carried forward a maximum of 5 days.
    """
    gold = daily_gold_close.astype(float).sort_index()
    gold_idx = pd.DatetimeIndex(gold.index)
    cboe_idx = pd.DatetimeIndex(cboe_curve.index)
    if gold_idx.tz is None or cboe_idx.tz is None:
        raise ValueError("gold and Cboe indices require explicit UTC timezone")
    if bool(gold.index.duplicated().any()) or bool((gold <= 0).any()):
        raise ValueError("duplicate gold timestamps or nonpositive gold close")
    if bool(cboe_curve.index.duplicated().any()):
        raise ValueError("duplicate Cboe timestamps")

    daily_vol = gold.pct_change().rolling(21, min_periods=21).std(ddof=1) * np.sqrt(252.0)
    # Keep true timestamp of the last observed trading bar, not a synthetic
    # month-end calendar stamp that could predate or postdate available prices.
    month_label = gold_idx.tz_convert("UTC").to_period("M")
    sampled = pd.DataFrame({"close": gold, "realized_vol_21d": daily_vol})
    monthly = sampled.groupby(month_label, sort=True).tail(1).copy()
    monthly["mom_1m"] = monthly["close"].pct_change()
    monthly["mom_3m"] = monthly["close"].pct_change(3)

    slope_ratio = cboe_curve["VIX3M"].astype(float) / cboe_curve["VIX"].astype(float)
    # An additional complete Cboe *published observation* must pass before the
    # signal can be used for a gold decision. Cross-venue timestamps otherwise
    # recreate the historical XL-001 look-ahead failure.
    past_slope = pd.Series(
        np.log(slope_ratio.to_numpy(dtype=float)),
        index=cboe_idx,
        name="vix_slope",
    ).shift(1).dropna()
    past_slope.index = pd.DatetimeIndex(past_slope.index).tz_convert("UTC")
    month_idx = pd.DatetimeIndex(monthly.index).tz_convert("UTC")
    aligned = past_slope.reindex(month_idx, method="ffill", tolerance=pd.Timedelta(days=5))
    monthly["vix_slope"] = aligned.to_numpy(dtype=float)
    monthly["mom_x_slope"] = monthly["mom_3m"] * monthly["vix_slope"]
    return monthly


def _ridge_predict(history: pd.DataFrame, current: pd.Series, cfg: OnlineModelConfig) -> float:
    """Train-only centering/scaling and regularization; no tuneable search."""
    x = history.loc[:, FEATURES].to_numpy(dtype=float)
    y = history["next_month_return"].to_numpy(dtype=float)
    cur = current.loc[list(FEATURES)].to_numpy(dtype=float)
    if not (np.isfinite(x).all() and np.isfinite(y).all() and np.isfinite(cur).all()):
        raise ValueError("training and current feature values must be finite")
    center = x.mean(axis=0)
    scale = x.std(axis=0, ddof=1)
    scale[scale < 1e-10] = 1.0
    z = np.clip((x - center) / scale, -cfg.max_feature_zscore, cfg.max_feature_zscore)
    z_cur = np.clip((cur - center) / scale, -cfg.max_feature_zscore, cfg.max_feature_zscore)
    intercept = float(y.mean())
    target = y - intercept
    coefficients = np.linalg.solve(
        z.T @ z + np.eye(z.shape[1]) * cfg.ridge_strength,
        z.T @ target,
    )
    return float(intercept + z_cur @ coefficients)


def prequential_monthly_predictions(
    features: pd.DataFrame,
    cfg: OnlineModelConfig | None = None,
) -> pd.DataFrame:
    """Predict in strict chronological order; never train on unresolved labels.

    Every prediction at month t trains only with rows k<t, whose next-month
    outcome is known by the last close of month t.
    """
    config = cfg or OnlineModelConfig()
    f = features.sort_index().copy()
    if pd.DatetimeIndex(f.index).tz is None:
        raise ValueError("monthly features must be timezone-aware")
    if bool(f.index.duplicated().any()):
        raise ValueError("monthly feature timestamps must be unique")
    f["next_month_return"] = f["close"].shift(-1) / f["close"] - 1.0
    rows: list[dict[str, object]] = []
    for i in range(len(f)):
        date = f.index[i]
        first = max(0, i - config.lookback_months)
        history = f.iloc[first:i].dropna(subset=[*FEATURES, "next_month_return"])
        valid = bool(f.iloc[i][list(FEATURES)].notna().all())
        if valid and len(history) >= config.min_train_months:
            forecast = _ridge_predict(history, f.iloc[i], config)
            target = float(forecast > config.entry_threshold)
        else:
            forecast = float("nan")
            target = 0.0
        rows.append(
            {
                "date": date,
                "forecast_next_month": forecast,
                "target_long": target,
                "training_rows": int(len(history)),
                "training_last_date": history.index[-1] if not history.empty else pd.NaT,
                "usable": valid and len(history) >= config.min_train_months,
            }
        )
    return pd.DataFrame(rows).set_index("date")


def daily_long_position(monthly_predictions: pd.DataFrame, gold_index: pd.DatetimeIndex) -> pd.Series:
    """Hold monthly decisions through next calendar month, starting NEXT open.

    The caller MUST feed these target positions to run_vector(execution="next_open").
    This function itself does not pretend to simulate fills.
    """
    idx = pd.DatetimeIndex(gold_index)
    monthly = monthly_predictions["target_long"].astype(float).sort_index()
    if pd.DatetimeIndex(monthly.index).tz is None or idx.tz is None:
        raise ValueError("explicit time zones are required")
    positions = monthly.reindex(idx, method="ffill").fillna(0.0).clip(0.0, 1.0)
    return positions.rename("online_gold_ridge_long")
