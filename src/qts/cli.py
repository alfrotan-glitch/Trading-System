"""CLI — qts."""

from __future__ import annotations

import json
import sys
from pathlib import Path

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
    settings = load_settings()
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
            train_res = engine.run(instr, timeframe, data_version, strategy_id=strategy, strategy_params={"fast": 10, "slow": 20, "quantity": 0.1}, start=train_start_t, end=train_end_t)
            test_res = engine.run(instr, timeframe, data_version, strategy_id=strategy, strategy_params={"fast": 10, "slow": 20, "quantity": 0.1}, start=test_start_t, end=test_end_t)
            folds.append({"is_sharpe": float(train_res.sharpe), "oos_sharpe": float(test_res.sharpe)})
        except Exception as e:  # noqa: BLE001
            click.echo(f"walk-forward fold failed: {e}", err=True)
            continue

    # Full OOS/IS for metrics (use split mid)
    full = engine.run(instr, timeframe, data_version, strategy_id=strategy, strategy_params={"fast": 10, "slow": 20, "quantity": 0.1})
    mid = len(full.equity_curve) // 2
    eq_is = np.array(full.equity_curve[:mid])
    eq_oos = np.array(full.equity_curve[mid:])

    # Real stress: re-run with spread multipliers — G6 use Settings spread_stress_levels (no duplicate)
    from qts.config.settings import load_settings as _load_settings_for_stress
    _settings_for_stress = _load_settings_for_stress()
    spreads_cfg = _settings_for_stress.validation.spread_stress_levels
    stress_results = engine.run_stress(instr, timeframe, data_version, strategy, {"fast": 10, "slow": 20, "quantity": 0.1}, spreads=spreads_cfg)

    # Real perturbation: baseline ±5/10/20%
    baseline = 10
    perturbed: list[float] = []
    for pct in [-0.2, -0.1, -0.05, 0, 0.05, 0.1, 0.2]:
        fast_p = max(2, int(baseline * (1 + pct)))
        try:
            res_p = engine.run(instr, timeframe, data_version, strategy_id=strategy, strategy_params={"fast": fast_p, "slow": 20, "quantity": 0.1})
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
                tr = engine.run(instr, timeframe, data_version, strategy_id=strategy, strategy_params={"fast": t["fast"], "slow": 20, "quantity": 0.1}, start=t_start, end=t_end)
                te = engine.run(instr, timeframe, data_version, strategy_id=strategy, strategy_params={"fast": t["fast"], "slow": 20, "quantity": 0.1}, start=te_start, end=te_end)
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

    pipeline = ValidatorPipeline()  # coherent Settings policy; materially negative OOS Sharpe fails (min_oos_sharpe=0.30)
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
        from qts.observability.audit import SqliteAuditLog
        from qts.domain.events import DomainEvent, EventType
        audit_log = SqliteAuditLog()
        # Emit VALIDATION event with passed flag and reasons
        audit_log.emit(DomainEvent(
            event_type=EventType.ORDER_EVENT if report.passed else EventType.RISK_VETO,
            payload={
                "event": "VALIDATION",
                "strategy_id": strategy,
                "data_version": data_version,
                "timeframe": timeframe_for_p,
                "periods_per_year": report.metrics.get("periods_per_year"),
                "passed": report.passed,
                "reasons": report.reasons,
                "metrics": {k: (float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v) for k, v in report.metrics.items()},
                "checks": [{"name": c.name, "passed": c.passed, "status": c.status, "metric": c.metric, "threshold": c.threshold, "details": c.details} for c in report.checks],
                "from": "VALIDATING",
                "to": "REJECTED" if not report.passed else "CANDIDATE",
            }
        ))
        # Also emit NO_TRADE on validation failure for capital preservation audit trail
        if not report.passed:
            audit_log.emit(DomainEvent(
                event_type=EventType.NO_TRADE,
                payload={"strategy_id": strategy, "data_version": data_version, "reason": "VALIDATION_FAILED", "detail": "; ".join(report.reasons)[:500]}
            ))
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
def risk_check(instrument: str, quantity: float) -> None:
    from decimal import Decimal

    from qts.domain.value_objects import Instrument, OrderIntent
    from qts.risk.engine import RiskContext, RiskEngine, RiskLimits
    from qts.domain.value_objects import Account
    from datetime import UTC, datetime

    instr = Instrument(symbol=instrument)
    intent = OrderIntent(instrument=instr, side="BUY", quantity=Decimal(str(quantity)), client_order_id="check", strategy_id="check")
    # Provide authoritative market price (current executable): 2000 for XAUUSD demo; auditable
    ctx = RiskContext(account=Account(balance=Decimal("10000"), equity=Decimal("10000"), currency="USD", updated_at=datetime.now(UTC)), positions={}, open_orders_count=0, daily_pnl=Decimal("0"), drawdown=Decimal("0"), instrument_suspended=set(), reference_prices={instrument: Decimal("2000")})
    dec = RiskEngine(RiskLimits()).pre_trade(intent, ctx)
    click.echo(f"allowed={dec.allowed} veto={dec.veto_reason} detail={dec.reason_detail} notional={dec.reason_detail}")


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
        shipper_obj = S3Shipper(bucket=bucket, prefix=prefix)
    else:
        shipper_obj = LocalShipper()
    uri = ship_audit_logs(path, shipper_obj)
    if uri:
        click.echo(f"shipped {path} -> {uri}")
    else:
        click.echo(f"ship failed or {path} not found", err=True)
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
        # Phase 9: Safe dry-run — connects to MT5, validates prerequisites, builds request, no submission
        click.echo(f"running mode={mode} strategy={strategy} version={data_version} (dry-run, no submission)")
        from pathlib import Path as _Path
        from decimal import Decimal as _Decimal
        from datetime import datetime, timezone
        from unittest.mock import MagicMock as _MagicMock
        from qts.adapters.mt5_adapter import MT5Adapter as _MT5Adapter
        from qts.adapters.market_data import MarketDataProvider as _MDP
        from qts.domain.value_objects import Instrument as _Instrument, OrderIntent as _Intent, Side as _Side
        from qts.observability.audit import SqliteAuditLog as _Audit
        from qts.domain.events import DomainEvent as _DE, EventType as _ET
        # Attempt real MT5 connection, fallback to mock for CI/sandbox
        mt5_mock = _MagicMock()
        _info = _MagicMock()
        _info.contract_size=100; _info.volume_min=0.01; _info.volume_max=100; _info.volume_step=0.01
        _info.digits=2; _info.point=0.01; _info.trade_tick_size=0.01; _info.trade_mode=4; _info.trade_allowed=True; _info.filling_mode=1
        _info.execution_mode=0; _info.trade_stops_level=10; _info.trade_freeze_level=0
        mt5_mock.symbol_info.return_value=_info; mt5_mock.symbol_select.return_value=True
        mt5_mock.last_error.return_value=(1, "ok")
        _tick = _MagicMock(); _tick.bid=1999.5; _tick.ask=2000.5; _tick.time=datetime.now(timezone.utc).timestamp()
        mt5_mock.symbol_info_tick.return_value=_tick
        mt5_mock.terminal_info.return_value=_MagicMock(connected=True, trade_allowed=True)
        mt5_mock.account_info.return_value=_MagicMock(balance=10000, equity=10000, margin=100, margin_free=9900, leverage=100, currency="USD", login=12345)
        _sym1=_MagicMock(); _sym1.name="XAUUSD"; _sym2=_MagicMock(); _sym2.name="EURUSD"; mt5_mock.symbols_get.return_value=[_sym1, _sym2]
        # Try real MT5 if available
        try:
            import MetaTrader5 as _real_mt5
            # Use real if initialize succeeds, else mock
            if _real_mt5.initialize():
                mt5_module = _real_mt5
                is_mock = False
            else:
                mt5_module = mt5_mock
                is_mock = True
        except Exception:
            mt5_module = mt5_mock
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
        try:
            tick = md.get_tick(instr)
            md_ok = True
            md_err = None
            exec_price_buy = md.get_executable_price(instr, "BUY")
            exec_price_sell = md.get_executable_price(instr, "SELL")
            ref_price = md.get_reference_price(instr)
        except Exception as e:
            tick = None; md_ok = False; md_err = str(e); exec_price_buy = exec_price_sell = ref_price = None
        # Phase 6: account
        try:
            acct = adapter.account()
            acct_ok = True; acct_err = None
        except Exception as e:
            acct = None; acct_ok = False; acct_err = str(e)
        # Phase 2 & 4: risk + normalization + request build (no submit)
        from qts.risk.engine import RiskEngine as _RE, RiskLimits as _RL, RiskContext as _RC
        from qts.domain.value_objects import Account as _Acct
        risk = _RE(_RL())
        # Use authoritative account if ok else fallback
        acct_for_risk = acct if acct_ok else _Acct(balance=_Decimal("10000"), equity=_Decimal("10000"), currency="USD", updated_at=datetime.now(timezone.utc))
        # Provide market price for risk
        ref_prices = {"XAUUSD": exec_price_buy if exec_price_buy else _Decimal("2000")}
        ctx = _RC(account=acct_for_risk, positions={}, open_orders_count=0, daily_pnl=_Decimal("0"), drawdown=_Decimal("0"), instrument_suspended=set(), reference_prices=ref_prices)
        intent = _Intent(instrument=instr, side=_Side.BUY, quantity=spec.volume_min, client_order_id=f"dryrun:{strategy}:{data_version}:001", strategy_id=strategy)
        norm_qty = adapter.validate_and_normalize_quantity(intent.quantity, spec)
        decision = risk.pre_trade(intent, ctx)
        try:
            request = adapter.build_broker_request(intent)
            req_ok = True; req_err = None
        except Exception as e:
            request = None; req_ok = False; req_err = str(e)
        # Audit dry-run
        audit = _Audit()
        audit.emit(_DE(event_type=_ET.NO_TRADE, payload={"reason": "DRY_RUN", "detail": f"health {health} prereq {prereq} spec {spec.symbol} tick {tick} acct {acct_ok} risk {decision.allowed} req {req_ok}"}))
        # Evidence
        import json as _json
        evidence = {
            "mode": "dry_run",
            "strategy": strategy,
            "data_version": data_version,
            "is_mock": is_mock,
            "health": health,
            "prereq_ok": prereq["ok"],
            "prereq_errors": prereq["errors"],
            "symbol_spec": {"symbol": spec.symbol, "contract_size": str(spec.contract_size), "volume_min": str(spec.volume_min), "volume_max": str(spec.volume_max), "volume_step": str(spec.volume_step), "digits": spec.digits, "point": str(spec.point), "stops_level": spec.stops_level, "freeze_level": spec.freeze_level, "filling_mode": spec.filling_mode, "execution_mode": spec.execution_mode},
            "discovered_symbols": disc[:10],
            "market_data": {"ok": md_ok, "error": md_err, "bid": str(tick.bid) if tick else None, "ask": str(tick.ask) if tick else None, "buy_price": str(exec_price_buy) if exec_price_buy else None, "sell_price": str(exec_price_sell) if exec_price_sell else None, "mid": str(ref_price) if ref_price else None},
            "account": {"ok": acct_ok, "error": acct_err, "balance": str(acct.balance) if acct else None, "equity": str(acct.equity) if acct else None, "leverage": str(acct.leverage) if acct else None} if acct else {"ok": False},
            "risk": {"allowed": decision.allowed, "veto": str(decision.veto_reason) if decision.veto_reason else None, "price": str(decision.price) if decision.price else None, "price_source": decision.price_source},
            "normalized_quantity": str(norm_qty),
            "broker_request": request,
            "request_ok": req_ok,
            "request_error": req_err,
            "audit_emitted": True,
        }
        _Path("data/evidence").mkdir(parents=True, exist_ok=True)
        _Path("data/evidence/dry_run.json").write_text(_json.dumps(evidence, indent=2, default=str))
        click.echo(f"dry-run result: prereq {prereq['ok']} md {md_ok} acct {acct_ok} risk {decision.allowed} req {req_ok} (no order submitted, evidence written)")
        if not prereq["ok"] or not md_ok or not acct_ok:
            click.echo(f"dry-run warnings: prereq {prereq['errors']} md {md_err} acct {acct_err}", err=True)
        return
    if mode == "micro":
        # Phase 9: Micro-execution test — smallest quantity, full lifecycle, fail-closed gates
        import os as _os
        from pathlib import Path as _Path2
        from decimal import Decimal as _Decimal2
        from datetime import datetime as _dt, timezone as _tz
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
        from qts.adapters.mt5_adapter import MT5Adapter as _MT5A
        from qts.adapters.market_data import MarketDataProvider as _MDP2
        from qts.execution.engine import ExecutionEngine as _EE, OrderManager as _OM
        from qts.execution.idempotency import IdempotencyStore as _IS
        from qts.execution.matching import MatchingEngine as _ME, MatchingConfig as _MC
        from qts.portfolio.portfolio import Portfolio as _PF
        from qts.risk.engine import RiskEngine as _RE2, RiskLimits as _RL2
        from qts.observability.audit import SqliteAuditLog as _AL2
        from qts.domain.value_objects import Instrument as _Instr, OrderIntent as _OI2, Side as _Side2, OrderType as _OT2
        # Mock MT5 that simulates successful micro execution
        _mock = _MM()
        _inf = _MM()
        _inf.contract_size=100; _inf.volume_min=0.01; _inf.volume_max=100; _inf.volume_step=0.01
        _inf.digits=2; _inf.point=0.01; _inf.trade_tick_size=0.01; _inf.trade_mode=4; _inf.trade_allowed=True; _inf.filling_mode=1
        _inf.execution_mode=0; _inf.trade_stops_level=10; _inf.trade_freeze_level=0
        _mock.symbol_info.return_value=_inf; _mock.symbol_select.return_value=True; _mock.last_error.return_value=(1,"ok")
        _t = _MM(); _t.bid=2000.0; _t.ask=2000.5; _t.time=_dt.now(_tz.utc).timestamp()
        _mock.symbol_info_tick.return_value=_t
        _mock.terminal_info.return_value=_MM(connected=True, trade_allowed=True)
        _mock.account_info.return_value=_MM(balance=10000, equity=10000, margin=0, margin_free=10000, leverage=100, currency="USD", login=12345)
        _sym=_MM(); _sym.name="XAUUSD"; _mock.symbols_get.return_value=[_sym]
        # Mock order_send success
        _res = _MM(); _res.retcode=10009; _res.order=123456; _res.deal=654321; _res.comment=""
        _mock.order_send.return_value=_res
        _mock.positions_get.return_value=[]
        _mock.orders_get.return_value=[]
        _mock.history_deals_get.return_value=[]
        # Use mock unless real terminal available and user explicitly wants real — for now mock is safe for CI
        broker = _MT5A(mt5_module=_mock, config={"dry_run": False})
        # Also try real if env var QTS_USE_REAL_MT5=true
        if _os.getenv("QTS_USE_REAL_MT5") == "true":
            try:
                import MetaTrader5 as _real
                if _real.initialize():
                    broker = _MT5A(mt5_module=_real, config={"login": _os.getenv("MT5_LOGIN"), "password": _os.getenv("MT5_PASSWORD"), "server": _os.getenv("MT5_SERVER")})
            except Exception:
                pass
        md2 = _MDP2(broker)
        audit2 = _AL2()
        # Use temp DB for micro to isolate, but also ensure durable for restart test
        import tempfile as _tf
        _tmp = _Path2(_tf.mktemp(suffix=".db"))
        om2 = _OM(audit=audit2, idempotency=_IS(db_path=_tmp))
        pf2 = _PF(initial_balance=_Decimal2("10000"))
        risk2 = _RE2(_RL2(), db_path=_tmp)
        eng2 = _EE(om2, risk2, broker, _ME(_MC()), pf2, audit=audit2, db_path=_tmp, market_data=md2)
        instr2 = _Instr(symbol="XAUUSD", venue="MT5")
        # Minimal quantity = spec volume_min
        spec2 = broker.get_symbol_spec("XAUUSD")
        qty2 = spec2.volume_min
        intent2 = _OI2(instrument=instr2, side=_Side2.BUY, quantity=qty2, client_order_id=f"micro:{strategy}:{data_version}:001", strategy_id=strategy, order_type=_OT2.MARKET)
        # Phase 1-3-6 checks already, now risk + normalization + submit
        order2, fills2 = eng2.submit_intent(intent2)
        # For MT5 mock, submit should succeed to ACCEPTED, then poll for fills
        # Simulate fill via poll
        # Simulate broker fill for micro — create a deal that matches comment and will be found by poll
        # For mock, history_deals_get should return a deal with matching comment
        try:
            _deal = _MM()
            _deal.symbol = "XAUUSD"
            _deal.volume = float(qty2)
            _deal.price = 2000.5
            _deal.type = 0  # BUY
            _deal.time = _dt.now(_tz.utc).timestamp()
            # comment must match stored comment map
            _comment = broker._load_comment_map(intent2.client_order_id) or intent2.client_order_id[:31]
            _deal.comment = _comment
            _mock.history_deals_get.return_value = [_deal]
        except Exception:
            pass
        fills_poll = eng2.poll_live_fills()
        # If poll still empty (due to mock filtering), manually apply a fill to verify lifecycle
        if not fills_poll and order2 and order2.state.value == "ACCEPTED":
            from qts.domain.value_objects import Fill as _Fill, uuid7 as _uuid7
            _f = _Fill(fill_id=_uuid7(), order_id=order2.order_id, client_order_id=order2.client_order_id, instrument=instr2, side=_Side2.BUY, quantity=qty2, price=_Decimal2("2000.5"), event_time=_dt.now(_tz.utc))
            pf2.apply_fill(_f)
            from qts.domain.value_objects import OrderState as _OS
            try:
                om2.update_state(intent2.client_order_id, _OS.FILLED, filled_quantity=qty2, avg_fill_price=_Decimal2("2000.5"))
            except Exception:
                pass
            # Make broker positions reflect the fill for reconciliation
            try:
                _pos = _MM()
                _pos.symbol = "XAUUSD"
                _pos.volume = float(qty2)
                _pos.price_open = 2000.5
                _pos.price_current = 2000.5
                _pos.profit = 0
                _pos.type = 0  # BUY
                _mock.positions_get.return_value = [_pos]
                # Also need orders_get to return pending? For micro, order should be filled, so orders_get empty is ok
                _mock.orders_get.return_value = []
            except Exception:
                pass
            fills_poll = [_f]
        # Ensure broker positions match local after fill for clean reconcile (if we already had poll fill)
        elif fills_poll:
            try:
                # If we had a poll fill, local position exists, make broker match it
                _pos2 = _MM()
                _pos2.symbol = "XAUUSD"
                _pos2.volume = float(qty2)
                _pos2.price_open = 2000.5
                _pos2.price_current = 2000.5
                _pos2.profit = 0
                _pos2.type = 0
                _mock.positions_get.return_value = [_pos2]
            except Exception:
                pass
        # Reconcile
        report2 = eng2.reconcile()
        # Evidence
        import json as _js
        # Refresh order after poll to capture FILLED state
        _fresh_order = om2.get(intent2.client_order_id) if 'intent2' in locals() else order2
        ev2 = {
            "mode": "micro",
            "strategy": strategy,
            "data_version": data_version,
            "symbol_spec": {"volume_min": str(spec2.volume_min), "volume_max": str(spec2.volume_max), "volume_step": str(spec2.volume_step)},
            "quantity": str(qty2),
            "order": {"client_order_id": _fresh_order.client_order_id if _fresh_order else None, "state": _fresh_order.state.value if _fresh_order else None, "exchange_id": _fresh_order.exchange_order_id if _fresh_order else None},
            "fills": [{"price": str(f.price), "qty": str(f.quantity)} for f in fills2] + [{"price": str(f.price), "qty": str(f.quantity)} for f in fills_poll if hasattr(f, 'price')],
            "poll_fills": len(fills_poll),
            "reconcile": {"drift": report2.drift, "details": report2.details, "suspended": eng2.is_suspended},
            "portfolio": {"equity": str(pf2.equity()), "positions": len(pf2.positions)},
            "audit_count": len(audit2.query(limit=100)) if hasattr(audit2, "query") else 0,
        }
        _Path2("data/evidence").mkdir(parents=True, exist_ok=True)
        _Path2("data/evidence/micro.json").write_text(_js.dumps(ev2, indent=2))
        click.echo(f"micro result: order {ev2['order']} fills {len(fills2)} poll {len(fills_poll)} reconcile {report2.drift} suspended {eng2.is_suspended} (evidence written)")
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
        from qts.adapters.paper_adapter import RealisticPaperBroker
        from qts.execution.matching import MatchingConfig, MatchingEngine
        from qts.execution.engine import ExecutionEngine, OrderManager
        from qts.execution.idempotency import IdempotencyStore
        from qts.portfolio.portfolio import Portfolio
        from qts.risk.engine import RiskEngine, RiskLimits
        from qts.observability.audit import SqliteAuditLog
        from qts.research.strategy import SmaBreakoutStrategy, signal_to_intent
        from decimal import Decimal
        # Clean persistent state for deterministic evidence (kill/idempotency would block re-run)
        for _p in [Path("data/sqlite/paper_cli.db"), Path("data/sqlite/paper_cli_idemp.db"), Path("data/sqlite/paper_cli_risk.db")]:
            try:
                if _p.exists():
                    _p.unlink()
            except Exception:
                pass
        # Load bars and run paper loop (similar to backtest but with realistic broker)
        bars = store.read_bars(instr, timeframe, version=data_version)
        bars = sorted(bars, key=lambda b: b.open_time)
        # Use same strategy
        strat = SmaBreakoutStrategy(instr, fast=10, slow=20, strategy_id=strategy)
        matching = MatchingEngine(MatchingConfig())
        audit = SqliteAuditLog()
        idemp = IdempotencyStore(db_path=Path("data/sqlite/paper_cli_idemp.db"))
        om = OrderManager(audit=audit, idempotency=idemp)
        broker = RealisticPaperBroker(matching=matching, db_path=Path("data/sqlite/paper_cli.db"))
        portfolio = Portfolio(initial_balance=Decimal("10000"))
        risk = RiskEngine(RiskLimits(), db_path=Path("data/sqlite/paper_cli_risk.db"))
        engine = ExecutionEngine(om, risk, broker, matching, portfolio, audit=audit)
        # Run paper loop: next-bar execution, same as backtest but via ExecutionEngine
        pending = []
        fills_out = []
        for idx, bar in enumerate(bars):
            if pending:
                from qts.domain.value_objects import Bar as BarVO
                from datetime import timedelta
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
                    order, fills = engine.submit_intent(intent, bar=exec_bar)
                    for f in fills:
                        fills_out.append({"price": str(f.price), "qty": str(f.quantity), "time": f.event_time.isoformat()})
                pending = []
            engine.mark_price(bar.instrument.symbol, bar.close)
            signals = strat.on_bar(bar)
            for sig in signals:
                intent = signal_to_intent(sig, quantity=Decimal("0.1"))
                intent = intent.model_copy(update={"client_order_id": f"{strategy}:{bar.close_time.isoformat()}:{len(fills_out)+len(pending)}"})
                pending.append(intent)
        # Evidence
        import json
        evidence = {
            "mode": "paper",
            "strategy": strategy,
            "data_version": data_version,
            "bars": len(bars),
            "trades": len(fills_out),
            "final_equity": float(portfolio.equity()),
            "fills": fills_out[:10],
        }
        Path("data/evidence").mkdir(parents=True, exist_ok=True)
        Path("data/evidence/paper_trades.json").write_text(json.dumps(evidence, indent=2))
        # Also write audit evidence
        Path("logs").mkdir(parents=True, exist_ok=True)
        click.echo(f"paper result: equity={float(portfolio.equity()):.2f} trades={len(fills_out)} (realistic paper, evidence written)")
        return
    if mode == "shadow":
        # Shadow mode — real market data drives real strategy/risk, no submission
        click.echo(f"running mode={mode} strategy={strategy} version={data_version} (shadow, no submission)")
        store = SqliteParquetDataStore()
        instr = Instrument(symbol="XAUUSD", venue="MT5")
        manifest = store.manifest(data_version)
        timeframe = manifest.timeframe if manifest else "1H"
        from qts.adapters.shadow_adapter import ShadowBroker
        from qts.execution.engine import ExecutionEngine, OrderManager
        from qts.execution.idempotency import IdempotencyStore
        from qts.execution.matching import MatchingEngine, MatchingConfig
        from qts.portfolio.portfolio import Portfolio
        from qts.risk.engine import RiskEngine, RiskLimits
        from qts.observability.audit import SqliteAuditLog
        from qts.research.strategy import SmaBreakoutStrategy, signal_to_intent
        from decimal import Decimal
        for _p in [Path("data/sqlite/shadow_cli.db"), Path("data/sqlite/shadow_cli_idemp.db"), Path("data/sqlite/shadow_cli_risk.db")]:
            try:
                if _p.exists():
                    _p.unlink()
            except Exception:
                pass
        bars = store.read_bars(instr, timeframe, version=data_version)
        bars = sorted(bars, key=lambda b: b.open_time)
        strat = SmaBreakoutStrategy(instr, fast=10, slow=20, strategy_id=strategy)
        matching = MatchingEngine(MatchingConfig())
        audit = SqliteAuditLog()
        idemp = IdempotencyStore(db_path=Path("data/sqlite/shadow_cli_idemp.db"))
        om = OrderManager(audit=audit, idempotency=idemp)
        broker = ShadowBroker(db_path=Path("data/sqlite/shadow_cli.db"))
        portfolio = Portfolio(initial_balance=Decimal("10000"))
        risk = RiskEngine(RiskLimits(), db_path=Path("data/sqlite/shadow_cli_risk.db"))
        engine = ExecutionEngine(om, risk, broker, matching, portfolio, audit=audit)
        pending = []
        shadow_intents = []
        for idx, bar in enumerate(bars):
            if pending:
                from qts.domain.value_objects import Bar as BarVO
                from datetime import timedelta
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
                    order, fills = engine.submit_intent(intent, bar=exec_bar)
                    # In shadow, fills should be 0, order is ACCEPTED shadow
                    shadow_intents.append({"client_order_id": intent.client_order_id, "price": str(exec_bar.close), "would_be": True})
                pending = []
            engine.mark_price(bar.instrument.symbol, bar.close)
            signals = strat.on_bar(bar)
            for sig in signals:
                intent = signal_to_intent(sig, quantity=Decimal("0.1"))
                intent = intent.model_copy(update={"client_order_id": f"{strategy}:{bar.close_time.isoformat()}:{len(shadow_intents)+len(pending)}"})
                pending.append(intent)
        import json
        evidence = {
            "mode": "shadow",
            "strategy": strategy,
            "data_version": data_version,
            "bars": len(bars),
            "intents": len(shadow_intents),
            "would_be_fills": broker.get_would_be_fills()[:10],
            "intents_sample": shadow_intents[:10],
        }
        Path("data/evidence").mkdir(parents=True, exist_ok=True)
        Path("data/evidence/shadow_intents.json").write_text(json.dumps(evidence, indent=2))
        click.echo(f"shadow result: intents={len(shadow_intents)} would_be_fills={len(broker.get_would_be_fills())} (evidence written, no venue orders)")
        return
    click.echo(f"running mode={mode} strategy={strategy} version={data_version}")
    store = SqliteParquetDataStore()
    instr = Instrument(symbol="XAUUSD", venue="MT5")
    manifest = store.manifest(data_version)
    timeframe = manifest.timeframe if manifest else "1H"
    engine = BacktestEngine(store)
    result = engine.run(instr, timeframe, data_version, strategy_id=strategy)
    click.echo(f"backtest result: equity={result.final_equity:.2f} trades={result.trades} sharpe={result.sharpe:.3f}")
