# Preregistration — Lagged Sahm unemployment-stress gate on frozen gold trend

**ID:** `LH-XAUUSD-SAHM-U3-GATE-2026-10-20`
**Registered:** 2026-10-20, before reading or converting any U3 unemployment value or calculating any candidate outcome.
**Status:** `PREREGISTERED — DISCOVERY + DEVELOPMENT ONLY`.
**Parent state:** `NO_VALIDATED_EDGE`; long-history denominator `N=361`.
**This cycle:** exactly one candidate configuration; cumulative descriptive DSR denominator becomes `N=362` only if candidate outcomes are calculated. Comparators are unchanged frozen controls and are not new candidates.
**Scope:** eligible monthly Gold and U3 inputs through 1999-12 only; discovery selection 1973–1983, confirmation 1984–1989, and development 1990–1999. No post-1999 price values, final/evaluation window, or locked 730-day tick data are in scope.
**Evidence/report if evaluated:** `data/evidence/longhistory/sahm_u3_gate_discovery_dev.json`; `docs/research/sahm_u3_gate_results_2026-10-20.md`.

## 1. Question, mechanism, and falsification

**Question:** Does a standard, lagged U.S. unemployment-stress indicator improve the frozen 9-month long-or-flat Gold trend on the authorized pre-2000 discovery and development partitions?

**Mechanism:** a material rise in the national U-3 unemployment rate above its recent low is a labor-market stress/recession-risk state. The hypothesis is that a positive Gold trend has a more favorable risk/return profile when this stress indicator is active, consistent with a safe-haven/policy-response channel. The registered indicator is the fixed 0.50-percentage-point Sahm threshold; there is no threshold search.

This is a labor-market signal, not a CPI/inflation, interest-rate, yield-curve, COT, FX, commodity-breadth, Brent, or calendar-seasonality variant. No CPI, recession-date label, H.10 feature, or post-1999 Gold price is used by the candidate. The Gold trend and all sizing/execution parameters remain unchanged.

**Falsification:** the one candidate is rejected if any gate in §5 fails. No alternative unemployment series, Sahm threshold, averaging window, release lag, Gold lookback, basket, or position rule may be substituted after measurement. A negative or inconclusive outcome closes this candidate; do not tune or rerun it on these partitions.

## 2. Frozen source identities and access boundary

### Gold and comparator input

Use the same pinned Gold price and unchanged H.10 comparator sources as the prior frozen screens:

- Gold repository: `awongstory/commodity-price-forecast-xgboost`
- Commit: `c4a9f734d92df0d0a6c4744a2d7c34417ecd074b`
- File: `data/wb_commodity_price_intelligence_1960_2026.csv`
- Git blob: `b31639d3bbf4c42ecd6406526d21bb7536e24ef9`
- Expected SHA-256: `3328bdff6156eb9ae11173ca2d52a8b207218cdd913ee0fa986be17d16e92aaf`
- Use only `commodity_name == "Gold"` and raw `price_nominal_usd` for dates before 2000-01-01. Do not use any source-panel precomputed feature.

`veto9` is reproduced unchanged under Amendment A1 from:

- H.10 repository: `datasets/exchange-rates`
- Commit: `c023dd8b8f879610641a7391c0394c3bbb42d0f7`
- File: `data/daily.csv`
- Expected SHA-256: `68349ef41ecc0cf35fa00ba0d9d63ec93b45a5182c37d2bb9a368fcd654bfeaa`
- Use only the pre-2000 values required by the existing eight-currency monthly USD-index builder. This is comparator reconstruction only and does not reopen the FX-dispersion screen.

### U.S. U-3 unemployment input

- Source mirror repository: `pmichaillat/feru`
- Pinned commit: `23d5e7795325ce1a69d02bd52e20ad075983082e`
- File: `raw/UNRATE.csv`
- Git blob SHA-1: `3e09b6924c5a010da67ffc2e850f9331bd7cdb4b`
- Expected file SHA-256: `c3be736b31e2ea488076b46190efbfa1762ea0bdf6171e92585e710523840a78`
- Schema: `DATE,UNRATE`; monthly date label and seasonally adjusted national U-3 unemployment rate in percent.
- Source README identifies the series as U.S. unemployment (U-3), source BLS (2024k), covering 1948–2024. It identifies the repository contents as MIT-licensed; the data are BLS source data, not original repository code. No separate point-in-time vintage file is included.

The metadata-only source preflight verified the pinned file hash, header, monthly date labels, and date coverage without converting or displaying a U3 value: 624 date rows from 1948-01 through 1999-12, including 324 monthly date labels from 1973-01 through 1999-12. The source snapshot also contains dates after 1999; for any row dated 2000-01-01 or later, the runner may inspect only `DATE` to skip it and must not read, parse, aggregate, plot, or convert `UNRATE`.

BLS is the stated upstream source. This protocol uses only the underlying public statistical series for internal research; it does not copy the source CSV into Git or use the repository's MATLAB code. The source repository provides no real-time revision history. Thus the pinned U3 snapshot is a revised historical series, and the screen is a retrospective association test—not a point-in-time simulation or production signal. If the candidate survives the screen, any new validation must first obtain licensed, point-in-time unemployment vintages and measured costs. No edge, causal, or live-trading claim is authorized here.

### Strict price/value boundary

