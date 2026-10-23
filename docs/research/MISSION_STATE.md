## Current continuation: controlled broker-quote ML assay (2026-10-23)

**Round 32 executed locally:** a preregistered fixed ridge-logistic model was
fit only on causal quote-derived features from the discovery prefix and then
evaluated through five chronological folds plus one frozen 40% holdout. All
five folds were negative at the additional 2 bps round-trip stress. The
holdout was negative even at the measured quote-side cost (`-0.5826` bps) and
`-2.5826` bps at 2 bps extra stress; its moving-block bootstrap 95% interval
was `[-2.6834, -2.4838]` bps. The 15-minute stability holdout was also
negative (`-2.7762` bps). H-ML-01 is rejected, no model was promoted, and no
product integration is justified. The sanitized record is
`data/evidence/mt5_broker_ml_365d_summary_20261023.json`.

The assay used no order API and retained `LIVE=LOCKED` and
`DEMO_EXECUTION=DISABLED`. The full local output remains separate from the
tracked sanitized evidence.

## Current continuation: independent broker-ledger follow-ups (2026-10-23)

**Round 31 executed locally:** the preregistered H-MM-02 market-making
walk-forward was rerun on the confirmed-basis 365-day MT5 bid/ask ledger.
The result is `INCONCLUSIVE`, not an edge: favorable-state fill lift was
`0.0183` versus the `0.05` floor, risk-adjusted favorable/unfavorable results
were `0.0609/0.0739`, and three folds had fewer than 500 favorable events.
The engine uses synthetic front-of-queue fills; bootstrap, commission,
slippage, swaps, and realized fill evidence remain unavailable. The sanitized
record is `data/evidence/mt5_marketmaking_wf_365d_summary_20261023.json`.

**Round 30 executed locally:** the preregistered H-TEMP-01 raw-hour magnitude
test ran on the same ledger. It was `REJECTED`: the primary active/quiet
absolute-movement ratio was `0.8735` with a `-$0.0641` gap, and the 64-quote
ratio was `0.8456`. This is not a directional strategy and no candidate was
promoted. The sanitized record is
`data/evidence/mt5_temporal_365d_summary_20261023.json`.

Neither experiment accessed the held-out suffix or an order API. `LIVE`
remains locked and `DEMO_EXECUTION` remains disabled.

The next independent mechanism is still Gold Futures basis versus XAUUSD.
No GC series is present locally; official CME historical products require a
separate data purchase or subscription, so basis research is blocked until a
licensed, timestamp-aligned GC feed is acquired. Do not substitute a
third-party unverified series or invent carry/roll costs.

## Current continuation: fixed UTC session assay (2026-10-23)

**Round 29 executed locally:** the preregistered fixed London/New York session
reversal follow-up also rejected both hypotheses on the 365-day ledger. At the
1 bps extra round-trip stress, London was negative in discovery and holdout;
New York was negative in discovery and effectively flat in holdout. Both were
more negative at 2 bps. This family is rejected and remains research-only;
`data/evidence/mt5_session_reversal_365d_summary_20261023.json` records the
bounded result.

**Round 28 executed locally:** the first fixed session-conditioned directional
family ran on the complete 365-day local MT5 ledger after the timestamp basis
was independently measured and digest-bound. London and New York four-hour
momentum were both rejected: London was negative in discovery and holdout;
New York was negative in discovery, effectively flat in holdout, and negative
under the 2 bps round-trip stress. The Asia reversal hypothesis had no
qualifying observations. The family is not an edge and no strategy was
promoted. Full fixed output is recorded in
`docs/research/mt5_session_assay_365d_20261023.md` and the sanitized summary
in `data/evidence/mt5_session_assay_365d_summary_20261023.json`.

**Round 27 executed locally:** the read-only MT5 ladder completed 45-, 60-,
90-, 120-, 180-, and 365-day windows. Deferred local analysis passed all six;
the longest ledger contains 81,211,638 rows. A same-session, read-only basis
measurement now binds the 1-, 7-, 30-, 45-, 60-, 90-, 120-, 180-, and 365-day
dataset digests to UTC historical `copy_ticks_range` time fields. Raw manifests
remain unchanged and conservative. The sanitized ladder is in
`docs/research/mt5_history_ladder_2026-10-23.md`.

## Current continuation: 30-day microstructure continuation (2026-10-23)

**Round 26 executed locally:** a complete 30-day read-only broker tick window
with 4,124,595 rows was quality-passed and scored by the unchanged fixed
microstructure engine. Quote spread remained near 0.58 bps median and 0.667
bps p95. The overall result remains `INCONCLUSIVE`: one hypothesis was
rejected, three were only `TESTED`, and the rest were inconclusive. The raw
historical clock basis is still blocked, so no executable edge claim is
eligible.

## Current continuation: microstructure scan (2026-10-23)

**Round 25 executed locally:** the fixed microstructure discovery engine ran on
the complete seven-day broker bid/ask dataset. The result is `INCONCLUSIVE`:
one process-only hypothesis was rejected, the remaining fixed hypotheses were
inconclusive, and the timestamp basis remained blocked. Mutual information was
0.0198 bits. No strategy was built or promoted; the next useful step is longer
unseen tick evidence with a confirmed clock basis, not threshold mining.

## Current continuation: measured broker quote-cost evidence (2026-10-23)

