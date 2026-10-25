# Buy/Sell signal indicator alternatives for XAUUSD@ — 2026-10-25

**Scope:** screen existing publicly documented indicators as replaceable **signal hypotheses** for QTS, not as automatically profitable algorithms. No source integration, account orders, changes to trading policies, or activation authorized by this document. `NO_VALIDATED_EDGE` remains true, and LIVE remains structurally locked.

## Findings

| Candidate | Public primary reference | Mechanism and plausible use | Major caveat |
|---|---|---|---|
| UT Bot Alerts (existing comparison baseline) | User's TradingView chart: sensitivity 1, ATR 10; https://github.com/Rico356/UT-Bot-Alerts-EA | ATR trailing-stop flip; direct BUY/SELL alert | ATR-based trend following, whipsaws during range; bar-close only |
| LuxAlgo Smart Money Concepts (existing context baseline) | https://www.tradingview.com/script/CnB3fSph-Smart-Money-Concepts-SMC-LuxAlgo/ | BOS/CHoCH, market structure, FVG and liquidity levels, NOT a standalone directional execution strategy | Confirmed swing/pivot labels can be retrospectively placed; causal availability must be respected |
| Optimized Trend Tracker (OTT) — PRIMARY DIRECT-ALERT CHALLENGER | https://www.tradingview.com/script/HPbRZvsV/ | MA-derived dynamic trailing boundary and explicit confirmed BUY/SELL trend flips. Uses different mechanics from UT Bot's ATR stop | Lag, false flips in range; variation by choice of moving-average type and lookback. Strictly use `Confirmed Reversal`, never `Potential Reversal` |
| QQE MOD — MOMENTUM FILTER | https://www.tradingview.com/script/TpUW4muw-QQE-MOD/ | Two smoothed RSI/QQE components; blue/red consensus can filter directional entries | Momentum lags; not independent of other momentum features; not a stop-loss |
| SSL Hybrid — BASELINE / PULLBACK FILTER | https://www.tradingview.com/script/YCob5r03-QQE-MOD-SSL-Hybrid-Waddah-Attar-Explosion/ | Trend baseline/channel and continuation entries. Public combined strategy published 2022 | Combination author reports best own results at H1, not broker XAUUSD@ M5; no independent live proof |
| Waddah Attar Explosion — VOLATILITY + DIRECTION FILTER | https://www.tradingview.com/script/iu3kKWDI-Waddah-Attar-Explosion-LazyBear/ | MACD momentum vs Bollinger width 'explosion'; expansion confirmation rather than always-on arrow | Filters out trades, may catch move late; correlated with other momentum filters |
| Supertrend — SIMPLE BASELINE | https://github.com/EarnForex/Supertrend | Open MQL5 implementation; ATR stop reversal/trailing trend | Largely same type of evidence as UT Bot; substitution not automatically an improvement |
| LazyBear Squeeze Momentum — REGIME FILTER | https://www.tradingview.com/script/nqQ1DT5a-Squeeze-Momentum-Indicator-LazyBear/ | Compression-release and momentum direction; 2014 source lineage | Not a dependable standalone Buy/Sell; original author acknowledges need for corroboration |
| WaveTrend [LazyBear] — RANGE/REVERSAL REFERENCE | https://www.tradingview.com/script/2KE8wTuF-Indicator-WaveTrend-Oscillator-WT/ | Overbought/oversold oscillator crossings for mean reversion | Can repeatedly fade a strong trend; keep separate from trend continuation |
| Nadaraya-Watson Envelope [LuxAlgo] — EXCLUDE DEFAULT | https://www.tradingview.com/script/Iko0E2kL-Nadaraya-Watson-Envelope-LuxAlgo/ | Price-envelope extreme alerts | Author explicitly warns default can repaint; visual historic arrows are not a tradable record |
| Lorentzian Classification — RESEARCH ONLY | https://www.tradingview.com/script/WhBzgfDu-Machine-Learning-Lorentzian-Classification/ | Multiple feature distance-classifier; live alerts | Author says performance dashboard is not a strategy backtest; model/data complexity needs independent causal tests |

