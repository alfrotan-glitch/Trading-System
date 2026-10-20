# XAUUSD Experiment Register

Persistent, append-only record of every materially tested hypothesis. Trial counts
here feed the deflated-Sharpe correction, so nothing is silently dropped — failed
and discarded experiments are the expensive part of the evidence and are listed
with the same care as survivors.

**Standing conclusion: `NO_VALIDATED_EDGE`.** `LIVE` locked, `REAL_CAPITAL_EXPOSURE = 0`.
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

## Unavailable inputs (attempted, with evidence)

| Input | Attempt | Outcome |
|---|---|---|
| CFTC COT positioning | GitHub code search for historical COT, `cftc.gov` direct | only single-snapshot JSON found; CFTC site unreachable from the sandbox |
| Broker tick archive (1 GB) | `gh release download`, `release-assets.githubusercontent.com` | connection reset / EOF |
| Measured broker costs | MT5 terminal records | not present in this environment; costs remain ASSUMED |
| Options-implied vol (GVZ) | GitHub search | no verified long history; not used |

## What the register implies

Four rounds, ~75 configurations, every family from price, macro, calendar,
relative-value and cross-sectional information. Not one survives DEV→VAL→TEST→holdout
on tradable prices. The two that cleared DEV died in identifiable ways: one on a
regime that ended in 1980, one on a fixing artifact plus post-2019 decay.

Continuing to add price-derived variants would raise the trial count while the
detection floor stays at SR 0.35 — that is arithmetic, not pessimism. The inputs
that would change the answer are the ones listed as unavailable above.