**Round 24 executed locally:** the read-only MT5 acquisition workflow captured
and quality-passed one complete seven-day bid/ask tick window. The sanitized
profile in `docs/research/mt5_tick_cost_profile_2026-10-23.md` records a
0.5803 bps median and 0.6535 bps p95 quoted spread over 935,472 rows, with no
invalid quotes or backward raw timestamps. This is quote evidence only:
commission, slippage, swaps, fills, and the historical server/UTC basis remain
unmeasured or unverified. Raw tick data and acquisition manifests remain local
and untracked. No order API was called; LIVE remains locked.

## Current continuation: conditioned-volatility discovery (2026-10-23)

**Round 23 executed locally:** the preregistered conditioned-volatility M15
screen in `docs/research/mt5_conditioned_volatility_2026-10-23.md` tested four
fixed range/tick-volume hypotheses on both preserved MT5 exports. Compression
breakout was positive only in the longer overlapping export; expansion
momentum was weakly positive in both but cost-sensitive. The family is
`NO_VALIDATED_EDGE`, remains research-only, and did not access an order API.
The next highest-information step is genuinely unseen broker observations with
measured executable costs, not another parameter sweep on spent windows.

## Current continuation: prospective integrity and Windows delivery (2026-10-22)

**Strategy outcome:** NO VALIDATED EXECUTABLE XAUUSD@ EDGE. This change set does
not produce a new profitable strategy and does not authorize LIVE or unattended
DEMO orders. Research candidates are not trade recommendations.

**Critical independent findings now corrected in main:**

1. Edge Lab's candidate freeze was previously just Python bytecode and
   parameters. Two materially different constant values could produce the
   SAME bytecode hash. The revised digest includes constants, function
   defaults, local same-module helpers and simple referenced globals.
   Existing freeze IDs written by older code should be reviewed, not
   silently migrated or equated with a genuine new forward candidate.
2. The low-level JSONL logger accepted a duplicate date with a DIFFERENT
   gold price when the signal matched. It now rejects revisions to
   price, signal, strategy hash or explicitly supplied provenance.
3. The previous command-line forward log could consume the rejected XL-001
   signal, backfill historical dates, and mix the LBMA AM fix with later
   macroeconomic inputs. It now fails closed rather than manufacturing
   forward observations. The older replay downloader avoids network work
   when no active candidate exists, and cannot mark public historical replay
   as authenticated broker-forward evidence.
4. Forward research now has a separate `prospective_integrity` audit:
   strategy registration, definition consistency, chronological logging,
   executable price basis, source identity and minimum sample are all
   required before even opening a review. The API's `validated` field
   remains FALSE regardless of a standalone t-statistic. A statistical
   threshold is not independent OOS validation, cost verification or
   permission to trade.
5. The forward scorer previously used the optimistic default transaction
   cost while the API described the realistic ECN model. It now uses the
   realistic ECN assumption consistently. Real WMMarkets-Demo spread,
   commission, slippage, swaps and execution timing are still unmeasured.
6. Desktop Reports contained fallback LONG signals and hardcoded historical
   profit numbers even if the backend returned no fresh research data. Those
   claims were removed. Reports now distinguishes dated research snapshots,
   verified prospective evidence and **no current validated signal**.
7. The Windows packaging workflow now rebuilds on changes anywhere within
   the packaged QTS runtime source and dependency manifest, rather than
   silently retaining an out-of-date ZIP when a research/forward module
   changes. The workflow also smoke-tests the extracted ZIP on Windows.

**Already available product workflow:** extract the GitHub Windows preview;
open QTS.exe with an actual MT5 DEMO account; use the in-app OBSERVE-ONLY
collector to record real broker ticks (zero orders), and use Reports'
"Check broker symbol terms (read-only)" for an explicit source-labeled
symbol specification / swap snapshot. Do not interpret a broker specification
snapshot as measured slippage or realized rollover cost; those require
broker fill/deal evidence.

**Next scientific work:** develop an auditable completed-bar *broker* feed
adapter from the existing canonical MT5 observation store for future,
pre-frozen candidates. Preserve the quote receipt time, broker timestamp,
bid/ask, UTC normalization and source metadata; never reconstruct missing
bars as factual observations or backfill after outcomes. Only then can
genuinely unseen forward signals be logged. In parallel, search materially
new, accessible gold information sets, with a realistic net risk-matched
control. Previous VIX, official CFTC and prequential AI studies were
falsified; merely retuning them on spent historical data is not new OOS.

**Verification:** the preceding pre-audit Windows ZIP and CI were green;
the newest combined commits must be checked against their own GitHub
Actions fast, extended, package, container and Windows jobs before being
described as fully verified. Never replace a failed gate with a verbal claim.

---

## Round 22: extended official CFTC gold positioning — 2026-10-22

**Official source verified and historical experiment executed successfully.**
GitHub Actions run 39725660921:
https://github.com/alfrotan-glitch/Trading-System/actions/runs/39725660921

The prior round-15 COT study used a nonofficial 374-report Legacy workbook
covering only 2018-2025. The improved study queried the official CFTC
Disaggregated Futures Only dataset 72hh-3qpy for the exact COMEX gold contract
code 088691 and verified **1,062 weekly reports, 2006-06-13 to 2026-10-13**.
These are Managed Money positions, *not* the Legacy non-commercial category;
we did not silently substitute the new columns for the old ones.

