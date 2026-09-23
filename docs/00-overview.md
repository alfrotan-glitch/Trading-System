# Autonomous Quant Research & Trading System — Documentation Index

> **Principle:** *Preserve capital. Do less when uncertain. Every decision must be explainable through an audit trail.*

This directory contains the scientific, architectural, and engineering foundation for an enterprise-grade autonomous quant research & trading platform targeting XAUUSD on MT5, designed to be instrument-, broker-, and venue-pluggable.

> **Current-state authority:** Read [`current_state.md`](current_state.md) first for the verified repository status and forward roadmap. It supersedes stale snapshot wording without rewriting historical evidence artifacts.

## Documents

| # | Document | Purpose |
|---|----------|---------|
| 01 | [System Architecture](01-architecture.md) | Modular monolith, boundaries, event model, deployment |
| 02 | [Domain Model](02-domain-model.md) | Ubiquitous language, entities, value objects, aggregates |
| 03 | [Component Boundaries](03-component-boundaries.md) | Interfaces, dependency rules, plug points |
| 04 | [Research & Strategy Lifecycles](04-lifecycles.md) | IDEA → LIVE state machines, gates, evidence |
| 05 | [Data Architecture](05-data-architecture.md) | Provenance, versioning, normalization, quality |
| 06 | [Execution Architecture](06-execution-architecture.md) | Order lifecycle, reconciliation, MT5 adapter |
| 07 | [Risk Architecture](07-risk-architecture.md) | Independent risk authority, limits, kill switches |
| 08 | [AI / Agent Architecture](08-ai-agent-architecture.md) | Where AI helps, where it doesn't, agent roles |
| 09 | [Validation Methodology](09-validation-methodology.md) | Walk-forward, adversarial, stress, statistics |
| 10 | [Security Model](10-security-model.md) | Secrets, env isolation, audit, least privilege |
| 11 | [Observability Model](11-observability-model.md) | Audit trail, metrics, lineage |
| 12 | [Testing Strategy](12-testing-strategy.md) | Determinism, property, failure injection |
| 13 | [ADRs](13-adrs.md) | Technology selection, reuse/adapt/rewrite/reject |
| 14 | [Implementation Plan](14-implementation-plan.md) | Phased roadmap, milestones |
| 15 | [Assumptions & Unknowns](15-assumptions.md) | Explicit uncertainties, experiments needed |
| CS | [Current State & Research Roadmap](current_state.md) | Single current status authority and staged next steps |

## Reading Order

For reviewers: current state → 00 → 13 (ADRs) → 01 → 02 → 04 → 09 → 05 → 06 → 07 → rest.

## Current project posture

The foundation and provenance/quality work are strong; REAL XAUUSD 15m history
has been acquired; the preregistered REAL impulse research has run and returned
`REGIME_DEPENDENT / BLOCK`; event-level outcome transparency is implemented; and
FO-R1 observation infrastructure is engineered and hardened. A real Windows/MT5
observation session has not yet run, R5 continuous execution-cost history is
still FAIL/non-blocking, broad research is incomplete, no profitable edge is
validated, DEMO execution is authorized for the DEMO account but not trading (`NO_TRADE`), and LIVE is locked.

## Invariant

No strategy reaches LIVE without passing the full validation stack with recorded evidence. The system defaults to NO_TRADE.
