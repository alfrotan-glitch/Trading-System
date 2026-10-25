# External live-trading EA evidence review — 2026-10-25

**Purpose:** use documented multi-year production/live experience from existing automated traders instead of inventing another unvalidated indicator combination.  
**Status:** evidence/reference only; NOT a trading-strategy promotion, not a code licence, not a buy recommendation, and not authorization for any order. QTS `NO_VALIDATED_EDGE`, DEMO research gates and `LIVE=LOCKED` are unchanged.

## Evidence hierarchy (strongest first)

1. Broker-linked account independently tracked, account type **real**, trading privileges verified, **equity** drawdown, full history available, >=24 months and broker execution costs explained.
2. MQL5 server-monitored live signal with many trades and multi-year history, account type established; still inspect other accounts from the same vendor.
3. Vendor's backtest across real broker ticks with downloadable report (not live proof).
4. GitHub public source with tests and maintenance (code-quality evidence, not profitability).
5. Advertisements, screenshots, self-selected testimonials and Reddit claims (hypothesis-generating only).

Two monitoring sites displaying the **same underlying account** count as one trading experiment, not independent replications.

## A — Gold Reaper MT5, Profalgo / Wim Schrynemakers — primary XAUUSD operational reference

- Official product: https://www.mql5.com/en/market/product/111357 — released 2024-02-01; v5.5 updated 2026-10-17; proprietary, $949 on 2026-10-25.
- MQL5 live signal: https://www.mql5.com/en/signals/2265877
- Corresponding Myfxbook record (same account, not a second replication): https://www.myfxbook.com/members/strueli/gold-reaper-v30/11320334
- Independent trade-history review, dated 2026-10-23: https://therobotictrader.com/gold-reaper-ea-review

**2026-10-23 fixed snapshot, one real-money account 2024-10-22 through 2026-10-22:** 905 XAUUSD trades, 71.71% wins, profit factor 2.09, net trading profit about $4,932.57, reported growth +326.06%, max relative balance drawdown 16.89%, MQL5 'by equity' relative drawdown 7.18% (different statistic; NOT a comparable peak-to-trough tick-equity DD), 99% algorithmic, average holding about four hours. October 2026 was down about 6.77% through Oct 22. Independent reviewer reconciled the exported 905 trades to the published net within $0.04. Accounts run under other settings had drawdowns of approximately 18.82%, 31.19% and 45.64%. No independent second broker/time-period strategy replication established; software versions changed during the record.

**Publicly disclosed operational design, not proprietary code:** multiple strategy variants for breakouts of important support/resistance, confirmations for false breakouts, server protective SL/TP, trailing exits, spread and Friday controls, account-level equity-based sizing and daily loss guard, pending-order handling, strategy-specific magic numbers. A developer claims no grid and no martingale; independent analysis found no systematic pattern of either in the main closed-trade record. Entry filters and parameter internals are **not public**.

**Hard lessons:**
- Multiple entries may share the same gold move; per-trade stop does NOT cap portfolio or daily losses. Independent audit observed up to 13 concurrent positions, a worst day around -6.49%, and a losing run larger than vendor backtest streak.
- Spread/gap on the first minutes after market reopen can turn pending orders into bad fills; some real user reviews specifically reported this.
- The best ten trading days accounted for 58.8% of reported profits: a rule mandating a trade or daily profit would destroy the selectivity.
- An EA's 'max DD' input is an *intent*, not a guaranteed loss ceiling; require simulation of crash/reconnect and gaps.
- Never use vendor's *other settings* record as if it validates the current version on WMMarkets XAUUSD@.
- Published product is proprietary. **Do not copy/reconstruct non-public implementation or redistribute the EA.** Free marketplace DEMO is for tester review under its terms; licensed purchase/rent needs owner decision.

## B — DARWIN EJL / Eliezer Hartmann — externally observed experienced systematic-trader reference (NOT proven to be an MT5 EA)

- Primary verified venue profile: https://www.darwinex.com/invest/EJL
- Author's public account of methods: https://www.reddit.com/r/algotrading/comments/1q25jpe/2025_was_my_best_year_and_heres_what_i_did/
- Darwinex profile view on 2026-10-25 exposed about 16,057 trades, mean holding 3h40, 65.49% win rate, about $1.94m investor AUM across 90 portfolios and EUR215k Darwinex allocations; DARWIN risk is adjusted by the venue. Do not conflate investor AUM with trading profit, or DARWIN risk-adjusted performance with the underlying account.
- Author attributes improvement to abandoning negative-R:R scalp/grid and using breakout entries with roughly 2:1 reward/risk and only XAUUSD/USDJPY in 2025. The author's +39% 2025 / 6.65% DD is self-report; the public static Darwinex page did not expose a machine-readable independent verification of those exact period figures in this review. Automation percentage and trading software source are unknown.
- Lesson: favor positive asymmetry, few instruments, enforce total exposure, and carefully measure **net** RR after costs; don't pretend 2:1 always means profitable.

## C — Waka Waka EA — warning from 8+ years of actual trading

