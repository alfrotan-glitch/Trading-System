# Strategy research brief — simple, cost-aware XAUUSD trend rules

- **Date:** 2026-10-11
- **Role:** Agent 1 — strategy research
- **Repository baseline inspected:** `055f1caba3b101f6a6c8d368295fda7d577d65b0`
- **Status:** research shortlist only; **`NO_VALIDATED_EDGE`**. No orders, broker access, strategy promotion, or risk/authorization changes were made.

## Executive decision

There is no evidence-backed strategy to deploy. The repository already tested daily and M15 moving-average and Donchian families. None passed the full validation gates; cost estimates are assumed, one long-history quote stream is not independently verified, and the M15 holdout is reused. The shortlist below was selected after reviewing those results, so this document is **not an ex-ante preregistration** and the candidates are not eligible for another unadjusted test on the same data. They are at most three hypotheses for a future, independent research run—not trading advice or an assertion of profitability.

Priority for any next offline test:

1. **Daily Donchian 55/20, 2 × ATR(14)** — low-frequency channel reference with more cost headroom than the tested M15 channel, but statistically weak and underpowered.
2. **Daily SMA 20/100, 3 × ATR(14)** — simple trend-filter comparator with low turnover, also statistically weak and underpowered.
3. **M15 Donchian 384/192, 3 × ATR(14)** — retain only as a conditional candidate if measured all-in costs are at or below its historical break-even estimate and independent M15 data are obtained.

The existing EMA 12/48 DEMO diagnostic is deliberately **not** re-proposed or changed here. It remains a frozen policy, not a validated strategy; this work places no DEMO orders.

## Repository findings that constrain the recommendation

| Existing evidence | What it says | Consequence |
|---|---|---|
| Daily preregistered study `LH-XAUUSD-D1-2026-10-10` | `donchian_55_20_atr2`: +$160.22 on the 2020–2025 holdout, 19 holdout round turns, break-even cost multiplier 4.76×; walk-forward Sharpe 0.14, 5/10 positive years, DSR 0.06. `ma_20_100_atr3`: +$530.11, 14 holdout round turns, break-even 23.66×; walk-forward Sharpe 0.17, 6/10 positive years, DSR 0.12. | Neither passed G1–G7. The low trade counts and failed multiple-testing/statistical gates prevent an edge claim. Buy-and-hold returned +$8,795.66 on the same holdout. See `docs/research/longhistory_results_2026-10-10.md`. |
| M15 preregistered study `LH-XAUUSD-M15-2026-10-10` | `donchian_384_192_atr3`: +$288.09 at base assumed costs, but −$983.49 at 2× costs; 231 round turns; break-even 1.215×; walk-forward Sharpe −0.247, 4/10 positive years, DSR 0.004. Buy-and-hold returned +$8,795.66. | Fails 5/7 gates; 83% of base-cost gross is consumed by modeled costs. The positive Dukascopy replicate is one previously viewed year, not independent confirmation. See `docs/research/longhistory_intraday_results_2026-10-10.md`. |
| Cost and source audits dated 2026-10-11 | The study's round-turn cost is about 6.077 bps at $1,300, but is **ASSUMED** (3 bps full spread, 1 bp slippage per side, $7/lot/side commission, and zero financing). Broker costs remain unmeasured. The M15 second-source candidate was rejected; no independent licensed confirmation exists. | No economic claim can be eligible. Spot/CFD overnight financing, executable bid/ask, spread spikes, slippage, and fees must be measured; current zero-financing assumptions are especially material for multi-day holds. See `docs/research/m15_cost_sensitivity_2026-10-11.md` and `docs/research/m15_second_source_check_2026-10-11.md`. |
| Existing implementation | `src/qts/research/longhistory/signals.py` already implements causal `donchian` and `ma_cross`; channel extrema use prior bars (`shift(1)`). `src/qts/research/longhistory/engine.py` implements next-open fills, stop-gap treatment, explicit costs, and trade-ledger reconciliation. | Reuse this research path; do not add a second indicator/backtest stack or modify a frozen preregistration to make it fit. |

### Sizing reconciliation

