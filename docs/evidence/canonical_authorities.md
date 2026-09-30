This file is a dated architecture note. Current component ownership is in `QTS_PROJECT_CONTROL.md`.

# Canonical Authorities — Architecture Notes (2026-09)

This document describes the SINGLE-authority architecture introduced to close
the audit findings. Every component consumes these authorities; no component
may define its own competing limits, mode semantics, permission state, or
metric semantics.

---

## 1. Mode authority — `qts.domain.modes`

ONE canonical `ExecutionMode`:

| Mode | Broker data | Broker orders | Money at risk |
|------|-------------|---------------|---------------|
| `DEVELOPMENT` | no | **no** | no |
| `PAPER` | no (simulation) | **no** | no |
| `SHADOW` | no (intents only) | **no** | no |
| `DEMO_FORWARD` | **yes** (real MT5) | **no — structurally** | no |
| `DEMO_EXECUTION` | **yes** | **authorized only** — requires a recorded owner authorization artifact, staged arming, pinned identity, an eligible registered strategy and a passing `run_pretrade_gate` | no |
| `LIVE` | **yes** | yes (gated) | **yes** |

Resolution precedence (highest wins): explicit argument → `QTS_MODE` →
`QTS_ENV` → config file env → `DEVELOPMENT`. Unknown selections raise
`ModeResolutionError` — they never silently become DEVELOPMENT. Legacy env
aliases (`dev`, `demo`, `dry_run`, `micro`) map deterministically.

Restart semantics: the mode is never persisted by the app; a restart
re-resolves from environment/arguments. There is no hidden sticky mode and
no silent mid-session mode change.

## 2. DEMO execution-permission authority — `qts.lifecycle.demo_authority`

`DemoExecutionAuthority` owns ONE durable refusal/history state (SQLite
`demo_execution_state` + audit events). It is an execution boundary, not an
enable switch:

- The effective policy is resolved from the recorded owner authorization
  (`qts.lifecycle.demo_authorization`). With no valid artifact it is
  `DEMO_EXECUTION = DISABLED BY POLICY` (the shipped default); a valid,
  in-scope, un-revoked artifact resolves it to `ENABLED_AUTHORIZED` for an
  explicit DEMO-only scope with `LIVE` locked and zero real capital exposure.
- `/api/demo/enable` returns HTTP 200 only when the authorization is valid
  *and* every gate passes (explicit confirmation, risk acknowledgement, FRESH
  passing readiness, required checks, broker-capable mode). It returns HTTP 409
  with `execution_permitted=false` and the reasons on any refusal, and never
  writes an enabled state on a refusal.
- `/api/demo/state` and `authority.is_execution_permitted(...)` report
  `DISABLED` / `false` while the policy is un-authorized, including when an old
  or tampered database contains an enabled row.
- Per-order permission is a separate question from policy: the pre-trade gate
  (`qts.execution.demo_pretrade`) and the stage machine
  (`qts.lifecycle.demo_stage`) must also pass in the same cycle.
- DEMO_FORWARD readiness is still useful for starting the zero-order
  observation collector; it is not an execution prerequisite that can be
  promoted.

The old behavior — returning `demo_enabled=true` while ignoring
`readiness.passed` — is impossible, and passing readiness never creates a
DEMO_EXECUTION order path. Unknown broker evidence stays unavailable.

## 3. Risk authority — `qts.risk.authority`

ONE canonical limit set (`BASE_LIMITS`) + per-mode restrictions that may only
TIGHTEN (validated at import AND at resolution) + explicit operator overrides
(loosening requires `risk.approved`; every application is recorded with its
source and a stable `config_hash`).

`resolve_risk_limits_from_settings(mode)` is the standard entry point: YAML
`risk:` flows through the authority as the override layer — there is no
parallel consumer path. `DEMO_FORWARD_DEFAULTS` (demo boundary) is DERIVED
from the shared demo-boundary risk resolution; the numbers live in exactly one
place. They are descriptive safety metadata only while DEMO_EXECUTION is
policy-disabled and do not authorize orders.

Runtime visibility: `/api/risk` serves the resolved snapshot (limits,
sources, overrides, warnings, config hash). The UI never displays invented
values ("1%", "2 lots", "$500" placeholders were removed).

## 4. Canonical observation store — `qts.observability.forward_observatory`

