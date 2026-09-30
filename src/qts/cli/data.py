"""QTS CLI — data."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from qts.data.ingest import ingest_csv
from qts.data.quality import validate_bars
from qts.data.store import SqliteParquetDataStore
from qts.data.synthetic import generate_gbm_bars, generate_trending_bars, write_csv
from qts.domain.value_objects import AssetClass, Instrument


@click.group()
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


@data.command("bootstrap")
@click.option("--root", default="data", help="data root directory")
@click.option("--fixture", default=None, help="fixture CSV (default: data/fixtures/XAUUSD_1H_500.csv)")
@click.option("--instrument", default="XAUUSD")
@click.option("--timeframe", default="1H")
@click.option("--venue", default="MT5")
def data_bootstrap(root: str, fixture: str | None, instrument: str, timeframe: str, venue: str) -> None:
    """Deterministic clean-clone data bootstrap — truthful, idempotent, never fabricates.

    Exit codes: 0 = usable data present (READY or INGESTED), 1 = FAILED (missing or
    zero-bar fixture). SYNTHETIC fixture data never counts as real market history.
    """
    from pathlib import Path as _P

    from qts.data.bootstrap import bootstrap_data

    # fixture=None resolves RELATIVE TO root (default: <root>/fixtures/XAUUSD_1H_500.csv)
    fx = _P(fixture) if fixture else None
    res = bootstrap_data(root=_P(root), fixture=fx, instrument=instrument, timeframe=timeframe, venue=venue)
    for msg in res.messages:
        click.echo(msg)
    if res.ok:
        click.echo(f"bootstrap: {res.status} version={res.version} bars={res.bars} class={res.data_class}")
    else:
        click.echo("bootstrap: FAILED — no usable data established (nothing was fabricated)", err=True)
        sys.exit(1)


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


