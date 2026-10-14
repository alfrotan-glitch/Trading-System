# Long-history XAUUSD results — generated tables (LH-XAUUSD-SES-2026-10-14, stage final)

Verdict: **NO_VALIDATED_EDGE**. Claim: none

## Holdout 2020-01-01 → 2025-02-28 (selection frozen on data through 2019-12-31)

| Group | Selected | Net USD | Sharpe | 95% CI (Sharpe) | Max DD | Round turns | Win rate | Cost USD | Net @2x | Net @3x | Break-even cost x | Holm p | Exposure |
|---|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---|---:|---:|
| session_drift | sd_all | -3,295.94 | -1.723 | [-2.58, -0.90] | -35.4% | 1332 | 45% | 4,292.97 | -6,065.32 | -7,690.95 | 0.2495 (CROSSES_ZERO) | 1.00 | 31% |
| weekday_drift | wd_all | 853.11 | 0.334 | [-0.57, 1.14] | -8.5% | 275 | 53% | 1,164.40 | -281.61 | -1,297.89 | 1.7414 (CROSSES_ZERO) | 0.46 | 21% |
| **buy_and_hold_long (reference)** | 1.0x long | 8,795.66 | 0.860 | — | -21.9% | 1 | — | 8.12 | 8,784.94 | — | — | — | 100% |

## Walk-forward 2010–2019 (per-year selection, frozen within each year)

| Group | WF Sharpe | Positive years | Years traded | Chained return |
|---|---:|---:|---:|---:|
| session_drift | -2.004 | 0/10 | 10 | -57.3% |
| weekday_drift | 0.229 | 5/10 | 10 | 11.3% |
| nfp_drift | 0.000 | 0/10 | 0 | 0.0% |
| **buy_and_hold_long (reference)** | 0.272 | — | — | 34.4% |

## Gates (G1–G8; all must pass)

| Group | Candidate | G1 | G2 | G3 | G4 | G5 | G6 | G7 | G8 | DSR | OOS round turns | Passes |
|---|---|---|---|---|---|---|---|---|---|---:|---:|---|
| session_drift | sd_all | FAIL | FAIL | FAIL | FAIL | FAIL | PASS | FAIL | FAIL | 0.000 | 3850 | no |
| weekday_drift | wd_all | PASS | FAIL | FAIL | FAIL | FAIL | PASS | FAIL | FAIL | 0.111 | 902 | no |

## Regimes (out-of-sample net USD, WF 2010–2019 plus holdout)

| Group | UP_HIVOL | UP_LOWVOL | DOWN_HIVOL | DOWN_LOWVOL |
|---|---:|---:|---:|---:|
| session_drift | -1,708.39 (58266d) | -4,364.35 (162328d) | -169.91 (22830d) | -5,008.62 (108456d) |
| weekday_drift | -686.50 (58266d) | 2,297.23 (162328d) | -104.60 (22830d) | 508.57 (108456d) |

## Dukascopy replicate 2025-08-06 → 2026-09-16 (frozen holdout selections, unchanged)

| Group | Candidate | Status | Net USD | Sharpe | Round turns |
|---|---|---|---:|---:|---:|
| session_drift | sd_all | EVALUATED | -102.60 | -0.158 | 280 |
| weekday_drift | wd_all | EVALUATED | -207.22 | -0.335 | 83 |
| nfp_drift | None | NO_SELECTION | — | — | — |
| **buy_and_hold_long (reference)** | 1.0x long | EVALUATED | 2,596.43 | 0.881 | 1 |

## Sign-randomisation null (trade-level, approximate)

| Group | Trades | Observed net (approx.) | p-value |
|---|---:|---:|---:|
| session_drift | 1332 | -3,295.94 | 0.106 |
| weekday_drift | 275 | 853.11 | 0.064 |

