# Long-history monthly ensemble results — LH-XAUUSD-ENS-2026-10-17 (stage final)

**Verdict: `NO_VALIDATED_EDGE`.** No group passes G1–G9. Claim: `none`
(costs ASSUMED; evaluation window reused across cycles — both disclosed
in the preregistration). `LIVE_LOCKED`, `REAL_CAPITAL_EXPOSURE = 0`
unchanged; research only.

- Preregistration: `docs/research/preregistration_longhistory_ensemble_2026-10-17.md`
  (frozen in the preregistration commit before `--stage final`).
- Evidence: `data/evidence/longhistory/ensemble_research_final.json`
  (+ `_dev.json` walk-forward-only stage; generated tables
  `ensemble_research_final_tables.md`).
- Runner: `python scripts/run_longhistory_ensemble.py --stage final`
  (first final execution crashed at the replicate step — USD-conditioned
  builders need the replicate's `usd` column and warm-up; fixed by
  loading OHLC+usd and attaching the replicate with the parent cycle's
  history-prefix method. No gate, window, candidate or number changed;
  disclosed here as in the parent monthly cycle.)

## 1. Gates and holdout (evaluation 2000-01 → 2026-09, selection ≤ 1999)

| Group | Selected | Net USD | Sharpe | 2x | Break-even | Holm p | DSR (N=149) | OOS turns | Gates passed |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| `ens_fast` | `e248_ls` | +34,457 | 0.551 | +32,841 | 40.9x | 0.039 | 0.247 | **100** | 7/9 (fail G3, G5) |
| `ens_multi` | `e3612_ls` | +32,583 | 0.539 | +31,351 | 49.8x | 0.044 | 0.220 | 72 | 6/9 (fail G3, G5, G6) |
| `usd_conditioned` | `e248_usdagree` | +11,421 | 0.366 | +10,858 | 29.4x | 0.067 | 0.104 | 76 | 4/9 |
| `long_only` | **`ts9_lo`** | **+70,989** | **0.837** | +70,165 | **>50x** | **0.010** | **0.929** | 26 | 5/9 (fail G3, G5, G6, G7) |
| buy-and-hold (ref) | 1.0x long | +142,032 | 0.850 | — | — | — | — | 1 | — |

## 2. Reading

- **`ts9_lo` (9-month TSMOM, long-or-flat) is the strongest single
  result in this repository's history**: holdout Sharpe 0.837 (bootstrap
  95% CI [0.32, 1.30]), sign-randomisation p = 0.042 (the first
  significant one in the long-history series), financed net +$59,931,
  max drawdown −31.0% vs buy-and-hold's rally exposure, profit factor
  7.09 on 16 round turns. Its DSR **0.929** at N=149 is the closest any
  candidate has come to the 0.95 bar. It fails G5 narrowly, G6
  structurally (16 evaluation turns; slow long-or-flat cannot reach
  100 OOS turns), G7 (long-or-flat loses in DOWN regimes by
  construction), and G3 (see §3).
- **`ens_fast` passes G6 for the first time in the monthly series**
  (exactly 100 OOS turns) and G4, but its 1990s walk-forward
  (Sharpe −0.364, 2/10 positive years) drags the combined DSR to 0.247.
- Walk-forward 1990–1999 remains the graveyard for every monthly group
  (Sharpe −0.83…−0.20); buy-and-hold chained −29.0% there, so groups
  lose less than passive but not positively.
- Replicate (BaseMax monthly, informational): all four selections
  positive (`ts9_lo` +$21,524 SR 0.641; `e248_ls` +$26,836 SR 0.620).

## 3. Why `long_only` G3 reads 0.0

The group's walk-forward composite is identically zero: no `long_only`
candidate reaches the inherited ≥20 training-turn eligibility until
1999 (`ts9_lo` reaches exactly 20 through 1999, hence its holdout
selection), and the faster `e248_lo` selected in 1994–1999 loses small
amounts. Candidate-level diagnostics in
`docs/research/best_edge_2026-10-17.md` separate this protocol artefact
from the candidates' own 1990s behaviour. Thresholds were not moved.
