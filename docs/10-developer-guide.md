# 10. Developer Guide

## Engineering Standards

QTS adheres to strict software engineering standards designed for mission-critical trading infrastructure:

- **Type checking:** `mypy src` is the check. The project config is not `--strict`. Research modules still have pre-existing annotation findings; do not treat a partial path as a clean strict run.
- **Fail-Closed Error Handling:** Catch blocks must never swallow exceptions into permissive defaults.
- **Path Portability:** Paths must never rely on process current working directory (`os.getcwd()`). Always resolve via `qts.config.paths.state_root()` or `artifact_path()`.
- **Zero Hidden Invariants:** All assumptions are code-verified with explicit assertion errors or domain refusals.

---

## Directory Structure

```
src/qts/
├── adapters/       # BrokerAdapter, MT5, paper, shadow. Does not import execution.
├── api/            # FastAPI app and route modules under api/routes/
├── backtest/       # Backtesting engine. Uses RealisticPaperBroker, not a second paper adapter.
├── cli/            # Command package. Entry point is qts.cli:main.
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
mypy src

# 3. JavaScript Syntax Verification
find src/qts/desktop/ui/js -name '*.js' -print0 | xargs -0 -n1 node --check

# 4. JavaScript Unit Tests
npm test

# 5. Python tests
# Default pytest includes tests/integration. The 119 integration tests do not need a flag.
# The two default skips are tests/adversarial/test_impulse_lookahead.py for family IMP-VE-V
# when the fixed seed window has no events.
# Playwright browser tests skip at import when playwright is not installed. They are outside that count.
# `--run-integration` still runs tests/integration explicitly.
pytest
pytest tests/integration --run-integration
```
