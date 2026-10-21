"""Regime-aware allocation across the strategy catalogue.

This is the layer the programme was missing: 21 researched signals, a regime
classifier, and no defined rule for *when* each signal is allowed to hold risk or
how much. Everything here is a pre-registered policy, fixed before it is measured,
because an allocation rule fitted to the same returns it filters is just another
overfitting channel.

Three decisions, each stated rather than tuned
---------------------------------------------
1. **Eligibility.** A long-only trend rule is allowed to hold only in ``TREND_UP``;
   a mean-reversion rule only in ``RANGE``; macro, calendar, quantity and
   positioning families are regime-agnostic and eligible whenever trading is
   allowed. These follow the economic content of the families, not a search.
2. **Volatility targeting.** Exposure is scaled by
   ``target_vol / realised_vol``, capped at ``max_leverage``. This is the standard
   risk-management construction (Moreira & Muir 2017) and it makes no alpha claim.
3. **No-trade.** Nothing is held when the regime module says conditions are
   unsuitable (top volatility percentile), regardless of signal.

What this module does *not* do
------------------------------
It does not switch between strategies on the basis of which one has recently
performed. Performance-chasing allocators add turnover and rarely survive costs on
daily data; the eligibility rule is structural instead.

The honest question the evaluation must answer is whether any of this beats a
static blend scaled to the *same average exposure*. If it does not, the system is
merely de-risking, and saying "intelligent regime allocation" would be marketing.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from qts.research.edgelab.regime import MarketRegime

_ALL = frozenset({MarketRegime.TREND_UP.value, MarketRegime.TREND_DOWN.value, MarketRegime.RANGE.value, MarketRegime.HIGH_VOL.value})

#: Pre-registered eligibility. Long-only signals, so a falling trend is no-trade.
DEFAULT_ELIGIBILITY: Mapping[str, frozenset[str]] = {
    "trend": frozenset({MarketRegime.TREND_UP.value}),
    "meanrev": frozenset({MarketRegime.RANGE.value}),
    "calendar": _ALL,
    "real_yield": _ALL,
    "inflation": _ALL,
    "regime": _ALL,
    "quantity": _ALL,
    "positioning": _ALL,
}


@dataclass(frozen=True)
class AllocationConfig:
    """Allocation policy. Values are round numbers chosen a priori."""

    target_vol: float = 0.12
    max_leverage: float = 1.0
    vol_window: int = 21
    min_scale: float = 0.0
    eligibility: Mapping[str, frozenset[str]] = field(default_factory=lambda: DEFAULT_ELIGIBILITY)

    def __post_init__(self) -> None:
        if not 0.0 < self.target_vol <= 1.0:
            raise ValueError("target_vol must be in (0, 1]")
        if self.max_leverage <= 0.0:
            raise ValueError("max_leverage must be positive")


def vol_scale(realized_vol: pd.Series, config: AllocationConfig) -> pd.Series:
    """``target_vol / realised_vol``, clipped to ``[min_scale, max_leverage]``.

    Undefined volatility (warm-up) yields zero scale, not one: an unmeasured
    market is not a reason to take full risk.
    """
    raw = config.target_vol / realized_vol.replace(0.0, np.nan)
    return raw.clip(config.min_scale, config.max_leverage).fillna(0.0).rename("vol_scale")


def eligible_positions(signals: pd.DataFrame, regimes: pd.DataFrame, families: Mapping[str, str], config: AllocationConfig) -> pd.DataFrame:
    """Mask each signal to the regimes its family is allowed to trade in."""
    reg = regimes["regime"].reindex(signals.index)
    out = signals.copy().astype(float)
    for col in out.columns:
        family = families.get(col, "")
        allowed = config.eligibility.get(family, _ALL)
        mask = reg.isin(list(allowed)).to_numpy()
        out[col] = np.where(mask, out[col].to_numpy(), 0.0)
    return out


def allocate(
    signals: pd.DataFrame,
    regimes: pd.DataFrame,
    families: Mapping[str, str],
    config: AllocationConfig | None = None,
) -> pd.DataFrame:
    """Combine signals into one exposure series under the stated policy.

    Returns a frame with the final ``position`` in [0, max_leverage], plus the
    intermediate quantities so the decision is auditable bar by bar.
    """
    cfg = config or AllocationConfig()
    sig = signals.reindex(regimes.index).fillna(0.0).astype(float)
    mask = eligible_positions(sig, regimes, families, cfg)

    n_eligible = (mask.abs() > 0).sum(axis=1)
    gross = mask.mean(axis=1).where(n_eligible > 0, 0.0)  # equal weight across *active* rules
    scale = vol_scale(regimes["realized_vol"].reindex(sig.index), cfg)
    allowed = regimes["allow_trade"].reindex(sig.index).fillna(False).astype(bool)

    position = (gross * scale).where(allowed, 0.0).clip(0.0, cfg.max_leverage)
    return pd.DataFrame(
        {
            "position": position,
            "gross_target": gross,
            "vol_scale": scale,
            "n_eligible": n_eligible,
            "allowed": allowed,
            "regime": regimes["regime"].reindex(sig.index),
        },
        index=sig.index,
    )
