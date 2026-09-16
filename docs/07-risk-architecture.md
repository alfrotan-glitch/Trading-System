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
    max_quantity: 1.0  # lots or units, per instrument
    max_notional: 10000  # USD
    max_risk_per_trade_bps: 50  # 0.5% of equity
    stop_loss_required: true
  portfolio:
    max_exposure: 2.0  # lots net
    max_leverage: 5
    max_correlated_exposure: 1.5  # e.g. XAUUSD + XAUEUR if added
    max_open_orders: 5
  account:
    daily_loss_limit: 200  # USD or bps
    max_drawdown: 500
    volatility_target: 0.15  # annualized, for vol-aware sizing
  kill_switch:
    enabled: true
    triggers: [daily_loss, max_drawdown, drift, consecutive_losses:5]
```

Limits are stored with `risk_version` in `ValidationReport` and `Order` lineage.

## 7.3 Checks

### Pre-Trade (per intent)

| Check | Veto Reason if Fail |
|-------|---------------------|
| Quantity >0, notional within max | `EXCEEDS_MAX_QUANTITY` |
| Notional ≤ max_notional | `EXCEEDS_NOTIONAL` |
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

Returns `RiskDecision {allowed: bool, resized_quantity?, veto_reason?}`.

### Portfolio (periodic)

- Exposure, leverage, margin level, correlated risk.
- Abnormal execution: slippage > 3σ, spread > threshold, latency spike → `SUSPEND`.

### Post-Trade

- Update drawdown, daily PnL, consecutive losses.
- If trigger → `kill_switch(reason)` → cancel all, flatten if configured, move to SUSPENDED.

## 7.4 Kill Switch

- **Software:** `RiskEngine.kill_switch(reason)` → sets `killed=True`, emits `KillSwitchEvent`, `ExecutionEngine` cancels all pending, optionally market-closes positions (configurable `flatten_on_kill`).
- **Manual:** `qts risk kill --reason "manual"` or API `POST /risk/kill`.
- **Broker:** MT5 terminal manual close still reconciled; Risk detects drift and holds SUSPENDED.
- **Persistence:** `killed` flag in SQLite survives restart; requires explicit `qts risk reset --confirm` + audit.

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
