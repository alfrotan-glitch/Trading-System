# Demo Forward Protocol — Observe First, Then Execute (DEMO, Never LIVE)
Version 2026-09-16

## Safety Boundary
```
DEVELOPMENT   — backtest only, mock, no broker
PAPER         — simulated fills, next-bar-open, no broker orders
SHADOW        — would-be intents, checks risk/spread, no submission
DEMO_FORWARD  — REAL MT5 + REAL market data + REAL DEMO account, OBSERVATION ONLY — no order path exists in this mode
DEMO_EXECUTION — REAL MT5 + REAL DEMO account + REAL demo order lifecycle — labeled DEMO, authoritative conservative limits, kill switch, never LIVE
LIVE          — real money, separately gated, LOCKED unless all scientific+safety gates pass + human approval
```
No env can silently become another (mode resolution: `qts.domain.modes` — unknown
selections fail closed). Demo limits are DERIVED from the unified risk authority
(`qts.risk.authority`, `resolve_risk_limits(DEMO_EXECUTION)`), not defined
independently:

- max 0.1 lot/order, 0.3 exposure, 3 open orders, 4 orders/min
- 50 USD daily loss, 100 USD /5% drawdown
- 30 bps spread, 20 bps slippage, kill switch armed
- Resolved snapshot visible at `/api/risk` with config hash and per-field source

## Lifecycle
```
RESEARCH → VALIDATING → FORWARD_OBSERVATION → PAPER_VERIFIED → SHADOW_VERIFIED → DEMO_OBSERVATION / DEMO_EXECUTION
```
`DEMO_EXECUTION` success does **NOT** become `LIVE_ELIGIBLE` automatically — separate gate requires DSR/PBO/PSR/costs/regime/perturbation/null/placebo/forward/reconciliation/risk/human.

## Phase 1: Observe Only (Safe, No Orders)
- Start via **Demo Forward → Start Observation** — refused unless all 14 readiness checks pass (fail-closed).
- Records REAL MT5 ticks with full provenance into the canonical observation store (`data/sqlite/forward_observatory.db`), bound to an audited session carrying environment/mode, broker, canonical+broker symbol, timestamp basis, and code version.
- No `order_send`, no order path, no capital. `data/evidence/forward_observation_manifest.json` is a DERIVED export.
- Legacy `demo_forward_observations.json` (fabricated fills) was quarantined — see `data/evidence/quarantine/README.md`; it satisfies nothing.

## Phase 2: Demo Execution Enabled (Requires Explicit Confirmation)
Prerequisites:
1. 14 checks ✓ (demo readiness)
2. Risk ack ticked
3. User confirms `confirmed=true` via **Enable Demo Execution** (POST `/api/demo/enable`)

Then — ONLY after the authority records a durable ENABLED state (fresh 14/14
readiness computed in the enable request; permission decays after
`reverify_ttl_s` and must be re-verified) — QTS submits **real demo orders** via MT5 `order_send` to demo account. Refusals return HTTP 409 with reasons; the state stays DISABLED and is never fabricated:
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
