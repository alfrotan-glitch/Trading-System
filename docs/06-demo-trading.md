# 6. Demo Trading Workflow

## The 12-Step Operational Trade Lifecycle

Demo trading in QTS is a gated, auditable diagnostic lifecycle, not a validated strategy. No real-terminal connection or broker order was used in the 2026-10-18 audit; the integration fixtures are synthetic. A completed checklist still does not establish an economic edge or authorize LIVE.

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
- Resolves canonical symbol `XAUUSD` to the configured broker symbol (the alias may vary by account).
- Checks symbol visibility in MT5 Market Watch and derives tradability from broker `trade_mode` and available permissions.
- Reads authoritative broker contract specifications: contract size, digits, minimum/maximum volume, volume step and stop constraints. Values are broker-specific; no universal lot minimum is assumed.

### Step 3: Probe Live Quote Freshness
- Fetches authoritative two-sided tick from MT5.
- Evaluates raw broker-stamp freshness through QTS's shared server-clock contract; an unmeasured offset is not silently treated as UTC.
- Rejects stale/malformed quotes and spreads outside the registered policy limits. The provider's own tick-age cap is separate from the readiness gate.

### Step 4: Staged Progression & Authority
- Progresses from `DISABLED` $\rightarrow$ `STAGE_1_CONNECTIVITY` $\rightarrow$ `STAGE_2_MIN_SIZE_ORDER`.
- Authority requires explicit operator confirmation and risk acknowledgement (`--confirm --risk-ack`).
- Permission decays after 120 seconds unless refreshed by verified terminal readiness.

### Step 5: Pre-trade gate
- Evaluates `run_pretrade_gate` before any intent reaches the broker.
- Fails closed on any `UNKNOWN` or `FAIL` outcome.
- Passing this gate does not mean a profitable strategy exists. Research status remains `NO_VALIDATED_EDGE`. The registered provider is `DEMO-XAUUSD-TREND-TSMOM-V1` (completed-bar M15 EMA(12/48), 0.01 registered lots, USD 3.00/oz XAUUSD quote-price-distance stop (not a dollar-loss cap), four-hour max hold), marked diagnostic with `validated_edge: false`. It is a DEMO forward-measurement policy, not a validated edge. The monthly `ts9_lo` / `veto9` candidates are paper-only and are not connected to this order path.

### Step 6: Atomic Order Submission
- Claims order slot in SQLite using `BEGIN IMMEDIATE` to prevent concurrency races.
- For autopilot, submits only a provider-generated signal from a newly completed M15 crossover; seeded historical crosses never become actionable signals.
- Manual UI/CLI requests are operator-selected DEMO diagnostics, not strategy-generated signals. They require explicit confirmation and risk acknowledgement plus the same backend gates; journal rationale must preserve the manual source.
- Both paths are diagnostics, not a validated edge. A non-dry-run path can submit an order and must not be used without separate operator authorization.
- Submits `OrderIntent` via `MT5Adapter.order_send()` only after the authoritative pre-trade gate passes.

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
- All lifecycle timestamps, requested vs executed prices, slippage (bps), latency (ms), broker receipts, and realized P&L are committed to `DemoOrderJournal`. The file is the state-root artifact `journal_db` (`data/sqlite/qts.db` under `qts.config.paths`), not a file in the repository checkout.
