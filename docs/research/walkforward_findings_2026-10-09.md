# Walk-forward strategy findings — real XAUUSD 15m history

**Date:** 2026-10-09
**Data:** `20261009-010+2b024334-1ba57af7` — 26,038 bars, 2025-08-06 → 2026-09-16
(407 days), 15-minute **mid** prices derived from Dukascopy bid/ask ticks via
the pinned `vudo805/forex-price-simulator` mirror at commit `4d6f155`.
**Provenance class `REAL`.**
**Cost basis:** **ASSUMED** (retail XAUUSD estimate: 3 bps spread, 2 bps
slippage, $7/lot commission). No cost has been measured on the broker.
**Coverage:** 100% of the series traded in every run below (0 halted folds).
**Verdict:** **NO EDGE ESTABLISHED.**

---

## Correction notice — read this first

An earlier version of this document reported a breakout candidate with
**+5,795 OOS, 4/4 profitable folds and 11.3% max drawdown** and rated it
`EDGE_CANDIDATE`. **That result was an artefact and is retracted.**

The risk engine's kill switch is terminal. Once it fired (default limits: $500
drawdown, $200 daily loss) every later intent was vetoed and the backtest
walked the remaining bars doing nothing — while returning a result that looked
complete. Nothing in the output said so.

Measured on this dataset, before and after the fix:

| | Before (truncated) | After (full series) |
|:---|---:|---:|
| Fills | 563 | **2,982** |
| Last fill bar (of 26,038) | 4,635 | **26,023** |
| Months traded (of 14) | 3 | **14** |
| Final equity | 10,566.03 | **13,737.40** |
| Max drawdown | 11.3% | **42.2%** |

A run that stops at its first drawdown never records the drawdown that stopped
it. It reported the strategy's best stretch and called it the strategy.

Fixed in `a4e5ac0`: `BacktestResult` now carries `halted` / `halt_reason` /
`halted_at_bar` / `bars_traded`; research runs with the kill switch off so the
full series is evaluated and the pipeline's own drawdown gate does the
rejecting; any fold that still halts fails the verdict with the coverage it
achieved. Regression tests in
`tests/unit/test_backtest_halt_detection.py`.

**Every number below is from a re-run with 100% coverage.**

---

## Headline

No candidate survived. All five families are measured on the full series with
100% coverage, and the single configuration that cleared the acceptance
criteria at one fold count failed both when the partition was refined and when
costs were stressed — which is the most useful thing this pipeline did.

Nothing here is a claim. Costs are assumed, so the pipeline refuses to make
one, and no strategy is promoted on this evidence.

---

## The frozen candidates

Run on the full 407 days through `qts edge benchmark`, $10,000 account,
0.01 lot, no stops:

| Candidate | Role | Round turns | Gross | Cost | **Net** | Net/trade |
|:---|:---|---:|---:|---:|---:|---:|
| BENCH-A-TREND-EMA-12-48 | CANDIDATE | 912 | **−125.77** | 456.00 | **−581.77** | −0.64 |
| BENCH-B-BREAKOUT-DONCHIAN-20 | CANDIDATE | 4,999 | **−735.39** | 1,422.00 | **−2,157.39** | −0.43 |
| BENCH-C-MEANREV-BOLLINGER-20-2.0 | CONTROL | 6,289 | +81.85 | 1,609.00 | **−1,527.15** | −0.24 |

**Both candidates lose money before costs.** A strategy with negative gross is
not a victim of its broker — the signal has no value, and no amount of spread
negotiation rescues it. The control behaves as a control should.

---

## Walk-forward: five established families

Parameters chosen on the training window only; reported figures are
out-of-sample. 4 folds, 15% test windows, purged and embargoed.
$10,000 account, 0.01 lot.

