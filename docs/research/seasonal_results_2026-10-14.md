# Results — XAUUSD calendar-seasonality study (`LH-XAUUSD-SES-2026-10-14`)

**Verdict: `NO_VALIDATED_EDGE`.** Claim: none (costs ASSUMED; the evaluation
window is reused from the parent cycles — both disclosed in the
preregistration §2). No group passes G1–G8. LIVE/DEMO state, risk limits and
authorisation are untouched; `REAL_CAPITAL_EXPOSURE = 0`.

- Preregistration (frozen in commit `18b27dc`, before the final run):
  `docs/research/preregistration_longhistory_seasonal_2026-10-14.md`
- Generated tables (this document's numbers):
  `docs/research/seasonal_results_tables_2026-10-14.md`
- Evidence: `data/evidence/longhistory/seasonal_research_final.json`
  (dev-stage pipeline run: `seasonal_research_dev.json`; stamp basis:
  `stamp_basis_probe.json`)
- Reproduce: `python scripts/fetch_longhistory_sources.py && python
  scripts/build_longhistory_dataset.py && python
  scripts/run_longhistory_seasonal.py --stage final`

## 1. Headline numbers

Evaluation window 2020-01-01 → 2025-02-28 (selection frozen on data through
2019-12-31, per group, from the walk-forward selection rule):

| Group | Selected | Net USD | Sharpe | Max DD | Turns | Break-even cost × | Holm p | DSR (N=47) | Gates |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| `session_drift` | `sd_all` | **−3,295.94** | −1.723 | −35.4% | 1,332 | 0.2495 | 1.00 | 0.000 | 1/8 (G6 only) |
| `weekday_drift` | `wd_all` | **+853.11** | +0.334 | −8.5% | 275 | 1.7414 | 0.46 | 0.111 | 2/8 (G1, G6) |
| `nfp_drift` | — | never traded | — | — | 0 | — | — | — | no eligible candidate |
| buy-and-hold (reference) | 1.0× long | +8,795.66 | +0.860 | −21.9% | 1 | — | — | — | — |

Walk-forward 2010–2019 (per-year selection, frozen within each year):
`session_drift` Sharpe −2.004, **0/10** positive years, chained −57.3%;
`weekday_drift` Sharpe +0.229, 5/10 positive years, chained +11.3%;
`nfp_drift` 0 years traded (no candidate ever eligible).

Replicate (Dukascopy 2025-08 → 2026-09, frozen selections, history-prefixed
plans): `sd_all` −102.60 (Sharpe −0.158, 280 turns); `wd_all` −207.22
(Sharpe −0.335, 83 turns); buy-and-hold +2,596.43. **Both selections are
negative on the independent replicate series.**

Trade-level sign-randomisation null: `session_drift` p = 0.106,
`weekday_drift` p = 0.064 — neither is distinguishable from a random ordering
of the same trades.

## 2. Family outcomes

### `session_drift` — REJECTED

`sd_all` was selected in all ten walk-forward folds and for the evaluation
window (train round turns 240–257 per fold). It loses on the evaluation
window at base cost, at 2× (−6,065) and 3× (−7,691), in every one of the four
regimes out-of-sample, and on the replicate. Break-even cost multiplier
0.2495×: the strategy is only profitable at under a quarter of the ASSUMED
base cost. G1, G2, G3, G4, G5, G7, G8 all fail; G6 (3,850 OOS round turns)
passes and is irrelevant alone. The pre-declared cost-regime diagnostic
agrees: negative under canonical (−1,018), WM median (−756), WM median+ECN
(−1,357) and WM reopen-stress (−2,336).

The design claim that the session family never holds through the 22:00 UTC
rollover is **mechanically verified**: 0 rollover crossings across all 1,332
holdout trades (swap diagnostic).

### `weekday_drift` — closest candidate, still REJECTED

`wd_all` passes G1 (evaluation-window net +853.11, Sharpe 0.334) and G6 (902
OOS round turns) and fails **G2** (net −281.61 at 2× cost), **G3** (walk-forward
Sharpe 0.229 > 0 but only 5/10 positive years vs the required ≥ 6), **G4**
(Holm p = 0.46), **G5** (DSR 0.111 vs 0.95 at N = 47), **G7** (negative in
UP_HIVOL −686.50 and DOWN_HIVOL −104.60: 2/4 regimes), and **G8**
(break-even 1.7414× < 2.0×). The bootstrap 95% Sharpe interval
[−0.57, +1.14] includes zero, the sign-randomisation p = 0.064, the replicate
is negative, and buy-and-hold makes +8,795.66 in the same window. Under all
four pre-declared cost regimes the evaluation-window net stays positive but
thin (+1,164 to +1,603, Sharpe 0.44–0.59) — a positive sign that is
nevertheless far below every pre-registered threshold. **No gate weakening is
on the table: G8 was added by this cycle, not inherited, and it fails.**

The weekday family holds whole trading days, so it crosses the 22:00 rollover
by construction: 800 crossings over 275 trades (2.91/trade) with an ASSUMED
drag of $101.26 at $3.5/lot/night — disclosed, not netted into any number
above (financing is 0 in the frozen cost model, as in the parents').

### `nfp_drift` — never traded under the frozen thresholds (structural)

Both `nfp_h4` and `nfp_h16` produce **zero decisions** on the whole research
series: the expanding post-release t-statistic only exceeds |t| ≥ 2.0 during
the first handful of events, while the warm-up requires `n ≥ 48` events; by
the time 48 valid occurrences exist, the expanding |t| settles near 1.0–1.4
and never reaches 2.0 again (max mature |t| observed ≈ 1.4; the early
|max| ≈ 7.0 occurs at n = 3, long before the warm-up). The thresholds were
frozen before any of this was observed and **were not changed afterwards**.
The group therefore has no eligible candidate in any fold and fails G0
("no eligible candidate"). The family's mechanism is untested-by-design here:
no trade means no evidence for or against post-payrolls drift — recorded as a
structural null, not a falsification of the mechanism and not an edge.

### Controls (non-gating, pre-declared)

- `wd_perm1_control` (weekday statistics rotated by one weekday): evaluation
  window +391.59 (Sharpe 0.179, 282 turns, break-even 1.34×), walk-forward
  Sharpe −0.281. It is **weaker than the aligned `wd_all` (+853.11)** on the
  evaluation window, so the §9 falsifier ("control passes while aligned
  fails") does not trigger — but the aligned candidate's own gates fail
  regardless.
- `sd_placebo_h3_control` (session machinery on fixed +3 h placebo windows):
  **never trades.** The placebo windows' mature expanding |t| crosses 2.0 only
  ephemerally (max 1.372 / 2.255 / 1.730 for Asia/Europe/US placebo windows at
  n ≥ 250) and never on a decision date, so the control has zero evaluation-
  window result. Disclosed as a null control: it provides no evidence either
  way.

## 3. Bias checks and integrity

- Truncation (causality) check: **7/7 candidates and controls pass at all
  three cuts** (25/50/75% of the series); ATR(14) and realised-vol warm-up
  checks pass (`bias_checks.all_passed = True` in the evidence JSON).
- The study ran the exact frozen pipeline: dev stage first (walk-forward
  only), committed with the preregistration (`18b27dc`), then **one** final
  run.
- Selection, gates, Holm, DSR (N = 47), bootstrap, sign-randomisation,
  regimes and benchmarks are the shared runner code; the only shared-code
  change this cycle (optional G8 via `getattr`, dynamic gate headers) was
  verified against both parent cycles: their final re-runs are byte-identical
  to the committed tables and evidence (JSON differs only in `generated_at`,
  plus the already-disclosed daily `periods_per_year` field).
- Trial count: 47 (40 parent + 7 this cycle), stated in the preregistration
  and `seasonal_protocol.N_TRIALS`; `docs/experiment_ledger.md` is a
  generated aggregate and was not hand-edited (ARCH-020/021 precedent).

## 4. Interpretation and what this closes

The audit's row D1 ("scheduled macro + session" — PURSUE) has now been
**executed end-to-end on the bar data**: signed session-window drift,
trading-day-of-week drift and post-payrolls drift, all causal, cost-aware and
multiplicity-corrected. None survives. `H-TOD-01`'s bar-level form is no
longer "NOT TESTED" — it is tested and rejected at the frozen thresholds;
the tick-level form remains BLOCKED (operator-side ZIP download, §11 of the
preregistration).

Remaining feasible work in this repository is blocked on data acquisition,
not on code: cross-asset conditioning (DXY, real yields), COMEX basis and
order-flow paths from the information-gap audit, and the tick archive. Costs
remain ASSUMED until `qts demo cost-check --record` can run against the
Windows MT5 terminal.

**Standing verdict: `NO_VALIDATED_EDGE`.** The strongest measured candidate
this cycle (`wd_all`) is +853 on the reused evaluation window with
break-even 1.74× and a negative independent replicate — it does not meet the
pre-registered bar for forward validation, and nothing here changes any
promotion, risk or LIVE state.
