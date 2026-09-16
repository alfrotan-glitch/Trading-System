# 14 — Phased Implementation Plan

**Approach:** Foundations first — data integrity → research correctness → validation → execution → risk → observability → AI → UX. No dashboard before decisions are trustworthy.

## Phase 0 — Foundation (Week 1) ✅ This Repo

- [x] ADRs, architecture, domain model, lifecycles, data/execution/risk/validation/security/observability/testing docs
- [ ] Repo scaffolding: `pyproject.toml`, `src/qts`, `tests`, `configs`, CI
- [ ] Domain value objects (Pydantic, Decimal, UTC)
- [ ] DataStore (Parquet+SQLite, manifests, quality gates, synthetic)
- [ ] Deterministic event loop + Bar/Tick bus
- [ ] Strategy interface + SMA breakout example
- [ ] RiskEngine (per-trade, exposure, daily loss, kill-switch)
- [ ] ExecutionEngine + MatchingEngine + Paper/Replay adapters
- [ ] Validation pipeline (splits, walk-forward, stress, perturbation, Monte Carlo, DSR/PBO)
- [ ] Experiment memory (SQLite lineage)
- [ ] Audit log (JSONL+SQLite)
- [ ] Lifecycle state machine + gates
- [ ] Unit + determinism tests, CI, ruff/mypy

**Exit:** `qts backtest --strategy sma_breakout --data-version <ver>` deterministic, risk vetoes work, audit log complete, tests green.

## Phase 1 — Research Hardening (Week 2-3)

- [ ] Feature Store (`fit`/`transform`, leakage guards, IC)
- [ ] Purged/CPCV splits, embargo
- [ ] Adversarial suite (leakage, cost sensitivity, regime)
- [ ] MT5 history ingest (CSV + MT5 API), session metadata
- [ ] Paper trading on live MT5 ticks (MT5DataFeed + PaperAdapter)
- [ ] Reconciler (drift detection, SUSPEND)
- [ ] Property tests, failure injection

**Exit:** Walk-forward + adversarial report for SMA; paper trading 1 week without drift.

## Phase 2 — Live Readiness (Week 4-5)

- [ ] MT5Adapter (live) with ZeroMQ/EA bridge, symbol/lot mapping, error mapping
- [ ] Shadow mode (live vs paper divergence metrics)
- [ ] Kill-switch persistence + manual reset
- [ ] SecretsProvider (Vault/1Password), env isolation
- [ ] Security audit (bandit, redaction)
- [ ] Docs for `LIVE_CANDIDATE` promotion checklist

**Exit:** SHADOW 2 weeks, divergence < threshold, kill-switch tested, security review PASS.

## Phase 3 — Intelligence (Week 6-8)

- [ ] Regime detectors (vol quantile, HMM) as hypotheses, WFA-conditioned evaluation
- [ ] ResearchAgent (Null + LLM-optional) + AdversarialAgent
- [ ] Portfolio vol-aware sizing, correlated exposure
- [ ] Experiment memory semantic search (embedding)
- [ ] Observability dashboard (read-only, derived from audit)

**Exit:** Regime-conditioned validation shows measured uplift or rejection with evidence; agents produce hypotheses that pass validation at > random baseline.

## Phase 4 — Scale & Polish (Week 9+)

- [ ] DuckDB/Postgres option, Timescale if needed (behind DataStore)
- [ ] Rust engine spike (behind Engine interface, benchmark)
- [ ] Additional instruments/venues (XAGUSD, EURUSD) to prove plugability
- [ ] Monte Carlo price paths, White's Reality Check
- [ ] Chaos tests, latency profiling, alerting (webhook)

**Exit:** Multi-instrument backtest, no core change for new venue; performance profile justifies or rejects Rust.

## Milestones & Gates

| Milestone | Gate | Evidence |
|-----------|------|----------|
| M1: Deterministic backtest | CI green, determinism hash | `tests/integration/test_determinism.py` PASS |
| M2: Validation report | Full pipeline on synthetic + real | `ValidationReport` JSON artifact |
| M3: Paper week | No drift, audit complete | `ReconcileReport` 7 days clean |
| M4: Shadow week | Live/paper delta < thresh | Divergence metrics |
| M5: LIVE_CANDIDATE | Manual approval + risk approved | Signed `ValidationReport` + `RiskLimits` |
| M6: LIVE | Kill-switch armed, reconciler live | Health checks green |

## Risk & Mitigation

| Risk | Mitigation |
|------|------------|
| MT5 API instability | Adapter isolation + Fake/Paper + reconciliation |
| Overfitting despite WFA | DSR/PBO + adversarial + holdout discipline |
| Scope creep to microservices | Modular monolith, interfaces first, distribution only with evidence |
| AI hallucinating edge | AI is hypothesis only, never bypasses validation |

## What We Will NOT Do

- No live capital before M5 gate.
- No new instrument before XAUUSD validation passes.
- No dashboard before audit log.
- No performance optimization before correctness tests.