ONE authoritative store for market observations: SQLite
(`data/sqlite/forward_observatory.db`) with provenance-first schema
(`provenance`, `session_id`, `symbol`, `event_time` accessor columns; the
full payload JSON is immutable).

- Sessions carry canonical identity: environment/mode, broker, canonical +
  broker symbol, data source, timestamp basis, code version, readiness
  summary, and `orders_possible: false` for observe-only sessions.
- The OBSERVE-ONLY collector stamps every record `provenance=DEMO` (real
  broker, demo account) and binds it to its session. Simulation writes
  `SYNTHETIC`. Nothing stamps `REAL` from a demo session.
- `real_observation_count()` counts only DEMO/REAL-provenance ticks — the
  impulse forward-evidence gate consumes THIS, never a JSON file.
- `forward_observation_manifest.json` is a DERIVED export (regenerable).
  It is never the primary source and never satisfies a gate by existing.
- Desktop -> audit transfer: `qts evidence export-session <id>` recomputes a
  sanitized, digest-bound artifact from the canonical store
  (`qts.observability.session_export`); `qts evidence verify <file>` checks
  it anywhere. See `docs/forward_observation_protocol.md` (Desktop Evidence
  Transfer). A consistent artifact proves internal coherence, never Desktop
  origin by itself.

## 5. Provenance model — `qts.domain.provenance`

`EvidenceProvenance`: `SYNTHETIC < HISTORICAL < PAPER < SHADOW < DEMO < REAL`,
with `UNVERIFIED` ranked below all (trusts nothing). Ambiguous evidence is
NEVER defaulted to REAL; `classify_record_provenance` downgrades any record
with broken symbol/timestamp/lineage integrity to UNVERIFIED.

`MetricValue` makes "not measured" inexpressible as a number: metrics are
`MEASURED` or `UNAVAILABLE`/`INSUFFICIENT_EVIDENCE` with machine-readable
reasons. A `MEASURED` zero is legitimate and explicitly distinct from an
unavailable metric.

## 6. Evidence quarantine — `data/evidence/quarantine/`

The legacy `demo_forward_observations.json` (fabricated demo fills: constant
2.5 bps slippage / 120 ms latency, prices near 2000, symbol `XAUUSD` instead
of the verified `XAUUSD@`, `source=REAL DEMO` despite synthetic origin) and a
stale simulated `forward_observation_manifest.json` were moved to quarantine
with a README documenting each violation. They are excluded from every claim
and every gate.

## 7. Live-gate proof tiers — `qts.lifecycle.live_gate`

Gate checks are classified:

- `structural` — source architecture guarantees (AST/source inspection)
- `integration` — verified against real components in-process
- `real_environment` — verified against real broker infrastructure

`mt5_connectivity` is `real_environment` tier and can only pass with a REAL
connected terminal. The previous MagicMock-based check (which "passed" in
every dev environment) is banned as live-gate evidence and
regression-pinned. Micro (LIVE-family) execution fails closed without a real
terminal.

## 8. Broker metadata & account authority — `qts.adapters.mt5_adapter`

Every SymbolSpec field resolves through an explicit alias table with NO
defaults: missing/None/non-finite/contradictory → `RuntimeError` (fail
closed). Tradability is authoritative from `trade_mode` (the real API's
signal); an absent `trade_allowed` no longer fabricates `True`.

Account state is broker-authoritative (`source="BROKER"`), with
`leverage`/`currency` as `None` = UNAVAILABLE when the broker does not
provide them — never guessed. `updated_at` is explicitly local RECEIPT time,
not a broker timestamp (MT5 `account_info` carries no server stamp).

Simulation accounts (`PAPER_SIMULATION`, `SHADOW_SIMULATION`,
`PORTFOLIO_SIMULATION`, `CLI_SYNTHETIC`) are explicitly labeled and can
never be confused with broker truth.

## 9. Durable suspension & recovery authority — `qts.execution.demo_session`

Exactly TWO durable records can suspend DEMO trading. They are written by
different components and enforced by different pre-trade checks:

