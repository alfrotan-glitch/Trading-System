# QTS Gold MT5 — owner's execution plan and Stop-Loss root-cause review
**Date:** 2026-10-26. **Status:** design and observation ONLY; current live trading locked; **NO_VALIDATED_EDGE**.

## 1. Resolve $3,000 Strategy Tester constraint

The operator reports their *local MT5 Strategy Tester* does not allow an initial deposit below **USD 3,000**. Respect the interface as observed; do not assume this proves the broker's minimum REAL funding requirement. Earlier generic advice to test $100/$200 inside this terminal was not executable. The **$200 Binance Spot conversation was separate** and must not be conflated with XAUUSD capital.

Use **USD 3,000 initial equity in MT5 Strategy Tester**, WMMarkets `XAUUSD@`, M15 baseline and separately M5, real-tick mode, zero optimization for baseline, verified spread/commission/swap and controlled delay scenarios. Test at user-selected terminal lower bound instead of fabricating a $200 native report. Research-only isolated `RunNativeValidation.ps1` still has its prior hardcoded custom-symbol fixture/deposit presets and is **NOT** a replacement for the operator's ordinary WMMarkets GUI test; this plan did not silently change those fixtures.

For $3,000 reference equity, a research **0.25%** per-trade stop-risk is $7.50; **0.5%** is $15.00; 1.5% daily budget is $45.00 and a 4% peak-equity research pause is $120.00. These are candidate risk settings, *not* live EA defaults or guaranteed loss caps. Confirm actual risk on legal min/step volume with broker `OrderCalcProfit`, adverse stop slip, fees and current equity, not fixed pips. The WMMarkets paper preflight previously observed a 0.01 lot minimum and a contract size of 100 oz/lot, so 0.01 lot represents ~1 oz; a $4/oz stop would have ~$4 raw loss plus charges, but a truly structural stop may be much farther and must not be artificially narrowed to force a fill.

## 2. Crucial source finding: default entry is at the FORMER STOP

The current default `PreparePullbackLimit` in `mt5_robot/QTS_Gold_Robot.mq5` (lines ~635–711) calculates the past 5–30 completed-bar extrema and puts the BUY LIMIT at the old hypothesized long SL **below** the closed-bar structural low, with the new stop even lower (symmetrical SELL LIMIT above the structural high). It does NOT require a subsequent accepted reclaim/CHoCH/BOS. This creates a possible adverse-selection failure: fills happen when the hypothesized support has actually broken, catching the continuation of the move. The `QTS_RETEST_LIMIT` alternative is a near-market retrace but also does not prove post-breakout acceptance. That is a **mechanism-based concern**, not a measured statistical attribution of every loss.

`ReadSignal` (around lines 460–536) uses EMA fast/slow, closed-bar EMA reclaim, ADX threshold, optional H1 MA filter. These do not tell us whether a price **below a violated swing low** has recovered structure at the *pending fill time*. Data from M15 2025 older native test: **136 accepted LIMIT**, **18 completed fills**, **13.2% fill rate**, **-$5.54 reported native net**, **PF 0.98** over six months on a **$10,000 tester account**. Extra modeled costs increase the loss. An accepted order is NOT a completed trade. Source: `docs/PERFORMANCE_REPORT.md`. No comparable net report yet exists for the latest EA revision that the operator has now compiled.

## 3. Do not infer stop-hunting or a wider stop from a chart

For an OTC/CFD non-exchange XAUUSD symbol, SL triggers from executable **Bid or Ask**. A short's SL can be touched by **Ask** when the Bid candle chart appears not to touch. A temporary spread expansion, price gap, liquidity sweep, badly timed entry, actual continuation or an unrealistically tight stop can all yield a stop then rebound. Broker stops are not loss ceilings; spreads and slippage may cause worse fills. See official MT5 docs:
- https://www.metatrader5.com/en/terminal/help/algotrading/testing_features
- https://www.metatrader5.com/en/terminal/help/algotrading/tick_generation

Distinguish these independent mechanisms:
- **Entry adverse selection:** price penetrates prior swing, the LIMIT buys the continuation before any close reclaims the broken level.
- **Stop mismatch:** trade's structural invalidation is farther than SL; price wicks and later returns. Changing SL distance also changes risk, lot size, hit probability and expectancy.
- **Ask/Bid spread:** stop triggered by an executable quote not visible on a one-sided chart.
- **Regime:** unfiltered high-volatility or strong-trend periods generate misleading mean-reversion attempts.
- **Execution:** slippage, gaps, incorrect quote timestamp/assumed commission.

## 4. What the historical strategy research proved (and did not)

A fixed previous-day liquidity sweep hypothesis earned **+$148.56, PF 1.25, on 74 development trades**. When replicated on a separate following July–December 2025 period, it LOST **-$324.83 on 60 trades**, PF **0.47**; the original family was rejected. This is concrete evidence **against asserting that 'sweep then reversal' has a positive edge just because it looks attractive on past charts**. Many other families, including trend pullback, opening range, exhaustion reversion, quote burst, were negative after modeled costs. Read `gold_robot/docs/PERFORMANCE_REPORT.md`.

