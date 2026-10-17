# Long-history XAUUSD results — generated tables (LH-XAUUSD-VOLM-2026-10-17, stage final)

Verdict: **NO_VALIDATED_EDGE**. Claim: none

## Holdout 2000-01-01 → 2026-09-30 (selection frozen on data through 1999-12-31)

| Group | Selected | Net USD | Sharpe | 95% CI (Sharpe) | Max DD | Round turns | Win rate | Cost USD | Net @2x | Net @3x | Break-even cost x | Holm p | Exposure |
|---|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---|---:|---:|
| vm_veto | veto9_fv3 | 43,487.20 | 0.624 | [0.10, 1.14] | -38.0% | 26 | 38% | 537.27 | 42,135.00 | 40,816.49 | 50.0 (POSITIVE_AT_50X) | 0.01 | 93% |
| vm_lo | lo9_fv3 | 65,083.53 | 0.811 | [0.28, 1.29] | -30.8% | 16 | 50% | 444.43 | 63,784.85 | 62,508.11 | 50.0 (POSITIVE_AT_50X) | 0.01 | 72% |
| **buy_and_hold_long (reference)** | 1.0x long | 142,032.02 | 0.850 | — | -39.3% | 1 | — | 45.45 | 141,986.57 | — | — | — | 100% |

## Walk-forward 1990–1999 (per-year selection, frozen within each year)

| Group | WF Sharpe | Positive years | Years traded | Chained return |
|---|---:|---:|---:|---:|
| vm_veto | 0.251 | 4/10 | 8 | 12.7% |
| vm_lo | 0.000 | 0/10 | 0 | 0.0% |
| **buy_and_hold_long (reference)** | -0.282 | — | — | -29.0% |

## Gates (G1–G9; all must pass)

| Group | Candidate | G1 | G2 | G3 | G4 | G5 | G6 | G7 | G8 | G9 | DSR | OOS round turns | Passes |
|---|---|---|---|---|---|---|---|---|---|---|---:|---:|---|
| vm_veto | veto9_fv3 | PASS | PASS | FAIL | PASS | FAIL | FAIL | PASS | PASS | PASS | 0.657 | 45 | no |
| vm_lo | lo9_fv3 | PASS | PASS | FAIL | PASS | FAIL | FAIL | FAIL | PASS | PASS | 0.917 | 16 | no |

## Regimes (out-of-sample net USD, WF 1990–1999 plus holdout)

| Group | UP_HIVOL | UP_LOWVOL | DOWN_HIVOL | DOWN_LOWVOL |
|---|---:|---:|---:|---:|
| vm_veto | 2,875.73 (92d) | 41,386.81 (194d) | -5,595.05 (26d) | 6,326.30 (105d) |
| vm_lo | 11,919.63 (92d) | 57,206.59 (157d) | -1,352.88 (23d) | -2,689.81 (49d) |

## Replicate 2004-06-30 → 2025-02-28 (BaseMax monthly OHLC aggregated from 15m bars (next-open fills)) (frozen holdout selections, unchanged)

| Group | Candidate | Status | Net USD | Sharpe | Round turns |
|---|---|---|---:|---:|---:|
| vm_veto | veto9_fv3 | EVALUATED | 13,142.40 | 0.397 | 32 |
| vm_lo | lo9_fv3 | EVALUATED | 20,378.90 | 0.577 | 18 |
| **buy_and_hold_long (reference)** | 1.0x long | EVALUATED | 62,577.62 | 0.664 | 1 |

## Sign-randomisation null (trade-level, approximate)

| Group | Trades | Observed net (approx.) | p-value |
|---|---:|---:|---:|
| vm_veto | 26 | 43,487.20 | 0.102 |
| vm_lo | 16 | 65,083.53 | 0.050 |

