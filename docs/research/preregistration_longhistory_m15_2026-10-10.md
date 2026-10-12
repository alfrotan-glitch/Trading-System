# Preregistration — XAUUSD Long-History Intraday (M15) Strategy Research

**ID:** `LH-XAUUSD-M15-2026-10-10`
**Status:** frozen and committed before any intraday walk-forward, holdout, or replicate result was computed. Code: `src/qts/research/longhistory/intraday_protocol.py`, `intraday_signals.py`. Runner: `scripts/run_longhistory_intraday.py --stage dev|final`.
**Evidence:** `data/evidence/longhistory/intraday_research_final.json`, tables `docs/research/longhistory_intraday_results_tables_2026-10-10.md`.
**Parent:** the daily cycle `LH-XAUUSD-D1-2026-10-10` (`preregistration_longhistory_2026-10-10.md`). Its data provenance, cost model, gates and selection rule are inherited unchanged, except where §9 says so.

This document fixes the question, candidates, calendar, selection rule, gates and verdict rule before the holdout is evaluated. A failed gate is a failed gate. Nothing here may be re-tuned against the holdout or the replicate. If a value must change, the change is a new preregistration with a new ID.

## 1. Question

Does any simple, causal, intraday (15-minute) XAUUSD rule from a documented family produce positive net performance after ASSUMED costs, and does that survive the same chain of tests as the daily cycle: walk-forward selection on 2010–2019, the untouched 2020-01-01 → 2025-02-28 holdout with training-only selection, 2× and 3× cost stresses, a multiple-testing correction over every configuration evaluated on this series, and a mechanical regime split?

This is a research question. A pass earns forward validation, not a claim. All costs are ASSUMED, `CLAIM_ELIGIBLE_BASES = {MEASURED}`, so no economic-edge claim can result from this study.

## 2. Data and windows

| Role | Source | Window (UTC) | Bars |
|---|---|---|---|
| Research (selection, walk-forward, holdout) | BaseMax XAUUSD 15m, converted to UTC (see the data provenance record) | 2004-06-11 → 2025-02-28, complete trading days only | 474,388 |
| Replicate (informational, final stage only) | Dukascopy mirror 15m, UTC | 2025-08-06 → 2026-09-16, complete trading days only | 26,030 (of 26,038 total) |

- A **trading day** rolls at 22:00 UTC (`daily.trading_day_label`). A day is **complete** when it has at least 40 bars (`daily.DEFAULT_MIN_BARS`). Only bars of complete days are used. A partial session can never generate a signal or a fill.
- **Bars per complete day: 92.** This is the median and maximum across the research series, and it is the same for the replicate. The annualisation constant is therefore `PERIODS_PER_YEAR = 92 × 252 = 23,184`. It is a calendar normalisation, not a tuned parameter.
- Timestamps are used as the source stamps, converted to UTC as the provenance record describes. **The record does not establish whether a stamp marks the bar open or the bar close.** If it is the close, every session boundary in this study is shifted by one 15-minute bar. This is a stated limitation. It is not corrected here, because correcting it would be a post-hoc change to the protocol.
- The research series ends at 2025-02-28. The 2025-03 onward BaseMax data is partial and is not used.

## 3. Execution model (inherited, unchanged)

Identical to the daily cycle §3, applied per 15-minute bar. A decision taken at the close of bar `t` fills at the open of bar `t+1`. Stops are checked against each bar's range and fill at the stop, or at the open on a gap. Re-entry in the same direction is blocked until the state changes. A position still open at the end of a window is closed at the final close and marked forced. Accounting identity: final equity minus initial equity equals the sum of trade net P&L (tested).

Long-only or long/short is as stated per family. Maximum notional is 1.0× equity, with no leverage.

## 4. Costs (ASSUMED)

Inherited: `CostModel(spread_bps=3, slippage_bps=1 per side, commission=$7 per lot per side, financing=0)`, basis `ASSUMED`. At an XAUUSD price of 1300 this is about 6.1 bps round turn. Stresses 2× and 3× are the same (inherited). Costs are not measured here; the study cannot test a claim.

At 15-minute frequency, trade counts are far higher than daily, so cost drag is structurally larger. The break-even cost multiplier is reported for every holdout result so that this is visible.

## 5. Candidate grid (14 configurations, all counted as trials)

Bar-count parameters: 16 bars = 4 h, 32 = 8 h, 64 = 16 h, 96 = 1 trading day, 128 = 32 h, 192 = 2 days, 256 ≈ 2.8 days, 384 = 4 days. ATR is ATR(14) in bars.

| Family group | Configuration | Definition |
|---|---|---|
| `ma_cross` | `ma_16_64_nostop`, `ma_16_64_atr3` | SMA 16/64 bars stop-and-reverse; with / without 3-ATR stop |
| `ma_cross` | `ma_32_128_nostop`, `ma_32_128_atr3` | SMA 32/128 bars, same two variants |
| `ma_cross` | `ma_64_256_nostop`, `ma_64_256_atr3` | SMA 64/256 bars, same two variants |
| `donchian` | `donchian_96_48_atr2` | 96-bar close breakout, 48-bar opposite exit, 2-ATR stop |
| `donchian` | `donchian_96_48_atr3` | as above, 3-ATR stop |
| `donchian` | `donchian_384_192_atr3` | 384-bar breakout, 192-bar exit, 3-ATR stop |
| `volatility_expansion` | `rexp_k10_h4` | bar body > 1.0 × ATR20 starts a 4-bar trade (1 h), long or short |
| `volatility_expansion` | `rexp_k10_h16` | as above, 16-bar trade (4 h) |
| `session_breakout` | `session_brk_b0` | Asian range 00:00–07:00 UTC; first close above the range high (or below the low) between 07:00 and 16:00 UTC opens a trade at the next open. Stop at the opposite range boundary, sized to `RISK_PER_TRADE` (1%). Flat from the 19:00 UTC decision. One entry per session |
| `session_breakout` | `session_brk_b025` | as `session_brk_b0`, but the close must exceed the range by a 0.25-ATR buffer |
| `bollinger_control` | `bollinger_20_2_control` | CONTROL, never a candidate. Bollinger(20 bars, 2σ) fade to mean, vol-targeted |

