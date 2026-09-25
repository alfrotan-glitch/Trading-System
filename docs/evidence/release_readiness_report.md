# QTS Release Readiness Report — Research-First, Observation-Only Boundary

**Date:** 2026-09-18
**Branch:** `arena/01a0b574-trading-system`
**Current-state authority:** [`docs/current_state.md`](current_state.md)
**Environment:** Linux development sandbox; no MT5 terminal, broker account, or live market session is available here.

## Executive verdict

**RELEASE STATUS: RESEARCH / OBSERVE-ONLY — KEEP `NO_TRADE`.**

The checkout is coherent as a quantitative research workstation and preserves
negative evidence. It does not demonstrate a profitable edge, claim real MT5
observations, enable DEMO execution, or unlock LIVE.

- `DEMO_FORWARD` is the only broker-facing product path and is structurally
  observation-only: it can record real MT5 demo-account observations when a
  real terminal is present, and it submits zero orders.
- `DEMO_EXECUTION` is disabled by product policy. Readiness is diagnostic and
  may authorize observation startup only; it never creates order permission.
  `DemoExecutionAuthority.enable()` refuses even a fresh passing report,
  records the refusal, and never writes an enabled state.
- `LIVE` remains separately locked. No UI action, readiness result, synthetic
  fixture, paper/shadow result, or evidence export can promote it.

## A. Canonical authority and safety boundaries

| Question | Canonical authority | Current contract |
|---|---|---|
| Effective mode | `src/qts/domain/modes.py` | Unknown modes fail closed; capability metadata is not product permission. |
| DEMO execution permission | `src/qts/lifecycle/demo_authority.py` | `DEMO_EXECUTION = DISABLED BY POLICY` is the shipped default (durable refusal, `execution_permitted=false`); with a recorded owner authorization it resolves to `ENABLED_AUTHORIZED` for the DEMO account, while per-order permission still requires staged arming, a pinned identity, an eligible registered strategy and a passing `run_pretrade_gate`. |
| DEMO_FORWARD readiness | `src/qts/lifecycle/demo_gate.py` | Fresh 14-check diagnostic gate for observation only. |
| Observation persistence | `src/qts/observability/forward_observatory.py` | One append-only SQLite store; derived manifest is regenerable. |
| Risk boundary | `src/qts/risk/authority.py` and `demo_limits.py` | Mode restrictions can only tighten; safety metadata does not authorize execution. |
| LIVE governance | `src/qts/lifecycle/live_gate.py` | Locked without independent claim-grade evidence and explicit human governance. |

The API boundary is intentionally diagnostic-only:

- `POST /api/demo/enable` returns HTTP `409` with policy and readiness
  reasons unless every gate passes (explicit confirmation, risk acknowledgement,
  fresh passing readiness); on success it returns `200` with
  `execution_permitted=true` and persists an audited enabled state. It never
  bypasses the authority.
- `GET /api/demo/config` reports `demo_execution_disabled` from the resolved policy.
- `/api/demo/state` is the single state consumed by API/UI/execution checks.
- A readiness pass is not a fill, account-state measurement, slippage,
  latency, reconciliation, profitability, or execution result.

## B. Data observatory and provenance

The frozen inventory evidence records two dataset rows rather than counting
duplicate raw/curated representations as independent evidence. The checked-in
JSON is a derived snapshot, not a current quality certificate:

- Version: `20260918-010+c83567cb-572728d9` (synthetic fixture)
  - Instrument/timeframe: `XAUUSD` / `1H`
  - Rows/span: `500` bars / `20.83` days
  - Source/class: `SYNTHETIC:fixture:XAUUSD_1H_500.csv` / `SYNTHETIC`
  - OHLC quality checks: `12/12` passed for the fixture schema
  - Bid/ask, tick, measured spread, broker session, fill, latency, and real
    volume semantics: `UNAVAILABLE` in this dataset
  - Research eligibility: `MECHANISM_VALIDATION_ONLY`; not claim-eligible
- Version: `20260918-010+8f120133-1ba57af7` (REAL history)
  - Instrument/timeframe: `XAUUSD` / `15m`
  - Rows/span: `26,038` bars / `407.00` days
  - Source/class: `REAL:dukascopy:vudo805@4d6f155:XAUUSD:15m:mid-from-bid-ask-ticks`
    / `REAL`
  - Frozen acquisition snapshot: OHLC quality checks `12/12` passed under the
    previous event-count-only gap gate. Current audit status: **FAIL for gap
    completeness**: the preserved legacy inventory has 1,493 unexpected
    intervals (5.42%), while current conservative semantics find 1,785
    intervals (6.42% of active expected span), both above the unchanged 2%
    limit. No research rerun was
    performed.
  - Bid/ask (continuous), tick, measured spread, broker session, fill, latency,
    and real volume semantics: `UNAVAILABLE` in the canonical bars; a
    supplementary 23-event bid/ask spread study exists but is not a gate input
  - The frozen REAL impulse artifact records R1–R4 and R6 passing and R5
    **FAIL/non-blocking**; it remains historical research evidence, not a
    current quality certification.
  - Provenance record: `docs/data_provenance_xauusd_dukascopy.md`

The `data_quality_summary.json` and `historical_depth.json` exports were
generated before the REAL dataset existed and still describe only the synthetic
fixture; they are snapshot-time derived exports, not current coverage.

The following are derived exports and must not be treated as primary evidence:

- `data/evidence/data_inventory.json`
- `data/evidence/data_source_audit.json`
- `data/evidence/data_quality_summary.json`
- `data/evidence/historical_depth.json`
- `data/evidence/edge_validation.json`
- `data/evidence/forward_observation_manifest.json`
- `data/evidence/paper_shadow_demo_comparison.json`

