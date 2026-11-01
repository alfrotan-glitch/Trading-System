# QTS Gold: per-opportunity research decision gate (2026-10-31)

**State: research-only; LIVE LOCKED; no validated economic edge.**
The new `research/gold_decision_audit.py` does not call MT5 or place, change, or cancel orders. It consumes an independently captured snapshot and returns a fully explainable research assessment for *every* proposed setup, including rejected ones. The only positive status is `RESEARCH_PROPOSAL_ONLY`, never permission to trade.

## Research basis and prioritization

- Multi-month time-series momentum is documented across diversified liquid futures, **not** proof that an M1/M5 XAUUSD CFD scalp works: Moskowitz, Ooi, Pedersen (JFE, 2012), https://www.sciencedirect.com/science/article/pii/S0304405X11002613
- Direct intraday gold papers report parameter sensitivity and conflicting out-of-sample findings. Batten et al. (2018): https://www.sciencedirect.com/science/article/pii/S1042443117301087 ; intraday China gold paper (2022): https://www.sciencedirect.com/science/article/pii/S1042443121001876
- Gold responds to risk, momentum, economic conditions and opportunity cost (including dollar/yields); those are potential research covariates, not unmeasured broker-data inputs: WGC 2026 https://www.gold.org/goldhub/research/gold-mid-year-outlook-2026
- Gold futures microstructure differs across geographic sessions; source: https://www.sciencedirect.com/science/article/pii/S2405851318300102
- London gold auctions begin at 10:30 and 15:00 London local time (LBMA): https://www.lbma.org.uk/prices-and-data/about-lbma-daily-auction-prices
- COMEX gold futures trade almost 24 hours with a daily maintenance break; the CFD broker's XAUUSD@ hours and contract rules **must be checked independently**: https://www.cmegroup.com/markets/metals/precious/gold.html

Investigate five explicitly defined **candidate families**: TREND_PULLBACK, BREAK_RETEST, MOMENTUM_CONTINUATION, SWEEP_RECLAIM, RANGE_REJECTION. These are not ranked by proven profitability. Every family requires an externally verified closed-bar setup, not an inferred signal manufactured from a profitable trade after the fact.

## Decision contract (frozen engineering starting point)

1. **Clock**: all fields are timezone-aware ISO-8601 timestamps. Convert to Europe/London and America/New_York with IANA DST rules. Research windows: 08:00–11:00 London time; 08:00–12:00 New York time; label the actual overlap. These windows are hypotheses, not asserted profitable sessions.
2. **Multi-timeframe context**: EMA fast/slow trend on H1, ADX plus EMA-distance/ATR on M15, last closed-bar relationship to the M5 EMA. H1 <= 2h, M15 <= 30min, M5 <= 10min old. Reject stale or future bars.
3. **Events**: verified, fresh, complete *external* USD/GLOBAL high-impact calendar; 30 minutes before and 15 minutes after a high-impact event: reject. Missing/stale calendar: reject. Do not invent news event timestamps. For official NFP/CPI calendars use https://www.bls.gov/schedule/news_release/empSit.htm and https://www.bls.gov/schedule/news_release/cpi.htm; include Fed announcements separately.
4. **Execution**: real broker symbol, contract size, min/step/max lots, margin per lot, free margin, bid/ask at an observed quote time, round-trip fees and adverse-slippage stress. Quote must be within 5 seconds. Missing commission or margin estimates are *not* zero by default.
5. **Risk**: cap research proposal at 0.5% of equity and 20% of free margin, max 3% day and 8% peak equity drawdown, minimum after-cost reward/risk of 1.25. These are *candidate policies for study*, not fitted optimal parameters or approved real-money controls. A $100–$200 account often cannot trade a broker minimum 0.01 lot within those limits.
6. **Strategy routing**: trend candidates can pass only with matching H1 bias and M5 close; range candidates only in the range regime; transition and volatility spikes abstain. Rank only passing candidates using a frozen heuristic. The score is **not** a probability of TP or a signal of expected positive net P&L.
7. **Immutability**: return a reason for every veto, and never write to live EA inputs, change risk rules, send `order_send`, or authorize real account trading.

The snapshot is an input contract: no production MT5 exporter currently supplies all fields. **Until a broker-specific, clock-verified, event-integrated source is implemented, this module is a deterministic offline research auditor rather than an operational trade selector.**

