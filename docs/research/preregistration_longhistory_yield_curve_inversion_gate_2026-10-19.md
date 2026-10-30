# Preregistration — US yield-curve inversion gate on frozen gold trend

**ID:** `LH-XAUUSD-YC-INVERSION-GATE-2026-10-19`
**Registered:** 2026-10-19, before opening the federal-funds CSV or calculating any term-spread feature or new candidate outcome.
**Status:** `PREREGISTERED — DISCOVERY + DEVELOPMENT ONLY`.
**Parent state:** `NO_VALIDATED_EDGE`; long-history denominator `N=359`.
**This cycle:** exactly one candidate; use `N=360` for descriptive DSR and trial accounting if outcomes are calculated.
**Scope:** pre-2000 monthly gold prices only; authorized windows are 1973–1989 discovery and 1990–1999 development. No 2000+ gold-price values or locked 730-day holdout may be read, converted, summarized, or plotted.

## 1. Hypothesis and mechanism

**Question:** Does a lagged US Treasury yield-curve inversion identify a financial-tightness/recession-risk regime in which the frozen nine-month long-only gold trend has better net returns?

**Mechanism:** the spread between the 10-year Treasury constant-maturity yield and the effective federal funds rate measures the curve relative to the current overnight policy rate. A negative spread is a distinct term-structure state, not 10-year yield momentum or a CPI-derived real-rate filter. The hypothesis is that gold's safe-haven trend is more useful when this policy/term-structure spread is inverted.

This is one fixed causal hypothesis, not a lookback or threshold search. The repository-wide novelty scan found no prior registered term-spread/inversion candidate. Existing CMR, Brent, FX-dispersion, commodity-breadth, CPI/inflation, and Wave-10 yield-momentum/real-rate results remain closed to tuning or rescue.

## 2. Frozen sources, attribution, and boundaries

### Gold prices

- Repository: `awongstory/commodity-price-forecast-xgboost`
- Commit: `c4a9f734d92df0d0a6c4744a2d7c34417ecd074b`
- File: `data/wb_commodity_price_intelligence_1960_2026.csv`
- Git blob: `b31639d3bbf4c42ecd6406526d21bb7536e24ef9`; previously reconciled SHA-256: `3328bdff6156eb9ae11173ca2d52a8b207218cdd913ee0fa986be17d16e92aaf`
- Use only `commodity_name == "Gold"` and raw `price_nominal_usd` for dates before 2000-01-01. Do not use any precomputed panel feature. For rows dated 2000-01-01 or later, inspect only date/name as needed to skip; do not parse or convert any price cell. The loader must record `post_1999_price_values_converted=0` and fail closed on boundary violations.

### 10-year yield

- Repository: `datasets/bond-yields-us-10y`
- Commit: `238315525deafefcf8334536990cafe23dc5eac4`
- File: `data/monthly.csv`
- Git blob: `873ccc4e9c90ab9e5b79e326a6af5d9ccda8856f`
- README identifies the series as the Federal Reserve H.15 monthly 10-year US Treasury yield; package metadata declares ODC-PDDL. Use the raw monthly 10-year yield and no other series.

### Effective federal funds rate

- Repository snapshot: `OpenSourceEcon/FedFundsPlot`
- Commit: `167fd89006994f09f482b9e3c1ad23fecf276416`
- File: `data/ffrates_2022-07-29.csv`
- Git blob: `df041eca9aee2e860b9d7cf1365f3ec960d525e9`; 539,244 bytes
- Its code identifies the effective-rate input as FRED series `DFF` and states that its data are downloaded from FRED. Use only the `DFF` series, not target-rate series. The file name and commit pin a fixed July 2022 snapshot; per-observation vintage/revision history is not available.
- The repository has no license metadata/file. This protocol uses the underlying Federal Reserve series as publicly available federal statistical data for **internal research only**, with attribution to the Board of Governors/FRED; it does not use or redistribute repository code or copy the rate file into Git. This is not a commercial data-rights determination. Any promotion, redistribution, or production use remains blocked until the applicable source terms and vintage are confirmed. The candidate may still be falsified in a research-only screen; the limitation must be carried into the report.

