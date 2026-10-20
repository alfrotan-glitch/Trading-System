# Candidate XL-001: easing financial conditions (6-month)

**Date registered:** 2026-10-20
**Status:** `CANDIDATE` — cleared the pre-registered gate; **not** validated
**Live trading:** locked. `REAL_CAPITAL_EXPOSURE = 0`.

This is the first configuration in the project to pass every pre-registered
criterion on development data. It is not a profitability claim, and the section
["What would still falsify this"](#7-what-would-still-falsify-this) is as
important as the results.

---

## 1. The hypothesis

Gold is a zero-coupon asset. Two things set the cost of holding it:

- the **US dollar**, in which it is quoted — a stronger dollar makes gold dearer
  for every other currency's holder;
- the **nominal 10-year Treasury yield**, the risk-free return it competes with.

When both are trending *down*, financial conditions are loosening and the
opportunity cost of holding gold is falling. The rule holds gold while they fall.

The combination is an average, not a conjunction. That was chosen by reasoning
before testing: the two series measure the same underlying factor with independent
noise, so averaging should improve signal-to-noise, while requiring agreement
throws away information. **The conjunction was tested and was worse** — mean
exposure 0.25 and DEV alpha t=1.27 — which is the outcome that makes the average
defensible rather than convenient.

## 2. Definition (frozen)

```
usd   = 1 if DXY(t)            < DXY(t - 6 months)  else 0
yld   = 1 if US10Y(t)          < US10Y(t - 6 months) else 0
signal = (usd + yld) / 2                                # exposure in [0, 1]
```

* 6-month lookback = 126 trading days. Values are forward-filled onto gold dates.
* Exposure 0.5 means exactly one of the two is falling.
* Registered hash `2c25b9fda8eebf01`; changing the logic changes the hash and the
  registry **refuses** to overwrite a candidate with a different definition.
* Turnover **6.7 per year**. This is the property that makes the result robust:
  there are only ~7 position changes annually, so costs cannot be doing the work.

## 3. Results

Split fixed before running: DEV 1971-2000, VAL 2001-2010, TEST 2011-2019.
Detection floor on DEV at `alpha_t = 2.5` is **SR 0.456** over 30 years.

### Under realistic costs

| Period | Alpha/yr | alpha_t | Sharpe | Max DD | Beta | Trades |
|---|---|---|---|---|---|---|
| DEV 1971-2000 | **+3.3%** | **2.70** | 0.62 | 24.6% | 0.46 | 304 |
| VAL 2001-2010 | +1.4% | 0.65 | 0.92 | 16.5% | 0.58 | — |
| TEST 2011-2019 | **+4.9%** | **2.94** | 0.66 | 14.6% | 0.50 | — |

`ecn_realistic` = 0.925 bps/side (0.20 USD spread, 3.50 USD/100 oz commission,
0.05 USD slippage at 2000 USD/oz).

**DEV and TEST are disjoint periods, each independently significant.** That is
stronger than one pooled result: the effect is not carried by a single era.

### Cost sensitivity (DEV)

| Model | bps/side | alpha | alpha_t |
|---|---|---|---|
| ecn_assumed | 0.40 | +3.6% | 2.92 |
| ecn_realistic | 0.93 | +3.3% | 2.70 |
| 2x stressed | 0.80 | +3.3% | 2.75 |
| 18-pip standard account | 0.55 | +3.5% | 2.86 |
| 5x stressed | 2.00 | +2.7% | **2.24** |

It survives everything up to 2x stress. At **5x** assumed costs it falls below the
2.5 threshold. That is the honest boundary: a 6.7x-per-year turnover strategy with
2%/yr alpha would be cost-bound, and this one is 12% away from that line at
extreme stress.

### Stability

| Decade | 1971s | 1981s | 1991s | 2001s | 2011s |
|---|---|---|---|---|---|
| alpha/yr | +4.8% | +6.0% | +0.2% | +1.6% | +5.0% |

Positive in all five decades. The 1990s are flat (+0.2%) — a decade of a strong
dollar and rising yields, i.e. the regime where the hypothesis predicts *low*
exposure, so flat rather than negative is consistent with the mechanism.

### Multiple testing

Deflated Sharpe at realistic costs, by trial count:

| Trials | 1 | 7 | 11 | 15 |
|---|---|---|---|---|
| DSR | 0.9997 | **0.978** | **0.962** | 0.948 |

The family contains 4 round-5 configurations plus 3 round-6 combinations = 7
trials. Even counting a pessimistic 11 the gate is cleared. At 15 trials DSR is
0.948, marginally below 0.95 — an honest boundary, not a hidden pass.

## 4. Gate scorecard

| Criterion (frozen) | Required | Achieved | Pass |
|---|---|---|---|
| `alpha_t` on DEV | ≥ 2.5 | 2.70 | ✅ |
| Deflated Sharpe | ≥ 0.95 | 0.962 (11 trials) | ✅ |
| Alpha positive at 2x costs | > 0 | +3.3% | ✅ |
| Alpha sign preserved on VAL | > 0 | +1.4% | ✅ |
| Independent significance on TEST | — | t=2.94 | ✅ |

## 5. What this is not

**Not validated.** A backtest holdout can be read once. The 2020-2024 window was
spent rejecting `tsmom_1m` in the 51-year study, so it is in-sample for this
candidate too, and it therefore cannot confirm anything. The vudo805 Dukascopy
series (2025-08 → 2026-09) is genuinely unseen, but the DXY and 10-year series
available here end 2024-05, so this rule **cannot be computed** over it.

That is the reason the forward pipeline exists: `qts forward log` records the
frozen signal daily, and only that evidence can promote the candidate.

**Not a profitability claim.** 3.3%/yr alpha with 0.46 beta and a 25% drawdown is a
modest effect on a leveraged commodity. It is meaningful because it is stable and
cheap to trade, not because the absolute return is large.

**Not free of selection risk.** The two component signals were identified in
round 5 and combined in round 6, so there is a degree of freedom in the
construction. The DSR at 7-11 trials covers that, but a lucky combination of two
weak signals cannot be excluded from backtest data alone. Forward evidence is the
only way to settle it.

## 6. Production integration

| Component | Purpose |
|---|---|
| `qts/research/edgelab/forward.py` | Frozen registry, append-only ledger, honest scoring |
| `qts/research/edgelab/candidates.py` | The candidate definition, hashed |
| `qts forward candidates` | List and registration status |
| `qts forward register` | Freeze the definition (refuses silent edits) |
| `qts forward log` | Record today's signal; warns if macro data is stale |
| `qts forward score` | Score the ledger; reports observations needed for significance |
| `GET /api/research/edgelab-forward` | Same status for the UI, `validated: false` until proven |

Integrity properties, each tested: registration refuses a changed definition;
observations cannot be revised once recorded; fewer than three observations
reports `insufficient` rather than a number; the API never reports `validated`
without forward evidence.

## 7. What would still falsify this

1. **Forward evidence contradicting the backtest.** Five years of daily
   observations at the observed effect size would be decisive. The ledger reports
   the count needed as it accumulates.
2. **The 1990s pattern repeating.** If the rule goes flat for a decade while
   exposure stays high, the mechanism is wrong, not merely unlucky.
3. **Structural change in gold's drivers.** Gold's behaviour after 2022 (central
   bank buying, de-dollarisation) may have broken the dollar/yield relationship
   that every result here depends on. This is the strongest reason for caution.
4. **Cost reality worse than 5x assumed.** At 2 bps/side the effect is already
   below threshold.

## 8. Reproduction

```bash
python scripts/edgelab_prepare_longgold.py            # 51-year store
python scripts/edgelab_macro_daily_run.py             # round 5: the components
python scripts/edgelab_candidate_run.py               # this candidate, all costs
qts forward register && qts forward log               # begin forward evidence
qts forward score
```
