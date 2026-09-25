"""Automated Research Campaigns — bounded, logged, no hidden experiments, DSR accounting, never auto-promote on high return alone."""

from __future__ import annotations

import contextlib
import itertools
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from qts.db import connect as db_connect
from qts.domain.value_objects import Instrument, uuid7
from qts.research.experiment import (
    ConclusionCode,
    Experiment,
    ExperimentStore,
    Hypothesis,
)
from qts.research.readiness import ResearchDataRequirements, assess_dataset


class CampaignConfig(BaseModel):
    name: str
    symbol: str = "XAUUSD"
    timeframe: str = "1H"
    data_version: str
    family: str  # trend, breakout, etc.
    param_space: dict[str, list[Any]] = Field(default_factory=dict)
    max_trials: int = 20
    max_runtime_s: float = 300.0
    max_param_combinations: int = 100
    seed: int = 42
    hypothesis_template: str = "Test {family} with {params}"
    # A campaign may inspect a synthetic fixture for mechanism validation, but
    # it must not report a meaningful real-market conclusion from it.
    minimum_bars: int = 5_000
    minimum_span_days: float = 180.0
    require_claim_eligible_data: bool = True


class CampaignResult(BaseModel):
    campaign_id: str
    trial_id: str
    strategy_id: str
    params: dict[str, Any]
    passed: bool
    sharpe_oos: float | None = None
    sharpe_is: float | None = None
    reasons: list[str] = Field(default_factory=list)
    conclusion: str = ConclusionCode.REJECTED.value
    data_readiness: dict[str, Any] = Field(default_factory=dict)
    experiment_id: str | None = None
    configuration_hash: str | None = None
    dataset_provenance: str | None = None
    dataset_manifest_hash: str | None = None
    code_version: str | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ResearchCampaignStore:
    def __init__(self, db_path: Path | str = "data/sqlite/qts.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _init(self) -> None:
        with db_connect(self.db_path) as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS research_campaigns (
                    id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS campaign_trials (
                    id TEXT PRIMARY KEY,
                    campaign_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(campaign_id) REFERENCES research_campaigns(id)
                )
            """)
            con.commit()

    def create_campaign(self, config: CampaignConfig) -> str:
        cid = f"C-{uuid7()[:8]}"
        payload = config.model_dump_json()
        now = datetime.now(UTC).isoformat()
        with db_connect(self.db_path) as con:
            con.execute("INSERT INTO research_campaigns VALUES (?,?,?,?)", (cid, payload, now, "CREATED"))
            con.commit()
        return cid

    def get_campaign(self, campaign_id: str) -> tuple[CampaignConfig, str] | None:
        with db_connect(self.db_path) as con:
            row = con.execute("SELECT payload, status FROM research_campaigns WHERE id=?", (campaign_id,)).fetchone()
            if not row:
                return None
            return CampaignConfig.model_validate_json(row[0]), row[1]

    def update_status(self, campaign_id: str, status: str) -> None:
        with db_connect(self.db_path) as con:
            con.execute("UPDATE research_campaigns SET status=? WHERE id=?", (status, campaign_id))
            con.commit()

    def put_trial(self, campaign_id: str, result: CampaignResult) -> None:
        payload = result.model_dump_json()
        with db_connect(self.db_path) as con:
            existing = con.execute("SELECT campaign_id, payload FROM campaign_trials WHERE id=?", (result.trial_id,)).fetchone()
            if existing is not None:
                if existing[0] != campaign_id or existing[1] != payload:
                    raise ValueError(f"campaign trial {result.trial_id} already exists with different evidence")
                return
            con.execute(
                "INSERT INTO campaign_trials VALUES (?,?,?,?)",
                (result.trial_id, campaign_id, payload, result.created_at.isoformat()),
            )
            con.commit()

    def list_trials(self, campaign_id: str) -> list[CampaignResult]:
        with db_connect(self.db_path) as con:
            rows = con.execute(
                "SELECT payload FROM campaign_trials WHERE campaign_id=? ORDER BY created_at", (campaign_id,)
            ).fetchall()
            return [CampaignResult.model_validate_json(r[0]) for r in rows]

    def list_campaigns(self) -> list[tuple[str, CampaignConfig, str]]:
        with db_connect(self.db_path) as con:
            rows = con.execute("SELECT id, payload, status FROM research_campaigns ORDER BY created_at DESC").fetchall()
            return [(r[0], CampaignConfig.model_validate_json(r[1]), r[2]) for r in rows]

    def count_trials(self, campaign_id: str) -> int:
        with db_connect(self.db_path) as con:
            row = con.execute("SELECT COUNT(*) FROM campaign_trials WHERE campaign_id=?", (campaign_id,)).fetchone()
            return row[0] if row else 0

    def close(self) -> None:
        with contextlib.suppress(Exception):
            # File-backed connections are opened/closed per operation via qts.db.connect,
            # so no persistent handle exists here. We must NOT re-open the database file
            # in close()/__del__: that recreates deleted files and re-acquires Windows
            # file locks during GC/shutdown (root cause of WinError 32 on cleanup).
            # close any memory connection if present
            mem = getattr(self, "_memory_con", None)
            if mem is not None:
                with contextlib.suppress(Exception):
                    mem.commit()
                    mem.close()
                self._memory_con = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


def _param_combinations(param_space: dict[str, list[Any]], max_combinations: int) -> list[dict[str, Any]]:
    if not param_space:
        return [{}]
    keys = list(param_space.keys())
    values = [param_space[k] for k in keys]
    combos = list(itertools.product(*values))
    # limit
    combos = combos[:max_combinations]
    return [dict(zip(keys, combo, strict=True)) for combo in combos]


def run_campaign(
    config: CampaignConfig,
    store_path: Path | str = "data/sqlite/qts.db",
    registry_path: Path | str = "data/sqlite/qts.db",
) -> dict[str, Any]:
    """Launch bounded research campaign.

    - Assigns trial IDs
    - Runs experiments via BacktestEngine + ValidatorPipeline (via edge orchestrator)
    - Stores results, rejects invalid
    - Applies DSR accounting (trial count)
    - Ranks for inspection, never auto-promotes solely on high return
    """
    import numpy as np

    from qts.backtest.engine import BacktestEngine
    from qts.data.store import SqliteParquetDataStore
    from qts.observability.lineage import code_version
    from qts.research.registry import StrategyRecord, StrategyRegistry
    from qts.research.strategies import BOUNDED_PARAM_SPACE, StrategyFamily, describe_features
    from qts.validation.pipeline import ValidatorPipeline

    campaign_store = ResearchCampaignStore(db_path=store_path)
    exp_store = ExperimentStore(db_path=store_path)
    registry = StrategyRegistry(db_path=registry_path)

    # Validate family
    try:
        family_enum = StrategyFamily(config.family)
    except ValueError as e:
        raise ValueError(f"unknown family {config.family}, must be one of {[f.value for f in StrategyFamily]}") from e

    # Derive param_space if not provided: use bounded defaults
    param_space = config.param_space or BOUNDED_PARAM_SPACE.get(family_enum, {})
    combos = _param_combinations(param_space, config.max_param_combinations)
    # Enforce max_trials
    combos = combos[: config.max_trials]

    cid = campaign_store.create_campaign(config)
    campaign_store.update_status(cid, "RUNNING")
    start = time.time()
    results: list[CampaignResult] = []
    passed = 0
    failed = 0

    # Resolve the exact immutable dataset once, before any trial runs.  A
    # campaign may still record blocked trials for a synthetic fixture (that
    # preserves the search ledger), but it must not turn those numbers into a
    # real-market claim.
    research_data_store = SqliteParquetDataStore()
    readiness = assess_dataset(
        research_data_store,
        config.data_version,
        requirements=ResearchDataRequirements(
            min_bars=config.minimum_bars,
            min_span_days=config.minimum_span_days,
        ),
    )
    claim_blocked = config.require_claim_eligible_data and not readiness.ready_for_claims

    for idx, params in enumerate(combos):
        # Stop conditions
        elapsed = time.time() - start
        if elapsed > config.max_runtime_s:
            # log stop
            break
        if len(results) >= config.max_trials:
            break

        # IDs are unique per campaign, while the trial index remains stable
        # for reproducibility and audit comparison across reruns.
        trial_id = f"T-{cid[2:]}-{idx:04d}"
        strategy_id = f"{config.family}_{cid[2:]}_{idx:04d}"
        if not config.data_version.strip():
            reasons = ["NO_DATASET_VERSION: campaign requires an explicit immutable data_version"]
            blocked_result = CampaignResult(
                campaign_id=cid,
                trial_id=trial_id,
                strategy_id=strategy_id,
                params=params,
                passed=False,
                reasons=reasons,
                conclusion=ConclusionCode.BLOCKED_INSUFFICIENT_DATA.value,
                data_readiness=readiness.as_dict(),
                evidence={"status": "BLOCKED", "reason": "no dataset version was supplied"},
            )
            campaign_store.put_trial(cid, blocked_result)
            results.append(blocked_result)
            failed += 1
            continue
        statement = config.hypothesis_template.format(family=config.family, params=params)
        # Create a fully described hypothesis; a legacy one-line statement is
        # not enough to justify a meaningful experiment.
        hyp = Hypothesis(
            statement=statement,
            question=f"Does {config.family} produce positive net expectancy for {config.symbol} {config.timeframe} after costs?",
            mechanism=config.family,
            prediction="The pre-registered signal will outperform its null and remain positive after the declared cost sweep.",
            null_hypothesis="The signal has no incremental predictive value after costs and timing controls.",
            competing_explanations=[
                "selection or trial-count bias",
                "look-ahead or timestamp leakage",
                "single-regime or single-instrument artifact",
            ],
            falsification_criteria=[
                "fails chronological OOS replication",
                "fails declared cost or parameter-perturbation stress",
                "is not separated from null/placebo controls",
            ],
            rationale=f"Campaign {cid} trial {idx} family {config.family}",
            falsifiability="fails if any required scientific gate fails",
            required_data={"symbol": config.symbol, "timeframe": config.timeframe, "version": config.data_version},
            intended_horizon=config.timeframe,
            intended_population=config.symbol,
            intended_regime="all declared regimes; no regime may be silently excluded",
            created_by="campaign",
        )
        exp_store.put_hypothesis(hyp)
        dataset_manifest = research_data_store.manifest(config.data_version)
        exp = Experiment(
            hypothesis_id=hyp.id,
            strategy_id=strategy_id,
            params=params,
            data_version=config.data_version,
            dataset_provenance=readiness.data_class,
            dataset_manifest_hash=dataset_manifest.checksum if dataset_manifest else "",
            seed=config.seed + idx,
            code_version=code_version(),
            split_definition={"kind": "chronological", "locked_test_access": False},
            cost_assumptions={
                "status": "MODEL_ASSUMPTION_NOT_MEASUREMENT",
                "spread_bps": None,
                "slippage_bps": "UNAVAILABLE",
                "latency": "UNAVAILABLE",
            },
            exclusions=[],
        )
        exp_store.put(exp)

        if claim_blocked:
            reasons = list(readiness.reasons) or ["research data is not claim-eligible"]
            blocked_result = CampaignResult(
                campaign_id=cid,
                trial_id=trial_id,
                strategy_id=strategy_id,
                params=params,
                passed=False,
                reasons=reasons,
                conclusion=ConclusionCode.BLOCKED_INSUFFICIENT_DATA.value,
                data_readiness=readiness.as_dict(),
                experiment_id=exp.id,
                configuration_hash=exp.configuration_hash,
                dataset_provenance=exp.dataset_provenance,
                dataset_manifest_hash=exp.dataset_manifest_hash,
                code_version=exp.code_version,
                evidence={"status": "BLOCKED", "reason": "claim-eligible execution was not attempted"},
            )
            exp_store.complete(
                exp.id,
                results={"data_readiness": readiness.as_dict()},
                conclusion=ConclusionCode.BLOCKED_INSUFFICIENT_DATA,
                failure_reason="; ".join(reasons),
            )
            campaign_store.put_trial(cid, blocked_result)
            results.append(blocked_result)
            failed += 1
            continue

        # Register in registry (durable, documented)
        try:
            features = describe_features(family_enum, params)
        except Exception:
            features = {"family": config.family, "params": params}
        rec = StrategyRecord(
            strategy_id=strategy_id,
            name=f"{config.family} campaign {cid}",
            version="1.0.0",
            hypothesis=hyp.statement,
            market=config.symbol,
            symbol=config.symbol,
            timeframe=config.timeframe,
            data_manifest=config.data_version,
            feature_definition=features,
            parameter_definition=params,
            execution_assumptions={
                "status": "MODEL_ASSUMPTION_NOT_MEASUREMENT",
                "spread_bps": None,
                "slippage": "UNAVAILABLE",
                "latency": "UNAVAILABLE",
                "note": "Backtest matching cost settings are scenario inputs, not broker observations",
            },
            risk_assumptions={"status": "DECLARED_ASSUMPTIONS_NOT_ACCOUNT_STATE"},
            code_revision=code_version(),
            lifecycle_state="RESEARCH",
            family=config.family,
        )
        with contextlib.suppress(Exception):
            # if already exists (unlikely) continue
            registry.register(rec)

        # Run only validations backed by an actual engine result. A missing
        # CPCV/null/placebo/gross-vs-net implementation is passed as missing
        # evidence and must block; it is never replaced with random numbers or
        # a scaled copy of the same equity curve.
        try:
            instr = Instrument(symbol=config.symbol, venue="MT5")
            engine = BacktestEngine(research_data_store)
            result = engine.run(
                instr,
                config.timeframe,
                config.data_version,
                strategy_id=strategy_id,
                strategy_params={**params, "_family": config.family},
                seed=config.seed + idx,
            )
            eq = np.asarray(result.equity_curve, dtype=float)
            if len(eq) < 20:
                raise ValueError("insufficient equity for validation")
            mid = len(eq) // 2
            eq_is = eq[:mid]
            eq_oos = eq[mid:]
            bars = research_data_store.read_bars(instr, config.timeframe, version=config.data_version)
            pipeline = ValidatorPipeline()

            # Real chronological walk-forward folds: each fold is an
            # independent backtest on its own train and test interval.
            train = max(100, len(bars) // 3)
            test = max(20, len(bars) // 10)
            folds: list[dict[str, float]] = []
            for train_start, train_end, test_start, test_end in pipeline.walk_forward_splits(
                len(bars), train=train, test=test, step=test
            ):
                train_result = engine.run(
                    instr,
                    config.timeframe,
                    config.data_version,
                    strategy_id=strategy_id,
                    strategy_params={**params, "_family": config.family},
                    seed=config.seed + idx,
                    start=bars[train_start].open_time,
                    end=bars[train_end - 1].close_time,
                )
                test_result = engine.run(
                    instr,
                    config.timeframe,
                    config.data_version,
                    strategy_id=strategy_id,
                    strategy_params={**params, "_family": config.family},
                    seed=config.seed + idx,
                    start=bars[test_start].open_time,
                    end=bars[test_end - 1].close_time,
                )
                folds.append({"is_sharpe": float(train_result.sharpe), "oos_sharpe": float(test_result.sharpe)})

            # Parameter perturbation is also a real rerun. If no numeric
            # parameter exists, there is no perturbation evidence and the gate
            # will block rather than infer stability.
            perturbed: list[float] = []
            numeric_keys = [k for k, v in params.items() if isinstance(v, (int, float)) and not k.startswith("_")]
            for key in numeric_keys:
                for factor in (0.8, 0.9, 1.1, 1.2):
                    variant = dict(params)
                    variant[key] = type(params[key])(params[key] * factor)
                    variant_result = engine.run(
                        instr,
                        config.timeframe,
                        config.data_version,
                        strategy_id=strategy_id,
                        strategy_params={**variant, "_family": config.family},
                        seed=config.seed + idx,
                    )
                    perturbed.append(float(variant_result.sharpe))

            from qts.validation.edge_validation import validate_edge_survival

            stress = engine.run_stress(
                instr,
                config.timeframe,
                config.data_version,
                strategy_id,
                {**params, "_family": config.family},
                spreads=[1.0, 1.5, 2.0],
            )
            trial_n = exp_store.count_trials()
            edge_res = validate_edge_survival(
                strategy_id,
                config.data_version,
                eq_is,
                eq_oos,
                None,  # gross equity is not measured by this matching model
                eq_oos,
                folds,
                [],  # CPCV is not implemented by this bounded campaign path
                perturbed,
                stress,
                trial_n,
                [],  # no randomized control evidence was executed
                [],  # no placebo evidence was executed
                bars,
                list(np.diff(eq)),
                timeframe=config.timeframe,
            )
            passed_flag = edge_res.passed
            # Economic edge also required
            # Never auto-promote solely because one candidate has high return: we explicitly require all gates, not just sharpe
            # So passed_flag already requires all gates
            # failure reasons come from the edge-survival check map (dict[str, bool]);
            # details is dict[str, str] and never carried a "fail_reasons" list
            reasons = [str(name) for name, ok in edge_res.checks.items() if not ok]
            if not passed_flag:
                conclusion = ConclusionCode.NO_EDGE_FOUND.value
                exp_store.reject(
                    exp.id,
                    reason="; ".join(reasons)[:500] or "scientific gate failure",
                    details={"edge_checks": edge_res.checks, "edge_details": edge_res.details},
                )
                failed += 1
            else:
                # A gate pass is still only a research candidate: this loop has
                # no forward/shadow evidence and never promotes execution.
                conclusion = ConclusionCode.PROMISING_INSUFFICIENT.value
                exp_store.complete(
                    exp.id,
                    results={"edge_checks": edge_res.checks, "edge_details": edge_res.details},
                    conclusion=conclusion,
                )
                passed += 1
            result_obj = CampaignResult(
                campaign_id=cid,
                trial_id=trial_id,
                strategy_id=strategy_id,
                params=params,
                passed=passed_flag,
                sharpe_oos=float(result.sharpe),
                sharpe_is=float(result.sharpe),
                reasons=reasons,
                conclusion=conclusion,
                data_readiness=readiness.as_dict(),
                experiment_id=exp.id,
                configuration_hash=exp.configuration_hash,
                dataset_provenance=exp.dataset_provenance,
                dataset_manifest_hash=exp.dataset_manifest_hash,
                code_version=exp.code_version,
                evidence={"checks": edge_res.checks, "details": edge_res.details},
            )
        except Exception as e:
            result_obj = CampaignResult(
                campaign_id=cid,
                trial_id=trial_id,
                strategy_id=strategy_id,
                params=params,
                passed=False,
                reasons=[str(e)[:300]],
                conclusion=ConclusionCode.REJECTED.value,
                data_readiness=readiness.as_dict(),
                experiment_id=exp.id,
                configuration_hash=exp.configuration_hash,
                dataset_provenance=exp.dataset_provenance,
                dataset_manifest_hash=exp.dataset_manifest_hash,
                code_version=exp.code_version,
                evidence={"status": "FAILED", "reason": str(e)[:300]},
            )
            failed += 1
            exp_store.reject(exp.id, reason=str(e)[:300])

        campaign_store.put_trial(cid, result_obj)
        results.append(result_obj)

    campaign_store.update_status(cid, "COMPLETED")
    # DSR accounting summary
    total_trials = exp_store.count_trials()
    # Rank for inspection (sorted by oos sharpe but never auto-promote)
    ranked = sorted(results, key=lambda r: r.sharpe_oos or -999, reverse=True)
    summary = {
        "campaign_id": cid,
        "config": config.model_dump(),
        "total_trials": len(results),
        "passed": passed,
        "failed": failed,
        "discarded": 0,  # could be counted via rejections
        "trials": [r.model_dump() for r in results],
        "ranked_for_inspection": [r.model_dump() for r in ranked[:5]],
        "dsr_trial_count": total_trials,
        "elapsed_s": time.time() - start,
        "status": "COMPLETED",
        "conclusion": (
            ConclusionCode.BLOCKED_INSUFFICIENT_DATA.value
            if claim_blocked
            else (ConclusionCode.NO_EDGE_FOUND.value if not passed else ConclusionCode.PROMISING_INSUFFICIENT.value)
        ),
        "data_readiness": readiness.as_dict(),
        "notes": "A completed campaign is not a positive result. Claim-ineligible data produces blocked trials; no trial is auto-promoted.",

    }
    return summary
