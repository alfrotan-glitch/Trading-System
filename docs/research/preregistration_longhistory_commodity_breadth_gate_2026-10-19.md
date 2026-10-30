# Preregistration — Broad non-energy commodity-breadth gate on frozen gold trend

**ID:** `LH-XAUUSD-COMMODITY-BREADTH-GATE-2026-10-19`
**Registered:** 2026-10-19, before converting any eligible price values for this candidate or computing its breadth feature/returns.
**Status:** `PREREGISTERED — DISCOVERY + DEVELOPMENT ONLY`. The CMR and Brent-gate candidates remain rejected; the separate FX-dispersion run is inconclusive for its intended hypothesis after a quote-convention conflict. This cycle is a distinct broad non-energy commodity-breadth mechanism: it is not a precious-metal basket/CMR variant, and it excludes all crude-oil and natural-gas series, so it does not rerun or tune the Brent gate. No post-1999 price values, 2000+ evaluation window, or locked 730-day tick partition are in scope.
**Parent research state:** `NO_VALIDATED_EDGE`, long-history cumulative `N=358`.
**This cycle:** exactly one candidate configuration; cumulative DSR denominator becomes `N=359` if evaluated. Frozen comparators do not count as new configurations.
**Candidate output:** `data/evidence/longhistory/commodity_breadth_gate_discovery_dev.json`; human report `docs/research/commodity_breadth_gate_results_2026-10-19.md`.

## 1. Question and hypothesis

Does **broad positive 12-month price breadth among non-energy, non-precious commodities**, known with a one-month lag, condition the return of the frozen 9-month long-or-flat gold trend?

Rationale fixed before measurement: breadth across unrelated real-economy commodity prices can indicate a generalized reflation/inflation regime more robustly than one oil series. Gold's positive trend may persist more reliably when a clear supermajority of non-energy commodity prices is also rising. This uses only raw monthly nominal USD prices and computes the signal causally; it does not use the panel's precomputed momentum, volatility, regime, or index columns.

**Falsification:** reject this one candidate if it fails any predeclared screen gate in §5. Do not substitute a different commodity set, category mapping, lag, lookback, breadth fraction, gold rule, or position rule after measurement. A negative or inconclusive result closes this cycle.

## 2. Frozen source and exact 42-series breadth basket

- Repository: `https://github.com/awongstory/commodity-price-forecast-xgboost`
- Commit: `c4a9f734d92df0d0a6c4744a2d7c34417ecd074b`
- File: `data/wb_commodity_price_intelligence_1960_2026.csv`
- Expected SHA-256: `3328bdff6156eb9ae11173ca2d52a8b207218cdd913ee0fa986be17d16e92aaf`
- The pinned repository is MIT-licensed and identifies the monthly input as World Bank Pink Sheet-derived prices. This is research data, not executable broker pricing.
- The pinned CSV is a single later snapshot: its schema has retrieval/build metadata but no historical release/vintage field. Results are retrospective associations, not a claim that these values were available at each historical decision time.
- Traded series: `Gold` only. The candidate feature basket is exactly the following 42 `commodity_name` series:

`Aluminum`; `Banana, US`; `Barley`; `Beef`; `Chicken`; `Cocoa`; `Coconut oil`; `Coffee, Arabica`; `Coffee, Robusta`; `Copper`; `Cotton, A Index`; `Groundnut oil`; `Iron ore, cfr spot`; `Lead`; `Logs, Malaysian`; `Maize`; `Nickel`; `Orange`; `Palm oil`; `Phosphate rock`; `Potassium chloride`; `Rice, Thai 5%`; `Rubber, RSS3`; `Sawnwood, Malaysian`; `Shrimps, Mexican`; `Sorghum`; `Soybean meal`; `Soybean oil`; `Soybeans`; `Sugar, EU`; `Sugar, US`; `Sugar, world`; `TSP`; `Tea, Colombo`; `Tea, Kolkata`; `Tea, Mombasa`; `Tea, avg 3 auctions`; `Tin`; `Tobacco, US import u.v.`; `Urea`; `Wheat, US HRW`; `Zinc`.

