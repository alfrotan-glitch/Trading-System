"""The single evaluation path shared by every candidate report.

Two scripts now report candidate performance — the frozen DEV/VAL/TEST scorecard
and the holdout extension. If each grew its own copy of "run the backtest, then
regress on buy-and-hold", the two would eventually disagree, and the number a
reader compares across periods would not be the same number. So the computation
lives here once.
"""

from __future__ import annotations

import pandas as pd

from qts.research.edgelab import (
    CostModel,
    alpha_decomposition,
    as_float,
    benchmark_returns,
    run_vector,
)

BARS_PER_YEAR = 252.0


def evaluate_period(
    sub: pd.DataFrame,
    sig: pd.Series,
    cost: CostModel,
    name: str,
    family: str,
    bars_per_year: float = BARS_PER_YEAR,
) -> dict:
    """Backtest one period and decompose the return against buy-and-hold.

    ``alpha_t`` is the plain OLS t-statistic of the intercept. It understates
    uncertainty when returns are autocorrelated, which is why
    :func:`qts.research.edgelab.hac_alpha` also exists; the frozen scorecard has
    always used this one, so it stays, and the HAC figure is reported beside it
    wherever a conclusion depends on the difference.
    """
    r = run_vector(sub, sig, cost, name=name, family=family, bars_per_year=bars_per_year, keep_equity=True)
    if r.net_returns is None:
        raise RuntimeError("keep_equity required")
    st = alpha_decomposition(r.net_returns, benchmark_returns(sub), bars_per_year)
    return {
        "cagr": r.cagr,
        "sharpe": r.sharpe,
        "max_dd": r.max_dd,
        "trades": r.trades,
        "exposure": r.exposure,
        "turnover_per_year": r.turnover_per_year,
        "alpha_ann": st.get("alpha_ann", float("nan")),
        "alpha_t": st.get("alpha_t", float("nan")),
        "beta": st.get("beta", float("nan")),
        "skew": as_float(r.net_returns.skew()),
        "kurt": as_float(r.net_returns.kurt()) + 3.0,
        "n_obs": int(len(r.net_returns)),
        "net_returns": r.net_returns,
        "bench_returns": benchmark_returns(sub),
    }


def strip_diagnostics(m: dict) -> dict:
    """Drop the Series fields so a metrics dict can be JSON-serialised."""
    return {k: v for k, v in m.items() if not isinstance(v, pd.Series)}
