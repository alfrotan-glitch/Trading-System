# Preregistration — Lagged US CPI-acceleration gate on frozen gold trend

- **ID:** `LH-XAUUSD-CPI-ACCELERATION-GATE-2026-10-19`
- **Registered:** 2026-10-19, before inspecting numerical CPI or candidate-return values for this hypothesis.
- **Status:** `PREREGISTERED — DISCOVERY + DEVELOPMENT ONLY`.
- **Parent research state:** `NO_VALIDATED_EDGE`; long-history cumulative denominator **N=359**.
- **This cycle:** exactly one candidate configuration; denominator becomes **N=360 if evaluated**. Frozen comparators do not count as candidate configurations.
- **Candidate result:** `data/evidence/longhistory/cpi_acceleration_gate_discovery_dev.json`.
- **Report:** `docs/research/cpi_acceleration_gate_results_2026-10-19.md`.
- **Hard boundary:** no price value dated 2000-01-01 or later, no 2000+ evaluation metric, no 730-day tick row, no holdout access, no orders. `LIVE=LOCKED`.

### Amendment A1 — pre-measurement warm-up coverage

Before reading CPI values or candidate outcomes, the frozen signal/execution timing was reviewed. The first selection-window return uses the December 1972 decision as its pre-window signal anchor; under the fixed `Y-2` mapping, that anchor requires acceleration for CPI year 1970, which in turn requires CPI index values for 1968–1970. Expand the required input years from 1969–1997 to **1968–1997 inclusive**; no formula, lag, threshold, window, gate, or candidate count changes. This is a data-availability requirement only, not a candidate variant. Freeze this amendment before inspecting values.

## 1. Question and hypothesis

Does annual US CPI inflation acceleration, observed with a conservative calendar lag, improve the frozen 9-month long-only gold trend?

Economic rationale fixed before measurement: an accelerating inflation rate may increase demand for gold as a monetary hedge. The hypothesis concerns acceleration, not an optimized CPI level, chosen inflation threshold, alternate lag, or alternate gold lookback.

**Falsification:** reject this single candidate if it fails any predeclared screen gate in §5. Missing, duplicate, invalid, or insufficiently covered source data makes the run `INCONCLUSIVE`; do not repair, interpolate, substitute another country/series, change the lag, or rerun. A screen pass is not a validated edge because the CPI source has no historical release-vintage record (§2).

## 2. Frozen source and data boundary

### CPI input

- Repository: `https://github.com/datasets/cpi`
- Commit: `3750e45064a99b0452deb1423a416e4d5473a58e`
- File: `data/cpi.csv`
- Pinned Git blob SHA-1: `20c3e21ab08e993b9ab1eb1b2e4c442f43042b4a`
- Pinned metadata file: `datapackage.json`, Git blob SHA-1 `5e01862471860e1b3233fb65d35625cc36a6b092`
- Fields: `Country Name`, `Country Code`, `Year`, `CPI`; CPI is an annual index with reference year 2005 = 100.
- Provenance: the datapackage names the World Bank's `FP.CPI.TOTL` indicator. Its datapackage declares ODC-PDDL-1.0; the repository-level GitHub license metadata says GPL-3.0. Keep the source file external to this repository and record this license-metadata discrepancy; do not redistribute it as part of this research change.
- The repository README describes an annual series, with historical collection beginning in 1960; the datapackage was last updated in 2025. The source does **not** supply historical release dates or vintage snapshots. Historical revisions and point-in-time availability therefore cannot be established. The two-calendar-year lag below reduces release-timing risk but does not cure unknown revisions; even a screen pass cannot authorize validation, promotion, or live use.

Use only the `USA` country-code rows, annual `CPI` values through 1999, and no alternative countries or CPI series. Required values are CPI for every year 1968–1997 inclusive; if any are absent, duplicated, nonpositive, or nonfinite, stop with `INCONCLUSIVE` before calculating any trading outcome. No interpolation or backfill is allowed. Rows after 1999 may be inspected only for country/year keys to skip them; their CPI values must not be parsed, converted, aggregated, or used.

### Gold input

Use the existing pinned World Bank Pink Sheet-derived monthly source already used by long-history screens:

- Repository: `https://github.com/awongstory/commodity-price-forecast-xgboost`
- Commit: `c4a9f734d92df0d0a6c4744a2d7c34417ecd074b`
- File: `data/wb_commodity_price_intelligence_1960_2026.csv`
- SHA-256: `3328bdff6156eb9ae11173ca2d52a8b207218cdd913ee0fa986be17d16e92aaf`
- Use only the `Gold` series' raw `price_nominal_usd` field, monthly rows dated before 2000-01-01. Do not use precomputed momentum, volatility, regime, or index fields from that panel.

The loader must validate both pinned identities, schema, chronological unique monthly dates, and positive finite eligible Gold prices. Post-1999 price rows may be inspected only by date/name to skip them; no post-1999 price value may be converted, aggregated, plotted, or otherwise used. No resampling, gap filling, price repair, or alternate series is permitted.

## 3. One frozen candidate and common execution

### Candidate `cpi_accel_lag2_ts9_longflat`