Two frozen hypotheses used measured historical open interest and managed-money
net positions: long gold at unusually low positioning relative to 104 reports,
or long when net positioning increased over 13 reports. Publication was
conservatively ASSUMED available 14 days after Tuesday's as-of date, with an
additional executable gold next-open lag. Exceptional CFTC report delays are
not verified; this assumption is insufficient for strategy promotion.
ECN turnover and calendar-day funding sensitivities were applied. Compared
against static gold with matched average exposure:

| Historical window (all SPENT) | Low-positioning reversal HAC t | Positioning trend HAC t |
| --- | ---: | ---: |
| 2008-2015 | -0.10 | -1.64 |
| 2016-2021 | +0.93 | -1.56 |
| 2022-2025 diagnostic | -0.88 | -1.04 |

**Verdict: neither hypothesis demonstrates robust positive net incremental
alpha. Both are REJECTED for trading promotion.** Repeating parameter sweeps
over these windows cannot create fresh holdout evidence. The official source
collector is reusable for future timestamp-correct observations, but no signal
may be enabled in DEMO auto-execution or LIVE on this basis.

Implementation: `src/qts/research/edgelab/cot_disaggregated.py`,
`scripts/fetch_cftc_gold.py`, `scripts/edgelab_cot_official_run.py`,
`tests/unit/test_edgelab_cot_disaggregated.py`. Automated execution and
manifest are maintained in the independent gold research workflow.

**Product state:** A real packaged Windows QTS executable now passes its
API/UI loopback HTTP smoke (GitHub Actions run 39724414064). Later fixes
ensure GUI startup failures are visibly reported rather than silently
closing when Windows supplies no console streams. Risk/live gates remain
unchanged, zero validated edges, real-capital exposure zero.

---

## Verified research and Windows delivery status — 2026-10-22

**Mission verdict: ZERO validated profitable XAUUSD@ strategies. LIVE remains LOCKED.**
A passing CI suite and packaged desktop do not demonstrate a profitable edge.

### Round 21: causal adaptive AI strategy tested and rejected

The verified research run 39597337813 completed on real historical gold and
official Cboe VIX/VIX3M:
https://github.com/alfrotan-glitch/Trading-System/actions/runs/39597337813

The predeclared monthly prequential ridge model generated 131 usable monthly
predictions from 254 months of observations. It used trailing gold features,
lagged Cboe variables, next-open execution, transaction costs and calendar-day
financing sensitivities. Against exposure-matched passive gold:

| Historical window (all SPENT) | AI Sharpe | matched passive Sharpe | paired HAC t |
| --- | ---: | ---: | ---: |
| 2008-2015 | -0.221 | +0.237 | -0.94 |
| 2016-2021 | +0.419 | +0.685 | -0.51 |
| 2022-2025 diagnostic | +0.990 | +1.284 | +0.65 |

The adaptive model did not show robust positive incremental value. REJECT for
trading-system promotion. It remains research-only, and re-fitting its
parameters on already-spent windows cannot validate it.

### Windows packaged preview

Windows build 39723415827 successfully produced and smoke-tested the frozen
application and its bundled UI/API:
https://github.com/alfrotan-glitch/Trading-System/actions/runs/39723415827

The ZIP preview extracts to a folder and runs by double-clicking QTS.exe:
no Python, Git or Docker required. This is not proof of the actual owner's
terminal connection, measured execution, or profitable strategies. A stricter
live localhost HTTP smoke has been added in later commits; check the latest
Actions run for its pass/fail status.

Two previously misleading smoke errors were corrected:
- FastAPI >=0.137 includes routers lazily. The flattened app.routes property
  is NOT a reliable route inventory; check OpenAPI and real HTTP instead.
- Frozen PyInstaller entry scripts resolve from the bundle root; bundled UI
  files live in qts/desktop/ui, not in a top-level ui folder.
- Local QTS API startup now requires a healthy response from THIS process,
  avoiding an apparent success when a different process already owns the port.

### Priority work remaining

1. Verify latest full CI and Windows loopback HTTP smoke; keep software
   release acceptance distinct from strategy validation.
2. Measure XAUUSD@ spread, slippage, overnight swaps and instrument terms from
   the OWNER'S connected DEMO broker terminal.
3. Accumulate genuinely new timestamp-aligned prospective XAUUSD@ observations
   in the existing durable forward ledger, rather than reuse spent holdouts.
4. Investigate independent mechanisms (futures basis, options, positioning,
   order flow) as accessible data permits. Test matched-risk net improvement
   with strict executable timestamps and explicit costs.
5. Maintain simple daily Windows UX, fail-closed risk controls and no real-money
   trading. No candidate is eligible for automatic trade registration today.

---

## Verified VIX curve research execution — Round 20 (2026-10-21)

**GitHub Actions run 39593567233: SUCCESS.** Cboe VIX/VIX3M CSV acquisition,
pinned BaseMax M15 historical data, unit checks, and the pre-registered
two-direction experiment executed. Full log and JSON artifact are available at
https://github.com/alfrotan-glitch/Trading-System/actions/runs/39593567233

**Verdict: REJECT both directions as a stable executable edge.**
All three windows were historically inspected in earlier studies; these figures
are *not independent holdout evidence*. Under ECN trading costs and the zero-swap
scenario, the paired excess net return versus an exposure-matched static gold
control was (annualised):