| Durable record | Owning authority | Enforced by | Recovery predicate | Cleared through |
|---|---|---|---|---|
| `risk_state.killed` | `qts.risk.engine.RiskEngine` | `pre_trade`, `kill_switch_functional` | an explicit operator decision with a recorded reason, over a readable row | `RiskEngine.reset_kill()` |
| `reconcile_state.suspended` | `qts.execution.engine.ExecutionEngine` | `reconciliation_ready` | a fresh broker-authoritative `reconcile()` reporting `requires_suspend=False` | `ExecutionEngine.heal_reconcile()` |

This is not a second kill switch (§11.2 of `QTS_PROJECT_CONTROL.md` stands):
they answer different questions — "an operator stopped trading" versus "QTS
and the broker disagree about open positions" — and neither is an in-memory
mirror of the other.

**One reader.** `qts.execution.engine.load_reconcile_suspension()` is the ONLY
implementation that reads `reconcile_state`. `ExecutionEngine`, the LIVE gate
(`live_gate.check_reconciliation_health`), the API
(`api.deps._reconciliation_status` → `/api/health`, `/api/risk`) and startup
health (`desktop.health.run_reconciliation`) are thin adapters over it.
Agreement is structural, not maintained by discipline. Unreadable is
SUSPENDED; only a missing table or a missing store is benign; a read probe
never creates the store.

Historical evidence is never the active condition. `run_reconciliation`
previously scanned the last 50 audit events for `DRIFT`/`SUSPENDED`, which was
wrong in both directions: a healed drift blocked startup until it aged out,
and an unhealed suspension reported "reconciliation healthy" once 50 newer
events existed while every order was still refused.

**No startup probe may infer state from an audit keyword scan.** The audit log
is append-only evidence of what happened; a durable row is what *is*. A
rolling window over it fails in both directions — stale evidence blocks a
recovered system, and a genuine unresolved condition disappears behind newer
events, which is a fail-OPEN on unknown state. `startup_health_check`'s probes
therefore each read their own authority: `restore_suspension` and
`run_reconciliation` read the two durable records above, and
`restore_pending_orders` reads `demo_order_journal` (§11.4 — the only store of
execution history), reporting `AMBIGUOUS` rows and submissions still in flight
with no recorded outcome. Each names the blocking order rather than counting
it, so the operator can reconcile it with the broker.

**One recovery transition.** `DemoSession.resume_from_suspension(reason, actor)`:

```
SUSPENDED → RECOVERY IN PROGRESS → RECOVERY VERIFIED → RECOVERED (stage HALTED)
          ↘ a predicate is unsatisfied → SUSPENDED (nothing cleared)
```

It is all-or-nothing, idempotent, verified by re-reading the durable set after
the write, fail-closed, and audited in both directions — a refusal is durable
evidence, not a silent no-op. `DemoSession.durable_suspension_state()` is the
single read every surface reports.

Recovery clears active blocking conditions and grants NO permission: the stage
machine stays `HALTED`, the authority is untouched, and the full pre-trade gate
still runs before any order (`orders_permitted=false`, `next="prepare"`). The
live predicates are re-proven by `/api/demo/guide/prepare` and the existing
21-check gate — recovery duplicates none of them. `must_kill_on()` is
deliberately NOT a resume precondition: `stage_not_order_permitted` always
holds while HALTED and would deadlock recovery.

Surfaces: `qts demo clear-kill` and `POST /api/demo/guide/resume` are the only
entry points, and both run this transition. The HTTP status is the outcome of
the operation, never of the request being understood — `200` recovered, `409`
blocked with machine-readable `recovery.active_blockers`, `400` invalid
request. A `200` cannot imply readiness.

## 9a. Execution outcome authority

Everything from broker request construction to durable resolution of the
outcome — the transmission classification, the request contract, and how an
UNKNOWN outcome is ended with broker evidence — is specified in
`docs/evidence/execution_outcome_contract.md`. It is the other half of this
section: §9 owns suspension → recovery, that document owns
submission → outcome → resolution, and they meet at
`resume_from_suspension`, which runs the resolver as one of its predicates.

## 10. What was deliberately NOT changed

- The 14-check DEMO readiness contract and the verified WM Markets timestamp
  behavior (fail-closed freshness, measured server offset) are preserved and
  remain regression-tested.
- The observe-only collector's structural no-order guarantee (AST scan +
  runtime `order_send` sentinel) is preserved.
- SQLite/Windows reliability fixes (deterministic connection lifecycle via
  `qts.db.connect`, no destructor-based resource lifecycles) are preserved.
