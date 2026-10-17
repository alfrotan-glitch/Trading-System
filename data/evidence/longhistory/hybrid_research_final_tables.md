# Long-history XAUUSD results — generated tables (LH-XAUUSD-HYB-2026-10-17, stage final)

Verdict: **NO_VALIDATED_EDGE**. Claim: none

## Holdout 2000-01-01 → 2026-09-30 (selection frozen on data through 1999-12-31)

| Group | Selected | Net USD | Sharpe | 95% CI (Sharpe) | Max DD | Round turns | Win rate | Cost USD | Net @2x | Net @3x | Break-even cost x | Holm p | Exposure |
|---|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---|---:|---:|
| hyb_veto | veto9 | 49,896.83 | 0.662 | [0.15, 1.15] | -36.0% | 26 | 38% | 368.12 | 48,915.86 | 47,950.61 | 50.0 (POSITIVE_AT_50X) | 0.01 | 93% |
| hyb_agree | agree9 | 12,962.65 | 0.393 | [-0.03, 0.86] | -37.7% | 31 | 52% | 343.14 | 12,543.50 | 12,131.83 | 45.7083 (CROSSES_ZERO) | 0.05 | 67% |
| hyb_lo | ts9_lo | 70,988.62 | 0.837 | [0.32, 1.30] | -31.0% | 16 | 50% | 269.69 | 70,164.54 | 69,348.52 | 50.0 (POSITIVE_AT_50X) | 0.01 | 72% |
| **buy_and_hold_long (reference)** | 1.0x long | 142,032.02 | 0.850 | — | -39.3% | 1 | — | 45.45 | 141,986.57 | — | — | — | 100% |

## Walk-forward 1990–1999 (per-year selection, frozen within each year)

| Group | WF Sharpe | Positive years | Years traded | Chained return |
|---|---:|---:|---:|---:|
| hyb_veto | 0.278 | 4/10 | 8 | 14.7% |
| hyb_agree | 0.277 | 5/10 | 10 | 15.1% |
| hyb_lo | 0.000 | 0/10 | 0 | 0.0% |
| **buy_and_hold_long (reference)** | -0.282 | — | — | -29.0% |

## Gates (G1–G9; all must pass)

| Group | Candidate | G1 | G2 | G3 | G4 | G5 | G6 | G7 | G8 | G9 | DSR | OOS round turns | Passes |
|---|---|---|---|---|---|---|---|---|---|---|---:|---:|---|
| hyb_veto | veto9 | PASS | PASS | FAIL | PASS | FAIL | FAIL | PASS | PASS | PASS | 0.752 | 45 | no |
| hyb_agree | agree9 | PASS | PASS | FAIL | FAIL | FAIL | FAIL | FAIL | PASS | PASS | 0.264 | 52 | no |
| hyb_lo | ts9_lo | PASS | PASS | FAIL | PASS | FAIL | FAIL | FAIL | PASS | PASS | 0.945 | 16 | no |

## Regimes (out-of-sample net USD, WF 1990–1999 plus holdout)

| Group | UP_HIVOL | UP_LOWVOL | DOWN_HIVOL | DOWN_LOWVOL |
|---|---:|---:|---:|---:|
| hyb_veto | 5,934.31 (92d) | 45,904.71 (194d) | -6,644.77 (26d) | 6,345.98 (105d) |
| hyb_agree | -1,249.38 (92d) | 13,100.53 (194d) | -4,635.44 (27d) | 7,467.43 (128d) |
| hyb_lo | 14,144.82 (92d) | 61,204.75 (157d) | -583.09 (23d) | -3,777.86 (49d) |

## Replicate 2004-06-30 → 2025-02-28 (BaseMax monthly OHLC aggregated from 15m bars (next-open fills)) (frozen holdout selections, unchanged)

| Group | Candidate | Status | Net USD | Sharpe | Round turns |
|---|---|---|---:|---:|---:|
| hyb_veto | veto9 | EVALUATED | 15,134.78 | 0.461 | 32 |
| hyb_agree | agree9 | EVALUATED | 3,435.08 | 0.201 | 32 |
| hyb_lo | ts9_lo | EVALUATED | 21,524.01 | 0.641 | 18 |
| **buy_and_hold_long (reference)** | 1.0x long | EVALUATED | 62,577.62 | 0.664 | 1 |

## Sign-randomisation null (trade-level, approximate)

| Group | Trades | Observed net (approx.) | p-value |
|---|---:|---:|---:|
| hyb_veto | 26 | 49,896.83 | 0.084 |
| hyb_agree | 31 | 12,962.65 | 0.084 |
| hyb_lo | 16 | 70,988.62 | 0.042 |

