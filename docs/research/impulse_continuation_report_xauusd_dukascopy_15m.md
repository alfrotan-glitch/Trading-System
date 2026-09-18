# Impulse Continuation Research — Evidence Report

Generated: 2026-09-18T15:23:39.228005+00:00  ·  Mode: **REAL_CLAIMS**

> Dataset passed the data-adequacy gate; conclusions may reference real-market behavior.

## Hypothesis
When price begins an unusually strong directional movement, the conditional distribution of the next short horizon is sufficiently directional and persistent to create positive net expectancy after spread, commission, slippage, and latency.

## Dataset provenance
- version `20260918-010+8f120133-1ba57af7` · XAUUSD 15m · venue MT5
- checksum `sha256:1ba57af7d9d034d9` · rows 26038 · bars read 26038
- span 2025-08-06T00:00:00+00:00 → 2026-09-17T00:00:00+00:00 (UTC)
- source label `REAL:dukascopy:vudo805@4d6f155:XAUUSD:15m:mid-from-bid-ask-ticks` · **data class: REAL**
- code version `0.1.0+8f120133e7bc`

## Falsifiable specification
- **Mechanism:** short-horizon directional persistence after an impulse, rather than unconditional continuation
- **Measurable Prediction:** impulse events have higher continuation and net-return distributions than the matched non-event baseline after declared costs
- **Null Hypothesis:** impulse events have no incremental predictive value versus the matched baseline after costs and timing controls
- **Horizon:** primary=12 bars; sensitivity=[12, 4]
- **Population:** XAUUSD 15m bars from the declared venue/source
- **Regime:** all declared volatility regimes; no unmeasured regime may be silently excluded
- **Competing Explanations:** selection or trial-count bias; timestamp/look-ahead leakage; single-regime or single-instrument artifact; cost assumptions masking unavailable broker execution evidence
- **Falsification Criteria:** chronological validation does not replicate the effect; the effect disappears under declared cost or latency sensitivity; the effect is not separated from baseline/placebo controls; event counts or regime coverage remain insufficient for the claim
- **Required Data:** immutable provenance-qualified OHLC history; measured bid/ask or tick spread and execution-cost fields; enough events per direction across multiple regimes; untouched chronological validation and forward observation

## Data adequacy gate
adequate_for_real_claims: **True**