The existing frozen long-history protocols use a 1% stop-risk budget, while the canonical product risk authority caps per-trade risk at 50 bps. The research-only sizing helper now accepts an explicit lower risk fraction (for example, `0.005` for 50 bps) for stop-based `ma_cross` and `donchian` plans; it rejects invalid values and any override above the legacy 1% maximum. The frozen builders retain their 1% default and existing plan metadata, as covered by regression tests. No candidate protocol, product risk limit, execution path, or authorization was changed. The proposed rules above use **no more than the existing 50 bps cap** and any stricter resolved mode/configuration limits. Consequently, historical dollar P&L in the study tables does not describe the proposed sizing and must not be presented as its expected P&L. A fresh preregistration must freeze the intended sizing and rerun the relevant metrics; this brief does not change any product risk limit.

### Evidence boundary

The cited backtests are informative diagnostics, not a validation. Their historical research data is one unverified third-party quote stream; the M15 stamp convention is not established as bar-open versus bar-close; the replicate has no verified independent long-history overlap; and costs are assumed. The 2020–2025 holdout and 2025–2026 replicate must not be treated as fresh tuning targets. A new test needs its own preregistration and a genuinely new, independently sourced test window.

## Proposed fixed candidate specifications (future data only)

### 1. Daily Donchian 55/20 with 2 × ATR(14) stop (`D55-20-ATR2-D1`)

- **Instrument / timeframe:** XAUUSD; one UTC trading-day bar per day using the QTS daily convention (22:00 UTC roll), complete days only. The data provider's timestamp semantics must be verified before session construction.
- **Warm-up:** at least 55 completed daily bars plus valid ATR(14); use Wilder ATR on true range.
- **Entry / direction:** after completed bar `t`, go long if `Close[t] > max(High[t-55:t])`; go short if `Close[t] < min(Low[t-55:t])`. Channel windows exclude bar `t`. Signal is executed at the next bar's open, not at the signal close. One position at a time; no pyramiding.
- **Trend filter:** the 55-bar channel breakout is the sole direction/trend filter. Do **not** append an SMA(200), efficiency-ratio, or session filter in this frozen version; that would be a different hypothesis.
- **Exit:** close a long if `Close[t] < min(Low[t-20:t])`; close a short if `Close[t] > max(High[t-20:t])`. An opposite 55-bar breakout reverses at the next open. A channel exit otherwise leaves the strategy flat until another entry signal.
- **Protective stop:** at entry fill, place a fixed, non-trailing stop `2 × ATR14[t]` below the long fill or above the short fill. ATR is known at the signal close. If the next open gaps through a stop, use the worse open; otherwise use the stop level. A stop blocks immediate same-direction re-entry until the signal state changes.
- **Position sizing:** cap initial stop risk at **50 bps (0.50%) of current equity**, the canonical per-trade ceiling; do not override any stricter resolved mode/configuration limit. For XAUUSD contract size `100 oz/lot`, stop distance `d` dollars per ounce and fill price `p`, calculate `q = floor_to_0.01(min(0.005 × equity/(100 × d), equity/(100 × p), resolved quantity/notional/exposure caps))`. If `q < 0.01 lot`, skip. The 1.0× notional cap in this research brief is tighter than the canonical leverage allowance. This is an offline sizing rule, not authorization to trade.
- **Why it might work:** a multi-week price extreme can reflect gradual macro repricing and trend/CTA flows; the slower entry can avoid some short-horizon noise, while the shorter exit channel cuts failed trends and leaves successful moves room to run. Fewer turns should reduce cost drag versus a short lookback.
- **Why not to trust it yet:** the exact QTS-tested variant failed the full gates, had only 19 holdout turns, and earned only 5 positive walk-forward years. Its apparent holdout cost tolerance does not repair low power, unstable regimes, source uncertainty, or large underperformance versus buy-and-hold.

### 2. Daily SMA 20/100 crossover with 3 × ATR(14) stop (`SMA20-100-ATR3-D1`)

- **Instrument / timeframe:** same verified UTC daily XAUUSD bars and complete-day rules as candidate 1.
- **Warm-up:** at least 100 completed daily closes plus valid ATR(14).
- **Entry / direction:** set target state long when `SMA20[t] > SMA100[t]`, short when `SMA20[t] < SMA100[t]`; a change of state is the crossover. Execute a new/reversed target at the next daily open. One position at a time; no pyramiding.
- **Trend filter:** the fast/slow SMA relationship **is** the trend filter; no additional filter.
- **Exit:** reverse on an opposite SMA state at the next open, or go flat when the protective stop is hit. No extra time exit.
- **Protective stop:** fixed, non-trailing `3 × ATR14[t]` from the next-open fill; gap-through fills at the worse open. A stopped position is not re-entered in the same direction until the SMA state changes away and back.
- **Position sizing:** same formula and constraints as candidate 1, using `d = 3 × ATR14[t]`; initial stop risk must not exceed the current 50 bps per-trade ceiling or any stricter resolved limit.
- **Why it might work:** averaging over 20 and 100 days can suppress noise and delay entries until the market has shown sustained direction. A three-ATR stop allows ordinary daily gold volatility while mechanically limiting the initial loss.
- **Why not to trust it yet:** the repository's nearest frozen variant, `ma_20_100_atr3`, failed Holm and DSR, had only 61 combined OOS round turns, and lost to buy-and-hold. Its reported +$530 holdout is not a reproducible edge claim.

