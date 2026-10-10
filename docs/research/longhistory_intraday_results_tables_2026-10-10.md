# Long-history XAUUSD results — generated tables (LH-XAUUSD-M15-2026-10-10, stage final)

Verdict: **NO_VALIDATED_EDGE**. Claim: none

## Holdout 2020-01-01 → 2025-02-28 (selection frozen on data through 2019-12-31)

| Group | Selected | Net USD | Sharpe | 95% CI (Sharpe) | Max DD | Round turns | Win rate | Cost USD | Net @2x | Net @3x | Break-even cost x | Holm p | Exposure |
|---|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---|---:|---:|
| ma_cross | ma_32_128_atr3 | 1,092.55 | 0.214 | [-0.63, 1.02] | -31.6% | 1154 | 27% | 7,562.02 | -4,265.81 | -7,036.33 | 1.1572 (CROSSES_ZERO) | 1.00 | 79% |
| donchian | donchian_384_192_atr3 | 288.09 | 0.104 | [-0.77, 0.95] | -16.8% | 231 | 22% | 1,438.60 | -983.49 | -2,098.20 | 1.2153 (CROSSES_ZERO) | 1.00 | 33% |
| volatility_expansion | rexp_k10_h16 | -9,938.70 | -7.142 | [-8.14, -6.23] | -99.4% | 8162 | 30% | 7,769.98 | -9,999.43 | -9,999.99 | 0.0 (NEGATIVE_EVEN_AT_ZERO_COST) | 1.00 | 66% |
| session_breakout | session_brk_b0 | -4,467.03 | -1.127 | [-1.99, -0.27] | -53.9% | 1265 | 39% | 5,583.78 | -7,272.83 | -8,656.06 | 0.1632 (CROSSES_ZERO) | 1.00 | 31% |
| **buy_and_hold_long (reference)** | 1.0x long | 8,795.66 | 0.860 | — | -21.9% | 1 | — | 8.12 | 8,784.94 | — | — | — | 100% |

## Walk-forward 2010–2019 (per-year selection, frozen within each year)

| Group | WF Sharpe | Positive years | Years traded | Chained return |
|---|---:|---:|---:|---:|
| ma_cross | -0.717 | 2/10 | 10 | -53.6% |
| donchian | -0.247 | 4/10 | 10 | -22.4% |
| volatility_expansion | -6.727 | 0/10 | 10 | -100.0% |
| session_breakout | -1.030 | 2/10 | 10 | -63.0% |
| **buy_and_hold_long (reference)** | 0.272 | — | — | 34.4% |

## Gates (G1–G7; all must pass)

| Group | Candidate | G1 | G2 | G3 | G4 | G5 | G6 | G7 | DSR | OOS round turns | Passes |
|---|---|---|---|---|---|---|---|---|---:|---:|---|
| ma_cross | ma_32_128_atr3 | PASS | FAIL | FAIL | FAIL | FAIL | PASS | FAIL | 0.000 | 3379 | no |
| donchian | donchian_384_192_atr3 | PASS | FAIL | FAIL | FAIL | FAIL | PASS | FAIL | 0.004 | 687 | no |
| volatility_expansion | rexp_k10_h16 | FAIL | FAIL | FAIL | FAIL | FAIL | PASS | FAIL | 0.000 | 23099 | no |
| session_breakout | session_brk_b0 | FAIL | FAIL | FAIL | FAIL | FAIL | PASS | FAIL | 0.000 | 3638 | no |

## Regimes (out-of-sample net USD, WF 2010–2019 plus holdout)

| Group | UP_HIVOL | UP_LOWVOL | DOWN_HIVOL | DOWN_LOWVOL |
|---|---:|---:|---:|---:|
| ma_cross | 2,126.88 (58266d) | -3,802.38 (162328d) | -1,020.43 (22830d) | -2,976.73 (108456d) |
| donchian | -1,608.43 (58266d) | 1,492.71 (162328d) | -1,672.56 (22830d) | -252.34 (108456d) |
| volatility_expansion | -12,002.23 (58266d) | -32,190.03 (162328d) | -3,780.97 (22830d) | -21,074.79 (108456d) |
| session_breakout | -824.92 (58266d) | -9,445.46 (162328d) | -517.80 (22830d) | -2,596.03 (108456d) |

## Dukascopy replicate 2025-08-06 → 2026-09-16 (frozen holdout selections, unchanged)

| Group | Candidate | Status | Net USD | Sharpe | Round turns |
|---|---|---|---:|---:|---:|
| ma_cross | ma_32_128_atr3 | EVALUATED | 2,499.33 | 1.011 | 263 |
| donchian | donchian_384_192_atr3 | EVALUATED | 3,935.03 | 1.687 | 47 |
| volatility_expansion | rexp_k10_h16 | EVALUATED | -6,977.02 | -4.864 | 1750 |
| session_breakout | session_brk_b0 | EVALUATED | -82.07 | -0.011 | 246 |
| **buy_and_hold_long (reference)** | 1.0x long | EVALUATED | 2,596.43 | 0.881 | 1 |

## Sign-randomisation null (trade-level, approximate)

| Group | Trades | Observed net (approx.) | p-value |
|---|---:|---:|---:|
| ma_cross | 1154 | 1,092.55 | 0.007 |
| donchian | 231 | 288.09 | 0.229 |
| volatility_expansion | 8162 | -9,938.70 | 0.982 |
| session_breakout | 1265 | -4,467.03 | 0.270 |

