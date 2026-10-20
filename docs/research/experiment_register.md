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

## Unavailable inputs (attempted, with evidence)

| Input | Attempt | Outcome |
|---|---|---|
| CFTC COT positioning | GitHub code search for historical COT, `cftc.gov` direct | only single-snapshot JSON found; CFTC site unreachable from the sandbox |
| Broker tick archive (1 GB) | `gh release download`, `release-assets.githubusercontent.com` | connection reset / EOF |
| Measured broker costs | MT5 terminal records | not present in this environment; costs remain ASSUMED |
| Options-implied vol (GVZ) | GitHub search | no verified long history; not used |

## What the register implies

Six rounds, ~83 configurations, every family from price, macro, calendar,
relative-value and cross-sectional information. Not one survives DEV→VAL→TEST→holdout
on tradable prices. The two that cleared DEV died in identifiable ways: one on a
regime that ended in 1980, one on a fixing artifact plus post-2019 decay.

One candidate now exists (XL-001) with a coherent economic mechanism, low turnover
and independent significance on two disjoint periods. What it lacks is genuinely
unseen confirmation, which no further analysis of the same data can provide. The
forward ledger (`qts forward log`, `qts forward score`) is the mechanism that
accumulates it.
