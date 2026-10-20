# XAUUSD Experiment Register

Persistent, append-only record of every materially tested hypothesis. Trial counts
here feed the deflated-Sharpe correction, so nothing is silently dropped — failed
and discarded experiments are the expensive part of the evidence and are listed
with the same care as survivors.

**Standing conclusion: `CANDIDATE` (XL-001), not validated.** `LIVE` locked,
`REAL_CAPITAL_EXPOSURE = 0`.
All costs ASSUMED in basis points, never measured.

Acceptance gate (frozen 2026-10-20, `qts/research/edgelab/gate.py`): `alpha_t >= 2.5`
on DEV, deflated Sharpe `>= 0.95` at the correct bar frequency, alpha positive at
2x assumed costs, and alpha sign preserved on VAL and TEST.

---

## Round 1 — M15/Gold, 2004-2018 DEV (52 configurations, 12 families)

| Family | Configs | Best DEV alpha t | Verdict |
|---|---|---|---|
| tsmom, ma, donchian, volbreak, session, dow, rsi, bollinger, orb, volman, ensemble, macro | 52 | 2.14 (`tsmom_d5`) | rejected on VAL sign reversal |

Key outcomes: `tsmom_d5` alpha +8.26%/yr at t=2.11 on DEV, then **−7.00%/yr on VAL**.
Volatility-managed exposure improved Sharpe and drawdown but earned alpha t≈1.0.
Full write-up: `xauusd_edge_lab_verdict_2026-10-20.md`.

## Round 2 — Replication and cross-section (3 configurations)

| Test | Result |
|---|---|
| Cross-source, XAUUSD, 2012-2018 (BaseMax vs ejtraderLabs) | `tsmom_d5` positive on both feeds; `volman` −0.66% on both |
| Sub-period, DEV halved | `volman` alpha +3.52% (2004-11) then −0.58% (2012-18); all of it from the bull run |
| Cross-section, 12 instruments | `tsmom_d5` positive 6/12 (p=1.000); `volman` 2/12 (p=0.021, reliably negative) |

Full write-up: `xauusd_replication_and_cross_section_2026-10-20.md`.

## Round 3 — 51-year history, LBMA fix 1969-2019 (16 configurations, 8 families)

Motivation: power. 17.8 years put the detection floor at SR 0.59; 51 years puts it
at **SR 0.35**, which is the only way to see a realistically sized edge without
weakening the gate.

| Family | Configs | Best DEV alpha t | Verdict |
|---|---|---|---|
| real_yield (level, 12m, 3m) | 3 | 1.56 | no |
| inflation (accel, level) | 2 | 1.30 | no |
| trend (1m, 3m, 6m, 12m, ma_trend) | 5 | 2.59 (`tsmom_1m`) | `tsmom_1m` cleared DEV; **rejected at holdout** |
| meanrev (pullback, reversal) | 2 | −3.84 (`reversal_1m`, wrong sign) | no |
| calendar (Sep-Nov, turn-of-month) | 2 | 0.33 | no |
| regime (trend_lowvol, trend_falling_yield) | 2 | 1.74 | no |

`ma_trend_12m` also cleared DEV (t=2.85) but its alpha is **entirely 1969-1979**
(+4.8%/yr) and negative from 1989 — the Bretton Woods gold bull, not a tradable
effect. Rejected on TEST.

### `tsmom_1m` — the closest call in the project

| Sample | Alpha/yr | t |
|---|---|---|
| LBMA fix 1969-2019 (51 yr) | +8.0% | **2.91** |
| LBMA fix, all six decades | +11.7, +9.5, +5.5, +5.4, +4.7, +14.6 | positive in 6/6 |
| LBMA fix 2004-2019 | +6.6% | 1.46 |
| **Tradable** closes 2004-2019 | +3.5% | 0.94 |
| **Tradable** closes 2020-2024 (holdout) | **−2.1%** | −0.38 |

