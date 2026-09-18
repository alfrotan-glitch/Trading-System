# Hypothesis Generation
Version: 0.1.0

## Autonomous Generation
`src/qts/research/intelligence.py` `IntelligenceOrchestrator.generate_mechanism_hypotheses` inspects prior evidence weaknesses (PBO, DSR, cost BE, worst regime) and creates a bounded set of falsifiable hypotheses from the mechanism pool defined in code. The pool is not evidence that every mechanism has been tested.

## Required Provenance per Hypothesis
Every `HypothesisSpec` stores:
- WHY THIS IDEA EXISTS: e.g., "PBO high, testing volatility expansion may reveal conditional edge not captured by SMA"
- WHAT MARKET MECHANISM IT ASSUMES: e.g., "volatility clustering — high vol begets high vol"
- WHAT OBSERVATION WOULD SUPPORT IT: "OOS Sharpe >0.3, WFE >0.3, DSR>0.95, cost BE >20bps, regime stable"
- WHAT OBSERVATION WOULD FALSIFY IT: "OOS ≤0, WFE<0.3, DSR<0.5, placebo equivalent, BE <5bps"
- WHAT DATA IS REQUIRED: "immutable provenance-qualified XAUUSD 1H history with enough depth/span, measured costs, and expansion needed for generality; the current 500-bar fixture is synthetic and mechanism-only"
- WHAT COST/EXECUTION CONDITIONS MATTER: "spread 3bps × multiplier, slippage, latency 100ms, next-bar-open"
- WHAT REGIMES IT SHOULD WORK IN: "trend for persistence, range for mean-reversion"
- WHAT CONDITIONS SHOULD MAKE IT STOP WORKING: "high_vol opposite regime should degrade"

## Example Hypotheses (illustrative, not current evidence)
- H-trend persistence: "If trend persists beyond costs, SMA crossover capturing it should survive walk-forward, CPCV, costs"
- H-volatility clustering: "If volatility clusters, ATR breakout should survive"
- H-time-of-day: "If session liquidity creates edge, session-conditioned strategy should survive"

The current campaign's exact hypothesis/configuration fields are stored with its
trial-bound evidence; these examples must not be read as completed tests.

## Generation Budget
Max 6 per batch, explicit seed, lineage `thought_lineage` tracks parent thought → hypothesis, mutation lineage via `IntelligenceOrchestrator.lineage`.

## Human + Agent Loop
UI `Research Lab` shows WHAT system thinking, WHY hypothesis, EXPECTS, FAILED, LEARNED, NEXT, but human cannot bypass gates — only direction/config/inspection/approval.

## Storage
Durable `research_thoughts` and `hypothesis_specs` SQLite, queryable via API `/api/research/thoughts`.

## References
Falsifiability per Popper, Bailey & López de Prado for PSR/DSR thresholds.