| Direction | DEV 2008-15 | VAL 2016-21 | DIAGNOSTIC 2022-25 |
| --- | ---: | ---: | ---: |
| VIX term contango | -1.20%, t(HAC) -0.31 | -1.84%, t -1.40 | -0.94%, t -0.72 |
| VIX term backwardation | -1.21%, t -0.78 | +1.81%, t +1.39 | +0.93%, t +0.71 |

Neither direction produced a robust, statistically decisive improvement across
windows. The backwardation rule is rarely invested (about 2-8% exposure), so
an impressive-looking portfolio Sharpe may simply be an artefact of being mostly
flat. Funding scenarios at 0.5, 1.0 and 2.0 bp/calendar day were also executed;
the actual broker swap remains unmeasured.

**The collection job, not the Edge, succeeded.** No promotion, no live unlock.
The older pre-execution plan below is retained as an audit trail, but its
statement that the VIX experiment had not run is now superseded by this record.
The research queue moves to one **genuinely different** mechanism/ML protocol,
with prospective integrity tests and full execution-cost disclosure.

---

# Mission state — XAUUSD@ validated-edge program

**Updated:** 2026-10-21, after round 19 (walk-forward selection).
**Status:** `NO_CANDIDATE` — `XL-001` **rejected** (round 10), **zero validated edges**,
`active_candidates: []`, forward ledger empty.
`LIVE` locked, `REAL_CAPITAL_EXPOSURE = 0`.

This file is the recovery document. If the session is interrupted, read this
first; it states exactly what is spent, what is available, and what to run next.
The full history lives in `experiment_register.md`; the project log is
`QTS_PROJECT_CONTROL.md`.

---

## Post-round-19 independent source-code audit (2026-10-21)

**This is a code-integrity update, not a claimed new strategy or an edge.**
Direct inspection of `src/qts/research/edgelab/intraday.py` discovered
additional timing defects that the original round-7 tests did not cover:

1. `overnight_momentum_close` grouped the 22:00..06:00 window by **calendar
   date**, so the D 19:00 signal could incorporate D 22:00..23:45 **future**
   prices. Fixed by grouping each overnight session by the date it *ends*,
   using only sessions with observed evening and morning halves.
2. `overnight_reversal` did not measure a completed overnight session; its
   calendar-date grouping mixed the morning and following evening, then shifted
   by a calendar day. It now trades against the latest *completed* overnight.
3. `opening_range_breakout` reset its range at calendar midnight, silently
   discarding the prior 22:00..23:45 portion of the Asian range. Its trading
   day now runs from the overnight start to the following day.
4. `window_return_per_day` credited the 22:00 reopening gap, which could not
   be earned by a strategy flat before the reopen; it also combined unrelated
   evening and morning sessions by calendar date. It now groups by the end
   date and excludes reopening/maintenance gaps.
5. `GET /api/research/regime` exposed old BaseMax prices as a purported
   "current" regime. It now exposes staleness and `allow_trade: false`
   whenever the source exceeds five calendar days.

Regression tests have been committed for all five defects. **The full repository
suite and historical re-scoring have not been run in this connector-only session**:
the gitignored BaseMax/Vudo raw data are not mounted, and the local shell cannot
download the repository. The committed source changes are not equivalent to a
green CI result. Re-run
`pytest tests/unit/test_edgelab_intraday.py tests/unit/test_edgelab_regime.py -q`,
then `python scripts/edgelab_intraday_run.py` on verified raw data. Do not
reuse old `overrev_asia`, `momclose_asia`, `orb_asia*` statistics as
independent evidence; their definitions changed. The previously consumed
historical windows remain spent, so repaired in-sample scores cannot become
fresh holdout evidence. All reported profitability remains unvalidated.

**Mission:** continue searching genuinely new information sets and run the
repaired execution-aware screen when reliable data become accessible. No
fabricated edge, no live-money unlock.

**Next independent research channel implemented but not yet executed**:
Cboe VIX/VIX3M implied-volatility **term-structure slope**, distinct from
the rejected VIX-level/credit-stress experiments. The exact predeclared
hypotheses, official-data collection, causal lag, monthly cadence, matched
controls, incomplete CFD financing model, and runnable commands are in
`docs/research/vix_curve_research_plan_2026-10-21.md`.
`scripts/fetch_cboe_vix_curve.py` acquires the source and
`scripts/edgelab_vix_curve_run.py` evaluates only *spent* historical
windows; `tests/unit/test_edgelab_vix_curve.py` contains integrity
regressions. **No actual download/backtest has run in this restricted
environment.** Run acquisition, tests and rescore in a data-connected
environment before interpreting a numerical result. Historical wins can
be DISCOVERY ONLY; forward observation and real broker financing are
needed for promotion. This source does not justify unlocking trading.

**Executable automation now configured:** `.github/workflows/vix-curve-research.yml`
responds to relevant `main` pushes or manual dispatch. It checks the causal
tests, acquires official Cboe data and the pinned BaseMax M15 archive, rejects
incomplete UTC trading days, evaluates BOTH frozen VIX-curve hypotheses under
four financing scenarios (0/0.5/1/2 bps per calendar day), and uploads only
the research JSON/manifest. The latest workflow execution is **not yet
independently verified from this connector**; do not claim tests passed or
that a historical Edge exists. The study now also tests the *paired net return
difference* relative to a static **exposure-matched** gold control with a HAC
statistic, not just a gross/Sharpe improvement. Every window remains marked
`SPENT`; independent validation cannot be manufactured.

