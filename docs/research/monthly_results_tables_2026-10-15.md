# Long-history XAUUSD results — generated tables (LH-XAUUSD-MON-2026-10-15, stage final)

Verdict: **NO_VALIDATED_EDGE**. Claim: none

## Holdout 2000-01-01 → 2026-09-30 (selection frozen on data through 1999-12-31)

| Group | Selected | Net USD | Sharpe | 95% CI (Sharpe) | Max DD | Round turns | Win rate | Cost USD | Net @2x | Net @3x | Break-even cost x | Holm p | Exposure |
|---|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---|---:|---:|
| gold_trend | m_tsmom_12 | 57,815.63 | 0.696 | [0.21, 1.21] | -34.8% | 40 | 48% | 671.71 | 56,299.34 | 54,816.46 | 50.0 (POSITIVE_AT_50X) | 0.01 | 99% |
| usd_veto | m_usdveto_6_12 | 42,208.97 | 0.617 | [0.09, 1.14] | -38.4% | 36 | 39% | 500.25 | 41,028.36 | 39,873.96 | 50.0 (POSITIVE_AT_50X) | 0.02 | 90% |
| usd_agreement | m_agree_12_12 | 16,217.42 | 0.436 | [0.00, 0.91] | -44.3% | 38 | 53% | 474.73 | 15,655.08 | 15,104.61 | 45.0969 (CROSSES_ZERO) | 0.04 | 70% |
| **buy_and_hold_long (reference)** | 1.0x long | 142,032.02 | 0.850 | — | -39.3% | 1 | — | 45.45 | 141,986.57 | — | — | — | 100% |

## Walk-forward 1990–1999 (per-year selection, frozen within each year)

| Group | WF Sharpe | Positive years | Years traded | Chained return |
|---|---:|---:|---:|---:|
| gold_trend | -0.145 | 2/10 | 9 | -15.3% |
| usd_veto | 0.130 | 4/10 | 9 | 6.0% |
| usd_agreement | 0.154 | 5/10 | 10 | 7.5% |
| **buy_and_hold_long (reference)** | -0.282 | — | — | -29.0% |

## Gates (G1–G9; all must pass)

| Group | Candidate | G1 | G2 | G3 | G4 | G5 | G6 | G7 | G8 | G9 | DSR | OOS round turns | Passes |
|---|---|---|---|---|---|---|---|---|---|---|---:|---:|---|
| gold_trend | m_tsmom_12 | PASS | PASS | FAIL | PASS | FAIL | FAIL | PASS | PASS | PASS | 0.726 | 64 | no |
| usd_veto | m_usdveto_6_12 | PASS | PASS | FAIL | PASS | FAIL | FAIL | PASS | PASS | PASS | 0.769 | 57 | no |
| usd_agreement | m_agree_12_12 | PASS | PASS | FAIL | PASS | FAIL | FAIL | PASS | PASS | PASS | 0.444 | 59 | no |

## Regimes (out-of-sample net USD, WF 1990–1999 plus holdout)

| Group | UP_HIVOL | UP_LOWVOL | DOWN_HIVOL | DOWN_LOWVOL |
|---|---:|---:|---:|---:|
| gold_trend | 11,707.33 (92d) | 46,787.46 (194d) | -9,817.00 (26d) | 7,759.93 (117d) |
| usd_veto | 4,960.26 (92d) | 42,333.66 (194d) | -8,469.31 (26d) | 4,223.99 (117d) |
| usd_agreement | 838.06 (92d) | 14,155.64 (194d) | -5,306.67 (27d) | 7,553.76 (128d) |

## Replicate 2004-06-30 → 2025-02-28 (BaseMax XAUUSD 15m aggregated to monthly OHLC (UTC)) (frozen holdout selections, unchanged)

| Group | Candidate | Status | Net USD | Sharpe | Round turns |
|---|---|---|---:|---:|---:|
| gold_trend | m_tsmom_12 | EVALUATED | 19,697.05 | 0.525 | 33 |
| usd_veto | m_usdveto_6_12 | EVALUATED | 24,596.39 | 0.627 | 36 |
| usd_agreement | m_agree_12_12 | EVALUATED | 5,847.55 | 0.284 | 31 |
| **buy_and_hold_long (reference)** | 1.0x long | EVALUATED | 62,577.62 | 0.664 | 1 |

## Sign-randomisation null (trade-level, approximate)

| Group | Trades | Observed net (approx.) | p-value |
|---|---:|---:|---:|
| gold_trend | 40 | 57,815.63 | 0.096 |
| usd_veto | 36 | 42,208.97 | 0.106 |
| usd_agreement | 38 | 16,217.42 | 0.100 |

