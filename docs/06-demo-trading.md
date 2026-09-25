# 6. Demo Trading Workflow

## The 12-Step Operational Trade Lifecycle

Demo trading in QTS is not an unmonitored script; it is a fully instrumented, auditable lifecycle designed to prove execution mechanics before real capital is considered.

```
 [1. Connect & Verify] ──► [2. Bind Tradable Symbol] ──► [3. Probe Live Quote]
                                                               │
 [6. Atomic Submit]   ◄── [5. Pre-trade gate]   ◄── [4. Staged Arming]
        │
        ▼
 [7. Broker Receipt]  ──► [8. Reconcile Order]      ──► [9. Monitor Position]
                                                               │
 [12. Audit Journal]  ◄── [11. Reconcile Closure]   ◄── [10. Close Position]
```

---

## Lifecycle Steps

### Step 1: Connect & Verify Broker Identity
- Verifies native IPC connection to MetaTrader 5.
- Confirms account mode is `DEMO` (rejects live accounts unconditionally).
- Checks server name, login ticket, company name, and currency.

### Step 2: Bind Tradable Symbol
- Resolves canonical symbol `XAUUSD` to broker venue symbol `XAUUSD@`.
- Checks symbol visibility in MT5 Market Watch and confirms `trade_allowed = True`.
- Caches authoritative broker contract specifications: contract size, digits, minimum volume (0.01), volume step, and stops level.

### Step 3: Probe Live Quote Freshness
- Fetches authoritative two-sided tick from MT5.
- Computes tick age against local UTC clock:
  $$\text{Age} = t_{\text{current}} - t_{\text{tick}}$$
- Rejects if $\text{Age} > 5.0\text{ s}$ or if bid/ask spread exceeds registered policy ceilings.

### Step 4: Staged Progression & Authority
- Progresses from `DISABLED` $\rightarrow$ `STAGE_1_CONNECTIVITY` $\rightarrow$ `STAGE_2_MIN_SIZE_ORDER`.
- Authority requires explicit operator confirmation and risk acknowledgement (`--confirm --risk-ack`).
- Permission decays after 120 seconds unless refreshed by verified terminal readiness.

### Step 5: Pre-trade gate
- Evaluates `run_pretrade_gate` before any intent reaches the broker.
- Fails closed on any `UNKNOWN` or `FAIL` outcome.
- Passing this gate does not mean a profitable strategy exists. Research status remains `NO_VALIDATED_EDGE`. The registered DEMO policy is an execution-cost probe.

### Step 6: Atomic Order Submission
- Claims order slot in SQLite using `BEGIN IMMEDIATE` to prevent concurrency races.
- Attaches the stop required by the registered diagnostic policy. That policy measures execution cost. It is not a validated edge.
- Submits `OrderIntent` via `MT5Adapter.order_send()`.

### Step 7: Broker Receipt & Retcode Verification
- Captures MT5 return code (`TRADE_RETCODE_DONE = 10009`).
- Records broker order ticket, deal ticket, executed price, executed volume, and submission latency.

### Step 8: Immediate Post-Order Reconciliation
- Polls broker deal history (`poll_live_fills`).
- Reconciles internal portfolio against venue positions. If phantom drift is detected, trading halts immediately.

### Step 9: Position Monitoring
- Continuously streams unrealized P&L, current market price, and holding duration.
- Enforces maximum hold time ceilings and policy stop-loss triggers.

### Step 10: Position Closure
- Submits offsetting market order (`TRADE_ACTION_DEAL`, opposite side) with position ticket identifier.
- Available automatically via autopilot exit policies or on-demand via CLI (`qts demo close`) and Web UI (`POST /api/demo/close`).

### Step 11: Final Post-Close Reconciliation
- Verifies broker open positions count returns to zero.
- Confirms closing deal fills are applied to portfolio and internal position balance is zero.

### Step 12: Audit Evidence Persistence
- All lifecycle timestamps, requested vs executed prices, slippage (bps), latency (ms), broker receipts, and realized P&L are committed to `DemoOrderJournal` (`data/evidence/demo_order_journal.db`).
