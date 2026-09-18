# QTS Engineering Report — Authority, Evidence, and Safety Boundaries

**Status:** superseded audit report reconciled with the current checkout
**Updated:** 2026-09-18
**Branch:** `arena/01a0b358-trading-system`
**Inspected base:** `a885f65d252e`
**Environment:** Linux development sandbox; no MT5 terminal or broker session.

This report records the current engineering contract. It does not claim that
the sandbox has produced real broker observations or a validated trading edge.
The release-level operator summary is `docs/release_readiness_report.md`.

> **Current status (2026-09-18, post-snapshot):** this document is a historical
> snapshot of the 2026-09-17 checkout. Since then a REAL, provenance-qualified
> XAUUSD 15m dataset has been registered (`20260918-010+8f120133-1ba57af7`,
> 26,038 Dukascopy tick-derived mid OHLC bars, 407.00 days, 12/12 quality
> checks, readiness `READY`; see `docs/data_provenance_xauusd_dukascopy.md`),
> and the pre-registered impulse study was re-run on it in `REAL_CLAIMS` mode
> with the measured conclusion `REGIME_DEPENDENT` → `BLOCK` and no promotion
> (`docs/research/impulse_continuation_evidence.md`). Where this snapshot says
> "one synthetic fixture", read it as snapshot-time wording; the synthetic
> fixture itself is unchanged and remains `MECHANISM_VALIDATION_ONLY`.

## 1. Canonical authorities

| Concern | Canonical implementation | Boundary |
|---|---|---|
| Mode resolution | `qts.domain.modes` | Unknown selections fail closed; descriptive capability is not permission. |
| DEMO execution | `qts.lifecycle.demo_authority` | Current policy is `DEMO_EXECUTION = DISABLED BY POLICY`; enablement is unreachable today, while the authority records refusal history and retains the future boundary. |
| DEMO_FORWARD gate | `qts.lifecycle.demo_gate` | Fresh readiness can start observation only; no order path. |
| Risk limits | `qts.risk.authority`, `qts.risk.demo_limits` | Restrictions can tighten only; limits do not authorize execution. |
| Observations | `qts.observability.forward_observatory` | One append-only SQLite store with provenance; JSON is derived. |
| Provenance/metric semantics | `qts.domain.provenance` | `MEASURED`, `UNAVAILABLE`, `INSUFFICIENT_EVIDENCE`, and blocked states stay distinct. |
| Research lineage | `qts.research.experiment`, `campaign`, `readiness` | Immutable configuration, dataset/version, seed, split, costs, trial count, conclusion, and failure reason. |
| LIVE governance | `qts.lifecycle.live_gate` | Separate lock; no DEMO or research result unlocks it. |

## 2. Current safety matrix

| Mode | Data | Broker orders | Product result |
|---|---|---|---|
| DEVELOPMENT | synthetic/backtest only | never | mechanism research |
| PAPER | recorded data with simulated fills | never | simulated evidence |
| SHADOW | would-be intents | never | divergence/intention evidence |
| DEMO_FORWARD / OBSERVE_ONLY | real MT5 demo data when available | structurally zero | provenance-bound observations |
| DEMO_EXECUTION | capability boundary retained | `DEMO_EXECUTION = DISABLED BY POLICY` | unreachable today; durable refusal; no permission |
| LIVE | real environment only | locked | requires independent governance/evidence |

`ExecutionMode.DEMO_EXECUTION.can_submit_broker_orders` remains `true` as a
capability-model compatibility value. It is not product permission. The
separate authority/API policy overrides it and always returns
`execution_permitted=false`.

## 3. DEMO boundary corrections

The previous implementation allowed a successful readiness/acknowledgement
transition to look like DEMO execution permission. The current boundary is
explicit:

- `DemoExecutionAuthority.enable()` always refuses, even with a fresh passing
  readiness object and both acknowledgements.