### 3. M15 Donchian 384/192 with 3 × ATR(14) stop (`D384-192-ATR3-M15`)

- **Instrument / timeframe:** XAUUSD 15-minute bars. Use only after bar-open/close stamps, UTC conversion, gaps, and source provenance are qualified. The QTS study's 92 complete bars/trading day makes 384 bars about four trading days, but that convention must be verified for a new source.
- **Warm-up:** 384 completed M15 bars plus valid ATR(14).
- **Entry / direction:** after completed bar `t`, go long if `Close[t] > max(High[t-384:t])`; go short if `Close[t] < min(Low[t-384:t])`; execute at the next M15 open. One position at a time; no pyramiding.
- **Trend filter:** the 384-bar breakout is the sole trend filter; no extra moving-average/session filter.
- **Exit:** long exits on a close below the prior 192-bar low; short exits on a close above the prior 192-bar high. Opposite 384-bar breakout reverses at the next open. Channel exits otherwise leave the position flat.
- **Protective stop:** fixed, non-trailing `3 × ATR14[t]` from entry fill, with the same adverse gap handling as candidate 1.
- **Position sizing:** same formula and existing 50 bps maximum per-trade risk as candidate 1, using `d = 3 × ATR14[t]`; apply all current resolved quantity, notional, exposure, spread, freshness, and stop controls unchanged. Skip if the minimum lot would breach a cap.
- **Why it might work:** a roughly four-day breakout may capture persistent price discovery while trading less often than conventional 20/55-bar M15 breakouts. The longer window is a deliberate transaction-cost tradeoff, not a parameter selected from the replicate.
- **Why it is conditional only:** the exact QTS variant's break-even multiplier is just 1.215× the assumed cost and its walk-forward result is negative. At approximately 2× assumed costs its holdout loses. Only measure it again if independent M15 data and actual broker spread, commission, slippage, and financing make the pre-registered cost test meaningful.

## Shared execution and research contract

1. **Causality:** indicators use completed bars only; signal at close `t` fills at open `t+1`. Exclude the current bar from channel maxima/minima. No same-close fills, partial-bar signals, interpolation, or gap repair.
2. **Cost basis:** charge executable bid/ask, commission, slippage, and broker financing/swap on each round turn/holding interval. Mark each component `MEASURED` only if it was actually measured. Continue 2×/3× stress, and show break-even cost. Mid-only bars plus assumed friction are diagnostic, not claim-eligible.
3. **Stops:** stops are not guaranteed prices. Model gap-through stops adversely; if a bar's OHLC cannot determine event ordering, use the more adverse ordering and disclose it.
4. **No execution changes:** do not change `LIVE_LOCKED`, `REAL_CAPITAL_EXPOSURE = 0`, existing risk ceilings, DEMO authorization, or the registered EMA 12/48 policy. No live/demo orders or order-path code are part of this research task.
5. **No selection leakage:** the old holdout and replicate have been examined. Freeze the three-or-fewer candidates, hashes, cost basis, sample windows, tests, and stop/size rules in a new preregistration before accessing any new test data. Count every tested variant as a trial. Existing validation gates remain binding.
6. **Recommendation:** keep the current posture `NO_TRADE`. Run no additional parameter sweep on the current reused holdout. The next useful milestone is qualified independent data and measured costs, not another indicator or infrastructure layer.

## Follow-up verification

The research implementation and cost machinery were checked with focused tests:

```text
Long-history and M15 tests after the sizing change: 39 passed, 2 skipped
Full suite (--run-integration --run-research, 4 workers): 1795 passed, 6 skipped, 4 warnings
Ruff: all checks passed; mypy: no issues in 182 source files
Bandit: no issues identified across 47,711 source lines
JS unit tests (unchanged UI): 48 passed; JS syntax checks passed; npm audit: 0 vulnerabilities
```

