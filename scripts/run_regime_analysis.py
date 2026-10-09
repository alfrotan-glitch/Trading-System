#!/usr/bin/env python
"""Attribute a strategy's P&L to market regimes.

A walk-forward average can hide everything that matters. A rule that makes
money only while gold is trending up is not an edge; it is a long position
with extra steps. This attributes every trade to the regime that was in
effect when it was opened, so a result concentrated in one regime is visible
instead of averaged away.

Regimes are defined from information available at the time of the trade — a
trailing moving average of *prior* daily closes — so this attribution cannot
peek into the future.

Usage
-----
    python scripts/run_regime_analysis.py \\
        --data-version <version> --family breakout \\
        --strategy-params '{"period": 20}' \\
        --stop-distance-usd 40 --max-hold-bars 96
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from qts.adapters.matching import MatchingConfig  # noqa: E402
from qts.backtest.engine import BacktestEngine  # noqa: E402
from qts.data.store import SqliteParquetDataStore  # noqa: E402
from qts.domain.value_objects import AssetClass, Instrument  # noqa: E402

SCHEMA = "qts.regime_analysis.v1"


def daily_regimes(bars: list, sma_window: int = 50) -> dict[int, str]:
    """Map each bar index to the regime in force, using only prior daily closes.

    Bars are bucketed by UTC date; a bar is UPTREND when the last *completed*
    daily close sits above the trailing mean of the previous ``sma_window``
    daily closes. The current day's own close is excluded, so the label for a
    bar never depends on data from its own day's end.
    """
    by_day: dict[str, list] = defaultdict(list)
    for idx, bar in enumerate(bars):
        by_day[bar.open_time.astimezone(UTC).date().isoformat()].append(idx)

    days = sorted(by_day)
    closes = []
    for day in days:
        last_idx = by_day[day][-1]
        closes.append(float(bars[last_idx].close))

    day_regime: dict[str, str] = {}
    for i, day in enumerate(days):
        if i < sma_window:
            day_regime[day] = "WARMUP"
            continue
        window = closes[i - sma_window : i]  # prior days only, not today
        mean = sum(window) / len(window)
        day_regime[day] = "UPTREND" if closes[i] > mean else "DOWNTREND"

    regime_of: dict[int, str] = {}
    for day in days:
        for idx in by_day[day]:
            regime_of[idx] = day_regime[day]
    return regime_of


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-version", required=True)
    ap.add_argument("--instrument", default="XAUUSD")
    ap.add_argument("--timeframe", default="15m")
    ap.add_argument("--family", default="breakout")
    ap.add_argument("--strategy-params", default="{}")
    ap.add_argument("--stop-distance-usd", type=float, default=40.0)
    ap.add_argument("--max-hold-bars", type=int, default=96)
    ap.add_argument("--quantity", type=float, default=0.01)
    ap.add_argument("--spread-bps", type=float, default=3.0)
    ap.add_argument("--slippage-bps", type=float, default=2.0)
    ap.add_argument("--commission-per-lot", type=float, default=7.0)
    ap.add_argument("--out", default="data/evidence/regime_analysis.json")
    args = ap.parse_args(argv)

    store = SqliteParquetDataStore()
    instrument = Instrument(
        symbol=args.instrument, venue="MT5", asset_class=AssetClass.METAL
    )
    bars = store.read_bars(instrument, args.timeframe, version=args.data_version)
    if not bars:
        print("no bars readable", file=sys.stderr)
        return 2
    bars = sorted(bars, key=lambda b: b.open_time)

    exit_rules = {
        "stop_distance_usd": args.stop_distance_usd,
        "max_hold_bars": args.max_hold_bars,
    }
    matching = MatchingConfig(
        spread_bps=args.spread_bps,
        slippage_bps=args.slippage_bps,
        commission_per_lot=args.commission_per_lot,
    )
    # Same reasoning as the research pipeline: a backtest must measure the
    # strategy, not the risk overlay. The default kill switch truncates the
    # run at the first 5% drawdown, which would silently confine every
    # attributed trade to the opening weeks of the series.
    from decimal import Decimal

    from qts.risk.engine import RiskLimits

    research_limits = RiskLimits(
        kill_switch_enabled=False,
        max_drawdown=Decimal("1000000"),
        daily_loss_limit=Decimal("1000000"),
        max_notional=Decimal("100000000"),
        max_exposure_lots=Decimal("1000"),
    )

    engine = BacktestEngine(
        data_store=store,
        matching_config=matching,
        risk_limits=research_limits,
        initial_balance=10000.0,
    )
    params = json.loads(args.strategy_params)

    result = engine.run(
        instrument=instrument,
        timeframe=args.timeframe,
        data_version=args.data_version,
        strategy_id=f"{args.family}_regime",
        strategy_params={**params, "_family": args.family, "quantity": args.quantity},
        exit_rules=exit_rules,
    )

    regime_of = daily_regimes(bars)
    contract = float(instrument.contract_size)

    # Attribute P&L using the ENGINE's own equity curve, not a reconstruction.
    #
    # Pairing fills entry->exit looked reasonable and was wrong: the engine
    # emits reversals as well as exits, so fills do not strictly alternate, and
    # a reversal's quantity is larger than the closing one. Reconstructing P&L
    # from that sequence produced a total that disagreed with the run's actual
    # final equity. Attributing the per-bar equity change to the regime of that
    # bar needs no pairing assumption, and costs are already inside the equity.
    equity = list(result.equity_curve or [])
    by_regime: dict[str, dict[str, float]] = defaultdict(
        lambda: {"round_turns": 0, "fills": 0, "net": 0.0, "cost": 0.0, "bars": 0}
    )

    for i in range(1, len(equity)):
        regime = regime_of.get(i, "UNKNOWN")
        by_regime[regime]["net"] += float(equity[i]) - float(equity[i - 1])

    for fill in result.fills:
        idx = int(fill.get("bar_idx", -1))
        regime = regime_of.get(idx, "UNKNOWN")
        price = float(fill.get("price") or 0)
        ref = float(fill.get("bar_open") or 0)
        qty = float(fill.get("qty") or 0)
        fee = float(fill.get("fee") or 0)
        friction = abs(price - ref) * qty * contract if ref > 0 else 0.0
        by_regime[regime]["cost"] += friction + fee
        by_regime[regime]["fills"] += 1
        # Round turns are half the fills: two fills close one round turn.
        by_regime[regime]["round_turns"] = by_regime[regime]["fills"] // 2

    for regime in regime_of.values():
        by_regime[regime]["bars"] += 1

    total_bars = len(bars)
    composition = defaultdict(int)
    for regime in regime_of.values():
        composition[regime] += 1

    report = {
        "schema": SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(),
        "data_version": args.data_version,
        "family": args.family,
        "strategy_params": params,
        "exit_rules": exit_rules,
        "cost_basis": "ASSUMED",
        "total_bars": total_bars,
        "dataset_span_days": (bars[-1].close_time - bars[0].open_time).days,
        "total_round_turns": result.trades,
        "regimes": {},
    }
    for regime, stats in sorted(by_regime.items()):
        n = stats["round_turns"]
        report["regimes"][regime] = {
            **stats,
            "expectancy_per_trade": (stats["net"] / n) if n else 0.0,
            "net_of_cost": stats["net"] - stats["cost"],
            "share_of_bars": composition.get(regime, 0) / total_bars if total_bars else 0.0,
        }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(f"\n=== regime attribution: {args.family} {params} ===")
    print(f"dataset: {report['dataset_span_days']} days, {total_bars} bars, "
          f"{result.trades} fills ({sum(r['round_turns'] for r in report['regimes'].values())} round turns)\n")
    print(f"{'regime':<11} {'trades':>7} {'net USD':>11} {'expect':>9} {'cost':>11} {'bars%':>7}")
    for regime, s in report["regimes"].items():
        print(f"{regime:<11} {s['round_turns']:>7} {s['net']:>11.2f} "
              f"{s['expectancy_per_trade']:>9.2f} {s['cost']:>11.2f} "
              f"{s['share_of_bars']*100:>6.1f}%")
    print(f"\nreport: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