The frozen inclusion rule is metadata-only: include every series having exactly one first-of-month date for each of the 480 months from 1960-01 through 1999-12, then exclude `Gold`, `Silver`, `Platinum`, and every name beginning `Crude oil,` or `Natural gas,`. The pre-registration scan inspected only dates and commodity names for this coverage rule; it found 50 full-span series, of which the explicit exclusions leave 42. A separate metadata-only presence check confirms all 480 eligible price cells are nonblank for Gold and each of the 42 basket series; it converted no price values and accessed no post-1999 price cells. Do not use `category` (the source labels are inconsistent across commodity names), `commodity_code`, `data_source`, any precomputed feature, or a data-dependent constituent selection. Each of the 42 named series receives one equal breadth vote, regardless of its unit, country, or source category.

Use only rows with a registered `commodity_name` and `price_nominal_usd`. Do not use `price_mom_pct`, `price_yoy_pct`, `price_mom_abs`, rolling-average/volatility columns, index columns, regime flags, or any other precomputed feature. Validate source SHA, schema, chronological unique monthly dates within each registered series, positive finite eligible prices, and the complete 1960-01–1999-12 span for Gold and every one of the 42 breadth series. For target rows dated 2000-01 or later, inspect only date and commodity-name fields to skip them; do not convert, aggregate, plot, or otherwise use their price cells. Since the file is long-form and grouped by commodity, continue scanning identity/date fields to reach all registered series. No resampling, interpolation, missing-price repair, or alternate series is allowed.

### Frozen causal feature

For each breadth series `c` and decision month `t`, compute its lagged 12-month log return:

`r[c,t] = ln(Price[c,t-1] / Price[c,t-13])`

Define breadth as:

`commodity_breadth_12m_lag1(t) = count_c(r[c,t] > 0) / 42`

The breadth gate passes iff at least 28 of 42 registered series have strictly positive lagged returns (`breadth >= 2/3`). Zero returns do not count as positive. The fixed one-month lag excludes the current month. If any registered price or paired endpoint is unavailable, fail closed; do not calculate breadth from a partial or substituted basket.

## 3. One frozen candidate and common execution

### Candidate `commodity_breadth12_lag1_ge2thirds_ts9_longflat`

At monthly decision month `t`, set the next monthly-bar target **long** iff both conditions hold:

1. `ln(Gold_t / Gold_(t-9)) > 0`; and
2. `commodity_breadth_12m_lag1(t) >= 2/3` (at least 28 of the fixed 42 non-energy/non-precious series have positive 12-month log returns ending at `t-1`).

Otherwise set the target **flat**. Ties in gold momentum are flat. There are no short positions. The gold trend, 9-month lookback, volatility sizing, and execution convention are inherited unchanged from `ts9_lo`.

### Frozen comparators

Run the following unchanged as references, not as new candidate configurations:

- `ts9_lo`: long if trailing 9-month gold return is positive, otherwise flat.
- `veto9`: frozen 9-month gold trend with the existing 12-month equal-weight H.10 USD-index veto and short rule.

### Sizing, fills, and costs

Use the existing monthly `fixed_units.v2` convention: 10% annualized gold-volatility target using trailing 12-month log-return volatility, capped at 1.0× equity, no leverage, no stop; signal at month `t` close, fill at month `t+1`'s published monthly-average price, monthly rebalance, and force flat at each window end. Each window starts a separate USD 10,000 account.

Primary costs are the existing `monthly_protocol.COST_BASE`: ASSUMED 3 bps spread, 1 bp slippage, USD 7/lot/side commission, zero financing. Report the predeclared 2× and 3× base-cost stresses and the existing financing assumption of 0.25 bps per calendar day. Costs are ASSUMED, not measured; no broker-economics claim is authorized.