The stop-sizing regression tests verify that explicit 50 bp inputs halve stop-based size on the synthetic fixture, default outputs and plan metadata remain identical for frozen MA/Donchian candidates, and invalid or increased risk budgets are rejected. This is mechanics-only; it is not an economic backtest. The earlier full-suite run exposed an order-dependent regression-test import: `tests/test_conftest_git_status.py` could bind the name `conftest` to the nested integration conftest instead of the root test conftest. The test now resolves the root conftest plugin by file path. The full suite passed on rerun. The four pytest warnings are Starlette's deprecation warning about `httpx` in `TestClient`.

These checks validate signal/engine, frozen-benchmark, cost-model, readiness, safety, typing/lint/security, and UI mechanics; they are **not** an economic validation. No new backtest was run: the checkout contains saved evidence and a synthetic 1H fixture, but no local raw daily/M15 price series. Costs remain unmeasured, and the test pass does not change `NO_VALIDATED_EDGE`.

## Research and implementation references

### Quantitative research

- Moskowitz, T. J., Ooi, Y. H., & Pedersen, L. H. (2012). “Time Series Momentum.” *Journal of Financial Economics*, 104(2), 228–250. [DOI](https://doi.org/10.1016/j.jfineco.2011.11.003) · [paper PDF](https://w4.stern.nyu.edu/facdir/lpederse/papers/TimeSeriesMomentum.pdf). The study documents own-return persistence over roughly 1–12 months across 58 futures/forward markets, including gold futures. This supports a broad trend mechanism; it does not validate intraday spot XAUUSD or this specification.
- Hurst, B., Ooi, Y. H., & Pedersen, L. H. (2017). “A Century of Evidence on Trend-Following Investing.” *The Journal of Portfolio Management*, 44(1), 15–29. [DOI](https://doi.org/10.3905/jpm.2017.44.1.015) · [public paper PDF](https://fairmodel.econ.yale.edu/ec439/hurst.pdf). Broad, multi-market and multi-decade trend evidence; not a single-instrument XAUUSD test.
- Brock, W., Lakonishok, J., & LeBaron, B. (1992). “Simple Technical Trading Rules and the Stochastic Properties of Stock Returns.” *The Journal of Finance*, 47(5), 1731–1764. [DOI](https://doi.org/10.1111/j.1540-6261.1992.tb04681.x). Tests moving-average and trading-range-break rules on the Dow Jones Industrial Average; the different market/sample limits direct transfer to gold.
- Sullivan, R., Timmermann, A., & White, H. (1999). “Data-Snooping, Technical Trading Rule Performance, and the Bootstrap.” *The Journal of Finance*, 54(5), 1647–1691. [DOI](https://doi.org/10.1111/0022-1082.00163). Relevant caution: performance must be adjusted for the full family of rules searched.
- Miffre, J., & Rallis, G. (2007). “Momentum Strategies in Commodity Futures Markets.” *Journal of Banking & Finance*, 31(6), 1863–1886. [DOI](https://doi.org/10.1016/j.jbankfin.2006.12.005). Useful commodity-futures context, including term-structure/roll components; spot XAUUSD has no directly observed futures curve here, so that component must not be inferred from this evidence.

### Mature open-source implementations reviewed

- [QuantConnect LEAN](https://github.com/QuantConnect/Lean) (Apache-2.0): its [Donchian Channel reference](https://www.quantconnect.com/docs/v2/writing-algorithms/indicators/supported-indicators/donchian-channel) defines upper/lower bands as rolling high/low extrema; its [ATR implementation](https://github.com/QuantConnect/Lean/blob/master/Indicators/AverageTrueRange.cs) explicitly includes previous-close gaps and Wilder smoothing. Its modular fee/slippage modeling is also consistent with keeping friction separate from signals.
- [Backtrader's Donchian recipe](https://www.backtrader.com/recipes/indicators/donchian/donchian/) calls out the lookback shift: including the current bar can make a close breakout impossible, while a prior-bar channel can be broken. This is a practical look-ahead/off-by-one hazard. QTS already avoids it with `shift(1)`.
- The repository's [`longhistory_method_survey_2026-10-10.md`](longhistory_method_survey_2026-10-10.md) records its review of LEAN, Qlib, and Freqtrade's testing concepts and the independent implementations used in QTS. No external code is copied or required for the candidate rules above.
