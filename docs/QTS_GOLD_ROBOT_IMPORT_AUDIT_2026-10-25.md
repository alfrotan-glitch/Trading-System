# QTS Gold Robot local-source audit (2026-10-25)

## Import status

A 29-file source export of the newer Windows QTS Gold Robot was provided and reviewed outside this GitHub repository. The **code has not yet been pushed to this repository**. The intended destination is `gold_robot/` on `main`, separate from the existing QTS Python application.

## Confirmed source findings

- Canonical EA source: `mt5_robot/QTS_Gold_Robot.mq5`; companion execution receipt policy: `mt5_robot/ExecutionPolicy.mqh`.
- The uploaded 29-file subset initially passed 46 tests and failed 3 because `README.txt`, `docs/RELEASE_STATUS.json`, and `docs/SOURCE_CHECKSUMS.json` were not exported; native compiler evidence was also excluded.
- The EA treats broker retcode 10009 with an order ticket as a pending-order acceptance, not a completed fill.
- Non-tester DEMO entries are disabled by the strategy evidence gate, and REAL accounts are blocked.
- Historical six-month report claims 136 accepted pending LIMITs, 18 completed fills (13.2%), a $10,000 tester balance, -$5.54 native net and a 0.98 profit factor. These numbers have not been independently reproduced from this source-only export.
- At least 15 research families were rejected or failed independent confirmation. There is no confirmed positive after-cost edge.
- As uploaded, the default trade risk was 0.25% and parameter validation capped it at 1.0%; a fixed minimum R:R filter of 1.7 does not imply a nearby or high-probability TP.
- A DEMO account login literal appeared in a native-validation script. This must be removed before any PUBLIC code import.

## Prepared corrections (pending publication)

A reviewed, sanitized import package was created outside GitHub. It restores required package metadata without claiming unverified current-build compilation; replaces the hard-coded DEMO login with an optional local parameter; expands **tester-only** risk input validation to 2.0% while retaining the 0.25% default; adds a source-local ignore file and audit notes. The source regression suite passed 50 tests, which is **not equivalent** to a native MetaEditor compile or a profitability validation.

## Before live use

1. Publish reviewed source to `gold_robot/` on main only after matching SHA-256 checks and confirming there are no secrets.
2. Recompile in local MetaEditor, then run native real-tick tests with actual $100/$200 simulated deposits and broker-correct margin/volume/cost assumptions.
3. Compare entry/SL/TP candidates under executable bid/ask, independent data, and after-cost net expectancy; avoid assuming near-100% TP reach.
4. Validate connected DEMO restart, pending-order, partial-close, and disconnect recovery.

**Release decision: NOT RELEASED / no proven edge / real-money locked.**
