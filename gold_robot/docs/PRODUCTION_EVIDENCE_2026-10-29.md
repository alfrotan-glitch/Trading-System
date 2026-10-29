# QTS Gold — Production Engineering and Strategy Evidence Gate

Date: 2026-10-29. Scope: WMMarkets MT5, XAUUSD@, native M15 real-tick research.

## Release verdict

**ENGINEERING: TESTER-READY. STRATEGY EDGE: UNVALIDATED. REAL MONEY: LOCKED.**

A clean native MetaEditor compile and broker preflight establish installation and broker compatibility, not profitable execution. No production authorization follows from this document.

## Independent evidence from user-supplied tester agent logs

Three files were agent logs, not native HTML reports. One file named `QTS_0.htm` actually began an incomplete EntryStyle 2 test; other files contained multiple sessions, aborted tests and an exact duplicate run.

The unique completed 2026-01-01 to 2026-02-05 sessions with WMMarkets real ticks, XAUUSD@, M15 and a modeled USD 3,000 tester deposit showed:

| Style | Closed exit deals | Wins/losses | Logged deal net USD | Illustrative result after an additional USD 10/round-turn lot |
|---|---:|---:|---:|---:|
| 1 Retest | 15 | 6 / 9 | -30.27 | -32.57 |
| 2 Break/Retest | 10 | 6 / 4 | +20.52 | +17.02 |
| 3 Sweep/Reclaim | 9 | 5 / 4 | +4.12 | +1.92 |

Style 0 was interrupted and dominated by two exceptionally large winners. None of these samples demonstrates robust positive expectancy; the reported MT5 commission, swap and fees were zero and real execution costs were not independently measured. Cost adjustments above are **scenario stress**, not observed charges.

The user-supplied log audit is read-only. The repository script `gold_robot/research/audit_mt5_logs.py` independently identifies session boundaries, exact duplicate runs, completion markers, entry style, deal P&L and assumed-cost stress. It does not assign a profitable-edge verdict.

## Source-level concerns confirmed

1. **Report identity:** A file named `QTS_0.htm` must not be accepted as Style 0 when its HTML inputs say EntryStyle 2. The comparator now rejects mismatched labels and identifies missing strategy metadata as unverified.
2. **Actual versus assumed costs:** `AssumedRoundTurnFeePerLot` is used by the entry permission check, not necessarily charged by the native MT5 report. Never treat zero logged commission as a verified WMMarkets zero-fee schedule.
3. **Non-equivalent exit models:** Style 0 uses an earlier swing extreme as target and `RewardToRisk` as a minimum; Styles 1–3 target approximately the specified R multiple. They are not four equivalent fixed 1:1 scalp models.
4. **Signal sparsity:** Closed-bar structural validation and H1 trend gating reject many M15 candidates. Rejected signals are not automatically missed profitable trades. Changing filters based on this sample would create selection bias.
5. **A changed source is not a freshly compiled EA:** Windows source integrity, MetaEditor compilation, real-tick data and account-side quote/ticket checks must be independently verified on the user terminal.

## Controlled research plan; no tuning on outcome data

Freeze a canonical source commit and the four existing presets. Retain one identical WMMarkets symbol, M15, real-tick quality model, deposit, timeframe, trade costs, start/end dates and broker-side trading sessions across styles. Start with the previously analyzed January–February period solely as historical diagnostics. Evaluate subsequent previously unseen months independently, without altering parameters after viewing their returns. Repeat on another separate period and M5 as a different predeclared experiment, not merged with M15 data.

Predeclare experiment hypotheses: baseline former-stop, shallow retest, structural break and retest, and sweep reclaim. Use the initial four opportunity-census presets only for candidate discovery; then repeat every surviving candidate with the `safety_on` presets (`TesterIgnoreDailyAndPeakStops=false`) before making any performance or operational claims. Record every attempted setup, accepted pending, fill, expiration, stop, take profit, gross/net proceeds, commission, adverse slippage, profit factor, maximal **equity** drawdown and duplicate-run fingerprint. Include outliers rather than removing losses; use time-based rather than random trade splits.

Stop considering a candidate if its fee-stressed expectancy is negative, its equity drawdown exceeds policy, or its positive return depends on a small number of extraordinary wins. Do not select the best among many variants on one historical window without correcting for multiple testing. Academic discussion: Bailey et al., *The Probability of Backtest Overfitting* (2017), https://escholarship.org/uc/item/4w1110bb.

## Mandatory release gates

- [x] Repository CI, Windows launcher smoke and read-only broker preflight workflows have been exercised on the current tester tooling; latest commit checks are authoritative.
- [x] Agent logs are not counted as HTML results; mismatched/missing style identity is rejected or marked unverified.
- [ ] All four *completed native* MT5 HTML reports, unmodified and style verified, with matching symbol, dates, timeframe and model.
- [ ] Native broker charge, swap, spread and slippage audit; cost stress reconciled to broker statement.
- [ ] Stable positive **after-cost** results on independent unseen real-tick months, with enough trades for statistical review.
- [ ] Equity drawdown, long losing streak, restart, disconnect, pending expiry and ticket reconciliation inspected in the actual WMMarkets DEMO terminal.
- [ ] Separate low-capital feasibility check at USD 100–200 with actual minimum lot, stop distance, margin and risk ceiling.
- [ ] Formal live permission decision after all evidence; default remains **NO-GO**.

## Local usage

Copy `QTS_*.htm` and `QTS_*.log` into `gold_robot/reports_local/native`. Genuine HTML results are compared via `START_HERE.bat` option 6. If Python 3 is installed, choose `START_HERE.bat` option 8 (or run `gold_robot/AUDIT_LOGS.bat`), which searches the native-report folder, Downloads, Desktop and Documents for QTS agent logs by file contents, not filename. On Windows, a file picker is offered if nothing is found. It opens a local HTML audit and also writes `QTS_Agent_Log_Audit.json`; a no-match scan is explicitly labeled `NO_AGENT_LOGS_FOUND`, not an execution failure. Neither is a production release certificate.

Never rename agent logs into HTML results, and never expose passwords or terminal account keys in Git.
