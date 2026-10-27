# QTS Gold Robot — Windows Release Candidate Engineering Handoff
**Date:** 2026-10-27 | **Status:** source package and research/virtual-DEMO candidate; NOT production-approved.

## Purpose and scope

One canonical MQL5 expert `gold_robot/mt5_robot/QTS_Gold_Robot.mq5` operates on **WMMarkets Demo / XAUUSD@** with its two compact local includes. No separate competing EA, signal servers, cloud agent, DLL import, Python broker execution or extra account credential store are required for the MT5 robot.

The operator uses **`START_HERE.bat` from repository root**. The Gold MT5 path is independent of the Python research desktop, though both exist in the repository.

## Completed, implementation-level review

| Engineering area | Current implementation | Acceptance interpretation |
|---|---|---|
| Install | One target MT5 Data Folder and MetaEditor shared by EA and Preflight; each component has source-hash validation, backup/rollback, zero-errors/zero-warnings and fresh EX5 verification | Windows synthetic path/rollback checks pass; current user-terminal MetaEditor compile **not independently observed** |
| Access control | REAL/CONTEST blocked by `DemoOrTester`/OnInit; only WMMarkets-Demo USD XAUUSD@ with two explicit inputs enables connected Demo orders | REAL locked; default observation-only; tester research remains separately authorized |
| Strategy selection | Existing former-stop & retest LIMIT plus closed-candle break/accept/retest and sweep/reclaim hypotheses | Four isolated candidates, NOT validated profitable strategies |
| Causality | Closed M5/M15/H1 bars; pre-established structure older than probe & confirm candles | Static no-future-access coverage; native broker replay still required |
| Entry execution | `OrderCheck`, broker LIMIT, server-side SL/TP and expiry; no market fallback | Historical rejection, pending-fill and gap behavior still needs new native evidence |
| Cash/risk | `OrderCalcProfit` and stressed stop costs, legal lot step/min, margin cap, spread/session/fresh quote | Hard per-trade risk check; actual gap/slippage can exceed modeled cap |
| Connected DEMO | Explicit `EnableDemoOrders=true` AND `EnableDemoForwardOrders=true`, max default effective 0.25% equity per trade | Virtual execution path awaits MetaEditor compile and connected WMMarkets Demo-forward observation |
| Halt authority | Execution-incident latch, unresolved submission marker, daily/peak equity stops, pending-entry caps | Halt bypass is only `MQL_TESTER`; daily/peak protection stays enabled on DEMO-forward |
| Broker reconciliation | Broker-authoritative deals and locally deduplicated audit CSV; restart/reconnect checks | Broker correction/commission timing and all failure races not exhaustively verified |
| Stop-Loss forensics | Read-only Bid/Ask after-stop windows; missing tick coverage marked UNKNOWN | Requires timestamped broker fills and ticks; do not widen SL simply after price rebounds |
| Operator experience | Unified START_HERE, Broker Preflight, local HTML/JSON readiness, four MT5 `.set` presets and four native-report comparison | Broker readiness now also checks the installed Preflight source hash, EX5, compile log and CSV freshness; NONE of these is strategy-profit evidence |

## Explicit boundaries

**Successfully passed CI** can prove code/tester preset generation, installer path invocation, report escaping, source hashes and guarded source conditions. It **cannot** claim: newest EA compiled on the user's WMMarkets terminal; user logged in to DEMO; connected DEMO broker orders filled; real-tick out-of-sample after-cost profit; or REAL-money safety under every broker operational failure.

Every virtual-forward trial must preserve its trade/closed-bar logs, actual spreads, volume/contract rules, commissions, swap, stop-gap triggers, slippage, unfilled limits, retries after connection loss and realized drawdown.

Prior baseline and sweep results were not validated positive. No user funds should be committed in reliance on a source-only handoff.

## One-screen Windows operator workflow

1. From a **clean main checkout**, update using `git pull --ff-only origin main` (do not delete old worktrees or data).
2. `START_HERE.bat` → option **1**. Verify both native MetaEditor compiles report `0 errors, 0 warnings`. If not, installer rolls back.
3. Open connected **WMMarkets Demo** `XAUUSD@`; Navigator → Scripts → `QTS_Broker_Preflight`. Use menu **2** to read the local HTML report. Do not bypass blocked broker-size/commission concerns.
4. Menu **5** generates 4 safe `.set` profiles in `gold_robot/reports_local/tester_presets`. MT5 Ctrl+R → Expert `QTS_Gold_Robot` → `XAUUSD@` → M15 → *Every tick based on real ticks* → $3,000 operator-selectable initial deposit → Inputs → Load each preset. Run the **same fixed dates and costs** for EntryStyle 0,1,2,3. Save full MT5 **Report, Deals, Orders and Journal** separately.
5. For optional **connected virtual-DEMO forward**, only AFTER step 2 succeeds: use the dedicated account, set *both* `EnableDemoOrders` and `EnableDemoForwardOrders` to true. The EA will verify account mode/server/symbol/USD, use risk <=0.25% by default, and retain daily halts. Operator supervises Experts/Journal and can set `PauseNewEntries=true`.
6. REAL remains locked regardless of flag values. Do not advertise steady income or a validated trading edge.

## Release gate and evidence not yet supplied

- User-terminal native MetaEditor compile of this exact main commit, with current source and no warnings. Both EA and broker preflight must use the same terminal and compiler.
- Four real-tick MT5 Strategy Tester runs from independent history, with full broker costs and trades (not just signals).
- A defensible post-stop Bid/Ask forensic sample distinguishing stop placement, spread and adverse selection.
- Supervised connected WMMarkets DEMO order acceptance/fill/expiry/restart/kill-switch check, including no accidental unintended exposure.
- Independent after-cost forward/out-of-sample evidence supporting a strategy before asking to unlock REAL.

**Current disposition: suitable for installed observation, native Strategy Tester research, and explicitly opt-in virtual DEMO-forward *evaluation* after native compile. NOT a validated profitable product and NOT a REAL-money production release.**
