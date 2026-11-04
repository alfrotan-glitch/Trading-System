# QTS Gold | Deep review — 2026-11-04 (Linux screening only, NOT a Windows test)

**RESEARCH ONLY — LIVE LOCKED — NO VALIDATED PROFITABLE EDGE — NO STRATEGY CHANGE IN THIS BRANCH**

## What Muse actually did, and did not do

- Muse's computer is a Linux (Ubuntu 24.04) VM. It has **no Wine, no MetaEditor and no MT5 terminal**.
  No Windows test, no MetaEditor compilation and no Strategy Tester run was performed by Muse
  in this review, and none is claimed here. Any claim of a Windows result must come from
  a run on the owner's Windows PC, with its own native logs.
- Remote `main` checked: `0f84b0a` ("audit: document verified historical tail truncation
  and fail-closed correction", 2026-11-03). Compared with the 2026-11-03 review head
  `9301a65`, the only changes are docs, research scripts and tests. **No `.mq5`/`.mqh`
  file changed**, so the EA under review is identical to the one behind the 172-trade
  Style 7 evidence.
- Linux screening run on `0f84b0a`, before this branch: **564 passed, 2 failed**.
  After the two stale-test fixes in this branch: **566 passed, 0 failed**
  (`python -m pytest gold_robot/tests -q -o addopts=''`, Python 3.12, Linux).
  Linux Python tests are screening only; they do not compile MQL5 and do not prove
  broker execution.

## The two fixes in this branch (tests only, no strategy, no risk, no demo flag)

1. `gold_robot/tests/test_robot.py` — `test_installer_dependency_set_matches_ea_includes`:
   the expected include set now includes `DualOpportunityLedger.mqh`. The installer
   already deployed that file; only the test expectation was stale. The EA is unchanged.
2. `gold_robot/tests/test_dual_opportunity_crosscheck.py` —
   `test_market_mismatch_fails_closed`: the expected error text now matches the
   current fail-closed message in `verify_dual_opportunity.py`
   ("conflicting native market observations"). The behaviour is unchanged:
   a market mismatch still raises `LedgerError` and fails closed.
3. `gold_robot/docs/SOURCE_CHECKSUMS.json`: only the two changed test files'
   byte counts and SHA-256 rows were updated, by hand, preserving every other row.
   `update_manifest.py --check` passes (179 files).

## Final verdict carried forward, unchanged

- Style 7 Dual Mode 2, WMMarkets XAUUSD@ M15, real ticks, 2025-01-01 to 2026-11-03,
  $3,000, safety_on: **172 trades, +$98.45 BEFORE commission/swap (charges $0),
  profit factor 1.10, win 51.7%, mean +$0.57/trade, max drawdown $200.94**.
  At $10/lot per side round-trip the result is about **-$2**; break-even is
  $9.81/lot per side. October 2026 alone is +$139.47; without it the total is -$41.02.
  S1 (BUY only) +$95.92, S3 (SELL only) +$2.53 — no proven regime-selection value
  for the Dual router over S1 alone. Worst trade (position 557) slipped $24.37
  beyond its stop, losing -$32.22 against ~$7.85 planned risk.
- **Tail coverage is NO-GO, not complete:** the regenerated 2026-11-03 history
  summary reports `HISTORICAL_MARKET_DATA_COVERAGE_NO_GO`, last observed bar
  2026-10-30 22:30, trailing weekday without closed bars `2026-11-02`.
  Do not claim coverage to 2026-11-03 until that Monday session is verified
  (or a documented broker closure is established).
- **Unseen-test protocol §9 is still blank in the local protocol file**
  (`workspace/goals/trading-system-adaptive-xauusd-robot/files/UNSEEN_TEST_PROTOCOL_STYLE7_20261103.md`,
  unchanged since 2026-11-03). The window opened 2026-11-04 broker-server time.
  §9 must **not** be backfilled as if signed before the window opened.
  If registration was completed elsewhere, record it with its real date and
  hashes; if not, this window is observation-only and can never later be
  presented as a GO/NO-GO under that protocol. A fresh, separate protocol
  would be needed for a future preregistered window.
- **LIVE remains LOCKED. Style 7 demo orders remain NOT permitted.**
  No input, stop, target, router rule, session or risk parameter was changed
  in this branch, precisely so that no in-sample tuning is smuggled in as a fix.
  The P0–P5 fixes from the 2026-11-03 specialist analysis (real WMMarkets
  commission document, cost-stressed RR, gap/news stress, a genuinely
  regime-gated router, fill-rate accounting, sell-side diagnosis) are
  **new hypotheses**, each needing its own separate, preregistered protocol —
  not edits to the frozen Style 7 result.

## What still has to happen on the owner's Windows PC (in order)

1. `START_HERE.bat` → install from `main` `0f84b0a` (or this branch's identical EA),
   MetaEditor compile of `QTS_Gold_Robot.mq5` with **0 errors, 0 warnings**,
   fresh EX5 hash recorded. If compilation fails, send the exact log back;
   never edit a frozen threshold to force a compile.
2. Decide the §9 question above (registered elsewhere / not registered /
   fresh protocol later) and record the decision with its real date.
   Do not run a "preregistered" Style 7 test on a window whose registration
   was not completed before it opened.
3. Only for a properly preregistered future window: safety_on Strategy Tester
   run (RiskPerTradePct 0.50, RewardToRisk 1.0, TesterIgnoreDailyAndPeakStops=false,
   session 06:00–22:00 broker time, MaxPositionMinutes 180), returning
   unmodified native HTML + forensic CSV + a measured WMMarkets commission/swap
   statement. No demo-forward and no live step follows from a tester pass alone.
4. Report the two Linux-test fixes and this note to the main branch only
   through a normal review; this branch is **not merged** by this review.
