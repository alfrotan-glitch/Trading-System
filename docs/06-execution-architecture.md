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

## 6.5 MatchingEngine (Backtest Realism) & Execution Convention (Phase 1)

For each order, matching applies in order:

1. **Spread:** `mid ± spread/2`. For XAUUSD, spread is dynamic — use historical spread if available else `spread_bps` param. BUY at `ask`, SELL at `bid`.
2. **Slippage:** `slippage_bps` adverse to trade.
3. **Latency/Execution convention:** **Next-bar open** — signal on `bar N close_time` queued as pending; matching uses synthetic `exec_bar` at `N+1 open` (`open==high==low==close==open(N+1)`). `execution_delay_ms` scheduled relative to `open_time`, not same-bar close. This eliminates lookahead.
4. **Partial fills:** If `volume < quantity` or `liquidity_model` says, emit `PARTIALLY_FILLED` then `FILLED`.
5. **Fees/commissions:** `commission_per_lot * quantity` deducted from fill, reflected in Portfolio realized.

Stress variants (`BacktestEngine.run_stress`) re-run strategy with `MatchingConfig(spread_bps *= multiplier, slippage_bps *= multiplier)` for multipliers 1.0/1.5/2.0 — not `PF*0.7`; stress metric is re-simulated PF/Sharpe.

## 6.6 Reconciliation (Phase 1: `requires_suspend`)

Runs every `reconcile_interval_s` (e.g. 30s live, 1s paper) and on every fill via `ExecutionEngine.reconcile()`:

1. Fetch venue `positions()` + `orders()` + `account()` (broker is authority).
2. Compare to local `Portfolio` (quantity lots, avg_price): `MISSING_POSITION` if local not on venue, `QUANTITY_MISMATCH` if lots differ, `UNKNOWN_POSITION` if venue has lots not in Portfolio.
3. `ReconcileReport {drift, details, requires_suspend}` — any drift except `NONE` sets `requires_suspend=True` (fail-closed, never auto-heal quantity). Caller must emit `NO_TRADE/RECONCILE_SUSPEND` and halt orders until manual `qts reconcile --heal` or kill reset.
4. `avg_price` diff >0.01 is logged but not suspend (venue avg may round).
5. Emits `DomainEvent(RECONCILE)` on drift; `NONE` is silent.

Duplicate prevention: `client_order_id` PK in SQLite `idempotency_store` (persistent) + `OrderManager.orders` in-memory. Persistent duplicate returns `REJECTED/duplicate-persistent` placeholder with no fill — survives restart (see `ExecutionEngine.submit_intent`).

### 6.6.1 MT5 Lots Fidelity

- `Instrument.lot_size` (0.01) enforces step; `MT5Adapter.lots_to_mt5_volume` quantizes to nearest step via `ROUND_HALF_UP`.
- `RiskEngine._notional_for = lots × contract_size × est_price`; exposure likewise lots×contract×price. Risk vetoes `MIN_QUANTITY_VIOLATION`/`QUANTITY_STEP_VIOLATION`.

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

## 6.7 Portfolio is Authority (Phase 1)

- `Portfolio` netting per symbol, `lots` signed; `apply_fill` handles weighted avg on add, unchanged avg on partial close, zero avg on flat, re-price on flip; fee deducted from `realized_pnl`/`balance`; `unrealized = lots×contract×(price-avg)` (long) or `|lots|×contract×(avg-price)` (short); `equity = balance + unrealized_total`.
- `ExecutionEngine.mark_price` drives unrealized; `_risk_ctx` uses `portfolio.equity()` for drawdown `peak_equity - equity`.

## 6.8 Idempotency & Audit

- `IdempotencyStore` SQLite `client_order_id PRIMARY KEY`; `OrderManager.submit` records `PENDING` → `FILLED/REJECTED`; `update_state` persists state.
- Every state emit `DomainEvent.ORDER_EVENT`; veto emits `RISK_VETO` + `NO_TRADE`.

## 6.9 Configuration

```yaml
execution:
  mode: backtest | paper | live  # live requires --confirm live + risk.approved + env=live
  reconcile_interval_s: 30
  order_timeout_s: 10
  max_retries: 3
  matching:
    spread_bps: 3
    slippage_bps: 2
    execution_delay_ms: 500
    commission_per_lot: 0.0  # USD per lot × qty
    partial_fill_model: none | volume_based
  # audit/shipper (observability)
  observability:
    audit_jsonl: logs/audit.jsonl
    shipper: {enabled: false, type: local|s3, bucket: qts-audit, prefix: qts/audit/}
```
