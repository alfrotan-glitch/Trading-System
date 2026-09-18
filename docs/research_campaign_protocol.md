# Research Campaign Protocol
Version: 0.1.0

> Current status and sequencing are maintained in [`docs/current_state.md`](current_state.md). This protocol describes the campaign machinery; it is not the authority for the latest dataset or research conclusion.

## Purpose
Controlled research engine for discovering genuine edge, not optimising backtest profit. Golden principle: edge survives attempts to disprove it.

## Hypothesis / Strategy Registry
Durable `StrategyRegistry` (`src/qts/research/registry.py`) SQLite `strategy_registry`. Required fields per candidate:
- unique strategy_id
- name, version
- hypothesis (falsifiable statement)
- market/symbol, timeframe
- data_manifest (version hash)
- feature_definition (interpretable dict: e.g., {"sma_fast":5, "crossover":"fast>SLOW"})
- parameter_definition (e.g., {"fast":5, "slow":20})
- execution_assumptions (spread/slippage/latency)
- risk_assumptions (risk_per_trade, max_exposure)
- creation_timestamp, code_revision, lifecycle_state, family, created_by

`validate_documented()` rejects if any required empty — no undocumented strategies enter validation.

## Controlled Strategy Search
Families (`src/qts/research/strategies.py`):
- trend following (SMA/EMA crossover)
- breakout (Donchian)
- mean reversion (Bollinger)
- momentum (close - close_n)
- volatility (ATR breakout)
- regime-conditioned variants (wrapper that checks regime before signalling)

Start simple interpretable before complex ML. Do not assume profitability. Engine systematically discovers, tests, rejects.

## Search Space Control
Every tested variation = trial in `ExperimentStore` (Hypothesis + Experiment, hash, seed, manifest, code_version, params, lineage). Counts:
- winners, losers, discarded, param variants, feature variants, failed experiments.

No hidden experiments. No manual trial-count adjustment. `trial_count = ExperimentStore.count_trials()` feeds DSR correction (`dsr_prob` with N). Campaign also writes `campaign_trials` table.

## Locked Test Protection
`LockedTestPartitioner` creates immutable DISCOVERY(300)/VALIDATION(100)/LOCKED(100) partitions via hash, frozen flag, access_log. Discovery/optimization never reads locked test. After freeze, locked test may be run only through `PromotionLedger` promotion (VALIDATING→VALIDATED→FORWARD_OBSERVATION). Any accidental access logs and invalidates experiment — pipeline checks `is_frozen` and `access_log`.

## Edge Discovery Pipeline
For every candidate, enforced order via `DiscoveryPipeline` STAGES:
DATA_QUALITY → DISCOVERY → IN_SAMPLE → WALK_FORWARD → CPCV → PBO → PSR → DSR → COST/STRESS → PERTURBATION → REGIME → NULL_CONTROL → PLACEBO_CONTROL → EXPECTANCY → ECONOMIC_EDGE → FORWARD_PAPER → SHADOW → PROMOTION_DECISION

No stage bypass — `_require_prior` raises if prior missing. No re-entry. `overall_passed()` requires all mandatory gates.

## Edge Scorecard
`EdgeScorecard` shows each dimension independently:
- OOS performance (oos_sharpe, oos_return, is_sharpe)
- WFE value/passed, PBO value/passed, PSR/DSR with trials/passed
- drawdown, expectancy, profit_factor, win_rate
- cost break-even bps/passed, slippage tolerance dict, regime results + worst regime, perturbation drop %, null/placebo sharpes + passed flags, forward signals, shadow/paper diff bps, economic remaining/passed, checks dict, overall_passed, blocked_reasons.

No simplistic single score hides failures. Candidate passes only if every mandatory gate passes.

## Candidate Lifecycle
Durable `PromotionLedger` state machine:
RESEARCH → CANDIDATE → VALIDATING → VALIDATED → FORWARD_OBSERVATION → PAPER_VERIFIED → SHADOW_VERIFIED → MICRO_ELIGIBLE → MICRO_VALIDATED → LIVE_ELIGIBLE
plus SUSPENDED/REJECTED.

Failure returns to appropriate research state or SUSPENDED. No skip (one-way, `_ALLOWED` map), no manual promotion via SQL — only `ledger.transition` audited. `SUSPENDED` can go back to `RESEARCH` for investigation.

Example: RESEARCH→CANDIDATE (hypothesis passes falsifiability) → VALIDATING (full pipeline) → VALIDATED (all gates pass) → FORWARD_OBSERVATION (frozen forward, no retune) → PAPER_VERIFIED (shadow vs paper consistency) → etc. Currently all campaign candidates stuck at RESEARCH/BLOCKED.

## Automated Research Campaigns
Bounded campaign via `CampaignConfig`:
- name, symbol, timeframe, data_version, family, param_space, max_trials (≤100), max_runtime_s, max_param_combinations, seed, hypothesis_template.

Launch:
- `qts research campaign --family trend --data-version <immutable-canonical-version> --trials 12`
- Or via desktop Research Center UI.
- Or API POST /api/research/campaigns.

System:
- assigns trial IDs `T-xxxx`, strategy IDs `family_xxxx`,
- runs experiments (BacktestEngine + ValidatorPipeline + edge_validation),
- stores results in `campaign_trials` + `experiments` + `strategy_registry`,
- rejects invalid via `ExperimentStore.reject`,
- applies DSR with current N,
- ranks candidates `ranked_for_inspection` sorted by OOS Sharpe for inspection only,
- never auto-promotes solely on high return — promotion requires `PromotionLedger` + human approval + scorecard overall_pass.

## Research Stop Conditions
Enforce caps:
- max_trials per campaign (default 20, hard cap 100),
- max_runtime_s (default 300s),
- max_compute not yet but limited via runtime + param_combinations,
- max_param_combinations (cartesian product limited),
- reproducible seeds (seed + trial idx),
- mandatory logging (registry_log, promotion_log, audit_log, campaign_trials, lineage).

Exceeded → campaign status COMPLETED with partial results, never silent infinite loop.

## Golden Principle
Objective is NOT "find most money historically" — that is overfitting.
Objective IS "find edge surviving attempts to disprove it" — walk-forward, CPCV, PBO, PSR/DSR, cost/regime/perturbation, null/placebo, expectancy, economic, forward/shadow.

If insufficient evidence → KEEP NO_TRADE. The bounded campaign and edge
artifacts remain blocked by synthetic provenance and insufficient depth/span; no
candidate is promoted. Separately, the REAL XAUUSD 15m impulse study has run and
returned `REGIME_DEPENDENT / go_block = BLOCK`; it does not override this
protocol or establish a validated edge.

## Evidence
- Canonical campaign artifact: `data/evidence/campaign_last.json`; compact pointer: `data/evidence/campaigns_summary.json`.
- Cumulative experiment and campaign trial counts are read from SQLite and are not manually copied into this protocol.
- Current campaign trials retain immutable dataset/configuration/provenance and `BLOCKED_INSUFFICIENT_DATA` conclusions.
- Promotion state remains RESEARCH for all.

## Security
No secrets, separate envs, live remains LOCKED.
