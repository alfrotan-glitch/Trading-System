# Adversarial Research
Version: 0.1.0

## Purpose
Internal adversary whose objective is BREAK THE STRATEGY, not confirm it. Structurally hostile to false discoveries.

## Implementation
`src/qts/research/adversary.py` `adversarial_attack(strategy_id, evidence)` → `best_for`/`best_against`.

Searches for:
- leakage (future info, normalization, feature selection, locked test contamination)
- parameter fragility (perturbation drop >20%)
- regime dependence (worst regime Sharpe)
- cost sensitivity (BE <20bps)
- hidden assumptions (exact params, single regime)
- selective reporting (favorable periods, suppressed drawdown)
- unstable exits (trailing vs fixed fragility)
- unrealistic fills (mid-price vs next-bar-open, partial fills)
- overfitting (PBO >0.5, CPCV fail)
- false correlations (null control Sharpe close to real)
- random-control equivalence (placebo)
- data artifacts (high/low proxy, survivorship)

## Output per Candidate
- BEST EVIDENCE FOR: e.g., "WFE 0.59 suggests some OOS persistence", "PSR 0.85 probabilistic edge"
- BEST EVIDENCE AGAINST: e.g., "PBO 0.83 >0.5 overfitting", "Regime range -5.17 dependence", "Cost BE 3bps sensitive", "Null 0.45 equivalence", "Placebo not rejected"
- leakage_found: bool
- fragility: stable/fragile
- cost_sensitivity: robust/sensitive
- regime_dependence: stable/dependent
- verdict: BREAKS or SURVIVES (needs forward)
- never_report_only_favorable: both sides mandatory

## Example (sma_breakout, 45 trials)
For: WFE 0.59
Against: PBO 0.33 (now stable but still DSR 0.12 fail), DSR 0.12, regime -5.17, cost 3bps, null 0.45, placebo fail → verdict BREAKS.

## Integration
Campaign engine step 7 `attack candidates` calls adversary per survivor, eliminates weak (verdict BREAKS), refines surviving via `ResearchMemory` + `novelty`.

## Testing
Unit tests in `tests/test_desktop.py` verify adversary produces both sides, never only favorable.

## References
Lopez de Prado adversarial validation, Harvey et al. false discoveries.
