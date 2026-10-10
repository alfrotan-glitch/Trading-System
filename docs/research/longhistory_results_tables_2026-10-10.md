# Long-history XAUUSD results — generated tables (LH-XAUUSD-D1-2026-10-10, stage final)

Verdict: **NO_VALIDATED_EDGE**. Claim: none

## Holdout 2020-01-01 → 2025-02-28 (selection frozen on data through 2019-12-31)

| Group | Selected | Net USD | Sharpe | 95% CI (Sharpe) | Max DD | Round turns | Win rate | Cost USD | Net @2x | Net @3x | Break-even cost x | Holm p | Exposure |
|---|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---|---:|---:|
| tsmom | tsmom_L126 | -378.57 | -0.011 | [-0.81, 0.86] | -36.9% | 13 | 15% | 66.78 | -447.81 | -516.56 | 0.0 (NEGATIVE_EVEN_AT_ZERO_COST) | 1.00 | 98% |
| ma_cross | ma_20_100_atr3 | 530.11 | 0.299 | [-0.55, 1.16] | -8.6% | 14 | 29% | 21.93 | 506.15 | 482.25 | 23.6561 (CROSSES_ZERO) | 1.00 | 75% |
| donchian | donchian_55_20_atr2 | 160.22 | 0.087 | [-0.75, 0.93] | -10.1% | 19 | 37% | 41.69 | 117.38 | 74.72 | 4.7614 (CROSSES_ZERO) | 1.00 | 49% |
| volatility_expansion | rexp_k10_h3 | 673.05 | 0.387 | [-0.49, 1.24] | -5.5% | 134 | 53% | 289.58 | 381.23 | 97.36 | 3.3494 (CROSSES_ZERO) | 1.00 | 35% |
| trend_gated | gated_er60_025 | -319.98 | -0.276 | [-0.96, 0.49] | -6.2% | 9 | 22% | 13.33 | -333.21 | -346.42 | 0.0 (NEGATIVE_EVEN_AT_ZERO_COST) | 1.00 | 16% |
| mean_reversion | rsi2_t10_sma200 | -841.32 | -0.397 | [-1.07, 0.39] | -15.8% | 47 | 53% | 175.17 | -1,009.83 | -1,175.27 | 0.0 (NEGATIVE_EVEN_AT_ZERO_COST) | 1.00 | 13% |
| **buy_and_hold_long (reference)** | 1.0x long | 8,795.66 | 0.865 | — | -21.4% | 1 | — | 8.12 | 8,784.94 | — | — | — | 100% |

## Walk-forward 2010–2019 (per-year selection, frozen within each year)

| Group | WF Sharpe | Positive years | Years traded | Chained return |
|---|---:|---:|---:|---:|
| tsmom | -0.071 | 3/10 | 9 | -10.9% |
| ma_cross | 0.168 | 6/10 | 10 | 5.9% |
| donchian | 0.142 | 5/10 | 10 | 5.7% |
| volatility_expansion | 0.013 | 5/10 | 10 | -0.1% |
| trend_gated | 0.536 | 2/10 | 2 | 2.8% |
| mean_reversion | -0.333 | 5/10 | 10 | -11.2% |
| **buy_and_hold_long (reference)** | 0.270 | — | — | 34.4% |

## Gates (G1–G7; all must pass)

| Group | Candidate | G1 | G2 | G3 | G4 | G5 | G6 | G7 | DSR | OOS round turns | Passes |
|---|---|---|---|---|---|---|---|---|---:|---:|---|
| tsmom | tsmom_L126 | FAIL | FAIL | FAIL | FAIL | FAIL | FAIL | FAIL | 0.014 | 47 | no |
| ma_cross | ma_20_100_atr3 | PASS | PASS | PASS | FAIL | FAIL | FAIL | PASS | 0.117 | 61 | no |
| donchian | donchian_55_20_atr2 | PASS | PASS | FAIL | FAIL | FAIL | FAIL | FAIL | 0.062 | 69 | no |
| volatility_expansion | rexp_k10_h3 | PASS | PASS | FAIL | FAIL | FAIL | PASS | PASS | 0.073 | 375 | no |
| trend_gated | gated_er60_025 | FAIL | FAIL | FAIL | FAIL | FAIL | FAIL | FAIL | 0.019 | 12 | no |
| mean_reversion | rsi2_t10_sma200 | FAIL | FAIL | FAIL | FAIL | FAIL | PASS | FAIL | 0.000 | 133 | no |

## Regimes (out-of-sample net USD, WF 2010–2019 plus holdout)

| Group | UP_HIVOL | UP_LOWVOL | DOWN_HIVOL | DOWN_LOWVOL |
|---|---:|---:|---:|---:|
| tsmom | -225.68 (929d) | 3,587.14 (1232d) | -796.80 (296d) | -3,199.58 (1170d) |
| ma_cross | 177.52 (987d) | 982.45 (1420d) | -394.81 (296d) | 388.74 (1170d) |
| donchian | -1,717.45 (987d) | 2,289.86 (1420d) | -142.84 (296d) | 363.70 (1170d) |
| volatility_expansion | -828.17 (987d) | 1,330.26 (1420d) | 134.12 (296d) | 51.73 (1170d) |
| trend_gated | -509.27 (608d) | 571.28 (714d) | -53.24 (59d) | -49.81 (468d) |
| mean_reversion | 332.45 (987d) | -1,142.46 (1420d) | -428.82 (296d) | -713.00 (1170d) |

## Dukascopy replicate 2025-08-06 → 2026-09-16 (frozen holdout selections, unchanged)

| Group | Candidate | Status | Net USD | Sharpe | Round turns |
|---|---|---|---:|---:|---:|
| tsmom | tsmom_L126 | NOT_EVALUABLE_INSUFFICIENT_WARMUP | — | — | — |
| ma_cross | ma_20_100_atr3 | NOT_EVALUABLE_INSUFFICIENT_WARMUP | — | — | — |
| donchian | donchian_55_20_atr2 | EVALUATED | -296.65 | -1.331 | 3 |
| volatility_expansion | rexp_k10_h3 | EVALUATED | 335.17 | 0.698 | 26 |
| trend_gated | gated_er60_025 | EVALUATED | -158.67 | -0.947 | 2 |
| mean_reversion | rsi2_t10_sma200 | EVALUATED | 15.54 | 0.093 | 4 |
| **buy_and_hold_long (reference)** | 1.0x long | EVALUATED | 2,647.22 | 0.899 | 1 |

## Sign-randomisation null (trade-level, approximate)

| Group | Trades | Observed net (approx.) | p-value |
|---|---:|---:|---:|
| tsmom | 13 | -378.57 | 0.528 |
| ma_cross | 14 | 530.11 | 0.460 |
| donchian | 19 | 160.22 | 0.374 |
| volatility_expansion | 134 | 673.05 | 0.109 |
| trend_gated | 9 | -319.98 | 0.839 |
| mean_reversion | 47 | -841.32 | 0.766 |