For Gold and H.10, follow the existing date-first boundary guards: on rows dated 2000-01-01 or later, inspect only date/name fields needed to skip; do not convert any price or FX value. For U3, inspect only `DATE` on rows dated 2000-01-01 or later; do not access or convert `UNRATE`. The loader must record zero post-1999 Gold-price, H.10-rate, and U3 values converted. No 2000+ evaluation metric, visualization, final stage, 730-day tick row, or holdout partition may be opened.

## 3. One frozen candidate, timing, and comparators

### Candidate `sahm_u3_ts9_longflat`

Let `u_m` be the U-3 rate for reference month `m`, in percentage points. At Gold decision month `t`, use only the U3 observation for `s = t-2`, a two-full-calendar-month release lag. Define:

`u3_avg(s) = mean(u_s, u_(s-1), u_(s-2))`

`sahm_gap(s) = u3_avg(s) - min(u3_avg(s-j) for j = 1,...,12)`

`gold_mom9(t) = ln(Gold_t / Gold_(t-9))`

For the next monthly bar, target **long** iff `gold_mom9(t) > 0` and `sahm_gap(t-2) >= 0.50` percentage points; otherwise target **flat**. Ties in Gold momentum are flat. There are no short positions. No missing unemployment month may be interpolated, forward-filled, or silently dropped. The two-month release lag is fixed to keep the latest unemployment month used safely behind the month-end Gold decision; it does not correct historical data revisions.

### Frozen comparators (unchanged, not new configurations)

- `ts9_lo`: long if the trailing 9-month Gold return is positive; otherwise flat.
- `veto9`: frozen 9-month Gold trend with the existing 12-month equal-weight H.10 USD veto and short rule.

### Sizing, fills, and costs

Use the existing monthly `fixed_units.v2` convention verbatim: 10% annualized Gold-volatility target using trailing 12-month log-return volatility, capped at 1.0× equity, no leverage, no stop; signal at month `t` close, fill at month `t+1` published monthly-average price, rebalance monthly, and force flat at each window end. Each window starts a separate USD 10,000 account.

Use the existing `monthly_protocol.COST_BASE`: ASSUMED 3 bps spread, 1 bp slippage, USD 7/lot/side commission, zero financing. Report the frozen 2× and 3× base-cost stresses and the existing financing sensitivity of 0.25 bps per calendar day. Costs are ASSUMED, not measured.

## 4. Authorized windows and reporting

- **Discovery selection:** 1973-01 through 1983-12.
- **Discovery confirmation:** 1984-01 through 1989-12.
- **Development:** 1990-01 through 1999-12.
- **No final/evaluation stage.** The 1990s are reused development evidence, not an untouched holdout.

Run the one candidate and both unchanged comparators on identical authorized windows, with separate USD 10,000 accounts. Report net/gross P&L, costs, annualized monthly Sharpe, maximum drawdown, exposure, round turns, calendar-year returns, and paired monthly-return differences. Development DSR at `N=362` is descriptive multiple-testing accounting only, not validation. Do not calculate any metric for 2000-01 or later.

## 5. Frozen screen gates

This is a discovery/development screen only. Even a pass would permit consideration of a separately preregistered validation; it would not establish an edge, eligibility for DEMO/LIVE, promotion, or permission to trade.

1. **Selection and confirmation:** candidate net P&L is positive and annualized Sharpe exceeds each frozen comparator by at least 0.10 in both windows.
2. **Development survival:** candidate net P&L and Sharpe are positive; it beats each comparator by at least USD 500 on the separate USD 10,000 account and by at least 0.10 annualized Sharpe; it has at least 20 round turns and at least 6/10 positive calendar years.
3. **Cost robustness:** development net P&L remains positive at 2× base costs and under the 0.25-bps/day financing assumption. Report 3× costs, but do not use them to change gates.
4. **Paired uncertainty:** on the 120 development monthly net returns, compare candidate-minus-comparator means using a circular block bootstrap with 12-month blocks, 9,999 draws, and seed `20261020`. For both comparators, the one-sided 95% lower bound (5th percentile of raw bootstrap mean differences) must exceed zero. Calculate one-sided centered-null p-values with the same circular-block procedure and `(1 + count(bootstrap_mean >= observed_mean)) / 10,000`; Holm-adjust across the fixed two-comparator family, and require each adjusted p-value ≤0.05.

Any identity/schema/coverage/boundary failure is `INCONCLUSIVE` and stops before candidate outcome calculation. Any gate failure is `REJECTED`. No alternate signal threshold, lag, source, window, comparator, or parameter variant may be substituted after feature values are observed. Evidence must state `strategy_promoted=false`, `orders_submitted=0`, `LIVE=LOCKED`, `post_1999_gold_prices_accessed=false`, `post_1999_u3_values_converted=0`, and `holdout_accessed=false`.

## 6. Freeze and run sequence

1. Commit this protocol before reading any U3 numerical value or calculating candidate/comparator outcomes.
2. Add a boundary-guarded U3/Gold loader, the single fixed candidate, an evidence-producing runner, and synthetic-only tests. Tests must cover the exact Sahm 0.50 threshold, two-month lag, missing U3 data, warmup, comparator preservation, and post-1999 U3/Gold exclusion without converting those values.
3. Verify all pinned source identities and date/schema coverage. If any preflight gate fails, stop as `INCONCLUSIVE` without calculating candidate/comparator outcomes.
4. Run authorized selection, confirmation, and development once. Preserve the source hashes and full evidence. Do not tune, rerun, promote, submit orders, access evaluation data, or open the locked holdout.
