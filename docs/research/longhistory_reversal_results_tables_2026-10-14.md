# Long-history XAUUSD results — generated tables (LH-XAUUSD-M15-REV-2026-10-14, stage final)

Verdict: **NO_VALIDATED_EDGE**. Claim: none

## Holdout 2020-01-01 → 2025-02-28 (selection frozen on data through 2019-12-31)

| Group | Selected | Net USD | Sharpe | 95% CI (Sharpe) | Max DD | Round turns | Win rate | Cost USD | Net @2x | Net @3x | Break-even cost x | Holm p | Exposure |
|---|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---|---:|---:|
| impulse_fade | fade_k20_h16 | -6,237.32 | -2.699 | [-3.53, -1.78] | -63.1% | 1711 | 39% | 6,109.07 | -8,586.60 | -9,469.23 | 0.0014 (CROSSES_ZERO) | 1.00 | 12% |
| **buy_and_hold_long (reference)** | 1.0x long | 8,795.66 | 0.860 | — | -21.9% | 1 | — | 8.12 | 8,784.94 | — | — | — | 100% |

## Walk-forward 2010–2019 (per-year selection, frozen within each year)

| Group | WF Sharpe | Positive years | Years traded | Chained return |
|---|---:|---:|---:|---:|
| impulse_fade | -3.029 | 0/10 | 10 | -88.6% |
| **buy_and_hold_long (reference)** | 0.272 | — | — | 34.4% |

## Gates (G1–G8; all must pass)

| Group | Candidate | G1 | G2 | G3 | G4 | G5 | G6 | G7 | G8 | DSR | OOS round turns | Passes |
|---|---|---|---|---|---|---|---|---|---|---:|---:|---|
| impulse_fade | fade_k20_h16 | FAIL | FAIL | FAIL | FAIL | FAIL | PASS | FAIL | FAIL | 0.000 | 5373 | no |

## Regimes (out-of-sample net USD, WF 2010–2019 plus holdout)

| Group | UP_HIVOL | UP_LOWVOL | DOWN_HIVOL | DOWN_LOWVOL |
|---|---:|---:|---:|---:|
| impulse_fade | -3,908.59 (58266d) | -11,569.85 (162328d) | -2,381.37 (22830d) | -7,806.78 (108456d) |

## Dukascopy replicate 2025-08-06 → 2026-09-16 (frozen holdout selections, unchanged)

| Group | Candidate | Status | Net USD | Sharpe | Round turns |
|---|---|---|---:|---:|---:|
| impulse_fade | fade_k20_h16 | EVALUATED | -1,953.63 | -1.861 | 348 |
| **buy_and_hold_long (reference)** | 1.0x long | EVALUATED | 2,596.43 | 0.881 | 1 |

## Sign-randomisation null (trade-level, approximate)

| Group | Trades | Observed net (approx.) | p-value |
|---|---:|---:|---:|
| impulse_fade | 1711 | -6,237.32 | 0.553 |