- The refusal is appended to the durable state/history and a refusal audit is
  attempted; no `enabled=1` state is written.
- `POST /api/demo/enable` is diagnostic-only and returns `409` with policy and
  readiness reasons. It cannot be used to create an order permission.
- `DEMO_FORWARD` collection owns no order submission call and remains the only
  broker-facing product path.
- UI operations, setup, trading, comparison, and governance views render
  `DISABLED BY POLICY` and do not offer an enable action.
- Tampered enabled rows, restarts, missing/failed readiness, and mode changes
  remain fail-closed.

No demo fill, account state, spread, slippage, latency, reconciliation, or
profitability is inferred from readiness or observation counts.

## 4. Observation/provenance corrections

The canonical observation store is `data/sqlite/forward_observatory.db`.
`data/evidence/forward_observation_manifest.json` is a derived export and
currently records zero sessions/ticks/signals. It must never be populated with
synthetic or quarantined samples labelled as DEMO evidence.

Every accepted observation carries source/session/timestamp/code provenance.
The timestamp contract remains unchanged: authoritative UTC `time.time()`;
broker server-local time minus one measured offset; retain the last good offset;
use zero only before any valid measurement; reject future/stale timestamps.
The FS-c42bbd regression suite remains part of the verification boundary.

The paper/shadow comparison now uses event alignment for signal agreement and
returns `UNAVAILABLE` with a reason for execution-side metrics because
DEMO_EXECUTION is disabled. Legacy fabricated constants are quarantined and
not claim-bearing.

## 5. Research/evidence corrections

At the time of this snapshot the canonical store contained one synthetic
fixture dataset:
`XAUUSD_1H_500`, 500 bars, 20.83 days. The quality checks pass for the fixture
schema, but readiness blocks claims because provenance is `SYNTHETIC`, depth is
below 5,000 bars, and span is below 180 days. Inventory/source-audit/quality/
historical-depth/edge/comparison/forward artifacts are regenerated from that
single source and retain explicit limitations.

Research records now require a complete falsifiable hypothesis: mechanism,
measurable prediction, null, competing explanations, falsification criteria,
required data, horizon, and population/regime. Experiments preserve immutable
configuration and cumulative trial memory. Blocked and rejected trials remain
in the denominator; no trial reset or unsupported promotion is allowed.

Current conclusion: `BLOCKED_INSUFFICIENT_DATA` / `NO_TRADE`.

`ValidatorPipeline.validate_stress()` treats non-numeric and non-finite stress
outputs as explicit `MEASURED_INVALID` blocking checks. It never replaces
`NaN`/`inf` with a favorable sentinel.

## 6. Verification snapshot

- `ruff check .`: clean.
- `python -m compileall -q src tests`: clean.
- Default `pytest -q`: 720 passed, 27 skipped; skipped integration/browser
  checks are not presented as evidence.
- Node UI logic tests: 25 passed.
- Direct authority/API checks: full-gate enable refuses; API enable returns
  `409`; state/config remain disabled.
- Evidence inspection at snapshot time: one canonical synthetic dataset, zero
  real forward observations, comparison execution metrics unavailable,
  edge/campaign conclusions blocked. (Post-snapshot: a REAL Dukascopy-derived
  XAUUSD 15m dataset is now registered; see the status note at the top.)

## 7. Remaining limitations

1. No real Windows/MT5 terminal observation was available in this checkout.
2. Historical depth, population breadth, regime coverage, measured costs, and
   execution evidence are insufficient for a claim.
3. Null/placebo/regime/gross-net controls remain blocked or unbound where the
   current experiment did not execute them.
4. Browser-level screenshots and opt-in integration tests require their
   external dependencies/flags and are not silently counted as passed.
5. DEMO_EXECUTION remains intentionally disabled and LIVE remains locked.

The next operator action is to acquire and register provenance-qualified
history, then regenerate and inspect the falsification/evidence bundle. No
execution mode should be enabled to satisfy a test or demonstration.
