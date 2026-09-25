"""QTS CLI — backtest, validation, health, and run."""

from __future__ import annotations

import contextlib
import sys
from datetime import UTC
from pathlib import Path
from typing import Any

import click
import numpy as np

from qts.backtest.engine import BacktestEngine
from qts.config.settings import load_settings
from qts.data.store import SqliteParquetDataStore
from qts.domain.value_objects import Instrument
from qts.research.agent import AdversarialAgent
from qts.research.experiment import ExperimentStore
from qts.validation.pipeline import ValidatorPipeline


@click.command("backtest")
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


@click.command("validate")
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



@click.command("health")
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



@click.command("run")
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