| Family | OOS net | Gross | Cost | Cost/gross | Trades | Expectancy | Folds + | Max DD | Verdict |
|:---|---:|---:|---:|---:|---:|---:|:---:|---:|:---|
| trend | +63.12 | 683.76 | 620.63 | 90.8% | 372 | +0.17 | 2/4 | 4.9% | NO_EDGE |
| breakout | +85.94 | 1,737.61 | 1,651.67 | 95.1% | 1,003 | +0.09 | 2/4 | 43.3% | NO_EDGE |
| mean_reversion | **−3,282.25** | 1,031.94 | 4,314.19 | **418.1%** | 2,667 | −1.23 | 2/4 | **73.6%** | NO_EDGE |
| momentum | **−11,938.35** | 10,112.78 | **22,051.13** | **218.1%** | 12,644 | −0.94 | **0/4** | 64.9% | NO_EDGE |
| volatility | **−4,775.92** | 4,797.62 | 9,573.54 | **199.5%** | 5,380 | −0.89 | 1/4 | 38.6% | NO_EDGE |

Momentum and volatility trade on nearly every bar — 12,644 and 5,380 trades
against 372 for trend — so their grids are capped with `--max-configs`. Both
are now complete, and both are among the worst results in the set: momentum
profitable in **0 of 4 folds**, volatility in 1 of 4, each paying about twice
its own gross in costs.

**All five families are now measured on 100% of the series. None of them has
an edge.**

The cost column is the finding. Trend and breakout consume **91% and 95% of
their own gross in assumed costs**. Mean reversion pays 4.2× its gross. These
are not strategies with a thin margin; they are strategies whose entire return
is a rounding error against the spread.

---

## Adding risk management

Re-running with a **$40 stop and a 96-bar (24h) time exit**:

| Run | OOS net | Gross | Cost | Cost/gross | Trades | Expectancy | Folds + | Max DD | Verdict |
|:---|---:|---:|---:|---:|---:|---:|:---:|---:|:---|
| breakout + stops | +3,764.97 | 9,124.48 | 5,359.50 | 58.7% | 2,555 | +1.47 | **1/4** | 53.1% | NO_EDGE |
| trend + stops | **+331.31** | 1,392.40 | 1,061.09 | 76.2% | 633 | +0.52 | **3/4** | 7.5% | **EDGE_CANDIDATE** |

Stops changed both pictures. Note what happened to the previously "winning"
breakout: with the full series traded it is profitable in **1 of 4 folds**, not
4 of 4, and carries a 53.1% drawdown. The earlier +5,795 / 4/4 / 11.3% was
entirely the truncation.

Trend + stops cleared every mechanical criterion and became the only
`EDGE_CANDIDATE` in the corrected set. It did not survive either stress test.

### Stress test 1: finer partition

The same configuration, 8 folds at 8% each instead of 4 at 15%:

| | 4 folds | **8 folds** |
|:---|---:|---:|
| OOS net | +331.31 | **−389.10** |
| Expectancy/trade | +0.52 | **−0.39** |
| Profitable folds | 3/4 | 3/6 |
| Worst fold | −216.15 | **−625.18** |
| Mean fold Sharpe | +0.311 | **−1.038** |
| Deflated Sharpe | p = 0.0000 | **p = 1.0000 (fails)** |
| Verdict | EDGE_CANDIDATE | **NO_EDGE_ESTABLISHED** |

The same reversal that killed the breakout candidate, on a different family:
a coarse partition averaged away a losing window. **A result that depends on
how the data is sliced is not a result.**

### Stress test 2: cost

The test that usually kills a backtest, and did:

| Costs | OOS net | Gross | Cost | Cost/gross | Expectancy | Folds + | Verdict |
|:---|---:|---:|---:|---:|---:|:---:|:---|
| 1× (3 bps) | +331.31 | 1,392.40 | 1,061.09 | 76.2% | +0.52 | 3/4 | EDGE_CANDIDATE |
| 2× (6 bps) | **−762.06** | 1,377.24 | 2,139.30 | **155.3%** | −1.19 | 1/4 | NO_EDGE |
| 3× (9 bps) | **−1,717.35** | 974.25 | 2,691.60 | **276.3%** | −3.18 | 1/4 | NO_EDGE |

