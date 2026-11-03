# QTS Gold | Independent Style 7 Native Evidence Audit — 2026-11-03

**RESEARCH ONLY — LIVE LOCKED — NO VALIDATED PROFITABLE EDGE**

## Evidence identity

A supplied private original ZIP was independently inspected and audited offline (source ZIP SHA-256: `88e9f2d3e20dce58e916aa8d0bc4ee34c3849d626a7eb308e69e240de4fa2656`). Archive integrity was clean. MT5 settings in the source report explicitly show: XAUUSD@, M15, real ticks, 2025-01-01 to exclusive 2026-11-03, Style 7 / TesterDualStrategyMode 2, RiskPerTradePct 0.50, RewardToRisk 1.0, TesterIgnoreDailyAndPeakStops false, BrokerStartHour 6, BrokerEndHour 22, MaxPositionMinutes 180.

## Reconstruction result

- **344/344 original broker Deal records** match 344 native MT5 HTML Deal rows (ticket, side, direction, price, lot volume, order ID, commission, swap, profit and time).
- **172/172 complete positions** reconstructed from the original deal CSV and independently matched to the packaged position forensic JSON. No duplicate/missing deal ID was found.
- **172/172 opening limit orders** matched against the native MT5 order table; 452 pending limit orders total: 172 filled, 249 canceled, 31 expired. Canceled/expired signals were NOT converted to simulated profits.
- Native net **+$98.45** equals +$1,042.46 winning P/L less $944.01 losing P/L; 89 winners, 83 losers, profit factor 1.104289 (native displayed 1.10), recorded deal charges $0.00.
- Reconstructed balance drawdown **$200.94** matches native report; native equity drawdown **$209.37** remains tick-path-unverified.
- Retest BUY / S1: 94 positions, +$95.92; Sweep SELL / S3: 78 positions, +$2.53.
- Calendar 2025: -$110.27; calendar 2026 to October: +$208.72. **October 2026 alone +$139.47**; all other months combined **-$41.02**.
- Limit fills all occurred at or better than original limit price in this native tester export (not generalizable to live).

## Serious execution anomalies

Position **557** (2026-09-04, Retest BUY, 0.01 lots): original stop 4462.40, exit 4438.03, adverse stop displacement 24.37 price units, recorded loss **-$32.22** against initial price-risk equivalent ~$7.85 assuming the 100 oz/lot factor implied by deal P/L (**approximately -4.10 R**). Position **517** (2026-07-17, Sweep SELL) has adverse displacement 3.71, **-$22.92** realized (approximately -1.94 R). No broker tick path or journal was included to establish root cause or post-stop counterfactual.

Among 172 positions: 79 SL exits, 88 TP exits, 5 EA/Expert exits. 63 stops had adverse displacement vs the exit-time stop. The nominal implied lot-risk factor is not independently broker-certified.

## Costs and statistical limitations

- All 344 tester Deal rows record commission/swap/fee as zero. Actual WMMarkets terms were not independently verified.
- A hypothetical extra roundtrip cost of $20 per lot across **5.02 traded entry lots** would change +$98.45 to **-$1.95**, ignoring any additional independent effects. Price-spread already included in the native fills must not be added a second time.
- A descriptive bootstrap of 22 active trading-month clusters produces an approximate 95% interval for mean trade P/L of **-$1.13 to +$2.49**; this is not an out-of-sample or preregistered edge test.

## Unresolved source-summary and coverage issues

The original packaged `QTS_2025_TO_DATE_SUMMARY.json` says `HISTORICAL_EVIDENCE_INVALID_NO_GO` because of a preperiod signal. The opportunity CSV has exactly two **NO_SIGNAL** rows for one paired warmup bar on **2024-12-31 20:45**; 86,626 opportunity rows total, 43,313 paired timestamps including warmup. Current `summarize_2025_history.py` explicitly handles this warmup pair, but the original saved invalid summary must be **preserved and re-generated**, not silently overwritten.

The last native opportunity bar is **2026-10-30 22:30**, despite requested exclusive 2026-11-03 end. Verify November 2 tick history before claiming complete coverage to end-of-window. Source/EX5/terminal hashes in metadata were not attested against the actual binary bytes in this ZIP.

**Remaining tasks before closing the full evidence chain:** regenerate dated original summary from current code; verify signed symbol contract and fee terms, missing journal and tick data around extreme stop incidents, full order modifications, equity path and binary/.set preregistration materials. No hidden order execution or live unlock.

**Independent adversarial checks:** 4 of 4 deliberately corrupted samples were rejected: altered forensic profit, duplicate deal ID, altered tester total and forged prestart signal. The unmodified data reconciled. The audit logic is read-only; no broker orders or strategy changes.

**Decision:** historical accounting is reconciled; an independent after-cost trading edge is **NOT** demonstrated. Continue **LIVE LOCKED**.