---

## 1. The one thing that changed the direction of the work

**Turnover, not signal quality, is the binding constraint.**

At 0.925 bps/side, one position change per day (≈550 sides/yr) costs **9.1%/yr**.
Round 7 measured what that does to real intraday signals:

| Strategy | Gross alpha | Net alpha | Sides/yr |
|---|---|---|---|
| `tsmom_m15_96` | **+20.9% (t 4.76)** | **−14.3%** | 2,158 |
| `orb_asia` | +10.3% (t 2.44) | +1.3% (t 0.30) | 545 |
| `sess_asia_2206` | +3.9% (t 2.24) | −5.2% | 551 |

Consequence: **only strategies below roughly 100 sides/yr can survive retail
costs.** Any new idea must state its turnover before it is worth a backtest, and
any idea above ~500 sides/yr needs >9%/yr of gross alpha just to break even.

`XL-001` trades 6.7 times a year, which is why it is the only candidate.

---

## 2. Data inventory (exact paths, exact coverage)

All raw data is gitignored (`data/raw/`) and must be re-fetched in a new sandbox.

| Dataset | Path | Coverage | Notes |
|---|---|---|---|
| Gold, LBMA fix daily | `data/raw/longgold/metals/AU.csv` | 1968-01-02 .. 2024-05-17 | `teofiloxyz/precious-metals-price` |
| Silver, daily | `data/raw/longgold/metals/AG.csv` | 1968-01-02 .. 2024-05-17 | same repo |
| DXY, daily | `data/raw/longgold/macro_daily/DXY.csv` | 1971-01-04 .. 2024-05-17 | same repo |
| 10y nominal, daily | `data/raw/longgold/macro_daily/US_10Y_TREASURY_YIELD.csv` | 1962-01-02 .. 2024-05-16 | same repo |
| 10y nominal (FRED mirror) | `data/raw/longgold/fred/treasury_10y.csv` | 1962-01-02 .. **2026-10-16** | `sgdividends/fred-macro-data`; **verified identical** to the copy above over 15,580 obs |
| 10y real (DFII10) | `data/raw/longgold/fred/treasury_10y_real.csv` | 2003-01-02 .. **2026-10-16** | same repo; negative yields 2011-2021 are real |
| Broad dollar (DTWEXBGS) | `data/raw/longgold/fred/broad_dollar.csv` | 2006-01-02 .. **2026-10-16** | same repo; 88.1% flag agreement with DXY |
| Gold M15 (BaseMax) | `data/research/xauusd_m15_basemax.parquet` | 2004-06-11 .. 2025-09-30 | **tail incomplete after 2025-02** — 0 bars Aug-2025, 2 in Sep-2025 |
| Gold M15 (Dukascopy replay) | `data/research/xauusd_m15_vudo.parquet` | 2025-08-06 .. 2026-09-16 | real Dukascopy feed, 5 symbols incl. 4 FX pairs |

Refetch: `bash scripts/fetch_longhistory.sh` is **not** the path for the FRED
mirror; use the tarball approach recorded in §6. The FRED files must be
re-downloaded before any script in §6 can run — the loaders fail with the file
name and the expected source rather than a bare `FileNotFoundError`.

---

## 3. Which windows are spent — read this before designing anything

Once a window's returns have been looked at, it is in-sample for **every later
hypothesis**. Applied consistently:

| Window | Status | Spent by |
|---|---|---|
| 1969-2000 | **spent** | rounds 1-6 |
| 2001-2010 | **spent** | rounds 3-6 |
| 2011-2019 | **spent** | rounds 3-6 |
| 2020-2024 | **spent** | round 3 (`tsmom_1m` holdout) |
| 2024-06 .. 2026-09 | **spent** | **round 8** (`XL-001` holdout) |

**There is no untouched historical window left.** This is the single most
important fact in this document. A new family can still be developed on
DEV/VAL-style sub-periods of older data, but it can no longer be *confirmed* on
historical data — only by forward observation through the ledger.

Exceptions that cost nothing to state: `XL-001`'s round-8 reading was a legitimate
holdout (it post-dated the frozen definition), and round 9 correctly refused to
read the same window because nothing survived DEV.

---

## 4. Candidate XL-001 — REJECTED in round 10

**Do not treat the table below as evidence of an edge.** Round 10 showed that the
pass was bought by a price-snapshot artifact: `AU.csv` is the LBMA AM fix struck
at 10:30 London, while both drivers are close-of-day values stamped 22:00 London.
At the first executable lag the effect disappears (full 2005-2025: +1.57%, t 1.34).
The original numbers are kept only so the reversal can be traced.
Full audit: `docs/research/audit_xl001_2026-10-21.md`.

`easing_conditions_6m`, hash `2c25b9fda8eebf01`.
Signal: `usd = 1 if DXY < its level 126 days ago`, `yld` likewise,
`signal = (usd + yld) / 2`. Exposure in [0, 1]. Turnover 6.7/yr.

| Period | Alpha/yr | alpha_t | Sharpe | Max DD | Beta |
|---|---|---|---|---|---|
| DEV 1971-2000 | +3.3% | **2.70** | 0.62 | 24.6% | 0.46 |
| VAL 2001-2010 | +1.4% | 0.65 | 0.92 | 16.5% | 0.58 |
| TEST 2011-2019 | +4.9% | **2.94** | 0.66 | 14.6% | 0.50 |
| Holdout A 2024-06..2025-02 | −2.9% | −0.80 | 0.56 | — | 0.24 |
| Holdout B 2025-08..2026-09 | +5.4% | 0.61 | 0.95 | — | 0.65 |
| Holdout pooled | net +12.3%/yr | — | — | — | — |

