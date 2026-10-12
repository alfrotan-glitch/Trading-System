# Long-history XAUUSD intraday (M15) results — 2026-10-10

**Preregistration:** `LH-XAUUSD-M15-2026-10-10` (`preregistration_longhistory_m15_2026-10-10.md`, committed `732eeb3` before any intraday walk-forward, holdout or replicate result).
**Evidence:** `data/evidence/longhistory/intraday_research_final.json`. **Tables:** `longhistory_intraday_results_tables_2026-10-10.md` (generated from the JSON, not typed by hand).
**Code:** `src/qts/research/longhistory/intraday_protocol.py`, `intraday_signals.py`; runner `scripts/run_longhistory_intraday.py --stage final`.

## Verdict

**`NO_VALIDATED_EDGE`. Claim: none.**

No intraday group passes all seven gates. The best groups pass two of seven (G1 and G6 for `ma_cross` and `donchian`). Costs are ASSUMED, so no economic-edge claim is eligible under any outcome.

## What was tested

- **Data.** BaseMax XAUUSD 15-minute bars, converted from broker server time to UTC, restricted to complete trading days (22:00 UTC roll; at least 40 bars). 474,388 research bars from 2004-06-11 to 2025-02-28. 92 bars per complete day. Replicate: Dukascopy M15, 26,030 complete-day bars, 2025-08-06 to 2026-09-16.
- **Configurations.** 13 candidates plus 1 control. Four family groups: MA crossover (6), Donchian breakout (3), 1-hour and 4-hour range expansion (2), and a new intraday-only session-range breakout (2). The deflated Sharpe uses 40 trials: the 26 daily configurations plus these 14, because the holdout period was already used.
- **Selection.** Within each group, the training-window winner on 2010–2019 (walk-forward per year, then one frozen choice for the holdout).
- **Holdout.** 2020-01-01 to 2025-02-28, run once, at base cost and at 2× and 3× costs.

## Holdout (selection frozen on data through 2019)

| Group | Selected | Net USD | Sharpe | Max DD | Round turns | Cost USD | Gross USD | Net @2× | Break-even × |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| ma_cross | ma_32_128_atr3 | +1,092.55 | 0.214 | −31.6% | 1,154 | 7,562 | +8,655 | −4,266 | 1.16× |
| donchian | donchian_384_192_atr3 | +288.09 | 0.104 | −16.8% | 231 | 1,439 | +1,727 | −983 | 1.22× |
| session_breakout | session_brk_b0 | −4,467.03 | −1.127 | −53.9% | 1,265 | 5,584 | +1,117 | −7,273 | 0.16× |
| volatility_expansion | rexp_k10_h16 | −9,938.70 | −7.142 | −99.4% | 8,162 | 7,770 | −2,169 | −9,999 | negative at zero cost |
| **buy-and-hold (reference)** | 1.0× long | **+8,795.66** | 0.860 | −21.9% | 1 | 8 | | +8,785 | |

Holm-adjusted p-values are 1.00 for every group. Bootstrap 95% Sharpe intervals all include zero or lie below it. Buy-and-hold beats every intraday group on the holdout.

## Walk-forward 2010–2019 (base cost)

| Group | WF Sharpe | Positive years | Chained return |
|---|---:|---:|---:|
| donchian | −0.247 | 4 / 10 | −22.4% |
| ma_cross | −0.717 | 2 / 10 | −53.6% |
| session_breakout | −1.030 | 2 / 10 | −63.0% |
| volatility_expansion | −6.727 | 0 / 10 | −100.0% |

Buy-and-hold over the same ten years chained to +34.4%.

## Gates

| Group | Gates passed | Failed |
|---|---:|---|
| donchian | 2 / 7 | G2 (2× cost), G3 (walk-forward), G4 (Holm), G5 (DSR), G7 (regimes) |
| ma_cross | 2 / 7 | G2, G3, G4, G5, G7 |
| session_breakout | 1 / 7 | G1, G2, G3, G4, G5, G7 |
| volatility_expansion | 1 / 7 | G1, G2, G3, G4, G5, G7 |

DSR on the combined out-of-sample series with 40 trials: donchian 0.004, ma_cross 0.0003, session_breakout 0.0, volatility_expansion 0.0 (the gate needs ≥ 0.95).

## Reading the result

- **Cost decides the MA and Donchian results.** The `ma_cross` selection makes +8,655 gross on the holdout, but it trades 1,154 round turns, so costs of 7,562 take it to +1,093. At 1.16× the assumed cost, it breaks even. Measured broker costs are therefore more decisive at M15 than at daily frequency, and no conclusion can be drawn until they are measured (see blockers).
- **Sign randomisation.** The `ma_cross` holdout trades have a direction null p-value of 0.007, so trade direction carries some information in this window. Gross information is not net profit, and the gates do not pass.
- **Range expansion is not viable at this cost.** 8,162 round turns on the holdout, gross negative. The 1-hour and 4-hour impulse rules do not survive even at zero cost.
- **Session breakout is negative net and gross on the holdout, and negative in the walk-forward years.** Its replicate result is near zero, as the table below shows.
- **Max drawdown reaches −99% for `rexp_k10_h16`.** The equity curve is effectively destroyed, not just unprofitable.

## Replicate (informational, not a gate)

The holdout selections were run unchanged on Dukascopy M15, 2025-08-06 to 2026-09-16. This series is **not untouched**: the daily cycle and an earlier study used it. It has 288 complete days.

| Group | Net USD | Round turns | Sharpe |
|---|---:|---:|---:|
| donchian | +3,935 | 47 | 1.69 |
| ma_cross | +2,499 | 263 | 1.01 |
| session_breakout | −82 | 246 | −0.01 |
| volatility_expansion | −6,977 | 1,750 | −4.86 |
| buy-and-hold (replicate) | +2,596 | 1 | 0.88 |

The replicate is positive for `donchian` and `ma_cross`. **It cannot change the verdict.** The protocol forbids re-selecting on the replicate, and the replicate is not an independent sample. Its positive figures are a reason to test the Donchian and MA families on fresh data with measured costs. They are not evidence of an edge. The replicate is one 288-day window. On that window buy-and-hold (+2,596) is roughly level with `ma_cross` (+2,499) and below `donchian` (+3,935).

## Bias checks

Truncation (causality) passed for all 14 configurations at three cut points. ATR(14) and realised-volatility warm-up both converged. Recorded in `bias_checks` in the evidence file.

## Limits

- All costs are ASSUMED. The gross-to-net gap is the most sensitive result in this study.
- BaseMax is one third-party quote stream. It is not independent of the ejtraderLabs copy, and its licence is unverified. Bar timestamps are used as the source gives them. The provenance record does not establish whether a stamp marks the bar open or the close. If it marks the close, every session boundary moves by one bar.
- The 2020–2025 holdout was used by both the daily and intraday cycles. Results on it are not fully independent. The 40-trial deflation is the protection applied.
- The intraday families are a deliberate subset. TSMOM, RSI(2), and the efficiency-ratio gate were not carried to M15, for the reasons in the preregistration §5.

## Open items

- Broker M15 depth and measured costs (Windows MT5 probe and cost check). These are the decisive inputs for any M15 result.
- A second, independent long-history M15 source.
- A fresh out-of-sample period for `donchian_384_192_atr3` and `ma_32_128_atr3` only if measured costs make the gross edge net-positive. Any such test needs its own preregistration.
