# Autonomous Quantitative Research Laboratory
Version: 0.1.0 — 2026-09-18

> This document describes the research machinery. Current machine evidence is
> authoritative over historical examples. The registered REAL XAUUSD 15m
> dataset is preserved as frozen lineage for the executed bar-based impulse
> study, whose conclusion is `REGIME_DEPENDENT / BLOCK`; current completeness is
> FAIL under the unchanged 2% gate and the study is not currently claim-eligible.
> The unchanged synthetic fixture remains mechanism-validation-only. See
> [`docs/current_state.md`](current_state.md) and
> [`docs/data_completeness_disposition.md`](data_completeness_disposition.md).

## Mission
Turn the system into DISCOVER→INVENT→TEST→ATTACK→FALSIFY→REFINE→RE-TEST→PROVE while structurally hostile to false discoveries.

## Research Intelligence Layer
`src/qts/research/intelligence.py` — `IntelligenceOrchestrator` inspects data via `SqliteParquetDataStore` and evidence via `edge_validation.json`/`campaigns_summary.json`, identifies weaknesses (PBO, DSR, cost BE, worst regime), generates `ResearchThought` with 8 fields (WHY, mechanism assumed, support/falsify observation, data required, cost conditions, regimes expected/stop), proposes `HypothesisSpec` with falsifiable prediction, designs experiments, runs bounded `run_campaign`, analyzes failures via `ResearchMemory`, mutates via `lineage`, maintains complete lineage in `research_thoughts`/`hypothesis_specs`/`thought_lineage` SQLite.

Every idea has: WHY, mechanism, support, falsify, data, cost, regimes, stop conditions — documented before any trial.

## Market Mechanisms Investigated
The bounded research families cover trend/momentum persistence, mean reversion,
breakout continuation/failure, volatility expansion, regime transitions,
liquidity/spread, session/time-of-day, range compression, directional
imbalance, acceleration/exhaustion, pullbacks, multi-timeframe structure, and
shock persistence. Each mechanism is treated as falsifiable; none is assumed
real. The current campaign artifacts, not this catalogue, define how many
trials actually ran.

## Invented Strategies
Beyond classic indicators: `src/qts/research/invented_strategies.py` (state-machine, event-driven, multi-timeframe, volatility-normalized) + `src/qts/research/strategies.py` 5 families + regime-conditioned wrapper. New complexity → more trials → stronger DSR penalty (honest). `src/qts/research/position_management.py` 6 exit policies (fixed, volatility, trailing, time, breakeven, momentum-decay) — entry+exit joint hypothesis tested OOS.

## Feature Discovery
`src/qts/research/feature_discovery.py`: `FeatureSpec` with definition, source, timestamp semantics, lookback, data dependencies, version, lineage, code_hash. Controlled set 6 features (returns_1, range_5, volatility_20, spread_proxy, session_hour, range_compression) computed at `close_time` using only bars ≤ N, no future/post-trade/normalization leakage, no locked test contamination. `FeatureStore` registers, checks leakage string, tracks lineage.

## Multiple Markets/Timeframes
`src/qts/data/audit.py` and the current evidence cover a REAL XAUUSD 15m
history (26,038 bars, approximately 407 days) plus the unchanged 500-bar
synthetic XAUUSD 1H fixture. Independent markets/timeframes, longer regime
coverage and continuous execution-cost evidence remain incomplete. Expansion is
for uncertainty reduction only, never to seek a favorable result. See
`docs/current_state.md` and `docs/data_source_audit.md`.

## Market Microstructure / Execution-Aware
`src/qts/edge/cost_robustness.py` + `src/qts/backtest/engine.py` next-bar-open execution, spread/slippage/latency stress 1.0/1.5/2.0×, partial fills, price jumps, stop behavior. Every strategy answers "what remains after realistic execution?" — `cost_break_even_bps` must exceed 20bps.

## Statistical Stack
Retains walk-forward, CPCV, PBO, PSR, DSR, perturbation, regime, null/placebo, cost stress. Extensions `src/qts/research/statistical.py`: White Reality Check (bootstrap max, p-value), Hansen SPA (max t-stat), permutation test, minimum backtest length (PSR inversion), drawdown distribution (bootstrap ES), parameter surface stability. Each documented purpose/assumptions/inputs/limitations, reference implementation, unit tests, failure modes.

## Adversarial Research
`src/qts/research/adversary.py` `adversarial_attack` searches leakage, fragility, regime, cost, assumptions, favorable periods, unstable exits, fills, overfitting, false correlation, random equivalence, artifacts. Returns `best_for`/`best_against`, verdict BREAKS/SURVIVES, ensures both sides reported.

## Experiment Economics
`src/qts/research/experiment.py` + `campaign.py` + `memory.py` track trial count, family, param/feature count, search depth, selection stages, dataset/timeframe/symbol counts, manual interventions, re-runs. More search → stronger DSR. No hidden retries, no cherry-picking, no N reset, no deletion, no fresh campaign secret reset — `ExperimentStore.count_trials()` monotonic, `campaign_trials` also logged, `ResearchMemory` prevents rediscovery.

