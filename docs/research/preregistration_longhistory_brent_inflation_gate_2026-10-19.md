# Preregistration — Lagged Brent-inflation gate on frozen gold trend

**ID:** `LH-XAUUSD-BRENT-GATE-2026-10-19`
**Registered:** 2026-10-19; before reading any Brent or candidate return values.
**Status:** `PREREGISTERED — DISCOVERY + DEVELOPMENT ONLY`. The prior cross-metal relative-momentum cycle remains rejected and will not be rerun, tuned, or rescued. No post-1999 price values, the 2000+ evaluation window, or the locked 730-day tick partition are in scope.
**Parent research state:** `NO_VALIDATED_EDGE`, long-history cumulative `N=356`.
**This cycle:** exactly one candidate configuration; cumulative DSR denominator becomes `N=357` if evaluated. Comparators are frozen champions and do not count as new configurations.
**Input boundary:** same pinned World Bank Pink Sheet-derived monthly source used by prior long-history work; gold is the traded series, and Brent crude is one lagged macro-conditioning series. This is not a precious-metal basket or an alternate CMR basket.
**Candidate output:** `data/evidence/longhistory/brent_gate_discovery_dev.json`; human report `docs/research/brent_gate_results_2026-10-19.md`.

## 1. Question and hypothesis

Does a **lagged Brent-oil inflation-persistence gate** improve the frozen 9-month long-or-flat gold trend?

Rationale fixed before measurement: persistent energy-price increases can signal inflationary pressure and demand for monetary hedges. One World Bank Pink Sheet series, one 12-month horizon, one sign threshold, and one lag are fixed below. The candidate is a new macro-conditioning mechanism, not an attempt to rescue the rejected gold-versus-silver/platinum relative-strength screen.

**Falsification:** reject this one candidate if it fails any predeclared screen gate in §5. No second oil series, commodity basket, sign, horizon, threshold, position rule, or sizing variant may be substituted after measurement. A negative or inconclusive result closes this cycle.

## 2. Frozen source and data boundary

### Gold and Brent

- Repository: `https://github.com/awongstory/commodity-price-forecast-xgboost`
- Commit: `c4a9f734d92df0d0a6c4744a2d7c34417ecd074b`
- File: `data/wb_commodity_price_intelligence_1960_2026.csv`
- Expected SHA-256: `3328bdff6156eb9ae11173ca2d52a8b207218cdd913ee0fa986be17d16e92aaf`
- License/provenance: MIT repository; monthly World Bank Pink Sheet-derived prices. This is research data, not executable broker pricing.
- Registered commodity identifiers: `Gold` and `Crude oil, Brent`; use only `price_nominal_usd`. Do not use any precomputed momentum, volatility, regime, or index columns in the wide source.

The metadata-only coverage check found 480 monthly rows for each registered series from 1960-01 through 1999-12. The only eligible numerical price rows are dates before 2000-01-01; earlier eligible rows are warm-up only. The loader must validate the exact file SHA, expected schema, chronological unique monthly dates, positive finite eligible prices, and complete 1960-01–1999-12 spans. For rows dated 2000-01 or later, it may inspect only date and commodity-name fields to skip them; it must not convert, aggregate, plot, or otherwise use any post-1999 price value. For each registered series, any return to a pre-2000 date after its first post-1999 row is an integrity failure. No resampling, gap filling, price repair, or alternate series is allowed.

### USD comparator input

`veto9` uses the existing pinned Federal Reserve H.10 eight-currency basket, unchanged: `datasets/exchange-rates@c023dd8b8f879610641a7391c0394c3bbb42d0f7`, `data/daily.csv`, SHA-256 `68349ef41ecc0cf35fa00ba0d9d63ec93b45a5182c37d2bb9a368fcd654bfeaa`. Use the existing H.10 construction and pre-2000 boundary checks; no post-1999 rate value may enter a calculation.

**Explicit exclusions:** all price/rate observations dated 2000-01 or later; the reused 2000–2026 evaluation window; every 730-day MT5 tick, including discovery and locked partitions. The 730-day holdout remains `LOCKED_NOT_READ`.

## 3. One frozen candidate and common execution

### Candidate `brent12_lag1_ts9_longflat`

At monthly decision month `t`, define the gold trend and lagged Brent state:

`gold_mom9(t) = ln(Gold_t / Gold_(t-9))`

`brent_mom12_lag1(t) = ln(Brent_(t-1) / Brent_(t-13))`

