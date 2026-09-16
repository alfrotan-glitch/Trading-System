# Demo Forward Protocol — Observe First, Then Execute (DEMO, Never LIVE)
Version 2026-09-16

## Safety Boundary
```
DEVELOPMENT — backtest only, mock, no broker
PAPER       — simulated fills, next-bar-open, no broker orders
SHADOW      — would-be intents, checks risk/spread, no submission
DEMO_FORWARD — REAL MT5 + REAL market data + REAL DEMO account + REAL demo order lifecycle — labeled DEMO, independent conservative limits, kill switch, never LIVE
LIVE        — real money, separately gated, LOCKED unless all scientific+safety gates pass + human approval
```
No env can silently become another. `DEMO_FORWARD` defaults conservative:

- max 0.1 lot/order, 0.3 exposure, 3 open orders, 4 orders/min
- 50 USD daily loss, 100 USD /5% drawdown
- 30 bps spread, 20 bps slippage, kill switch armed
- See `src/qts/risk/demo_limits.py` and `configs/demo_forward.yaml`

## Lifecycle
```
RESEARCH → VALIDATING → FORWARD_OBSERVATION → PAPER_VERIFIED → SHADOW_VERIFIED → DEMO_OBSERVATION / DEMO_EXECUTION
```
`DEMO_EXECUTION` success does **NOT** become `LIVE_ELIGIBLE` automatically — separate gate requires DSR/PBO/PSR/costs/regime/perturbation/null/placebo/forward/reconciliation/risk/human.

## Phase 1: Observe Only (Safe, No Orders)
- Start via **Demo Forward → Start Observation** or forward observatory.
- Records every second (if tick available): timestamp, bid/ask/spread, symbol/timeframe/tick, session, strategy_state, regime, signal, NO_TRADE reason, hypothetical order.
- No `order_send`, no capital. Evidence `data/evidence/forward_observation_manifest.json` + `demo_forward_observations.json` (type demo_observe).

## Phase 2: Demo Execution Enabled (Requires Explicit Confirmation)
Prerequisites:
1. 14 checks ✓ (demo readiness)
2. Risk ack ticked
3. User confirms `confirmed=true` via **Enable Demo Execution** (POST `/api/demo/enable`)

Then QTS submits **real demo orders** via MT5 `order_send` to demo account:
- Captures requested vs actual price, slippage, latency, broker response, fill/partial/rejection/cancellation, position, exit, P&L with `label=DEMO` and provenance.
- Reconciliation checks after each fill; ambiguous orders (timeout) → fail-closed, require manual reconciliation, block new orders.
- Crash after submission → on restart, `startup_health_check` restores pending/ambiguous orders, verifies fills via MT5 deals, audits.

Every result in `data/evidence/demo_forward_observations.json` with fields:
`timestamp/bid/ask/spread/symbol/timeframe/tick/session/strategy_state/regime/signal/NO_TRADE/hypothetical order/actual demo order/requested_price/actual_price/slippage/latency/broker_response/fill/position/exit/PnL/provenance/label=DEMO`.

## Comparison
Automatic vs paper/shadow:

- `data/evidence/paper_shadow_demo_comparison.json` + **Paper/Shadow/Demo** view
- Metrics: signal agreement, expected vs actual entry, spread/slippage/latency, fill/rejected/partial/exit/P&L differences. Refresh via button or `POST /api/demo/comparison/refresh`.

## Position Management Research
During demo_forward, research engine can compare (still under same gates):
- fixed TP/SL, trailing, volatility-based, structural, momentum-decay, time, partial, dynamic risk reduction, emergency exit
No demo result auto-validates — must re-pass validation pipeline.

## Stopping
- Demo Forward → kill switch or close app → clean shutdown, durable audit.