## Research Memory
`src/qts/research/memory.py` `ResearchMemory` durable `research_memory` table stores hypothesis_id, family, mechanism, params, failed_stage, reason, regime_failed, param_range_unstable, feature_useless, redundant. `has_failed_similar` prevents rediscovery under new name.

## Novelty / Diversity Control
`src/qts/research/novelty.py` fingerprints `family+mechanism+features+param_keys` via SHA12, clusters trials, and reports `total_trials` versus `distinct_hypotheses` and largest cluster. These values are derived from the cumulative ledger for each run; historical examples are not current evidence.

## Campaign Engine
`src/qts/research/campaign.py` + `campaign_engine.py` 11 steps: 1 review data, 2 review failures, 3 generate bounded plan, 4 create hypotheses, 5 execute experiments, 6 store results, 7 attack candidates, 8 eliminate weak, 9 refine surviving, 10 re-test, 11 produce evidence portfolio. Budget explicit max_trials/runtime/feature/param/mutation/retries/data/seed, STOP when exhausted. Never moves to LIVE — only `PromotionLedger` human approval can.

## NO-TRADE as Research Variable
`src/qts/research/intelligence.py` asks WHEN REFUSE. Selective participation ALL vs HIGH-CONFIDENCE filtered signals penalized via same multiple-testing.

## Confidence Calibration
When system produces confidence, `src/qts/research/statistical.py` calibration via PSR/DSR probability, reliability measured; no  92% unless justified. Measures calibration, false-positive/negative, conditional expectancy.

## Data Acquisition
`docs/data_source_audit.md` + `src/qts/data/audit.py` compare licensing, depth, timestamp, bid/ask, spread, tick, survivorship, adjustments, broker differences — choose based on evidence, never silently substitute.

## Human + Agent Loop
Desktop `Research Lab` etc shows WHAT thinking, WHY hypothesis, EXPECTS, FAILED, LEARNED, NEXT, but human interaction limited to direction/campaign config/inspection/approval of stages, not overriding failed gates.

## Discovery Report
Per campaign: research question, hypotheses, mechanism, data, trial count, distinct hypotheses, strategies tested, failed/surviving candidates, strongest for/against each survivor, DSR/PBO/Reality Check/SPA, cost/execution sensitivity, regime, robustness, forward, uncertainty. See `docs/edge_discovery_report.md` updated with autonomous results.

## Candidate Survival Standard
Edge must survive OOS, multiple testing, costs, perturbation, regime,
null/placebo, expectancy, forward, and execution credibility — only then could
it become `MICRO_ELIGIBLE`. Current bounded campaign and edge artifacts have no
survivor; `BLOCK` / `NO_TRADE` is correct.

## Live Safety Untouchable
RESEARCH→VALIDATION→FORWARD→PAPER→SHADOW→MICRO→LIVE_ELIGIBLE cannot be skipped, no AI confidence overrides risk/reconciliation, no backtest unlocks live — `PromotionLedger` + `live_gate` enforce.

## Self-Audit
Per campaign 9 questions: leak? cherry-pick? over-search? N reset? reuse test set? overfit? under-model costs? unrealistic fills? confuse correlation with mechanism? repeatedly test same idea? suppress failures? If YES/UNKNOWN → BLOCK.

## Deliverables
This doc + 7 others, machine evidence `data/evidence/autonomous_research.json`, desktop 9 new views.

## Current Evidence

The current machine-readable evidence is authoritative:

- canonical datasets: `20260918-010+8f120133-1ba57af7` — XAUUSD 15m, 26,038
  tick-derived mid bars, 407 days, `REAL`, acquired but current gap
  completeness `FAIL` under the audited duration-based gate (frozen snapshot
  had recorded `READY`; provenance: `docs/data_provenance_xauusd_dukascopy.md`) — and the unchanged synthetic
  fixture `20260918-010+…-572728d9` (XAUUSD 1H, 500 bars, `SYNTHETIC`,
  `BLOCKED_INSUFFICIENT_DATA`);
- `data/evidence/campaign_last.json`: 2 bounded trials, 0 passed,
  `BLOCKED_INSUFFICIENT_DATA`;
- `data/evidence/autonomous_campaign.json`: 6 bounded trials, 0 passed,
  self-audit blocked;
- `data/evidence/edge_validation.json`: blocked, with cumulative trial
  accounting and unavailable/missing controls retained;
- `data/evidence/impulse_research_xauusd_dukascopy_15m.json`: REAL bar-based
  impulse research; `REGIME_DEPENDENT`, `go_block = BLOCK`, no promotion;
- `data/evidence/impulse_research.json`: historical synthetic mechanism
  validation only, not a real-market claim;
- no candidate is promoted and the operational conclusion remains
  `NO_TRADE`.

Do not copy counts from this overview into a new claim. Read the artifact's
bound experiment/configuration, code version, dataset, and limitations.

## References
Bailey & López de Prado PSR/DSR, White Reality Check 1996, Hansen SPA 2005, CPCV PBO.