- Publicly reviewed long real-money record, roughly 5,500 trades, PF ~1.70, max floating-equity drawdown ~72.4%, correlated AUD/NZD/CAD pairs and grid/averaging exposure; another account suffered >90% drawdown.
- Independent reference: https://therobotictrader.com/waka-waka-ea-review
- **Reject for QTS**: longevity or high win-rate without bounded tail loss is not acceptable. The system is not an XAUUSD comparator and it is not a reusable strategy endorsement.

## D — Other operational signals and open-source frameworks

- https://www.mql5.com/en/signals/2268766 — Soma PureGold Indexes and Oil; as observed Oct 2026, 7,150 trades, 99% algo, PF ~1.29, across multiple instruments. More trades do not imply a stronger gold-only edge. Inspect monthly concentration, deposits/withdrawals, and historical DD before making any inference.
- https://www.mql5.com/en/signals/2300694 — RAZOR EA; about 1,934 trades, 94% algo, PF ~1.98, ~2-day average holding period, mixed instruments and not suitable as direct short-horizon XAUUSD benchmark.
- https://github.com/EA31337/EA31337 — maintained multi-strategy MetaTrader framework. Its public source can inform architecture but has **no established proven live XAUUSD alpha**. GPL-3.0 obligations conflict with simply copying code into the current proprietary QTS licence. Study ideas, not copied code.
- https://github.com/koichi055/ema-gold-trader-ea — an openly inspectable EMA/DEMA gold EA with backtest claims, but no independently established live performance found in this review. NOT a production-alpha baseline.

## Transfer to QTS — reuse lessons, not a new standalone indicator EA

**Existing assets to KEEP (present already):** fail-closed real account gate; persistent drawdown and daily loss accounting; protective stops; broker bid/ask/spread checks; OrderCheck; pending order expiration; dedup/reconciliation; transaction audit; strategy and demo authority gates. Source: `gold_robot/mt5_robot/QTS_Gold_Robot.mq5` and `ExecutionPolicy.mqh`.

**Reference candidate only:** a *structural support/resistance breakout* with causal swing levels from completed bars, directional confirmation, a false-breakout exit, server-side stop and expiry, no averaging down, and portfolio-level gold exposure cap. This is a generic published strategy class, NOT Gold Reaper's nonpublic algorithm. It is NOT the same as the narrow first-minutes opening-range hypothesis already tested and lost in QTS.

**Do not promote using old data:** the repo's pre-existing XAUUSD opening-range breakout holdout was -2.98 net bps at 2-bps stress and EMA(12/48) holdout -2.52 bps at 2-bps stress. These are negative tests for their *own* fixed hypotheses, not a proof that every support/resistance breakout is unprofitable. See `docs/research/mt5_broker_opening_range_365d_20261023.md` and `docs/research/mt5_broker_ema_365d_20261023.md`.

### Adoption and validation gates

1. **External benchmark:** obtain a legally licensed/tester-only build of the official Gold Reaper if desired; run on the user's *exact* WMMarkets `XAUUSD@` real tick history and broker account specification in the MT5 Strategy Tester. Require same test horizon, commission, spread, swap, leverage and initial deposit as QTS. Replaying historical data known to this review is descriptive, not independent holdout.
2. **Freeze ex-ante hypothesis:** explicitly preregister a SMALL and auditable support/resistance breakout reference that uses only publicly described market principles, not Gold Reaper's private rules. Existing QTS research backtest and broker-causal execution engine must be reused; **no parallel shiny bot**.
3. **Measure trades not curves:** after-cost per-trade expectancy, PF, median R, equity high-watermark DD, recovery length, concentration by best days, slippage p50/p95, no fill/cancel reasons, source/rollover/timezone and hedging/netting behavior, portfolio exposure when many strategies signal together.
4. **Stress:** recompute under +spread, +commission, spread-gap events, 1–3 second delay, widened stops, missing ticks, price gaps, weekend reopen, and disconnections. Handle broker min-volume and margin. Hard daily and total equity guards must fail closed.
5. **Independent period:** use genuinely unseen later WMMarkets ticks plus DEMO-forward shadow observations. Lock parameters and audit all variants to avoid data mining.
6. **Decision:** only if a preregistered independent after-cost edge and operational gates pass may an owner consider DEMO-only order trials under existing QTS authority. LIVE stays structurally locked; no commercial EA licence permits overriding it.

## Important limitations

The external dashboards prove that **some** accounts have traded and booked gains; they do not establish the exact nonpublic causal strategy, execution suitability for WMMarkets, or performance reproducibility at the same settings. The independent reviewer of Gold Reaper evaluated the published history and selected tester settings, not an unseen future sample. Screenshots and Reddit anecdotes are not independent audits. This work changes documentation only; no MetaEditor compilation, local broker access, live orders or deployment was performed.

**Decision at 2026-10-25:** Gold Reaper is the highest-priority verified XAUUSD practical-reference product identified in this review; EJL is a public systematic-trader lesson; EA31337 is a code-architecture reference. No QTS trade authority, strategy registration or executable settings change is approved.