Cleared DEV (t=2.59, DSR 0.964), held sign on VAL (+2.3%) and TEST (+7.2%), then
failed the untouched holdout. The same-period comparison shows the effect is
roughly **halved** on tradable closes versus the 10:30 London fixing, so part of
the 51-year "edge" was a fixing-snapshot artifact rather than a tradable return.

## Round 4 — Gold/silver ratio, 1968-2024 (3 configurations)

Both directions declared in advance, because theory supports each.

| Hypothesis | DEV 1969-2000 | VAL 2001-2010 | TEST 2011-2019 | Verdict |
|---|---|---|---|---|
| mean reversion (long gold when ratio low) | −1.1% (t=−0.66) | −0.6% | — | no |
| stress momentum (long gold when ratio high) | +0.9% (t=0.52) | −1.0% | +2.2% (t=0.89) | no |
| extreme only (z < −1) | −0.0% (t=−0.02) | −0.1% | — | no |

0 DEV survivors. Reproduce: `python scripts/edgelab_gsr_run.py`.

## Round 5 — Daily macro drivers, 1971-2024 (4 configurations)

DXY daily from 1971-01-04 and the 10-year constant-maturity yield daily from
1962-01-02 — genuinely external series with their own dynamics, unlike every
price-derived rule tested so far. Hypotheses concern direction of travel, not the
well-known contemporaneous correlation (which is not predictive).

| Hypothesis | DEV 1971-2000 | VAL 2001-2010 | TEST 2011-2019 | 2020-24 | Verdict |
|---|---|---|---|---|---|
| `usd_falling_6m` | +4.8% (t=2.41) | +0.6% (0.20) | +2.8% (1.18) | +3.6% (1.00) | positive 4/4, **misses DEV gate by 0.09** |
| `usd_falling_12m` | +6.7% (**t=3.34**) | −1.3% (−0.42) | +0.7% (0.35) | −2.3% (−0.77) | passes DEV, **fails sign test 1/3** |
| `yield_falling_6m` | +2.3% (1.21) | +3.4% (1.10) | +6.4% (**2.62**) | +3.8% (1.24) | positive 4/4, **fails DEV** |
| `yield_falling_12m` | −0.4% (−0.22) | −0.0% | −0.9% | −1.4% | no |

0 candidates holding sign out of sample. Reproduce: `python scripts/edgelab_macro_daily_run.py`.

**Holdout status: spent.** 2020-2024 was consumed rejecting `tsmom_1m` in Round 3.
Once read, a window is in-sample for every later hypothesis, so `usd_falling_6m`
and `yield_falling_6m` — both positive across all four windows — **cannot** be
called validated here. They are interesting and underpowered; nothing more.

Two near-misses worth noting precisely, because they are the most consistent
signals found in the entire project and still do not clear the bar:
`usd_falling_6m` is positive in 4/4 windows with DEV t=2.41 (gate: 2.5), and
`yield_falling_6m` is positive in 4/4 with TEST t=2.62 but DEV t=1.21. Each fails
a different criterion. That pattern — consistency without a decisive period — is
what a small real effect looks like, and also what a mild overfit looks like. With
the holdout spent, this dataset cannot distinguish them.

## Round 6 — Easing-conditions composite (3 configurations) → **first candidate**

The round-5 finding that `usd_falling_6m` and `yield_falling_6m` were both positive
in all four windows suggested they measure one factor with independent noise.
Combining them is a single economic hypothesis (loosening financial conditions),
so the combination rule was fixed by reasoning, not by fitting.

| Variant | DEV alpha t | Note |
|---|---|---|
| conjunction (both falling) | 1.27 | **worse** — requiring agreement discards information |
| **average of the two (6m)** | **2.70** | `XL-001` — all gate criteria pass |
| disjunction either falling (12m) | — | fails VAL (t=−2.03) |

### XL-001 under realistic costs (0.925 bps/side)

| Period | Alpha/yr | alpha_t | Sharpe | Max DD | Beta |
|---|---|---|---|---|---|
| DEV 1971-2000 | +3.3% | **2.70** | 0.62 | 24.6% | 0.46 |
| VAL 2001-2010 | +1.4% | 0.65 | 0.92 | 16.5% | 0.58 |
| TEST 2011-2019 | +4.9% | **2.94** | 0.66 | 14.6% | 0.50 |

