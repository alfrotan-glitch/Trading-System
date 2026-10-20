"""QTS CLI — research."""

from __future__ import annotations

import json
from pathlib import Path

import click

from qts.data.store import SqliteParquetDataStore
from qts.research.agent import NullAgent
from qts.research.experiment import ExperimentStore


@click.group()
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


@research.command("impulse")
@click.option("--data-version", default=None, help="usable data version (default: latest usable)")
@click.option("--root", default="data", help="data root directory")
@click.option("--ledger-db", default=None, help="trial ledger SQLite (default: <root>/sqlite/qts.db)")
@click.option("--out", default=None, help="evidence JSON (default: <root>/evidence/impulse_research.json)")
@click.option("--report-out", default=None, help="optional markdown report path")
@click.option("--seed", default=42, type=int)
def research_impulse(
    data_version: str | None, root: str, ledger_db: str | None, out: str | None, report_out: str | None, seed: int
) -> None:
    """Impulse-continuation event study (RESEARCH ONLY — never enables trading).

    Fail-closed: exits non-zero with an honest message when no usable dataset
    exists. Never fabricates data, never promotes anything, never touches
    live eligibility or order submission.
    """
    from qts.research.impulse import ImpulseResearchConfig, render_markdown_report, run_impulse_research

    root_p = Path(root)
    ledger_path = Path(ledger_db) if ledger_db else root_p / "sqlite" / "qts.db"
    out_path = Path(out) if out else root_p / "evidence" / "impulse_research.json"
    store = SqliteParquetDataStore(root=root_p)
    try:
        try:
            evidence = run_impulse_research(
                store,
                data_version=data_version,
                cfg=ImpulseResearchConfig(seed=seed),
                ledger_db_path=ledger_path,
                partition_db_path=ledger_path,
                evidence_dir=root_p / "evidence",
            )
        except ValueError as e:
            raise click.ClickException(str(e)) from e
    finally:
        store.close()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")
    if report_out:
        rp = Path(report_out)
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(render_markdown_report(evidence), encoding="utf-8")

    concl = evidence["conclusion"]
    t = evidence["analysis"]["totals"]
    click.echo(f"mode: {evidence['mode']}")
    click.echo(
        f"data: {evidence['provenance']['data_version']} class={evidence['provenance']['data_class']} "
        f"bars={evidence['provenance']['bars_read']}"
    )
    click.echo(
        f"event-study units: detected={t['events_detected_total']} family-scoped event records; "
        f"primary_outcomes={t.get('primary_outcomes_measured_total', t['events_detected_total'])}; "
        f"all_horizon_outcomes={t.get('all_horizon_outcomes_measured_total', t['events_measured_total'])}; "
        f"excluded={t['events_excluded_total']} trials_recorded={t['trials_recorded']}"
    )
    click.echo("event-study outcomes: see the human-readable report; units are measured event outcomes, not executed trades")
    click.echo(f"conclusion: {concl['conclusion']} (research {concl['go_block']})")
    for reason in concl["reasons"]:
        click.echo(f"  - {reason}")
    click.echo(f"evidence: {out_path}")
    click.echo("promotion: BLOCKED — research artifact only; live eligibility untouched")



@research.command("campaign")
@click.option(
    "--family", default="trend", type=click.Choice(["trend", "breakout", "mean_reversion", "momentum", "volatility"])
)
@click.option("--symbol", default="XAUUSD")
@click.option("--timeframe", default="1H")
@click.option("--data-version", required=True)
@click.option("--trials", default=12, type=int)
@click.option("--max-runtime", default=60, type=int)
def research_campaign(
    family: str, symbol: str, timeframe: str, data_version: str, trials: int, max_runtime: int
) -> None:
    from qts.research.campaign import CampaignConfig, run_campaign

    cfg = CampaignConfig(
        name=f"campaign-{family}",
        symbol=symbol,
        timeframe=timeframe,
        data_version=data_version,
        family=family,
        max_trials=trials,
        max_runtime_s=max_runtime,
        max_param_combinations=trials,
    )
    click.echo(f"launching bounded campaign family={family} trials={trials}")
    summary = run_campaign(cfg)
    from qts.config.paths import artifact_path

    campaign_path = artifact_path("campaign_last")
    campaign_path.parent.mkdir(parents=True, exist_ok=True)
    campaign_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    click.echo(
        f"campaign {summary['campaign_id']} completed: passed={summary['passed']} failed={summary['failed']} total={summary['total_trials']} DSR N={summary['dsr_trial_count']}"
    )
    if summary["passed"] == 0:
        click.echo("BLOCK — no candidate survived scientific gates — keep NO_TRADE")