Set the target for the next monthly bar to **long** iff both values are strictly positive; otherwise set it **flat**. Ties are flat. There are no short positions. The one-month Brent lag is fixed to avoid using the current-month oil average as a contemporaneous gate. The gold trend, 9-month lookback, volatility sizing, and execution convention are inherited unchanged from `ts9_lo`.

### Frozen comparators

Run the following unchanged as references, not as new candidate configurations:

- `ts9_lo`: long if trailing 9-month gold return is positive, otherwise flat.
- `veto9`: 9-month gold trend; longs follow the trend, and shorts are allowed only when the 12-month equal-weight USD index strengthened, otherwise flat.

### Sizing, fills, and costs

Use the existing monthly `fixed_units.v2` convention: 10% annualized gold-volatility target using trailing 12-month log-return volatility, capped at 1.0× equity, no leverage, no stop; signal at month `t` close, fill at month `t+1`'s published monthly-average price, monthly rebalance, and force flat at each window end. Each window starts a separate USD 10,000 account.

Primary costs are the existing `monthly_protocol.COST_BASE`: ASSUMED 3 bps spread, 1 bp slippage, USD 7/lot/side commission, zero financing. Report the predeclared 2× and 3× base-cost stresses and the existing financing assumption of 0.25 bps per calendar day. Costs are ASSUMED, not measured; no broker-economics claim is authorized.

## 4. Windows — no evaluation stage

- **Discovery selection:** 1973-01 through 1983-12.
- **Discovery confirmation:** 1984-01 through 1989-12.
- **Development:** 1990-01 through 1999-12.
- **No final/evaluation window is authorized.** The 1990s are reused development evidence, not an untouched holdout. No metric, plot, aggregate, or intermediate result may be calculated on 2000-01 onward.

For the candidate and both comparators, report net/gross P&L, costs, annualized monthly Sharpe, maximum drawdown, exposure, round turns, calendar-year returns, and paired monthly-return differences. Report development DSR using `N=357` as descriptive multiple-testing accounting, not as validation.

## 5. Predeclared screen gates

This is a discovery/development screen only. Passing permits consideration of a separately preregistered validation; it does not establish a validated edge, promotion, or permission to trade. Thresholds intentionally match the previous frozen screen and are not relaxed.

1. **Selection and confirmation:** candidate net P&L is positive in both 1973–1983 and 1984–1989, and its annualized Sharpe exceeds **each** frozen comparator by at least 0.10 in both windows.
2. **Development survival:** in 1990–1999, candidate net P&L and annualized Sharpe are positive at base cost; candidate beats each comparator by at least USD 500 on the separate USD 10,000 account and by at least 0.10 annualized Sharpe; it has at least 20 round turns and at least 6/10 positive calendar years.
3. **Cost robustness:** development candidate net P&L remains positive at 2× base costs and under the 0.25-bps/day financing assumption. Report 3× cost but do not use it to relax gates.
4. **Paired uncertainty:** on the 120 development monthly net returns, compare candidate-minus-comparator mean return against each of the two frozen comparators using a circular block bootstrap (12-month blocks, 9,999 draws, seed `20261019`). For each comparison, the one-sided 95% lower bound (5th percentile of the raw bootstrap mean differences) must be above zero. Compute the one-sided null p-value by centering observed monthly differences at zero, resampling with the same circular-block procedure, and using `(1 + count(boot_mean >= observed_mean)) / 10,000`; Holm-adjusted p-values across the two comparisons must each be ≤0.05. The comparator family size is fixed at two.

Any gate failure records `REJECTED`; an input/identity failure records `INCONCLUSIVE`. No alternate specification, favorable-subset analysis, or rerun under a changed formula is permitted. Every output must state `strategy_promoted=false`, `held_out_span_opened=false`, `orders_submitted=0`, and `LIVE=LOCKED`.

## 6. Trial accounting, safety, and freeze procedure

- This candidate adds exactly one trial to long-history DSR accounting: inherited `N=356`, one new candidate, `N=357` when evaluated. Feature engineering choices, bootstrap draws, comparators, and stress views are not extra candidate configurations.
- Research-only. Do not edit DEMO policy, risk limits, authorization, execution code, or any LIVE lock. No broker connection, order, paper execution, or execution-readiness claim is part of this protocol.
- Freeze this file in a commit before reading any Brent/gold price value for this hypothesis or calculating signals/outcomes. Then implement a boundary-guarded runner and synthetic-only tests; verify source identity; run the authorized stages once; preserve all results.
- If the candidate survives, the next step is a new preregistered validation using genuinely new/forward data and measured costs where claimed. The reused 2000–2026 window and locked 730-day holdout are not substitutes.
