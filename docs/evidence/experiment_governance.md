# Experiment Governance
Version: 0.1.0

## Economics
Every experiment costs statistical credibility. Track:
- trial count (monotonic `ExperimentStore.count_trials()`)
- hypothesis family (trend/breakout/...),
- parameter count (len(params)),
- feature count (len(feature_lineage)),
- search depth (campaign iteration),
- selection stages (pipeline stages),
- dataset count (manifest versions),
- timeframe count,
- symbol count,
- manual interventions (registry_log),
- re-runs (experiment lineage)

More search → stronger DSR requirement: `deflated_sharpe_ratio` with N including discarded. No hidden retries.

## No Hidden
- No cherry-picking: `campaign_trials` stores all pass/fail, `ranked_for_inspection` only for viewing.
- No N reset: `ExperimentStore` never deletes, `count_trials()` monotonic, fresh campaign does not reset N — `campaigns_summary.json` reports cumulative N.
- No deletion of failed experiments: `rejections` table preserves reason, `research_memory` remembers.
- No fresh campaign secret reset: explicitly checked via `ResearchCampaignStore` cumulative, `novelty.report_novelty` reports distinct vs total.
- No leaking test set: `LockedTestPartitioner` frozen, access_log, discovery never reads locked; any accidental access invalidates via `DiscoveryPipeline`.

## Governance Controls
- `FeatureStore` lineage, timestamp semantics, no future.
- `PositionManager` joint hypothesis, exit policies documented.
- `ResearchMemory` prevents rediscovery.
- `Novelty` clusters, reports distinct.
- `PromotionLedger` one-way, no skip, no manual DB edit — only `transition` audited.

## Budget
Every campaign explicit `max_trials`, `max_runtime_s`, `max_feature_count` (via param_space), `max_param_combinations`, `max_mutation_depth` (via lineage), `max_retries`, `max_data_scope` (manifest), `random seed`. When exhausted → STOP, status COMPLETED, no silent continue.

## Self-Audit
Per campaign 9 questions (did we leak? cherry-pick? over-search? N reset? reuse test set? overfit? under-model costs? unrealistic fills? confuse correlation? repeatedly test same idea? suppress failures?) → if YES/UNKNOWN → BLOCK.

## Machine Evidence
`data/evidence/experiment_governance.json` with trial counts, family breakdown, selection stages.

## Human Loop
Human for direction/campaign config/inspection/approval of stages, not for overriding failed gate.

## Verification
Tests: `test_trial_ledger`, `test_novelty`, `test_memory_no_rediscovery` verify no hidden experiments.
