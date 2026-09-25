# 10. Developer Guide

## Engineering Standards

QTS adheres to strict software engineering standards designed for mission-critical trading infrastructure:

- **Type Safety:** Full static typing with strict `mypy` validation across all source modules.
- **Fail-Closed Error Handling:** Catch blocks must never swallow exceptions into permissive defaults.
- **Path Portability:** Paths must never rely on process current working directory (`os.getcwd()`). Always resolve via `qts.config.paths.state_root()` or `artifact_path()`.
- **Zero Hidden Invariants:** All assumptions are code-verified with explicit assertion errors or domain refusals.

---

## Directory Structure

```
src/qts/
├── adapters/       # MT5 broker adapter, market data providers, IPC bridges
├── api/            # FastAPI REST backend, security middleware, schemas
├── backtest/       # Backtesting engine, trade accounting, fill simulation
├── config/         # Path resolution, configuration wizard, settings
├── data/           # History acquisition, tick parsers, parquet stores
├── desktop/        # Vanilla JS workstation UI (ES modules, semantic CSS)
├── domain/         # Value objects, instruments, orders, execution modes
├── execution/      # Demo session, pre-trade gates, autopilot, order journal
├── lifecycle/      # Authority, stage machine, forward validation registry
├── observability/  # Observation collectors, audit logs, event telemetry
├── portfolio/      # Portfolio tracking, fill processing, cash management
├── regime/         # Market volatility and regime classifiers
├── research/       # Hypothesis generation, impulse event study, DSR engine
├── risk/           # RiskEngine, exposure controls, persistent kill switch
└── validation/     # Walk-forward analysis, statistical testing, evidence
```

---

## Implementing a New Strategy

To register a new trading hypothesis:

1. **Preregister the Hypothesis:**
   Document the exact mathematical rules in `docs/` and generate a frozen parameter JSON.
2. **Implement Signal Provider:**
   Create a provider class conforming to `SignalProvider`:
   ```python
   class MyStrategyProvider:
       def __init__(self, params: dict[str, Any]) -> None:
           self.params = params

       def evaluate_quote(self, tick: Any) -> OrderIntent | None:
           # Pure function evaluation; never mutate parameters
           ...
   ```
   *Note: Providers exposing `.optimize()` or `.fit()` methods are rejected by the pre-trade gate.*
3. **Compute Parameter Hash:**
   Generate the canonical SHA-256 fingerprint of the parameter dictionary:
   ```bash
   python scripts/register_demo_research_policy.py --strategy MY-STRATEGY-V1 ...
   ```

---

## Running Verification Suites

Always run the full suite before submitting changes:

```bash
# 1. Linting and Code Style
ruff check src/ tests/

# 2. Type Checking
mypy src/qts/execution src/qts/lifecycle src/qts/api src/qts/config src/qts/domain src/qts/adapters src/qts/risk src/qts/cli.py

# 3. JavaScript Syntax Verification
node --check src/qts/desktop/ui/js/**/*.js src/qts/desktop/ui/js/views/*.js

# 4. JavaScript Unit Tests
npm test

# 5. Python Unit and Integration Test Suites
pytest tests/unit/
pytest tests/integration/ --run-integration
pytest tests/adversarial/
```