### Data alignment and cutoff

Convert only eligible pre-2000 observations. Average the daily `DFF` observations by calendar month; use the H.15 monthly 10-year observation as supplied. Join on calendar month and require both series and gold to be finite/complete for each authorized feature month. The eligible price/rate cutoff is 1999-12-31. No 2000+ gold price values are permitted. No 2000+ rates are needed or permitted in this run either.

## 3. One candidate, frozen comparators, and timing

### Candidate `yc_inversion_ts9_lo`

For calendar month `t`, calculate the prior-complete-month spread:

`spread_lag1(t) = GS10_monthly_mean(t-1) - DFF_monthly_mean(t-1)`

Rates are in percentage points. The spread is inverted only when it is **strictly below zero**; zero is not inverted. Use the inherited `ts9_lo` nine-month gold-trend signal verbatim. For the next monthly bar, target long iff both (a) `ts9_lo` is long and (b) `spread_lag1(t) < 0`; otherwise target flat. There are no shorts, alternative thresholds, extra lags, or additional gates. This uses only rate information from the prior complete month.

### Comparators (not new configurations)

- `ts9_lo`, unchanged.
- `veto9`, unchanged, as a secondary frozen reference.

Use the existing monthly `fixed_units.v2` execution, sizing, signal/fill timing, account reset, and cost assumptions verbatim. Do not modify base parameters. Report base costs, the existing 2× and 3× cost stresses, and the fixed financing sensitivity; costs remain ASSUMED, not measured.

## 4. Authorized evaluation windows

- Discovery selection: 1973-01 through 1983-12.
- Discovery confirmation: 1984-01 through 1989-12.
- Development: 1990-01 through 1999-12.
- No final/evaluation stage is authorized. Do not open or compute any 2000+ gold-price output or the locked 730-day tick holdout.

Run the candidate and both comparators on the same windows, each with a separate USD 10,000 account. Report net/gross P&L, costs, monthly annualized Sharpe, maximum drawdown, exposure, round turns, annual returns, and paired monthly-return differences. Development DSR is descriptive at `N=360` only.

## 5. Frozen pass/fail criteria

This is a discovery/development screen, not validation or permission to trade.

1. **Selection and confirmation:** candidate net P&L must be positive and Sharpe must exceed each frozen comparator by at least 0.10 in both windows.
2. **Development:** candidate net P&L and Sharpe must be positive; it must beat each comparator by at least USD 500 on the separate USD 10,000 account and by at least 0.10 Sharpe; it must have at least 20 round turns and at least 6/10 positive calendar years.
3. **Cost robustness:** development net P&L must stay positive at 2× base costs and under the existing 0.25 bps/day financing sensitivity. Report 3× costs without using them to alter the gates.
4. **Paired uncertainty:** use 120 development monthly net returns, 12-month circular blocks, 9,999 bootstrap draws, seed `20261019`. For candidate-minus-each-comparator monthly returns, the one-sided 95% lower bound must exceed zero and the one-sided centered-null p-values, Holm-adjusted across the fixed two-comparator family, must each be ≤0.05.

Any input identity, schema, availability, or cutoff failure is `INCONCLUSIVE` and stops before candidate outcome calculation. Any gate failure is `REJECTED`. No alternate spread sign, threshold, averaging convention, lag, comparator, or parameter variant is allowed after the values are observed. `strategy_promoted=false`, `orders_submitted=0`, `LIVE=LOCKED`, `post_1999_gold_prices_accessed=false`, and `holdout_accessed=false` must be explicit in evidence.

## 6. Freeze and execution sequence

1. Commit this protocol before fetching/opening any of its rate data or measuring the candidate.
2. Add a boundary-guarded loader and runner plus synthetic-only tests. Tests must cover exact zero vs negative spreads, one-month lag, missing values, and exclusion of post-1999 gold-price cells without converting them.
3. Verify all three pinned source identities. If any gate fails, stop as `INCONCLUSIVE` without calculating candidate/comparator outcomes.
4. Run the authorized discovery and development stages exactly once. Preserve raw source hashes and complete evidence. Do not tune, rerun, promote, submit orders, or access the locked holdout.