Positive in all five decades (+4.8, +6.0, +0.2, +1.6, +5.0 %/yr). DSR 0.962 at 11
trials, 0.978 at 7. Survives 2x cost stress; falls below threshold only at 5x.
Turnover 6.7/yr — costs are not doing the work. Reproduce:
`python scripts/edgelab_candidate_run.py`.

**Status `CANDIDATE`, not validated:** the 2020-2024 holdout was spent in round 3,
and the macro drivers end 2024-05 so the rule cannot be computed over the genuinely
unseen vudo 2025-26 series. Forward observation is the only remaining evidence.
Full write-up: `candidate_xl001_easing_conditions_2026-10-20.md`.

### Cost-model correction (integrity)

The `CostModel` docstring claimed **4.0 bps/side** while the formula computed
**0.40** — a factor-of-ten gap, so every cost assumption reported in rounds 1-5 was
10x stricter than what was actually charged. The docstring is corrected, the
formula is authoritative, and `realistic_ecn()` (0.925 bps/side) was added because
0.40 bps is optimistic for retail gold. XL-001 is reported under both, and a test
now pins the documented rate to the computed one.

## Round 7 — Session clock on M15 (9 configurations, 61 cumulative trials)

A materially different question from every earlier round: not *which direction*
but *when*. Gold's marginal buyer is Asian physical demand and its price-setter is
the New York futures book, so the intraday clock is a real information source that
costs nothing to condition on.

Design: M15 XAUUSD 2004-06-11..2025-09-30 (BaseMax). DEV 2004-2014, VAL 2015-2019,
**2020-2024 excluded from both fitting and validation** (consumed in round 3), OOS
2024-10..2025-09 left untouched. Inference on **daily-aggregated** returns with
Newey-West (5 lag) standard errors — a naive t-statistic on 480,717 M15 bars would
be inflated several-fold. Two of the nine configurations are deliberate negative
controls.

| Configuration | DEV gross alpha | DEV net alpha | DEV net a_t | Turnover/yr |
|---|---|---|---|---|
| `sess_asia_2206` (long 22-06) | +3.9% (t 2.24) | **−5.2%** | −2.96 | 551 |
| `sess_asia_2307` | +3.7% | −5.4% | −2.93 | 551 |
| `sess_london_only` *(control)* | −5.8% (t −2.91) | −14.9% | −7.53 | 553 |
| `sess_newyork_only` *(control)* | +0.5% | −8.7% | −3.64 | 552 |
| `overrev_asia` (fade the overnight move) | −3.1% | −12.0% | −3.47 | 544 |
| `momclose_asia` (overnight → NY close) | +2.5% (t 2.24) | −6.0% | −5.40 | 523 |
| `orb_asia` (Asian-range breakout) | **+10.3%** (t 2.44) | +1.3% | 0.30 | 545 |
| `orb_asia_buf10` | +9.6% (t 2.40) | +0.8% | 0.20 | 529 |
| `tsmom_m15_96` (1-day trend at M15) | **+20.9%** (t 4.76) | −14.3% | −2.93 | **2 158** |

Zero survivors; the two negative controls behave as controls.

### The number this round actually produced: the cost of a daily flip

At 0.925 bps/side, one position change per day (≈550 sides/yr) costs **9.1%/yr**.
Every gross edge found here is smaller than that toll except the fastest-trading
one, which pays 35%/yr. `tsmom_m15_96` is the crispest case in the project: a
**+20.9%/yr gross alpha at t 4.76** — a statistic that would pass any screen that
ignored costs — turned into −14.3% by its own turnover.

The operating rule that follows, and that governs every later round: **a strategy
trading daily needs >9%/yr of gross alpha merely to break even; only strategies
below roughly 100 sides/yr can survive retail costs at all.** XL-001's turnover is
6.7/yr.

