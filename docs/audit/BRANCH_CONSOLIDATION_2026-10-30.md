# Branch consolidation record — 2026-10-30

## Goal and immutable safety boundaries
Consolidate research into the sole long-term branch `main`; no force-push; no live-money authorization. **LIVE LOCKED; PROFITABLE EDGE NOT VALIDATED.**

## Sources preserved as commit ancestry
- `arena/0c685e3b-trading-system@6ab8d48`: 54 previously absent long-history research/evidence/test files added.
- `independent/adaptive-repair-20261030@cb16a325`: 27 changed files applied on top of latest main; includes `independent/adaptive-robot-20261030@34cab34` in its history.
- `independent/trading-strategy-fixes-20261030@5fc0929`: source changes carried through the adaptive-repair work; its independent commit is preserved.
- `audit/ten-lenses-edge-gate-hardening-20261025@a70fdb5`, `fix/backtest-closed-trade-ledger-20261025@7ab0890`, `fix/reference-benchmark-cost-integrity-20261025@59f9b60`: current main already contains the relevant source/test implementations, retaining newer versions where they differ; independent commit histories preserved.
- `research/live-reference-benchmark-20261025@113c54e`: original benchmark research retained in history; main's newer cost-integrity revision retained as the effective working version.
- The other 11 legacy `arena/*` branches were already ancestors of main at audit time.

## Conflict choices
Latest pre-consolidation main `81ce01f` wins for existing files except paths explicitly updated from adaptive-repair and for missing long-history research files. This keeps the post-stop real-tick audit, observed adverse quote extremes, and adaptive router attribution fixes delivered after `6c8f786`. Historical modifications to existing files on the Oct-20 research branch were not blindly substituted for newer main code; their prior versions remain accessible through Git history. The generated `gold_robot/docs/SOURCE_CHECKSUMS.json` was combined from exact main and repair manifest entries for the chosen source blobs (94 entries), not selected wholesale from either side.

## Verification restrictions
GitHub object-tree assembly and SHA-level comparison are not a substitute for running tests. Native Windows MetaEditor compile, MT5 native Strategy Tester results, complete Python regression, and independent CI confirmation are still required. Neither the merge nor historical documentation constitutes proof of positive expected trading returns. Keep live order execution disabled.

After verifying all old branch heads are ancestors of main, old remote branch refs can be deleted without losing commit ancestry. No detached research branch should be used as a replacement production entry point.