Verdict **MIXED** in the holdout: no upgrade, no downgrade. Block A is the
weakest evidence the candidate has produced (gold +12.8% while a 47%-exposed rule
returned +2.4%) and is the first concrete sign the 2022+ driver relationship may
be drifting.

**Falsification conditions** (from the candidate write-up): five years of forward
observations at the observed effect size would be decisive; a long flat spell with
high exposure means the mechanism is wrong; a structural break in gold's drivers
post-2022 is the strongest reason for caution; costs above ~2 bps/side put the
effect below threshold.

Forward ledger: `data/evidence/edgelab_forward_ledger.jsonl` — **empty on purpose**.
Nothing logged so far is forward; everything available today predates the freeze.
`qts forward score` reports `insufficient` until ≥3 observations exist.

---

## 5. Experiment queue (ranked, with the reason)

**The standing rule from round 14: a new round must bring new information, not a
new transformation of information already in hand.** Round 14 measured the
persistence of the whole catalogue: 2 of 21 signals stayed positive on
DEV+VAL+TEST, against 2.6 expected from chance alone, and White's reality check on
the best of them gave p 0.056. Single-signal enumeration over daily gold is over.

0b. **Do not performance-chase (round 19).** Re-selecting strategies by trailing
   Sharpe is significantly worse than a fixed blend at every concentration
   (top-3 ΔSharpe −0.244, p 0.002). The default allocation is fixed and
   pre-registered.
0a. **The regime/portfolio layer exists and is measured (round 17).** It is wired
   into `GET /api/research/regime`, and the measurement says it does **not** beat
   exposure-matched controls (1 of 3 windows). Do not describe it as intelligent
   allocation; it is de-risking plus a tail-risk no-trade state.
0. **Read round 16 before designing anything.** The horizon to validate the best
   signal is 28.9 years of forward data (blend: 73; median 94.6). Forward
   observation is therefore not a route to validation either. See
   `scripts/edgelab_power_horizon.py`.
1. **The classical data channels are now exhausted.** Round 15 closed positioning
   (8.7 years only, no CI excluding zero). Every dataset reachable from this
   sandbox has been tested: price, trend, volatility, calendar, relative value,
   real yields, inflation, money stock, labour market, credit, financial
   conditions, and positioning. A further round must either bring a genuinely new
   data source or change the *question*, not add another transform.
2. **Re-scope the product claim.** If no edge materialises, the honest product is a
   risk-managed gold allocation with a measured, *unvalidated* timing overlay —
   and the docs must say exactly that. Do not relabel it.
3. **Anything above ~500 sides/yr is not worth running** unless its gross alpha
   clears 9%/yr by a wide margin.

Explicitly closed — do not re-run: `tsmom_1m` (failed holdout), gold/silver ratio
(3 hypotheses, 0 survivors), standalone `usd_falling_*` / `yield_falling_*` legs
(round 5), conjunction of the easing legs (worse than the average), session-clock
flips (round 7, cost-killed), M15 trend at intraday cadence (round 7), **XL-001
(round 10, price-snapshot artifact)**, **real-yield residual (round 11, dead on
tradable closes)**, **the stress complex — VIX / credit / NFCI / St Louis FSI —
in both directions (round 12)**.

---

## 6. Recovery instructions

```bash
# 1. environment (the venv is not persisted)
python3 -m venv .venv && .venv/bin/pip install -e ".[dev,packaging]"

# 2. raw data — only codeload.github.com works for GitHub tarballs
curl -sSL -o /tmp/pm.tgz https://codeload.github.com/teofiloxyz/precious-metals-price/tar.gz/HEAD
curl -sSL -o /tmp/fred.tgz https://codeload.github.com/sgdividends/fred-macro-data/tar.gz/HEAD
curl -sSL -o /tmp/bm.tgz https://codeload.github.com/BaseMax/XAUUSD-LSTM/tar.gz/43f4177e701fdf3643cc02413e4337932af57401
curl -sSL -o /tmp/vu.tgz https://codeload.github.com/vudo805/forex-price-simulator/tar.gz/4d6f15543e6285fad91fd57fe42f716bc7273075
# extract into data/raw/longgold/{metals,macro_daily,fred} and data/raw/longhistory

# 3. prepare and reproduce
.venv/bin/python scripts/edgelab_prepare_data.py
.venv/bin/python scripts/edgelab_prepare_longgold.py   # rebuilds the 52-year store; fixed 2026-10-21
.venv/bin/python scripts/edgelab_longhistory_run.py    # round 3; must still find tsmom_1m
.venv/bin/python scripts/edgelab_realyield_retest.py   # round 11
.venv/bin/python scripts/edgelab_stress_run.py         # round 12
.venv/bin/python scripts/edgelab_candidate_run.py        # XL-001 scorecard
.venv/bin/python scripts/edgelab_xl001_holdout.py        # round 8 holdout
.venv/bin/python scripts/edgelab_intraday_run.py         # round 7 sessions
.venv/bin/python scripts/edgelab_realyield_run.py        # round 9 real-yield residual
qts forward score

# 3b. rounds 13-14
.venv/bin/python scripts/edgelab_quantity_run.py    # round 13: money + labour
.venv/bin/python scripts/edgelab_meta_run.py        # round 14: reality check, ~5 s

# 4. verification before any PR
.venv/bin/pytest tests/ -q && .venv/bin/ruff check src/ tests/ && .venv/bin/mypy src/qts/research
```

