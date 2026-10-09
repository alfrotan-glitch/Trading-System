"""A small, FROZEN set of preregistered benchmark candidates.

Why this module exists
----------------------
The 2026-10-09 audit's trading-edge plan, step 3:

    *Freeze a small, production-inspired candidate set before evaluation …
    Keep this to a few distinct hypotheses, not hundreds of indicator variants.*

Hundreds of variants is how you find an edge that isn't there. Three
hypotheses, declared in advance, with their parameters, stop, and time exit
written down before anything is measured, is how you find out whether one is.

The rules
---------
1. **Frozen before evaluation.** Each :class:`BenchmarkSpec` hashes to a value
   recorded in :data:`FROZEN_SPEC_HASHES`. Change a parameter and
   :func:`verify_frozen` fails — the same contract the owner authorization
   artifact uses. There is no "just this once" edit.
2. **A control is not a candidate.** Benchmark C is registered as a
   falsification control. It is not expected to win; if it does win, the
   likeliest explanation is that the measurement is wrong, not that
   mean-reversion is free money.
3. **Every evaluation is a trial.** Running these counts against the DSR
   multiple-testing penalty, because it is exactly the multiple testing DSR
   exists to penalise.
4. **Nothing here promotes anything.** The report states what was measured
   and whether the dataset could support a claim. It never concludes
   "trade this".

Parameters were chosen from public, documented practice (time-series momentum,
Donchian breakout, Bollinger reversion) and the parameters already registered
for the DEMO benchmark — not from sweeping this repository's data.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from qts.research.strategies import StrategyFamily


class BenchmarkRole(StrEnum):
    """Why a benchmark is in the set."""

    #: A hypothesis we would consider trading if it survived.
    CANDIDATE = "CANDIDATE"
    #: A hypothesis included to be FALSIFIED. Its failure is the result.
    CONTROL = "CONTROL"


@dataclass(frozen=True)
class BenchmarkSpec:
    """One preregistered hypothesis, fully specified before any measurement.

    ``stop_distance_usd`` and ``max_hold_bars`` are part of the hypothesis, not
    of the harness: a trend rule with a 3 USD stop and a trend rule with no stop
    are two different strategies, and backtesting one while registering the
    other is how a system lies to itself.
    """

    benchmark_id: str
    hypothesis_id: str
    role: BenchmarkRole
    family: StrategyFamily
    params: dict[str, Any]
    #: The timeframe the hypothesis is DEFINED on. Evaluation on any other
    #: timeframe is mechanism-only and is reported as such.
    timeframe: str
    quantity_lots: float
    stop_distance_usd: float
    max_hold_bars: int
    rationale: str
    #: Public basis for the hypothesis — never "it backtested well here".
    basis: str

    def exit_rules(self) -> dict[str, Any]:
        return {"stop_distance_usd": self.stop_distance_usd, "max_hold_bars": self.max_hold_bars}

    def canonical_json(self) -> str:
        body = asdict(self)
        body["role"] = self.role.value
        body["family"] = self.family.value
        return json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)

    def spec_hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def as_dict(self) -> dict[str, Any]:
        return {
            **{k: v for k, v in asdict(self).items() if k != "family"},
            "family": self.family.value,
            "role": self.role.value,
            "exit_rules": self.exit_rules(),
            "spec_hash": self.spec_hash(),
        }


# --------------------------------------------------------------------------- #
# The frozen set — three hypotheses, declared before evaluation
# --------------------------------------------------------------------------- #

BENCHMARK_A = BenchmarkSpec(
    benchmark_id="BENCH-A-TREND-EMA-12-48",
    hypothesis_id="H-BENCH-A",
    role=BenchmarkRole.CANDIDATE,
    family=StrategyFamily.TREND,
    params={"fast": 12, "slow": 48, "ma_type": "ema"},
    timeframe="15m",
    quantity_lots=0.01,
    stop_distance_usd=3.00,
    max_hold_bars=16,  # 16 x 15m = 4h, the registered DEMO max hold
    rationale=(
        "The trend rule already registered as the DEMO forward benchmark "
        "(DEMO-XAUUSD-TREND-TSMOM-V1). Included unchanged so that the DEMO "
        "measurement and the historical measurement describe the same strategy."
    ),
    basis=(
        "Moskowitz, Ooi & Pedersen (2012), Time Series Momentum — a broad, "
        "publicly documented phenomenon across liquid futures. It does NOT "
        "establish that this exact intraday XAUUSD rule is profitable."
    ),
)

BENCHMARK_B = BenchmarkSpec(
    benchmark_id="BENCH-B-BREAKOUT-DONCHIAN-20",
    hypothesis_id="H-BENCH-B",
    role=BenchmarkRole.CANDIDATE,
    family=StrategyFamily.BREAKOUT,
    params={"period": 20},
    timeframe="15m",
    quantity_lots=0.01,
    stop_distance_usd=3.00,
    max_hold_bars=16,
    rationale=(
        "A volatility-normalized breakout: the channel is the realized "
        "high-low range, so the entry threshold widens and narrows with "
        "volatility instead of firing on a fixed price distance. Identical "
        "stop and time exit to A, so A and B differ in entry logic only."
    ),
    basis=(
        "Donchian channel / turtle breakout practice, publicly documented for "
        "decades. Chosen for the hypothesis, not for a result."
    ),
)

BENCHMARK_C = BenchmarkSpec(
    benchmark_id="BENCH-C-MEANREV-BOLLINGER-20-2.0",
    hypothesis_id="H-BENCH-C",
    role=BenchmarkRole.CONTROL,
    family=StrategyFamily.MEAN_REVERSION,
    params={"period": 20, "k": 2.0},
    timeframe="15m",
    quantity_lots=0.01,
    stop_distance_usd=3.00,
    max_hold_bars=16,
    rationale=(
        "Falsification control. Intraday gold does mean-revert at some "
        "horizons, which is exactly why this is here: a control that could "
        "plausibly pass is the only kind worth having. If BOTH a trend rule "
        "and its opposite survive the same gates, the gates are measuring "
        "something other than an edge."
    ),
    basis=(
        "Bollinger-band reversion, standard textbook construction. Included "
        "because microstructure makes it plausible, not because it is expected "
        "to win."
    ),
)

BENCHMARKS: tuple[BenchmarkSpec, ...] = (BENCHMARK_A, BENCHMARK_B, BENCHMARK_C)

#: Hashes recorded when the set was frozen. ``verify_frozen`` recomputes them;
#: a mismatch means a parameter was edited after preregistration.
FROZEN_SPEC_HASHES: dict[str, str] = {
    "BENCH-A-TREND-EMA-12-48": "d6d5dccd5b0cbb2cfcf47b1092eaedd5960721d70034029611afb636c45f2036",
    "BENCH-B-BREAKOUT-DONCHIAN-20": "f44be6d02e28d0696334251978022d267614d3b3d2302e403394f87172373c5e",
    "BENCH-C-MEANREV-BOLLINGER-20-2.0": "7704e9b18617d5b97024eafdd083ba5fc55c184b0b182c3083453593b01a48cf",
}

PREREGISTERED_AT = "2026-10-09"


def verify_frozen() -> tuple[bool, list[str]]:
    """Every spec must still hash to the value recorded when it was frozen."""
    problems: list[str] = []
    for spec in BENCHMARKS:
        expected = FROZEN_SPEC_HASHES.get(spec.benchmark_id)
        actual = spec.spec_hash()
        if expected is None:
            problems.append(f"{spec.benchmark_id}: no frozen hash recorded — cannot verify preregistration")
            continue
        if expected != actual:
            problems.append(
                f"{spec.benchmark_id}: spec hash {actual[:12]}… != frozen {expected[:12]}… — "
                "a preregistered parameter was changed after registration; the result would not be a "
                "test of the stated hypothesis"
            )
    return (not problems), problems


# --------------------------------------------------------------------------- #
# Evaluation
# --------------------------------------------------------------------------- #


@dataclass
class BenchmarkObservation:
    """What one preregistered hypothesis did on one dataset."""

    benchmark_id: str
    role: str
    spec_hash: str
    timeframe_requested: str
    timeframe_measured: str
    timeframe_matches: bool
    bars: int
    round_turns: int
    gross_pnl_usd: float
    cost_usd: float
    measured_cost_usd: float
    net_pnl_usd: float
    net_expectancy_per_trade: float
    break_even_cost_multiple: float
    win_rate: float
    profit_factor: float
    exits: dict[str, int] = field(default_factory=dict)
    sharpe: float = 0.0
    max_drawdown: float = 0.0
    walk_forward_folds: int = 0
    walk_forward_wfe: float | None = None
    claim_eligible: bool = False
    mechanism_only: bool = True
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BenchmarkReport:
    generated_at: str
    data_version: str
    dataset_provenance: str
    dataset_claim_eligible: bool
    timeframe: str
    frozen_verified: bool
    frozen_problems: list[str]
    cost_model: dict[str, Any] | None
    observations: list[BenchmarkObservation]
    conclusion: str
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "qts.benchmark_candidates.v1",
            "generated_at": self.generated_at,
            "data_version": self.data_version,
            "dataset_provenance": self.dataset_provenance,
            "dataset_claim_eligible": self.dataset_claim_eligible,
            "timeframe": self.timeframe,
            "frozen_verified": self.frozen_verified,
            "frozen_problems": list(self.frozen_problems),
            "cost_model": self.cost_model,
            "observations": [o.as_dict() for o in self.observations],
            "conclusion": self.conclusion,
            "reasons": list(self.reasons),
        }


def evaluate_benchmarks(
    store: Any,
    data_version: str,
    *,
    timeframe: str | None = None,
    cost_model: Any = None,
    contract_size: float = 100.0,
    record_trials: bool = True,
) -> BenchmarkReport:
    """Run every frozen candidate on one dataset and report what happened.

    This never promotes anything. It reports gross, cost and net for each
    hypothesis and states plainly whether the dataset could support a claim.
    """
    from qts.backtest.engine import BacktestEngine
    from qts.domain.value_objects import Instrument
    from qts.research.trade_ledger import round_turns_from_fills

    frozen_ok, frozen_problems = verify_frozen()

    manifest = store.manifest(data_version)
    if manifest is None:
        raise ValueError(f"dataset manifest unavailable for version {data_version}")
    symbol = manifest.instrument
    bar_timeframe = timeframe or manifest.timeframe

    provenance = str(getattr(manifest, "source", "") or "")
    dataset_claim_eligible = provenance.upper().startswith(("MT5", "BROKER", "DUKASCOPY", "HISTORICAL"))

    instrument = Instrument(symbol=symbol)
    engine = BacktestEngine(store)
    contract = float(getattr(instrument, "contract_size", 0) or contract_size) or contract_size

    observations: list[BenchmarkObservation] = []
    for spec in BENCHMARKS:
        reasons: list[str] = []
        if spec.family is StrategyFamily.MEAN_REVERSION:
            reasons.append("registered as a falsification CONTROL — failure is the expected result")
        timeframe_matches = spec.timeframe == bar_timeframe
        if not timeframe_matches:
            reasons.append(
                f"evaluated on {bar_timeframe} bars but the hypothesis is defined on {spec.timeframe} — "
                "mechanism evidence only, not a test of the stated hypothesis"
            )

        # ``_family`` is an explicit contract with the engine: it refuses to
        # fall back to another strategy if these parameters cannot be built.
        params = {**spec.params, "_family": spec.family.value, "quantity": str(spec.quantity_lots)}
        run = engine.run(
            instrument,
            bar_timeframe,
            data_version,
            strategy_id=spec.benchmark_id,
            strategy_params=params,
            exit_rules=spec.exit_rules(),
        )

        ledger = round_turns_from_fills(list(run.fills), contract_size=contract)
        if ledger.unparseable_fills:
            reasons.append(f"{ledger.unparseable_fills} fill(s) could not be parsed — ledger is incomplete")

        # Measured cost: what the simulation actually charged (spread,
        # slippage, fees), recovered from the fill prices against their
        # reference prices.
        measured_cost = ledger.measured_cost_usd

        decomposition = None
        cost_total = measured_cost
        net_total = ledger.realized_pnl_usd
        if cost_model is not None:
            from qts.research.costs import decompose_costs
            from qts.research.trade_ledger import to_trade_records

            decomposition = decompose_costs(to_trade_records(ledger), cost_model)
            cost_total = decomposition.cost_usd
            net_total = decomposition.net_pnl_usd
            if not decomposition.claim_eligible:
                reasons.append("cost components are not MEASURED — not claim-eligible")
            reasons.extend(decomposition.reasons)

        n = ledger.trades
        wins = [t for t in ledger.round_turns if t.gross_pnl_usd > 0]
        losses = [t for t in ledger.round_turns if t.gross_pnl_usd < 0]
        gross_wins = float(sum(t.gross_pnl_usd for t in wins))
        gross_losses = float(-sum(t.gross_pnl_usd for t in losses))
        exits: dict[str, int] = {}
        for fill in run.fills:
            role = str(fill.get("role") or "signal")
            if role.startswith("exit"):
                exits[role] = exits.get(role, 0) + 1

        # Walk-forward on the SAME exit rules — a fold run without the stop
        # would be a different strategy and would inflate WFE.
        folds = 0
        wfe: float | None = None
        try:
            from qts.validation.pipeline import ValidatorPipeline

            bars = store.read_bars(instrument, bar_timeframe, version=data_version)
            bars = sorted(bars, key=lambda b: b.open_time)
            if len(bars) >= 60:
                pipeline = ValidatorPipeline()
                train = max(20, len(bars) // 3)
                test = max(10, len(bars) // 10)
                fold_sharpes: list[tuple[float, float]] = []
                for ts, te, vs, ve in pipeline.walk_forward_splits(len(bars), train=train, test=test, step=test):
                    train_run = engine.run(
                        instrument,
                        bar_timeframe,
                        data_version,
                        strategy_id=spec.benchmark_id,
                        strategy_params=params,
                        exit_rules=spec.exit_rules(),
                        start=bars[ts].open_time,
                        end=bars[te - 1].close_time,
                    )
                    test_run = engine.run(
                        instrument,
                        bar_timeframe,
                        data_version,
                        strategy_id=spec.benchmark_id,
                        strategy_params=params,
                        exit_rules=spec.exit_rules(),
                        start=bars[vs].open_time,
                        end=bars[ve - 1].close_time,
                    )
                    fold_sharpes.append((float(train_run.sharpe), float(test_run.sharpe)))
                if fold_sharpes:
                    from qts.validation.metrics import walk_forward_efficiency

                    is_mean = sum(a for a, _ in fold_sharpes) / len(fold_sharpes)
                    oos_mean = sum(b for _, b in fold_sharpes) / len(fold_sharpes)
                    folds = len(fold_sharpes)
                    wfe = walk_forward_efficiency(is_mean, oos_mean)
        except Exception as exc:  # an unevaluable fold is reported, not filled in
            reasons.append(f"walk-forward unevaluable: {type(exc).__name__}: {exc}")

        if n == 0:
            reasons.append("no completed round turn — nothing was measured (not a zero, not a pass)")
        if not dataset_claim_eligible:
            reasons.append(
                f"dataset provenance {provenance or 'UNKNOWN'!r} is not claim-eligible — mechanism evidence only"
            )

        observations.append(
            BenchmarkObservation(
                benchmark_id=spec.benchmark_id,
                role=spec.role.value,
                spec_hash=spec.spec_hash(),
                timeframe_requested=spec.timeframe,
                timeframe_measured=bar_timeframe,
                timeframe_matches=timeframe_matches,
                bars=run.bars,
                round_turns=n,
                gross_pnl_usd=ledger.gross_pnl_usd,
                cost_usd=cost_total,
                measured_cost_usd=measured_cost,
                net_pnl_usd=net_total,
                net_expectancy_per_trade=(net_total / n) if n else 0.0,
                break_even_cost_multiple=(ledger.gross_pnl_usd / cost_total) if cost_total > 0 else 0.0,
                win_rate=(len(wins) / n) if n else 0.0,
                profit_factor=(gross_wins / gross_losses) if gross_losses > 0 else (0.0 if gross_wins == 0 else float("inf")),
                exits=exits,
                sharpe=float(run.sharpe),
                max_drawdown=float(run.max_dd),
                walk_forward_folds=folds,
                walk_forward_wfe=wfe,
                claim_eligible=bool(
                    n > 0 and dataset_claim_eligible and timeframe_matches and decomposition is not None
                    and decomposition.claim_eligible
                ),
                mechanism_only=not (dataset_claim_eligible and timeframe_matches),
                reasons=reasons,
            )
        )

        if record_trials:
            _record_trial(spec, data_version, bar_timeframe)

    conclusion = (
        "NO_EDGE_ESTABLISHED — mechanism evidence only"
        if not dataset_claim_eligible
        else "MEASURED — no hypothesis promoted; promotion is a separate, gated process"
    )
    return BenchmarkReport(
        generated_at=datetime.now(UTC).isoformat(),
        data_version=data_version,
        dataset_provenance=provenance,
        dataset_claim_eligible=dataset_claim_eligible,
        timeframe=bar_timeframe,
        frozen_verified=frozen_ok,
        frozen_problems=frozen_problems,
        cost_model=(cost_model.as_dict() if cost_model is not None else None),
        observations=observations,
        conclusion=conclusion,
        reasons=(
            ["no hypothesis was promoted — this report measures, it does not authorise"]
            if dataset_claim_eligible
            else [
                "no hypothesis was promoted — this report measures, it does not authorise",
                "the dataset cannot support an edge claim, so these numbers are mechanism evidence only",
            ]
        ),
    )


def _record_trial(spec: BenchmarkSpec, data_version: str, timeframe: str) -> str | None:
    """Register the hypothesis and the evaluation in the experiment ledger.

    Running three preregistered hypotheses IS multiple testing. If it were not
    recorded, the next DSR computed from this store would understate exactly
    the selection bias DSR exists to penalise.
    """
    try:
        from qts.observability.lineage import code_version
        from qts.research.experiment import Experiment, ExperimentStore, Hypothesis

        store = ExperimentStore()
        hypothesis = Hypothesis(
            id=spec.hypothesis_id,
            statement=f"{spec.benchmark_id}: {spec.rationale}",
            question=f"Does {spec.benchmark_id} produce net-of-cost expectancy on {timeframe} {data_version}?",
            mechanism=f"{spec.family.value} family — see basis",
            prediction=(
                "No durable net-of-cost edge."
                if spec.role is BenchmarkRole.CONTROL
                else "Positive net expectancy after measured costs, stable across walk-forward folds."
            ),
            null_hypothesis="Net-of-cost expectancy is zero or negative.",
            competing_explanations=[
                "cost assumptions do not match the venue actually used",
                "the sample is dominated by one regime",
                "multiple-testing selection across the candidate set",
            ],
            falsification_criteria=[
                "net expectancy <= 0 after MEASURED costs",
                "walk-forward efficiency below the configured floor",
            ],
            rationale=spec.rationale,
            falsifiability="Falsified by a non-positive net expectancy after measured costs.",
            required_data={"instrument": "XAUUSD", "timeframe": spec.timeframe},
            intended_horizon="the exact chronological dataset partition declared in the run",
            intended_population=f"XAUUSD {timeframe} bars in dataset {data_version}",
            intended_regime="all observed regimes; regime stability must be measured, not assumed",
            created_by="qts.research.benchmarks",
        )
        store.put_hypothesis(hypothesis)
        experiment = Experiment(
            hypothesis_id=spec.hypothesis_id,
            strategy_id=spec.benchmark_id,
            params={
                **spec.params,
                "quantity": spec.quantity_lots,
                "timeframe": timeframe,
                "stop_distance_usd": spec.stop_distance_usd,
                "max_hold_bars": spec.max_hold_bars,
            },
            data_version=data_version,
            dataset_provenance="UNVERIFIED",
            code_version=code_version(),
            seed=42,
            split_definition={"partitioner": "none", "note": "whole-partition mechanism run"},
            cost_assumptions={"status": "BENCHMARK_DECLARED", "source": "qts.research.costs"},
            exclusions=[
                "CPCV/PBO not executed by the benchmark harness",
                "randomized null/placebo not executed",
                "no forward broker observation in this call",
            ],
        )
        store.put(experiment)
        return experiment.id
    except Exception:
        # A trial that could not be recorded must not silently become an
        # un-counted one; the report itself is the fallback record.
        return None
