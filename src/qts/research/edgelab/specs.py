"""The hypothesis catalogue: every strategy the Edge Lab is allowed to test.

Kept in the package (not in a script) so the same definitions are used by the
screen, the acceptance gate and the test suite. A catalogue that exists in two
places is how a "survivor" gets evaluated against different code than the one
that produced it.
"""

from __future__ import annotations

import pandas as pd

from qts.research.edgelab import StrategySpec
from qts.research.edgelab import signals as S

BARS_PER_YEAR = {"D1": 252.0, "H4": 252.0 * 6, "H1": 252.0 * 24, "M15": 252.0 * 96, "M30": 252.0 * 48}


def trend_ensemble(bars: pd.DataFrame, members: tuple[str, ...] = ("tsmom5", "tsmom20", "ma", "donch")) -> pd.Series:
    """Average several weak, imperfectly-correlated trend rules.

    Individually each rule has an alpha t-stat near 2, which is not enough after
    multiple testing. Averaging diversified, correlated-but-not-identical signals
    is the standard way to raise the information ratio without adding a new bet —
    if the effect is real. If the members are pure noise, the average is noise too.
    """
    parts: list[pd.Series] = []
    for m in members:
        if m == "tsmom5":
            parts.append(S.tsmom(bars, 5))
        elif m == "tsmom20":
            parts.append(S.tsmom(bars, 20))
        elif m == "ma":
            parts.append(S.ma_cross(bars, 50, 200))
        elif m == "donch":
            parts.append(S.donchian(bars, 20, 10))
        else:
            raise ValueError(m)
    return pd.concat(parts, axis=1).mean(axis=1).clip(-1.0, 1.0)


def build_specs() -> list[StrategySpec]:
    specs: list[StrategySpec] = []

    # ---- Family 1: time-series momentum on daily bars (the classic XAUUSD edge) --
    for lb in (5, 10, 20, 40, 60, 120, 250):
        specs.append(
            StrategySpec(
                name=f"tsmom_d{lb}",
                family="tsmom",
                params={"lookback_days": lb},
                fn=S.tsmom,
                rationale="Gold trends: trailing-return sign persistence at daily/weekly horizon.",
            )
        )
    for lb in (20, 60):
        specs.append(
            StrategySpec(
                name=f"tsmom_vol_d{lb}",
                family="tsmom",
                params={"lookback_days": lb, "vol_target": 0.15},
                fn=S.tsmom,
                rationale="Same signal, volatility-scaled for stable risk across regimes.",
            )
        )

    # ---- Family 2: moving-average trend -----------------------------------------
    for fast, slow in ((10, 50), (20, 100), (50, 200), (20, 50)):
        specs.append(
            StrategySpec(
                name=f"ma_{fast}_{slow}",
                family="ma",
                params={"fast_days": fast, "slow_days": slow},
                fn=S.ma_cross,
                rationale="Classic trend filter; slower pairs trade less and pay less cost.",
            )
        )

    # ---- Family 3: Donchian breakout --------------------------------------------
    for entry, exit_ in ((20, 10), (50, 20), (100, 50)):
        specs.append(
            StrategySpec(
                name=f"donchian_{entry}_{exit_}",
                family="donchian",
                params={"entry_days": entry, "exit_days": exit_},
                fn=S.donchian,
                rationale="Range expansion follows the same trend economics with a timed exit.",
            )
        )

    # ---- Family 4: volatility breakout ------------------------------------------
    for k in (0.5, 1.0, 1.5):
        specs.append(
            StrategySpec(
                name=f"volbreak_{k}",
                family="volbreak",
                params={"k": k, "lookback": 20},
                fn=S.volatility_breakout,
                rationale="Directional expansion after a volatility-scaled close.",
            )
        )

    # ---- Family 5: intraday session behaviour ------------------------------------
    for h in ((7, 8), (13, 14, 15), (8, 9, 10, 11)):
        specs.append(
            StrategySpec(
                name=f"session_long_{'-'.join(map(str, h))}",
                family="session",
                params={"long_hours": h},
                fn=S.session_bias,
                rationale="Gold carries session-dependent drift (London/NY demand).",
            )
        )
    specs.append(
        StrategySpec(
            name="overnight_long",
            family="session",
            params={"entry_hour": 20, "exit_hour": 6},
            fn=S.overnight,
            rationale="Close-to-open drift / carry effect.",
        )
    )
    for d in (0, 1, 2, 3, 4):
        specs.append(
            StrategySpec(
                name=f"dow_long_{d}",
                family="dow",
                params={"long_days": (d,)},
                fn=S.day_of_week,
                rationale="Weekday seasonality (a weak prior; included to be falsified).",
            )
        )

    # ---- Family 6: mean reversion -------------------------------------------------
    for n in (7, 14, 21):
        specs.append(
            StrategySpec(
                name=f"rsi_{n}_30_70",
                family="rsi",
                params={"n": n, "low": 30, "high": 70},
                fn=S.rsi_reversion,
                rationale="Intraday overreaction fades back to the mean.",
            )
        )
    specs.append(
        StrategySpec(
            name="rsi_14_trendfilter",
            family="rsi",
            params={"n": 14, "low": 35, "high": 65, "trend_filter_days": 50},
            fn=S.rsi_reversion,
            rationale="Fade only with the daily trend — avoids fighting momentum.",
        )
    )
    for n, k in ((40, 2.0), (96, 2.0), (96, 3.0)):
        specs.append(
            StrategySpec(
                name=f"boll_{n}_{k}",
                family="bollinger",
                params={"n": n, "k": k},
                fn=S.bollinger_reversion,
                rationale="Fade k-sigma extensions on intraday bars.",
            )
        )

    # ---- Family 9: ensemble of weak trend rules -----------------------------------
    specs.append(
        StrategySpec(
            name="ensemble_trend",
            family="ensemble",
            params={"members": ("tsmom5", "tsmom20", "ma", "donch")},
            fn=trend_ensemble,
            rationale="Diversify several weak trend rules; the average should beat its parts if the effect is real.",
        )
    )
    specs.append(
        StrategySpec(
            name="ensemble_tsmom",
            family="ensemble",
            params={"members": ("tsmom5", "tsmom20")},
            fn=trend_ensemble,
            rationale="Two-horizon momentum only — the least correlated components.",
        )
    )

    # ---- Family 8: volatility-managed exposure ------------------------------------
    for tv in (0.10, 0.15, 0.20):
        for lb in (20, 60):
            specs.append(
                StrategySpec(
                    name=f"volman_{int(tv * 100)}_d{lb}",
                    family="volman",
                    params={"target_vol": tv, "lookback_days": lb},
                    fn=S.vol_managed_long,
                    rationale="Gold's vol clusters; constant-notional holds varying risk. Scale to a vol budget.",
                )
            )

    # ---- Family 7: opening-range breakout (London) --------------------------------
    for rm, hold in ((60, 240), (120, 360), (60, 480)):
        specs.append(
            StrategySpec(
                name=f"orb_london_{rm}_{hold}",
                family="orb",
                params={"range_minutes": rm, "session_start_hour": 7, "hold_minutes": hold},
                fn=S.opening_range_breakout,
                rationale="London open concentrates real flow; breaks of the initial range persist.",
            )
        )

    return specs