Unreachable hosts, verified: `raw.githubusercontent.com`, `cftc.gov`,
`fred.stlouisfed.org`, `release-assets.githubusercontent.com`. `codeload.github.com`
and `gh api` work. `gh pr edit` is broken — use `gh api -X PATCH`.
## Current continuation: fixed volatility-regime directional assay (2026-10-23)

**Round 33 executed locally:** the preregistered H-REG-01 rule used complete
five-minute bars from the confirmed-basis 365-day MT5 ledger. It followed the
last completed bar during a fixed 12-bar/48-bar volatility expansion and faded
it during a fixed contraction. All five chronological folds were negative at
2 bps extra stress. The frozen holdout had 4,023 non-overlapping trades,
`-0.4263` bps at measured quote cost, and `-2.4263` bps at 2 bps extra stress;
the moving-block bootstrap interval was `[-2.9153, -1.9531]` bps. H-REG-01
is rejected, no model or rule was promoted, and no product integration is
justified. The sanitized record is
`data/evidence/mt5_broker_regime_365d_summary_20261023.json`.

The runner was made directly invocable on Windows and used no order API.
`orders_submitted=0`, `DEMO_EXECUTION=DISABLED`, and `LIVE=LOCKED` remain
enforced. The full local output remains separate from tracked sanitized
evidence.
## Current continuation: fixed return-sign Markov assay (2026-10-23)

**Round 34 executed locally:** H-STAT-01 fit a first-order two-state return-sign
model with fixed Laplace smoothing and fixed 0.55/0.45 direction gates. The
confirmed-basis 365-day ledger supplied 69,631 five-minute samples, but every
walk-forward prefix estimated both state probabilities inside the no-trade
band. All five folds and the frozen holdout therefore produced zero trades.
The result is `INCONCLUSIVE`, not an edge, and no threshold was tuned after
the result. The sanitized record is
`data/evidence/mt5_broker_markov_365d_summary_20261023.json`.

The shared MT5 tick-to-minute reader now serves the broker ML, regime, and
Markov assays without changing their measured results. No order API was used;
`orders_submitted=0`, `DEMO_EXECUTION=DISABLED`, and `LIVE=LOCKED` remain
enforced. The full local output remains separate from tracked sanitized
evidence.
## Current continuation: fixed three-bar sequence assay (2026-10-23)

**Round 35 executed locally:** the preregistered H-SEQ-01 event/state assay
tested both continuation and fade mappings after three same-sign completed
five-minute bars. Each mapping had 3,415 non-overlapping holdout trades and
all five walk-forward folds were negative at 2 bps extra stress. Holdout means
were `-2.9002` bps for continuation and `-2.2914` bps for fade; both moving-
block bootstrap intervals were entirely below zero. H-SEQ-01 is rejected and
no product integration is justified. The sanitized record is
`data/evidence/mt5_broker_sequence_365d_summary_20261023.json`.

No order API was used; `orders_submitted=0`, `DEMO_EXECUTION=DISABLED`, and
`LIVE=LOCKED` remain enforced. The full local output remains separate from
tracked sanitized evidence.

## Current continuation: fixed opening-range assay (2026-10-23)

**Round 36 executed locally:** H-ORB-01 tested two predeclared UTC opening
events (08:00 and 13:30), a 30-minute completed-bar range, the first breach
within the next 60 minutes, next-bar executable entry, and a fixed 30-minute
hold. Breakout and fade mappings were both evaluated with five chronological
folds, a frozen 40% holdout, measured bid/ask execution, and 0/1/2 bps extra
stress. The assay produced 494 qualifying events and 203 holdout trades,
below the preregistered 500-trade minimum. Both holdout means were negative
at measured quote cost and at 2 bps stress; both 2 bps bootstrap intervals
were entirely below zero. The formal classification is `INCONCLUSIVE` because
the sample gate was not met, not a validated edge. No candidate was promoted.
The sanitized record is
`data/evidence/mt5_broker_opening_range_365d_summary_20261023.json`.

The assay used no order API and retained `LIVE=LOCKED` and
`DEMO_EXECUTION=DISABLED`. The full local output remains separate from the
tracked sanitized evidence. The next independent mechanism must not retune
this event definition or reopen rejected families.

## Current continuation: corrected compressed-range breakout assay (2026-10-23)

**Round 37 executed locally:** the earlier H-VOL-COMP-BREAK-8 screen was
retested after correcting a definition defect: its recorded compression gate
had not been applied to the breakout signal. The corrected rule used causal
15-minute range medians (32-bar recent versus the prior 256 recent medians),
the prior 32-bar high/low breakout, next-bar bid/ask entry, fixed 8-bar
primary and 16-bar stability exits, five chronological folds, and a frozen
40% holdout. The confirmed ledger supplied 23,410 complete 15-minute bars.