### Why the descriptive session effect looked so good

Compounding the 22:00-06:00 window gives **+4.7 bps/day at 8.0% annualised vol**
(DEV) against +4.1 bps/day at 18.1% for the full day — an apparently free 2.3x
improvement in Sharpe. It is not tradable. Splitting the 22:00 bar by the length of
the preceding gap:

| Preceding gap | n | Mean return | t |
|---|---|---|---|
| ≤ 30 min | 7 430 | **−0.17 bps** | −1.47 |
| > 30 min (daily halt / weekend) | 2 693 | **+2.34 bps** | 4.96 |

The drift lives in the reopening gap, which a strategy entering *at* the reopen
never earns. The executable version keeps the risk and loses the return. This is a
useful general lesson: a session statistic computed on close-to-close bars silently
credits the holder with moves that happened while the market was shut.

Reproduce: `python scripts/edgelab_intraday_run.py`.

## Round 8 — XL-001 holdout on data that continues past 2024-05 (no new trials)

The candidate's blocker was that its drivers stopped on 2024-05-17. A FRED mirror
(`sgdividends/fred-macro-data`) supplies `treasury_10y.csv`, `treasury_10y_real.csv`
and `broad_dollar.csv` through **2026-10-16**, and the mirror is *checked* rather
than trusted: its DGS10 file reproduces the independently obtained copy **exactly
over 15,580 overlapping observations spanning 62 years** (max |difference| 0.0).

Two substitutions were measured before use:

| Check | Result | Consequence |
|---|---|---|
| DXY → DTWEXBGS (broad dollar) | level corr 0.969, 6-month-change corr 0.918, **flag agreement 88.1%** | not free — quantified |
| Same rule, both indices, 2006-2019 | alpha_t **2.69** (DXY) vs **2.93** (broad) | index choice does not drive it |
| BaseMax M15 tail | 0 bars Aug-2025, 2 in Sep-2025 | holdout split into two blocks |

With the swap validated, XL-001 was evaluated unchanged (same hash, same 126-day
lookback, same 0.925 bps/side) on windows that start after 2024-05-17:

| Block | n | Alpha/yr | a_t | HAC t | Sharpe | Beta | Exposure |
|---|---|---|---|---|---|---|---|
| A 2024-06..2025-02 (BaseMax) | 233 | −2.9% | −0.80 | −0.81 | 0.56 | 0.24 | 0.47 |
| B 2025-08..2026-09 (Dukascopy) | 346 | +5.4% | 0.61 | 0.64 | 0.95 | 0.65 | 0.77 |
| pooled | 579 | net +12.3%/yr | — | — | — | — | — |

**Read: MIXED — no upgrade, no downgrade.** Neither block is significant, which is
what the sample length guarantees: at 2.3 years the detection floor is a Sharpe
well above 1.2. Block A is the weakest reading in the project's history for this
candidate (gold +12.8% while the rule was 47% exposed and returned +2.4%), and it
is the first evidence that the 2022+ drivers may be drifting. Block B is
comfortably positive but proves nothing at that length.

**This is a holdout, not forward evidence.** The observations post-date the frozen
definition but existed before the operator fetched them; the append-only ledger
remains the only place forward observations live, and the script does not write to
it. Reproduce: `python scripts/edgelab_xl001_holdout.py`.

## Round 9 — Real-yield residual (4 configurations, 9 cumulative trials)

A different use of a familiar driver. Rounds 3, 5 and 6 bet on the *direction of
travel* of macro series; this bets on gold's **distance from its own recent fair
value given the real yield**. For each date, `log gold` is regressed on the
10-year TIPS yield over a rolling 252-day window; the residual, scaled by that
window's own residual standard error, becomes the position (`-z`, clipped).

The window's residual scale is computed from the same fit, not from the rolling
standard deviation of the residual series — the latter mixes residuals produced by
different coefficient sets and gave a materially different z (0.908 vs 0.891 on a
synthetic window). A test pins the rolling-sums implementation to
`numpy.linalg.lstsq` to 1e-8.

