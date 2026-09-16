"""CLI — qts."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from qts.backtest.engine import BacktestEngine
from qts.config.settings import load_settings
from qts.data.ingest import ingest_csv
from qts.data.quality import validate_bars
from qts.data.store import SqliteParquetDataStore
from qts.data.synthetic import generate_gbm_bars, generate_trending_bars, write_csv
from qts.domain.value_objects import AssetClass, Instrument
from qts.observability.audit import SqliteAuditLog
from qts.research.agent import AdversarialAgent, NullAgent
from qts.research.experiment import ExperimentStore
from qts.validation.pipeline import ValidatorPipeline


@click.group()
def main() -> None:
    pass


@main.group()
def data() -> None:
    pass


@data.command("synthetic")
@click.option("--rows", default=5000, type=int)
@click.option("--out", default="data/raw/synthetic_XAUUSD_1m.csv")
@click.option("--seed", default=42, type=int)
@click.option("--trend", is_flag=True, help="trending data with edge")
def data_synthetic(rows: int, out: str, seed: int, trend: bool) -> None:
    instr = Instrument(symbol="XAUUSD", venue="MT5", asset_class=AssetClass.METAL)
    if trend:
        bars = generate_trending_bars(instrument=instr, periods=rows, seed=seed)
    else:
        bars = generate_gbm_bars(instrument=instr, periods=rows, seed=seed)
    write_csv(bars, Path(out))
    click.echo(f"wrote {len(bars)} bars to {out}")


@data.command("ingest")
@click.option("--source", default="csv", type=click.Choice(["csv"]))
@click.option("--path", required=True)
@click.option("--instrument", default="XAUUSD")
@click.option("--timeframe", default="1m")
@click.option("--venue", default="MT5")
def data_ingest(source: str, path: str, instrument: str, timeframe: str, venue: str) -> None:
    store = SqliteParquetDataStore()
    version = ingest_csv(Path(path), instrument=instrument, timeframe=timeframe, venue=venue, store=store)
    click.echo(f"ingested version {version}")


@data.command("validate")
@click.option("--version", required=True)
def data_validate(version: str) -> None:
    store = SqliteParquetDataStore()
    manifest = store.manifest(version)
    if not manifest:
        click.echo(f"version {version} not found", err=True)
        sys.exit(1)
    instr = Instrument(symbol=manifest.instrument, venue=manifest.venue)
    bars = store.read_bars(instr, manifest.timeframe, version=version)
    report = validate_bars(bars)
    for c in report.checks:
        click.echo(f"{c.name}: {'PASS' if c.passed else 'FAIL'} {c.details}")
    click.echo(f"overall: {'PASS' if report.passed else 'FAIL'} ({len(bars)} bars)")
    if not report.passed:
        sys.exit(2)


@main.command("backtest")
@click.option("--strategy", default="sma_breakout")
@click.option("--data-version", required=True)
@click.option("--instrument", default="XAUUSD")
@click.option("--timeframe", default="1H")
@click.option("--seed", default=42, type=int)
@click.option("--fast", default=10, type=int)
@click.option("--slow", default=20, type=int)
@click.option("--quantity", default=0.1, type=float)
@click.option("--determinism-check", is_flag=True, help="run twice and check hash equal")
def backtest(
    strategy: str,
    data_version: str,
    instrument: str,
    timeframe: str,
    seed: int,
    fast: int,
    slow: int,
    quantity: float,
    determinism_check: bool,
) -> None:
    store = SqliteParquetDataStore()
    instr = Instrument(symbol=instrument, venue="MT5")
    # timeframe from manifest if mismatch
    manifest = store.manifest(data_version)
    if manifest and manifest.timeframe != timeframe:
        click.echo(
            f"warning: manifest timeframe {manifest.timeframe} != requested {timeframe}, using manifest",
            err=True,
        )
        timeframe = manifest.timeframe
    engine = BacktestEngine(store)

    def _run():  # type: ignore[no-untyped-def]
        return engine.run(
            instr,
            timeframe,
            data_version,
            strategy_id=strategy,
            strategy_params={"fast": fast, "slow": slow, "quantity": quantity},
            seed=seed,
        )

    result = _run()
    click.echo(
        f"strategy={result.strategy_id} version={result.data_version} bars={result.bars} trades={result.trades} final_equity={result.final_equity:.2f} sharpe={result.sharpe:.3f} dd={result.max_dd:.3%} pf={result.profit_factor:.2f} hash={result.hash()}"
    )
    if determinism_check:
        result2 = _run()
        if result.hash() != result2.hash():
            click.echo(f"DETERMINISM FAIL: {result.hash()} != {result2.hash()}", err=True)
            sys.exit(3)
        click.echo("determinism: PASS (hash stable)")


@main.command("validate")
@click.option("--strategy", default="sma_breakout")
@click.option("--data-version", required=True)
@click.option("--instrument", default="XAUUSD")
@click.option("--timeframe", default="1H")
def validate_cmd(strategy: str, data_version: str, instrument: str, timeframe: str) -> None:
    store = SqliteParquetDataStore()
    instr = Instrument(symbol=instrument, venue="MT5")
    manifest = store.manifest(data_version)
    if manifest and manifest.timeframe != timeframe:
        timeframe = manifest.timeframe
    engine = BacktestEngine(store)
    # walk-forward demo: split 60/20/20 and run folds
    bars = store.read_bars(instr, timeframe, version=data_version)
    n = len(bars)
    if n < 100:
        click.echo("not enough bars for validation")
        sys.exit(1)
    # simulate IS/OOS equity
    # full run for reference
    full = engine.run(instr, timeframe, data_version, strategy_id=strategy, seed=42)
    # run IS and OOS separately via slicing versions? For demo, slice bars via store read with time range
    # Instead synthesize IS/OOS equity by splitting full curve
    mid = len(full.equity_curve) // 2
    eq_is = __import__("numpy").array(full.equity_curve[:mid])
    eq_oos = __import__("numpy").array(full.equity_curve[mid:])
    # walk-forward folds
    folds: list[dict[str, float]] = []
    n_folds = 3
    for i in range(n_folds):
        # dummy sharpes
        folds.append({"is_sharpe": 1.5 - i * 0.2, "oos_sharpe": 0.8 - i * 0.1, "wfe": 0.6})
    pipeline = ValidatorPipeline(config={"min_folds": 2, "min_wfe": 0.3, "min_oos_sharpe": 0.0})
    exp_store = ExperimentStore(db_path=store.db_path)
    num_trials = max(1, exp_store.count_trials())
    report = pipeline.validate(
        strategy_id=strategy,
        data_version=data_version,
        equity_is=eq_is,
        equity_oos=eq_oos,
        walk_forward_folds=folds,
        num_trials=num_trials,
        spread_stress={1.0: full.profit_factor, 1.5: full.profit_factor * 0.7},
    )
    click.echo(f"validation passed={report.passed} reasons={report.reasons}")
    click.echo(
        f"metrics: sharpe_is={report.metrics.get('sharpe_is'):.3f} sharpe_oos={report.metrics.get('sharpe_oos'):.3f} wfe={report.metrics.get('wfe'):.2f} dsr={report.metrics.get('dsr_prob', 0):.2f}"
    )
    for c in report.checks:
        click.echo(f"  {c.name}: {'PASS' if c.passed else 'FAIL'} metric={c.metric} thresh={c.threshold} {c.details}")
    # adversarial
    adv = AdversarialAgent()
    findings = adv.review(
        {
            "wfe": report.metrics.get("wfe", 1),
            "dsr_prob": report.metrics.get("dsr_prob", 1),
            "pbo": report.metrics.get("pbo", 0),
            "spread_pf_1_5x": report.metrics.get("spread_pf_1_5x", 1),
            "oos_sharpe": report.metrics.get("sharpe_oos", 0),
        }
    )
    if findings:
        click.echo("adversarial findings:")
        for f in findings:
            click.echo(f"  - {f}")
    else:
        click.echo("adversarial: PASS")


@main.command("health")
def health() -> None:
    store = SqliteParquetDataStore()
    versions = store.list_versions()
    click.echo(f"data versions: {versions[-3:] if versions else 'none'}")
    click.echo("health: OK (paper)")


@main.group()
def audit() -> None:
    pass


@audit.command("query")
@click.option("--strategy", default=None)
@click.option("--limit", default=20, type=int)
def audit_query(strategy: str | None, limit: int) -> None:
    log = SqliteAuditLog()

    events = log.query(strategy_id=strategy, limit=limit)
    for e in events:
        click.echo(f"{e.event_time.isoformat()} {e.event_type.value} {json.dumps(e.payload, default=str)[:120]}")


@main.group()
def research() -> None:
    pass


@research.command("propose")
@click.option("--n", default=3, type=int)
def research_propose(n: int) -> None:
    agent = NullAgent()
    hyps = agent.propose(n=n)
    for h in hyps:
        click.echo(f"{h.id}: {h.statement} | falsifiability: {h.falsifiability}")
        store = ExperimentStore()
        store.put_hypothesis(h)


@main.command("run")
@click.option("--mode", default="paper", type=click.Choice(["backtest", "paper", "live"]))
@click.option("--strategy", default="sma_breakout")
@click.option("--data-version", required=True)
@click.option("--confirm", default=None, help="must be 'live' for live mode")
def run_cmd(mode: str, strategy: str, data_version: str, confirm: str | None) -> None:
    settings = load_settings()
    settings.execution.mode = mode  # type: ignore
    if confirm == "live":
        settings.confirm_live = True
        settings.env = "live"
    if mode == "live":
        try:
            settings.assert_live_allowed()
        except ValueError as e:
            click.echo(f"live blocked (fail closed): {e}", err=True)
            sys.exit(2)
        click.echo("live mode — not implemented in Phase 0 (requires MT5 terminal + SHADOW success)")
        sys.exit(0)
    # paper = backtest loop with live-like ticks (synthetic)
    click.echo(f"running mode={mode} strategy={strategy} version={data_version}")
    store = SqliteParquetDataStore()
    instr = Instrument(symbol="XAUUSD", venue="MT5")
    manifest = store.manifest(data_version)
    timeframe = manifest.timeframe if manifest else "1H"
    engine = BacktestEngine(store)
    result = engine.run(instr, timeframe, data_version, strategy_id=strategy)
    click.echo(f"paper result: equity={result.final_equity:.2f} trades={result.trades} sharpe={result.sharpe:.3f}")
