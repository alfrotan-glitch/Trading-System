# Autonomous Quant Research & Trading System — Documentation Index

> **Principle:** *Preserve capital. Do less when uncertain. Every decision must be explainable through an audit trail.*

This directory contains the scientific, architectural, and engineering foundation for an enterprise-grade autonomous quant research & trading platform targeting XAUUSD on MT5, designed to be instrument-, broker-, and venue-pluggable.

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

## Reading Order

For reviewers: 00 → 13 (ADRs) → 01 → 02 → 04 → 09 → 05 → 06 → 07 → rest.

## Invariant

No strategy reaches LIVE without passing the full validation stack with recorded evidence. The system defaults to NO_TRADE.
