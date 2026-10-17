# Long-history monthly slow-hybrid results — LH-XAUUSD-HYB-2026-10-17 (stage final)

**Verdict: `NO_VALIDATED_EDGE`.** No group passes G1–G9. Claim: `none`.
- Preregistration: `docs/research/preregistration_longhistory_hybrid_2026-10-17.md`
- Evidence: `data/evidence/longhistory/hybrid_research_final.json`

| Group | Selected | WF SR (90s) | WF pos yrs | Holdout net | Holdout SR | Holm | DSR (N=237) | OOS turns | Gates |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| `hyb_veto` | `veto9` | **+0.278** | 4/10 | +49,897 | 0.662 | 0.013 | 0.752 | 45 | 6/9 (fail G3 yrs, G5, G6) |
| `hyb_agree` | `agree9` | **+0.277** | **5/10** | +12,963 | 0.393 | 0.054 | 0.264 | 52 | 4/9 |
| `hyb_lo` | `ts9_lo` | 0.000* | 0* | +70,989 | 0.837 | 0.008 | **0.945** | 16 | 5/9 |
| buy-and-hold | | −0.282 | — | +142,032 | 0.850 | | | | |

\* protocol composite: no `hyb_lo` candidate is WF-eligible before
1999 (≥20-turn rule); candidate-level 1990s figures are in
`docs/research/best_edge_2026-10-17.md`.

**First positive monthly walk-forward in the repository.** Slow trends
whose shorts require 12-month USD confirmation are the first monthly
family with a positive 1990s walk-forward Sharpe (`veto9` +0.278
chained +14.7%; `agree9` +0.277, 5/10 positive years — one short of
G3's 6). `veto9` also passes G4/G7/G8/G9 on the evaluation window.
Re-selection of `ts9_lo` at the cumulative N=237 yields DSR **0.945** —
0.005 below the gate; the bar rose with the trial count exactly as
designed, and it was not moved. Replicate: `veto9` +$15,135 (SR 0.461),
`ts9_lo` +$21,524 (SR 0.641), both positive.
