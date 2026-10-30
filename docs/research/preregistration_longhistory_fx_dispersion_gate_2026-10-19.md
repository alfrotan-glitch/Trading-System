# Preregistration — Lagged FX-dispersion gate on frozen gold trend

**ID:** `LH-XAUUSD-FX-DISPERSION-GATE-2026-10-19`
**Registered:** 2026-10-19, before computing or inspecting any FX-dispersion feature value or candidate return for this hypothesis.
**Status:** `PREREGISTERED — DISCOVERY + DEVELOPMENT ONLY`. The separate CMR and Brent-gate screens are rejected; neither will be rerun, tuned, or rescued. This is a distinct currency-dispersion hypothesis, not a precious-metal basket or a CMR parameter/basket variant. No post-1999 price/rate values, 2000+ evaluation window, or locked 730-day tick partition are in scope.
**Parent research state:** `NO_VALIDATED_EDGE`, long-history cumulative `N=357`.
**This cycle:** exactly one candidate configuration; cumulative DSR denominator becomes `N=358` if evaluated. Frozen comparators do not count as new configurations.
**Candidate output:** `data/evidence/longhistory/fx_dispersion_gate_discovery_dev.json`; human report `docs/research/fx_dispersion_gate_results_2026-10-19.md`.

## 1. Question and hypothesis

Does broad **cross-sectional dispersion in 12-month foreign-exchange movements**, known with a one-month lag, condition the return of the frozen 9-month long-or-flat gold trend?

Rationale fixed before measurement: dispersion among the eight currencies' USD-relative moves can represent monetary and capital-flow dislocation not captured by the direction of an equal-weight USD index. A positive gold trend may have greater persistence when that dispersion is elevated. The test uses one fixed currency set, one horizon, one lag, one dispersion statistic, and one threshold.

**Falsification:** reject this candidate if it fails any predeclared screen gate in §5. Do not substitute a currency subset, alternate quote handling, statistic, horizon, lag, threshold, gold lookback, or position rule after measurement. A negative or inconclusive result closes this cycle.

## 2. Frozen sources, quote orientation, and data boundary

### Gold

- Repository: `https://github.com/awongstory/commodity-price-forecast-xgboost`
- Commit: `c4a9f734d92df0d0a6c4744a2d7c34417ecd074b`
- File: `data/wb_commodity_price_intelligence_1960_2026.csv`
- Expected SHA-256: `3328bdff6156eb9ae11173ca2d52a8b207218cdd913ee0fa986be17d16e92aaf`
- Use only rows with `commodity_name == Gold` and `price_nominal_usd`; do not use precomputed feature columns or any other commodity's price values. The pinned MIT repository describes monthly World Bank Pink Sheet-derived prices; this is research data, not executable broker pricing.

Only eligible dates before 2000-01-01 may have price values converted. Validate source SHA, schema, chronological unique monthly dates, positive finite eligible prices, and the complete 1960-01–1999-12 Gold span. For Gold rows dated 2000-01 or later, inspect only date and commodity-name fields to skip them; do not convert or otherwise use their price cells. Reject any return to a pre-2000 date after the first post-1999 Gold row.

### Federal Reserve H.10 currency panel

- Pinned repository: `https://github.com/datasets/exchange-rates`
- Commit: `c023dd8b8f879610641a7391c0394c3bbb42d0f7`
- File: `data/daily.csv`
- Expected SHA-256: `68349ef41ecc0cf35fa00ba0d9d63ec93b45a5182c37d2bb9a368fcd654bfeaa`
- The pinned data package identifies the source as Federal Reserve/FRED and carries a Public Domain Dedication and License. Preserve its source and quote-convention limitations.
- Use exactly these eight country series: `Australia`, `Canada`, `Denmark`, `Japan`, `New Zealand`, `Sweden`, `Switzerland`, and `United Kingdom`.
- The source data package identifies Australia, New Zealand, and the United Kingdom as quoted `USD/currency`; invert their log returns. Canada, Denmark, Japan, Sweden, and Switzerland are quoted `currency/USD`; use their log returns as published. This converts all eight to the common `currency/USD` return orientation before dispersion is calculated.

For each currency and calendar month, use its last nonblank eligible daily observation in that month; do not interpolate or carry a rate forward from a prior month. Monthly coverage preflight, using dates/country names and nonblank-cell status only (no numerical rate conversion), found at least one eligible observation for all eight currencies in each of 348 months from 1971-01 through 1999-12. If fewer than six currencies have valid paired endpoints for a signal month, the FX feature is unavailable and the candidate is flat for that month; do not change the currency set or impute missing values.

For monthly rate `q[c,m]`, form a common-orientation log level `x[c,m] = ln(q[c,m])` for the five `currency/USD` series and `x[c,m] = -ln(q[c,m])` for Australia, New Zealand, and the United Kingdom. Define the lagged cross-sectional dispersion available at decision month `t` as:

