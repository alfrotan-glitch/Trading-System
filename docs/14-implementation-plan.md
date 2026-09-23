# 14 — Current Implementation and Research Roadmap

**Status:** current roadmap; use `docs/current_state.md` as the single status
summary. Historical phase labels from the original bootstrap plan are not used
to describe unfinished work. This document records what is complete and what
remains, without changing research mathematics, gates, execution boundaries or
provenance.

## 1. Completed foundation

The following are implemented and are not future tasks:

- modular-monolith architecture, domain model, lifecycle boundaries, canonical
  authorities and fail-closed defaults;
- SQLite + Parquet data storage, immutable manifests, provenance, strict OHLC
  quality validation and synthetic fixtures;
- deterministic bar replay and next-bar execution semantics;
- strategy interfaces, paper/shadow infrastructure, generic execution/risk/
  reconciliation boundaries and durable NO_TRADE/audit behavior;
- walk-forward, CPCV/PBO, PSR/DSR, perturbation, stress, null/placebo and
  cumulative-trial governance where implemented by the existing validation
  pipeline;
- bounded research campaigns, experiment lineage, research memory and
  adversarial research machinery;
- hardened FO-R1 observation boundary: canonical SQLite observatory, durable
  acquisition accounting, research snapshot support, integrity checks,
  long-session protections and structural order-free enforcement;
- REAL XAUUSD 15m data acquisition and provenance record:
  `20260918-010+8f120133-1ba57af7`, 26,038 rows, approximately 407 days,
  class `REAL`;
- execution of the unchanged preregistered REAL impulse study;
- event-level outcome transparency using existing measured directional outcomes.

These completed items must not be reintroduced as work for future agents. See
`docs/current_state.md` and the linked evidence for the current proof boundary.

## 2. Immutable current decision boundary

The REAL impulse result is:

```text
conclusion = REGIME_DEPENDENT
go_block   = BLOCK
```

R5 remains **FAIL/non-blocking** because continuous historical bid/ask,
measured spread, fill, latency and slippage evidence is unavailable in the
canonical dataset. The supplementary event-selected spread study is not an R5
replacement. The locked research partition remains untouched.

`DEMO_EXECUTION = DISABLED BY POLICY` is the shipped default; with a recorded owner authorization it resolves to `ENABLED_AUTHORIZED` for the DEMO account only, and every order still requires the staged progression and the 22-check pre-trade gate. `DEMO_FORWARD` is observation-only and structurally order-free. `LIVE = LOCKED`. No roadmap item changes these states.

## 3. Staged roadmap

### Stage A — Documentation/state convergence

**Completed in this documentation change.** `docs/current_state.md` is the
current-state authority; stale status/roadmap references are corrected and
historical reports are labelled as snapshots where they are retained.

### Stage B — Next engineering/operator milestone: real observation

On a real Windows/MT5 operator machine, run the existing readiness-gated
`DEMO_FORWARD/OBSERVE_ONLY` protocol. Preserve the canonical SQLite store,
durable acquisition ledger, snapshot/export lineage and order-free checks.

Acceptance is a real, provenance-bound observation session and its independently
reviewed evidence. It is not an order, fill, profitability result, or LIVE gate.
No real session is currently present in repository evidence.

### Stage C — Historical execution realism / R5

Acquire or license a provenance-qualified source with continuous historical
bid/ask/tick and, where available, broker-session/execution-cost fields. Register
it as a new immutable dataset or explicitly versioned evidence source. Do not
rewrite the current REAL mid history or infer continuous spread from OHLC.

### Stage D — Re-run existing research on improved evidence

After a valid R5-capable dataset exists, re-run the same preregistered impulse
hypothesis and design. Preserve definitions, costs, gates, locked partition
rules, cumulative trial ledger and REAL/SYNTHETIC lineage. Do not change the
hypothesis or search parameters merely to seek a positive result. The present
`REGIME_DEPENDENT / BLOCK` remains authoritative until a new run supersedes it
with its own artifact.

### Stage E — Research breadth

As a separate research program, mature the feature store, investigate causal
regimes, extend licensed history, add independent timeframes/instruments, and
register additional hypothesis families with falsification, null/placebo,
OOS and multiple-testing controls. Breadth is not a substitute for R5.

### Stage F — Paper and shadow validation

Only after a candidate hypothesis has sufficient research evidence, run paper
and shadow comparisons under declared immutable assumptions. Keep simulated fills,
shadow intents, DEMO observations and broker fills as separate evidence classes.
No paper or shadow result grants execution permission.

### Stage G — Candidate lifecycle

Only after the required research, cost, regime, OOS, forward, risk and
reconciliation evidence exists may human governance review a candidate
lifecycle transition. A positive event-level outcome row alone is insufficient.

### Stage H — Future governed execution

Any future DEMO execution or LIVE decision requires a separately approved human
policy change and all applicable gates. This roadmap does not add an order path,
enable DEMO execution or unlock LIVE.

## 4. Explicit non-goals

- Do not reacquire the already registered REAL history as if no dataset exists.
- Do not redo FO-R1 storage hardening that is already closed in the current
  observation boundary.
- Do not rerun the impulse study merely for documentation.
- Do not promote the supplementary spread windows into R5.
- Do not call event-study outcomes executed trades, fills or realized P&L.
- Do not interpret synthetic campaign artifacts as REAL research.
- Do not reset cumulative trial accounting or alter R1–R6, DSR, PBO or CPCV logic.

## 5. Roadmap ownership and evidence

| Milestone | Owner / environment | Required evidence | Current state |
|---|---|---|---|
| Documentation convergence | Repository maintainers | Current-state page and consistent references | **This mission** |
| Real observation session | Windows/MT5 operator | Canonical session, acquisition ledger, reviewed snapshot | **Pending** |
| R5 execution-cost history | Licensed data/research owner | Immutable continuous bid/ask/tick lineage | **Pending; R5 FAIL** |
| Unchanged research rerun | Research owner | New bound artifact and unchanged design/gates | **Future, after R5 evidence** |
| Breadth research | Research owner | New preregistration and independent datasets | **Future** |
| Paper/shadow validation | Research + governance | Separate simulation/intention comparison evidence | **Future, candidate-dependent** |
| Candidate/execution governance | Human approval + all authorities | Full gate evidence and explicit approval | **Not eligible** |