**Do not rank by stars, indicator colors, win-rate screenshots, vendor profit claims or count of alerts.** TradingView's official repainting docs: https://www.tradingview.com/pine-script-docs/concepts/repainting/ . Realtime current-bar signals and higher-timeframe requests may be revised, while historical charts may obscure this. For MQL5 use documented `iCustom` and `CopyBuffer` for indicator buffers: https://www.mql5.com/en/docs/indicators/icustom .

## Pre-registered research comparisons (new unseen broker period only)

Run four arms **with exactly the same entry/exit cost/exposure framework**:

- **A, baseline:** QTS existing gold signals plus separately logged UT Bot-confirmed and causal SMC swing conditions, no extra trade authority.
- **B, simpler signal challenger:** OTT *confirmed close* BUY/SELL plus **one** preselected momentum filter (QQE MOD). Direction uses only completed H1 and M5 bars. No direct current-candle flip. Keep signal and filters individually switchable for attribution.
- **C, public combined-strategy reference:** reproduce only lawfully accessible/publicly documented conditions of QQE MOD blue/red, SSL Hybrid price-vs-baseline trend, and WAE above explosion level. **Not a claimed gold scalper:** original author's preferred timeframe is H1. If tested at M5, register M5 as a distinct hypothesis from H1. Never copy incompatible copyrighted code into QTS.
- **D, simple comparator:** EarnForex Supertrend *closed-bar confirmed* directional change, identical broker execution and costs, expected to be highly correlated with UT Bot.

The three-indicator combination is a community-derived **published hypothesis**, not evidence of increased profit; UT vs Supertrend are both ATR trend reversers. The direct-alert replacement shortlist is **OTT**, and the best independent extra dimension to examine is **WAE volatility/impulse** or **QQE momentum**; **do not stack both by default** to manufacture apparent 'confluence' from correlated features.

For each arm record every long/short/no-trade and its decision-time: source, variant, closed-candle index, OHLC/ticks used, regime, stop-distance, reason for veto, spread, swap/commission, latency and realised after-cost P&L. Distinguish non-repaint by comparing prefix-only replay with full replay and reconnect history. M5 signals must not read incomplete M5 or H1 bars or use future-confirmed pivots at their plotted swing position.

### Required gates to replace either existing indicator

1. Same broker `XAUUSD@`, same dates/side, comparable average holding period and portfolio risk; real-tick next-executable bid/ask and spread/commission/slippage included.
2. Predeclare one parameter set for each arm, track all trials and multiple-comparison penalty; no searching known holdouts for winner.
3. Minimum matched-sample head-to-head with UT Bot and QTS standalone baseline: net expectancy/trade, profit factor, trading frequency, max equity drawdown, max one-day loss, false flips per regime, 95th-percentile slippage, missed-move ratio.
4. Sensitivity to doubled costs, 1–3s execution latency, spread shock, weekend gap, no bid/ask, restart and order status ambiguity.
5. Positive lower uncertainty bound on *incremental* after-cost value, untouched independent forward period, operational gates and owner approval, then DEMO-only shadow / controlled tests through existing QTS machinery.
6. Otherwise **retain both existing indicators or disable them from trade authorization.** A prettier arrow is not grounds for replacing a strategy.

### Prior QTS evidence, not to be recycled as a clean final holdout

- `docs/research/mt5_broker_ema_365d_20261023.md`: EMA(12/48) fixed holdout mean -2.52 bps with 2-bp stress.
- `docs/research/mt5_broker_opening_range_365d_20261023.md`: opening-range breakout -2.98 bps with same stress.
- Existing `gold_robot/research/scalp_signals.py` already supplies causal closed-bar research signals and prefix-no-lookahead tests in `gold_robot/tests/test_scalp_signals.py`; reuse this engine rather than inventing a second trade/ledger implementation.

**Current decision (2026-10-25):** insufficient verified WMMarkets evidence that any alternative outperforms either UT Bot or LuxAlgo SMC. **Do not replace production signals or modify EA execution settings yet.** Authorize only research comparisons. No tests have been run as part of this literature/source review.

## Third-party licence guard

TradingView 'open source' is not automatically an MIT/GPL/redistribution grant; obey authors' script licensing, tradingview publication rules and dependency licences. For EarnForex/Supertrend inspect `LICENSE` before any code reuse. QTS proprietary licence is a separate constraint. Implement only independently derived generic mathematics or properly licensed dependencies.
