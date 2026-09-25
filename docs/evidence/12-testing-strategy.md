# 12 — Testing Strategy

**Principle:** Do not accept “works on my machine.” Correctness before performance. No LIVE without tests gating.

## 12.1 Pyramid

```
            E2E (backtest→paper→reconcile)
          Integration (adapter vs Fake, DB)
        Property (invariants, fuzz)
      Unit (domain, risk, matching)
```

Coverage gate: 80% line, 100% of risk/execution state transitions.

## 12.2 Unit Tests (`tests/unit/`)

- **Domain:** `Bar` validation (high/low, timezone), `Order` state machine, `Money` decimals.
- **Risk:** each limit in isolation, boundary, veto reason exact.
- **Matching:** spread/slippage/latency/partial fill combos, deterministic.
- **Data:** normalization, deduplication, schema validation, provenance.
- **Lifecycle:** state transitions, gate checks.

Run: `pytest tests/unit -q`

## 12.3 Integration Tests (`tests/integration/`)

- **Data:** ingest CSV → Parquet → read back identical; manifest hash stable.
- **Backtest determinism:** same seed+data+code → identical trades & equity (hash equity curve).
- **Execution:** `FakeBroker` + `ExecutionEngine` + `RiskEngine` → order→fill→position→account flow.
- **Reconciliation:** inject drift (venue qty != local) → `ReconcileReport` detects, SUSPEND.
- **Validation pipeline:** run full pipeline on synthetic data → report.

Run: `pytest tests/integration -q --run-integration` (needs data fixtures).



## 12.4 Adversarial Tests (Phase 1 Audit `tests/adversarial/test_phase1_audit.py` — 20 checks)

Implemented to make system fail if leakage or fake validation exists:

- `test_next_bar_execution_no_lookahead`: hold_long queued at close N → fill at open N+1 (`bar_idx==1`, price==next open), not same-bar. Prevents zigzag leakage.
- `test_walk_forward_is_real_not_sliced`, `test_pbo_requires_real_computation`: missing `walk_forward_folds` / `cpcv_folds<5` → `NOT_IMPLEMENTED` blocks (`passed=False`).
- `test_psr_dsr_reference_values`, `test_dsr_documents_trials`: `PSR(1,100)∈(0.5,1)`, `DSR<PSR` for N>1, `DSR==PSR` when N=1, DSR ↓ with N when SR<benchmark, ↑ when SR>benchmark.
- `test_perturbation_requires_real_runs`, `test_stress_must_be_real_not_multiplied`: real re-runs required (fast ±5/10/20%, `run_stress` spreads 1.0/1.5/2.0 distinct), `PF×0.7` rejected, missing → `NOT_IMPLEMENTED`.
- `test_pnl_*`: long→flat, partial 0.4, flip long→short, fees/spread (MatchingEngine 10bps/5bps → price>close, fee 0.2), validated via `Portfolio` lots×contract invariants.
- `test_kill_switch_survives_restart_and_blocks`, `test_risk_uses_current_equity_not_stale`: SQLite persisted kill, new engine still `KILL_SWITCH_ACTIVE`, notional = `lots×contract×price` (XAUUSD 0.1 lot 100×2000=20000 veto).
- `test_idempotency_no_double_fill`: second submit `fills2==[]`, survives restart via persistent placeholder `REJECTED/duplicate-persistent`.
- `test_reconciliation_suspends_on_drift`: `QUANTITY_MISMATCH` → `requires_suspend=True`, `UNKNOWN_POSITION` likewise.
- `test_quantity_lots_to_notional`, `test_manifest_reproducibility`, `test_bar_interval_and_timezone`, `test_no_trade_on_uncertainty`: micro vs std contract 1 vs 100, checksum `sha256:`, tz/interval invariants, veto → `NO_TRADE` (empty fills, `EventType.NO_TRADE` emitted).

Run: `pytest tests/adversarial -v` (20 passed), included in `pytest -q` (64 passed).

## 12.4 Property-Based (`tests/property/` via Hypothesis)

- **Prices:** random bars always satisfy `high>=low`, conversion round-trip `Bar→DataFrame→Bar`.
- **Orders:** random intents after `RiskEngine.pre_trade` never exceed limits.
- **Matching:** random spreads/slippages never produce negative fill price.
- **Data:** random timestamps remain UTC after normalization.
- **Lifecycle:** random transitions never reach LIVE without gates.

Example:

```python
from hypothesis import given, strategies as st

@given(qty=st.decimals(min_value=0.01, max_value=10))
def test_risk_never_exceeds_max_quantity(qty):
    intent = OrderIntent(quantity=qty, ...)
    decision = risk_engine.pre_trade(intent, ctx)
    if decision.allowed:
        assert decision.quantity <= limits.max_quantity
```

## 12.5 Data Integrity Tests

- `test_no_lookahead`: feature at `t` computed from data ≤ `t` only (assert via timestamped fixtures).
- `test_purging`: purged overlap removed.
- `test_determinism`: two runs same hash.

## 12.6 Execution Simulation Tests

- `test_fill_at_ask_not_mid`: BUY fills at ask+slippage, not mid.
- `test_latency`: order submitted at bar close fills at `close_time + delay`.
- `test_partial_fill`: large qty vs volume → PARTIALLY_FILLED.
- `test_idempotency`: duplicate `client_order_id` returns same order, no double fill.

## 12.7 Reconciliation Tests

- `test_drift_detection_quantity_mismatch`
- `test_unknown_order`
- `test_reconnect_reconciles`

## 12.8 Failure-Injection

- `test_missing_data`: drop 5% bars → strategy emits NO_TRADE, no crash.
- `test_broker_timeout`: adapter timeout → OrderManager polls, SUSPEND.
- `test_kill_switch`: breach daily loss → next order vetoed, kill flag persisted.
- `test_network_partition`: disconnect → queue, reconnect → reconcile.

## 12.9 Risk-Limit Tests

- Parametrize over each `VetoReason`; ensure exact veto and audit emitted.
- `test_vol_aware_sizing_reduces_in_high_vol`

## 12.10 Kill-Switch Tests (Critical)

- `test_kill_cancels_pending_and_blocks_new`
- `test_kill_persists_across_restart`
- `test_kill_requires_explicit_reset`

## 12.11 Regression Tests

- Frozen fixtures: `data/fixtures/XAUUSD_1m_2024-01.parquet` + expected trades for `SMA(20)` strategy. CI fails if trades diverge without manifest version bump.

## 12.12 End-to-End

```
seed CSV → ingest → validate → run SMA experiment → ValidationReport → promote to PAPER (FakeBroker live ticks) → reconcile → check audit log completeness
```
Run nightly or on `main`.

## 12.13 CI

```yaml
# .github/workflows/ci.yml
- ruff check + format --check
- mypy --strict
- bandit -r src
- pytest tests/unit tests/property  # fast
- pytest tests/integration          # slower, with fixtures
- import-linter --check
```

No merge if any fail. Determinism test is required gate.

## 12.14 Local Repro

```bash
pip install -e ".[dev]"
pytest -q
qts data validate --version <ver>
qts backtest --strategy sma_breakout --data-version <ver> --seed 42 --determinism-check
```

## 12.15 Test Data

- Synthetic generators in `src/qts/data/synthetic.py` (GBM, regime-switching) for property tests.
- Small real sample `data/fixtures/` (1k bars) committed; large data (Parquet) gitignored, generated via `qts data synthetic --rows 100000`.