Breakout + stops behaves the same way but worse — at 2× costs it loses
**−7,012.31 against +3,120.31 gross**, paying 3.2× its own gross in
friction.

At 76% of gross, the candidate needs costs to be *exactly* as assumed to
break even. Doubling them — a routine difference between a quoted spread and
a real one during a news spike — makes it a loser. **A strategy that cannot
absorb a 2× cost error has no margin of safety, and the margin of safety is
the strategy.**

---

## Summary of every corrected run

| Run | OOS net | Cost/gross | Folds + | Max DD | Coverage | Verdict |
|:---|---:|---:|:---:|---:|---:|:---|
| trend | +63.12 | 90.8% | 2/4 | 4.9% | 100% | NO_EDGE |
| breakout | +85.94 | 95.1% | 2/4 | 43.3% | 100% | NO_EDGE |
| mean_reversion | −3,282.25 | 418.1% | 2/4 | 73.6% | 100% | NO_EDGE |
| momentum | −11,938.35 | 218.1% | 0/4 | 64.9% | 100% | NO_EDGE |
| volatility | −4,775.92 | 199.5% | 1/4 | 38.6% | 100% | NO_EDGE |
| breakout + stops | +3,764.97 | 58.7% | 1/4 | 53.1% | 100% | NO_EDGE |
| breakout + stops, 8 folds | +4,610.87 | 61.2% | 2/6 | 53.1% | 100% | NO_EDGE |
| breakout + stops, 2× cost | −7,012.31 | 324.7% | 1/4 | 63.1% | 100% | NO_EDGE |
| trend + stops | +331.31 | 76.2% | 3/4 | 7.5% | 100% | EDGE_CANDIDATE |
| trend + stops, 8 folds | −389.10 | 131.5% | 3/6 | 7.5% | 100% | NO_EDGE |
| trend + stops, 2× cost | −762.06 | 155.3% | 1/4 | 10.1% | 100% | NO_EDGE |
| trend + stops, 3× cost | −1,717.35 | 276.3% | 1/4 | 8.4% | 100% | NO_EDGE |

Reports: `data/evidence/wf_*_fixed.json`.

---

## Baseline

Over the four 15% test windows, **simply holding 0.01 lot of gold lost $341**
— the windows sit after the peak. Over the eight 8% windows holding returned
**+$588.69**. Over the full 407 days holding returned **+$888.50 (+26.3%)**,
from 3,383.31 to 4,271.81.

A rule must beat the metal. Five of the ten runs above did not.

---

## Two structural limits on this evidence

* **One regime.** 407 days containing a single historic advance to a peak near
  $5,586 and the decline after it. There is no second regime in this data to
  test against, and a search for deeper public XAUUSD intraday history found
  none — the pinned mirror is refreshed daily and 14 months is its full
  extent. Any rule fitted here is fitted to one market environment.
* **Costs are assumed, never measured.** Every verdict is capped by this. Real
  costs are the difference between the best and worst rows in the cost table
  above.

## What would change the answer

1. **Measured costs.** Nothing here can become a claim while costs are
   assumed. One Windows DEMO session with `qts demo cost-check --record`
   settles it.
2. **Broker data.** Mid prices from a Dukascopy-derived feed are not the
   broker's executable prices. `qts data mt5-depth` will show whether the
   terminal itself holds ≥5,000 M15 bars.
3. **More history.** 407 days with one regime cannot distinguish a regime-fit
   from an edge.
4. ~~Finish volatility.~~ Complete — volatility reports NO_EDGE_ESTABLISHED.
   All five families are now measured; none has an edge.

## What is not claimed

No strategy is promoted. No edge is claimed. Eleven of twelve corrected
configurations report `NO_EDGE_ESTABLISHED`, and the single `EDGE_CANDIDATE`
was withdrawn by its own robustness checks — an 8-fold re-run and a 2× cost
stress — not by hand.
