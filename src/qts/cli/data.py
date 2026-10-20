"""QTS CLI — data."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from qts.data.ingest import ingest_csv
from qts.data.quality import validate_bars
from qts.data.sessions import closure_intervals as _closure_intervals
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

    try:
        report = probe(mt5, resolved)
    finally:
        shutdown = getattr(mt5, "shutdown", None)
        if callable(shutdown):
            shutdown()
    click.echo(markdown(report))
    if json_out:
        Path(json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(json_out).write_text(
            __import__("json").dumps(report.as_dict(), indent=2, default=str), encoding="utf-8"
        )
        click.echo(f"report written to {json_out}")


@data.command("mt5-bars")
@click.option("--symbol", default=None, help="Broker symbol (default: from the setup file).")
@click.option("--timeframe", default="M15", type=click.Choice(["M1", "M5", "M15", "M30", "H1", "H4", "D1"], case_sensitive=False))
@click.option("--count", default=20000, type=click.IntRange(min=300, max=100000), show_default=True)
@click.option("--out", "out_path", default="data/raw/mt5_xauusd_m15.csv", type=click.Path(dir_okay=False))
@click.option("--json-out", default="data/evidence/mt5_bars_acquisition.json", type=click.Path(dir_okay=False))
def data_mt5_bars(
    symbol: str | None, timeframe: str, count: int, out_path: str, json_out: str
) -> None:
    """Export real broker OHLC bars from the connected DEMO terminal (read-only)."""
    import json
    from datetime import UTC, datetime

    import numpy as np
    import pandas as pd

    from qts.config.wizard import load_setup
    from qts.data.mt5_history_acquisition import AcquisitionRefused, require_read_only_demo, resolve_symbol

    saved = load_setup()
    requested = symbol or saved.get("symbol") or "XAUUSD"
    symbol_map = saved.get("symbol_map")
    if isinstance(symbol_map, dict):
        from qts.adapters.mt5_adapter import broker_symbol as to_broker

        requested = to_broker(requested, symbol_map)

    try:
        import MetaTrader5 as mt5  # type: ignore[import-not-found]
    except ImportError:
        raise click.ClickException(
            "MetaTrader5 package unavailable; run this command on the Windows host with MT5 installed."
        ) from None

    initialized = mt5.initialize(path=saved.get("terminal_path") or None)
    if not initialized:
        raise click.ClickException(f"MT5 initialize failed: {mt5.last_error()}")
    try:
        identity = require_read_only_demo(mt5)
        actual_symbol = resolve_symbol(mt5, requested)
        tf_name = timeframe.upper()
        tf_constant_name = f"TIMEFRAME_{tf_name}"
        tf_constant = getattr(mt5, tf_constant_name, None)
        if tf_constant is None:
            raise click.ClickException(f"MT5 does not expose {tf_constant_name}")
        rates = mt5.copy_rates_from_pos(actual_symbol, tf_constant, 0, count)
        if rates is None:
            raise click.ClickException(f"MT5 bar query failed: {mt5.last_error()}")
        if len(rates) == 0:
            raise click.ClickException("MT5 returned zero bars; no dataset was written")
        frame = pd.DataFrame(rates)
        required = {"time", "open", "high", "low", "close"}
        if not required.issubset(frame.columns):
            raise click.ClickException(f"MT5 bars missing fields: {sorted(required - set(frame.columns))}")
        frame["timestamp"] = pd.to_datetime(frame["time"], unit="s", utc=True, errors="raise")
        duration_seconds = {
            "M1": 60, "M5": 300, "M15": 900, "M30": 1800,
            "H1": 3600, "H4": 14400, "D1": 86400,
        }[tf_name]
        now = datetime.now(UTC)
        complete = frame["timestamp"] + pd.to_timedelta(duration_seconds, unit="s") <= now
        dropped_incomplete = int((~complete).sum())
        frame = frame.loc[complete].copy()
        if len(frame) < 300:
            raise click.ClickException(
                f"only {len(frame)} closed bars remain after excluding the current incomplete bar; "
                "at least 300 are required"
            )
        if frame["timestamp"].duplicated().any() or not frame["timestamp"].is_monotonic_increasing:
            raise click.ClickException("broker bars have duplicate or non-monotonic timestamps; refusing export")
        prices = frame[["open", "high", "low", "close"]].to_numpy(dtype=float)
        if not np.isfinite(prices).all() or (prices <= 0).any():
            raise click.ClickException("broker OHLC contains non-finite or non-positive prices")
        if (frame["high"] < frame[["open", "close", "low"]].max(axis=1)).any():
            raise click.ClickException("broker OHLC high invariant failed")
        if (frame["low"] > frame[["open", "close", "high"]].min(axis=1)).any():
            raise click.ClickException("broker OHLC low invariant failed")

        output = frame.copy()
        output = output[["timestamp", "time", "open", "high", "low", "close"] + [
            name for name in ("tick_volume", "spread", "real_volume") if name in output.columns
        ]]
        target = Path(out_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        output.to_csv(target, index=False)
        report = {
            "schema": "qts.mt5_ohlc_acquisition.v1",
            "status": "COMPLETE",
            "data_class": "REAL_BROKER_DEMO_OHLC",
            "instrument": "XAUUSD",
            "requested_symbol": requested,
            "broker_symbol": actual_symbol,
            "timeframe": tf_name,
            "bars_requested": count,
            "bars_exported": len(output),
            "incomplete_bars_excluded": dropped_incomplete,
            "start_timestamp": output["timestamp"].iloc[0].isoformat(),
            "end_timestamp": output["timestamp"].iloc[-1].isoformat(),
            "timestamp_convention": "MT5 rates time epoch converted using the MetaTrader5 Python API UTC convention; raw epoch retained in CSV column 'time'.",
            "ohlc_validated": True,
            "tick_volume_is_not_real_volume": True,
            "spread_field_units": "broker points; not converted to USD/oz",
            "identity": identity,
            "read_only": True,
            "order_apis_called": [],
            "orders_submitted": 0,
            "csv_path": str(target),
            "limitations": [
                "The most recent incomplete bar is excluded.",
                "OHLC history does not establish executable bid/ask spread or slippage.",
                "Commission, swap and fee must be measured separately; this command does not infer them.",
                "MT5 history depth depends on terminal settings and broker retention.",
            ],
        }
        report_path = Path(json_out)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        click.echo(f"bars: {len(output)} {tf_name} {report['start_timestamp']} -> {report['end_timestamp']}")
        click.echo(f"broker symbol: {actual_symbol}; DEMO verified; read-only; orders submitted: 0")
        click.echo(f"CSV: {target}")
        click.echo(f"evidence: {report_path}")
    except AcquisitionRefused as exc:
        raise click.ClickException(f"MT5 history export refused: {exc}") from exc
    finally:
        mt5.shutdown()


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
    session_cal = getattr(manifest, "session_calendar", None)
    closures = (
        _closure_intervals(bars[0].open_time, bars[-1].close_time, symbol=session_cal)
        if session_cal and bars
        else None
    )
    report = validate_bars(bars, manifest.timeframe, closure_intervals=closures)
    for c in report.checks:
        click.echo(f"{c.name}: {'PASS' if c.passed else 'FAIL'} {c.details}")
    click.echo(f"overall: {'PASS' if report.passed else 'FAIL'} ({len(bars)} bars)")
    if not report.passed:
        sys.exit(2)


