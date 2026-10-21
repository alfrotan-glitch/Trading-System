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
