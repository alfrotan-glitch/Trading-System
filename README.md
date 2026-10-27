# QTS — Quantitative Trading System

> **Gold research workstation. Live trading stays locked. There is no validated opportunity.**  
> A connection is not a price, and a price is not a trade.

---

## Windows: one file to start QTS Gold MT5

**Clone the canonical `main` branch and run `START_HERE.bat`:**

```powershell
git clone --branch main --single-branch https://github.com/alfrotan-glitch/Trading-System.git
cd Trading-System
.\START_HERE.bat
```

Choose **1** to install/compile the existing QTS Gold MT5 Expert Advisor and the read-only broker audit. Choose **2** to generate a clear local HTML/JSON readiness report. Choose **5** for four no-order Strategy Tester preset profiles (one per EntryStyle). These two choices require **WMMarkets MetaTrader 5 on Windows, not Python**. The report is stored locally under `gold_robot/reports_local/` and is not uploaded to GitHub.

After install, open `XAUUSD@` in MT5, refresh **Navigator → Scripts** and run `QTS_Broker_Preflight` on that chart. Then use option **2** for the report. When the broker/compile checks pass, use **MT5 Strategy Tester** with the user-observed minimum deposit **USD 3,000** and real ticks. The EA offers four `EntryStyle` research candidates; the optional tester-only opportunity census deliberately bypasses daily session limits **only in Strategy Tester**, not in connected accounts. **LIVE stays locked; none of these strategies has verified positive after-cost expectancy.**

[Quick Windows/Dari installation and tester guide](gold_robot/docs/WINDOWS_START_DARI.md) · [Technical research details](gold_robot/docs/MT5_3000_UNLIMITED_TESTER_DARI_2026-10-26.md)

**Two distinct launchers:** `START_HERE.bat` is the recommended MT5 Gold installation/report entry point. `ROBOT.bat` runs the separate QTS Python desktop and has its own gated DEMO controls. Do not mistake opening the Python desktop for installing the MT5 Expert Advisor.

---

## Product Mission

QTS is a gold research workstation. It can watch a demo account and submit
explicitly-confirmed DEMO orders through a fail-closed gate. It cannot open live
trading.

There is no validated trading opportunity. Real-money trading stays locked. `REAL_CAPITAL_EXPOSURE` must stay 0. There is no multi-party unlock in this repository, and a demo result cannot create one.

Start with [`QTS_PROJECT_CONTROL.md`](QTS_PROJECT_CONTROL.md) and the [operating guides](docs/README.md). Research records in `docs/` are evidence, not operating instructions.

**Release 1.0.1.** Production release of the research workstation:
reproducible dependencies (`requirements-prod.lock`), a hardened local API,
health/version probes, a container image, a systemd unit, and a one-command
release gate. It does not change the safety posture — see
[Production Deployment](docs/12-production-deployment.md) and the
[CHANGELOG](CHANGELOG.md).

---

## Key Capabilities

1. **Home Command Center:**  
   Instant, plain-English awareness of system status, Demo account connection, the gold price (shown only when fresh), trading opportunity (never invented — `NO_VALIDATED_EDGE` stays honest), money never at risk, and the single recommended next action.

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

## Start the Robot on Windows

**Double-click `ROBOT.bat` in the repository folder.** You get one simple
operator menu for the existing QTS engine:

1. **Open QTS desktop (default):** guided DEMO account setup, gold
   observation, practice and reports. Launching the desktop sends no order.
2. **Run authorized DEMO trading robot:** requires typing `DEMO` explicitly.
   The existing `qts demo verify` must succeed before the launcher calls the
   already-implemented supervised `qts demo run --confirm --risk-ack`.
   A failed broker, registration, account identity, risk or authority gate
   means **no robot execution**.

This is not a second trading engine or a shortcut around risk protection.
The tested 1-minute confirmed/anticipatory strategies lost money after
estimated costs. The newer counter-pressure candidate is not a proven
profitable strategy. No LIVE account can be traded by this repository.

Read [the short operator guide](docs/robot-operator-windows.md).

---

## Quickstart

### 1. Prerequisites
- **Python:** 3.11, 3.12, 3.13, or 3.14
- **Git**
- **MetaTrader 5 Terminal:** (Windows for broker IPC connection; Linux/macOS for research, API, and backtesting)

### 2. Installation
```bash
git clone https://github.com/alfrotan-glitch/Trading-System.git
cd Trading-System

python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -e ".[dev]"
python -m qts data bootstrap
```

`qts data bootstrap` establishes the research data version QTS verifies at
startup. Without it the first launch reports
`Blocked — verify_data: FAIL no data versions`. The step is deterministic and
idempotent (re-running reuses an already usable version). On Windows the
`scripts\setup_windows.bat` / `scripts\run_qts.bat` path below runs it for
you automatically.

`main` is the canonical product branch. Do not use historical `arena/*` branches.

Windows, from the cloned folder:

```bat
scripts\setup_windows.bat
scripts\run_qts.bat
```

The console must print `UI source: src\qts\desktop\ui`. The desk opens at `http://127.0.0.1:8000/`. There is no port 8901. `python -m qts.api.server` is not a launch command.

Manual launch, after the install above:

```bash
python -m qts.desktop.launcher
```

### 4. Verify System Status via CLI
```bash
qts demo verify
qts demo paths     # where every machine-local artefact resolves
```

### 5. Production Server
```bash
qts serve --host 127.0.0.1 --port 8000
curl -fsS http://127.0.0.1:8000/api/health/live
curl -fsS http://127.0.0.1:8000/api/version
```

`qts serve` is the supported production entry point. It binds loopback by
default, requires `QTS_ALLOW_REMOTE=1` before binding a public address, shuts down
gracefully and suppresses the server banner. Container, systemd and TLS-proxy
deployments are documented in
[12. Production Deployment](docs/12-production-deployment.md).

---

## Repository Structure

```
├── configs/            # Declarable environment definitions (demo_forward, paper, dev)
├── data/
│   ├── evidence/       # Preregistration artifacts, validation registries, order journals
│   └── setup/          # Machine-local wizard setup (symbol maps, terminal paths)
├── docs/               # 12 Canonical product documentation guides
├── scripts/            # History acquisition, diagnostics, and setup tools
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
# Fast developer suite (integration + research are intentionally opt-in)
pytest

# Full verification
pytest --run-integration --run-research

# Release gate (all of the above + build + packaged-wheel assertion)
scripts/verify_release.sh
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
- [**12. Production Deployment**](docs/12-production-deployment.md)

---

## License & Safety Notice

QTS is proprietary software; see [LICENSE](LICENSE). It is for research and a
locked demo account. Live trading cannot be opened from this repository and no
part of this licence grants permission to trade. Real-money exposure stays at
`$0.00`. Research figures produced on synthetic or demo data demonstrate
mechanism only — they are not evidence of edge.
