# Preregistration — annual physical-demand seasonality in monthly gold

**ID:** `LH-XAUUSD-GOLD-CALENDAR-SEASONALITY-2026-10-19`
**Registered:** 2026-10-19, before calculating month-of-year return summaries, the candidate's seasonal outcome, or any new comparator outcome.
**Status:** `PREREGISTERED — DISCOVERY + DEVELOPMENT ONLY`.
**Parent state:** `NO_VALIDATED_EDGE`; long-history denominator `N=360`.
**This cycle:** exactly one candidate; use `N=361` for descriptive development DSR if candidate outcomes are calculated.
**Scope:** pre-2000 monthly Gold `price_nominal_usd`; discovery selection 1973–1983, confirmation 1984–1989, development 1990–1999. No post-1999 Gold price values or locked 730-day tick holdout may be read, converted, summarized, or plotted.

## 1. Hypothesis and mechanism

**Question:** Does a fixed annual gold-demand calendar produce a repeatable long-only premium in two recurring physical-demand periods, independent of the frozen gold-trend entry signal?

**Mechanism:** recurring jewelry/festival and Lunar New Year purchases may create calendar-clustered physical demand. This is a calendar-known seasonal exposure hypothesis, not a claim that the effect exists in this dataset. Earlier intraday session, weekday, and payroll-release studies tested different timing mechanisms; the repository-wide novelty scan found no monthly month-of-year rule. No eligible-period return by calendar month or candidate statistic was inspected to select this mask.

## 2. Frozen sources and boundaries

### Gold prices

- Repository: `awongstory/commodity-price-forecast-xgboost`
- Commit: `c4a9f734d92df0d0a6c4744a2d7c34417ecd074b`
- File: `data/wb_commodity_price_intelligence_1960_2026.csv`
- Git blob: `b31639d3bbf4c42ecd6406526d21bb7536e24ef9`
- Expected SHA-256: `3328bdff6156eb9ae11173ca2d52a8b207218cdd913ee0fa986be17d16e92aaf`
- Use only `commodity_name == "Gold"` and raw `price_nominal_usd` for dates before 2000-01-01. Do not use precomputed panel features. For rows dated 2000-01-01 or later, inspect only date/name as needed to skip; do not parse or convert any price cell. Record `post_1999_price_values_converted=0` and fail closed on boundary violations.

### H.10 comparator input

The only use of H.10 is to reproduce unchanged comparator `veto9`, under Amendment A1:

- Repository: `datasets/exchange-rates`
- Commit: `c023dd8b8f879610641a7391c0394c3bbb42d0f7`
- File: `data/daily.csv`
- Expected SHA-256: `68349ef41ecc0cf35fa00ba0d9d63ec93b45a5182c37d2bb9a368fcd654bfeaa`
- Use only pre-2000 values required for the unchanged eight-currency monthly USD-index builder. For rows dated 2000-01-01 or later, date/name fields may be used to skip; do not convert or use exchange-rate values. This does not reopen the rejected/inconclusive FX-dispersion hypothesis.

### Data alignment and cutoff

Use the pinned raw monthly Gold price. The monthly engine frame has `open=high=low=close=price_nominal_usd`, matching existing World Bank monthly-average studies. Keep input context from 1960-01 through 1999-12 for the 12-month volatility-sizing warmup; the executable model span is 1971-12 through 1999-12 to match `veto9` H.10 coverage. Use no post-1999 price or exchange-rate values.

## 3. One candidate and timing

### Candidate `calendar_seasonal_gold_5m`

The target is long in the fixed calendar months **January, February, March, August, and September**; it is flat in all other months. The mask is a fixed calendar rule, not estimated from or updated with historical Gold returns. At close of month `t`, determine the target for the next monthly bar from that next bar's calendar month, and execute using the existing monthly `fixed_units.v2` signal/fill convention. There are no shorts, trend confirmation, market-state gates, alternate month sets, or parameter search.

For fair comparison, size the long position using the inherited 12-month realized-volatility sizing primitive (`10%` annualized target, capped at `1.0x`, no leverage) and the existing monthly rebalance behavior; only the calendar target rule is new. Use a separate USD 10,000 account for each candidate/comparator window.

### Comparators (not new configurations)

- `ts9_lo`, unchanged.
- `veto9`, unchanged, built with the frozen H.10 comparator source and construction above.

## 4. Authorized evaluation windows

- Discovery selection: 1973-01 through 1983-12.
- Discovery confirmation: 1984-01 through 1989-12.
- Development: 1990-01 through 1999-12.
- No final/evaluation stage is authorized. Do not access or calculate any 2000+ Gold output or the locked 730-day tick holdout.

Run the candidate and both comparators on the same windows with the existing `fixed_units.v2` monthly engine. Report net/gross P&L, costs, annualized monthly Sharpe, maximum drawdown, exposure, round turns, annual returns, and paired monthly-return differences. Development DSR is descriptive at `N=361` only if candidate outcomes are calculated.

## 5. Frozen pass/fail criteria

1. **Selection and confirmation:** candidate net P&L must be positive and Sharpe must exceed each frozen comparator by at least 0.10 in both windows.
2. **Development:** candidate net P&L and Sharpe must be positive; it must beat each comparator by at least USD 500 on the separate USD 10,000 account and by at least 0.10 Sharpe; it must have at least 20 round turns and at least 6/10 positive calendar years.
3. **Cost robustness:** development net P&L must stay positive at 2× base costs and under the existing 0.25 bps/day financing sensitivity. Report 3× costs without using them to alter the gates. Costs remain ASSUMED, not measured.
4. **Paired uncertainty:** use 120 development monthly net returns, 12-month circular blocks, 9,999 bootstrap draws, seed `20261019`. For candidate-minus-each-comparator monthly returns, the one-sided 95% lower bound must exceed zero and the one-sided centered-null p-values, Holm-adjusted across the fixed two-comparator family, must each be ≤0.05.

Any source identity, schema, availability, or cutoff failure is `INCONCLUSIVE` and stops before candidate outcome calculation. Any gate failure is `REJECTED`. Do not choose alternate months, windows, sizing, lag, comparators, or costs after feature values are observed. The candidate is one configuration; comparators do not increase the candidate count. `strategy_promoted=false`, `orders_submitted=0`, `LIVE=LOCKED`, `post_1999_gold_prices_accessed=false`, and `holdout_accessed=false` must be explicit in evidence.

## 6. Freeze and execution sequence

1. Commit this protocol before calculating month-of-year return summaries, seasonal features, or candidate outcomes.
2. Add a boundary-guarded calendar signal/runner and synthetic-only tests. Test next-bar month timing, the exact five-month mask, warmup preservation, and post-1999 value exclusion without parsing those values.
3. Verify the pinned Gold and H.10 source identities. If any preflight gate fails, stop as `INCONCLUSIVE` without calculating candidate/comparator outcomes.
4. Run discovery and development exactly once. Preserve hashes and complete evidence. Do not tune, rerun, promote, submit orders, or access the locked holdout.
