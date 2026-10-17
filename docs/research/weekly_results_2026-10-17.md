# Long-history weekly ensemble results — LH-XAUUSD-W1-2026-10-17 (stage final)

**Verdict: `NO_VALIDATED_EDGE`.** No group passes G1–G8. Claim: `none`.
- Preregistration: `docs/research/preregistration_longhistory_weekly_2026-10-17.md`
- Evidence: `data/evidence/longhistory/weekly_research_final.json`
  (tables: `weekly_research_final_tables.md`)
- Disclosure: `--stage final` executed twice. The first marked every
  replicate group `NOT_EVALUABLE` (59-week replicate < 52-week warm-up);
  the second attaches the replicate with a research history prefix
  (informational only). Holdout numbers verified byte-identical between
  executions (all three groups' nets unchanged).

| Group | Selected | Holdout net | Sharpe | 2x | BE | Holm | DSR (N=193) | OOS turns | Gates |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| `wk_ens` | `w_e132652_ls` | +1,137 | 0.244 | +1,011 | 10.5x | 0.471 | 0.015 | 86 | 3/8 |
| `wk_trend` | `w_sma52_ls` | +1,275 | 0.265 | +1,167 | 13.4x | 0.471 | 0.011 | 50 | 4/8 |
| `wk_longonly` | `w_sma52_lo` | +2,981 | 0.562 | +2,911 | 48.8x | 0.168 | 0.144 | 39 | 3/8 |
| buy-and-hold | | +8,911 | 0.881 | | | | | | |

Walk-forward 2010–2019 is weak for all groups (best `wk_longonly`
Sharpe 0.351, 4/10 positive years). The weekly frequency does raise
turnover (86 OOS turns for the ensemble) but dilutes the signal:
holdout Sharpes are a third of the monthly family's. The weekly
hypothesis — intermediate frequency rescues sample size without losing
the edge — is **not supported**; the edge, such as it is, lives at
monthly horizon. Replicate (Dukascopy weekly, prefixed): all selections
small-positive (best `w_sma52_lo` +$641, SR 0.687).
