# 6 — Execution Architecture

**Principle:** Execution is independent from strategy logic. MT5 is an external authority whose state must be reconciled — never assume fill on API success.

## 6.1 Order Lifecycle (State Machine)

```
OrderIntent (strategy)
  │  RiskEngine.pre_trade → allow/veto/resize
  ▼
PENDING  ──submit via BrokerAdapter──► ACCEPTED ──► PARTIALLY_FILLED ──► FILLED
  │           │                          │  ▲              │
  │           └────────► REJECTED        └──┘              │
  │                        │                               │
  └────────────────────────┴──────────────────────────────► CANCELLED
```

- `client_order_id` is idempotency key: `f"{strategy_id}:{uuid7}"`. Duplicate submit with same key → return existing order, do not double-send.
- `exchange_order_id` assigned by venue on ACCEPTED.
- State transitions only forward (except PENDING→REJECTED/CANCELLED).
- Every transition emits `OrderEvent` to audit log + bus.

## 6.2 Components

| Component | Responsibility |
|-----------|----------------|
| `OrderManager` | Owns Order lifecycle, idempotency, retry, timeout |
| `ExecutionEngine` | Routes OrderIntent → Risk → OrderManager → BrokerAdapter |
| `MatchingEngine` | Backtest/paper matching: spread, slippage, latency, partial fills |
| `BrokerAdapter` | Venue-specific translate + transport (MT5, Paper, Replay) |
| `Reconciler` | Polls venue truth, detects drift, heals state |

## 6.3 ExecutionEngine Flow

```
Signal → Target → OrderIntent → RiskEngine.pre_trade
                                  │ veto → emit RiskVeto, NO_TRADE, stop
                                  ▼ allow/resized
                              OrderManager.submit
                                  │
                          BrokerAdapter.submit(intent) → Order (PENDING→ACCEPTED)
                                  │
                              Fill stream → Position/Account update → RiskEngine.post_trade
                                  │
                              Reconciler (every N sec) → compare local vs venue → emit ReconcileReport
```

- Latency model: `intent.created_at → broker.submit delay → venue ack delay → fill delay`. Configurable per adapter; backtest injects same delays.
- Retries: only for transport errors, never for REJECTED. Retry uses same `client_order_id`.
- Timeout: if no ack within `order_timeout`, query venue; do not assume.

## 6.4 BrokerAdapter Interface

```python
class BrokerAdapter:
    def connect(self): ...
    def disconnect(self): ...
    def submit(self, intent: OrderIntent) -> Order: ...
    def cancel(self, order_id: str) -> None: ...
    def positions(self) -> list[Position]: ...
    def account(self) -> Account: ...
    def orders(self) -> list[Order]: ...
    def ticks(self, instrument: Instrument) -> Tick | None: ...
```

### MT5 Adapter Details

- **Transport:** `MetaTrader5` Python package if available; else ZeroMQ bridge to MT5 terminal (EA). Adapter hides choice.
- **Symbol mapping:** `XAUUSD` → broker-specific symbol (e.g. `GOLD`, `XAUUSD.a`) via `symbol_map` config.
- **Lots:** MT5 lot semantics (`contract_size=100` for XAUUSD). Adapter converts `quantity` (oz) ↔ `lots`.
- **Fills:** MT5 `order_send` result → map to `OrderState`; then poll `positions_get`/`orders_get` for truth.
- **Errors:** `TRADE_RETCODE_*` mapped to `OrderRejectedReason` (e.g. `INVALID_VOLUME`, `MARKET_CLOSED`); retriable vs permanent classified.
- **No assumption:** Even `TRADE_RETCODE_DONE` does not guarantee fill until reconciled.

### Paper Adapter

- Uses `MatchingEngine` with same logic as backtest but on liveTicks. Tracks virtual positions/account separately.
- Useful for SHADOW mode: compare paper vs live fills.

### Replay Adapter

- Replays historical fills for deterministic integration tests.

## 6.5 MatchingEngine (Backtest Realism)

For each order, matching applies in order:

1. **Spread:** `mid ± spread/2`. For XAUUSD, spread is dynamic — use historical spread if available else `spread_bps` param. BUY at `ask`, SELL at `bid`.
2. **Slippage:** `slippage_bps * ATR` or fixed bps; direction adverse to trade.
3. **Latency:** `execution_delay_ms` — order executes at `bar.close_time + delay`, not at signal bar close.
4. **Partial fills:** If `volume < quantity` or `liquidity_model` says, emit `PARTIALLY_FILLED` then `FILLED`.
5. **Fees/commissions:** `commission_per_lot` deducted from fill.

Stress variants multiply spread/slippage for adversarial tests.

## 6.6 Reconciliation

Runs every `reconcile_interval_s` (e.g. 30s live, 1s paper) and on every fill:

1. Fetch venue `positions()` + `orders()` + `account()`.
2. Compare to local `Portfolio` (quantity, avg_price, order states).
3. Classify drift: `NONE`, `QUANTITY_MISMATCH`, `UNKNOWN_ORDER`, `MISSING_ORDER`, `ACCOUNT_DRIFT`.
4. Actions: emit `ReconcileEvent`, alert, pause trading if drift > threshold, auto-heal only for known idempotent cases (e.g. local PENDING but venue ACCEPTED → update local).
5. Never auto-heal quantity mismatch — require manual or kill-switch.

Duplicate prevention: `client_order_id` stored in venue comment/magic field where supported; else local dedup table.

## 6.7 Position & Account

- `Portfolio` holds `positions: dict[Instrument, Position]` + `account: Account`, updated only via `Fill` events and `ReconcileReport`, never via intent.
- `avg_price` via weighted fill average; `unrealized_pnl` via mark-to-market on tick/bar close.

## 6.8 Failure Handling

| Failure | Behavior |
|---------|----------|
| Network down | Retry with backoff, same idempotency key, NO new orders, reconcile on reconnect |
| Venue REJECT | Log reason, do not retry, strategy notified via `on_order_update` |
| Venue timeout | Poll venue state, if unknown → SUSPEND |
| Duplicate order detected | Return existing order, alert |
| Position drift | SUSPEND, alert, require manual `qts reconcile --heal` |

## 6.9 Configuration

```yaml
execution:
  mode: backtest | paper | live
  reconcile_interval_s: 30
  order_timeout_s: 10
  max_retries: 3
  matching:
    spread_bps: 3
    slippage_bps: 2
    execution_delay_ms: 500
    commission_per_lot: 0.0
    partial_fill_model: none | volume_based
```
