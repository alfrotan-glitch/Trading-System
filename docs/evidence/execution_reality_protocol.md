# Execution Reality Protocol
Version: 0.1.0

## Purpose
Learn difference between SIGNAL PRICE, EXPECTED EXECUTION, ACTUAL EXECUTION — not claim realism without observations.

## Required Fields
`src/qts/execution/reality.py` `ExecutionObservation`: id, timestamp, symbol, signal_price, expected_price (bid/ask at decision), requested_price, submission_timestamp, broker_ack_timestamp, fill_timestamp, requested_volume, filled_volume, realized_price, bid/ask/spread at decision, slippage_bps (computed (realized-expected)/expected*10000), latency_ms (ack - submission), rejection_reason, cancellation, partial_fill, market_state, source (REAL/SYNTHETIC/SIMULATED/ESTIMATED/MODEL_DERIVED) — source must be explicit, never synthetic labeled as REAL.

## Collection
- **Where possible**: at decision time capture `MarketDataProvider.get_tick` bid/ask, record requested price, submission timestamp before `broker.submit`, broker ack timestamp from `MT5Adapter` order_send, fill timestamp from `broker.poll`, realized price from `Fill.price`, spread/slippage computed, latency measured.
- **Currently**: `ExecutionRealityStore` empty — 0 real observations, so summary notes "cannot claim realism". Rejects/partial fills tracked but not yet observed.
- **Synthetic** `ExecutionRealityStore` may contain `SYNTHETIC` for simulations (spread via high-low proxy), but `summary` separates `real_count` vs `synthetic_count` and warns.

## Storage
`src/qts/execution/reality.py` SQLite `execution_observations`, `to_json` → `data/evidence/execution_reality.json` with count, real/synthetic, avg/max slippage, rejections, partials.

## Cost & Slippage Research
Requires real observations; until then cost stress 1.0/1.5/2.0× is proxy, labeled `SYNTHETIC`. Do not assume mid-price edge equals executable edge.

## UI
Execution Center shows lifecycle, Risk Center shows block reasons, Market Monitor shows spread.

## Evidence
Current `execution_reality.json`: count 0, note no real observations.