@research.command("autonomous")
@click.option("--name", default="autonomous-search")
@click.option("--symbol", default="XAUUSD")
@click.option("--timeframe", default="1H")
@click.option("--data-version", default=None)
@click.option("--trials", default=12, type=int)
@click.option("--max-runtime", default=60, type=int)
@click.option("--seed", default=42, type=int)
def research_autonomous(
    name: str, symbol: str, timeframe: str, data_version: str | None, trials: int, max_runtime: int, seed: int
) -> None:
    from qts.research.campaign_engine import run_autonomous_campaign

    click.echo(f"launching autonomous campaign {name} trials={trials} (11 steps, never LIVE)")
    result = run_autonomous_campaign(name, symbol, timeframe, data_version, trials, max_runtime, seed)
    from qts.config.paths import artifact_path

    autonomous_path = artifact_path("autonomous_campaign")
    autonomous_path.parent.mkdir(parents=True, exist_ok=True)
    autonomous_path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    ev = result["evidence_portfolio"]
    click.echo(
        f"autonomous completed: trials {result['summary']['total_trials']} passed {result['summary']['passed']} distinct {result['novelty']['distinct_hypotheses']}"
    )
    click.echo(f"self-audit verdict {result['self_audit']['verdict']}")
    click.echo(f"overall {ev['overall']}")
    if ev["overall"].startswith("BLOCK"):
        click.echo("BLOCK — keep NO_TRADE — no genuine economic edge demonstrated")


@research.command("hypotheses")
def research_hypotheses() -> None:
    """List registered hypotheses. None is a validated trading opportunity."""
    from qts.research.catalog import list_hypotheses

    for row in list_hypotheses():
        click.echo(f"{row['id']}\t{row['edge_status']}\t{row['question']}")


@research.command(
    "run-hypothesis",
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
)
@click.argument("hypothesis_id")
@click.pass_context
def research_run_hypothesis(ctx: click.Context, hypothesis_id: str) -> None:
    """Run one registered hypothesis. Does not authorize trading."""
    from qts.research.catalog import dispatch_hypothesis

    raise SystemExit(dispatch_hypothesis(hypothesis_id, list(ctx.args)))




