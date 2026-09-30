# 7 — Risk Architecture

**Principle:** Risk is an independent authority. Strategy can suggest, Risk disposes. Strategy authority never overrides Risk authority. Fail closed.

## 7.1 Placement

Risk sits **between** Strategy/Execution and Broker. Every `OrderIntent` passes `RiskEngine.pre_trade`. Post-fill, `post_trade` updates state. Portfolio-level checks run on timer and on position change.

```
Strategy → OrderIntent ──► RiskEngine.pre_trade ──► (veto/resize/allow) ──► BrokerAdapter
                                │
                         RiskLimits (config, versioned, approved)
                                │
                         RiskContext (account, positions, recent fills, volatility, drawdown)
```

## 7.2 Risk Limits (Versioned, Approved)

```yaml
risk:
  version: 1
  approved: false  # must be true for LIVE
  per_trade:
    max_quantity: 1.0  # lots
    min_quantity: 0.01  # lots (instrument.lot_size)
    quantity_step: 0.01  # lots — enforced, veto QUANTITY_STEP_VIOLATION if not multiple
    max_notional: 50000  # USD — enforced as lots × contract_size(100 for XAUUSD) × price; veto EXCEEDS_NOTIONAL
    max_risk_per_trade_bps: 50  # 0.5% of equity
    stop_loss_required: false
  portfolio:
    max_exposure_lots: 2.0  # lots net abs(|qty + delta|) — veto EXCEEDS_EXPOSURE
    max_exposure_notional: null  # optional USD cap
    max_leverage: 5  # (sum|qty|×contract×price)/equity
    max_correlated_exposure: 1.5
    max_open_orders: 5
  account:
    daily_loss_limit: 200  # USD loss (daily_pnl <= -limit vetoes)
    max_drawdown: 500  # USD peak-equ
    volatility_target: null  # annualized, for vol-aware resize (factor 0.25-1.0)
  kill_switch:
    enabled: true
    triggers: [daily_loss, max_drawdown, drift, consecutive_losses:5]
    persist: SQLite risk_state.killed (survives restart, needs qts risk reset --confirm)
```

Limits are stored with `risk_version` in `ValidationReport` and `Order` lineage.

## 7.3 Checks

### Pre-Trade (per intent)

| Check | Veto Reason if Fail |
|-------|---------------------|
| Quantity ≥ min_quantity, multiple of lot_size/quantity_step | `MIN_QUANTITY_VIOLATION` / `QUANTITY_STEP_VIOLATION` |
| Quantity ≤ max_quantity | `EXCEEDS_MAX_QUANTITY` |
| Notional = qty×contract_size×est_price ≤ max_notional | `EXCEEDS_NOTIONAL` |
| Risk per trade ≤ limit (stop distance × qty) | `EXCEEDS_RISK_PER_TRADE` |
| Stop-loss present if required | `MISSING_STOP` |
| Leverage after trade ≤ max | `EXCEEDS_LEVERAGE` |
| Net exposure after trade ≤ max | `EXCEEDS_EXPOSURE` |
| Correlated exposure ≤ limit | `EXCEEDS_CORRELATED` |
| Open orders < max | `TOO_MANY_ORDERS` |
| Daily loss not breached | `DAILY_LOSS_BREACH` |
| Drawdown not breached | `DRAWDOWN_BREACH` |
| Volatility-aware size (if enabled) | `VOL_RESIZE` (resize, not veto) |
| Kill-switch not active | `KILL_SWITCH_ACTIVE` |
| Instrument suspended | `INSTRUMENT_SUSPENDED` |

Returns `RiskDecision {allowed: bool, resized_quantity?, veto_reason?: RiskVetoReason, reason_detail}` + emits `NO_TRADE` on veto/kill.

### Portfolio (periodic)

- Exposure, leverage, margin level, correlated risk.
- Abnormal execution: slippage > 3σ, spread > threshold, latency spike → `SUSPEND`.

### Post-Trade

- Update drawdown, daily PnL, consecutive losses.
- If trigger → `kill_switch(reason)` → cancel all, flatten if configured, move to SUSPENDED.

## 7.4 Kill Switch

- **Software:** `RiskEngine.kill_switch(reason)` → sets `killed=True` in SQLite `risk_state`, emits `KillSwitchEvent`, `ExecutionEngine.handle_kill` cancels all pending and venue orders.
- **Manual:** `qts risk kill --reason "manual"` or API `POST /risk/kill`.
- **Broker:** MT5 terminal manual close still reconciled; Risk detects drift and holds SUSPENDED.
- **Persistence:** `killed` flag in SQLite `data/sqlite/qts.db` survives process restart; new `RiskEngine(db_path=...)` loads it; requires explicit `reset_kill()` + audit. `pre_trade` always checks `killed` first → `KILL_SWITCH_ACTIVE`.
- **Post-trade:** `post_trade(fill, ctx)` checks `daily_pnl <= -daily_loss_limit` or `drawdown >= max_drawdown` then kills.

## 7.5 Volatility-Aware Sizing

If `volatility_target` set:

```
position_size = (target_vol / realized_vol) * base_size
clipped to [min_size, max_size]
realized_vol = EWMA of returns (e.g. 20d)
```

Reduces size in high-vol regimes, preserves capital.

## 7.6 Interaction with Strategy

- Strategy proposes via `OrderIntent`; Risk may resize (e.g. vol-target) and returns adjusted intent. Strategy is notified via `on_order_update` with `resized` flag.
- Strategy cannot bypass Risk — `ExecutionEngine` enforces call.
- Risk veto is logged as `RiskVeto {intent, reason, limits_version}` in audit log.

## 7.7 Testing

- Unit: each limit in isolation, boundary values.
- Property: random intents never exceed limits after `pre_trade`.
- Failure injection: breach daily loss mid-day → next intent vetoed.
- Kill-switch: trigger → orders cancelled, no new orders accepted.

## 7.8 Observability

- `RiskVeto` events, `RiskMetrics` (exposure, leverage, drawdown) emitted to audit log + metrics.
- Dashboard shows current limits vs usage gauge.

## 7.9 Authority Diagram

```
        Strategy (suggest)
            │
            ▼
        RiskEngine (decide) ──► Broker (execute)
            ▲
            │
        RiskLimits (approve)
            │
        Human / ValidationReport (evidence)
```

No edge bypasses RiskEngine. Even manual `qts order submit` goes through Risk.
