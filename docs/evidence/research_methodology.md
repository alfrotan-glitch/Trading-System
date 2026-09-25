# Research Methodology
Version: 0.1.0

## Principle
Maximum freedom to INVENT, minimum freedom to ACCEPT. Expansive generation, conservative acceptance. Allowed to be wrong, not allowed to hide wrong.

## Stages (no bypass)
DATA_QUALITY (12 checks, manifest versioned, checksum, timezone UTC, missing stats, session) → DISCOVERY (300 bars, never locked) → IN_SAMPLE → WALK_FORWARD (WFE >0.3, OOS Sharpe >0.3) → CPCV (6 folds purged/embargo) → PBO (<0.5) → PSR (>0.95) → DSR (N trials, >0.95) → COST_STRESS (1.0/1.5/2.0× spread, BE >20bps) → PERTURBATION (±15% param <20% drop) → REGIME (trend/range/high_vol each must not rely) → NULL_CONTROL (random timing/shuffled labels) → PLACEBO (intentionally bad strategies) → EXPECTANCY (PF>1, positive net after cost) → ECONOMIC_EDGE (remaining = expectancy - cost - uncertainty - penalty >0 and >20% cost) → FORWARD_PAPER (10/90 frozen, no retune) → SHADOW (shadow vs paper diff <50bps) → PROMOTION_DECISION (ledger one-way).

`DiscoveryPipeline` enforces order, `EdgeScorecard` shows each dimension, `overall_passed` requires all mandatory.

## Hypothesis Formalism
Every hypothesis spec has WHY, mechanism assumed, support observation, falsify observation, data required, cost conditions, regimes expected/stop conditions, family, lineage. Stored in `hypothesis_specs` with thought lineage.

## Feature Methodology
Controlled `FeatureStore`, 6 baseline features, every transformation timestamp semantics "computed at close_time using only bars ≤ N", lineage versioned, leakage string check, normalization per window only on IS, feature selection on DISCOVERY only, locked test never used.

## Position Management Methodology
Joint entry+exit hypothesis: entry family × exit policy (6 types). Tested OOS paired, not assumed superior. Emergency exit always available.

## Statistical Rigor
Retain PSR/DSR/PBO/WFE, extend White Reality Check (bootstrap max Sharpe p-value), Hansen SPA (max t), permutation (shuffle labels), minimum backtest length (invert PSR), drawdown distribution (bootstrap ES), parameter surface (peak vs mean). Each documented purpose/assumptions/limitations, unit tests, failure modes in `src/qts/research/statistical.py`.

## Multiple Markets
Single 500 XAUUSD 1H sample limitation explicitly reported. Expansion requires 5000+ bars, multi-year, multi-symbol, multi-timeframe, real bid/ask — only for uncertainty reduction, not to make strategy look good. `src/qts/data/audit.py` audits.

## Execution-Aware
Next-bar-open, spread 3bps × multiplier, slippage, latency 100ms, partial fills, bid/ask asymmetry, stop execution, liquidity. Mid-price only edge not validated.

## Adversarial
Internal adversary `adversarial_attack` reports best for/against, never only favorable.

## Economics
Trial count monotonic, family/param/feature/search depth/dataset counts tracked, N never reset, no hidden retries, no cherry-picking. See `docs/experiment_governance.md`.

## Memory & Novelty
`ResearchMemory` remembers failures, `has_failed_similar` blocks rediscovery. `novelty.py` fingerprints, reports distinct vs total.

## Campaign
Explicit budget max_trials/runtime/feature/param/mutation/retries/data/seed, STOP when exhausted. 11 steps autonomously, human for direction/config/inspection/approval, not bypass.

## Self-Audit
9 questions per campaign, if YES/UNKNOWN → BLOCK.

## References
Bailey 2012 PSR, Bailey & López de Prado 2014 DSR, Lopez de Prado CPCV, White 1996, Hansen 2005, plus regime/perturbation.

## Evidence
All stages produce `edge_validation.json` + `campaigns_summary.json` + `autonomous_research.json` machine-readable, audit logs, lineage.