**Scope decisions made before any intraday result was seen:**

- **TSMOM and RSI(2) are not carried to M15.** TSMOM rebalances at month-end and RSI(2) uses an SMA of 200 *days*. A bar-count substitute would be a different strategy, so it is excluded rather than approximated.
- **`trend_gated` is not carried to M15.** It depends on the 60-day efficiency ratio, which would need its own preregistered window.
- **Session breakout is intraday-specific.** It has no daily analogue. Its definition is fixed above.
- **Volatility windows** are 60 trading days in bars (5,520 bars), matching the daily 60-day window.
- **Regime labels** use a 12-month (23,184-bar) trend and the expanding median of the 60-day realised volatility, with a 12-month minimum history, matching the daily definition in calendar units.

The number of configurations is 14 in this cycle (13 candidates plus 1 control). **Every configuration evaluated on this research series is counted**, including the 26 daily configurations, which used the same 2020–2025 holdout. The deflated Sharpe therefore uses `N_TRIALS = 26 + 14 = 40`. This is a deliberate conservative choice, not a bug.

## 6. Windows and selection rule

Inherited from the daily protocol:

- Walk-forward: one test year per fold, 2010 through 2019, using expanding training windows that start 2004-06-11. Selection is frozen within each fold.
- Holdout: selection uses data through 2019-12-31 only. The chosen configuration per group is then run once on 2020-01-01 → 2025-02-28. A **single** evaluation, not repeated.
- Within each family group, select the candidate with the highest net Sharpe on the training window at base costs. Candidates must have at least 20 round turns in training. Ties go to the earlier candidate.
- Replicate: the holdout selections are run unchanged on the Dukascopy M15 series (2025-08-06 → 2026-09-16). Informational, not a gate. The Dukascopy series is not untouched: the daily cycle and an earlier study used it, so it is a replicate, not an out-of-sample test.

**Holdout reuse.** The 2020–2025 holdout was already evaluated for the daily cycle. It is therefore not a fresh sample for this cycle. The cumulative trial count (40) and the Holm correction over this cycle's groups are the protections applied. The verdict must be read with this caveat stated.

## 7. Statistics

- Sharpe: annualised with `sqrt(23,184)`, on per-bar returns that include flat bars.
- Confidence intervals: circular block bootstrap of per-bar returns, block 20 bars.
- P-value per group: one-sided block-bootstrap test of mean return greater than 0, 2000 resamples.
- Multiple testing: Holm step-down across the four candidate groups in the holdout stage.
- Deflated Sharpe: `N_TRIALS = 40`, annualised with 23,184 periods per year.
- Sign-randomisation null on the holdout trades (inherited).

## 8. Gates (all must pass for a group to pass)

Identical thresholds to the daily protocol:

| Gate | Test |
|---|---|
| G1 | Holdout net > 0 and holdout Sharpe > 0 at base cost |
| G2 | Holdout net > 0 at 2× cost |
| G3 | Walk-forward chained Sharpe > 0, and positive net in at least 6 of 10 test years |
| G4 | Holm-adjusted one-sided p ≤ 0.05 |
| G5 | Deflated Sharpe on the combined out-of-sample series ≥ 0.95 with `N_TRIALS = 40` |
| G6 | Out-of-sample round turns ≥ 100 |
| G7 | All four regimes present, with positive net in at least 3 |

**Verdict rule (inherited):** `FORWARD_VALIDATION_CANDIDATE_ONLY` if any group passes all gates, otherwise `NO_VALIDATED_EDGE`. Either way the claim is `none`, because costs are ASSUMED.

Bias checks are run on the final stage, not left to tests alone: truncation (causality) on every configuration at three cut points, and warm-up convergence of ATR(14) and the realised volatility. Any failure is reported and blocks the verdict.

## 9. Deviations and disclosure

- **Ordering.** This preregistration is committed before the dev stage (2010–2019 walk-forward) and before the final stage runs. The daily cycle ran its dev stage before its prereg commit, and that is disclosed in its §9. This cycle does not repeat that deviation.
- **Shared code change.** The runner, stats and signals gained protocol and annualisation parameters with daily defaults. The daily final evidence was re-run after the change and is identical except for a new `periods_per_year` field. The daily committed evidence file was not modified.
- **Window end.** Windows now include every bar on the end day (`searchsorted` on the next midnight). For daily data this is identical to the original behaviour. For M15 it is necessary.
- **Bug found and fixed before any intraday run.** The intraday protocol first re-exported the daily candidate lookup, which would have made the replicate step look up the wrong candidate. Caught by a unit test and fixed before the dev stage. No result was affected.
- **Dev stage.** The dev stage (2010–2019 folds only) is run once after this commit, for pipeline debugging. Its output is not used for selection, and it is not committed as evidence. Only the final stage is evidence.
