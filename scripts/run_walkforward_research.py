#!/usr/bin/env python
"""Walk-forward strategy research on real XAUUSD history.

This is the honest version of "does this strategy work?": pick parameters on
one stretch of history, measure on a stretch the selection never saw, repeat
across the whole series, then correct for how many things you tried.

It does not search for a winner to report. It measures a bounded, pre-declared
set of hypotheses and reports whatever they do — including, and especially,
when they lose.

Usage
-----
    python scripts/run_walkforward_research.py \\
        --data-version <version> \\
        --family trend \\
        --folds 5 \\
        --spread-bps 3.0 --slippage-bps 2.0 --commission-per-lot 7.0 \\
        --cost-source "WMMarkets-Demo, ASSUMED retail estimate, 2026-10-09"

Costs are ASSUMED until measured on the broker. The report says so, and the
verdict can never be a claim while that is true.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from qts.adapters.matching import MatchingConfig  # noqa: E402
from qts.backtest.engine import BacktestEngine  # noqa: E402
from qts.data.store import SqliteParquetDataStore  # noqa: E402
from qts.domain.value_objects import AssetClass, Instrument  # noqa: E402
from qts.research.pipeline import (  # noqa: E402
    RunOutcome,
    build_folds,
    run_walk_forward,
    write_report,
)
from qts.research.strategies import BOUNDED_PARAM_SPACE, StrategyFamily  # noqa: E402

# Bars per year for a 23h/day, 5-day-week market at 15m cadence.
PERIODS_PER_YEAR = 23 * 4 * 252

REPORT_SCHEMA = "qts.walkforward_research_run.v1"


def make_runner(
    engine: BacktestEngine,
    instrument: Instrument,
    timeframe: str,
    data_version: str,
    family: str,
    *,
    exit_rules: dict[str, object] | None,
    quantity: float,
):
    """Bind the engine to the pipeline's runner signature."""

    def runner(params: dict[str, object], start: datetime, end: datetime) -> RunOutcome:
        strategy_params = {**params, "_family": family, "quantity": quantity}
        result = engine.run(
            instrument=instrument,
            timeframe=timeframe,
            data_version=data_version,
            strategy_id=f"{family}_wf",
            strategy_params=strategy_params,
            start=start,
            end=end,
            exit_rules=exit_rules,
        )
        fills = result.fills or []

        # The matching engine charges spread and slippage by moving the EXECUTION
        # PRICE, not by adding a fee — which is how a broker actually works. The
        # `fee` field is commission alone, so summing it captures a fraction of
        # the real cost and makes "gross" look far better than it is. Recover the
        # price-based friction from the difference between the executed price and
        # the bar open it was priced against.
        # quantity is in LOTS and PnL is lots * contract_size * price_diff, so the
        # friction must be scaled the same way. Omitting contract_size here
        # understated real trading cost by 100x on XAUUSD and made gross
        # performance look far better than it is.
        contract_size = float(instrument.contract_size)
        commission = sum(float(f.get("fee", 0) or 0) for f in fills)
        friction = 0.0
        for f in fills:
            try:
                price = float(f.get("price") or 0)
                reference = float(f.get("bar_open") or 0)
                qty = float(f.get("qty") or 0)
            except (TypeError, ValueError):
                continue
            if reference > 0:
                friction += abs(price - reference) * qty * contract_size
        cost = commission + friction

        net = float(result.final_equity) - 10000.0
        return RunOutcome(
            trades=result.trades,
            net_return=net,
            gross_return=net + cost,
            cost=cost,
            equity_curve=list(result.equity_curve or []),
            returns=list(result.returns or []),
        )

    return runner


