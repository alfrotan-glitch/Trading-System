# Walk-forward strategy findings — real XAUUSD 15m history

**Date:** 2026-10-09
**Data:** `20261009-010+2b024334-1ba57af7` — 26,038 bars, 2025-08-06 → 2026-09-16
(407 days), 15-minute **mid** prices derived from Dukascopy bid/ask ticks via
the pinned `vudo805/forex-price-simulator` mirror at commit `4d6f155`.
**Provenance class `REAL`.**
**Cost basis:** **ASSUMED** (retail XAUUSD estimate: 3 bps spread, 2 bps
slippage, $7/lot commission). No cost has been measured on the broker.
**Verdict:** **NO EDGE ESTABLISHED.**

---

## Headline

No candidate survived. The most promising result did not survive being looked
at more closely — which is the single most useful thing this pipeline did.

Nothing here is a claim. Costs are assumed, so the pipeline refuses to make
one, and a strategy is not promoted on this evidence.

---

## The frozen candidates

Run on the full 407 days through `qts edge benchmark`, $10,000 account,
0.01 lot, no stops:

| Candidate | Role | Round turns | Gross | Cost | **Net** | Net/trade |
|:---|:---|---:|---:|---:|---:|---:|
| BENCH-A-TREND-EMA-12-48 | CANDIDATE | 912 | **−125.77** | 456.00 | **−581.77** | −0.64 |
| BENCH-B-BREAKOUT-DONCHIAN-20 | CANDIDATE | 4,999 | **−735.39** | 1,422.00 | **−2,157.39** | −0.43 |
| BENCH-C-MEANREV-BOLLINGER-20-2.0 | CONTROL | 6,289 | +81.85 | 1,609.00 | **−1,527.15** | −0.24 |

**Both candidates lose money before costs.** That is the important line. A
strategy with negative gross is not a victim of its broker — the signal has no
value, and no amount of spread negotiation rescues it. The control behaves as
a control should.

---

## Walk-forward: five established families

Parameters chosen on the training window only; reported figures are
out-of-sample. 4 folds, 15% test windows, purged and embargoed.

| Family | OOS net | Trades | Expectancy | Profitable folds | Max DD | Verdict |
|:---|---:|---:|---:|:---:|---:|:---|
| trend | +434.81 | 282 | +1.54 | 2/4 | 4.2% | NO_EDGE |
| breakout | +3,919.81 | 508 | +7.72 | 2/4 | **53.3%** | NO_EDGE |
| mean_reversion | **−6,138.51** | 1,188 | −5.17 | 1/4 | **72.6%** | NO_EDGE |
| momentum | not completed | — | — | — | — | — |
| volatility | not completed | — | — | — | — | — |

Momentum and volatility trade on nearly every bar; a full walk-forward over
26k bars did not complete in the time available. Not a result — an unfinished
run.

Drawdowns of 53% and 73% are disqualifying on their own.

---

## Adding risk management: the breakout that looked like an edge

Re-running with a **$40 stop and a 96-bar (24h) time exit** changed the
picture substantially:

| Run | OOS net | Expectancy | Profitable folds | Max DD | Verdict |
|:---|---:|---:|:---:|---:|:---|
| breakout + stops | **+5,795.42** | **+20.62** | **4/4** | 11.3% | **EDGE_CANDIDATE** |
| trend + stops | −1,401.60 | −1.33 | 1/4 | 10.5% | NO_EDGE |

Stops *improved both* return and drawdown — from +3,919 at 53% DD to +5,795 at
11% DD. All four folds independently selected `period=20`. It beat buy-and-hold
(−341 over the same windows). Costs were 10% of gross.

**It also survived a cost stress test**, which is the test that usually kills
a backtest:

| Costs | OOS net | Expectancy | Profitable folds | Max DD |
|:---|---:|---:|:---:|---:|
| 1× (3 bps) | +5,795.42 | +20.62 | 4/4 | 11.3% |
| 2× (6 bps) | +5,869.28 | +16.58 | 4/4 | 12.3% |
| 3× (9 bps) | +5,164.63 | +14.15 | 4/4 | 10.1% |

### Why it still is not an edge

Four folds at 15% each is a coarse partition. Re-running the **same
configuration** with 8 folds at 8% each:

| | 4 folds | **8 folds** |
|:---|---:|---:|
| OOS net | +5,795.42 | +3,485.45 |
| Expectancy/trade | +20.62 | **+3.09** |
| Profitable folds | 4/4 | **6/8** |
| Worst fold | +558.68 | **−2,387.74** |
| Max drawdown | 11.3% | **31.4%** |
| Verdict | EDGE_CANDIDATE | **NO_EDGE_ESTABLISHED** |

Expectancy collapses by 85% and a two-thousand-dollar losing window appears
that the coarse split averaged away. The result was **an artefact of how the
data was sliced**. This is precisely the failure the "profitable in a majority
of folds" and drawdown criteria exist to catch, and they caught it.

Contributing factors, all visible in the per-fold detail:

* **281 trades is thin**, and fold 1 contributed +2,711 from just 15 trades.
* **One regime.** The window contains one historic gold advance to $5,586 and
  the crash after it. Breakout rules thrive on exactly that. 407 days is not
  regime diversity, and this dataset contains no other regime to test.

---

## Baseline

Over the four 15% test windows, **simply holding 0.01 lot of gold lost $341**
— the windows sit after the peak. Over the full 407 days holding returned
**+$888.50 (+26.3%)**. A rule must beat the metal, and on the full period
none did.

---

## What would change the answer

1. **Measured costs.** Nothing here can become a claim while costs are
   assumed. One Windows DEMO session with `qts demo cost-check --record`
   settles it.
2. **Broker data.** Mid prices from a Dukascopy-derived feed are not the
   broker's executable prices. `qts data mt5-depth` will show whether the
   terminal itself holds ≥5,000 M15 bars.
3. **More history.** 407 days with one regime cannot distinguish a regime-fit
   from an edge.
4. **Finish momentum and volatility**, with position limits to bound the trade
   count.

## What is not claimed

No strategy is promoted. No edge is claimed. The pipeline reports
`NO_EDGE_ESTABLISHED` for every configuration tried, and the one
`EDGE_CANDIDATE` was withdrawn by its own robustness check, not by hand.
