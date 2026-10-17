# Long-history XAUUSD results — generated tables (LH-XAUUSD-W1-2026-10-17, stage final)

Verdict: **NO_VALIDATED_EDGE**. Claim: none

## Holdout 2020-01-01 → 2025-02-28 (selection frozen on data through 2019-12-31)

| Group | Selected | Net USD | Sharpe | 95% CI (Sharpe) | Max DD | Round turns | Win rate | Cost USD | Net @2x | Net @3x | Break-even cost x | Holm p | Exposure |
|---|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---|---:|---:|
| wk_ens | w_e132652_ls | 1,136.71 | 0.244 | [-0.58, 1.05] | -25.8% | 21 | 24% | 112.16 | 1,011.27 | 887.20 | 10.4931 (CROSSES_ZERO) | 0.47 | 99% |
| wk_trend | w_sma52_ls | 1,275.07 | 0.265 | [-0.49, 0.97] | -24.7% | 17 | 18% | 92.24 | 1,166.65 | 1,059.23 | 13.3972 (CROSSES_ZERO) | 0.47 | 99% |
| wk_longonly | w_sma52_lo | 2,980.61 | 0.562 | [-0.13, 1.23] | -13.2% | 9 | 33% | 55.97 | 2,910.54 | 2,840.84 | 48.8143 (CROSSES_ZERO) | 0.17 | 74% |
| **buy_and_hold_long (reference)** | 1.0x long | 8,911.48 | 0.880 | — | -19.1% | 1 | — | 8.16 | 8,903.33 | — | — | — | 100% |

## Walk-forward 2010–2019 (per-year selection, frozen within each year)

| Group | WF Sharpe | Positive years | Years traded | Chained return |
|---|---:|---:|---:|---:|
| wk_ens | 0.085 | 4/10 | 10 | 3.7% |
| wk_trend | 0.028 | 3/10 | 7 | -1.6% |
| wk_longonly | 0.351 | 4/10 | 10 | 25.3% |
| **buy_and_hold_long (reference)** | 0.274 | — | — | 34.1% |

## Gates (G1–G8; all must pass)

| Group | Candidate | G1 | G2 | G3 | G4 | G5 | G6 | G7 | G8 | DSR | OOS round turns | Passes |
|---|---|---|---|---|---|---|---|---|---|---:|---:|---|
| wk_ens | w_e132652_ls | PASS | PASS | FAIL | FAIL | FAIL | FAIL | FAIL | PASS | 0.015 | 86 | no |
| wk_trend | w_sma52_ls | PASS | PASS | FAIL | FAIL | FAIL | FAIL | PASS | PASS | 0.011 | 50 | no |
| wk_longonly | w_sma52_lo | PASS | PASS | FAIL | FAIL | FAIL | FAIL | FAIL | PASS | 0.144 | 39 | no |

## Regimes (out-of-sample net USD, WF 2010–2019 plus holdout)

| Group | UP_HIVOL | UP_LOWVOL | DOWN_HIVOL | DOWN_LOWVOL |
|---|---:|---:|---:|---:|
| wk_ens | 2,522.60 (164d) | 2,961.89 (332d) | -509.78 (57d) | -3,036.20 (235d) |
| wk_trend | 2,073.09 (123d) | 63.95 (234d) | 119.57 (57d) | -655.31 (221d) |
| wk_longonly | 1,399.23 (164d) | 5,845.10 (332d) | -279.06 (57d) | -1,339.07 (235d) |

## Replicate 2025-08-08 → 2026-09-11 (Dukascopy complete-day daily resampled W-FRI (UTC)) (frozen holdout selections, unchanged)

| Group | Candidate | Status | Net USD | Sharpe | Round turns |
|---|---|---|---:|---:|---:|
| wk_ens | w_e132652_ls | EVALUATED | 139.41 | 0.178 | 5 |
| wk_trend | w_sma52_ls | EVALUATED | 386.27 | 0.412 | 3 |
| wk_longonly | w_sma52_lo | EVALUATED | 641.35 | 0.687 | 2 |
| **buy_and_hold_long (reference)** | 1.0x long | EVALUATED | 2,790.02 | 1.063 | 1 |

## Sign-randomisation null (trade-level, approximate)

| Group | Trades | Observed net (approx.) | p-value |
|---|---:|---:|---:|
| wk_ens | 21 | 1,136.71 | 0.405 |
| wk_trend | 17 | 1,275.07 | 0.459 |
| wk_longonly | 9 | 2,980.61 | 0.279 |

