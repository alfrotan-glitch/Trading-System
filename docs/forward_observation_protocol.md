# Forward Observation Protocol
Version: 0.1.0

## Purpose
Safe forward-observation mode that runs continuously without placing real orders, collecting future research evidence.

## Safety
- No live trading, no capital exposure — `ForwardObservatory` `observation_sessions` status ACTIVE/ENDED, no order submission.
- Records only hypothetical executions; `ExecutionRealityStore` source remains SYNTHETIC until real broker observed.
- Human approval required to move beyond observation (promotion ledger).

## What Is Recorded
- **Live quotes**: timestamp, symbol, bid/ask/mid, spread_bps, data freshness
- **Spreads**: at decision time
- **Volatility**: realized vol 20
- **Market sessions**: London/NY/Asian, weekend_closed
- **Signals**: strategy state, side, theoretical vs executable bid/ask, hypothetical fill, slippage model (2bps), latency where measurable
- **NO_TRADE decisions**: with reason (regime filter, vol low, risk)
- **Hypothetical orders**: intent count, would-be trades, estimated fills
- **Hypothetical fills**: fill price, volume, slippage
- **Theoretical vs executable**: gap between signal price (mid) and bid/ask
- **Latency**: submission→ack where measurable (0 if simulated)
- **Market regime**: trend/range, volatility regime, session, acceleration, compression/expansion
- **Data interruptions**: missing ticks, stale >1s
- **Anomalies**: spread spike, bid/ask inversion attempt

## Storage
`src/qts/observability/forward_observatory.py` SQLite `observation_ticks`/`observation_signals`/`observation_sessions`, `to_manifest` → `data/evidence/forward_observation_manifest.json` with sample ticks/signals, sessions count, generated_at.

## How To Run
- Simulated: `ForwardObservatory().simulate_observation(symbol="XAUUSD", n_ticks=10)` for testing (currently used).
- Real (when MT5 live): subscribe to `MT5Adapter` tick, poll `MarketDataProvider` every second, record `ObservationTick` with real bid/ask, run strategy `on_bar` on live bars, record `ObservationSignal` with executable prices, never call `broker.submit`.
- Desktop: Market Monitor shows live quotes, Forward Observatory view shows active sessions, signals, NO_TRADE, hypothetical fills, slippage.

## Evidence Use
Ticks/signals become future `data_inventory` rows (forward dataset), must be versioned immutable, checksum, used for regime observations and later research reboot.

## Example
Current `forward_observation_manifest.json`: simulated 10 ticks, 10 signals (30% signals, 70% NO_TRADE), spread 0.5-1.5, sessions 1 ended.

## Desktop UI
Market Monitor, Forward Observatory views in `src/qts/desktop/ui`.

