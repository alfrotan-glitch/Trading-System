"""How big would an edge have to be for this sample to see it at all?

A gate can only answer "is there evidence". It cannot answer "is there no effect",
because a small real effect is indistinguishable from zero on a finite sample. On
17.8 years of daily data the acceptance threshold of ``alpha_t >= 2.5`` has a hard
detection floor, and reporting `NO_VALIDATED_EDGE` without stating that floor
overstates what was ruled out.

The relationship is the ordinary one for a Sharpe ratio: with ``t`` years of data,

    t-statistic = SR * sqrt(years)          =>    SR = t / sqrt(years)

so the smallest annualised Sharpe that can reach significance is ``t/sqrt(years)``.
This holds for any bar frequency, which is the key implication: **re-sampling the
same period more finely adds no evidence.** Daily and hourly bars over 2004-2018
are the same 17.8 years, which is why an apparent "confirmation" at two timeframes
is not two observations.

Caveat: these are normal-approximation detection floors. Real return distributions
have fat tails and clustering, so the effective sample is smaller than the bar
count and the true floor is somewhat higher than this reports. Treat the output as
a best case, never a guarantee.
"""

from __future__ import annotations

import math

DEFAULT_T_STAT = 2.5


def years_for(n_obs: int, bars_per_year: float) -> float:
    """Calendar-equivalent years covered by ``n_obs`` bars."""
    if bars_per_year <= 0:
        raise ValueError("bars_per_year must be positive")
    return n_obs / bars_per_year


def min_detectable_sr(years: float, t_stat: float = DEFAULT_T_STAT) -> float:
    """Smallest annualised Sharpe that reaches ``t_stat`` over ``years``.

    Below this, a real edge cannot clear the gate however genuine it is.
    """
    if years <= 0:
        raise ValueError("years must be positive")
    if t_stat <= 0:
        raise ValueError("t_stat must be positive")
    return t_stat / math.sqrt(years)


def years_needed(sr: float, t_stat: float = DEFAULT_T_STAT) -> float:
    """Years of data required for a strategy with true Sharpe ``sr`` to reach ``t_stat``.

    Grows quadratically as the effect shrinks: halving the Sharpe quadruples the
    data required.
    """
    if sr <= 0:
        raise ValueError("sr must be positive to accumulate evidence")
    if t_stat <= 0:
        raise ValueError("t_stat must be positive")
    return (t_stat / sr) ** 2


def detection_summary(n_obs: int, bars_per_year: float, t_stat: float = DEFAULT_T_STAT) -> dict:
    """One row of context to attach to any gate verdict."""
    yrs = years_for(n_obs, bars_per_year)
    return {
        "years": yrs,
        "t_stat_threshold": t_stat,
        "min_detectable_sr": min_detectable_sr(yrs, t_stat),
        "years_for_sr_0_3": years_needed(0.3, t_stat),
        "years_for_sr_0_5": years_needed(0.5, t_stat),
        "note": "Normal approximation; fat tails mean the true floor is higher.",
    }
