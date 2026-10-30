# Preregistration — XAUUSD Cross-Metal Relative-Momentum Screen

**ID:** `LH-XAUUSD-CMR-2026-10-19`  
**Registered:** 2026-10-19; frozen before any measurement of this candidate.  
**Status:** `PREREGISTERED — DISCOVERY + DEVELOPMENT ONLY`. No post-1999 evaluation and no 730-day tick data are in scope. The metals source has appeared in the prior post-hoc cross-metal replication of existing champions; this candidate has not been measured on it. The 1973–1999 periods are previously used discovery/development data, not an independent holdout, and are counted under inherited `N=355`.  
**Parent research state:** `NO_VALIDATED_EDGE`, cumulative `N_TRIALS = 355` (QTS control register / long-history handbook).  
**This cycle:** one fixed strategy configuration; `N_TRIALS_THIS_CYCLE = 1`; cumulative `N_TRIALS = 356`.  
**Runner:** `scripts/run_longhistory_crossmetal_relative.py` (to be implemented after this freeze).  
**Result artifact:** `data/evidence/longhistory/crossmetal_relative_discovery_dev.json` and a human report under `docs/research/`.

## 1. Question and distinct mechanism

Does **relative strength of gold against an equal-weight precious-metal basket** identify months when a long XAUUSD position is more productive than the frozen slow-trend champions?

This is a cross-market leadership mechanism, not another lookback search on gold's own trend, volatility sizing, USD veto, real-rate/inflation filter, seasonal rule, or re-expression of `ts9_lo` / `veto9`. The hypothesis is that persistent gold-specific demand, rather than a general precious-metals move, contains information about the next month's absolute gold return.

**Falsification:** reject the screen if the one frozen rule does not clear the predeclared discovery/development gates in §5. A negative or inconclusive outcome closes this cycle. No alternate basket, lookback, sign, threshold, or sizing variant may be substituted after measurement.

## 2. Frozen source and data boundary

### Metals series

- Source repository: `https://github.com/awongstory/commodity-price-forecast-xgboost`
- Commit: `c4a9f734d92df0d0a6c4744a2d7c34417ecd074b`
- File: `data/wb_commodity_price_intelligence_1960_2026.csv`
- Expected file SHA-256: `3328bdff6156eb9ae11173ca2d52a8b207218cdd913ee0fa986be17d16e92aaf`
- Licence/provenance: MIT repository licence; World Bank Pink Sheet-derived monthly averages. The repository's prior provenance check cross-validated its gold column against the pinned `datasets/gold-prices` series. This is a research source, not executable broker pricing.

The only price rows eligible for feature calculation or performance measurement are **1960-01 through 1999-12**; dates before 1973 are warm-up only. The source is grouped by commodity rather than globally chronological, so the loader must scan row identifiers/dates through the file to reach all three required series. It may convert `price_nominal_usd` to a number only for `Gold`, `Silver`, or `Platinum` rows dated before 2000-01. For every row dated on or after 2000-01, it must use only the date and commodity-name fields to skip the row; it must not convert, aggregate, plot, or otherwise use any post-1999 price value. Per-series order must be chronological; after a target series reaches 2000-01, any later return to a pre-2000 date is an integrity failure. It must fail closed on missing/duplicate required months, non-positive eligible prices, or an unrecognized schema. No gap filling, resampling beyond aligning monthly dates, or price repair is allowed.

The USD-veto comparator uses the existing pinned Federal Reserve H.10 basket construction from `datasets/exchange-rates@c023dd8b8f879610641a7391c0394c3bbb42d0f7`, file `data/daily.csv`, expected SHA-256 `68349ef41ecc0cf35fa00ba0d9d63ec93b45a5182c37d2bb9a368fcd654bfeaa`, restricted to dates through 1999-12. Its eight currencies and quote convention must match `scripts/build_longhistory_monthly_dataset.py`; no post-1999 USD observations may enter the calculation.

**Explicitly excluded:** every observation dated 2000-01 or later in the metals/FX files; the reused 2000–2026 long-history evaluation window; all 730-day MT5 tick rows, including both discovery and locked holdout. The 730-day holdout remains `LOCKED_NOT_READ`.

## 3. One frozen candidate and common execution

### Candidate `cmr12_longflat`

At each month-end `t`, compute

`R_rel12(t) = ln(Gold_t / Gold_(t-12)) - 0.5 * [ln(Silver_t / Silver_(t-12)) + ln(Platinum_t / Platinum_(t-12))]`.

The signal at `t` sets the next-month position to **long** if `R_rel12(t) > 0`, otherwise **flat** (ties are flat). It never shorts. There is one 12-month lookback, one 50/50 Silver/Platinum geometric basket, and one zero threshold; none may be searched or changed.

### Frozen comparators

Run `ts9_lo` and `veto9` verbatim as fixed comparators, not as new candidate configurations:

- `ts9_lo`: long when trailing 9-month gold return is positive, otherwise flat.
- `veto9`: 9-month gold trend; longs always follow the trend, shorts are allowed only when the 12-month equal-weight USD index strengthened, otherwise flat.