The primary rule produced 1,032 samples but only 218 holdout trades; stability
produced 170 holdout trades, both below the preregistered 500-trade gate.
Primary holdout means were `-3.7832` bps at measured quote cost and `-5.7832`
bps at 2 bps stress. Stability was `-2.6859` bps at 2 bps stress. Both
bootstrap intervals crossed zero because of the small holdout. The formal
classification is `INCONCLUSIVE`, not a validated edge; no candidate was
promoted. The sanitized record is
`data/evidence/mt5_broker_compression_365d_summary_20261023.json`.

The earlier positive assumed-cost result is not reproducible under the
corrected causal definition and measured broker quote execution. No order API
was called; `LIVE=LOCKED` and `DEMO_EXECUTION=DISABLED` remain enforced.

## Current continuation: fixed multi-timeframe alignment assay (2026-10-23)

**Round 38 executed locally:** H-ALIGN-01 required the signs of fixed
15-minute, one-hour, and four-hour completed five-minute returns to agree,
then entered on the next bar. The confirmed ledger supplied 70,596 complete
five-minute bars. The primary 15-minute horizon produced 24,495 samples and
3,611 holdout trades. All five qualifying walk-forward folds were negative at
2 bps stress; the holdout was `-0.8117` bps at measured quote cost and
`-2.8117` bps at 2 bps stress, with bootstrap interval
`[-3.3164, -2.2626]` bps. The one-hour stability horizon was also negative
(`-0.3880` measured, `-2.3880` at 2 bps; interval
`[-3.8878, -0.8822]`). H-ALIGN-01 is rejected and no candidate was promoted.
The sanitized record is
`data/evidence/mt5_broker_alignment_365d_summary_20261023.json`.

No order API was called; `LIVE=LOCKED` and `DEMO_EXECUTION=DISABLED` remain
enforced. The next experiment must be materially distinct and must not retune
the fixed alignment horizons.

## Current continuation: fixed Bollinger mean-reversion assay (2026-10-23)

**Round 39 executed locally:** H-BB-01 faded a causal five-minute close at or
beyond a fixed two-standard-deviation band from the prior 48 close mids. The
confirmed-basis 365-day ledger supplied 70,596 complete five-minute bars.
The primary six-bar horizon produced 8,597 samples and 933 frozen-holdout
trades. Its holdout was `-0.3015` bps at measured quote cost and `-2.3015`
bps at 2 bps extra stress, with bootstrap interval
`[-3.7592, -0.8538]` bps. The stability 24-bar horizon had 470 holdout
trades, `0.0478` bps at 2 bps stress, and an interval spanning zero. No
walk-forward fold met the 500-trade gate for either horizon. H-BB-01 is
**INCONCLUSIVE**, not a validated edge; no candidate was promoted. The
sanitized record is
 `data/evidence/mt5_broker_bollinger_365d_summary_20261023.json`.

No order API was called; `orders_submitted=0`, `DEMO_EXECUTION=DISABLED`, and
`LIVE=LOCKED` remain enforced. The full local output remains separate from
tracked sanitized evidence. The next experiment must be materially distinct
and must not retune this fixed band or horizon definition.

## Current continuation: fixed RSI(2) oscillator assay (2026-10-23)

**Round 40 executed locally:** H-RSI-01 faded fixed RSI(2) close extremes at
 thresholds 10 and 90 using the confirmed-basis 365-day MT5 ledger. The data
 supplied 70,596 complete five-minute bars. The primary six-bar horizon had
 38,502 samples and 3,592 frozen-holdout trades. Its holdout was `-0.7266`
 bps at measured quote cost and `-2.7266` bps at 2 bps extra stress, with
 bootstrap interval `[-3.4318, -2.0239]` bps. All five qualifying primary
 walk-forward folds were negative at 2 bps. The 24-bar stability horizon was
 also negative (`-2.9449` measured and `-4.9449` at 2 bps; interval
 `[-7.2971, -2.6111]`). H-RSI-01 is **REJECTED**, not a validated edge; no
 candidate was promoted. The sanitized record is
 `data/evidence/mt5_broker_rsi_365d_summary_20261023.json`.

No order API was called; `orders_submitted=0`, `DEMO_EXECUTION=DISABLED`, and
`LIVE=LOCKED` remain enforced. The next experiment must be materially distinct
and must not retune these fixed RSI thresholds or horizons.

## Current continuation: fixed EMA trend-state assay (2026-10-23)

**Round 41 executed locally:** H-EMA-01 followed the causal sign of EMA(12)
versus EMA(48) on complete five-minute close mids, resetting at gaps. The
confirmed-basis 365-day ledger supplied 70,596 complete five-minute bars.
The primary six-bar horizon produced 56,175 samples and 3,286 frozen-holdout
trades. Its holdout was `-0.5200` bps at measured quote cost and `-2.5200`
bps at 2 bps extra stress, with bootstrap interval
`[-3.1762, -1.8429]` bps. All five qualifying primary walk-forward folds
were negative at 2 bps. The 24-bar stability horizon was also negative
(`-1.2405` measured and `-3.2405` at 2 bps; interval
`[-5.4938, -0.9560]`). H-EMA-01 is **REJECTED**, not a validated edge; no
candidate was promoted. The sanitized record is
`data/evidence/mt5_broker_ema_365d_summary_20261023.json`.

No order API was called; `orders_submitted=0`, `DEMO_EXECUTION=DISABLED`, and
`LIVE=LOCKED` remain enforced. The next experiment must be materially distinct
and must not retune these fixed EMA periods or horizons.
