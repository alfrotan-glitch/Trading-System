# Mission state — XAUUSD@ validated-edge program

**Updated:** 2026-10-20, after round 9 (PR #42) and the forward-API honesty fix (PR #43).
**Status:** `CANDIDATE` — one candidate (`XL-001`), **zero validated edges**.
`LIVE` locked, `REAL_CAPITAL_EXPOSURE = 0`.

This file is the recovery document. If the session is interrupted, read this
first; it states exactly what is spent, what is available, and what to run next.
The full history lives in `experiment_register.md`; the project log is
`QTS_PROJECT_CONTROL.md`.

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
mirror; use the tarball approach recorded in §6.

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

## 4. Candidate XL-001

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

1. **Forward observation loop for XL-001.** The only path to validation left.
   Refresh the three FRED mirror files, run `qts forward log`, and append. Needs a
   date strictly after 2026-10-16 to count as forward. Automate with a cron-style
   script; the ledger is append-only and refuses revisions.
2. **Portfolio construction across the two credible families** (`XL-001` macro
   easing, and the real-yield residual from round 9). Both are low-turnover, both
   are positive on DEV and VAL, neither is validated. A combined book is worth
   measuring because their drivers are related but not identical — but it must be
   reported as a *combination of unvalidated signals*, never as a validated edge,
   and the combination itself is a new trial that must be counted.
3. **Structural-break study on the dollar/yield → gold relationship.** Round 8
   block A and the known 2022+ breakdown suggest the relationship changed. A
   regime-switching version of `XL-001` (exposure scaled by rolling correlation
   strength) is the natural next hypothesis — low turnover, economically
   motivated, and it addresses the identified failure mode rather than adding a
   new bet.
4. **Anything above ~500 sides/yr is not worth running** unless its gross alpha
   clears 9%/yr by a wide margin.

Explicitly closed — do not re-run: `tsmom_1m` (failed holdout), gold/silver ratio
(3 hypotheses, 0 survivors), standalone `usd_falling_*` / `yield_falling_*` legs
(round 5), conjunction of the easing legs (worse than the average), session-clock
flips (round 7, cost-killed), M15 trend at intraday cadence (round 7).

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
.venv/bin/python scripts/edgelab_prepare_longgold.py
.venv/bin/python scripts/edgelab_candidate_run.py        # XL-001 scorecard
.venv/bin/python scripts/edgelab_xl001_holdout.py        # round 8 holdout
.venv/bin/python scripts/edgelab_intraday_run.py         # round 7 sessions
.venv/bin/python scripts/edgelab_realyield_run.py        # round 9 real-yield residual
qts forward score

# 4. verification before any PR
.venv/bin/pytest tests/ -q && .venv/bin/ruff check src/ tests/ && .venv/bin/mypy src/qts/research
```

Unreachable hosts, verified: `raw.githubusercontent.com`, `cftc.gov`,
`fred.stlouisfed.org`, `release-assets.githubusercontent.com`. `codeload.github.com`
and `gh api` work. `gh pr edit` is broken — use `gh api -X PATCH`.