@research.command("adaptive-xauusd")
@click.option("--input", "input_path", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--timestamp-column", default="timestamp", show_default=True)
@click.option("--out", "out_path", default=Path("data/evidence/adaptive_xauusd.json"), type=click.Path(dir_okay=False, path_type=Path))
@click.option("--initial-equity", default=10000.0, type=float, show_default=True)
@click.option("--spread-bps", default=3.0, type=float, show_default=True, help="Full spread in basis points; an assumption unless measured.")
@click.option("--slippage-bps", default=2.0, type=float, show_default=True, help="Slippage per side in basis points; an assumption unless measured.")
@click.option("--commission-per-lot-side", default=7.0, type=float, show_default=True)
@click.option("--financing-bps-per-day", default=0.0, type=float, show_default=True)
@click.option("--cost-basis", default="ASSUMED", type=click.Choice(["ASSUMED", "SENSITIVITY"], case_sensitive=False), show_default=True, help="Label for the supplied costs; MEASURED is reserved for broker-evidence-backed models.")
@click.option("--lookback", default=252, type=int, show_default=True)
@click.option("--min-observations", default=30, type=int, show_default=True)
@click.option("--train-fraction", default=0.70, type=click.FloatRange(min=0.5, max=0.9), show_default=True, help="Chronological training fraction; remaining bars are held out.")
def research_adaptive_xauusd(
    input_path: Path, timestamp_column: str, out_path: Path, initial_equity: float,
    spread_bps: float, slippage_bps: float, commission_per_lot_side: float,
    financing_bps_per_day: float, cost_basis: str, lookback: int, min_observations: int,
    train_fraction: float,
) -> None:
    """Run causal regime-aware XAUUSD routing on an OHLC CSV (diagnostic only)."""
    from collections import Counter
    from decimal import Decimal

    import numpy as np
    import pandas as pd

    from qts.data.quality import MAX_UNEXPECTED_MISSING_FRACTION, analyze_gap_semantics
    from qts.data.sessions import closure_intervals
    from qts.domain.value_objects import AssetClass, Bar, Instrument
    from qts.research.longhistory.adaptive_backtest import build_adaptive_plan
    from qts.research.longhistory.adaptive_router import AdaptiveRoutingConfig
    from qts.research.longhistory.engine import CostModel, RunResult, run_plan
    from qts.research.longhistory.signals import donchian, ma_cross, rsi2

    if not np.isfinite(initial_equity) or initial_equity <= 0:
        raise click.ClickException("--initial-equity must be finite and positive")
    if lookback < 2 or min_observations < 2 or min_observations > lookback:
        raise click.ClickException("require lookback >= min-observations >= 2")
    if not cost_basis.strip():
        raise click.ClickException("--cost-basis cannot be empty")

    try:
        raw = pd.read_csv(input_path)
        timestamp_name = timestamp_column
        if timestamp_name not in raw.columns:
            matches = [str(c) for c in raw.columns if str(c).lower() == timestamp_column.lower()]
            if len(matches) == 1:
                timestamp_name = matches[0]
            elif not matches and timestamp_column == "timestamp":
                common_time_columns = [
                    str(c) for c in raw.columns if str(c).lower() in {"time", "open_time"}
                ]
                if len(common_time_columns) != 1:
                    raise ValueError(
                        "timestamp column not found; provide --timestamp-column "
                        "or include exactly one of 'time'/'open_time'"
                    )
                timestamp_name = common_time_columns[0]
            else:
                raise ValueError(f"timestamp column {timestamp_column!r} not found")
        raw = raw.rename(columns={c: str(c).lower() for c in raw.columns if c != timestamp_name})
        raw = raw.rename(columns={timestamp_name: "timestamp"})
        raw["timestamp"] = pd.to_datetime(raw["timestamp"], utc=True, errors="raise")
        bars = raw.set_index("timestamp").sort_index()
        bars.index = pd.DatetimeIndex(bars.index)
        if bars.index.has_duplicates:
            raise ValueError("duplicate timestamps found; refusing to silently discard market bars")
        required = ["open", "high", "low", "close"]
        missing = [c for c in required if c not in bars.columns]
        if missing:
            raise ValueError(f"missing OHLC columns: {', '.join(missing)}")
        bars = bars[required].astype(float)
        if len(bars) < 300:
            raise ValueError(f"only {len(bars)} bars available; at least 300 are required")
        values = bars.to_numpy()
        if not np.isfinite(values).all() or (values <= 0).any():
            raise ValueError("OHLC data must be finite and positive")
        if (bars["high"] < bars[["open", "close", "low"]].max(axis=1)).any():
            raise ValueError("high is inconsistent with open/close/low")
        if (bars["low"] > bars[["open", "close", "high"]].min(axis=1)).any():
            raise ValueError("low is inconsistent with open/close/high")

        deltas = bars.index.to_series().diff().dropna().dt.total_seconds().astype(int)
        cadence_seconds = Counter(deltas).most_common(1)[0][0]
        timeframe_by_seconds = {
            60: "1m", 300: "5m", 900: "15m", 1800: "30m",
            3600: "1H", 14400: "4H", 86400: "1D",
        }
        timeframe = timeframe_by_seconds.get(cadence_seconds)
        if timeframe is None:
            raise ValueError(
                f"unsupported inferred bar cadence {cadence_seconds}s; "
                "supported cadences are 1m, 5m, 15m, 30m, 1H, 4H, and 1D"
            )
        instrument = Instrument(symbol="XAUUSD", venue="CSV", asset_class=AssetClass.METAL)
        bar_records = [
            Bar(
                instrument=instrument,
                open=Decimal(str(row["open"])),
                high=Decimal(str(row["high"])),
                low=Decimal(str(row["low"])),
                close=Decimal(str(row["close"])),
                open_time=timestamp.to_pydatetime(),
                close_time=(timestamp + pd.Timedelta(seconds=cadence_seconds)).to_pydatetime(),
                source="CSV",
            )
            for timestamp, row in bars.iterrows()
        ]
        quality_end = (bars.index[-1] + pd.Timedelta(seconds=cadence_seconds)).to_pydatetime()
        known_closures = closure_intervals(
            bars.index[0].to_pydatetime(), quality_end, symbol="XAUUSD"
        )
        gap_quality = analyze_gap_semantics(
            bar_records, timeframe, closure_intervals=known_closures
        ).as_dict()
        raw_missing_fraction = gap_quality["active_span_missing_fraction"]
        missing_fraction = (
            float(raw_missing_fraction)
            if isinstance(raw_missing_fraction, (int, float))
            else None
        )
        if (
            missing_fraction is None
            or not np.isfinite(missing_fraction)
            or missing_fraction > MAX_UNEXPECTED_MISSING_FRACTION
        ):
            measured_pct = (
                f"{missing_fraction:.2%}"
                if missing_fraction is not None and np.isfinite(missing_fraction)
                else "UNAVAILABLE"
            )
            raise ValueError(
                f"data completeness gate blocked this dataset: unexpected active-span "
                f"missing intervals={measured_pct}; maximum allowed="
                f"{MAX_UNEXPECTED_MISSING_FRACTION:.2%}. Do not interpolate or forward-fill "
                "gaps to bypass this gate."
            )

        candidates = {
            "ma_10_30": ma_cross(bars, 10, 30, 2.0),
            "ma_20_50": ma_cross(bars, 20, 50, 2.0),
            "donchian_20_10": donchian(bars, 20, 10, 2.0),
            "donchian_55_20": donchian(bars, 55, 20, 2.5),
            "rsi2_oversold_10": rsi2(bars, 10.0, False, 5),
            "rsi2_trend_10": rsi2(bars, 10.0, True, 5),
        }
        costs = CostModel(
            spread_bps=spread_bps, slippage_bps=slippage_bps,
            commission_usd_per_lot_side=commission_per_lot_side,
            financing_bps_per_day=financing_bps_per_day, basis=cost_basis,
        )
        config = AdaptiveRoutingConfig(lookback=lookback, min_observations=min_observations)
        adaptive_plan, routing, _ = build_adaptive_plan(
            bars, candidates, costs, routing_config=config, initial_equity=initial_equity
        )
        split = int(round(len(bars) * train_fraction))
        if split < max(lookback, 100) or len(bars) - split < 50:
            raise ValueError("dataset too short for the requested chronological train/holdout split")
        routed_result = run_plan(
            bars, adaptive_plan, split, len(bars), costs,
            initial_equity=initial_equity, force_close_end=True,
        )

        def summarize(result: RunResult) -> dict[str, object]:
            equity = np.asarray(result.equity, dtype=float)
            peaks = np.maximum.accumulate(equity)
            drawdown = np.divide(equity, peaks, out=np.ones_like(equity), where=peaks != 0) - 1.0
            return {
                "final_equity": result.final_equity, "net_usd": result.net_usd,
                "gross_usd": result.gross_usd, "execution_cost_usd": result.cost_usd,
                "financing_usd": result.financing_usd, "trades": len(result.trades),
                "exposure_fraction": result.exposure,
                "max_drawdown_fraction": float(drawdown.min()), "cost_basis": result.cost_basis,
            }

        candidate_metrics = {}
        for name, candidate in candidates.items():
            result = run_plan(
                bars, candidate, split, len(bars), costs,
                initial_equity=initial_equity, force_close_end=True,
            )
            candidate_metrics[name] = summarize(result)

        report = {
            "mode": "RESEARCH_DIAGNOSTIC_ONLY", "symbol": "XAUUSD",
            "data": {
                "path": str(input_path), "bars": len(bars),
                "start": bars.index[0].isoformat(), "end": bars.index[-1].isoformat(),
                "timestamp_column": timestamp_name, "timeframe": timeframe, "data_quality": {"ohlc": "passed", "gap_gate": "passed", "gap_semantics": gap_quality},
                "train_bars": split, "holdout_bars": len(bars) - split,
                "train_end": bars.index[split - 1].isoformat(),
                "holdout_start": bars.index[split].isoformat(),
                "train_fraction": train_fraction,
            },
            "evaluation": "chronological holdout; parameters and candidate set fixed before the holdout; router may adapt causally using prior holdout outcomes",
            "cost_model": costs.describe(),
            "routing_config": {
                "lookback": lookback, "min_observations": min_observations,
                "candidate_count": len(candidates), "same_regime_only": True,
                "current_bar_return_excluded_from_selection": True,
            },
            "adaptive_router": summarize(routed_result),
            "candidate_strategies": candidate_metrics,
            "selection_counts": {str(k): int(v) for k, v in routing["selected_strategy"].value_counts(dropna=False).items()},
            "regime_counts": {str(k): int(v) for k, v in routing["regime"].value_counts().items()},
            "limitations": [
                "Holdout is one chronological split, not proof of robustness across multiple market cycles.",
                "Router adapts during the holdout using only previously realized returns; candidate parameters remain fixed.",
                "Cost assumptions must be replaced with broker-measured spread, slippage, commission and directional rollover.",
                "No profitability guarantee; no broker orders are sent and live eligibility is unchanged.",
                "OHLC bar backtests cannot model all intrabar price paths.",
            ],
        }
    except (ValueError, KeyError, TypeError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    metrics = summarize(routed_result)
    click.echo(f"data: XAUUSD bars={len(bars)} {bars.index[0]} -> {bars.index[-1]}")
    click.echo(f"holdout: {len(bars) - split} bars starting {bars.index[split]}")
    click.echo(f"cost basis: {cost_basis}; spread={spread_bps}bps; slippage={slippage_bps}bps/side; commission={commission_per_lot_side} USD/lot/side")
    click.echo(f"adaptive HOLDOUT metrics: {json.dumps(metrics, sort_keys=True)}")
    click.echo(f"evidence: {out_path}")
    click.echo("verdict: DIAGNOSTIC ONLY — no out-of-sample edge validation and no live trading authorization")
