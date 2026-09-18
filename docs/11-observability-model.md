# 11 — Observability Model

**Principle:** Every live decision must be explainable through an audit trail. Dashboard is derived, not primary.

## 11.1 Three Pillars

1. **Audit Log** (primary) — immutable, structured, complete
2. **Metrics** (derived) — Prometheus/OpenTelemetry or in-process
3. **Health** (operational) — liveness, data freshness, broker connectivity

## 11.2 Audit Log

### What is logged

Every domain event:

- `BarReceived {instrument, open_time, version}`
- `SignalGenerated {strategy_id, instrument, side, strength, hypothesis_id, features}`
- `OrderIntentCreated {intent}`
- `RiskDecision {intent, allowed, veto_reason, limits_version}`
- `OrderEvent {order_id, from_state, to_state, reason}`
- `Fill {fill_id, order_id, price, quantity, fee}`
- `PositionUpdate {instrument, quantity, avg_price, pnl}`
- `AccountUpdate {balance, equity, margin}`
- `ReconcileReport {drift_type, local, venue, action}`
- `DataQualityAlert {check, details}`
- `KillSwitchEvent {reason, actor}`
- `LifecycleTransition {strategy_id, from, to, evidence}`

### Format

- **JSONL** `logs/audit.jsonl` — one JSON per line, UTC `recorded_at`, `event_id` (UUID7), `event_type`, `payload`, `code_version`, `data_version`.
- **SQLite** `audit_events` table — indexed by `event_time`, `strategy_id`, `instrument`, for queries.
- Both written atomically; JSONL is human-grep, SQLite is query.

### Query

```python
audit.query(strategy_id="S-042", event_type="RiskVeto", start=..., end=...)
qts audit query --strategy S-042 --type Fill --since 2024-01-01
```

### Guarantees

- Append-only, fsync per batch.
- No mutation; corrections are new events (`ReconcileEvent`).
- Retention: 2 years (configurable), rotation via `logrotate`.

## 11.3 Metrics

Derived from audit log or in-process counters:

| Metric | Type | Labels |
|--------|------|--------|
| `qts_bars_received_total` | counter | instrument, timeframe, version |
| `qts_signals_total` | counter | strategy_id, side |
| `qts_orders_total` | counter | strategy_id, state |
| `qts_fills_total` | counter | instrument |
| `qts_pnl` | gauge | strategy_id, instrument |
| `qts_exposure` | gauge | instrument |
| `qts_drawdown` | gauge | strategy_id |
| `qts_data_lag_seconds` | gauge | instrument |
| `qts_broker_connected` | gauge | venue |
| `qts_reconcile_drift` | gauge | instrument |
| `qts_risk_veto_total` | counter | reason |

Exposed via `qts metrics` or `/metrics` HTTP if `observability.http_enabled`.

## 11.4 Health

`qts health` checks:

- Data freshness: `now - last_bar < 2* timeframe`
- Broker connectivity: `adapter.ping()`
- Reconciler: `last_reconcile < interval*2` and `drift == NONE`
- Risk: `kill_switch == false`, `daily_loss < limit`
- Disk: `data/` writable, not full

Health endpoint `/healthz` for orchestrators.

## 11.5 Durability — Shipper (Phase 1)

- `AuditLog` is `SqliteAuditLog` (SQLite `audit_events` + JSONL `logs/audit.jsonl`, redacts `password/secret/token`).
- `Shipper` protocol (`src/qts/observability/shipper.py`): `LocalShipper(root=data/shipped)` for dev and `S3Shipper(bucket, prefix, region)` for prod (boto3). Key includes content hash `sha256[:12]` for idempotency, `ship_audit_logs(jsonl, shipper)` is periodic/CLI `qts audit ship`.
- `ObservabilityConfig.shipper {enabled, type: local|s3, bucket, prefix, local_root}` — credentials via env/IAM (or `security.SecretsProvider`), never YAML. Factory `make_shipper_from_config`.

CLI:

```bash
qts audit ship --jsonl logs/audit.jsonl --shipper s3 --bucket qts-audit --prefix prod/
```

Durability gate: SHADOW→LIVE_CANDIDATE requires shipper enabled in prod or explicit acknowledge unshipped risk in audit.

## 11.6 Lineage

Every decision carries `lineage {data_version, code_version, experiment_id, manifest_hash}`:

- `Bar.data_version → Manifest`
- `Signal.hypothesis_id → Hypothesis → Experiment`
- `OrderIntent.strategy_id → StrategyDef (code_version)`
- `Fill → Order → Intent → Signal`

Query: “why did we BUY at 2024-03-15 08:00?” → `audit.query(event_time=...)` → signal → hypothesis → validation.

## 11.6 Alerting

| Alert | Condition | Action |
|-------|-----------|--------|
| `DataStale` | lag > threshold | Pause strategy, notify |
| `BrokerDisconnected` | ping fail 3× | Reconnect, SUSPEND if >5m |
| `ReconcileDrift` | drift != NONE | SUSPEND, alert |
| `KillSwitch` | triggered | Cancel all, alert |
| `DrawdownBreach` | DD > limit | SUSPEND |

At v1: log + stdout; v2: webhook/email/PagerDuty via `AlertSink` interface.

## 11.7 Dashboard (Secondary)

Built only after audit is trustworthy. At v1: `qts dashboard` CLI summary + optional `streamlit`/`fastapi` UI that reads SQLite/JSONL — never writes.

Panels: equity curve, per-strategy PnL, risk gauges, data quality, recent vetoes, lineage graph.

## 11.8 Latency Tracking

Each event records `event_time` vs `recorded_at`. Latency = `recorded_at - event_time`. Tracked per venue; spike → alert.

## 11.9 Example Audit Line

```json
{"event_id":"018f...","event_type":"RiskVeto","recorded_at":"2024-03-15T08:00:01.123Z","strategy_id":"S-042","payload":{"client_order_id":"S-042:018f...","reason":"EXCEEDS_RISK_PER_TRADE","limits_version":1},"code_version":"a1b2c3d","data_version":"20240301-a1b2c3d-..."}
```
