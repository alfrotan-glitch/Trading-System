# Long-history XAUUSD results — generated tables (LH-XAUUSD-ENS-2026-10-17, stage final)

Verdict: **NO_VALIDATED_EDGE**. Claim: none

## Holdout 2000-01-01 → 2026-09-30 (selection frozen on data through 1999-12-31)

| Group | Selected | Net USD | Sharpe | 95% CI (Sharpe) | Max DD | Round turns | Win rate | Cost USD | Net @2x | Net @3x | Break-even cost x | Holm p | Exposure |
|---|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---|---:|---:|
| ens_fast | e248_ls | 34,456.76 | 0.551 | [0.07, 1.01] | -35.4% | 61 | 34% | 823.15 | 32,840.64 | 31,282.59 | 40.9298 (CROSSES_ZERO) | 0.04 | 99% |
| ens_multi | e3612_ls | 32,582.55 | 0.539 | [0.02, 1.05] | -47.0% | 45 | 36% | 603.70 | 31,351.17 | 30,154.83 | 49.7927 (CROSSES_ZERO) | 0.04 | 98% |
| usd_conditioned | e248_usdagree | 11,420.59 | 0.366 | [-0.06, 0.81] | -43.6% | 45 | 49% | 502.48 | 10,858.07 | 10,310.09 | 29.4497 (CROSSES_ZERO) | 0.07 | 61% |
| long_only | ts9_lo | 70,988.62 | 0.837 | [0.32, 1.30] | -31.0% | 16 | 50% | 269.69 | 70,164.54 | 69,348.52 | 50.0 (POSITIVE_AT_50X) | 0.01 | 72% |
| **buy_and_hold_long (reference)** | 1.0x long | 142,032.02 | 0.850 | — | -39.3% | 1 | — | 45.45 | 141,986.57 | — | — | — | 100% |

## Walk-forward 1990–1999 (per-year selection, frozen within each year)

| Group | WF Sharpe | Positive years | Years traded | Chained return |
|---|---:|---:|---:|---:|
| ens_fast | -0.364 | 2/10 | 10 | -32.8% |
| ens_multi | -0.385 | 2/10 | 10 | -34.1% |
| usd_conditioned | -0.197 | 3/10 | 10 | -14.7% |
| long_only | -0.833 | 0/10 | 5 | -11.5% |
| **buy_and_hold_long (reference)** | -0.282 | — | — | -29.0% |

## Gates (G1–G9; all must pass)

| Group | Candidate | G1 | G2 | G3 | G4 | G5 | G6 | G7 | G8 | G9 | DSR | OOS round turns | Passes |
|---|---|---|---|---|---|---|---|---|---|---|---:|---:|---|
| ens_fast | e248_ls | PASS | PASS | FAIL | PASS | FAIL | PASS | PASS | PASS | PASS | 0.247 | 100 | no |
| ens_multi | e3612_ls | PASS | PASS | FAIL | PASS | FAIL | FAIL | PASS | PASS | PASS | 0.220 | 72 | no |
| usd_conditioned | e248_usdagree | PASS | PASS | FAIL | FAIL | FAIL | FAIL | FAIL | PASS | PASS | 0.104 | 76 | no |
| long_only | ts9_lo | PASS | PASS | FAIL | PASS | FAIL | FAIL | FAIL | PASS | PASS | 0.929 | 26 | no |

## Regimes (out-of-sample net USD, WF 1990–1999 plus holdout)

| Group | UP_HIVOL | UP_LOWVOL | DOWN_HIVOL | DOWN_LOWVOL |
|---|---:|---:|---:|---:|
| ens_fast | 4,321.29 (92d) | 29,124.12 (194d) | -6,919.89 (27d) | 4,460.85 (128d) |
| ens_multi | 1,945.19 (92d) | 31,887.41 (194d) | -9,626.90 (27d) | 4,675.90 (128d) |
| usd_conditioned | -834.06 (92d) | 10,066.39 (194d) | -4,592.54 (27d) | 5,626.21 (128d) |
| long_only | 14,144.82 (92d) | 60,690.83 (186d) | -773.92 (26d) | -4,272.01 (89d) |

## Replicate 2004-06-30 → 2025-02-28 (BaseMax monthly OHLC aggregated from 15m bars (next-open fills)) (frozen holdout selections, unchanged)

| Group | Candidate | Status | Net USD | Sharpe | Round turns |
|---|---|---|---:|---:|---:|
| ens_fast | e248_ls | EVALUATED | 26,835.69 | 0.620 | 44 |
| ens_multi | e3612_ls | EVALUATED | 18,770.89 | 0.510 | 42 |
| usd_conditioned | e248_usdagree | EVALUATED | 7,840.78 | 0.360 | 35 |
| long_only | ts9_lo | EVALUATED | 21,524.01 | 0.641 | 18 |
| **buy_and_hold_long (reference)** | 1.0x long | EVALUATED | 62,577.62 | 0.664 | 1 |

## Sign-randomisation null (trade-level, approximate)

| Group | Trades | Observed net (approx.) | p-value |
|---|---:|---:|---:|
| ens_fast | 61 | 34,456.76 | 0.110 |
| ens_multi | 45 | 32,582.55 | 0.137 |
| usd_conditioned | 45 | 11,420.59 | 0.125 |
| long_only | 16 | 70,988.62 | 0.042 |