## Run an independent audit

From the repository root, after a trusted snapshot has been produced:

```powershell
python gold_robot/research/gold_decision_audit.py --input path\to\verified_snapshot.json --output gold_robot\reports_local\gold_decisions\assessment.json
```

The output includes `session`, `regime`, `h1_bias`, `decision`, `selected_candidate_id`, and `candidate_audit` for every rejected and accepted proposal. Missing features cause `NO_TRADE`, not permissive defaults. Save all as-of feature timestamps and the native source hashes alongside the report.

### Nonnegotiable validation before any EA integration

- Independently capture broker quotes and real-tick execution with contract/commission and spread, avoid mixing COMEX futures and WMMarkets CFD rules.
- Time-based walk-forward and untouched forward evaluation across more than one market regime; purge overlapping events. Correct for multiple tested strategies and selection effects.
- Compare against a baseline, session-matched random entry, and cost-only models; report net expectancy, downside, position sizing, max drawdown and uncertainty.
- Diagnose stop->reversal->TP on **post-exit bid/ask tick paths** with a verified clock and uninterrupted tick coverage. Native deals alone cannot prove what happened after the stop.
- Require independent risk, broker integration and native Windows acceptance before any real trading authority; profitable training scores are not enough.

**No guarantee of profits, no claim this is a best-performing strategy and no connected trading permission.**


## Native M15 Adaptive Market-Context V3 hypothesis

The existing EntryStyle 7 adaptive router is NOT retrospectively replaced. A new separately preregistered flag `TesterUseMarketContextV3=false` preserves the original behaviour by default. Only `MQL_TESTER`, EntryStyle 7 and M15 can activate it. The gate executes in `EvaluateNewEntry` **after** the adaptive router chooses and prepares an actual LIMIT candidate but **before** `OrderCheck` or `OrderSend`.

V3 evaluates **every prepared, risk-sizeable adaptive candidate before priority ranking**, so a rejected first candidate cannot prevent the router from considering a different setup. It rechecks the chosen candidate immediately before broker preflight. V3 uses `CopyRates(..., shift=1)` from 18 M15 bars, two M5 bars and one H1 bar, plus only closed H1 EMA50/M15 EMA20 buffers. It checks continuity, chronological causal alignment, the previous M15 swing zone, a closed M5 directional candle and the H1 trend for trend-family entries. For range entries it checks a previously observed M15 boundary; sweep setups must have pierced then reclaimed the prior edge. It vetoes insufficient stop room, bad directional stop geometry, spread-heavy signals and broker-quoted after-fee reward/risk below 1.25, using the same `EstimatedMonetaryLoss` slippage/fee stress function as the canonical EA. Each veto has a specific Experts-log reason; the same signal cannot bypass this gate on the way to the broker.

V3 has **no verified real-time economic-event calendar or DST-aligned trading-session gate inside MQL5**. The offline `gold_decision_audit.py` does implement these gates when trusted timestamped market/news snapshots are supplied. The native V3 is therefore a *partial, explicitly labelled technical-context hypothesis* for isolated native testing; it is not the same as the full offline audit.

A Windows operator may compare baseline versus V3 on the **same untouched MT5 history and real-tick model**, in separate output folders:

```powershell
# Both commands are TESTER ONLY; connected live orders stay blocked.
.\gold_robot\research\RunAutomaticTester.ps1 -OnlyStyles '7' -ResearchVariant BASELINE -FromDate '2026.04.01' -ToDate '2026.10.01' -NoOpen
.\gold_robot\research\RunAutomaticTester.ps1 -OnlyStyles '7' -ResearchVariant CONTEXT_V3 -FromDate '2026.04.01' -ToDate '2026.10.01' -NoOpen
```

This historical April-October 2026 window is **exploratory and already examined in earlier research**. It is not fresh holdout evidence. Do NOT choose V3 merely because it looks better than baseline there. A truly new completed month, native replay after observed broker costs, chronological walk-forward, and independent prospective validation are required. The V3 policy is fixed before evaluating new periods; modifying these thresholds restarts the prospective clock.

**Native MT5 MetaEditor compilation and WMMarkets terminal integration are not proved by GitHub Python/static tests.** Compile with the actual compiler and verify its exit code and diagnostics on Windows before relying on Strategy Tester results.
