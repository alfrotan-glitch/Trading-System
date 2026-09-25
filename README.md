# QTS — Quantitative Trading System

> **Gold research workstation. Live trading stays locked. There is no validated opportunity.**  
> A connection is not a price, and a price is not a trade.

---

## Product Mission

QTS is a gold research workstation. It can watch a demo account. It cannot open live trading.

There is no validated trading opportunity. Real-money trading stays locked. `REAL_CAPITAL_EXPOSURE` must stay 0. There is no multi-party unlock in this repository, and a demo result cannot create one.

Start with [`QTS_PROJECT_CONTROL.md`](QTS_PROJECT_CONTROL.md) and the [operating guides](docs/README.md). Research records in `docs/` are evidence, not operating instructions.

---

## Key Capabilities

1. **Executive Telemetry Dashboard:**  
   Instant, plain-English awareness across Market Connectivity, Validated Opportunities, Trading Permission, Risk Controls, and the single recommended next operator action.

2. **Rigorous Research & Event Study Framework:**  
   Pre-registered hypothesis testing with Deflated Sharpe Ratio (DSR) metrics, Holm multiple-testing adjustments, and zero synthetic quote smoothing.

3. **End-to-End DEMO Execution Lifecycle:**  
   Complete operational lifecycle: terminal connection, account identity pinning, symbol binding, quote freshness, the fail-closed pre-trade gate, atomic order submission, broker receipt, reconciliation, position close, and a durable journal. This is not a claim that a profitable strategy exists.

4. **Continuous Broker Reconciliation:**  
   Internal portfolio positions are reconciled against venue tickets after every order and position exit. Any quantity mismatch, ghost position, or unmapped fill immediately halts the engine.

5. **Durable Fail-Closed Controls:**  
   SQLite-persisted kill switches and stage machines that survive process restarts and ensure emergency stops remain in effect until deliberately cleared.

---

## Operating Modes

| Mode | Broker Linked? | Real Money? | Execution Capability | Safety Posture |
|:---|:---:|:---:|:---|:---|
| **DEVELOPMENT** | No / Mock | No | Code compilation, unit tests, mock sessions | Safe default |
| **PAPER** | No | No | Next-tick fill simulation with modeled slippage | Zero venue access |
| **SHADOW** | No | No | Records would-be intents. It does not submit, and it is not a live broker link. | Zero orders submitted |
| **DEMO_FORWARD** | Yes (MT5) | No | Real demo quote observation and logging | Zero orders submitted |
| **DEMO_EXECUTION**| Yes (MT5) | No | Controlled order submission on MT5 DEMO account | Fail-closed pre-trade gate |
| **LIVE** | Yes (MT5) | **Yes** | Real-money execution | **STRUCTURALLY LOCKED** |

---

## Quickstart

### 1. Prerequisites
- **Python:** 3.11, 3.12, or 3.13
- **Git**
- **MetaTrader 5 Terminal:** (Windows for broker IPC connection; Linux/macOS for research, API, and backtesting)

### 2. Installation
```bash
git clone https://github.com/alfrotan-glitch/Trading-System.git
cd Trading-System

python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

### 3. Launch Web Workstation
```bash
python -m qts.api.server
```
Navigate to `http://localhost:8901` in your browser.

### 4. Verify System Status via CLI
```bash
qts demo verify
```

---

## Repository Structure

```
├── configs/            # Declarable environment definitions (demo_forward, paper, dev)
├── data/
│   ├── evidence/       # Preregistration artifacts, validation registries, order journals
│   └── setup/          # Machine-local wizard setup (symbol maps, terminal paths)
├── docs/               # 10 Canonical product documentation guides
├── scripts/            # History acquisition, discovery audit, and setup tools
├── src/qts/
│   ├── adapters/       # MT5 broker adapter and IPC bridges
│   ├── api/            # FastAPI app and route modules under api/routes/
│   ├── backtest/       # Backtesting and simulation engine
│   ├── config/         # Machine-local path resolver and setup wizard
│   ├── data/           # Tick parsers and dataset loaders
│   ├── desktop/ui/     # Modern vanilla JS workstation UI (ES modules, semantic CSS)
│   ├── domain/         # Core trading value objects and execution modes
│   ├── execution/      # Demo session, pre-trade gate, autopilot, order journal
│   ├── lifecycle/      # Authority, stage machine, forward registry
│   ├── observability/  # Observation collectors, audit logs, event telemetry
│   ├── portfolio/      # Portfolio tracking, fill processing, cash management
│   ├── research/       # Hypothesis generation, impulse event study, DSR engine
│   └── risk/           # RiskEngine, exposure controls, persistent kill switch
└── tests/
    ├── adversarial/    # Security invariants, edge cases, and gate penetration suites
    ├── integration/    # Full lifecycle, CLI, autopilot loop, and session wiring tests
    ├── unit/           # Domain logic, risk calculations, and stage machine tests
    └── ui/js/          # Node-based UI unit and workstation tests
```

---

## Testing & Quality Assurance

Run the complete verification suite locally:

```bash
# 1. Static Analysis & Linting
ruff check src/ tests/
mypy src

# 2. JavaScript UI Tests
find src/qts/desktop/ui/js -name '*.js' -print0 | xargs -0 -n1 node --check
npm test

# 3. Python tests
# Default pytest runs tests/integration as well.
# --run-integration is only required for an explicit @pytest.mark.integration marker.
pytest
pytest tests/integration --run-integration
```

---

## Canonical Documentation

For detailed architecture, operational runbooks, and risk specifications, consult the canonical documentation:

- [**01. Product Overview**](docs/01-product-overview.md)
- [**02. System Architecture**](docs/02-architecture.md)
- [**03. Getting Started**](docs/03-getting-started.md)
- [**04. Operating QTS**](docs/04-operating-qts.md)
- [**05. Research & Validation**](docs/05-research-and-validation.md)
- [**06. Demo Trading Workflow**](docs/06-demo-trading.md)
- [**07. Risk Controls & Safety**](docs/07-risk-and-safety.md)
- [**08. Live Trading Governance**](docs/08-live-trading-governance.md)
- [**09. Troubleshooting & Diagnostics**](docs/09-troubleshooting.md)
- [**10. Developer Guide**](docs/10-developer-guide.md)

---

## License & Safety Notice

QTS is for research and a locked demo account. Live trading cannot be opened from this repository. Real-money exposure stays at `$0.00`.