No synthetic fixture, paper record, shadow intent, quarantined legacy artifact,
or derived JSON is relabeled as REAL or as a broker observation.

## C. Research and falsification status

The research contract retains hypothesis and experiment lineage: mechanism,
prediction, null, competing explanations, falsification criteria, required
data, horizon/population, immutable configuration hash, data version,
provenance, split, seed, costs, exclusions, trial count, code identity,
results, conclusion, and failure reason.

Current evidence is explicitly blocked:

- Bounded campaign artifact: `data/evidence/campaign_last.json` — `2` trials,
  `0` passed, conclusion `BLOCKED_INSUFFICIENT_DATA`.
- Autonomous campaign artifact: `6` trials, `0` passed, self-audit remains
  `BLOCK — independent audit gates remain unproven`.
- Edge validation: `BLOCKED_INSUFFICIENT_DATA`; synthetic provenance and
  500-bar/20.83-day depth/span are recorded as reasons. The cumulative ledger
  count is preserved for multiple-testing accounting and is not reset.
- REAL-data impulse campaign:
  `data/evidence/impulse_research_xauusd_dukascopy_15m.json` — `REAL_CLAIMS`
  mode on `20260918-010+8f120133-1ba57af7`; conclusion `REGIME_DEPENDENT` /
  `go_block BLOCK` with no promotion. R5 (tick/execution-cost data) remains
  `FAIL` and non-blocking; declared round-trip cost is an assumption, not a
  broker observation.
- Null control, placebo, gross/net cost decomposition, regime-bound evidence,
  realized expectancy, and execution-reality evidence are not claimed when
  they were not executed or cannot be bound to this experiment.
- Non-finite cost-stress values are explicit `MEASURED_INVALID` blocking
  results; they are never replaced with a favorable sentinel.

The correct conclusion remains `NO_TRADE` (`BLOCKED_INSUFFICIENT_DATA` for the
fixture campaign; `REGIME_DEPENDENT` / `BLOCK` for the REAL-data impulse
campaign), not an unsupported promotion.

## D. Forward observation and comparison

`data/sqlite/forward_observatory.db` currently contains:

- active sessions: `0`
- ticks/signals: `0/0`
- real-market ticks: `0`
- order submissions: `0`
- realized execution/PnL: `UNAVAILABLE`

This checkout therefore contains no real MT5 observation session. The
manifest honestly reports zero observations and is not populated from old or
synthetic samples.

The current paper/shadow/comparison export reports:

- paper records: `6`
- shadow intents: `10`
- canonical DEMO_FORWARD observations: `0`
- signal agreement: `MEASURED` at `0.5` for the available paper/shadow event
  alignment
- DEMO execution policy: `DISABLED`
- demo fills, slippage, latency, spread/fill/exit/PnL differences:
  `UNAVAILABLE` with reasons

The comparison label remains `DEMO never LIVE`; its policy block states that
DEMO_FORWARD is observation-only and DEMO_EXECUTION is disabled. No fill-shaped
row is interpreted as execution permission.

## E. Documentation and operator UI

README, the demo-forward protocol, MT5 setup instructions, release guidance,
governance, setup, operations, trading, and comparison views now distinguish:

- capability metadata versus product permission;
- DEMO_FORWARD observation versus DEMO_EXECUTION (disabled);
- measured values versus `UNAVAILABLE` / `INSUFFICIENT_EVIDENCE`;
- canonical SQLite evidence versus derived exports;
- DEMO versus LIVE, with LIVE always visibly locked.

The UI has no DEMO execution enable control. It presents the policy refusal,
readiness blockers, observation action, provenance, and next operator action.
Safety limits are shown as non-authorizing metadata.

## F. Verification boundary

Historical test counts in older release snapshots are not current-state evidence
and are intentionally not repeated here. Documentation convergence does not
claim a new research run, a real MT5 session, a browser screenshot run, or
claim-grade execution validation.

The repository's executable tests remain the authority for code behavior. A
real-environment MT5 observation run remains a separate operator requirement;
skipped or controlled-environment tests cannot satisfy it.

## G. Remaining blockers and staged roadmap

The first provenance-qualified REAL historical dataset is already acquired; the
next tasks must not send an operator back to that completed milestone. The
canonical sequence is maintained in [`docs/current_state.md`](current_state.md):

1. **Immediate operator/engineering milestone:** on a real Windows/MT5 demo
   terminal, run the readiness-gated `DEMO_FORWARD/OBSERVE_ONLY` protocol and
   retain canonical observation evidence. This is zero-order observation, not
   execution or a profitability test.
2. **Historical execution-realism milestone:** acquire or license continuous,
   provenance-qualified bid/ask/tick and broker execution-cost history where
   possible. This is the remaining R5 problem; the supplementary 23-window
   spread study is not sufficient.
3. **Research milestone:** only after improved evidence exists, rerun the
   existing preregistered impulse design unchanged, preserving its hypothesis,
   gates, locked partition and cumulative trial ledger.
4. **Later breadth milestone:** mature feature/regime research and add
   independent licensed populations/timeframes with new preregistration and
   falsification controls.
5. **Future validation/governance:** paper/shadow validation and candidate
   lifecycle review occur only after sufficient evidence; they do not create
   execution permission.

**What remains blocked:** R5 is `FAIL`/non-blocking; no real MT5 observation
session is present in repository evidence; no validated profitable edge exists;
the REAL result remains `REGIME_DEPENDENT / BLOCK`; `DEMO_EXECUTION` is authorized for the
DEMO account but not trading (`NO_TRADE` — no registered strategy has passed the research
gates); and `LIVE` remains locked.
