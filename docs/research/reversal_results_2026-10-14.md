# Results — XAUUSD M15 impulse-fade (short-horizon reversal) (`LH-XAUUSD-M15-REV-2026-10-14`)

**Verdict: `NO_VALIDATED_EDGE`. Claim: none.** The mechanism is rejected at the **gross** level: the
pre-costs return of the selected fade is ~zero on the reused holdout, and it is negative in
walk-forward. Costs are ASSUMED, the holdout and replicate are reused (disclosed in the
preregistration §2), and nothing here changes any risk, LIVE or DEMO state. `REAL_CAPITAL_EXPOSURE = 0`.

- Preregistration (committed `561e8e6` before any reversal result): `docs/research/preregistration_longhistory_m15_reversal_2026-10-14.md`
- Evidence: `data/evidence/longhistory/reversal_research_dev.json` (walk-forward only, first) and
  `data/evidence/longhistory/reversal_research_final.json` (single final run)
- Tables (generated from the JSON): `docs/research/longhistory_reversal_results_tables_2026-10-14.md`
- Code: `src/qts/research/longhistory/reversal_protocol.py`, `signals.impulse_fade`,
  `scripts/run_longhistory_reversal.py`; tests `tests/unit/test_longhistory_reversal.py`
- Reproduce: `python scripts/fetch_longhistory_sources.py && python scripts/build_longhistory_dataset.py &&
  python scripts/run_longhistory_reversal.py --stage dev && python scripts/run_longhistory_reversal.py --stage final`

## 1. Why this was the next experiment

The parent M15 cycle showed that the **continuation** of large bar impulses (`rexp_k10_h4/h16`, bar body
> 1 ATR) loses at zero cost on the holdout (−3,450 for `h16`). The question was whether the **opposite
sign**, with a stricter trigger that reduces turnover, is a reversal the cost model could support. This
is a new, sign-inverted, pre-registered hypothesis; it is counted in the trial count.

## 2. Holdout (2020-01-01 → 2025-02-28; selection frozen on data through 2019)

| Selected | Net USD | Gross (zero-cost) USD | Cost USD | Round turns | Sharpe | Net @2× | Break-even × | Holm p |
|---|---:|---:|---:|---:|---:|---:|---|---:|
| `fade_k20_h16` | **−6,237.32** | **+14.01** | 6,109.07 | 1,711 | −2.699 | −8,586.60 | 0.0014 (crosses zero) | 1.00 |

- **Gross is ~zero.** The zero-cost holdout P&L is +$14 over 1,711 round turns (about $0.008 per trade).
  Measured against an assumed cost of about $3.57 per round turn, the gross edge per trade is a tiny
  fraction of its cost. This is the decisive finding: the fade has no measurable gross edge at this
  threshold, so costs are not the only reason it fails.
- Costs turn a ~zero gross into −$6,237 net. Break-even is 0.0014× the assumed cost.
- Sign-randomisation p = 0.55: the direction of these trades is indistinguishable from a random sign.

## 3. Walk-forward 2010–2019 (per-year selection, frozen within each year; base cost)

- Selected in every year: `fade_k20_h16`. Sharpe −3.029, **0 of 10 positive years**, chained −88.6%.
- Net negative in all four regimes out-of-sample (UP_HIVOL, UP_LOWVOL, DOWN_HIVOL, DOWN_LOWVOL).
- Buy-and-hold over the same years: chained +34.4%, Sharpe +0.272.

## 4. Dukascopy replicate (2025-08-06 → 2026-09-16, frozen holdout selection, informational)

`fade_k20_h16`: net −1,953.63, Sharpe −1.861, 348 round turns, gross −338.48, profit factor 0.75.
Buy-and-hold: +2,596.43. The replicate is consistent with the research result, not with an edge.

## 5. Gates (G1–G8; all must pass)

| G1 | G2 | G3 | G4 | G5 | G6 | G7 | G8 | DSR (N=50) | OOS round turns | Passes |
|---|---|---|---|---|---|---|---|---:|---:|---|
| FAIL | FAIL | FAIL | FAIL | FAIL | PASS | FAIL | FAIL | 0.000 | 5,373 | **no** |

G6 (≥ 100 OOS round turns) is the only gate that passes, and it is irrelevant alone. The bias checks
(causality truncation at 3 cuts on all candidates, ATR and realised-vol warm-up) pass.

## 6. Conclusion for this mechanism

- **Rejected:** the impulse-fade (reversal) hypothesis, at thresholds 1.0 and 2.0 ATR20 and holds of
  4 and 16 bars, on this series. Gross is ~0 at the selected candidate and negative in walk-forward.
- The short-horizon reversal channel described in the preregistration is **not** supported by this
  data at this granularity. The sign-inverted continuation also loses (parent cycle), so large M15
  bar impulses carry no exploitable directional information after costs here.
- Multiple testing: the three candidates are counted in N = 50; the holdout is reused, so no pass would
  have been more than forward validation.

## 7. Trial-count inconsistency (recorded, not fixed here)

`docs/experiment_ledger.md` reports **304 trials** from the `qts edge` SQLite ledger, while the
long-history research series uses its own cumulative count (**50** after this cycle). These are
different registries. The 304 figure is not reconciled with the 50 in this document, and the ledger is
generated from `data/sqlite/qts.db`, which this cycle did not touch.

## 8. Remaining feasible paths (not executed; see the seasonal cycle §4)

- Independent unseen XAUUSD data: none in this sandbox beyond the reused 2025-08 → 2026-09 replicate.
- Measured costs (`qts demo cost-check --record`): needs the Windows MT5 terminal.
- Tick-level order-flow and cross-asset (DXY, real yields): no reachable source in this sandbox.
