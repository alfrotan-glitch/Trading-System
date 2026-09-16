# 4 — Research Lifecycle & Strategy Lifecycle

## 4.1 Research Lifecycle (Scientific)

```
IDEA
  │  (free-form, AI or human, logged)
  ▼
HYPOTHESIS  ← must be falsifiable, with rationale & invalidation criteria
  │  e.g. "XAUUSD 1H momentum persists 2-4h after London open, conditioned on ATR expansion"
  ▼
EXPERIMENT  ← code_version + data_version + params + seed + manifest_hash pinned
  │
  ├─► RESULT  (single backtest, metrics, equity curve, trades)
  │
  ▼
VALIDATED RESULT  ← passes validation stack (walk-forward, stress, etc.)
  │
  ▼
CANDIDATE STRATEGY  ← encapsulated as StrategyDef + RiskLimits + docs
  │
  ▼
PAPER STRATEGY  ← paper trading on live feed, no capital
  │
  ▼
LIVE-ELIGIBLE  ← all gates + manual approval + kill-switch armed
```

Distinguishing each stage is mandatory. AI output is at most IDEA; promotion requires hypothesis + experiment.

### Gates

| Transition | Required Evidence |
|------------|-------------------|
| IDEA → HYPOTHESIS | Written statement + falsifiability + base rate |
| HYPOTHESIS → EXPERIMENT | Data version pinned, experiment code review, leakage checklist |
| EXPERIMENT → RESULT | Deterministic run, manifest_hash recorded |
| RESULT → VALIDATED RESULT | `ValidationReport` with PASS on all required validators |
| VALIDATED → CANDIDATE | Adversarial review PASS, parameter sensitivity stable, cost stress PASS |
| CANDIDATE → PAPER | Risk limits defined, paper adapter smoke test |
| PAPER → LIVE-ELIGIBLE | Paper duration ≥ N weeks, live/paper divergence < threshold, manual sign-off |

Failing any gate routes to `REJECTED` or back to `RESEARCH` with reason stored in `ExperimentStore`.

## 4.2 Strategy Lifecycle (Operational)

```
RESEARCH ──► VALIDATING ──► PAPER ──► SHADOW ──► LIVE_CANDIDATE ──► LIVE
                │             │         │              │              │
                ▼             ▼         ▼              ▼              ▼
            REJECTED      SUSPENDED  SUSPENDED    SUSPENDED      SUSPENDED
                │             │         │              │              │
                └─────────────┴─────────┴──────────────┴──────────────► RETIRED
```

- **RESEARCH:** Code only, no orders.
- **VALIDATING:** Validation pipeline running, no live orders.
- **PAPER:** Live data, paper adapter, orders simulated with live spread.
- **SHADOW:** Live adapter in read-only + paper orders mirrored; measures live/paper divergence (slippage, spread, latency).
- **LIVE_CANDIDATE:** Ready but still paper; requires explicit `--confirm live` + 2-person approval (or single in solo mode with audit).
- **LIVE:** Capital at risk, risk engine armed, reconciler active, kill-switch monitored.
- **SUSPENDED:** Trading halted, positions may remain, reconcile-only. Triggered by drawdown, drift, manual, kill-switch.
- **RETIRED:** Strategy code archived, no further promotion.

### State Machine Rules

- Only forward promotion via gates; any state can go to SUSPENDED/RETIRED.
- `LIVE` requires `LIVE_CANDIDATE` + `ValidationReport.passed == True` + `RiskLimits.approved == True` + `paper_duration_ok`.
- Downgrade from LIVE requires reason + audit.
- `REJECTED` is terminal for that StrategyDef version; new version is new entity.

### Capital Exposure

Live entry needs:

1. `ValidationReport` (commit hash, data version, DSR/PSR/PBO, walk-forward, stresses).
2. `RiskLimits` approved and tested.
3. `Reconciler` healthy checks passing.
4. Explicit env `live` + `--confirm` + secret scope `live/*`.
5. Kill-switch reachable.

Missing any → fail closed, process exits non-zero.

## 4.3 Experiment Memory

Stored in `ExperimentStore` (SQLite):

- `hypotheses(id, statement, rationale, created_by, created_at, status)`
- `experiments(id, hypothesis_id, code_version, data_version, params, seed, manifest_hash, status)`
- `runs(id, experiment_id, metrics, equity_curve, trades, validation_report_id)`
- `rejections(id, experiment_id, reason, adversarial_findings)`
- `lineage(parent_experiment_id, child_experiment_id, relation)`

Query: “have we tried this before?” → search hypotheses by embedding + lineage graph, not just keyword.

## 4.4 Example

Hypothesis `H-042`: "XAUUSD breaks London high with ATR filter outperforms random entry after cost."

Experiment `E-042a`: SMA(20) breakout, ATR(14) > median, 1H, 2020-2023 train, 2024 holdout, cost 3bps + spread.

Validation: walk-forward 6×12m/3m, perturbation ±10%, slippage 2×, spread 2× → WFE 0.6, DSR p=0.04, PBO 0.35 → PASS.

Candidate `S-042 v1` → PAPER 8 weeks, Sharpe live/paper delta 0.2 → SHADOW 4 weeks → approved → LIVE_CANDIDATE → manual confirm → LIVE.

If live drawdown > 2× expected → SUSPENDED, hypothesis re-opened.

## 4.5 NO_TRADE Discipline

Strategies return `[]` (no signal) when: confidence low, regime uncertain, data quality bad, risk veto, or validation says weak. The platform treats empty signal set as success (capital preserved), not failure.
