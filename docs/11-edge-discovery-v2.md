# QTS Edge Discovery v2 — XAUUSD Preregistered Research Plan

Status: RESEARCH ONLY / NO PROMOTION
Target: XAUUSD
Purpose: find a reproducible statistical edge without expanding the runtime architecture.

## Why v2

The prior edge record is not evidence of a failed strategy search: the canonical trial used a synthetic 500-bar fixture and was correctly blocked. The recovered 15m XAUUSD candidate has 26,178 bars but fails the active-span completeness gate (5.91% unexpected missing intervals versus a 2% limit). Therefore neither artifact may support a trading claim.

The next campaign must begin only from a claim-eligible historical/broker-derived dataset.

## Research priorities

The search is deliberately small. We test mechanisms, not indicator combinations.

### H1 — Volatility-normalized time-series momentum

Mechanism:
Persistent directional moves may continue after conditioning on realized volatility.

Signal:
direction(sign of return over a declared lookback) × volatility-normalized magnitude.

Candidate horizons:
15m, 1h, 4h.

Robustness:
lookback perturbation, volatility scaling, execution lag, spread/slippage stress, regime split.

### H2 — Momentum reversal after extreme realized semivariance

Mechanism:
Trend moves can reverse when downside/upside realized semivariance becomes unusually asymmetric.

Signal:
existing directional impulse + semivariance imbalance filter; test both continuation and reversal, preregistered before evaluation.

This is motivated by published commodity-futures research finding information in realized semivariance around time-series-momentum reversals.

### H3 — Session/opening information transfer

Mechanism:
An earlier active-session return may contain information about the next active session.

Signal:
declared prior-session return sign/magnitude predicts the next session's first fixed interval, with both momentum and reversal alternatives tested.

No arbitrary session selection after looking at results.

### H4 — Volatility compression → expansion

Mechanism:
A compressed volatility state can precede directional range expansion.

Signal:
pre-registered compression percentile + range expansion trigger + direction rule.

The test must distinguish genuine directional expectancy from volatility-only profit.

## Explicit exclusions

Do not search:
- large indicator grids;
- neural networks/black-box models;
- dozens of arbitrary thresholds;
- strategies selected because their equity curve looks attractive;
- single-event cherry picking;
- post-hoc regime definitions;
- parameter combinations chosen after inspecting the locked test set.

## Campaign design

1. Freeze dataset and provenance.
2. Freeze four hypotheses and mathematical definitions.
3. Discovery partition only.
4. Small bounded parameter set.
5. Chronological walk-forward.
6. Locked test remains untouched until the candidate is frozen.
7. Cost decomposition using measured or conservative broker-relevant assumptions.
8. Parameter perturbation.
9. Regime stability.
10. Randomized/null and placebo controls.
11. CPCV/PBO/PSR/DSR where sample size permits.
12. Only a surviving candidate may enter forward DEMO observation.
13. No result can unlock LIVE by itself.

## Minimum acceptance for an Edge Candidate

A candidate is not called an edge unless it:
- remains positive after declared costs;
- survives the locked out-of-sample period;
- has stable sign and economically meaningful expectancy across walk-forward folds;
- survives reasonable parameter perturbation;
- is not explained by one regime/event window;
- beats the declared null/placebo controls;
- passes multiple-testing correction;
- has an execution-cost break-even margin;
- can be expressed as a small deterministic rule;
- is reproducible from its immutable dataset, code revision, and parameter hash.

If any required gate fails: NO_VALIDATED_EDGE.

## Current research conclusion

The strongest literature-guided candidates for the next XAUUSD study are:
1. volatility-normalized trend/momentum;
2. semivariance-conditioned momentum reversal;
3. session-return information transfer;
4. compression-to-expansion.

This document does not promote any of them. It defines the next experiments only.
