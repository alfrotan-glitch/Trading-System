# Impulse Continuation Research — Evidence Report

Generated: 2026-09-16T18:47:50.410106+00:00  ·  Mode: **MECHANISM_VALIDATION**

> Dataset failed the pre-registered data-adequacy gate. All numbers below describe the RESEARCH MECHANISM operating on this dataset, NOT real-market behavior. No real-market claim is permitted and nothing was promoted.

## Hypothesis
When price begins an unusually strong directional movement, the conditional distribution of the next short horizon is sufficiently directional and persistent to create positive net expectancy after spread, commission, slippage, and latency.

## Dataset provenance
- version `20260916-010-572728d9` · XAUUSD 1H · venue MT5
- checksum `sha256:572728d92ebb5c2a` · rows 500 · bars read 500
- span 2020-01-01T00:00:00+00:00 → 2020-01-21T20:00:00+00:00 (UTC)
- source label `SYNTHETIC:fixture:XAUUSD_1H_500.csv` · **data class: SYNTHETIC**

## Data adequacy gate
adequate_for_real_claims: **False**

| ID | Requirement | Minimum | Observed | Passed | Blocking |
|----|-------------|---------|----------|--------|----------|
| R1-REAL-PROVENANCE | Data must be REAL broker/exchange history — synthetic or simulated data cannot s | data_class == REAL | data_class=SYNTHETIC (source='SYNTHETIC:fixture:XAUUSD_1H_50 | FAIL | yes |
| R2-DEPTH | Minimum number of bars for event-count sufficiency | >= 5000 bars (target 17520) | 500 bars | FAIL | yes |
| R3-REGIME-COVERAGE | Series must span enough calendar time to contain multiple volatility regimes | >= 180 days | 20.8 days | FAIL | yes |
| R4-FRESHNESS | Real-time impulse claims require recent data (stale data cannot describe current | last bar within 7 days of assessment time | last bar 2429.9 days old | FAIL | yes |
| R5-EXECUTION-DATA | Real spread/bid-ask/tick history is required to replace declared cost ASSUMPTION | bid/ask or tick data with real spread history available | OHLC bars only — no bid/ask, no ticks (costs remain ESTIMATE | FAIL | no |
| R6-EVENT-SUFFICIENCY | Enough measured events (per side) for statistical inference after multiple-testi | >= 100 total, >= 30 per side | total=53 long=27 short=26 | FAIL | yes |

## Pre-registered design
- families: 10 (5 definitions x 2 parameterizations, no data-driven search)
- horizons (bars): [12, 4] (primary 12)
- warmup: 64 bars · alpha: 0.05 · bootstrap: 2000
- declared cost assumptions (ESTIMATED): {'spread_bps': 2.0, 'commission_bps_round_turn': 0.4, 'slippage_bps_per_side': 0.5, 'latency_bars': 1, 'round_turn_cost_bps': 3.4, 'provenance': 'ESTIMATED:declared_assumption'}
- splits: discovery/validation chronological; LOCKED partition untouched: True
- events: detected 53, measured 106, excluded (insufficient forward bars) 0, discarded-in-locked 11
- trials recorded in ledger: 40 · ledger total (never reset): 57 · DSR penalized with N=57

## Results (primary horizon 12 bars, pooled discovery+validation)

| Family | n | cont. rate | baseline | diff | p_raw | p_holm | gross bps | net bps | net CI | TTT hit | MFE | MAE | DSR |
|--------|---|------------|----------|------|-------|--------|-----------|---------|--------|---------|-----|-----|-----|
| IMP-BE-B | 7 | 0.429 | 0.462 | -0.034 | 1.0000 | 1.0000 | -231.21 | -234.61 | [-586.46,71.41] | 0.43 | 196.0 | 212.2 | 0.000 |
| IMP-BE-V | 3 | 0.667 | 0.500 | +0.167 | 1.0000 | 1.0000 | +61.82 | +58.42 | [-330.44,274.47] | 1.00 | 344.8 | 95.5 | 0.025 |
| IMP-PV-B | 6 | 0.500 | 0.448 | +0.052 | 1.0000 | 1.0000 | -203.43 | -206.83 | [-716.36,320.95] | 0.33 | 163.4 | 314.9 | 0.002 |
| IMP-PV-V | 1 | 0.000 | 0.506 | -0.506 | 0.4938 | 1.0000 | -938.62 | -942.02 | [-942.02,-942.02] | 0.00 | 16.4 | 460.5 | n/a |
| IMP-RB-B | 16 | 0.375 | 0.454 | -0.079 | 0.6205 | 1.0000 | -132.61 | -136.01 | [-349.56,70.79] | 0.44 | 181.6 | 218.7 | 0.000 |
| IMP-RB-V | 10 | 0.500 | 0.465 | +0.035 | 1.0000 | 1.0000 | -16.69 | -20.09 | [-328.65,306.49] | 0.60 | 257.9 | 206.3 | 0.007 |
| IMP-RE-B | 7 | 0.286 | 0.523 | -0.237 | 0.2696 | 1.0000 | -150.28 | -153.68 | [-664.10,356.02] | 0.71 | 254.8 | 186.9 | 0.003 |
| IMP-RE-V | 1 | 0.000 | 0.525 | -0.525 | 0.4752 | 1.0000 | -1003.48 | -1006.88 | [-1006.88,-1006.88] | 1.00 | 302.7 | 128.6 | n/a |
| IMP-VE-B | 2 | 0.000 | 0.487 | -0.487 | 0.5003 | 1.0000 | -566.72 | -570.12 | [-896.33,-243.91] | 0.50 | 303.5 | 268.0 | n/a |
| IMP-VE-V | 0 | 0.000 | 0.497 | +0.000 | 1.0000 | 1.0000 | +0.00 | +0.00 | [0.00,0.00] | 0.00 | 0.0 | 0.0 | n/a |

## Cost / spread / latency sensitivity (pooled net mean bps, primary horizon)

| Family | cost 0.5x | 1x | 1.5x | 2x | spread 0.5x | 1x | 1.5x | 2x | latency 0 | 1 | 2 |
|--------|-----------|----|------|----|-------------|----|------|----|-----------|---|---|
| IMP-BE-B | -232.91 | -234.61 | -236.31 | -238.01 | -233.61 | -234.61 | -235.61 | -236.61 | -261.07 | -234.61 | -273.17 |
| IMP-BE-V | +60.12 | +58.42 | +56.72 | +55.02 | +59.42 | +58.42 | +57.42 | +56.42 | +125.52 | +58.42 | -76.60 |
| IMP-PV-B | -205.13 | -206.83 | -208.53 | -210.23 | -205.83 | -206.83 | -207.83 | -208.83 | -195.32 | -206.83 | -226.00 |
| IMP-PV-V | -940.32 | -942.02 | -943.72 | -945.42 | -941.02 | -942.02 | -943.02 | -944.02 | -653.61 | -942.02 | -873.35 |
| IMP-RB-B | -134.31 | -136.01 | -137.71 | -139.41 | -135.01 | -136.01 | -137.01 | -138.01 | -199.50 | -136.01 | -177.55 |
| IMP-RB-V | -18.39 | -20.09 | -21.79 | -23.49 | -19.09 | -20.09 | -21.09 | -22.09 | -49.02 | -20.09 | -75.51 |
| IMP-RE-B | -151.98 | -153.68 | -155.38 | -157.08 | -152.68 | -153.68 | -154.68 | -155.68 | -176.39 | -153.68 | -153.28 |
| IMP-RE-V | -1005.18 | -1006.88 | -1008.58 | -1010.28 | -1005.88 | -1006.88 | -1007.88 | -1008.88 | -1012.78 | -1006.88 | -1012.20 |
| IMP-VE-B | -568.42 | -570.12 | -571.82 | -573.52 | -569.12 | -570.12 | -571.12 | -572.12 | -585.59 | -570.12 | -745.39 |
| IMP-VE-V | +0.00 | +0.00 | +0.00 | +0.00 | +0.00 | +0.00 | +0.00 | +0.00 | +0.00 | +0.00 | +0.00 |

## Conclusion
**BLOCKED_INSUFFICIENT_DATA** — research GO/BLOCK: **BLOCK**

- R1-REAL-PROVENANCE: Data must be REAL broker/exchange history — synthetic or simulated data cannot support claims about real-market behavior (minimum: data_class == REAL; observed: data_class=SYNTHETIC (source='SYNTHETIC:fixture:XAUUSD_1H_500.csv'))
- R2-DEPTH: Minimum number of bars for event-count sufficiency (minimum: >= 5000 bars (target 17520); observed: 500 bars)
- R3-REGIME-COVERAGE: Series must span enough calendar time to contain multiple volatility regimes (minimum: >= 180 days; observed: 20.8 days)
- R4-FRESHNESS: Real-time impulse claims require recent data (stale data cannot describe current market microstructure) (minimum: last bar within 7 days of assessment time; observed: last bar 2429.9 days old)
- R5-EXECUTION-DATA: Real spread/bid-ask/tick history is required to replace declared cost ASSUMPTIONS with broker-observed costs (bar high-low range is only a proxy) (minimum: bid/ask or tick data with real spread history available; observed: OHLC bars only — no bid/ask, no ticks (costs remain ESTIMATED assumptions))
- R6-EVENT-SUFFICIENCY: Enough measured events (per side) for statistical inference after multiple-testing correction (minimum: >= 100 total, >= 30 per side; observed: total=53 long=27 short=26)

Promotion: BLOCKED — research artifact only. Lifecycle state unchanged. Not connected to order submission. Demo success never implies live eligibility.

## Safety invariants
- live_trading_enabled: False
- live_eligibility_modified: False
- order_submission_connected: False
- promotion_state_modified: False
- locked_test_partition_accessed: False
- trial_ledger_reset: False
