# 14 — Phased Implementation Plan

**Approach:** Foundations first — data integrity → research correctness → validation → execution → risk → observability → AI → UX. No dashboard before decisions are trustworthy.

## Phase 0 — Foundation (Week 1) ✅ Done

- [x] ADRs, architecture, domain model, lifecycles, data/execution/risk/validation/security/observability/testing docs
- [x] Repo scaffolding: `pyproject.toml`, `src/qts`, `tests`, `configs`, CI
- [x] Domain value objects (Pydantic, Decimal, UTC, Instrument lot_size/contract_size)
- [x] DataStore (Parquet+SQLite, manifests, quality_reports, synthetic) — quality gate enforced `write_bars(strict_quality=True)`, staleness/duplicate/tz checks
- [x] Deterministic event loop + Bar/Tick bus + next-bar `exec_bar` (open_time+1ms)
- [x] Strategy interface + SMA breakout + hold_long test harness
- [x] RiskEngine (per-trade lots×contract×price, step/min lots, exposure, daily loss, drawdown, kill-switch persisted SQLite)
- [x] ExecutionEngine + MatchingEngine + Paper/Replay/MT5Adapter (lots_to_mt5_volume, idempotency SQLite + placeholder, reconcile requires_suspend, NO_TRADE explicit)
- [x] Validation pipeline (real walk-forward splits, CPCV+PBO, perturbation ±10/20% re-run, stress run_stress multipliers, PSR/DSR Bailey, NOT_IMPLEMENTED blocks)
- [x] Experiment memory (SQLite lineage, Hypothesis/Experiment) + ResearchLoop (NullAgent → validate → AdversarialAgent)
- [x] Audit log (JSONL+SQLite, redaction) + Shipper (Local+S3 bucket/prefix/content-hash)
- [x] Lifecycle state machine + gates + NO_TRADE sentinel (NoTradeReason)
- [x] Unit + determinism + 20 adversarial tests (64 passed), CI, ruff/mypy

**Exit:** `qts backtest --strategy sma_breakout --data-version <ver>` deterministic (hash stable), risk vetoes lots-aware, reconciliation suspends on drift, validation fails closed on placeholder, audit durable.

## Phase 0.1 — Fidelity Patch (Phase 1 Audit Fix) ✅ This PR (907d8dc)

- next-bar proven via `test_next_bar_execution_no_lookahead` (hold_long bar_idx 1, price==next open), zigzag PF inf no longer mis-flagged
- Portfolio PnL weighted avg / partial 0.4 / flip + contract×lots formula + mark_to_market
- Idempotency persistent placeholder survives restart
- Kill persists across RiskEngine restarts
- Docs updated for lots, next-bar, PSR/DSR, CPCV, gates, shipper, NO_TRADE

## Phase 1 — Research Hardening (Week 2-3) ▲ In Progress

- [x] Adversarial suite (20 audits) + determinism
- [x] Purged/CPCV splits (cpcv_splits + embargo via walk_forward_splits), PBO blocking
- [x] Reconciler drift SUSPEND (`requires_suspend`) + kill persistence
- [x] MT5 symbol/lot mapping (MT5Adapter.lots_to_mt5_volume, 0.01 step, contract_size 100) — live send stubbed for Phase 2
- [x] Data quality hooks enforced (validate_bars on write, quality_reports SQLite, `qts data validate`)
- [x] Shipper local+S3, NO_TRADE explicit, AI loop (ResearchLoop)
- [ ] Feature Store (`fit`/`transform`, leakage guards, IC) — vectorized isolated, not for execution
- [ ] MT5 history ingest from terminal API (CSV path done, MT5 API polling next)
- [ ] Paper trading on live MT5 ticks (MT5DataFeed + PaperAdapter) — Paper on synthetic done, MT5 ticks pending terminal
- [ ] Property tests & failure injection (hypothesis already in tests/property for portfolio, need walk-forward + execution property)

**Exit:** Walk-forward + adversarial report for SMA ✅ + paper trading 1 week without drift (paper on synthetic done, MT5 paper pending)

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