Data: DFII10 daily 2003-01-02..2026-10-16 (5,952 obs), span-checked (real yield
never exceeded nominal on any overlapping day, as it must not). DEV 2004-2014,
VAL 2015-2019, **2020-2024 excluded**, 2024-06..2026-09 reserved.

| Configuration | DEV alpha | a_t | HAC t | Sharpe | Turnover | DSR | VAL alpha | VAL t |
|---|---|---|---|---|---|---|---|---|
| `ry_z252` (continuous, long/short) | **+10.2%** | 2.20 | 2.19 | 0.42 | 30/yr | 0.452 | **+8.2%** | 1.89 |
| `ry_z252_long` (long/flat) | +4.3% | 1.84 | 1.83 | 0.78 | 13/yr | 0.857 | +2.3% | 1.02 |
| `ry_z504` (two-year window) | +1.8% | 0.38 | 0.38 | −0.10 | 19/yr | 0.032 | +5.7% | 1.24 |
| `ry_z252_sign` (discrete) | +12.5% | 2.19 | 2.19 | 0.44 | 32/yr | 0.477 | +7.8% | 1.46 |

**Zero survivors.** All four are positive on both DEV and VAL — the sign test that
killed most earlier families passes comfortably — but the best DEV t is **2.20
against a 2.5 gate**, and DSR is 0.45 at 9 trials. The DEV window is 11 years, so
the detection floor is Sharpe 0.753 and the achieved Sharpe is 0.42: this family
is **underpowered, not refuted**.

Because nothing cleared DEV, the 2024-2026 window was **not read**. That is the
point of holding it: a family that cannot clear the gate does not get to spend the
only post-sample data the project has left.

Reproduce: `python scripts/edgelab_realyield_run.py`.

## Unavailable inputs (attempted, with evidence)

| Input | Attempt | Outcome |
|---|---|---|
| CFTC COT positioning | GitHub code search for historical COT, `cftc.gov` direct | only single-snapshot JSON found; CFTC site unreachable from the sandbox |
| Broker tick archive (1 GB) | `gh release download`, `release-assets.githubusercontent.com` | connection reset / EOF |
| Measured broker costs | MT5 terminal records | not present in this environment; costs remain ASSUMED |
| Options-implied vol (GVZ) | GitHub search | no verified long history; not used |

## What the register implies

Nine rounds, ~96 configurations, every family from price, macro, calendar,
relative-value, cross-sectional and intraday-clock information. Not one survives
DEV→VAL→TEST→holdout on tradable prices. The two that cleared DEV died in
identifiable ways: one on a regime that ended in 1980, one on a fixing artifact
plus post-2019 decay.

Round 7 added the structural explanation for the whole pattern, which is worth
more than any single rejected strategy: **at retail costs the search is bounded by
turnover, not by signal quality.** Intraday rules with gross alphas of +10% to
+21%/yr at t-stats up to 4.8 lose money once their own trading costs are charged,
because a daily flip costs 9%/yr. That is why the only candidate the project has
ever produced trades 6.7 times a year. Future effort is therefore directed at
low-turnover constructions, and any high-frequency idea must demonstrate gross
alpha above roughly 9%/yr before it is worth implementing at all.

Round 9 added a second low-turnover family that nearly clears the bar (real-yield
residual, DEV t 2.20, positive on both DEV and VAL) and left the 2024-2026 window
unspent because it did not clear it. Two families now sit in the same place: a
credible mechanism, a consistent sign, and too few years to prove it. That is the
honest state of the search, and it is a better state than a validated claim built
on a window that has already been read.

One candidate now exists (XL-001) with a coherent economic mechanism, low turnover
and independent significance on two disjoint periods. Round 8 gave it its first
post-sample reading and the answer was "indistinguishable from zero, both
directions" — the honest outcome for 2.3 years. What it still lacks is genuinely
unseen confirmation accumulated over time, and the forward ledger
(`qts forward log`, `qts forward score`) is the only mechanism that can supply it.
