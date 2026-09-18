# Edge Validation Report
**Generated:** 2026-09-18T10:20:51.016708+00:00
**Strategy:** sma_breakout
**Data version:** 20260918-010-572728d9
**Code version:** 0.1.0+64fab8dae9dc

## 1. Dataset integrity
- Manifest: 20260918-010-572728d9 XAUUSD 1H rows 500 checksum sha256:572728d92ebb5c2a timezone UTC preprocessing 1.0 source SYNTHETIC:fixture:XAUUSD_1H_500.csv
- Quality passed: True checks: monotonic_time:PASS, tz_aware:PASS, no_future:PASS, ohlc_invariants:PASS, positive_prices:PASS, abnormal_spreads:PASS, no_duplicates:PASS, single_symbol:PASS, no_missing_bars:PASS, session_boundaries:PASS, no_broker_artifacts:PASS, volume_non_negative:PASS
- Missing stats: {'status': 'MEASURED', 'expected': 501, 'actual': 500, 'missing': 1, 'gap_count': 0, 'max_gap_s': 0.0, 'missing_pct': 0.2, 'timezone': 'UTC'}
- Locked partition: discovery 300 validation 100 locked 100 frozen True access_log 0 attempts

## 2. Trial count
- Trials: 304 (all materially tested variants counted, DSR uses N=304)

## 3. Locked-test status
- Frozen: True — locked test never influenced design/params/thresholds/feature selection
- Access log: []

## 4. Walk-forward results
- WFE: -0.69 passed: False
- Details: walk_forward_min_folds=True; walk_forward_wfe=False; walk_forward_oos_sharpe=False

## 5. CPCV/PBO
- PBO: UNAVAILABLE passed: False details: PBO CPCV not executed (need >=6 combos, got 0) → BLOCKS

## 6. PSR/DSR
- PSR: 0.46 DSR: 0.00 trials 304 passed: False

## 7. Null controls
- Null-control evidence: {'status': 'NOT_IMPLEMENTED', 'value': None, 'reason': 'separate randomized signal model was not executed'}

## 8. Stress results
- Stress: {1.0: 1.0322221474267004, 1.5: 1.0320169672876036, 2.0: 1.031813412459434}

## 9. Cost/slippage tolerance
- Break-even spread: 0.0bps passed: False details: gross/net cost decomposition NOT_IMPLEMENTED — blocks

## 10. Regime results
- Regimes: {'status': 'UNAVAILABLE', 'value': None, 'reason': 'regime result is not separately bound in this evidence object; edge details contain the gate'}

## 11. Forward paper results
- Forward: {'status': 'INSUFFICIENT_EVIDENCE', 'real_observations': 0, 'note': 'observation count only; divergence/realized PnL requires a bound session export'}

## 12. Shadow/paper discrepancy
- Consistency: {'status': 'UNAVAILABLE', 'value': None, 'reason': 'shadow/paper artifacts are not bound to this experiment'}

## 13. Expected net edge
- Expectancy: {'status': 'UNAVAILABLE', 'value': None, 'reason': 'realized trade PnL attribution is unavailable from BacktestResult fills'}
- Economic edge: {'status': 'UNAVAILABLE', 'value': None, 'reason': 'gross/net cost decomposition is unavailable'}

## 14. Drawdown
- Drawdown / expected shortfall evidence: {'status': 'UNAVAILABLE', 'value': None, 'reason': 'realized trade PnL attribution is unavailable from BacktestResult fills'}

## 15. Worst observed failure
- Worst regime/stress: UNAVAILABLE

## 16. Capital-at-risk assumptions
- Risk per trade {'status': 'UNAVAILABLE', 'value': None, 'reason': 'authoritative account state is unavailable in research mode'} + SymbolSpec authoritative, spread/slippage/delay net metrics

## 17. Exact reasons for PASS or BLOCK
- Edge survival passed: False checks: {'walk_forward': False, 'spread': True, 'cost': False, 'perturbation': False, 'time_window': False, 'regime': False, 'randomized_control': False, 'walk_forward_K': False, 'cpcv': False, 'pbo': False, 'psr': False, 'dsr': False, 'placebo': False, 'expectancy': False, 'economic_edge': False}
- Economic edge evidence: {'status': 'UNAVAILABLE', 'value': None, 'reason': 'gross/net cost decomposition is unavailable'}
- Overall: **BLOCK — keep NO_TRADE** — genuine edge must survive costs, regime, perturbation, multiple testing, unseen data

## Promotion
- Current promotion state: RESEARCH — one-way RESEARCH→LIVE_ELIGIBLE, no skip, anomaly→SUSPENDED
- Emergency kill: {'kill_switch': False, 'execution_enabled': False}