def buy_and_hold_baseline(
    bars: list,
    folds: list,
    *,
    quantity: float,
    contract_size: float,
    spread_bps: float,
    slippage_bps: float,
    commission_per_lot: float,
) -> RunOutcome:
    """What simply holding the instrument over the same windows would have done.

    This is the baseline that decides whether a strategy is worth its costs.
    Gold rose 26% across the acquired history; a rule that makes less than
    holding the metal has not earned its spread, slippage and commission — it
    has just been busy.

    Priced with the same friction as any other trade: half-spread plus
    slippage on the way in and again on the way out, plus commission.
    """
    net = 0.0
    cost = 0.0
    returns: list[float] = []
    trades = 0
    for fold in folds:
        window = [b for b in bars if fold.test_start <= b.open_time < fold.test_end]
        if len(window) < 2:
            continue
        entry = float(window[0].open)
        exit_ = float(window[-1].close)
        friction_bps = (spread_bps / 2.0 + slippage_bps) / 10000.0
        entry_cost = entry * friction_bps
        exit_cost = exit_ * friction_bps
        notional = quantity * contract_size
        leg_cost = (entry_cost + exit_cost) * notional + 2.0 * commission_per_lot * quantity
        pnl = (exit_ - entry) * notional
        net += pnl - leg_cost
        cost += leg_cost
        returns.append((pnl - leg_cost) / 10000.0)
        trades += 1
    return RunOutcome(
        trades=trades,
        net_return=net,
        gross_return=net + cost,
        cost=cost,
        equity_curve=[],
        returns=returns,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-version", required=True)
    ap.add_argument("--instrument", default="XAUUSD")
    ap.add_argument("--venue", default="MT5")
    ap.add_argument("--timeframe", default="15m")
    ap.add_argument(
        "--family",
        default="trend",
        choices=[f.value for f in BOUNDED_PARAM_SPACE],
    )
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--test-fraction", type=float, default=0.15)
    ap.add_argument("--purge-bars", type=int, default=96, help="bars removed before the test boundary")
    ap.add_argument("--embargo-bars", type=int, default=96, help="gap left after the test window")
    ap.add_argument("--quantity", type=float, default=0.01, help="order size in lots")
    ap.add_argument("--spread-bps", type=float, default=3.0)
    ap.add_argument("--slippage-bps", type=float, default=2.0)
    ap.add_argument("--commission-per-lot", type=float, default=7.0)
    ap.add_argument("--stop-distance-usd", type=float, default=None)
    ap.add_argument("--max-hold-bars", type=int, default=None)
    ap.add_argument("--max-drawdown", type=float, default=0.20)
    ap.add_argument("--cost-source", default="")
    ap.add_argument("--cost-basis", default="ASSUMED", choices=["ASSUMED", "MEASURED"])
    ap.add_argument("--out", default="data/evidence/walkforward_research.json")
    args = ap.parse_args(argv)

    store = SqliteParquetDataStore()
    manifest = store.manifest(args.data_version)
    if manifest is None:
        print(f"no manifest for data version {args.data_version}", file=sys.stderr)
        return 2

    instrument = Instrument(
        symbol=args.instrument, venue=args.venue, asset_class=AssetClass.METAL
    )
    bars = store.read_bars(instrument, args.timeframe, version=args.data_version)
    if not bars:
        print("no bars readable for that version/timeframe", file=sys.stderr)
        return 2

    start = min(b.open_time for b in bars).astimezone(UTC)
    end = max(b.close_time for b in bars).astimezone(UTC)
    bar_seconds = int((bars[1].open_time - bars[0].open_time).total_seconds()) if len(bars) > 1 else 900

    folds = build_folds(
        start,
        end,
        n_folds=args.folds,
        test_fraction=args.test_fraction,
        purge_bars=args.purge_bars,
        embargo_bars=args.embargo_bars,
        bar_seconds=bar_seconds,
    )

    exit_rules: dict[str, object] | None = None
    if args.stop_distance_usd or args.max_hold_bars:
        exit_rules = {}
        if args.stop_distance_usd:
            exit_rules["stop_distance_usd"] = args.stop_distance_usd
        if args.max_hold_bars:
            exit_rules["max_hold_bars"] = args.max_hold_bars

    matching = MatchingConfig(
        spread_bps=args.spread_bps,
        slippage_bps=args.slippage_bps,
        commission_per_lot=args.commission_per_lot,
    )
    engine = BacktestEngine(
        data_store=store, matching_config=matching, initial_balance=10000.0
    )

    runner = make_runner(
        engine,
        instrument,
        args.timeframe,
        args.data_version,
        args.family,
        exit_rules=exit_rules,
        quantity=args.quantity,
    )

    param_space = {
        k: list(v) for k, v in BOUNDED_PARAM_SPACE[StrategyFamily(args.family)].items()
    }

    baseline = buy_and_hold_baseline(
        bars,
        folds,
        quantity=args.quantity,
        contract_size=float(instrument.contract_size),
        spread_bps=args.spread_bps,
        slippage_bps=args.slippage_bps,
        commission_per_lot=args.commission_per_lot,
    )

    result = run_walk_forward(
        runner,
        param_space,
        folds,
        baseline_outcomes={"buy_and_hold": baseline},
        periods_per_year=PERIODS_PER_YEAR,
        cost_basis=args.cost_basis,
        cost_source=args.cost_source,
        data_version=args.data_version,
        instrument=args.instrument,
        timeframe=args.timeframe,
        max_drawdown_limit=args.max_drawdown,
    )

    path = write_report(result, args.out)

    agg = result.aggregate
    print(f"\n=== walk-forward: {args.family} on {args.data_version} ===")
    print(f"folds={agg['folds_evaluated']}  trades={agg['total_trades']}  "
          f"configs tried={result.total_configurations_tried}")
    print(f"OOS net    : {agg['oos_net_return']:+.2f} USD")
    print(f"OOS gross  : {agg['oos_gross_return']:+.2f} USD   cost: {agg['oos_cost']:.2f} USD")
    print(f"expectancy : {agg['expectancy_per_trade']:+.4f} USD/trade")
    print(f"profitable folds: {agg['profitable_folds']}/{agg['folds_evaluated']}  "
          f"worst fold: {agg['worst_fold']:+.2f}")
    print(f"max DD     : {agg['max_drawdown']:.2%}   mean fold Sharpe: {agg['sharpe']:.3f}")
    of = result.overfitting
    print(f"deflated Sharpe p = {of['deflated_sharpe_pvalue']:.4f} "
          f"({'survives' if of['survives_multiple_testing'] else 'FAILS'} multiple testing)")
    bh = result.baselines.get("buy_and_hold", {})
    if bh:
        print(
            f"baseline buy&hold: {bh['net_return']:+.2f} USD over the same windows "
            f"({'strategy beats it' if bh.get('beats_strategy') else 'STRATEGY DOES NOT BEAT HOLDING'})"
        )
    print(f"\nVERDICT: {result.verdict}")
    for r in result.reasons:
        print(f"  - {r}")
    print(f"\nreport: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
