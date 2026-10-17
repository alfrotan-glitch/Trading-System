# Long-history XAUUSD results — generated tables (LH-XAUUSD-WHYB-2026-10-17, stage final)

Verdict: **NO_VALIDATED_EDGE**. Claim: none

## Holdout 2020-01-01 → 2025-02-28 (selection frozen on data through 2019-12-31)

| Group | Selected | Net USD | Sharpe | 95% CI (Sharpe) | Max DD | Round turns | Win rate | Cost USD | Net @2x | Net @3x | Break-even cost x | Holm p | Exposure |
|---|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---|---:|---:|
| wh_veto | wv_2652 | 1,098.68 | 0.264 | [-0.50, 1.01] | -21.3% | 17 | 18% | 80.15 | 1,006.26 | 914.60 | 13.4481 (CROSSES_ZERO) | 0.25 | 74% |
| wh_lo | wl_2652 | 1,960.90 | 0.442 | [-0.27, 1.15] | -15.2% | 9 | 22% | 45.79 | 1,905.89 | 1,851.12 | 39.6545 (CROSSES_ZERO) | 0.24 | 64% |
| **buy_and_hold_long (reference)** | 1.0x long | 8,911.48 | 0.880 | — | -19.1% | 1 | — | 8.16 | 8,903.33 | — | — | — | 100% |

## Walk-forward 2010–2019 (per-year selection, frozen within each year)

| Group | WF Sharpe | Positive years | Years traded | Chained return |
|---|---:|---:|---:|---:|
| wh_veto | 0.059 | 3/10 | 7 | 0.9% |
| wh_lo | 0.255 | 2/10 | 4 | 6.6% |
| **buy_and_hold_long (reference)** | 0.274 | — | — | 34.1% |

## Gates (G1–G8; all must pass)

| Group | Candidate | G1 | G2 | G3 | G4 | G5 | G6 | G7 | G8 | DSR | OOS round turns | Passes |
|---|---|---|---|---|---|---|---|---|---|---:|---:|---|
| wh_veto | wv_2652 | PASS | PASS | FAIL | FAIL | FAIL | FAIL | PASS | PASS | 0.009 | 55 | no |
| wh_lo | wl_2652 | PASS | PASS | FAIL | FAIL | FAIL | FAIL | PASS | PASS | 0.042 | 21 | no |

## Regimes (out-of-sample net USD, WF 2010–2019 plus holdout)

| Group | UP_HIVOL | UP_LOWVOL | DOWN_HIVOL | DOWN_LOWVOL |
|---|---:|---:|---:|---:|
| wh_veto | 948.42 (123d) | 1,036.48 (234d) | 223.37 (57d) | -598.58 (221d) |
| wh_lo | 1,565.90 (123d) | 1,856.58 (223d) | 7.33 (10d) | -704.98 (123d) |

## Replicate 2025-08-08 → 2026-09-11 (Dukascopy complete-day daily resampled W-FRI + same USD index) (frozen holdout selections, unchanged)

| Group | Candidate | Status | Net USD | Sharpe | Round turns |
|---|---|---|---:|---:|---:|
| wh_veto | wv_2652 | EVALUATED | 761.98 | 0.836 | 1 |
| wh_lo | wl_2652 | EVALUATED | 761.98 | 0.836 | 1 |
| **buy_and_hold_long (reference)** | 1.0x long | EVALUATED | 2,790.02 | 1.063 | 1 |

## Sign-randomisation null (trade-level, approximate)

| Group | Trades | Observed net (approx.) | p-value |
|---|---:|---:|---:|
| wh_veto | 17 | 1,098.68 | 0.447 |
| wh_lo | 9 | 1,960.90 | 0.391 |