| ID | Requirement | Minimum | Observed | Passed | Blocking |
|----|-------------|---------|----------|--------|----------|
| R1-REAL-PROVENANCE | Data must be REAL broker/exchange history — synthetic or simulated data cannot s | data_class == REAL | data_class=REAL (source='REAL:dukascopy:vudo805@4d6f155:XAUU | PASS | yes |
| R2-DEPTH | Minimum number of bars for event-count sufficiency | >= 5000 bars (target 17520) | 26038 bars | PASS | yes |
| R3-REGIME-COVERAGE | Series must span enough calendar time to contain multiple volatility regimes | >= 180 days | 407.0 days | PASS | yes |
| R4-FRESHNESS | Real-time impulse claims require recent data (stale data cannot describe current | last bar within 7 days of assessment time | last bar 1.6 days old | PASS | yes |
| R5-EXECUTION-DATA | Real spread/bid-ask/tick history is required to replace declared cost ASSUMPTION | bid/ask or tick data with real spread history available | OHLC bars only — no bid/ask, no ticks (costs remain ESTIMATE | FAIL | no |
| R6-EVENT-SUFFICIENCY | Enough measured events (per side) for statistical inference after multiple-testi | >= 100 total, >= 30 per side | total=3759 long=1874 short=1885 | PASS | yes |

## Pre-registered design
- families: 10 (5 definitions x 2 parameterizations, no data-driven search)
- horizons (bars): [12, 4] (primary 12)
- warmup: 64 bars · alpha: 0.05 · bootstrap: 2000
- declared cost assumptions (ESTIMATED): {'spread_bps': 2.0, 'commission_bps_round_turn': 0.4, 'slippage_bps_per_side': 0.5, 'latency_bars': 1, 'round_turn_cost_bps': 3.4, 'provenance': 'ESTIMATED:declared_assumption'}
- splits: discovery/validation chronological; LOCKED partition untouched: True
- events: detected 3759, measured 7518, excluded (insufficient forward bars) 0, discarded-in-locked 1021
- trials recorded in ledger: 40 · ledger total (never reset): 180 · DSR penalized with N=180

## Results (primary horizon 12 bars, pooled discovery+validation)

| Family | n | cont. rate | baseline | diff | p_raw | p_holm | gross bps | net bps | net CI | TTT hit | MFE | MAE | DSR |
|--------|---|------------|----------|------|-------|--------|-----------|---------|--------|---------|-----|-----|-----|
| IMP-BE-B | 427 | 0.496 | 0.503 | -0.007 | 0.8089 | 1.0000 | +2.75 | -0.65 | [-7.69,6.14] | 0.51 | 25.5 | 22.8 | 0.002 |
| IMP-BE-V | 321 | 0.492 | 0.499 | -0.006 | 0.8236 | 1.0000 | +3.68 | +0.28 | [-7.81,8.88] | 0.53 | 27.5 | 24.2 | 0.004 |
| IMP-PV-B | 352 | 0.509 | 0.502 | +0.007 | 0.8312 | 1.0000 | +3.81 | +0.41 | [-7.20,7.95] | 0.43 | 24.9 | 24.9 | 0.004 |
| IMP-PV-V | 165 | 0.515 | 0.495 | +0.021 | 0.6406 | 1.0000 | +8.90 | +5.50 | [-5.45,17.06] | 0.44 | 27.5 | 29.4 | 0.036 |
| IMP-RB-B | 815 | 0.507 | 0.509 | -0.002 | 0.9163 | 1.0000 | +3.81 | +0.41 | [-3.65,4.45] | 0.50 | 22.4 | 19.7 | 0.005 |
| IMP-RB-V | 573 | 0.506 | 0.494 | +0.012 | 0.5589 | 1.0000 | +4.02 | +0.62 | [-4.66,5.70] | 0.49 | 23.3 | 21.2 | 0.006 |
| IMP-RE-B | 449 | 0.510 | 0.503 | +0.007 | 0.7771 | 1.0000 | +5.93 | +2.53 | [-3.73,8.40] | 0.47 | 23.5 | 22.1 | 0.026 |
| IMP-RE-V | 221 | 0.525 | 0.504 | +0.021 | 0.5454 | 1.0000 | +9.15 | +5.75 | [-2.90,14.63] | 0.43 | 24.7 | 26.9 | 0.070 |
| IMP-VE-B | 330 | 0.512 | 0.505 | +0.008 | 0.8258 | 1.0000 | +4.62 | +1.22 | [-6.09,8.80] | 0.49 | 24.9 | 22.4 | 0.008 |
| IMP-VE-V | 106 | 0.462 | 0.501 | -0.039 | 0.4384 | 1.0000 | +0.49 | -2.91 | [-15.89,10.38] | 0.46 | 26.6 | 26.2 | 0.001 |

## Cost / spread / latency sensitivity (pooled net mean bps, primary horizon)

| Family | cost 0.5x | 1x | 1.5x | 2x | spread 0.5x | 1x | 1.5x | 2x | latency 0 | 1 | 2 |
|--------|-----------|----|------|----|-------------|----|------|----|-----------|---|---|
| IMP-BE-B | +1.05 | -0.65 | -2.35 | -4.05 | +0.35 | -0.65 | -1.65 | -2.65 | -1.52 | -0.65 | -2.89 |
| IMP-BE-V | +1.98 | +0.28 | -1.42 | -3.12 | +1.28 | +0.28 | -0.72 | -1.72 | -1.41 | +0.28 | -3.29 |
| IMP-PV-B | +2.11 | +0.41 | -1.29 | -2.99 | +1.41 | +0.41 | -0.59 | -1.59 | -2.86 | +0.41 | -1.49 |
| IMP-PV-V | +7.20 | +5.50 | +3.80 | +2.10 | +6.50 | +5.50 | +4.50 | +3.50 | +2.15 | +5.50 | +3.17 |
| IMP-RB-B | +2.11 | +0.41 | -1.29 | -2.99 | +1.41 | +0.41 | -0.59 | -1.59 | -0.89 | +0.41 | -0.85 |
| IMP-RB-V | +2.32 | +0.62 | -1.08 | -2.78 | +1.62 | +0.62 | -0.38 | -1.38 | -0.87 | +0.62 | -0.57 |
| IMP-RE-B | +4.23 | +2.53 | +0.83 | -0.87 | +3.53 | +2.53 | +1.53 | +0.53 | +2.91 | +2.53 | +2.97 |
| IMP-RE-V | +7.45 | +5.75 | +4.05 | +2.35 | +6.75 | +5.75 | +4.75 | +3.75 | +5.05 | +5.75 | +6.86 |
| IMP-VE-B | +2.92 | +1.22 | -0.48 | -2.18 | +2.22 | +1.22 | +0.22 | -0.78 | +0.05 | +1.22 | +1.59 |
| IMP-VE-V | -1.21 | -2.91 | -4.61 | -6.31 | -1.91 | -2.91 | -3.91 | -4.91 | +2.90 | -2.91 | -8.78 |

## Conclusion
**REGIME_DEPENDENT** — research GO/BLOCK: **BLOCK**

- aggregate evidence is null/weak, but net expectancy is positive in exactly one causal volatility regime and non-positive in the others — any claim must be regime-conditional and requires out-of-sample confirmation per regime
- families referenced by the classifier: IMP-BE-B, IMP-RB-B, IMP-RE-B

Promotion: BLOCKED — research artifact only. Lifecycle state unchanged. Not connected to order submission. Demo success never implies live eligibility.

## Safety invariants
- live_trading_enabled: False
- live_eligibility_modified: False
- order_submission_connected: False
- promotion_state_modified: False
- locked_test_partition_accessed: False
- trial_ledger_reset: False
