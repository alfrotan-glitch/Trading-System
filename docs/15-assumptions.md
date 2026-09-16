# 15 — Assumptions & Unknowns

Explicitly stating what we assume, what we don't know, and what experiments will resolve.

## 15.1 Assumptions (with Confidence)

| # | Assumption | Confidence | How to Falsify |
|---|------------|------------|----------------|
| A1 | XAUUSD has microstructure where spread/slippage materially impacts edge (3-10 bps) | High | Measure live spread distribution vs backtest assumption; stress test |
| A2 | MT5 `order_send` + polling can be reconciled reliably for XAUUSD (no hidden state) | Medium | SHADOW mode drift metrics over 2 weeks |
| A3 | Deterministic Python event loop suffices for 1m/1H XAUUSD (no μs need) | High | Profile event loop at 1m tick rate; if >10ms/event, Rust justified |
| A4 | Walk-forward 12m/3m captures regime change for XAUUSD | Medium | Compare WFE vs 6m/1m, 24m/6m; CPCV PBO |
| A5 | Purged/embargo horizon = label horizon prevents leakage for our labels | High | Leakage injection tests |
| A6 | DSR assumes we track N trials correctly via ExperimentStore | Medium | Audit N counting; if N undercounted, DSR optimistic |
| A7 | Single SQLite+Parquet suffices for years of 1m XAUUSD | High | Load test: 5 years × 1m = ~2.6M bars, <100MB Parquet |
| A8 | Kill-switch + reconciler prevents runaway orders | High | Failure-injection tests |
| A9 | Regime classification may not improve returns; treat as hypothesis | High | Regime-conditioned WFA uplift test |
| A10 | LLM hypotheses outperform random only if validated; not assumed | Low (unknown) | A/B `NullAgent` vs `LLMAgent` pass rate |

## 15.2 Unknowns (Need Experiments)

| # | Unknown | Experiment |
|---|---------|------------|
| U1 | What is live XAUUSD spread distribution on target broker (session/time dependent)? | Live tick capture 2 weeks, histogram per session |
| U2 | What slippage/latency does MT5 bridge impose (py vs ZMQ vs EA)? | Benchmark submit→ack→fill latency; SHADOW delta |
| U3 | What `spread_bps` + `slippage_bps` makes SMA breakout unprofitable? | Cost-stress sweep in validation |
| U4 | What walk-forward config maximizes OOS relevance for XAUUSD? | Grid over train/test/step, compare PBO |
| U5 | Does vol-aware sizing improve risk-adjusted returns for XAUUSD? | Backtest with/without, WFA OOS Sharpe |
| U6 | Does any regime detector provide conditional edge? | Regime-conditioned WFA for 3 detectors |
| U7 | What DSR threshold maps to live profitability for XAUUSD? | Track live vs DSR over many strategies |
| U8 | How many trials N have we actually run (multiple-testing)? | Instrument ExperimentStore to count all runs, including rejected |
| U9 | Can we detect leakage automatically (e.g. feature uses future bar)? | Adversarial leakage validator on synthetic leakage fixture |
| U10 | What drawdown distribution to expect for validated strategies? | Monte Carlo trade reshuffle on validated strategies |

## 15.3 Explicit Non-Assumptions

- We do **not** assume any edge exists for XAUUSD. The system must be capable of concluding NO_TRADE and of rejecting all hypotheses.
- We do **not** assume backtest profitability implies live profitability.
- We do **not** assume regime classification helps.
- We do **not** assume AI generates valid hypotheses.
- We do **not** assume MT5 fills at requested price.

## 15.4 Decisions Deferred

| Decision | Defer Until | Trigger |
|----------|-------------|---------|
| Rust engine | After profiling | Python loop > threshold or live latency breach |
| Postgres/Timescale | After multi-user or >10M bars/s | SQLite bottleneck observed |
| Full L2 simulator | If spread model insufficient | Live/paper divergence > X |
| CEX/IB adapters | After XAUUSD/MT5 validated | New instrument request |
| Dashboard framework | After audit log stable | M3 paper success |

## 15.5 Risks If Assumptions Wrong

| If Wrong | Impact | Fallback |
|----------|--------|----------|
| A2 (MT5 unreliable) | Drift, missed fills | Switch broker adapter (interface), paper-only |
| A3 (Python too slow) | Missed ticks, stale signals | Rust engine behind interface, no strategy change |
| A6 (N undercounted) | DSR overconfident | Inflate N, require higher Sharpe, add SPA test |

## 15.6 How We Track

- Assumptions linked to `ValidationReport` thresholds (e.g. WFE, DSR) — reviewers can adjust without code.
- Unknowns become `Experiment` entries with `hypothesis: "U1: spread is X"` and are prioritized in research backlog.
- Every assumption review is an ADR amendment with evidence.
