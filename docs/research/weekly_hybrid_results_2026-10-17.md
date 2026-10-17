# Long-history weekly slow-hybrid results — LH-XAUUSD-WHYB-2026-10-17 (stage final)

**Verdict: `NO_VALIDATED_EDGE`.** No group passes G1–G8. Claim: `none`.
- Preregistration: `docs/research/preregistration_longhistory_weekly_hybrid_2026-10-17.md`
- Evidence: `data/evidence/longhistory/weekly_hybrid_research_final.json`

| Group | Selected | WF SR | Holdout net | Holdout SR | Holm | DSR (N=262) | OOS turns | Gates |
|---|---|---:|---:|---:|---:|---:|---:|---|
| `wh_veto` | `wv_2652` | +0.059 | +1,099 | 0.264 | 0.246 | 0.010 | 55 | 4/8 |
| `wh_lo` | `wl_2652` | +0.255 | +1,961 | 0.442 | 0.242 | 0.042 | 21 | 4/8 |
| buy-and-hold | | | +8,911 | 0.881 | | | | |

Translating the monthly champion mechanism to weekly frequency
**destroys it**: holdout Sharpe falls from 0.66–0.84 (monthly) to
0.26–0.44, DSR collapses despite similar nets, and walk-forward stays
below every bar. Combined with `LH-XAUUSD-W1-2026-10-17`, the weekly
branch is closed: two preregistered cycles, no group above 4/8 gates.
The mechanism is monthly-horizon-specific. Replicate selections are
positive but tiny (+$762, SR 0.836 on the short 2025–26 window;
informational).
