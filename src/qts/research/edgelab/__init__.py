"""Edge Lab — honest vectorised research harness for XAUUSD strategies.

Design rules (these exist because the opposite produced false positives here):

1. **No look-ahead by construction.** A position decided using information up to and
   including the close of bar ``t`` earns the return from ``open[t]`` to ``open[t+1]``.
   Signals never see their own fill.
2. **Costs are charged on turnover, not assumed away.** Every position change pays
   half-spread + slippage + commission, per side. A strategy that only survives at
   zero cost is reported as such.
3. **Untouched data is untouched.** ``split()`` returns chronological DEV/VAL/TEST
   indices; research code may only read DEV and VAL until a candidate is frozen.
4. **Trials are counted.** ``deflated_sharpe`` receives the number of configurations
   tried for that hypothesis family, so the multiple-testing correction is honest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------- costs


@dataclass(frozen=True)
class CostModel:
    """Round-trip trading cost, expressed per side in basis points of notional.

    Defaults are explicitly ASSUMED, not measured on the configured broker. At the
    ``reference_price`` of 2000 USD/oz they work out to:

    * half-spread   0.025 USD/oz on 2000 USD/oz  = 0.125 bps/side
    * commission    3.50 USD per 100 oz lot      = 0.175 bps/side
    * slippage      0.02 USD/oz                  = 0.100 bps/side
    * **total 0.40 bps/side, 0.80 bps round trip**

    An earlier version of this docstring claimed 4.0 bps/side — a factor-of-ten
    error between the prose and the formula. The formula is authoritative and the
    number above is what it computes. Because 0.40 bps is optimistic for retail
    gold (typical ECN spreads are 10-30 cents, not 5), ``realistic_ecn()`` models a
    wider spread and heavier slippage and **every candidate must be reported under
    both**. ``standard_account()`` models an 18-pip spread with no commission.
    """

    name: str = "ecn_assumed"
    spread_usd: float = 0.05
    commission_usd_per_lot_side: float = 3.50
    contract_oz: float = 100.0
    slippage_usd: float = 0.02
    reference_price: float = 2000.0

    def per_side_bps(self, price: float | None = None) -> float:
        px = float(price) if price else self.reference_price
        half_spread_bps = (self.spread_usd / 2.0) / px * 1e4
        commission_bps = (self.commission_usd_per_lot_side / (self.contract_oz * px)) * 1e4
        slippage_bps = (self.slippage_usd / px) * 1e4
        return half_spread_bps + commission_bps + slippage_bps

    @classmethod
    def zero(cls) -> CostModel:
        return cls(name="zero", spread_usd=0.0, commission_usd_per_lot_side=0.0, slippage_usd=0.0)

    @classmethod
    def standard_account(cls) -> CostModel:
        """No commission, 18-pip spread — typical of a standard gold account."""
        return cls(
            name="standard_assumed",
            spread_usd=0.18,
            commission_usd_per_lot_side=0.0,
            slippage_usd=0.02,
        )

    @classmethod
    def realistic_ecn(cls) -> CostModel:
        """A deliberately less flattering ECN model than the optimistic default.

        0.20 USD spread (typical retail ECN is 10-30 cents on gold) and 0.05 USD
        slippage. At 2000 USD/oz this costs ~0.925 bps/side, i.e. 2.3x the default.
        Use this whenever a result is close enough that the cost assumption could
        be doing the work.
        """
        return cls(
            name="ecn_realistic",
            spread_usd=0.20,
            commission_usd_per_lot_side=3.50,
            slippage_usd=0.05,
        )

    @classmethod
    def stressed(cls, factor: float = 2.0) -> CostModel:
        return cls(
            name=f"stressed_x{factor:g}",
            spread_usd=0.05 * factor,
            commission_usd_per_lot_side=3.50 * factor,
            slippage_usd=0.02 * factor,
        )


# --------------------------------------------------------------------------- splits

PERIODS = ("DEV", "VAL", "TEST", "OOS")
DEFAULT_BOUNDS = {
    "DEV": ("2004-01-01", "2018-12-31"),
    "VAL": ("2019-01-01", "2021-12-31"),
    "TEST": ("2022-01-01", "2024-12-31"),
}


def split(index: pd.DatetimeIndex, bounds: dict | None = None) -> dict[str, pd.DatetimeIndex]:
    """Chronological, non-overlapping period masks."""
    b = dict(DEFAULT_BOUNDS)
    if bounds:
        b.update({k: v for k, v in bounds.items() if k in PERIODS})
    out: dict[str, pd.DatetimeIndex] = {}
    for name in ("DEV", "VAL", "TEST"):
        lo, hi = b[name]
        out[name] = index[(index >= pd.Timestamp(lo, tz="UTC")) & (index <= pd.Timestamp(hi, tz="UTC"))]
    return out


# --------------------------------------------------------------------------- signals


def atr(bars: pd.DataFrame, n: int = 14) -> pd.Series:
    high, low, close = bars["high"], bars["low"], bars["close"]
    prev = close.shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    return tr.rolling(n, min_periods=n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def infer_bars_per_year(index: pd.DatetimeIndex) -> float:
    """Annualisation factor implied by the bar spacing actually present.

    Gold trades ~5 days a week, so a *calendar*-day convention would understate
    annual volatility by ~15%. Using 252 trading days and the median observed bar
    spacing gives 252 for D1, 6,048 for H1 and 24,192 for M15.
    """
    idx = pd.DatetimeIndex(index)
    if len(idx) < 3:
        return 252.0
    secs = np.diff(idx.values).astype("timedelta64[s]").astype(float)
    secs = secs[secs > 0]
    if not len(secs):
        return 252.0
    med = float(np.median(secs))
    return 252.0 * 86400.0 / med


def realized_vol(close: pd.Series, n: int = 96, bars_per_year: float | None = None) -> pd.Series:
    """Annualised realised volatility of log returns.

    ``bars_per_year`` must be the number of *bars* per trading year, not bars per
    day: annualising a daily series with sqrt(1) returns daily vol (~1%), which made
    every vol-target expression in this module clip to full size and silently do
    nothing.
    """
    ann = bars_per_year if bars_per_year is not None else infer_bars_per_year(pd.DatetimeIndex(close.index))
    r = np.log(close).diff()
    return r.rolling(n, min_periods=max(10, n // 4)).std() * np.sqrt(ann)


@dataclass
class StrategySpec:
    """A named, parameterised position rule.

    ``signal`` must return a float Series in [-1, 1] aligned to ``bars.index``
    describing the position to hold starting at the NEXT bar's open.
    """

    name: str
    family: str
    params: dict = field(default_factory=dict)
    fn: Any = None
    rationale: str = ""

    def positions(self, bars: pd.DataFrame) -> pd.Series:
        pos = pd.Series(self.fn(bars, **self.params), index=bars.index, dtype=float)
        return pos.clip(-1.0, 1.0).fillna(0.0)


# --------------------------------------------------------------------------- engine


@dataclass
class BacktestResult:
    name: str
    family: str
    params: dict
    period: str
    bars: int
    trades: int
    exposure: float
    gross_return: float
    net_return: float
    cagr: float
    sharpe: float
    sortino: float
    max_dd: float
    calmar: float
    profit_factor: float
    win_rate: float
    avg_win: float
    avg_loss: float
    expectancy_bps: float
    cost_drag: float
    turnover_per_year: float
    t_stat: float
    equity: pd.Series | None = None
    net_returns: pd.Series | None = None
    held: pd.Series | None = None

    def row(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k not in ("equity", "net_returns", "held", "params")}
        d["params"] = str(self.params)
        return d


def _metrics_from_returns(
    ret: np.ndarray,
    index: pd.DatetimeIndex,
    position: np.ndarray,
    cost_per_side: np.ndarray,
    bars_per_year: float,
) -> dict:
    equity = np.cumprod(1.0 + ret)
    n = len(ret)
    if n == 0:
        return {}
    years = n / bars_per_year
    total = float(equity[-1] - 1.0) if n else 0.0
    cagr = float(equity[-1] ** (1.0 / years) - 1.0) if years > 0 and equity[-1] > 0 else -1.0
    sd = float(np.std(ret, ddof=1)) if n > 2 else 0.0
    sharpe = float(np.mean(ret) / sd * np.sqrt(bars_per_year)) if sd > 0 else 0.0
    downside = ret[ret < 0]
    dsd = float(np.std(downside, ddof=1)) if len(downside) > 2 else 0.0
    sortino = float(np.mean(ret) / dsd * np.sqrt(bars_per_year)) if dsd > 0 else 0.0
    peak = np.maximum.accumulate(equity)
    dd = float(np.max(1.0 - equity / peak))
    calmar = float(cagr / dd) if dd > 0 else 0.0

    # Trade segmentation: a trade is a contiguous non-zero position block.
    trades: list[float] = []
    pos_change = np.diff(np.concatenate([[0.0], position, [0.0]]))
    starts = np.flatnonzero((position != 0) & (pos_change[:-1] != 0))
    ends = np.flatnonzero((position != 0) & (pos_change[1:] != 0)) + 1
    for s, e in zip(starts, ends, strict=False):
        seg = ret[s:e]
        if len(seg):
            trades.append(float(np.prod(1.0 + seg) - 1.0))
    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t < 0]
    pf = (sum(wins) / abs(sum(losses))) if losses and sum(losses) != 0 else (float("inf") if wins else 0.0)
    t_stat = float(np.mean(ret) / (sd / np.sqrt(n))) if sd > 0 and n > 2 else 0.0

    return {
        "bars": n,
        "trades": len(trades),
        "exposure": float(np.mean(position != 0)),
        "gross_return": float(np.sum(position * 0.0)),  # filled by caller
        "net_return": total,
        "cagr": cagr,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_dd": dd,
        "calmar": calmar,
        "profit_factor": float(pf),
        "win_rate": float(len(wins) / len(trades)) if trades else 0.0,
        "avg_win": float(np.mean(wins)) if wins else 0.0,
        "avg_loss": float(np.mean(losses)) if losses else 0.0,
        "expectancy_bps": float(np.mean(ret) * 1e4),
        "cost_drag": float(np.sum(cost_per_side)),
        "turnover_per_year": float(np.sum(np.abs(np.diff(position))) / years) if years > 0 else 0.0,
        "t_stat": t_stat,
    }


def run_vector(  # noqa: C901 - one explicit, auditable execution path
    bars: pd.DataFrame,
    positions: pd.Series,
    cost: CostModel,
    *,
    name: str,
    family: str,
    params: dict | None = None,
    period: str = "ALL",
    bars_per_year: float | None = None,
    keep_equity: bool = False,
    execution: str = "close",
) -> BacktestResult:
    """Vectorised backtest with turnover-charged costs.

    ``execution="close"`` (default): the position decided at the close of bar ``t``
    earns ``close[t+1]/close[t] - 1``. Standard signal-research convention, and
    executable (you trade at the close you just observed).

    ``execution="next_open"``: the same decision is filled at ``open[t+1]`` and
    realised at ``open[t+2]``, so P&L is indexed two bars ahead. Use this to prove a
    result is not an artefact of close-fill timing.

    Both are explicit about the offset — an implicit shift is how a signal ends up
    credited with the move that preceded it.
    """
    pos = positions.reindex(bars.index).fillna(0.0).to_numpy(dtype=float)
    n = len(pos)
    if n < 4:
        raise ValueError("need at least 4 bars")

    if execution == "close":
        px = bars["close"].to_numpy(dtype=float)
        roc = np.zeros(n)
        roc[1:] = px[1:] / px[:-1] - 1.0
        held = np.zeros(n)
        held[1:] = pos[:-1]  # decision at t earns the t -> t+1 move
        gross = held * roc
        cost_px = px
        idx = bars.index
        valid = slice(1, n)  # bar 0 has no prior decision
    elif execution == "next_open":
        px = bars["open"].to_numpy(dtype=float)
        roo = np.zeros(n)
        roo[1:] = px[1:] / px[:-1] - 1.0
        held = np.zeros(n)
        held[2:] = pos[:-2]  # decided at close t, filled open t+1, realised open t+2
        gross = held * roo
        cost_px = px
        idx = bars.index
        valid = slice(2, n)
    else:
        raise ValueError(f"unknown execution {execution!r}")

    dpos = np.abs(np.diff(np.concatenate([[0.0], held])))
    per_side = np.array([cost.per_side_bps(p) / 1e4 for p in cost_px])
    costs = dpos * per_side
    net = gross - costs

    net, gross = net[valid], gross[valid]
    held, costs = held[valid], costs[valid]
    idx = pd.DatetimeIndex(idx[valid])

    bpy = bars_per_year if bars_per_year is not None else 96.0 * 252.0
    m = _metrics_from_returns(net, idx, held, costs, bpy)
    m["gross_return"] = float(np.sum(gross))
    m["params"] = params or {}
    m["name"] = name
    m["family"] = family
    m["period"] = period
    m["net_return"] = float(np.prod(1.0 + net) - 1.0)
    eq = pd.Series(np.cumprod(1.0 + net), index=idx) if keep_equity else None
    nr = pd.Series(net, index=idx) if keep_equity else None
    hp = pd.Series(held, index=idx) if keep_equity else None
    return BacktestResult(equity=eq, net_returns=nr, held=hp, **m)


# --------------------------------------------------------------------------- alpha


def benchmark_returns(bars: pd.DataFrame) -> pd.Series:
    """Buy-and-hold close-to-close returns — the bar every strategy must clear."""
    return bars["close"].pct_change()


def alpha_decomposition(
    strategy_returns: pd.Series,
    bench_returns: pd.Series,
    bars_per_year: float,
) -> dict:
    """Separate *timing skill* from *long beta*, which is the whole game for gold.

    Gold rose secularly from 2004 to 2025. A rule that is long most of the time
    earns that beta and looks profitable while adding nothing. This reports:

    * ``beta``      — exposure to the underlying, regression based
    * ``alpha_ann`` — annualised intercept, i.e. return NOT explained by beta
    * ``ir``        — information ratio of the active return vs buy-and-hold
    * long/short    — P&L split by side, so a one-sided result is visible
    """
    joined = pd.concat([strategy_returns.rename("s"), bench_returns.rename("b")], axis=1).dropna()
    if len(joined) < 30:
        return {}
    var_b = float(joined["b"].var(ddof=1))
    if var_b <= 0:
        return {}
    beta = float(joined["s"].cov(joined["b"]) / var_b)
    alpha_bar = float(joined["s"].mean() - beta * joined["b"].mean())
    resid = joined["s"] - beta * joined["b"]
    active = joined["s"] - joined["b"]
    te = float(active.std(ddof=1))
    return {
        "beta": beta,
        "alpha_ann": alpha_bar * bars_per_year,
        "alpha_t": float(alpha_bar / (resid.std(ddof=1) / np.sqrt(len(joined))))
        if resid.std(ddof=1) > 0
        else 0.0,
        "ir_vs_bh": float(active.mean() / te * np.sqrt(bars_per_year)) if te > 0 else 0.0,
    }


def side_attribution(net_returns: np.ndarray, position: np.ndarray) -> dict:
    """P&L contributed while long vs while short."""
    long_mask = position > 0
    short_mask = position < 0
    return {
        "long_pnl": float(np.sum(net_returns[long_mask])),
        "short_pnl": float(np.sum(net_returns[short_mask])),
        "long_bars": int(long_mask.sum()),
        "short_bars": int(short_mask.sum()),
    }


# --------------------------------------------------------------------------- stats


def deflated_sharpe(
    sr_annualised: float,
    n_trials: int,
    n_obs: int,
    bars_per_year: float,
    skew: float = 0.0,
    kurt: float = 3.0,
) -> float:
    """Bailey & López de Prado deflated Sharpe: P(true SR > 0) after N trials.

    A value below ~0.95 is not evidence of skill once multiple testing is counted.

    **Units are a parameter, not an assumption.** The deflation benchmark is
    ``E[max SR] * sqrt(P / (n - 1))``, which is only correct if the Sharpe and the
    period count describe the same frequency. An earlier version of this function
    took an *annualised* Sharpe and multiplied it by ``sqrt(n_obs)`` as though it
    were per-bar, inflating the t-statistic by ``sqrt(252) ≈ 15.9x`` and returning
    ~1.0 for every input — a guard that passed everything is indistinguishable
    from no guard.

    ``bars_per_year`` is therefore required, and this delegates to the tested
    implementation in :mod:`qts.validation.metrics` rather than re-deriving the
    formula. Two copies of a statistic is how they drift apart.
    """
    from qts.validation.metrics import deflated_sharpe_ratio

    if n_obs < 3 or n_trials < 1:
        return 0.0
    return float(
        deflated_sharpe_ratio(
            observed_sr=sr_annualised,
            num_trials=n_trials,
            n=n_obs,
            skewness=skew,
            kurtosis=kurt,
            periods_per_year=int(round(bars_per_year)),
            annualized=True,
        )
    )


def yearly_table(ret: pd.Series) -> pd.DataFrame:
    """Per-calendar-year net return and Sharpe — exposes regime dependence."""
    rows = []
    for year, grp in ret.groupby(pd.DatetimeIndex(ret.index).year):
        eq = float(np.prod(1.0 + grp.to_numpy()) - 1.0)
        sd = float(np.std(grp.to_numpy(), ddof=1)) if len(grp) > 2 else 0.0
        rows.append(
            {
                "year": int(year),
                "return": eq,
                "sharpe": float(np.mean(grp) / sd * np.sqrt(len(grp))) if sd > 0 else 0.0,
                "bars": len(grp),
            }
        )
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- data


def load_bars(source: Literal["basemax", "vudo"] = "basemax") -> pd.DataFrame:
    path = {
        "basemax": "data/research/xauusd_m15_basemax.parquet",
        "vudo": "data/research/xauusd_m15_vudo.parquet",
    }[source]
    df = pd.read_parquet(path)
    df.index = pd.DatetimeIndex(df.index)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    return df.sort_index()


#: Tolerated spellings mapped to pandas offsets (``D1`` is MT5 shorthand).
_RULE_ALIASES = {"D1": "1D", "H1": "1h", "H4": "4h", "M15": "15min", "M30": "30min", "W1": "1W"}


def resample(bars: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Aggregate bars. ``label='left', closed='left'`` keeps the open of the first
    M15 bar as the aggregate open, so open-to-open returns stay executable."""
    rule = _RULE_ALIASES.get(rule, rule)
    out = bars.resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    return out.dropna(subset=["open", "high", "low", "close"])
