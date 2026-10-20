# Edge Lab: XAUUSD alpha attribution and the first acceptance run

**Date:** 2026-10-20
**Verdict:** `NO_VALIDATED_EDGE`
**Holdout status:** TEST (2022-2024) and OOS (2025-2026) **not read**. No candidate
earned the right to see them.

This note records an independent replication of the project's existing negative
result (`QTS_PROJECT_CONTROL.md` §20-22) using a separate harness, a separate data
pipeline and a stricter acceptance criterion. The conclusion did not change, but
the *reason* the earlier candidates looked good did.

---

## 1. The question the earlier screens answered wrongly

The first pass over this dataset ranked strategies by Sharpe. The best DEV result
was `tsmom_d5` at Sharpe 0.513 — a number that looks like skill until you ask what
simply owning gold scores over the same window:

| Period | Buy-and-hold CAGR | Sharpe | Max drawdown |
|---|---|---|---|
| DEV 2004-06-11 → 2018-12-31 | 7.00% | 0.493 | 44.9% |
| VAL 2019-01-01 → 2021-12-31 | 9.98% | 0.748 | 18.6% |

A strategy cannot be judged by a Sharpe of 0.5 on an asset that returns 0.49.
Ranking on Sharpe ranks *exposure*, not skill. Every DEV "winner" was therefore
re-tested against a regression on the underlying:

```
r_strategy = alpha + beta * r_gold + e
```

* `beta` — how much of the return is just holding gold
* `alpha` — the return that gold does not explain
* `alpha_t` — whether that alpha is distinguishable from zero
* `ir_vs_bh` — information ratio against simply buying and holding

## 2. Result: the best candidate was noise, and it reversed

| Strategy | DEV alpha (annual) | DEV alpha t | DEV Sharpe | VAL alpha (annual) | VAL alpha t | VAL Sharpe |
|---|---|---|---|---|---|---|
| `tsmom_d5` | **+8.26%** | 2.11 | 0.513 | **−7.00%** | −0.95 | −0.50 |
| `ma_50_200` | +6.07% | 1.60 | 0.472 | −6.40% | −1.20 | −0.02 |
| `tsmom_d10` | +5.78% | 1.48 | 0.345 | −6.70% | −0.93 | −0.38 |

`tsmom_d5` is not a beta proxy — its DEV beta is 0.02, so the +8.26% really was
unexplained by gold. That made it the most promising candidate in the study. It
then lost money every year of the validation period and flipped to a
**negative** alpha.

A real effect decays. A fitted artefact reverses. This one reversed.

Note also that the t-statistic was 2.11 across 46 configurations. After accounting
for the number of hypotheses tried, that is not evidence of anything.

## 3. Volatility-managed exposure: real risk reduction, no alpha

`realized_vol` had a defect that made every vol-scaled strategy a no-op: it
annualised with `sqrt(bars_per_day)`, which for daily bars is `sqrt(1)`, producing
*daily* sigma (~1%) instead of annual (~16%). A 15% volatility target was
therefore never binding and every "vol-scaled" variant silently ran at full size.

With the annualisation fixed, volatility-managed long gold (Moreira–Muir style)
was tested properly for the first time:

| Period | Strategy | CAGR | Sharpe | Max DD | Alpha (ann) | Alpha t |
|---|---|---|---|---|---|---|
| DEV | buy-and-hold | 7.00% | 0.493 | 44.9% | — | — |
| DEV | `volman_15_d60` | 6.60% | **0.549** | 42.4% | +1.0% | 1.13 |
| VAL | buy-and-hold | 9.98% | 0.748 | 18.6% | — | — |
| VAL | `volman_10_d60` | 8.70% | **0.863** | **13.9%** | +1.4% | 1.04 |

Sharpe improves and drawdown falls in *both* periods, which is consistent with
volatility clustering being a real, persistent property of the market. But alpha
is ~1%/yr with a t-stat near 1.0: this is **risk management of a long-gold
position, not a return edge**. It is not promoted, and it must not be described as
alpha.

## 4. Acceptance gate (pre-registered)

`qts/research/edgelab/gate.py` fixes the criteria before results are read:

1. `alpha_t >= 2.5` on DEV (higher than 2.0 because ~46 configurations were tried)
2. deflated Sharpe `>= 0.95`, counted per family
3. alpha stays **positive** under 2× assumed costs
4. alpha keeps the **same sign** on VAL

A candidate failing any one of them stays `NO_VALIDATED_EDGE`.

**Outcome: 0 survivors out of 39 evaluable D1 strategies (46 defined, 11 families)
and 0 of 46 on H1.** The best DEV alpha t-stat was 2.11 (D1) and 2.14 (H1) — and
it is the *same* signal at two resolutions, so those are not independent
observations.

Honest caveat: the deflated Sharpe saturates at 1.000 for anything with a Sharpe
near 0.5 over 4,481 daily bars, because the t-statistic is enormous. DSR is not
the binding constraint here — the alpha regression and the VAL sign test are. That
is worth knowing before treating DSR as the guard against overfitting: on a long
sample it will wave through almost everything.

## 5. Defects found and fixed while doing this

| Defect | Consequence if shipped | Fix |
|---|---|---|
| Unshifted `held` array in `run_vector` | Credited a signal with the move that preceded it: `tsmom_d5` showed Sharpe 5.46 / 88% a year | Explicit execution conventions; buy-and-hold matches to 1e-12; regression tests |
| `deflated_sharpe` returned **1.0 for every input** | The multiple-testing guard passed anything, including pure noise | `norm.ppf(1 - 1/1) = -inf` special-cased; test now pins that 500 trials demote a marginal Sharpe |
| `realized_vol` annualised with bars-per-*day* | Vol targeting never engaged; every "vol-scaled" result was actually unscaled | `infer_bars_per_year()` from median bar spacing; regression test asserts daily bars annualise with sqrt(252) |
| Strategy catalogue lived in `scripts/` | The gate could evaluate different code than the screen that produced the candidate | Moved to `qts/research/edgelab/specs.py`, imported by both |

Each of these is a case where the harness would have reported a confidently wrong
number. None of them were visible from the output — only from reading the code.

## 6. What this does and does not establish

**Established:** over 2004-2021, in this dataset, none of 46 price-based
configurations in 11 families produces alpha that survives costs, multiple-testing
correction and a validation period. This corroborates §20-22 from an independent
implementation.

**Not established:** that no XAUUSD edge exists. This study tests *price-derived*
signals on one instrument. It says nothing about:

* signals using data this harness does not have — order flow, options-implied
  volatility, real yields, ETF flows, positioning;
* execution-level edges (maker/taker, latency, spread capture);
* portfolio construction across several instruments.

**Untouched:** TEST 2022-2024 and OOS 2025-2026 remain unread. Spending the
holdout on a strategy that already failed DEV and VAL would destroy it for nothing.

## 7. Reproduction

```bash
python scripts/edgelab_prepare_data.py     # build parquet + quality report
python scripts/edgelab_screen.py --timeframe D1 --period DEV    # rank by alpha
python scripts/edgelab_report.py --timeframes D1,H1             # gate + verdict
```

Artifacts: `data/research/experiments/` (per-run CSVs and `verdict_*.json`).

Tests pinning the above: `tests/unit/test_edgelab_engine.py` (14 invariants) and
`tests/unit/test_edgelab_gate.py` (7 gate behaviours).