## 5. An operator-grade research plan (NOT an active signal)

**Keep the EXISTING QTS execution, risk and order ledger. Do not replace the compiled EA with an unproven multi-indicator novelty.** Compare causally different hypotheses, all fully frozen before new data:

- **A — Default former-SL LIMIT:** unchanged control/baseline, M15, same bid/ask execution.
- **B — Break + ACCEPT + retest:** H1 directional regime from last completed H1 bar; M15 completed bar closes beyond a previously established swing; a later **completed** M5/M15 bar retests and holds the level, with a genuine confirmation at next executable quote. Stop beyond structural invalidation plus a frozen volatility/spread buffer. No orders placed on mere first touch. A breakout in the opening range was *previously rejected* and cannot be relabeled as this new experiment.
- **C — Liquidity sweep + reclaim:** price trades through a prior confirmed liquidity level, THEN a completed bar closes back within the range and another non-future signal confirms acceptance; trade follows the reclaim, not the stop-hit tick. **Historical prior-day sweep replication failed**, so this remains explicitly high-risk/exploratory, not presumed profitable.
- **D — OTT/QQE-MOD:** separately log **confirmed bar-close** OTT trend flips and QQE momentum; use only as control/optional non-causal signal hypotheses, not hidden ensemble overfitting. UT Bot and Supertrend share an ATR-flip mechanism; four correlated arrows do not equal four independent pieces of evidence.

Use an ATR-derived **volatility estimate** and actual Bid/Ask spread for contextual risk bounds; **never** use ATR multiple alone to declare price structure invalid, move stops further after opening, or force risk above budget. One gold position total. Cancel pending orders on loss of causal setup. Fixed SL/TP attached server-side; hard portfolio pause, restart-reconciliation, no grid/martingale, no averaging down, no forced trades. New exits (time stop / trailing / break-even) require their own frozen head-to-head trial; no cherry-picking winners.

## 6. Stop-path diagnosis with new standalone code

`gold_robot/research/stop_reversal_audit.py` is **read-only** and processes an operator-exported normalized STOP-exit ledger and timestamped executable Bid/Ask ticks. It computes: among **quote-covered** stops, fraction of prior **entry price** reclaims at 5/15/30/60/120 minutes and max favorable/adverse movement after stop in units of the **initial R**. It treats missing quotes as UNKNOWN; no trading API. Synthetic unit tests verify no future leak into earlier windows, proper SELL Ask handling and missing coverage.

CSV trade format: `trade_id,side,entry_time_ms,exit_time_ms,entry_price,initial_stop_price,exit_price,exit_reason`. `exit_reason=SL` for stop exits. Tick format: `time_ms,bid,ask`, chronological UTC milliseconds. The script requires actual matched broker time bases and sufficient quote history; neither the current preflight CSV nor a chart screenshot contains these events. Run:

```text
python gold_robot/research/stop_reversal_audit.py --stops path/to/stops.csv --ticks path/to/ticks.csv --output path/to/stop_audit.json
```

Do not upload private account IDs, login, keys or passwords; use anonymous trade IDs. This script **cannot** establish whether widening stops would have made money: counterfactual size, delayed entries, other signals, realized costs and portfolio path all change. New native MT5 tester exports or verified broker fills **must be collected before reporting an actual reversal fraction**.

## 7. Promotion gate and personal daily operations

A professional owner measures **opportunity and execution quality**, not merely number of BUY/SELL arrows.

- Daily automated self-check: symbol, price freshness, server timezone, volatility regime, spread distribution, terminal uptime, EA hash, outstanding pending/positions/deals, persistent halt and reconciliation.
- Each signal: pre-record strategy ID, known closed bars, trend/structure evidence, entry level, stop/invalidation, actual executable bid/ask and effective risk/lots; log the exact reason for every rejected signal.
- After each trade: entry/exit receipts, commissions/swap, stop reason, whether intended SL or execution issue, post-stop quote path (when data available), actual R and slippage, correlated exposure.
- Weekly review: negative after-cost expectancy, stop/reversal fraction, median MAE/MFE *before stop*, fill ratio, opportunity cost of skipped signals and 1.5% daily stop incidence. Freeze versions and counterfactual hypotheses.
- Promotion only with pristine, independent **future** WMMarkets XAUUSD@ bid/ask ticks, adequate trade count, matched execution, stressed costs, drawdown survivability, first on tester then explicit supervised DEMO-forward testing. No LIVE enablement from an indicator or profit screenshot.

**As of 2026-10-26:** The original EA compiled successfully on the user's WMMarkets PC. This new work is an independent diagnosis tool plus documented experiment design. The canonical EA installed on Windows has NOT been changed; no new broker test report or positive after-cost edge has been generated. Keep LIVE locked.