## 4. Windows — no evaluation stage

- **Discovery selection:** 1973-01 through 1983-12.
- **Discovery confirmation:** 1984-01 through 1989-12.
- **Development:** 1990-01 through 1999-12.
- **No final/evaluation window is authorized.** The 1990s are reused development evidence, not an untouched holdout. No metric, plot, aggregate, or intermediate result may be calculated on 2000-01 onward.

For the candidate and both comparators, report net/gross P&L, costs, annualized monthly Sharpe, maximum drawdown, exposure, round turns, calendar-year returns, and paired monthly-return differences. Report development DSR using `N=359` as descriptive multiple-testing accounting, not as validation.

## 5. Predeclared screen gates

This is a discovery/development screen only. Passing permits consideration of a separately preregistered validation; it does not establish a validated edge, promotion, or permission to trade. The gates match the already-frozen long-history discovery screens.

1. **Selection and confirmation:** candidate net P&L is positive in both 1973–1983 and 1984–1989, and its annualized Sharpe exceeds **each** frozen comparator by at least 0.10 in both windows.
2. **Development survival:** in 1990–1999, candidate net P&L and annualized Sharpe are positive at base cost; candidate beats each comparator by at least USD 500 on the separate USD 10,000 account and by at least 0.10 annualized Sharpe; it has at least 20 round turns and at least 6/10 positive calendar years.
3. **Cost robustness:** development candidate net P&L remains positive at 2× base costs and under the 0.25-bps/day financing assumption. Report 3× cost but do not use it to relax gates.
4. **Paired uncertainty:** on the 120 development monthly net returns, compare candidate-minus-comparator mean return against each frozen comparator using a circular block bootstrap (12-month blocks, 9,999 draws, seed `20261019`). For each comparison, the one-sided 95% lower bound (5th percentile of the raw bootstrap mean differences) must be above zero. Compute the one-sided null p-value by centering observed monthly differences at zero, resampling with the same circular-block procedure, and using `(1 + count(boot_mean >= observed_mean)) / 10,000`; Holm-adjusted p-values across the two comparisons must each be ≤0.05. The comparator family size is fixed at two.

Any gate failure records `REJECTED`; an input/identity failure records `INCONCLUSIVE`. No alternate specification, favorable-subset analysis, or rerun under a changed formula is permitted. Every output must state `strategy_promoted=false`, `held_out_span_opened=false`, `orders_submitted=0`, and `LIVE=LOCKED`.

## 6. Trial accounting, safety, and freeze procedure

- This candidate adds exactly one trial to the long-history DSR accounting: inherited `N=358`, one new configuration, `N=359` when evaluated. The fixed basket, breadth calculation, bootstrap draws, comparators, and cost stresses are parts of this single frozen configuration, not additional candidate configurations.
- Research-only. Do not edit DEMO policy, risk limits, authorization, execution code, or any LIVE lock. No broker connection, order, paper execution, or execution-readiness claim is part of this protocol.
- Freeze this file in a commit before converting any eligible commodity price values for this hypothesis or calculating its breadth/signal/outcome. Then implement a raw-price-only boundary-guarded runner and synthetic-only tests; verify source identity and protocol ancestry; run the authorized screen once; preserve all results.
- If the candidate survives, the next step is a new preregistered validation using genuinely new/forward data and measured costs where claimed. The reused 2000–2026 window and locked 730-day holdout are not substitutes.

## Amendment A1 — source-vintage limitation (pre-measurement)

After the initial protocol commit, a schema-only review confirmed that the pinned commodity CSV has retrieval/build metadata but no historical release/vintage timestamp. This is recorded as a limitation: a one-month lag is a causal formula on the stored monthly dates, but the file cannot prove point-in-time publication availability. The candidate, 42-series basket, threshold, windows, costs, and gates are unchanged. This amendment was added before any eligible price value or candidate feature/return was calculated.
