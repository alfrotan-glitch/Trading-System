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
@click.option(
    "--source",
    default=None,
    help=(
        "provenance label recorded on every bar and in the manifest "
        "(e.g. REAL:dukascopy:...). Free text: the provenance classifier "
        "reads it, so a fixed choice list would make real history unlabelable."
    ),
)
@click.option("--path", required=True)
@click.option("--instrument", default="XAUUSD")
@click.option("--timeframe", default="1m")
@click.option("--venue", default="MT5")
@click.option(
    "--session-calendar",
    default=None,
    help=(
        "explicit market-hours calendar (e.g. XAUUSD) separating scheduled closures "
        "from genuinely missing bars. Omit to grade against the calendar span only."
    ),
)
def data_ingest(
    source: str, path: str, instrument: str, timeframe: str, venue: str, session_calendar: str | None
) -> None:
    store = SqliteParquetDataStore()
    version = ingest_csv(
        Path(path),
        instrument=instrument,
        timeframe=timeframe,
        venue=venue,
        store=store,
        source=source,
        session_calendar=session_calendar,
    )
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


@data.command("mt5-depth")
@click.option("--symbol", default=None, help="Broker symbol (default: from the setup file).")
@click.option("--json-out", default=None)
def data_mt5_depth(symbol: str | None, json_out: str | None) -> None:
    """How much history does the terminal actually hold? Read-only, no download.

    Answers the question the 15m benchmark audit is blocked on, in seconds
    instead of after a full acquisition run.

    It distinguishes two things one big query cannot:

    * **M15 bar depth** — asked positionally via ``copy_rates_from_pos``, so it
      is not subject to the range-request failure that made the old 365-day
      probe fail. Bars are what the frozen benchmark needs, and this has never
      been measured on any terminal.
    * **tick depth** — probed as several small one-hour windows at increasing
      age, because a single oversized request failing is evidence of a
      REQUEST-SIZE limit and not of a RETENTION limit.

    Submits nothing and calls no order API.
    """
    from qts.config.wizard import load_setup
    from qts.data.mt5_depth import markdown, probe

    saved = load_setup()
    resolved = symbol or saved.get("symbol") or "XAUUSD"
    symbol_map = saved.get("symbol_map")
    if isinstance(symbol_map, dict):
        from qts.adapters.mt5_adapter import broker_symbol as to_broker

        resolved = to_broker(resolved, symbol_map)

    mt5 = None
    try:
        import MetaTrader5 as mt5_module  # type: ignore[import-not-found]

        mt5 = mt5_module
        initialized = mt5.initialize(path=saved.get("terminal_path") or None)
        if not initialized:
            click.echo(
                f"MT5 initialize failed: {mt5.last_error()} — this command must run "
                "on the Windows machine with the DEMO terminal open",
                err=True,
            )
            raise SystemExit(2)
    except ImportError:
        click.echo(
            "MetaTrader5 package unavailable (Windows + a running terminal required). "
            "No history was queried and nothing was fabricated.",
            err=True,
        )
        raise SystemExit(2) from None

    report = probe(mt5, resolved)
    click.echo(markdown(report))
    if json_out:
        Path(json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(json_out).write_text(
            __import__("json").dumps(report.as_dict(), indent=2, default=str), encoding="utf-8"
        )
        click.echo(f"report written to {json_out}")


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


