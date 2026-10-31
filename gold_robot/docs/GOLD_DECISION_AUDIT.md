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