For annual CPI index `C_y`, define log annual inflation and its acceleration:

`pi_y = ln(C_y / C_(y-1))`

`accel_y = pi_y - pi_(y-1)`

For a monthly decision made in calendar year `Y`, use only `accel_(Y-2)`. This means the CPI state is fixed for each calendar year and is based on an annual observation from two calendar years earlier. No current-year or previous-year CPI observation enters the decision.

At monthly decision month `t`, define:

`gold_mom9(t) = ln(Gold_t / Gold_(t-9))`

Set the target for the next monthly bar to **long** iff both `gold_mom9(t) > 0` and `accel_(year(t)-2) > 0`; otherwise set it **flat**. Ties are flat. There are no short positions. No alternate lag, threshold, horizon, CPI transformation, or sizing is authorized.

### Frozen comparator

- `ts9_lo`: long if the trailing 9-month Gold return is positive, otherwise flat. It is the only gating comparator. No FX-derived comparator is used in this cycle.

### Sizing, fills, and costs

Use the existing monthly `fixed_units.v2` convention unchanged: 10% annualized Gold-volatility target using trailing 12-month log-return volatility, capped at 1.0× equity, no leverage, no stop; signal at month `t` close, fill at month `t+1` published monthly-average price, monthly rebalance, and force flat at each window end. Each window starts a separate USD 10,000 account.

Primary costs are the existing monthly `COST_BASE`: ASSUMED 3 bps spread, 1 bp slippage, USD 7/lot/side commission, and zero financing. Report the predeclared 2× and 3× base-cost stresses and existing financing assumption of 0.25 bps per calendar day. Costs are ASSUMED, not measured; no broker-economics claim is authorized.

## 4. Windows — no evaluation stage

- **Discovery selection:** 1973-01 through 1983-12.
- **Discovery confirmation:** 1984-01 through 1989-12.
- **Development:** 1990-01 through 1999-12.
- **No final/evaluation window is authorized.** The 1990s are reused development evidence, not an untouched holdout. Do not calculate any metric, plot, aggregate, or intermediate result on 2000-01 onward.

For candidate and comparator, report net/gross P&L, costs, annualized monthly Sharpe, maximum drawdown, exposure, round turns, calendar-year returns, and paired monthly-return differences. Report development DSR using **N=360** as descriptive multiple-testing accounting, not as validation.

## 5. Predeclared screen gates

This is a discovery/development screen only. Passing permits consideration of a separately preregistered study using independently sourced, point-in-time CPI vintages and genuinely eligible data; it does not establish a validated edge, promotion, or permission to trade. Since no point-in-time CPI vintage source is currently available, a screen pass alone cannot advance this candidate.

1. **Selection and confirmation:** candidate net P&L is positive in both 1973–1983 and 1984–1989, and its annualized Sharpe exceeds `ts9_lo` by at least 0.10 in both windows.
2. **Development survival:** in 1990–1999, candidate net P&L and annualized Sharpe are positive at base cost; candidate beats `ts9_lo` by at least USD 500 on the separate USD 10,000 account and by at least 0.10 annualized Sharpe; it has at least 20 round turns and at least 6/10 positive calendar years.
3. **Cost robustness:** development candidate net P&L remains positive at 2× base costs and under the 0.25-bps/day financing assumption. Report 3× cost, but do not use it to relax gates.
4. **Paired uncertainty:** on the 120 development monthly net returns, compare candidate-minus-`ts9_lo` mean return using a circular block bootstrap (12-month blocks, 9,999 draws, seed `20261019`). The one-sided 95% lower bound (5th percentile of raw bootstrap mean differences) must be above zero. Compute the one-sided null p-value by centering observed monthly differences at zero, resampling with the same circular-block procedure, and using `(1 + count(boot_mean >= observed_mean)) / 10,000`; the single-comparator Holm-adjusted p-value must be ≤0.05.

Any gate failure records `REJECTED`. An input/identity failure records `INCONCLUSIVE`. If all gates pass, record `SCREEN_PASS_UNVALIDATED_SOURCE_VINTAGE`; do not call it a validated edge or promote it. No alternate specification, favorable-subset analysis, or rerun under a changed formula is permitted. Every output must state `strategy_promoted=false`, `held_out_span_opened=false`, `orders_submitted=0`, and `LIVE=LOCKED`.

## 6. Trial accounting, safety, and freeze procedure

- This candidate adds exactly one trial to long-history DSR accounting: inherited **N=359**, one new candidate, **N=360 if evaluated**. Feature engineering, bootstrap draws, the frozen comparator, and stress views do not add candidate configurations.
- Research-only. Do not edit DEMO policy, risk limits, authorization, execution code, or any LIVE lock. No broker connection, order, paper execution, or execution-readiness claim is part of this protocol.
- Freeze this file in a commit before reading numerical CPI values for this hypothesis or calculating candidate outcomes. Then implement a boundary-guarded runner and synthetic-only tests, verify pinned inputs, execute the authorized screen once, and preserve every result.
- Do not open the locked 730-day holdout or any 2000+ price data. If the candidate survives every screen gate, do not proceed without a separately frozen protocol and a source with actual historical CPI vintages; no such validation is authorized here.
