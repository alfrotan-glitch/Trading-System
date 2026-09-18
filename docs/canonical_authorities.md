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
| `DEMO_EXECUTION` | **yes** | **no — disabled by product policy** | no |
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

- `/api/demo/enable` returns HTTP 409 with the policy refusal and diagnostic
  readiness evidence. It never creates order permission.
- `DemoExecutionAuthority.enable(...)` is hard-disabled as well; direct callers
  receive a durable refusal and no `enabled=1` state.
- `/api/demo/state` and `authority.is_execution_permitted(...)` always report
  `DISABLED` / `false` while the product policy is active, including when an
  old or tampered database contains an enabled row.
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

## 9. What was deliberately NOT changed

- The 14-check DEMO readiness contract and the verified WM Markets timestamp
  behavior (fail-closed freshness, measured server offset) are preserved and
  remain regression-tested.
- The observe-only collector's structural no-order guarantee (AST scan +
  runtime `order_send` sentinel) is preserved.
- SQLite/Windows reliability fixes (deterministic connection lifecycle via
  `qts.db.connect`, no destructor-based resource lifecycles) are preserved.
