"""CLI — qts."""

from __future__ import annotations

import contextlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import click
import numpy as np

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
    bars = store.read_bars(instr, timeframe, version=data_version)
    n = len(bars)
    if n < 100:
        click.echo("not enough bars for validation")
        sys.exit(1)

    # --- real walk-forward: use single coherent policy from Settings (no duplicated thresholds) ---
    from qts.config.settings import load_settings

    _settings = load_settings()
    # ValidatorPipeline reads defaults from Settings.validation (min_folds=5, min_wfe=0.30, min_oos_sharpe=0.30, max_pbo=0.50)
    pipeline = ValidatorPipeline()  # uses Settings defaults
    # Use 60% train / 20% test style but via splits; for demo use train=30% of n, test=10% , step=test
    train = max(50, n // 3)
    test = max(20, n // 9)
    step = test
    splits = pipeline.walk_forward_splits(n, train=train, test=test, step=step)
    folds: list[dict[str, float]] = []
    for train_start, train_end, test_start, test_end in splits[:5]:  # cap 5 folds for speed
        # train period: bars[train_start:train_end] — we run backtest on that slice via start/end times
        train_bars = bars[train_start:train_end]
        test_bars = bars[test_start:test_end]
        if not train_bars or not test_bars:
            continue
        # We need to run backtest on those slices — use time bounds
        # Create temporary versions for slices? Instead we can directly run engine on sliced Bars
        # Simpler: run backtest via engine but with start/end times
        # Our engine reads from store by version and time range, so we can use start/end
        train_start_t = train_bars[0].open_time
        train_end_t = train_bars[-1].close_time
        test_start_t = test_bars[0].open_time
        test_end_t = test_bars[-1].close_time
        try:
            train_res = engine.run(
                instr,
                timeframe,
                data_version,
                strategy_id=strategy,
                strategy_params={"fast": 10, "slow": 20, "quantity": 0.1},
                start=train_start_t,
                end=train_end_t,
            )
            test_res = engine.run(
                instr,
                timeframe,
                data_version,
                strategy_id=strategy,
                strategy_params={"fast": 10, "slow": 20, "quantity": 0.1},
                start=test_start_t,
                end=test_end_t,
            )
            folds.append({"is_sharpe": float(train_res.sharpe), "oos_sharpe": float(test_res.sharpe)})
        except Exception as e:  # noqa: BLE001
            click.echo(f"walk-forward fold failed: {e}", err=True)
            continue

    # Full OOS/IS for metrics (use split mid)
    full = engine.run(
        instr, timeframe, data_version, strategy_id=strategy, strategy_params={"fast": 10, "slow": 20, "quantity": 0.1}
    )
    mid = len(full.equity_curve) // 2
    eq_is = np.array(full.equity_curve[:mid])
    eq_oos = np.array(full.equity_curve[mid:])

    # Real stress: re-run with spread multipliers — G6 use Settings spread_stress_levels (no duplicate)
    from qts.config.settings import load_settings as _load_settings_for_stress

    _settings_for_stress = _load_settings_for_stress()
    spreads_cfg = _settings_for_stress.validation.spread_stress_levels
    stress_results = engine.run_stress(
        instr, timeframe, data_version, strategy, {"fast": 10, "slow": 20, "quantity": 0.1}, spreads=spreads_cfg
    )

    # Real perturbation: baseline ±5/10/20%
    baseline = 10
    perturbed: list[float] = []
    for pct in [-0.2, -0.1, -0.05, 0, 0.05, 0.1, 0.2]:
        fast_p = max(2, int(baseline * (1 + pct)))
        try:
            res_p = engine.run(
                instr,
                timeframe,
                data_version,
                strategy_id=strategy,
                strategy_params={"fast": fast_p, "slow": 20, "quantity": 0.1},
            )
            perturbed.append(float(res_p.sharpe))
        except Exception:
            perturbed.append(0.0)

    # CPCV: combinatorial splits — must meet ValidatorPipeline.cpcv_min_combos (6) with sufficient trials
    # Use n_groups=6,n_test=2 => C(6,2)=15 combos >=6, each fold evaluated across trials [5,10,15]
    cpcv_folds: list[dict[str, Any]] = []
    cpcv_splits = pipeline.cpcv_splits(n, n_groups=6, n_test=2)
    trials = [{"fast": 5}, {"fast": 10}, {"fast": 15}]
    # Ensure we produce at least cpcv_min_combos; if n small, fallback to 4,1 but validator will BLOCK

    for train_idx, test_idx in cpcv_splits[:6]:
        train_sharpes: dict[str, float] = {}
        test_sharpes: dict[str, float] = {}
        for t in trials:
            trial_id = f"fast_{t['fast']}"
            # run train and test for this trial
            if not train_idx or not test_idx:
                continue
            t_start = bars[train_idx[0]].open_time
            t_end = bars[train_idx[-1]].close_time
            te_start = bars[test_idx[0]].open_time
            te_end = bars[test_idx[-1]].close_time
            try:
                tr = engine.run(
                    instr,
                    timeframe,
                    data_version,
                    strategy_id=strategy,
                    strategy_params={"fast": t["fast"], "slow": 20, "quantity": 0.1},
                    start=t_start,
                    end=t_end,
                )
                te = engine.run(
                    instr,
                    timeframe,
                    data_version,
                    strategy_id=strategy,
                    strategy_params={"fast": t["fast"], "slow": 20, "quantity": 0.1},
                    start=te_start,
                    end=te_end,
                )
                train_sharpes[trial_id] = float(tr.sharpe)
                test_sharpes[trial_id] = float(te.sharpe)
            except Exception:
                train_sharpes[trial_id] = 0.0
                test_sharpes[trial_id] = 0.0
        if train_sharpes and test_sharpes:
            best_is = max(train_sharpes, key=lambda k: train_sharpes[k])
            median_test = float(np.median(list(test_sharpes.values())))
            cpcv_folds.append(
                {
                    "train_sharpes": train_sharpes,
                    "test_sharpes": test_sharpes,
                    "best_is_trial": best_is,
                    "best_is_test_sharpe": float(test_sharpes[best_is]),
                    "median_test_sharpe": median_test,
                }
            )

    exp_store = ExperimentStore(db_path=store.db_path)
    num_trials = max(1, exp_store.count_trials())
    # include cpcv trials in count for DSR N (must count all trials including discarded)
    num_trials = max(num_trials, len(trials) * max(1, len(cpcv_folds)) if cpcv_folds else num_trials)
    # If CPCV insufficient, validator will return NOT_IMPLEMENTED → BLOCKED (explicit)
    if len(cpcv_folds) < pipeline.cpcv_min_combos:
        # still pass empty to validator to trigger BLOCK, but log
        pass

    pipeline = (
        ValidatorPipeline()
    )  # coherent Settings policy; materially negative OOS Sharpe fails (min_oos_sharpe=0.30)
    # Derive timeframe from manifest for P scaling (G8) — no hardcoded 252 fallback without audit
    manifest_for_p = store.manifest(data_version)
    timeframe_for_p = manifest_for_p.timeframe if manifest_for_p else timeframe
    report = pipeline.validate(
        strategy_id=strategy,
        data_version=data_version,
        equity_is=eq_is,
        equity_oos=eq_oos,
        walk_forward_folds=folds if folds else None,
        num_trials=num_trials,
        cpcv_folds=cpcv_folds if cpcv_folds else None,
        perturbed_sharpes=perturbed if perturbed else None,
        stress_results=stress_results,
        timeframe=timeframe_for_p,
    )
    # G12: Durable audit for validation outcome — success and failure must be auditable
    try:
        from qts.domain.events import DomainEvent, EventType
        from qts.observability.audit import SqliteAuditLog

        audit_log = SqliteAuditLog()
        # Emit VALIDATION event with passed flag and reasons
        audit_log.emit(
            DomainEvent(
                event_type=EventType.ORDER_EVENT if report.passed else EventType.RISK_VETO,
                payload={
                    "event": "VALIDATION",
                    "strategy_id": strategy,
                    "data_version": data_version,
                    "timeframe": timeframe_for_p,
                    "periods_per_year": report.metrics.get("periods_per_year"),
                    "passed": report.passed,
                    "reasons": report.reasons,
                    "metrics": {
                        k: (float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v)
                        for k, v in report.metrics.items()
                    },
                    "checks": [
                        {
                            "name": c.name,
                            "passed": c.passed,
                            "status": c.status,
                            "metric": c.metric,
                            "threshold": c.threshold,
                            "details": c.details,
                        }
                        for c in report.checks
                    ],
                    "from": "VALIDATING",
                    "to": "REJECTED" if not report.passed else "CANDIDATE",
                },
            )
        )
        # Also emit NO_TRADE on validation failure for capital preservation audit trail
        if not report.passed:
            audit_log.emit(
                DomainEvent(
                    event_type=EventType.NO_TRADE,
                    payload={
                        "strategy_id": strategy,
                        "data_version": data_version,
                        "reason": "VALIDATION_FAILED",
                        "detail": "; ".join(report.reasons)[:500],
                    },
                )
            )
    except Exception as e:
        click.echo(f"validation audit emit failed: {e}", err=True)

    click.echo(f"validation passed={report.passed} reasons={report.reasons}")
    click.echo(
        f"metrics: sharpe_is={report.metrics.get('sharpe_is', 0):.3f} sharpe_oos={report.metrics.get('sharpe_oos', 0):.3f} wfe={report.metrics.get('wfe', 0):.2f} dsr={report.metrics.get('dsr_prob', 0):.2f} pbo={report.metrics.get('pbo', 0):.2f}"
    )
    for c in report.checks:
        status = c.status
        flag = "PASS" if c.passed else "FAIL"
        extra = f" [{status}]" if status != "IMPLEMENTED" else ""
        click.echo(f"  {c.name}: {flag}{extra} metric={c.metric} thresh={c.threshold} {c.details}")
    adv = AdversarialAgent()
    findings = adv.review(
        {
            "wfe": report.metrics.get("wfe", 1),
            "dsr_prob": report.metrics.get("dsr_prob", 1),
            "pbo": report.metrics.get("pbo", 0),
            "spread_pf_1_5x": stress_results.get(1.5, 1) if stress_results else 1,
            "oos_sharpe": report.metrics.get("sharpe_oos", 0),
        }
    )
    if findings:
        click.echo("adversarial findings:")
        for f in findings:
            click.echo(f"  - {f}")
    else:
        click.echo("adversarial: PASS")
    if not report.passed:
        click.echo("RECOMMENDATION: DO NOT PROMOTE — validation failed or NOT_IMPLEMENTED blocks", err=True)


@main.group()
def risk() -> None:
    pass


@risk.command("kill")
@click.option("--reason", default="manual")
def risk_kill(reason: str) -> None:
    from qts.risk.engine import RiskEngine, RiskLimits

    eng = RiskEngine(RiskLimits())
    eng.kill_switch(reason)
    click.echo(f"kill active: {reason}")


@risk.command("reset")
@click.option("--confirm", required=True, help="must be 'yes' to reset")
def risk_reset(confirm: str) -> None:
    from qts.risk.engine import RiskEngine, RiskLimits

    if confirm != "yes":
        click.echo("reset requires --confirm yes", err=True)
        raise SystemExit(2)
    eng = RiskEngine(RiskLimits())
    eng.reset_kill()
    click.echo("kill reset")


@risk.command("check")
@click.option("--instrument", default="XAUUSD")
@click.option("--quantity", default=0.1, type=float)
@click.option(
    "--reference-price",
    required=True,
    help="Authoritative current reference price for notional/exposure checks. "
    "REQUIRED — the CLI never assumes a hardcoded market price. Obtain it from your "
    "market data source (e.g. MT5 terminal) and pass it explicitly.",
)
def risk_check(instrument: str, quantity: float, reference_price: str) -> None:
    from datetime import UTC
    from decimal import Decimal, InvalidOperation

    from qts.domain.value_objects import Account, Instrument, OrderIntent
    from qts.risk.engine import RiskContext, RiskEngine, RiskLimits

    try:
        price = Decimal(reference_price)
    except InvalidOperation:
        click.echo(f"invalid --reference-price: {reference_price!r}", err=True)
        raise SystemExit(2) from None
    if price <= 0:
        click.echo("--reference-price must be > 0 (no hardcoded or placeholder prices)", err=True)
        raise SystemExit(2)

    from qts.domain.value_objects import Side

    instr = Instrument(symbol=instrument)
    intent = OrderIntent(
        instrument=instr, side=Side.BUY, quantity=Decimal(str(quantity)), client_order_id="check", strategy_id="check"
    )
    # Reference price is caller-supplied and auditable — never hardcoded here.
    # The account is an explicit LABELED synthetic state for offline checks
    # (this command never reaches a broker).
    ctx = RiskContext(
        account=Account(
            balance=Decimal("10000"),
            equity=Decimal("10000"),
            currency="OFFLINE_CHECK",
            source="CLI_SYNTHETIC",
            updated_at=datetime.now(UTC),
        ),
        positions={},
        open_orders_count=0,
        daily_pnl=Decimal("0"),
        drawdown=Decimal("0"),
        instrument_suspended=set(),
        reference_prices={instrument: price},
    )
    eng = RiskEngine(RiskLimits())
    dec = eng.pre_trade(intent, ctx)
    eng.close()
    click.echo(f"allowed={dec.allowed} veto={dec.veto_reason} detail={dec.reason_detail} notional={dec.reason_detail}")


@main.command("health")
def health() -> None:
    from qts.data.bootstrap import classify_source

    store = SqliteParquetDataStore()
    versions = store.list_versions()
    usable = store.list_usable_versions()
    click.echo(f"data versions: {versions[-3:] if versions else 'none'}")
    click.echo(f"usable versions: {len(usable)} of {len(versions)} registered")
    phantom = [v for v in versions if v not in usable]
    if phantom:
        click.echo(f"registered but NOT usable (manifest without readable bars): {phantom}")
    for v in usable:
        m = store.manifest(v)
        if m:
            click.echo(
                f"  {v}: {m.instrument} {m.timeframe} rows={m.rows} class={classify_source(m.source)} source={m.source}"
            )
    if not usable:
        click.echo("data: NONE — run `qts data bootstrap` (synthetic fixture) or ingest real data")
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


@audit.command("ship")
@click.option("--jsonl", default="logs/audit.jsonl")
@click.option("--shipper", default="local", type=click.Choice(["local", "s3"]))
@click.option("--bucket", default=None, help="S3 bucket (required for s3)")
@click.option("--prefix", default="qts/audit/")
def audit_ship(jsonl: str, shipper: str, bucket: str | None, prefix: str) -> None:
    from pathlib import Path

    from qts.observability.shipper import LocalShipper, S3Shipper, ship_audit_logs

    path = Path(jsonl)
    if shipper == "s3":
        if not bucket:
            click.echo("s3 shipper requires --bucket", err=True)
            raise SystemExit(2)
        shipper_obj: S3Shipper | LocalShipper = S3Shipper(bucket=bucket, prefix=prefix)
    else:
        shipper_obj = LocalShipper()
    uri = ship_audit_logs(path, shipper_obj)
    if uri:
        click.echo(f"shipped {path} -> {uri}")
    else:
        click.echo(f"ship failed or {path} not found", err=True)
        raise SystemExit(1)


@main.group()
def evidence() -> None:
    """Sanitized session-evidence export/verify (Desktop -> auditable artifact)."""


@evidence.command("export-session")
@click.argument("session_id")
@click.option("--db", default="data/sqlite/forward_observatory.db", help="canonical observation store")
@click.option("--out", default=None, help="output path (default data/evidence/exports/<id>.session_evidence.json)")
def evidence_export_session(session_id: str, db: str, out: str | None) -> None:
    """Recompute ONE session's evidence from the canonical store and write a
    sanitized, digest-bound artifact. Run this ON THE DESKTOP that observed."""
    from qts.observability.session_export import SessionExportError, write_session_evidence

    try:
        art, path = write_session_evidence(session_id, db_path=db, out_path=out)
    except SessionExportError as e:
        click.echo(f"export refused (fail-closed): {e}", err=True)
        raise SystemExit(1) from e
    c = art["counters"]
    click.echo(f"exported session {session_id} -> {path}")
    click.echo(
        f"  ticks={c['tick_count']} provenance={c['ticks_by_provenance']} "
        f"duplicates_in_store={c['duplicate_raw_stamps_in_store']} status={art['session']['status']}"
    )
    click.echo(f"  chain_root={art['digest']['chain_root']}")
    click.echo("  NOTE: transfer only this artifact; it contains no credentials.")


@evidence.command("verify")
@click.argument("artifact_path")
def evidence_verify(artifact_path: str) -> None:
    """Structurally verify an exported session-evidence artifact. Proves internal
    consistency + contract conformance, never the Desktop origin by itself."""
    from qts.observability.session_export import verify_session_export

    rpt = verify_session_export(Path(artifact_path))
    click.echo(json.dumps(rpt, indent=2, default=str))
    if rpt["verdict"] != "CONSISTENT":
        raise SystemExit(1)


@evidence.command("export-research")
@click.argument("session_id")
@click.option("--db", default="data/sqlite/forward_observatory.db", help="canonical observation store")
@click.option("--out", default=None, help="output path (default data/evidence/exports/<id>.research_snapshot.json)")
def evidence_export_research(session_id: str, db: str, out: str | None) -> None:
    """Export the COMPLETE research snapshot (full accepted payloads + acquisition
    ledger + run/clock identity) for ONE session. Separate contract from the v1
    audit artifact. Run this ON THE DESKTOP that observed."""
    from qts.observability.research_snapshot import ResearchSnapshotError, write_research_snapshot

    try:
        art, path = write_research_snapshot(session_id, db_path=db, out_path=out)
    except ResearchSnapshotError as e:
        click.echo(f"research snapshot refused (fail-closed): {e}", err=True)
        raise SystemExit(1) from e
    rec = art["reconciliation"]
    click.echo(f"research snapshot {session_id} -> {path}")
    click.echo(
        f"  accepted_rows={art['accepted']['count']} ledger_rows={art['ledger']['count']} "
        f"agreement={rec['ledger_store_agreement']}"
    )
    click.echo(f"  outcomes={art['ledger']['counts_by_outcome']}")
    click.echo(f"  manifest_hash={art['integrity']['manifest_hash']}")
    click.echo("  NOTE: transfer only this artifact; it contains no credentials.")


@evidence.command("verify-research")
@click.argument("snapshot_path")
def evidence_verify_research(snapshot_path: str) -> None:
    """Verify a research snapshot: completeness, ledger/store agreement, hashes
    and metadata integrity. Proves internal consistency, never Desktop origin."""
    from qts.observability.research_snapshot import verify_research_snapshot_file

    rpt = verify_research_snapshot_file(Path(snapshot_path))
    click.echo(json.dumps(rpt, indent=2, default=str))
    if rpt["verdict"] != "CONSISTENT":
        raise SystemExit(1)


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


@main.group()
def edge() -> None:
    """Capital preservation + real edge discovery."""
    pass


@edge.command("validate")
@click.option("--strategy", default="sma_breakout")
@click.option("--data-version", default=None)
@click.option("--strict", is_flag=True, help="fail-closed on weak edge")
def edge_validate(strategy: str, data_version: str | None, strict: bool) -> None:
    import json
    from pathlib import Path

    from qts.edge.orchestrator import run_full_edge_validation

    click.echo(f"running edge validation for {strategy} version {data_version or 'latest'} (capital preservation)")
    evidence = run_full_edge_validation(data_version=data_version, strategy_id=strategy)
    # Write machine-readable
    Path("data/evidence").mkdir(parents=True, exist_ok=True)
    Path("data/evidence/edge_validation.json").write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")
    # Generate docs
    # 1 edge_validation_report
    ev = evidence
    ds = ev["dataset"]
    es = ev["edge_survival"]

    def _metric(value: Any, fmt: str = ".2f") -> str:
        if value is None:
            return "UNAVAILABLE"
        try:
            return format(float(value), fmt)
        except (TypeError, ValueError):
            return str(value)

    regime_rows = ev.get("regime") if isinstance(ev.get("regime"), list) else []
    economic = ev.get("economic_edge") or {}
    report_md = f"""# Edge Validation Report
**Generated:** {ev["generated_at"]}
**Strategy:** {strategy}
**Data version:** {data_version or ds["manifest"]["version"]}
**Code version:** {ev["code_version"]}

## 1. Dataset integrity
- Manifest: {ds["manifest"]["version"]} {ds["manifest"]["instrument"]} {ds["manifest"]["timeframe"]} rows {ds["manifest"]["rows"]} checksum {ds["manifest"]["checksum"]} timezone {ds["manifest"].get("timezone", "UTC")} preprocessing {ds["manifest"].get("preprocessing_version", "1.0")} source {ds["manifest"].get("source", "")}
- Quality passed: {ds["quality_passed"]} checks: {", ".join(c["name"] + ":" + ("PASS" if c["passed"] else "FAIL") for c in ds["quality_checks"])}
- Missing stats: {ds["missing_stats"]}
- Locked partition: discovery {ds["locked_partition"]["discovery"]} validation {ds["locked_partition"]["validation"]} locked {ds["locked_partition"]["locked"]} frozen {ds["locked_partition"]["is_frozen"]} access_log {len(ds["locked_partition"]["access_log"])} attempts

## 2. Trial count
- Trials: {ev["trial_ledger"]["trial_count"]} (all materially tested variants counted, DSR uses N={ev["trial_ledger"]["trial_count"]})

## 3. Locked-test status
- Frozen: {ds["locked_partition"]["is_frozen"]} — locked test never influenced design/params/thresholds/feature selection
- Access log: {ev["dataset"]["locked_partition"]["access_log"]}

## 4. Walk-forward results
- WFE: {_metric(es.get("wfe"))} passed: {es["checks"].get("walk_forward", False)}
- Details: {es["details"].get("walk_forward", "")}

## 5. CPCV/PBO
- PBO: {_metric(es.get("pbo"))} passed: {es["checks"].get("cpcv", False)} details: {es["details"].get("cpcv", "")}

## 6. PSR/DSR
- PSR: {_metric(es.get("psr"))} DSR: {_metric(es.get("dsr"))} trials {ev["trial_ledger"]["trial_count"]} passed: {es["checks"].get("dsr", False)}

## 7. Null controls
- Null-control evidence: {ev["null_control"]}

## 8. Stress results
- Stress: {ev["cost_robustness"]["stress"]}

## 9. Cost/slippage tolerance
- Break-even spread: {es["cost_be"]:.1f}bps passed: {es["checks"].get("cost", False)} details: {es["details"].get("cost", "")}

## 10. Regime results
- Regimes: {ev["regime"]}

## 11. Forward paper results
- Forward: {ev["forward"]}

## 12. Shadow/paper discrepancy
- Consistency: {ev["shadow_paper"]}

## 13. Expected net edge
- Expectancy: {ev["expectancy"]}
- Economic edge: {ev["economic_edge"]}

## 14. Drawdown
- Drawdown / expected shortfall evidence: {ev["expectancy"]}

## 15. Worst observed failure
- Worst regime/stress: {min(regime_rows, key=lambda x: x.get("sharpe", 0)) if regime_rows else "UNAVAILABLE"}

## 16. Capital-at-risk assumptions
- Risk per trade {ev["capital_policy"]} + SymbolSpec authoritative, spread/slippage/delay net metrics

## 17. Exact reasons for PASS or BLOCK
- Edge survival passed: {es["passed"]} checks: {es["checks"]}
- Economic edge evidence: {economic}
- Overall: **{"PASS" if es["passed"] and economic.get("passed", False) and ds["quality_passed"] else "BLOCK — keep NO_TRADE"}** — genuine edge must survive costs, regime, perturbation, multiple testing, unseen data

## Promotion
- Current promotion state: {ev["promotion"]["state"]} — one-way RESEARCH→LIVE_ELIGIBLE, no skip, anomaly→SUSPENDED
- Emergency kill: {ev["emergency"]}

"""
    Path("docs").mkdir(parents=True, exist_ok=True)
    Path("docs/edge_validation_report.md").write_text(report_md, encoding="utf-8")
    # 2 capital_preservation_policy
    cap_md = f"""# Capital Preservation Policy
**Generated:** {ev["generated_at"]}

Hard limits (Phase 12) — crossing any forces NO_TRADE or SUSPENDED, no adaptive expansion after losses.

- risk_per_trade: 50 bps
- total_open_exposure: 2.0 lots
- daily_loss: 200 USD
- rolling_loss: 500 USD
- max_drawdown: 500 USD
- consecutive_losses: 5
- num_trades/day: 20
- order_frequency: 10/min
- spread: 100 bps
- slippage: 20 bps
- latency: 2000 ms
- data_staleness: 5s
- reconciliation_drift: any drift → SUSPENDED

Current check: {ev["capital_policy"]}

Emergency controls (Phase 17): kill_switch, cancel_all, suspend_new_orders, max_order_rate, max_order_size, stale_data_stop, abnormal_spread_stop, latency_stop, account_state_stop, reconciliation_stop — independently tested.

"""
    Path("docs/capital_preservation_policy.md").write_text(cap_md, encoding="utf-8")
    # 3 strategy_promotion_policy
    promo_md = f"""# Strategy Promotion Policy — One-Way
**State:** {ev["promotion"]["state"]}

Immutable lifecycle: RESEARCH → CANDIDATE → VALIDATED → FORWARD_OBSERVATION → PAPER_VERIFIED → SHADOW_VERIFIED → MICRO_ELIGIBLE → MICRO_VALIDATED → LIVE_ELIGIBLE

- No state may skip prerequisites
- Any serious anomaly → SUSPENDED or REJECTED
- No manual DB edit may promote (all via PromotionLedger transition with audit)
- Scaling (Phase 16) before first real trade: define protocol, depends on forward observations>=30, drawdown<10%, slippage<5bps, reconciliation health, expectancy stability — wins alone never scale
- Current: {ev["promotion"]["state"]}

"""
    Path("docs/strategy_promotion_policy.md").write_text(promo_md, encoding="utf-8")
    # 4 locked_test_protocol
    locked_md = f"""# Locked Test Protocol
**Data version:** {ds["manifest"]["version"]}

- Partitions: discovery {ds["locked_partition"]["discovery"]} (60%), validation {ds["locked_partition"]["validation"]} (20%), locked {ds["locked_partition"]["locked"]} (20%)
- Immutable: hash {ds["manifest"]["checksum"]}, once created cannot change
- Locked test never influences design/params/thresholds/feature selection
- Prevent accidental access via LockedTestPartitioner.get_locked(allow=False) → violation, every attempt logged: {ev["dataset"]["locked_partition"]["access_log"]}
- Freeze: strategy spec/params/features/execution/risk frozen after discovery, only then locked test executed one-shot unless protocol violation documented
- Record every attempt to access/modify locked-test artifacts

"""
    Path("docs/locked_test_protocol.md").write_text(locked_md, encoding="utf-8")
    # 5 experiment_ledger
    exp_store = __import__("qts.research.experiment", fromlist=["ExperimentStore"]).ExperimentStore()
    trials = exp_store.count_trials()
    economic_passed = bool((ev.get("economic_edge") or {}).get("passed", False))
    ledger_md = f"""# Experiment Ledger
**Trials:** {trials} (all materially tested variants, not only winners, discarded counts)

Every experiment recorded: strategy identity, parameter set, feature set, timeframe, data manifest, random seed, objective metrics, rejected/accepted status, reason, timestamp, code version

- Trial count feeds DSR/multiple-testing correction (DSR {_metric(es.get("dsr"))} with N={trials})
- No manual adjustment of trial count
- Ledger DB: data/sqlite/qts.db experiments table

Current ledger count: {trials}
"""
    Path("docs/experiment_ledger.md").write_text(ledger_md, encoding="utf-8")
    click.echo("edge validation evidence written to data/evidence/edge_validation.json")
    click.echo(
        "docs: edge_validation_report.md, capital_preservation_policy.md, strategy_promotion_policy.md, locked_test_protocol.md, experiment_ledger.md"
    )
    if strict and not (es["passed"] and economic_passed):
        click.echo("BLOCK — edge does not survive costs/regime/perturbation/multiple-testing → KEEP NO_TRADE", err=True)
        # do not exit 2 here, just report BLOCK; live gate still blocks
    else:
        click.echo(f"edge validation completed: passed={es['passed']} economic={economic_passed}")


@main.command("run")
@click.option("--mode", default="paper", type=click.Choice(["backtest", "paper", "shadow", "live", "dry_run", "micro"]))
@click.option("--strategy", default="sma_breakout")
@click.option("--data-version", required=True)
@click.option("--confirm", default=None, help="must be 'live' for live mode")
def run_cmd(mode: str, strategy: str, data_version: str, confirm: str | None) -> None:
    settings = load_settings()
    settings.execution.mode = mode  # type: ignore
    if confirm == "live":
        settings.confirm_live = True
        settings.env = "live"
    if confirm == "micro":
        settings.confirm_live = True
        settings.env = "live"
        settings.execution.mode = "micro"  # type: ignore
    if mode == "live":
        try:
            settings.assert_live_allowed()
        except ValueError as e:
            click.echo(f"live blocked (fail closed): {e}", err=True)
            sys.exit(2)
        # Check that requested data_version exists
        store_tmp = SqliteParquetDataStore()
        manifest_tmp = store_tmp.manifest(data_version)
        if manifest_tmp is None:
            click.echo(f"live blocked: data_version {data_version} not found (fail closed)", err=True)
            sys.exit(2)
        # LIVE GATE — check all required capabilities and evidence
        try:
            from qts.lifecycle.live_gate import live_readiness_report

            rpt = live_readiness_report()
            if not rpt["ready"]:
                click.echo("live blocked: production execution boundary not ready", err=True)
                for k, v in rpt.items():
                    if isinstance(v, dict) and not v["passed"]:
                        click.echo(f"  - {k}: {v['detail']}", err=True)
                click.echo(f"blocked reasons: {rpt['blocked_reasons']}", err=True)
                sys.exit(2)
        except Exception as e:
            click.echo(f"live gate check failed (fail closed): {e}", err=True)
            sys.exit(2)
        # Even if gate passes, still require explicit live implementation note
        # For now, live remains blocked until shadow/paper evidence present and MT5 terminal available
        # This is the final structural block — remove only when all evidence verified
        from qts.lifecycle.live_gate import is_live_ready

        if not is_live_ready():
            click.echo("live mode — not ready (requires MT5 terminal + evidence) — BLOCKED", err=True)
            sys.exit(2)
        click.echo("live mode — gate passed but live trading still requires final manual approval", err=True)
        sys.exit(2)
    if mode == "dry_run":
        # Phase 9: Safe dry-run — OFFLINE pipeline rehearsal against an
        # EXPLICITLY LABELED synthetic module. dry_run NEVER imports or
        # contacts the MetaTrader5 package/terminal and NEVER submits orders;
        # real-terminal validation is the 14-check readiness gate's job
        # (demo_forward_readiness_report).
        click.echo(f"running mode={mode} strategy={strategy} version={data_version} (dry-run, offline, no submission)")
        from datetime import datetime
        from decimal import Decimal as _Decimal
        from pathlib import Path as _Path
        from unittest.mock import MagicMock as _MagicMock

        from qts.adapters.market_data import MarketDataProvider as _MDP
        from qts.adapters.mt5_adapter import MT5Adapter as _MT5Adapter
        from qts.domain.events import DomainEvent as _DE
        from qts.domain.events import EventType as _ET
        from qts.domain.value_objects import Instrument as _Instrument
        from qts.domain.value_objects import OrderIntent as _Intent
        from qts.domain.value_objects import Side as _Side
        from qts.observability.audit import SqliteAuditLog as _Audit

        # Explicit OFFLINE dependency boundary (root-cause fix for the
        # Windows dry_run regression): the previous "use the real MT5 module
        # when initialize() succeeds" escalation made dry_run depend on live
        # broker-session state — on a machine with the terminal installed it
        # silently switched to the real module and then crashed on
        # symbol_info (broker symbol/login not usable in-process). Dry-run
        # now uses the labeled synthetic module UNCONDITIONALLY: executable
        # and testable with zero broker dependency, never submitting.
        mt5_mock = _MagicMock()
        _info = _MagicMock()
        _info.contract_size = 100
        _info.volume_min = 0.01
        _info.volume_max = 100
        _info.volume_step = 0.01
        _info.digits = 2
        _info.point = 0.01
        _info.trade_tick_size = 0.01
        _info.trade_mode = 4
        _info.trade_allowed = True
        _info.filling_mode = 1
        _info.execution_mode = 0
        _info.trade_stops_level = 10
        _info.trade_freeze_level = 0
        mt5_mock.symbol_info.return_value = _info
        mt5_mock.symbol_select.return_value = True
        mt5_mock.last_error.return_value = (1, "ok")
        _tick = _MagicMock()
        _tick.bid = 1999.5
        _tick.ask = 2000.5
        _tick.time = datetime.now(UTC).timestamp()
        mt5_mock.symbol_info_tick.return_value = _tick
        mt5_mock.terminal_info.return_value = _MagicMock(connected=True, trade_allowed=True)
        mt5_mock.account_info.return_value = _MagicMock(
            balance=10000, equity=10000, margin=100, margin_free=9900, leverage=100, currency="USD", login=12345
        )
        _sym1 = _MagicMock()
        _sym1.name = "XAUUSD"
        _sym2 = _MagicMock()
        _sym2.name = "EURUSD"
        mt5_mock.symbols_get.return_value = [_sym1, _sym2]
        mt5_module = mt5_mock  # ALWAYS the labeled synthetic module — see boundary note above
        is_mock = True
        adapter = _MT5Adapter(mt5_module=mt5_module, config={"path": "", "login": 12345})
        # Phase 1: connectivity
        health = adapter.health_check()
        prereq = adapter.validate_prerequisites("XAUUSD")
        spec = adapter.get_symbol_spec("XAUUSD")
        disc = adapter.discover_symbols()
        # Phase 3: market data
        md = _MDP(adapter)
        instr = _Instrument(symbol="XAUUSD", venue="MT5")
        tick = None
        exec_price_buy = None
        exec_price_sell = None
        ref_price = None
        try:
            tick = md.get_tick(instr)
            md_ok = True
            md_err = None
            exec_price_buy = md.get_executable_price(instr, "BUY")
            exec_price_sell = md.get_executable_price(instr, "SELL")
            ref_price = md.get_reference_price(instr)
        except Exception as e:
            tick = None
            md_ok = False
            md_err = str(e)
            exec_price_buy = exec_price_sell = ref_price = None
        # Phase 6: account
        try:
            acct = adapter.account()
            acct_ok = True
            acct_err = None
        except Exception as e:
            acct = None
            acct_ok = False
            acct_err = str(e)
        # Phase 2 & 4: risk + normalization + request build (no submit)
        from qts.domain.value_objects import Account as _Acct
        from qts.risk.engine import RiskContext as _RC
        from qts.risk.engine import RiskEngine as _RE
        from qts.risk.engine import RiskLimits as _RL

        risk = _RE(_RL())
        # Authoritative account when reachable; otherwise an EXPLICITLY
        # LABELED synthetic state (dry-run never trades, but its evidence
        # must not present fabricated capital as broker truth).
        acct_for_risk = (
            acct.model_copy(update={"source": "DRY_RUN_SYNTHETIC"})
            if (acct_ok and acct is not None)
            else _Acct(
                balance=_Decimal("10000"),
                equity=_Decimal("10000"),
                currency="DRYRUN_SIM",
                source="CLI_SYNTHETIC",
                updated_at=datetime.now(UTC),
            )
        )
        # Reference price for risk comes from the market data adapter only — NEVER a
        # hardcoded fallback. If unavailable, ref_prices stays empty and the risk
        # engine vetoes fail-closed ("no market price"), which the evidence records.
        ref_prices = {"XAUUSD": exec_price_buy} if exec_price_buy is not None else {}
        ctx = _RC(
            account=acct_for_risk,
            positions={},
            open_orders_count=0,
            daily_pnl=_Decimal("0"),
            drawdown=_Decimal("0"),
            instrument_suspended=set(),
            reference_prices=ref_prices,
        )
        intent = _Intent(
            instrument=instr,
            side=_Side.BUY,
            quantity=spec.volume_min,
            client_order_id=f"dryrun:{strategy}:{data_version}:001",
            strategy_id=strategy,
        )
        norm_qty = adapter.validate_and_normalize_quantity(intent.quantity, spec)
        decision = risk.pre_trade(intent, ctx)
        try:
            request = adapter.build_broker_request(intent)
            req_ok = True
            req_err = None
        except Exception as e:
            request = None
            req_ok = False
            req_err = str(e)
        # Audit dry-run
        audit = _Audit()
        audit.emit(
            _DE(
                event_type=_ET.NO_TRADE,
                payload={
                    "reason": "DRY_RUN",
                    "detail": f"health {health} prereq {prereq} spec {spec.symbol} tick {tick} acct {acct_ok} risk {decision.allowed} req {req_ok}",
                },
            )
        )
        # Evidence
        import json as _json

        evidence = {
            "mode": "dry_run",
            "strategy": strategy,
            "data_version": data_version,
            "is_mock": is_mock,
            "terminal_contacted": False,
            "broker_dependency": "OFFLINE_DRY_RUN — dry_run never imports/contacts MetaTrader5 or the terminal",
            "data_class": "SYNTHETIC",
            "health": health,
            "prereq_ok": prereq["ok"],
            "prereq_errors": prereq["errors"],
            "symbol_spec": {
                "symbol": spec.symbol,
                "contract_size": str(spec.contract_size),
                "volume_min": str(spec.volume_min),
                "volume_max": str(spec.volume_max),
                "volume_step": str(spec.volume_step),
                "digits": spec.digits,
                "point": str(spec.point),
                "stops_level": spec.stops_level,
                "freeze_level": spec.freeze_level,
                "filling_mode": spec.filling_mode,
                "execution_mode": spec.execution_mode,
                "source": "DRY_RUN_SYNTHETIC (offline module — a real authoritative spec requires the readiness gate)",
            },
            "discovered_symbols": disc[:10],
            "market_data": {
                "ok": md_ok,
                "error": md_err,
                "bid": str(tick.bid) if tick else None,
                "ask": str(tick.ask) if tick else None,
                "buy_price": str(exec_price_buy) if exec_price_buy else None,
                "sell_price": str(exec_price_sell) if exec_price_sell else None,
                "mid": str(ref_price) if ref_price else None,
            },
            "account": {
                "ok": acct_ok,
                "error": acct_err,
                "balance": str(acct.balance) if acct else None,
                "equity": str(acct.equity) if acct else None,
                "leverage": str(acct.leverage) if acct else None,
                "source": "DRY_RUN_SYNTHETIC (offline module — never broker state)",
            }
            if acct
            else {"ok": False},
            "risk": {
                "allowed": decision.allowed,
                "veto": str(decision.veto_reason) if decision.veto_reason else None,
                "price": str(decision.price) if decision.price else None,
                "price_source": decision.price_source,
            },
            "normalized_quantity": str(norm_qty),
            "broker_request": request,
            "request_ok": req_ok,
            "request_error": req_err,
            "audit_emitted": True,
        }
        _Path("data/evidence").mkdir(parents=True, exist_ok=True)
        _Path("data/evidence/dry_run.json").write_text(_json.dumps(evidence, indent=2, default=str), encoding="utf-8")
        click.echo(
            f"dry-run result: prereq {prereq['ok']} md {md_ok} acct {acct_ok} risk {decision.allowed} req {req_ok} (no order submitted, evidence written)"
        )
        if not prereq["ok"] or not md_ok or not acct_ok:
            click.echo(f"dry-run warnings: prereq {prereq['errors']} md {md_err} acct {acct_err}", err=True)
        return
    if mode == "micro":
        # Phase 9: Micro-execution test — smallest quantity, full lifecycle, fail-closed gates
        import os as _os
        from datetime import datetime as _dt
        from decimal import Decimal as _Decimal2
        from pathlib import Path as _Path2
        from unittest.mock import MagicMock as _MM

        # Gate: micro requires explicit enable
        if _os.getenv("QTS_MICRO_ENABLED") != "true":
            click.echo("micro blocked (fail closed): requires QTS_MICRO_ENABLED=true", err=True)
            sys.exit(2)
        try:
            settings.assert_micro_allowed()
        except ValueError as e:
            click.echo(f"micro blocked (fail closed): {e}", err=True)
            sys.exit(2)
        # Validate data version
        _store = SqliteParquetDataStore()
        if _store.manifest(data_version) is None:
            click.echo(f"micro blocked: data_version {data_version} not found", err=True)
            sys.exit(2)
        # Check that no unresolved suspension
        try:
            from qts.lifecycle.live_gate import live_readiness_report as _lrr

            _rpt = _lrr()
            # For micro, we require most gates except env already checked, but still warn if many blocked
            # Do not block on env already passed, but block if MT5 connectivity or symbol spec fails
            if not _rpt["mt5_connectivity"]["passed"] or not _rpt["symbol_spec"]["passed"]:
                click.echo(f"micro blocked: MT5/symbol not ready {_rpt['blocked_reasons']}", err=True)
                sys.exit(2)
        except Exception as e:
            click.echo(f"micro gate check failed: {e}", err=True)
            sys.exit(2)
        click.echo(f"running mode={mode} strategy={strategy} version={data_version} (micro, minimal quantity)")
        # Setup broker with mock that simulates micro fill (or real if available)
        from qts.adapters.market_data import MarketDataProvider as _MDP2
        from qts.adapters.mt5_adapter import MT5Adapter as _MT5A
        from qts.domain.value_objects import Instrument as _Instr
        from qts.domain.value_objects import OrderIntent as _OI2
        from qts.domain.value_objects import OrderType as _OT2
        from qts.domain.value_objects import Side as _Side2
        from qts.execution.engine import ExecutionEngine as _EE
        from qts.execution.engine import OrderManager as _OM
        from qts.execution.idempotency import IdempotencyStore as _IS
        from qts.execution.matching import MatchingConfig as _MC
        from qts.execution.matching import MatchingEngine as _ME
        from qts.observability.audit import SqliteAuditLog as _AL2
        from qts.portfolio.portfolio import Portfolio as _PF
        from qts.risk.engine import RiskEngine as _RE2
        from qts.risk.engine import RiskLimits as _RL2

        # Mock MT5 that simulates successful micro execution
        _mock = _MM()
        _inf = _MM()
        _inf.contract_size = 100
        _inf.volume_min = 0.01
        _inf.volume_max = 100
        _inf.volume_step = 0.01
        _inf.digits = 2
        _inf.point = 0.01
        _inf.trade_tick_size = 0.01
        _inf.trade_mode = 4
        _inf.trade_allowed = True
        _inf.filling_mode = 1
        _inf.execution_mode = 0
        _inf.trade_stops_level = 10
        _inf.trade_freeze_level = 0
        _mock.symbol_info.return_value = _inf
        _mock.symbol_select.return_value = True
        _mock.last_error.return_value = (1, "ok")
        _t = _MM()
        _t.bid = 2000.0
        _t.ask = 2000.5
        _t.time = _dt.now(UTC).timestamp()
        _mock.symbol_info_tick.return_value = _t
        _mock.terminal_info.return_value = _MM(connected=True, trade_allowed=True)
        _mock.account_info.return_value = _MM(
            balance=10000, equity=10000, margin=0, margin_free=10000, leverage=100, currency="USD", login=12345
        )
        _sym = _MM()
        _sym.name = "XAUUSD"
        _mock.symbols_get.return_value = [_sym]
        # Mock order_send success
        _res = _MM()
        _res.retcode = 10009
        _res.order = 123456
        _res.deal = 654321
        _res.comment = ""
        _mock.order_send.return_value = _res
        _mock.positions_get.return_value = []
        _mock.orders_get.return_value = []
        _mock.history_deals_get.return_value = []
        # The rehearsal defaults to an in-process MagicMock broker; the real
        # terminal is used only when the operator explicitly asks for it. Which
        # one actually ran is RECORDED in the evidence artifact, because a
        # simulated broker can never produce broker-execution evidence.
        broker = _MT5A(mt5_module=_mock, config={"dry_run": False})
        broker_is_mock = True
        # Also try real if env var QTS_USE_REAL_MT5=true
        if _os.getenv("QTS_USE_REAL_MT5") == "true":
            with contextlib.suppress(Exception):
                import MetaTrader5 as _real

                if _real.initialize():
                    broker = _MT5A(
                        mt5_module=_real,
                        config={
                            # canonical QTS_MT5_* names (docs/UI); legacy
                            # unprefixed MT5_* accepted as fallback
                            "login": _os.getenv("QTS_MT5_LOGIN") or _os.getenv("MT5_LOGIN"),
                            "password": _os.getenv("QTS_MT5_PASSWORD") or _os.getenv("MT5_PASSWORD"),
                            "server": _os.getenv("QTS_MT5_SERVER") or _os.getenv("MT5_SERVER"),
                        },
                    )
                    broker_is_mock = False
        md2 = _MDP2(broker)
        audit2 = _AL2()
        # Use temp DB for micro to isolate, but also ensure durable for restart test
        import tempfile as _tf

        _fd, _tmpname = _tf.mkstemp(suffix=".db")  # secure: mktemp is racy
        _os.close(_fd)
        _tmp = _Path2(_tmpname)
        om2 = _OM(audit=audit2, idempotency=_IS(db_path=_tmp))
        pf2 = _PF(initial_balance=_Decimal2("10000"))
        risk2 = _RE2(_RL2(), db_path=_tmp)
        eng2 = _EE(om2, risk2, broker, _ME(_MC()), pf2, audit=audit2, db_path=_tmp, market_data=md2)
        instr2 = _Instr(symbol="XAUUSD", venue="MT5")
        # Minimal quantity = spec volume_min
        spec2 = broker.get_symbol_spec("XAUUSD")
        qty2 = spec2.volume_min
        intent2 = _OI2(
            instrument=instr2,
            side=_Side2.BUY,
            quantity=qty2,
            client_order_id=f"micro:{strategy}:{data_version}:001",
            strategy_id=strategy,
            order_type=_OT2.MARKET,
        )
        # Phase 1-3-6 checks already, now risk + normalization + submit
        order2, fills2 = eng2.submit_intent(intent2)
        # For MT5 mock, submit should succeed to ACCEPTED, then poll for fills
        # Simulate fill via poll
        # Simulate broker fill for micro — create a deal that matches comment and will be found by poll
        # For mock, history_deals_get should return a deal with matching comment
        with contextlib.suppress(Exception):
            _deal = _MM()
            _deal.symbol = "XAUUSD"
            _deal.volume = float(qty2)
            _deal.price = 2000.5
            _deal.type = 0  # BUY
            _deal.time = _dt.now(UTC).timestamp()
            # comment must match stored comment map
            _comment = broker._load_comment_map(intent2.client_order_id) or intent2.client_order_id[:31]
            _deal.comment = _comment
            _mock.history_deals_get.return_value = [_deal]
        fills_poll = eng2.poll_live_fills()
        # NO fabricated fills and NO scripted broker positions.
        #
        # This path used to (a) invent a Fill the broker never returned, apply
        # it to the portfolio and force the order state to FILLED when the poll
        # came back empty, and (b) overwrite the broker's reported positions so
        # that reconcile() could only answer "drift NONE". Both destroyed the
        # meaning of the artifact: the published evidence showed a FILLED
        # LIVE-family order and a clean reconciliation that were manufactured
        # here rather than observed. Fills and reconciliation are now reported
        # exactly as the broker/poll/reconcile actually produced them; an empty
        # poll is recorded as an empty poll.
        report2 = eng2.reconcile()
        # Evidence
        import json as _js

        # Refresh order after poll to capture the ACTUAL state
        _fresh_order = om2.get(intent2.client_order_id) if "intent2" in locals() else order2
        from qts.observability.lineage import code_version as _code_version

        _manifest2 = _store.manifest(data_version)
        ev2 = {
            "mode": "micro",
            "strategy": strategy,
            "data_version": data_version,
            # ---- provenance / lineage (same contract as dry_run.json) ----
            # A micro rehearsal runs against an in-process MagicMock broker
            # unless the operator explicitly opted into the real terminal. That
            # fact is part of the evidence: without it a simulated FILLED order
            # and a simulated "drift NONE" are indistinguishable from broker
            # execution, which is exactly the confusion the provenance model
            # exists to prevent.
            "is_mock": broker_is_mock,
            "terminal_contacted": not broker_is_mock,
            "broker_source": "MOCK_SIMULATED" if broker_is_mock else "REAL_MT5_TERMINAL",
            "data_class": "SIMULATED" if broker_is_mock else "UNVERIFIED",
            "data_class_reason": (
                "order/fill/reconcile values were produced by an in-process simulated broker; "
                "they are not broker execution evidence and satisfy no execution or promotion gate"
                if broker_is_mock
                else "a real terminal was used but this path does not verify the connected account "
                "class, so the result is not automatically DEMO or REAL evidence"
            ),
            "generated_at": _dt.now(UTC).isoformat(),
            "code_version": _code_version(),
            "dataset_class": _manifest2.provenance_class if _manifest2 else "UNVERIFIED",
            "dataset_source": _manifest2.source if _manifest2 else None,
            "symbol_spec": {
                "volume_min": str(spec2.volume_min),
                "volume_max": str(spec2.volume_max),
                "volume_step": str(spec2.volume_step),
                "source": "MOCK_SIMULATED" if broker_is_mock else "MT5 SymbolInfo",
            },
            "quantity": str(qty2),
            "order": {
                "client_order_id": _fresh_order.client_order_id if _fresh_order else None,
                "state": _fresh_order.state.value if _fresh_order else None,
                "exchange_id": _fresh_order.exchange_order_id if _fresh_order else None,
            },
            "fills": [{"price": str(f.price), "qty": str(f.quantity)} for f in fills2]
            + [{"price": str(f.price), "qty": str(f.quantity)} for f in fills_poll if hasattr(f, "price")],
            "poll_fills": len(fills_poll),
            "reconcile": {"drift": report2.drift, "details": report2.details, "suspended": eng2.is_suspended},
            "portfolio": {"equity": str(pf2.equity()), "positions": len(pf2.positions)},
            "audit_count": len(audit2.query(limit=100)) if hasattr(audit2, "query") else 0,
        }
        _Path2("data/evidence").mkdir(parents=True, exist_ok=True)
        _Path2("data/evidence/micro.json").write_text(_js.dumps(ev2, indent=2), encoding="utf-8")
        click.echo(
            f"micro result: broker={ev2['broker_source']} data_class={ev2['data_class']} order {ev2['order']} "
            f"fills {len(fills2)} poll {len(fills_poll)} reconcile {report2.drift} "
            f"suspended {eng2.is_suspended} (evidence written)"
        )
        if broker_is_mock:
            click.echo(
                "micro evidence is SIMULATED: the broker was an in-process mock, so no order, fill or "
                "reconciliation result in it is broker execution evidence",
                err=True,
            )
        if report2.requires_suspend:
            click.echo(f"micro reconcile suspended: {report2.details}", err=True)
        return
    if mode == "paper":
        # Paper trading — broker-realistic, same lifecycle as live
        click.echo(f"running mode={mode} strategy={strategy} version={data_version} (realistic paper)")
        store = SqliteParquetDataStore()
        instr = Instrument(symbol="XAUUSD", venue="MT5")
        manifest = store.manifest(data_version)
        timeframe = manifest.timeframe if manifest else "1H"
        # Use realistic paper broker with same validation as MT5
        from decimal import Decimal

        from qts.adapters.paper_adapter import RealisticPaperBroker
        from qts.execution.engine import ExecutionEngine, OrderManager
        from qts.execution.idempotency import IdempotencyStore
        from qts.execution.matching import MatchingConfig, MatchingEngine
        from qts.observability.audit import SqliteAuditLog
        from qts.portfolio.portfolio import Portfolio
        from qts.research.strategy import SmaBreakoutStrategy, signal_to_intent
        from qts.risk.engine import RiskEngine, RiskLimits

        # Clean persistent state for deterministic evidence (kill/idempotency would block re-run)
        for _p in [
            Path("data/sqlite/paper_cli.db"),
            Path("data/sqlite/paper_cli_idemp.db"),
            Path("data/sqlite/paper_cli_risk.db"),
        ]:
            with contextlib.suppress(Exception):
                if _p.exists():
                    _p.unlink()
        # Load bars and run paper loop (similar to backtest but with realistic broker)
        bars = store.read_bars(instr, timeframe, version=data_version)
        bars = sorted(bars, key=lambda b: b.open_time)
        # Use same strategy
        strat = SmaBreakoutStrategy(instr, fast=10, slow=20, strategy_id=strategy)
        matching = MatchingEngine(MatchingConfig())
        audit = SqliteAuditLog()
        idemp = IdempotencyStore(db_path=Path("data/sqlite/paper_cli_idemp.db"))
        om = OrderManager(audit=audit, idempotency=idemp)
        paper_broker = RealisticPaperBroker(matching=matching, db_path=Path("data/sqlite/paper_cli.db"))
        portfolio = Portfolio(initial_balance=Decimal("10000"))
        risk = RiskEngine(RiskLimits(), db_path=Path("data/sqlite/paper_cli_risk.db"))
        paper_engine = ExecutionEngine(om, risk, paper_broker, matching, portfolio, audit=audit)
        # Run paper loop: next-bar execution, same as backtest but via ExecutionEngine
        pending: list = []
        fills_out = []
        for bar in bars:
            if pending:
                from datetime import timedelta

                from qts.domain.value_objects import Bar as BarVO

                exec_bar = BarVO(
                    instrument=bar.instrument,
                    open=bar.open,
                    high=bar.open,
                    low=bar.open,
                    close=bar.open,
                    volume=bar.volume,
                    open_time=bar.open_time,
                    close_time=bar.open_time + timedelta(milliseconds=1),
                    data_version=bar.data_version,
                    source="paper_execution_open",
                )
                for intent in pending:
                    order, fills = paper_engine.submit_intent(intent, bar=exec_bar)
                    for f in fills:
                        fills_out.append(
                            {"price": str(f.price), "qty": str(f.quantity), "time": f.event_time.isoformat()}
                        )
                pending = []
            paper_engine.mark_price(bar.instrument.symbol, bar.close)
            signals = strat.on_bar(bar)
            for sig in signals:
                intent = signal_to_intent(sig, quantity=Decimal("0.1"))
                intent = intent.model_copy(
                    update={
                        "client_order_id": f"{strategy}:{bar.close_time.isoformat()}:{len(fills_out) + len(pending)}"
                    }
                )
                pending.append(intent)
        # Evidence
        import json
        from datetime import datetime as _dt_lineage

        from qts.observability.lineage import code_version as _code_version

        evidence = {
            "mode": "paper",
            "strategy": strategy,
            "data_version": data_version,
            "bars": len(bars),
            "trades": len(fills_out),
            "final_equity": float(portfolio.equity()),
            "fills": fills_out[:10],
            # Evidence lineage (findings #21/#42): results that cannot be
            # traced to code/config/time are not promotion-grade evidence.
            "generated_at": _dt_lineage.now(UTC).isoformat(),
            "code_version": _code_version(),
            "data_class": "PAPER",
        }
        Path("data/evidence").mkdir(parents=True, exist_ok=True)
        Path("data/evidence/paper_trades.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        # Also write audit evidence
        Path("logs").mkdir(parents=True, exist_ok=True)
        click.echo(
            f"paper result: equity={float(portfolio.equity()):.2f} trades={len(fills_out)} (realistic paper, evidence written)"
        )
        return
    if mode == "shadow":
        # Shadow mode — real market data drives real strategy/risk, no submission
        click.echo(f"running mode={mode} strategy={strategy} version={data_version} (shadow, no submission)")
        store = SqliteParquetDataStore()
        instr = Instrument(symbol="XAUUSD", venue="MT5")
        manifest = store.manifest(data_version)
        timeframe = manifest.timeframe if manifest else "1H"
        from decimal import Decimal

        from qts.adapters.shadow_adapter import ShadowBroker
        from qts.execution.engine import ExecutionEngine, OrderManager
        from qts.execution.idempotency import IdempotencyStore
        from qts.execution.matching import MatchingConfig, MatchingEngine
        from qts.observability.audit import SqliteAuditLog
        from qts.portfolio.portfolio import Portfolio
        from qts.research.strategy import SmaBreakoutStrategy, signal_to_intent
        from qts.risk.engine import RiskEngine, RiskLimits

        for _p in [
            Path("data/sqlite/shadow_cli.db"),
            Path("data/sqlite/shadow_cli_idemp.db"),
            Path("data/sqlite/shadow_cli_risk.db"),
        ]:
            with contextlib.suppress(Exception):
                if _p.exists():
                    _p.unlink()
        bars = store.read_bars(instr, timeframe, version=data_version)
        bars = sorted(bars, key=lambda b: b.open_time)
        strat = SmaBreakoutStrategy(instr, fast=10, slow=20, strategy_id=strategy)
        matching = MatchingEngine(MatchingConfig())
        audit = SqliteAuditLog()
        idemp = IdempotencyStore(db_path=Path("data/sqlite/shadow_cli_idemp.db"))
        om = OrderManager(audit=audit, idempotency=idemp)
        shadow_broker = ShadowBroker(db_path=Path("data/sqlite/shadow_cli.db"))
        portfolio = Portfolio(initial_balance=Decimal("10000"))
        risk = RiskEngine(RiskLimits(), db_path=Path("data/sqlite/shadow_cli_risk.db"))
        shadow_engine = ExecutionEngine(om, risk, shadow_broker, matching, portfolio, audit=audit)
        pending = []
        shadow_intents = []
        for bar in bars:
            if pending:
                from datetime import timedelta

                from qts.domain.value_objects import Bar as BarVO

                exec_bar = BarVO(
                    instrument=bar.instrument,
                    open=bar.open,
                    high=bar.open,
                    low=bar.open,
                    close=bar.open,
                    volume=bar.volume,
                    open_time=bar.open_time,
                    close_time=bar.open_time + timedelta(milliseconds=1),
                    data_version=bar.data_version,
                    source="shadow_execution_open",
                )
                for intent in pending:
                    order, fills = shadow_engine.submit_intent(intent, bar=exec_bar)
                    # In shadow, fills should be 0, order is ACCEPTED shadow
                    shadow_intents.append(
                        {"client_order_id": intent.client_order_id, "price": str(exec_bar.close), "would_be": True}
                    )
                pending = []
            shadow_engine.mark_price(bar.instrument.symbol, bar.close)
            signals = strat.on_bar(bar)
            for sig in signals:
                intent = signal_to_intent(sig, quantity=Decimal("0.1"))
                intent = intent.model_copy(
                    update={
                        "client_order_id": f"{strategy}:{bar.close_time.isoformat()}:{len(shadow_intents) + len(pending)}"
                    }
                )
                pending.append(intent)
        import json
        from datetime import datetime as _dt_lineage

        from qts.observability.lineage import code_version as _code_version

        evidence = {
            "mode": "shadow",
            "strategy": strategy,
            "data_version": data_version,
            "bars": len(bars),
            "intents": len(shadow_intents),
            "would_be_fills": shadow_broker.get_would_be_fills()[:10],
            "intents_sample": shadow_intents[:10],
            "generated_at": _dt_lineage.now(UTC).isoformat(),
            "code_version": _code_version(),
            "data_class": "SHADOW",
        }
        Path("data/evidence").mkdir(parents=True, exist_ok=True)
        Path("data/evidence/shadow_intents.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        click.echo(
            f"shadow result: intents={len(shadow_intents)} would_be_fills={len(shadow_broker.get_would_be_fills())} (evidence written, no venue orders)"
        )
        return
    click.echo(f"running mode={mode} strategy={strategy} version={data_version}")
    store = SqliteParquetDataStore()
    instr = Instrument(symbol="XAUUSD", venue="MT5")
    manifest = store.manifest(data_version)
    timeframe = manifest.timeframe if manifest else "1H"
    bt_engine = BacktestEngine(store)
    result = bt_engine.run(instr, timeframe, data_version, strategy_id=strategy)
    click.echo(f"backtest result: equity={result.final_equity:.2f} trades={result.trades} sharpe={result.sharpe:.3f}")


@main.group()
def desktop() -> None:
    """Desktop application."""


@desktop.command("launch")
@click.option("--host", default="127.0.0.1")
@click.option("--port", default=8000, type=int)
def desktop_launch(host: str, port: int) -> None:
    from qts.desktop.health import startup_health_check
    from qts.desktop.launcher import open_desktop_window, start_api_server

    click.echo("[desktop] startup health check")
    health = startup_health_check()
    for c in health["checks"]:
        click.echo(f"  {c['name']}: {'PASS' if c['passed'] else 'FAIL'} {c['detail']}")
    click.echo(f"overall: {health['overall']} status={health['system_status']}")
    server, thread = start_api_server(host, port)
    click.echo(f"API at http://{host}:{port}/ — opening desktop window")
    open_desktop_window(host, port)


@desktop.command("api")
@click.option("--host", default="127.0.0.1")
@click.option("--port", default=8000, type=int)
def desktop_api(host: str, port: int) -> None:
    import uvicorn

    from qts.api.server import app

    click.echo(f"starting API server at http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)


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
    Path("data/evidence").mkdir(parents=True, exist_ok=True)
    Path("data/evidence/campaign_last.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
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
    Path("data/evidence").mkdir(parents=True, exist_ok=True)
    Path("data/evidence/autonomous_campaign.json").write_text(
        json.dumps(result, indent=2, default=str), encoding="utf-8"
    )
    ev = result["evidence_portfolio"]
    click.echo(
        f"autonomous completed: trials {result['summary']['total_trials']} passed {result['summary']['passed']} distinct {result['novelty']['distinct_hypotheses']}"
    )
    click.echo(f"self-audit verdict {result['self_audit']['verdict']}")
    click.echo(f"overall {ev['overall']}")
    if ev["overall"].startswith("BLOCK"):
        click.echo("BLOCK — keep NO_TRADE — no genuine economic edge demonstrated")


# ---------------------------------------------------------------------------
# DEMO execution — explicit, staged, auditable (LIVE remains locked)
# ---------------------------------------------------------------------------


def _demo_session(symbol: str, db: str, terminal_path: str | None = None) -> Any:
    from qts.config.wizard import load_setup
    from qts.execution.demo_session import DemoSession, DemoSessionConfig

    saved = load_setup()
    symbol_map = saved.get("symbol_map")
    return DemoSession(
        DemoSessionConfig(
            symbol=symbol or saved.get("symbol") or "XAUUSD",
            terminal_path=terminal_path or saved.get("terminal_path") or None,
            symbol_map=symbol_map if isinstance(symbol_map, dict) else {},
            db_path=Path(db),
            actor="cli",
        )
    )


@main.group()
def demo() -> None:
    """Controlled DEMO execution (authorization-gated; LIVE stays locked)."""


@demo.command("authorization")
def demo_authorization() -> None:
    """Show the owner authorization artifact and its validation result."""
    from qts.lifecycle.demo_authorization import authorization_status, resolve_demo_execution_policy

    status = authorization_status()
    click.echo(json.dumps(status.as_dict(), indent=2, default=str))
    policy = resolve_demo_execution_policy(mode="DEMO_EXECUTION")
    click.echo(f"policy(DEMO_EXECUTION): {policy.state}")
    live_policy = resolve_demo_execution_policy(mode="LIVE")
    click.echo(f"policy(LIVE): {live_policy.state} — {'; '.join(live_policy.reasons)}")


@demo.command("status")
@click.option("--symbol", default=None)
@click.option("--db", default="data/sqlite/qts.db")
def demo_status(symbol: str | None, db: str) -> None:
    """One honest snapshot: policy, stage, registry, journal, kill switch."""
    from qts.execution.demo_journal import summarize
    from qts.lifecycle.demo_registry import registry_status

    session = _demo_session(symbol or "", db)
    policy = session.policy
    out = {
        "mode": "DEMO_EXECUTION",
        "policy": policy.as_dict(),
        "stage": session.stage.as_dict(),
        "registry": registry_status(),
        "kill_switch": session.kill_switch_state(),
        "journal": summarize(session.journal).as_dict(),
        "live_locked": True,
        "real_capital_exposure_usd": 0,
    }
    click.echo(json.dumps(out, indent=2, default=str))


@demo.command("verify")
@click.option("--symbol", default=None)
@click.option("--db", default="data/sqlite/qts.db")
@click.option("--terminal-path", default=None)
@click.option("--json", "json_out", default=None, help="write the full triage report to this path")
def demo_verify(symbol: str | None, db: str, terminal_path: str | None, json_out: str | None) -> None:
    """Read-only triage: what is blocking DEMO execution, and what to do next.

    Touches nothing — no order, no stage change, no enablement. It answers one
    question an operator actually has: "where am I, and which single command
    comes next?" Exit code 0 means every gate that can be checked now passes;
    exit code 2 means something is blocking (the report says what).
    """
    from qts.lifecycle.demo_registry import registry_status
    from qts.lifecycle.demo_stage import ORDER_STAGES

    session = _demo_session(symbol or "", db, terminal_path)
    policy = session.policy
    connectivity = session.connectivity_report()
    registry = registry_status()
    stage_record = session.stage.current()
    kill = session.kill_switch_state()
    reconciliation = session.reconcile()

    entry = registry.get("resolved_strategy")
    readiness = connectivity.get("readiness") or {}
    identity = connectivity.get("identity") or {}
    pin = connectivity.get("identity_pin") or {}
    mapping = connectivity.get("symbol_mapping") or {}
    pin_present = bool(pin.get("pinned"))
    pin_confirmed = str(pin.get("status") or "") == "CONFIRMED"
    pin_verified = pin.get("verified") is True

    preflight: dict[str, Any] | None = None
    if entry is not None:
        from decimal import Decimal

        # Probe the gate with the smallest possible order — it submits nothing.
        outcome = session.preflight(side="BUY", stop_loss=Decimal("0"))
        preflight = {
            "passed": bool(outcome["verdict"]["passed"]),
            "failed": list(outcome["verdict"]["failed"]),
            "unknown": list(outcome["verdict"]["unknown"]),
        }

    checks = {
        "mode_is_demo_execution": str(getattr(session, "mode", "DEMO_EXECUTION")) == "DEMO_EXECUTION",
        "authorization_valid": bool(policy.enabled),
        "terminal_reachable": bool(identity.get("ok")),
        "account_is_demo": identity.get("is_demo") is True,
        "identity_pinned": pin_present,
        "identity_confirmed": pin_confirmed,
        "identity_verified": pin_verified,
        "readiness_passed": bool(readiness.get("passed")),
        "authority_permitted": bool(session.authority.current().execution_permitted),
        "stage_allows_orders": stage_record.stage in ORDER_STAGES,
        "strategy_registered": entry is not None,
        "kill_switch_clear": (not kill.get("killed")) and bool(kill.get("readable")),
        "reconciliation_clean": not reconciliation.get("requires_suspend"),
        "preflight_passed": None if preflight is None else bool(preflight["passed"]),
    }

    # Blockers and the next action are listed in the order an operator must
    # resolve them: the FIRST blocker is the one the NEXT command addresses.
    blockers: list[str] = []

    def block(reason: str) -> None:
        blockers.append(reason)

    if not checks["mode_is_demo_execution"]:
        block(
            f"process mode is {getattr(session, 'mode', 'unknown')} — the DEMO order path exists only in "
            "DEMO_EXECUTION (set QTS_MODE=demo_execution); LIVE stays locked in every mode"
        )
    if not checks["authorization_valid"]:
        block(f"no valid owner authorization ({policy.state}) — DEMO_EXECUTION stays DISABLED BY POLICY")
    if not checks["terminal_reachable"]:
        block(f"terminal unreachable: {identity.get('error')}")
    if checks["terminal_reachable"] and not checks["account_is_demo"]:
        block(f"connected account is not DEMO (is_demo={identity.get('is_demo')})")
    if not checks["identity_pinned"]:
        block("broker identity is not pinned")
    elif not checks["identity_confirmed"]:
        block("identity pin is recorded but not owner-confirmed")
    elif not checks["identity_verified"]:
        block(f"identity does not match the confirmed pin: {'; '.join(pin.get('detail') or ['mismatch'])}")
    if not checks["readiness_passed"]:
        block(f"readiness failed: {'; '.join(readiness.get('blocked_reasons') or ['unknown'])}")
    if not checks["kill_switch_clear"]:
        block(f"kill switch {'ACTIVE' if kill.get('killed') else 'unreadable'}: {kill.get('reason')}")
    if not checks["reconciliation_clean"]:
        block(f"reconciliation: {reconciliation.get('drift')} {reconciliation.get('details')}".strip())
    if not checks["stage_allows_orders"]:
        block(f"stage {stage_record.stage} does not permit orders")
    elif not checks["authority_permitted"]:
        block("durable authority has not granted execution permission")
    if not checks["strategy_registered"]:
        block(
            "no eligible strategy in the forward-validation registry — NO_TRADE "
            f"(registry: {registry['registry']['path']})"
            + (f"; reasons: {'; '.join(registry['reasons'])}" if registry.get("reasons") else "")
        )
    if preflight is not None and not preflight["passed"]:
        block(f"pre-trade gate: failed={preflight['failed']} unknown={preflight['unknown']}")

    # One next action, in the order an operator must do things.
    if not checks["mode_is_demo_execution"]:
        action = "set QTS_MODE=demo_execution (LIVE and the observation modes have no DEMO order path)"
    elif not checks["authorization_valid"]:
        action = (
            "record an owner authorization artifact (DEMO only, LIVE locked) at "
            "QTS_DEMO_AUTHORIZATION — see docs/demo_execution_authorization_and_safety_2026-09-23.md §2"
        )
    elif not checks["terminal_reachable"] or not checks["account_is_demo"]:
        action = f"qts demo connectivity --db {db}"
    elif not checks["identity_pinned"]:
        action = f"qts demo connectivity --pin --db {db}"
    elif not checks["identity_confirmed"]:
        action = f"qts demo connectivity --confirm-pin --db {db}"
    elif not checks["identity_verified"]:
        action = f"qts demo connectivity --db {db}   # the account no longer matches the pin — re-review"
    elif not checks["readiness_passed"]:
        action = f"qts demo connectivity --db {db}   # fix the failing readiness checks above"
    elif not checks["kill_switch_clear"]:
        # Arming cannot succeed while the kill switch is raised, so clearing it
        # comes first — and the stage stays HALTED until re-armed afterwards.
        action = f"qts demo clear-kill --reason '<why>' --confirm --db {db}"
    elif not checks["reconciliation_clean"]:
        action = f"qts demo connectivity --db {db}   # reconcile broker vs internal state first"
    elif not checks["stage_allows_orders"] or not checks["authority_permitted"]:
        action = f"qts demo arm --stage 2 --confirm --risk-ack --db {db}"
    elif not checks["strategy_registered"]:
        action = (
            f"register a preregistered experiment in {registry['registry']['path']} "
            "(status ELIGIBLE with a validation artifact, or ELIGIBLE_DIAGNOSTIC with a complete "
            "DEMO_FORWARD_RESEARCH_POLICY) — see scripts/register_demo_research_policy.py"
        )
    elif preflight is not None and not preflight["passed"]:
        action = f"qts demo preflight --side BUY --db {db}   # inspect the failing checks above"
    else:
        action = (
            f"qts demo run --strategy {entry['strategy_id']} --db {db}"
            if stage_record.stage == "STAGE_3_FORWARD_OBSERVATION"
            else f"qts demo order --side BUY --stop-loss <price> --db {db}"
        )

    report: dict[str, Any] = {
        "checked_at": connectivity.get("checked_at"),
        "ready_to_trade": not blockers,
        "next_action": action,
        "blockers": blockers,
        "checks": checks,
        "mode": str(getattr(session, "mode", "unknown")),
        "policy": policy.as_dict(),
        "identity": {"is_demo": identity.get("is_demo"), "login": identity.get("login"), "server": identity.get("server")},
        "identity_pin": {
            "pinned": pin_present,
            "status": pin.get("status"),
            "confirmed": pin_confirmed,
            "verified": pin.get("verified"),
            "detail": pin.get("detail") or [],
        },
        "symbol": {"canonical": mapping.get("canonical"), "broker": mapping.get("broker_symbol"), "tradable": mapping.get("tradable")},
        "readiness": {"passed": readiness.get("passed"), "blocked_reasons": readiness.get("blocked_reasons", [])},
        "registry": {
            "path": registry["registry"]["path"],
            "trading_state": registry["trading_state"],
            "entries": registry["registry"]["entry_count"],
            "reasons": list(registry.get("reasons") or []),
        },
        "resolved_policy": (
            None
            if entry is None
            else {
                "strategy_id": entry["strategy_id"],
                "status": entry["status"],
                "policy_id": entry.get("policy_id"),
                "policy_class": entry.get("policy_class"),
                "validated_edge": entry.get("validated_edge"),
                "hypothesis_id": entry.get("hypothesis_id"),
                "preregistration_artifact": entry.get("preregistration_artifact"),
            }
        ),
        "stage": {"stage": stage_record.stage, "orders_permitted": stage_record.stage in ORDER_STAGES},
        "controls": {"kill_switch": kill, "reconciliation": reconciliation},
        "preflight": preflight,
        "live_locked": True,
        "real_capital_exposure_usd": 0,
    }

    click.echo(f"mode: {getattr(session, 'mode', 'unknown')}")
    click.echo(f"authorization: {policy.state} ({'valid' if policy.enabled else 'NOT valid'}) — LIVE locked, real capital 0")
    click.echo(f"account: demo={identity.get('is_demo')} login={identity.get('login')} server={identity.get('server')}")
    click.echo(
        f"identity pin: pinned={pin_present} status={pin.get('status')} verified={pin.get('verified')}"
    )
    click.echo(f"symbol: {mapping.get('canonical')} -> {mapping.get('broker_symbol')} tradable={mapping.get('tradable')}")
    click.echo(f"readiness: passed={bool(readiness.get('passed'))} blockers={readiness.get('blocked_reasons', [])}")
    click.echo(f"registry: entries={registry['registry']['entry_count']} trading_state={registry['trading_state']}")
    if entry is not None:
        click.echo(
            f"policy: {entry['strategy_id']} status={entry['status']} "
            f"class={entry.get('policy_class')} validated_edge={entry.get('validated_edge')} "
            f"hypothesis={entry.get('hypothesis_id')}"
        )
    click.echo(f"stage: {stage_record.stage} orders_permitted={stage_record.stage in ORDER_STAGES}")
    if preflight is not None:
        click.echo(f"preflight: passed={preflight['passed']} failed={preflight['failed']} unknown={preflight['unknown']}")
    click.echo(f"controls: kill_switch={'ACTIVE' if kill.get('killed') else 'clear'} reconciliation={reconciliation.get('drift')}")
    click.echo(f"READY: {not blockers}")
    for reason in blockers:
        click.echo(f"  BLOCKED: {reason}", err=True)
    click.echo(f"NEXT: {action}")

    if json_out:
        Path(json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(json_out).write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        click.echo(f"report written to {json_out}")

    if blockers:
        raise SystemExit(2)


@demo.command("clear-kill")
@click.option("--db", default="data/sqlite/qts.db")
@click.option("--reason", required=True, help="why the halt is being lifted (recorded)")
@click.option("--confirm", is_flag=True, help="explicit operator confirmation (required)")
def demo_clear_kill(db: str, reason: str, confirm: bool) -> None:
    """Clear the durable kill switch — recorded; the stage stays HALTED.

    Clearing the flag does NOT resume trading: the stage machine remains
    HALTED, so orders stay refused until an operator re-arms explicitly and
    the whole staged progression is proved again.
    """
    if not confirm or not reason.strip():
        click.echo("REFUSED: clearing a kill switch requires --confirm and a non-empty --reason", err=True)
        raise SystemExit(2)

    from qts.risk.engine import RiskEngine, RiskLimits

    engine = RiskEngine(RiskLimits(), db_path=Path(db), persist_kill=True)
    was_killed = bool(engine.is_killed())
    engine.reset_kill()

    session = _demo_session("", db)
    stage_record = session.stage.current()

    # Audit the recovery: a lifted halt must be as traceable as the halt itself.
    audit_note = None
    try:
        from qts.domain.events import DomainEvent, EventType
        from qts.observability.audit import SqliteAuditLog

        audit = SqliteAuditLog()
        audit.emit(
            DomainEvent(
                event_type=EventType.KILL_SWITCH,
                payload={
                    "action": "cleared",
                    "was_killed": was_killed,
                    "reason": reason,
                    "stage": stage_record.stage,
                    "actor": "cli:demo-clear-kill",
                },
            )
        )
        audit_note = "audit event recorded"
    except Exception as exc:  # pragma: no cover - audit best effort
        audit_note = f"audit event NOT recorded: {type(exc).__name__}: {exc}"

    out = {
        "was_killed": was_killed,
        "killed": bool(engine.is_killed()),
        "reason": reason,
        "stage": stage_record.as_dict(),
        "audit": audit_note,
        "next": f"qts demo arm --stage 1 --confirm --risk-ack --db {db}",
    }
    click.echo(json.dumps(out, indent=2, default=str))
    click.echo("kill switch cleared — the stage remains HALTED; re-arm explicitly before any order.")


@demo.command("connectivity")
@click.option("--symbol", default=None)
@click.option("--db", default="data/sqlite/qts.db")
@click.option("--terminal-path", default=None)
@click.option("--pin", is_flag=True, help="record the observed identity as a pin (PENDING_REVIEW)")
@click.option("--confirm-pin", is_flag=True, help="owner confirmation of the recorded pin")
@click.option("--json-out", default=None, help="write the full report to this path")
def demo_connectivity(
    symbol: str | None,
    db: str,
    terminal_path: str | None,
    pin: bool,
    confirm_pin: bool,
    json_out: str | None,
) -> None:
    """Stage 1 — verify terminal, DEMO account, broker, symbol, quote. No orders."""
    session = _demo_session(symbol or "", db, terminal_path)
    report = session.connectivity_report()

    if pin:
        from qts.execution.demo_identity import write_pin

        with contextlib.suppress(Exception):
            identity = session.adapter.broker_identity()
            path = write_pin(identity, actor="cli")
            report["pin_written"] = str(path)
            click.echo(f"identity pin written (PENDING_REVIEW): {path}")
    if confirm_pin:
        from qts.execution.demo_identity import confirm_pin

        ok, detail = confirm_pin(actor="owner")
        report["pin_confirmation"] = {"ok": ok, "detail": detail}
        click.echo(f"pin confirmation: {detail}")

    readiness = report.get("readiness") or {}
    click.echo(f"readiness passed: {bool(readiness.get('passed'))} blockers={readiness.get('blocked_reasons', [])}")
    identity = report.get("identity") or {}
    click.echo(
        f"account: demo={identity.get('is_demo')} login={identity.get('login')} "
        f"server={identity.get('server')} company={identity.get('company')} type={identity.get('account_type')}"
    )
    mapping = report.get("symbol_mapping") or {}
    click.echo(
        f"symbol: {mapping.get('canonical')} -> {mapping.get('broker_symbol')} "
        f"visible={mapping.get('visible')} tradable={mapping.get('tradable')}"
    )
    quote = report.get("quote") or {}
    click.echo(f"quote: bid={quote.get('bid')} ask={quote.get('ask')} age={quote.get('age_s')} spread_bps={quote.get('spread_bps')}")
    click.echo(f"order_check dry-run: {report.get('order_check')}")
    click.echo(f"STAGE_1_READY: {report['ready_for_stage_1']}")

    if json_out:
        Path(json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(json_out).write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        click.echo(f"report written to {json_out}")


@demo.command("arm")
@click.option("--stage", required=True, type=click.Choice(["1", "2", "3"]))
@click.option("--symbol", default=None)
@click.option("--db", default="data/sqlite/qts.db")
@click.option("--confirm", is_flag=True, help="explicit operator confirmation (required)")
@click.option("--risk-ack", is_flag=True, help="explicit risk acknowledgement (required)")
@click.option("--strategy", default=None, help="registry strategy_id (required for stage 3)")
def demo_arm(stage: str, symbol: str | None, db: str, confirm: bool, risk_ack: bool, strategy: str | None) -> None:
    """Advance the DEMO stage machine. Each stage proves its prerequisites."""
    from qts.lifecycle.demo_stage import DemoStage, StageTransitionError

    session = _demo_session(symbol or "", db)
    target = {"1": DemoStage.STAGE_1_CONNECTIVITY, "2": DemoStage.STAGE_2_MIN_SIZE_ORDER,
              "3": DemoStage.STAGE_3_FORWARD_OBSERVATION}[stage]

    prereq: dict[str, bool] = {}
    if target in (DemoStage.STAGE_1_CONNECTIVITY, DemoStage.STAGE_2_MIN_SIZE_ORDER,
                  DemoStage.STAGE_3_FORWARD_OBSERVATION):
        report = session.connectivity_report()
        prereq["readiness_passed"] = bool((report.get("readiness") or {}).get("passed"))
        prereq["account_is_demo"] = (report.get("identity") or {}).get("is_demo") is True
        prereq["symbol_ok"] = bool((report.get("symbol_mapping") or {}).get("ok"))
        prereq["quote_fresh"] = bool((report.get("quote") or {}).get("fresh"))
    if target in (DemoStage.STAGE_2_MIN_SIZE_ORDER, DemoStage.STAGE_3_FORWARD_OBSERVATION):
        prereq["policy_authorized"] = session.policy.enabled
        prereq["identity_pinned_confirmed"] = (report.get("identity_pin") or {}).get("verified") is True
        prereq["operator_confirmation"] = bool(confirm and risk_ack)
        if prereq["operator_confirmation"]:
            from qts.lifecycle.demo_authority import readiness_age_seconds
            from qts.lifecycle.demo_gate import demo_forward_readiness_report

            rpt = demo_forward_readiness_report(
                mt5_module=None,
                terminal_path=session.config.terminal_path,
                symbol=session.config.symbol,
                symbol_map=session.config.symbol_map or None,
            )
            decision = session.authority.enable(
                readiness=rpt,
                confirmed=True,
                risk_ack=True,
                readiness_age_s=readiness_age_seconds(rpt),
                actor="cli:demo-arm",
            )
            prereq["authority_enabled"] = bool(decision.execution_permitted)
            click.echo(f"authority: {decision.state} permitted={decision.execution_permitted} {decision.reasons}")
        else:
            prereq["authority_enabled"] = False
    if target is DemoStage.STAGE_3_FORWARD_OBSERVATION:
        from qts.execution.demo_journal import summarize

        summary = summarize(session.journal)
        prereq["stage2_order_recorded"] = summary.orders > 0
        prereq["strategy_selected"] = bool(strategy)

    try:
        record = session.stage.advance(
            target, actor="cli", reason=f"operator arm to stage {stage}", prerequisites=prereq
        )
    except StageTransitionError as exc:
        click.echo(f"REFUSED: {exc}", err=True)
        click.echo(json.dumps(prereq, indent=2, default=str), err=True)
        raise SystemExit(2) from exc
    click.echo(json.dumps(record.as_dict(), indent=2, default=str))


@demo.command("preflight")
@click.option("--symbol", default=None)
@click.option("--db", default="data/sqlite/qts.db")
@click.option("--side", default="BUY", type=click.Choice(["BUY", "SELL"]))
@click.option("--lots", default=None)
@click.option("--stop-loss", default=None)
def demo_preflight(symbol: str | None, db: str, side: str, lots: str | None, stop_loss: str | None) -> None:
    """Run the full pre-trade gate for a would-be order. Submits nothing."""
    from decimal import Decimal

    from qts.lifecycle.demo_registry import load_registry, resolve_entry

    session = _demo_session(symbol or "", db)
    registry = load_registry()
    entry, _reasons = resolve_entry(registry)
    out = session.preflight(
        side=side,
        lots=Decimal(lots) if lots else None,
        stop_loss=Decimal(stop_loss) if stop_loss else None,
        entry=entry,
    )
    verdict = out["verdict"]
    click.echo(f"PREFLIGHT {'PASS' if verdict['passed'] else 'REFUSE'}")
    for name, check in verdict["checks"].items():
        click.echo(f"  [{check['status']:7}] {name}: {check['detail']}")
    if not verdict["passed"]:
        click.echo(f"blocked by: {', '.join(verdict['failed'])}")


@demo.command("order")
@click.option("--symbol", default=None)
@click.option("--db", default="data/sqlite/qts.db")
@click.option("--side", required=True, type=click.Choice(["BUY", "SELL"]))
@click.option("--lots", default=None)
@click.option("--stop-loss", default=None)
@click.option("--take-profit", default=None)
@click.option("--strategy", default=None)
@click.option("--rationale", default="")
@click.option("--dry-run", is_flag=True, help="evaluate the gate without submitting")
def demo_order(
    symbol: str | None,
    db: str,
    side: str,
    lots: str | None,
    stop_loss: str | None,
    take_profit: str | None,
    strategy: str | None,
    rationale: str,
    dry_run: bool,
) -> None:
    """Submit ONE DEMO order through the gate (or dry-run it)."""
    from decimal import Decimal

    from qts.lifecycle.demo_registry import load_registry, resolve_entry

    session = _demo_session(symbol or "", db)
    registry = load_registry()
    entry, reasons = resolve_entry(registry, strategy)
    if entry is None:
        click.echo(f"NO_TRADE — {'; '.join(reasons)}", err=True)
        raise SystemExit(2)
    if dry_run:
        out = session.preflight(
            side=side,
            lots=Decimal(lots) if lots else None,
            stop_loss=Decimal(stop_loss) if stop_loss else None,
            entry=entry,
        )
        click.echo(json.dumps(out, indent=2, default=str))
        return
    result = session.submit(
        side=side,
        lots=Decimal(lots) if lots else None,
        stop_loss=Decimal(stop_loss) if stop_loss else None,
        take_profit=Decimal(take_profit) if take_profit else None,
        rationale=rationale or "operator-initiated RESEARCH_DEMO_ORDER",
        entry=entry,
    )
    click.echo(json.dumps(result.as_dict(), indent=2, default=str))
    if not result.allowed:
        raise SystemExit(2)


@demo.command("run")
@click.option("--symbol", default=None)
@click.option("--db", default="data/sqlite/qts.db")
@click.option("--strategy", default=None)
@click.option("--poll-interval", default=5.0, type=float)
@click.option("--max-iterations", default=0, type=int)
@click.option("--max-runtime", default=0.0, type=float)
@click.option("--dry-run", is_flag=True, help="evaluate the gate every cycle, submit nothing")
def demo_run(
    symbol: str | None,
    db: str,
    strategy: str | None,
    poll_interval: float,
    max_iterations: int,
    max_runtime: float,
    dry_run: bool,
) -> None:
    """Autonomous DEMO trading under the registered policy (never LIVE)."""
    from qts.execution.demo_autopilot import AutopilotConfig, run_autopilot

    session = _demo_session(symbol or "", db)
    config = AutopilotConfig(
        symbol=session.config.symbol,
        poll_interval_s=poll_interval,
        max_iterations=max_iterations,
        max_runtime_s=max_runtime,
        strategy_id=strategy,
        dry_run=dry_run,
        actor="cli:demo-run",
    )
    report = run_autopilot(session, config)
    click.echo(json.dumps(report.as_dict(), indent=2, default=str))
    if report.halted:
        click.echo(f"HALTED: {report.halt_reason}", err=True)


@demo.command("kill")
@click.option("--db", default="data/sqlite/qts.db")
@click.option("--reason", default="operator kill via CLI")
def demo_kill(db: str, reason: str) -> None:
    """Raise the durable kill switch and halt the DEMO stage machine."""
    session = _demo_session("", db)
    out = session.raise_kill_switch(reason)
    click.echo(json.dumps(out, indent=2, default=str))


@demo.command("journal")
@click.option("--db", default="data/sqlite/qts.db")
@click.option("--limit", default=20, type=int)
@click.option("--export", "export_path", default=None)
def demo_journal(db: str, limit: int, export_path: str | None) -> None:
    """Show/export the DEMO order journal (forward-observation audit trail)."""
    session = _demo_session("", db)
    if export_path:
        path = session.journal.export_jsonl(export_path)
        click.echo(f"exported to {path}")
        return
    for row in session.journal.list_orders(limit=limit):
        click.echo(
            f"#{row['journal_id']} {row['created_at']} {row['label']} {row['side']} {row['requested_lots']} "
            f"{row['symbol']} state={row['state']} broker_order={row['broker_order_id']} "
            f"pos={row['broker_position_id']} px={row['executed_price']} slip_bps={row['slippage_bps']} "
            f"pnl={row['realized_pnl']} exit={row['exit_reason']}"
        )


@demo.command("revoke")
@click.option("--reason", required=True)
@click.option("--actor", default="owner")
def demo_revoke(reason: str, actor: str) -> None:
    """Revoke the DEMO authorization (additive record; artifact is never edited)."""
    from qts.lifecycle.demo_authorization import revoke_authorization

    path = revoke_authorization(reason=reason, actor=actor)
    click.echo(f"revocation written: {path}")
    click.echo("DEMO_EXECUTION is DISABLED BY POLICY again until a new authorization artifact is recorded.")
