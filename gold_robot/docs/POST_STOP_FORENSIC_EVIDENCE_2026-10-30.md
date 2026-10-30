# QTS Gold — Eight-style native forensic audit and post-SL replay handoff
Date: 2026-10-30. Scope: the user-provided \`QTS_SHARE_RESULTS(2).zip\` from the
WMMarkets XAUUSD@ M15 simulated native tests, 2026-04-01 through 2026-10-01.
No files with broker account credentials, native HTML or journal are stored here.
These summary figures are *descriptive observations*, not an alpha claim.
The authoritative raw CSV/JSON remain in the operator's private reports_local.

## Reconciled evidence (not a combined account return)

The 8 individual native tests have **938 completed positions** in total:
503 SL exits, 427 TP exits, 8 other exits, total arithmetic net -$549.87
**across separate simulations**. Do not treat that sum as a single tradable
portfolio or infer which style would have traded instead of another.
All 938 position aggregates are marked COMPLETE; that concerns deal joins
only, not quote history before/after the trades. No post-stop bid/ask tick
paths were included in the evidence ZIP.

| Style | Positions | SL | SL within 5 min | SL adverse slip >$0.10 XAU price units | Native net USD |
|---|---:|---:|---:|---:|---:|
| 0 former-stop | 18 | 17 | 6 | 10 | -65.16 |
| 1 retest | 68 | 32 | 8 | 12 | +39.92 |
| 2 break/retest | 41 | 22 | 14 | 9 | -26.05 |
| 3 sweep/reclaim | 54 | 26 | 13 | 9 | +45.20 |
| 4 trend impulse | 80 | 50 | 13 | 16 | -226.75 |
| 5 range rejection | 194 | 103 | 55 | 47 | -81.11 |
| 6 inside breakout | 64 | 37 | 3 | 15 | -134.05 |
| 7 adaptive | 419 | 216 | 52 | 81 | -101.87 |

The spread is already reflected in executable prices if broker bid/ask quotes
were correctly modeled. Broker commission/fee fields are almost entirely zero:
**cost realism is NOT independently verified**.

Within the 419 adaptive positions, selection was concentrated in
**Trend Impulse 303 positions, net -$158.46**, while Retest contributed
43 / +$53.18, Sweep 17 / +$14.72, Range Rejection 28 / +$45.49,
Break/Retest 17 / -$34.94 and Inside Breakout 11 / -$21.86. The inference
"disable Trend Impulse => +$56.59" is invalid as a forward backtest:
position availability, equity-dependent sizing and risk stops would change.
Strategy 7 stopped recording exits on August 5 despite a September end date;
whether a persistent risk halt, broker history or signal veto caused that
requires the missing *native Tester Journal*, not speculation.

## Reproducible individual incident examples

- Style 1, position 155, BUY: entry 4470.25, initial SL 4462.40,
  original TP 4478.12, actual SL execution 4438.03. Adverse
  stop slippage **24.37 XAU price units**, realized -$32.22.
- Style 3 position 128 and Style 7 position 915 represent *separate*
  simulation occurrences with identical native entry 4003.08 SELL,
  SL 4007.01, TP 3999.06 and SL execution 4010.72,
  slippage 3.71 price units, -$22.92 each. These should **not** be
  counted as two independent broker-live experiences.
- Style 5 position 297 SELL: entry 4038.96, SL 4041.36,
  TP 4036.16, SL execution 4043.51, slippage 2.15, -$22.75.

No submitted file establishes *where the quote subsequently reversed*,
whether bid/ask later touched the **original TP**, or the first reversal
timestamp. Never label that outcome YES or NO without executable ticks.
The same initial TP can be quoted after SL, but such a retrospective
quote touch is **not** a tradable counterfactual.

## Included code: causal event study, not post-hoc SL optimization

- \`research/build_post_stop_inputs.py\` reads the complete private ZIP,
  requires eight style-identified reports and a reconciled trade ledger,
  joins raw entry/exit deals by (style, position_id), exports a stable
  \`QTS_STOP_CASES.csv\` for single-exit SL trades and explicitly excludes
  multi-exit/reversal cases rather than inventing one exit.
- \`research/stop_reversal_audit.py\` already performed no-lookahead,
  executable bid/ask recovery checks for 5,15,30,60,120-minute
  horizons. It now also measures **the first touch of the original TP
  after SL**, its elapsed minutes and the extreme executable quote
  price/time in each complete horizon. A missing quote window is UNKNOWN
  with a null fraction, not a negative observation.
- \`--tick-dir\` accepts the daily \`ticks_<epoch-day>.csv\` files generated
  by the existing *read-only* \`research/ExportBrokerData.mq5\`. These
  files carry a \`time_msc,bid,ask\` header, while a combined tick file
  may use \`time_ms,bid,ask\`. Timestamps must use the **same convention**
  as the MT5 deal times. Broker identity and executable tick accuracy
  must be checked by operator before treating an apparent TP touch as fact.
- \`QTS_POST_STOP_REVIEW.bat\` generates the stop input case files
  without rerunning MT5. With \`QTS_BROKER_TICKS_DIR\` set to an existing
  tick export, it performs the descriptive quote replay. No order
  submission, connected-account login, future data inference or
  profitable-edge approval exists in either script.

## Repo integrity, research scope and pending gates

- Canonical branch for delivery: \`main\`; multiple earlier arena,
  independent and research branches are present and **were not deleted**,
  since several contain unmerged, uncompiled 10-style experimental source.
  Do not silently merge old alternative rule sets and label the old
  six-month results as fresh evidence for those changes.
- An existing independent \`adaptive-repair\` branch documents a
  CopyBuffer index and cost-evaluator correctness repair **for its
  different hardened Style 7**, plus uncompiled SMC style 8 and
  M1 scalp style 9. Those are *not* the currently native-tested
  main Style 7. They require separate compile and preregistered trials
  before any integration.
- Last pre-audit main CI included a **fast-suite timing-sensitive**
  failure in \`tests/test_observation_attempt_journal.py\`:
  \`missed_slots == 1\` instead of 0. This is not proof that
  the MT5 EA lost trades; it requires a separately isolated deterministic
  repair. Windows installer and Gold research safety gates passed.
- Original April–September 2026 samples were viewed while designing
  the router; they **cannot** serve as untouched out-of-sample evaluation
  for revisions of that router. Any new selection rule, adaptive
  arbitration change, or fee/slippage parameter is a new research trial.
- **Remaining hard gates:** post-stop executable broker ticks (including
  continuity verification); contemporaneous decision logs and native
  Tester Journal for missing opportunities and August stoppage; measured
  spread/commission/slippage; 200 USD broker minimum lot and margin
  feasibility; independent later-window native trials; stable after-cost
  positive expectancy and bounded drawdown. All are still NO-GO.
- LIVE remains LOCKED. No profitable trading edge has been validated.