`fx_dispersion_12m_lag1(t) = population_std_c(x[c,t-1] - x[c,t-13])`

Use `ddof=0`; require at least six finite currency returns. This is the standard deviation **across currencies** of their oriented 12-month log moves, not the median/mean magnitude of those moves and not a USD-index direction signal. The one-month lag prevents use of current-month rates.

For H.10 rows dated 2000-01 or later, inspect only date and country fields to skip them; do not convert or use post-1999 rate cells. Validate source identity, chronological unique dates by country, positive finite eligible rates, and the frozen basket. No FX rates dated on or after 2000-01-01 may enter a calculation.

### Boundaries and preflight

The gold source has 480 monthly Gold rows from 1960-01 through 1999-12. H.10 has eligible observations from 1971-01 through 1999-12. Gold and FX warm-up rows before the first registered window may be used only to form the causal indicators. No values on or after 2000-01-01 are eligible. All existing 2000+ evaluation material and every 730-day MT5 tick row remain excluded; the 730-day partition stays `LOCKED_NOT_READ`.

## 3. One frozen candidate and common execution

### Candidate `fxdisp12_lag1_ge5pct_ts9_longflat`

At monthly decision month `t`, compute:

`gold_mom9(t) = ln(Gold_t / Gold_(t-9))`

`fx_dispersion_12m_lag1(t) = population_std_c(x[c,t-1] - x[c,t-13])`

Set the next monthly-bar target **long** iff `gold_mom9(t) > 0` and `fx_dispersion_12m_lag1(t) >= 0.05`; otherwise set it **flat**. `0.05` is a fixed 5-percentage-point dispersion in 12-month log returns. Ties at the gold trend boundary are flat. There are no short positions. If fewer than six valid currency returns are available, the target is flat. The gold trend, 9-month lookback, volatility sizing, and execution convention are inherited unchanged from `ts9_lo`.

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

For the candidate and both comparators, report net/gross P&L, costs, annualized monthly Sharpe, maximum drawdown, exposure, round turns, calendar-year returns, and paired monthly-return differences. Report development DSR using `N=358` as descriptive multiple-testing accounting, not as validation.

## 5. Predeclared screen gates

This is a discovery/development screen only. Passing permits consideration of a separately preregistered validation; it does not establish a validated edge, promotion, or permission to trade. The screen gates match the already-frozen long-history discovery screens.

1. **Selection and confirmation:** candidate net P&L is positive in both 1973–1983 and 1984–1989, and its annualized Sharpe exceeds **each** frozen comparator by at least 0.10 in both windows.
2. **Development survival:** in 1990–1999, candidate net P&L and annualized Sharpe are positive at base cost; candidate beats each comparator by at least USD 500 on the separate USD 10,000 account and by at least 0.10 annualized Sharpe; it has at least 20 round turns and at least 6/10 positive calendar years.
3. **Cost robustness:** development candidate net P&L remains positive at 2× base costs and under the 0.25-bps/day financing assumption. Report 3× cost but do not use it to relax gates.
4. **Paired uncertainty:** on the 120 development monthly net returns, compare candidate-minus-comparator mean return against each frozen comparator using a circular block bootstrap (12-month blocks, 9,999 draws, seed `20261019`). For each comparison, the one-sided 95% lower bound (5th percentile of the raw bootstrap mean differences) must be above zero. Compute the one-sided null p-value by centering observed monthly differences at zero, resampling with the same circular-block procedure, and using `(1 + count(boot_mean >= observed_mean)) / 10,000`; Holm-adjusted p-values across the two comparisons must each be ≤0.05. The comparator family size is fixed at two.

Any gate failure records `REJECTED`; an input/identity failure records `INCONCLUSIVE`. No alternate specification, favorable-subset analysis, or rerun under a changed formula is permitted. Every output must state `strategy_promoted=false`, `held_out_span_opened=false`, `orders_submitted=0`, and `LIVE=LOCKED`.

## 6. Trial accounting, safety, and freeze procedure

- This candidate adds exactly one trial to the long-history DSR accounting: inherited `N=357`, one new configuration, `N=358` when evaluated. Feature engineering, quote-orientation conversion, bootstrap draws, comparators, and cost stresses are parts of this single frozen configuration, not additional candidate configurations.
- Research-only. Do not edit DEMO policy, risk limits, authorization, execution code, or any LIVE lock. No broker connection, order, paper execution, or execution-readiness claim is part of this protocol.
- Freeze this file in a commit before calculating the dispersion feature or any candidate signal/outcome. Then implement a boundary-guarded runner and synthetic-only tests; verify source identity and protocol ancestry; run the authorized screen once; preserve all results.
- If the candidate survives, the next step is a new preregistered validation using genuinely new/forward data and measured costs where claimed. The reused 2000–2026 window and locked 730-day holdout are not substitutes.
