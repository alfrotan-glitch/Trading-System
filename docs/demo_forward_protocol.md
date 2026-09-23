# Demo Forward Protocol — Observe Only (DEMO, Never LIVE)
Version 2026-09-18

## Safety Boundary
```
DEVELOPMENT   — backtest only, mock, no broker
PAPER         — simulated fills, next-bar-open, no broker orders
SHADOW        — would-be intents, checks risk/spread, no submission
DEMO_FORWARD  — REAL MT5 + REAL market data + REAL DEMO account, OBSERVATION ONLY — no order path exists in this mode
DEMO_EXECUTION — DISABLED BY POLICY today; no order path is reachable while policy is active; authority/execution boundary retained for future explicit authorization
LIVE          — real money, separately gated, LOCKED
```
No env can silently become another (mode resolution: `qts.domain.modes` — unknown
selections fail closed). Risk limits remain inspectable, but they do not create
an order permission while the product policy disables DEMO_EXECUTION. The
observation path has no order boundary.

## Lifecycle
```
RESEARCH → VALIDATING → FORWARD_OBSERVATION → PAPER_VERIFIED → SHADOW_VERIFIED → DEMO_OBSERVATION
```
`DEMO_EXECUTION` is intentionally absent from the enabled lifecycle. `LIVE`
requires its separate scientific, reconciliation, risk, governance, and human
approval gates and remains locked.

## Phase 1: Observe Only (Safe, No Orders)
- Start via **Demo Forward → Start Observation** — refused unless all 14 readiness checks pass (fail-closed).
- Records real MT5 demo-account ticks with provenance class `DEMO` into the canonical observation store (`data/sqlite/forward_observatory.db`), bound to an audited session carrying environment/mode, broker, canonical+broker symbol, timestamp basis, and code version.
- No `order_send`, no order path, no capital. `data/evidence/forward_observation_manifest.json` is a DERIVED export.
- Legacy `demo_forward_observations.json` (fabricated fills) was quarantined — see `data/evidence/quarantine/README.md`; it satisfies nothing.

## Phase 2: DEMO_EXECUTION (authorized — currently NO_TRADE)

An owner authorization artifact (`data/evidence/demo_execution_authorization_2026-09-23.json`,
DEMO account only, `LIVE = LOCKED`, zero real capital) resolves
`DEMO_EXECUTION = ENABLED_AUTHORIZED`; without such an artifact the resolved
policy is `DEMO_EXECUTION = DISABLED BY POLICY`, which remains the shipped
default of a clean checkout. A passing 14-check readiness report can authorize
**observation only** — by itself it never creates order permission.

`POST /api/demo/enable` returns HTTP 200 only when the authorization is valid
**and** every gate passes (explicit confirmation, risk acknowledgement, FRESH
passing readiness, required checks, broker-capable mode); otherwise it returns
HTTP 409 with `execution_permitted=false` and the reasons, and writes no
enabled state. Per-order permission is a further, separate decision
(staged arming, pinned+confirmed broker identity, eligible registered
strategy, 22 pre-trade checks in the same cycle) — see
`docs/demo_execution_authorization_and_safety_2026-09-23.md`.

No strategy has passed the research gates, so this path currently has no
actual demo fills, execution latency, slippage, broker responses, positions,
exits, or P&L records. Those fields remain `UNAVAILABLE`, not zero or
simulated.

## Comparison
The canonical observation store can measure signal/theoretical-price versus
hypothetical-price divergence when both fields are present. Execution/fill
divergence, realized P&L, and paper/shadow-to-broker fill differences are
`UNAVAILABLE` because OBSERVE_ONLY submits no orders and the DEMO execution
path has not traded (no eligible strategy — `NO_TRADE`). The API reports these states explicitly rather than deriving them from
simulation.

## Position Management Research
During demo_forward, research engine can compare (still under same gates):
- fixed TP/SL, trailing, volatility-based, structural, momentum-decay, time, partial, dynamic risk reduction, emergency exit
No demo result auto-validates — must re-pass validation pipeline.

## Stopping
- Demo Forward → kill switch or close app → clean shutdown, durable audit.
