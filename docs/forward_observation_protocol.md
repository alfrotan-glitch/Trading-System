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
- **OBSERVE-ONLY (canonical real path)**: `POST /api/observe/start` (UI:
  Trading → Start Observation). Refuses unless the 14-check DEMO readiness
  gate passes. The `ObservationCollector` polls `MT5Adapter.ticks` →
  `MarketDataProvider.get_tick` (validated, fail-closed) and records every
  tick with full broker-timestamp provenance into the canonical store. The
  runtime is structurally order-free (AST-pinned + runtime sentinel).
- Simulated: `ForwardObservatory().simulate_observation(...)` — testing only;
  every record is stamped `SYNTHETIC` and never counts as market evidence
  (`real_observation_count()` excludes it).
- Desktop: Market Monitor shows live quotes, Forward Observatory view shows
  active sessions, signals, NO_TRADE, hypothetical fills, slippage.

## Evidence Use
Ticks/signals become future `data_inventory` rows (forward dataset), must be versioned immutable, checksum, used for regime observations and later research reboot.

## Desktop Evidence Transfer (auditing a session from the repository side)
The canonical observation store lives ON the Desktop that observed MT5. An
auditor of the Git repository cannot see it, the terminal, or the broker.
To make a session (e.g. `FS-5a9542`) auditable, the Desktop exports ONE
sanitized artifact:

```bat
qts evidence export-session FS-5a9542
REM -> data/evidence/exports/FS-5a9542.session_evidence.json
```

The artifact (`qts.session_evidence.v1`) recomputes EVERYTHING from the
canonical store at export time (never from in-memory state or derived JSON):

- session identity + lifecycle status (`ENDED` / `ENDED_ON_ERRORS`) + sanitized meta
- tick count, provenance classes (DEMO/REAL only qualify; anything else is
  flagged as contamination), symbol identity, timestamp-basis + server-offset
  distribution, first/last event times, monotonicity violations
- duplicate handling (distinct raw broker stamps vs ticks; duplicates in the
  store are a verification failure)
- order-freedom: `orders_possible=false` flag, zero signal records, no order
  tables in the observation store
- a sha256 digest per tick and an ordered hash-chain root binding count,
  order, and content; first/last sample payloads verbatim for inspection

Sanitization is allowlist-based: session meta outside the collector contract
is redacted; credential-shaped keys are redacted; logins masked. Transfer
ONLY this artifact — it contains no passwords, keys, tokens, or broker
credentials.

Verify anywhere (no Desktop access needed):

```bash
qts evidence verify path/to/FS-5a9542.session_evidence.json
```

**Evidence discipline**: a `CONSISTENT` verdict proves the artifact is
internally coherent and contract-conforming. It does NOT, by itself, prove
the session was produced by a real MT5 terminal — that origin claim rests on
the operator's Desktop and the session's bound `code_version`/readiness
lineage. Numbers reported verbally (tick counts, duplicates, failures) remain
user-reported until the artifact is produced and verified.

## Example
A fresh clone's `forward_observation_manifest.json` reports zero ticks (no
observation session has run). Real sessions appear only after a readiness-gated
OBSERVE-ONLY run on a connected DEMO terminal.

## Desktop UI
Market Monitor, Forward Observatory views in `src/qts/desktop/ui`.

