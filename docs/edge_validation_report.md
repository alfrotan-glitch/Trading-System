# Edge Validation Report
**Generated:** 2026-09-16T14:08:36.444539+00:00
**Strategy:** sma_breakout
**Data version:** 20260916-010-572728d9
**Code version:** 0.1.0

## 1. Dataset integrity
- Manifest: 20260916-010-572728d9 XAUUSD 1H rows 500 checksum sha256:572728d92ebb5c2a timezone UTC preprocessing 1.0 source synthetic_or_csv
- Quality passed: True checks: monotonic_time:PASS, tz_aware:PASS, no_future:PASS, ohlc_invariants:PASS, positive_prices:PASS, abnormal_spreads:PASS, no_duplicates:PASS, single_symbol:PASS, no_missing_bars:PASS, session_boundaries:PASS, no_broker_artifacts:PASS, volume_non_negative:PASS
- Missing stats: {'expected': 501, 'actual': 500, 'missing': 1, 'gap_count': 0, 'max_gap_s': 0, 'missing_pct': 0.2, 'timezone': 'UTC'}
- Locked partition: discovery 300 validation 100 locked 100 frozen True access_log 0 attempts

## 2. Trial count
- Trials: 45 (all materially tested variants counted, DSR uses N=45)

## 3. Locked-test status
- Frozen: True — locked test never influenced design/params/thresholds/feature selection
- Access log: []

## 4. Walk-forward results
- WFE: 0.59 passed: True
- Details: walk_forward_min_folds=True; walk_forward_wfe=True; walk_forward_oos_sharpe=True

## 5. CPCV/PBO
- PBO: 0.33 passed: True details: PBO 0.33

## 6. PSR/DSR
- PSR: 0.85 DSR: 0.12 trials 45 passed: False

## 7. Null controls
- Control sharpes: [0.14901424590336979, -0.0414792903513554, 0.19430656143020775, 0.45690895692240757, -0.07024601241700079] rejected: False

## 8. Stress results
- Stress: {1.0: 1.0322221474267004, 1.5: 1.0320169672876036, 2.0: 1.031813412459434}

## 9. Cost/slippage tolerance
- Break-even spread: 3.0bps passed: False details: net_sharpe 0.02 pf 1.00 be_spread 3.0bps tol 0.0bps

## 10. Regime results
- Regimes: [{'regime': 'trend', 'sharpe': 4.466737959747593, 'passed': True}, {'regime': 'range', 'sharpe': -5.179791746655208, 'passed': False}, {'regime': 'high_vol', 'sharpe': 1.6003123126448962, 'passed': True}]

## 11. Forward paper results
- Forward: {'signals': 10, 'no_trades': 90, 'invalidated': False}

## 12. Shadow/paper discrepancy
- Consistency: {'missed_entries': 4, 'unexpected_fills': 0, 'avg_price_diff_bps': 144.7310040068556, 'max_price_diff_bps': 850.8872468975351, 'avg_timing_diff_s': 0.5, 'rejected_trades': 0, 'partial_fills': 0, 'slippage_error_bps': 144.7310040068556, 'error_distribution': [3.4987754285990134, 3.5012254288998457, 3.498775428599632, 3.5012254288994793, 3.498775428600666, 850.8872468975351], 'paper_represents_live': False}

## 13. Expected net edge
- Expectancy: {'expectancy_per_trade': -48.322339795877525, 'profit_factor': 0.9763406556135362, 'avg_win': 276.4818810817307, 'avg_loss': -280.48480695238095, 'win_rate': 0.4168336673346693, 'loss_rate': 0.5831663326653307, 'max_drawdown': 8418.6, 'expected_shortfall': -559.3799999999999, 'turnover': 499.0, 'cost_per_trade': 0.0, 'net_expectancy': -48.322339795877525, 'net_expectancy_after_costs': -48.322339795877525, 'trades': 499}
- Economic edge: {'expected_net_edge': -48.322339795877525, 'conservative_cost': 0.01, 'statistical_uncertainty': 0.02, 'model_penalty': 0.01, 'remaining_edge': -48.362339795877524, 'passed': False, 'criterion': 'remaining = expectancy -48.3223 - cost 0.0100 - uncertainty 0.0200 - penalty 0.0100 = -48.3623 > threshold 0.0 and >20% cost'}

## 14. Drawdown
- Max DD: 8418.6 expected shortfall: -559.3799999999999

## 15. Worst observed failure
- Worst regime/stress: {'regime': 'range', 'sharpe': -5.179791746655208, 'passed': False}

## 16. Capital-at-risk assumptions
- Risk per trade {'passed': True, 'reason': None} + SymbolSpec authoritative, spread/slippage/delay net metrics

## 17. Exact reasons for PASS or BLOCK
- Edge survival passed: False checks: {'walk_forward': True, 'spread': True, 'cost': False, 'perturbation': False, 'time_window': True, 'regime': False, 'randomized_control': False, 'walk_forward_K': True, 'cpcv': True, 'pbo': True, 'psr': True, 'dsr': False, 'placebo': False, 'expectancy': False, 'economic_edge': False}
- Economic edge passed: False criterion: remaining = expectancy -48.3223 - cost 0.0100 - uncertainty 0.0200 - penalty 0.0100 = -48.3623 > threshold 0.0 and >20% cost
- Overall: **BLOCK — keep NO_TRADE** — genuine edge must survive costs, regime, perturbation, multiple testing, unseen data

## Promotion
- Current promotion state: RESEARCH — one-way RESEARCH→LIVE_ELIGIBLE, no skip, anomaly→SUSPENDED
- Emergency kill: {'kill_switch': True}