### Sizing, fills, and costs

All three rules use the existing monthly `fixed_units.v2` convention: 10% annualized gold-volatility target from trailing 12-month log-return volatility, capped at 1.0× equity, no leverage, no stop; signal at month `t` close, fill at month `t+1`'s published monthly-average price, monthly rebalance, forced flat at each window end. Each window starts a separate $10,000 account.

Primary costs are the existing `monthly_protocol.COST_BASE`: ASSUMED spread 3 bps, slippage 1 bp, commission USD 7/lot/side, and zero financing. Predeclared stress views are 2× and 3× this base cost plus the existing financing-charged assumption of 0.25 bps per calendar day. Costs are **ASSUMED**, never measured; this screen cannot establish a broker-economics claim.

## 4. Windows — no evaluation stage

- **Discovery selection:** 1973-01 through 1983-12.
- **Discovery confirmation:** 1984-01 through 1989-12.
- **Development check:** 1990-01 through 1999-12.
- **No final/evaluation window is authorized.** No metric, plot, aggregate, or intermediate result may be calculated for 2000-01 onward. The 1990s check is development evidence, not an untouched holdout or independent validation.

Report per-window net/gross P&L, costs, annualized monthly Sharpe, maximum drawdown, exposure, round turns, annual returns, and the paired monthly-return differences against each frozen comparator. Report DSR on the development window with `N=356` as a descriptive multiple-testing correction, not as a validation gate.

## 5. Predeclared screen gates

The cycle is a **discovery/development screen only**. It is eligible for a separately preregistered future validation only if every gate below passes; a pass is not a validated edge, promotion, or permission to trade.

1. **Selection and confirmation:** in both the 1973–1983 and 1984–1989 windows, candidate net P&L is positive and its annualized Sharpe exceeds **each** frozen comparator by at least 0.10.
2. **Development survival:** in 1990–1999, candidate net P&L and annualized Sharpe are positive at base cost; it beats **each** comparator by at least USD 500 on the separate $10,000 account and by at least 0.10 annualized Sharpe; it has at least 20 round turns and at least 6 of 10 positive calendar years.
3. **Cost robustness:** 1990–1999 candidate net P&L remains positive at 2× base costs and under the 0.25-bps/day financing assumption. The 3× result is reported, not used to relax any gate.
4. **Paired uncertainty:** on 1990–1999 monthly net returns, test candidate-minus-comparator mean return against each of the two frozen comparators using a circular block bootstrap (12-month blocks, 9,999 draws, seed `20261019`). For each comparison, report the one-sided 95% lower bound as the 5th percentile of the raw bootstrap mean-difference distribution. Compute the one-sided null p-value by centering the observed monthly differences at zero (`d0 = d - mean(d)`), resampling `d0` with the same circular-block procedure, and using `(1 + count(boot_mean >= observed_mean)) / 10,000`. The lower bound must be above zero for both comparisons, and Holm-adjusted p-values across the two comparisons must each be ≤0.05. The comparator family size is fixed at two.

A gate failure is recorded as `REJECTED` (or `INCONCLUSIVE` if a required input/identity gate fails). There is no parameter rescue, favorable-subset analysis, or rerun under a revised formula. All outputs must state `strategy_promoted=false`, `held_out_span_opened=false`, `orders_submitted=0`, and `LIVE=LOCKED`.

## 6. Trial accounting, safety, and next step

- Every measured strategy configuration in this cycle counts; the single candidate increments cumulative `N_TRIALS` from 355 to 356. Comparators are already counted champions. Cost stresses and bootstrap draws are not additional candidate configurations.
- The cycle is research-only. It must not edit the DEMO policy registry, risk limits, authorization, execution path, or any LIVE lock. No broker connection, order, paper execution, or execution-readiness claim is part of this protocol.
- Freeze this document in a commit before fetching/parsing the source or calculating any candidate/comparator outcome. Then implement the runner and synthetic-only tests, verify source identity, run the two authorized stages once, and preserve every result.
- If the candidate passes, the next action is a **new** preregistered validation using genuinely new/forward data and measured costs where claimed. The reused 2000–2026 window and the locked 730-day holdout are not substitutes.

## Amendment A1 — Source ordering / post-1999 access guard (2026-10-19)

**Amended before any candidate signal, return, or performance statistic was calculated.** The initial freeze is commit `a745c43`. After that commit, a metadata/schema-only read of the pinned source header and early date/commodity fields showed the CSV is grouped by commodity, so stopping globally at the first 2000 date would omit later-listed pre-2000 series. The loader rule in §2 is amended accordingly: scan only row identity/date fields as needed; convert eligible prices only for the three named metals through 1999; never numerically parse or calculate from any 2000+ price field. Candidate formula, windows, costs, thresholds, bootstrap, comparator family, and all acceptance gates are unchanged. The metadata read did not calculate any candidate feature or outcome.
