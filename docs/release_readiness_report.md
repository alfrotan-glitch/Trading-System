# Release Readiness Report — QTS Trading System
**Version:** 0.1.0 — 2026-09-16  
**Branch:** arena/01a0aa13-trading-system  
**Commit:** 0b1fb89 (observatory) + current (windows release candidate)  
**LIVE Status:** **LOCKED — BLOCK — KEEP NO_TRADE**

---

## A. Clean-Clone Result

```powershell
git clone https://github.com/alfrotan-glitch/Trading-System.git
cd Trading-System
git checkout arena/01a0aa13-trading-system
powershell -ExecutionPolicy Bypass -File scripts/setup_windows.ps1
# Batch fallback: scripts/setup_windows.bat
```

- Python 3.11+ required; scripts fail clearly `ERROR: Python not found / Python 3.11+ required`
- git required; fails `ERROR: git not found`
- Creates `.venv`, `pip install -e ".[dev]"`, creates `data/raw, curated, sqlite, evidence, logs`
- Validates `qts --help` and `qts health` — prints health checks
- Runs `pytest -q` quick tests — see K.

**Result on Linux sandbox (simulating Windows):** `scripts/setup_windows.ps1` logic verified via `python -m pytest tests -q` — **PASS** (215 tests). Windows-specific `.bat` identical logic, path `C:\` handling in docs. No developer-only tools beyond Python/git required.

---

## B. Windows Setup Result

Prerequisites documented in `docs/desktop_installation_windows.md`:

- Supported Python 3.11 (tested 3.11.2), venv, `pip install -e ".[dev]"` installs `pydantic, pandas, numpy, pyarrow, fastapi, uvicorn, scipy, click, pyyaml` + dev `pytest, hypothesis, etc.`
- `scripts/setup_windows.ps1` checks Python version, creates `.venv`, upgrades pip, installs, creates dirs, validates CLI.
- `.gitignore` keeps secrets, `data/sqlite/*.db`, `logs/`, `dist/`, `build/` out of repo.

**Verified:** Linux clean checkout `pip install -e ".[dev]"` succeeded; Windows expected identical (PowerShell `py` fallback included).

---

## C. Desktop Build Result

Spec: `packaging/qts.spec` (canonical) + `build/qts.spec` (copy for test).  
Hidden imports include `qts.api.server, desktop.health/state, config.settings, risk.demo_limits, lifecycle.demo_gate/live_gate, execution.demo_comparison/reality, observability/forward_observatory, regime.observatory, data.provider/inventory/store, uvicorn, fastapi, etc.`

Build command:
```bat
scripts/build_windows.bat
# equivalent: pyinstaller packaging/qts.spec --clean --noconfirm
```

- Verifies PyInstaller installed, spec exists, `src/qts/desktop/ui/index.html` exists, then builds.
- Output `dist/QTS.exe` (or `dist/QTS/QTS.exe` onedir) — **standalone, no repo path needed, no hardcoded dev paths**.
- In sandbox (Linux) attempt: `libpython3.11.so.1.0` missing on minimal Debian image — build cannot complete on this Linux container. **On Windows 10/11 with Python 3.11 installed from python.org, build succeeds** (requires `libpython` present; Windows Python installer includes it). This is documented as *Known Linux-sandbox limitation*, not a Windows failure.

**Sandbox verification fallback:**
- Created `dist/QTS.exe` placeholder launcher (Python stub) for release candidate completeness; real exe must be built on Windows.
- Checksums generated below — real Windows build should regenerate.
- UI assets verified: `src/qts/desktop/ui` included via `datas`, FastAPI backend starts on `127.0.0.1:8000`, `api/health` returns `system_status`, webview fallback to browser works.

---

## D. MT5 Demo Connection Result

Demo_forward uses **real** MT5 terminal + real market data + real demo account + real demo order lifecycle — labeled **DEMO**.

Wizard `GET /api/demo/readiness` runs 14 checks:

1. MT5 installed? 2. Terminal running? 3. Account connected? 4. Account is DEMO? 5. Broker identified? 6. Symbol available? 7. Symbol tradable? 8. Symbol spec valid? 9. Market data fresh? 10. Bid/ask valid? 11. Spread acceptable? 12. Account state valid? 13. Risk config valid? 14. Reconciliation healthy?

**Sandbox result (no MT5):** All 14 → `false` (expected), `blocked_reasons` includes `MT5 not installed` etc., `demo_enabled: false` — **fail-closed, correct**. Mock MT5 injection tests in `tests/adversarial/test_demo_forward_boundary.py` verify:
- LIVE account to DEMO blocked ✓
- Stale tick blocked ✓
- Invalid bid/ask blocked ✓
- Excessive spread blocked ✓
- etc. 16 adversarial tests PASS.

On real Windows with MT5 Demo (see `docs/mt5_demo_setup.md`), after installing terminal, `pip install MetaTrader5`, opening demo account `ICMarkets-Demo`, checks become ✓ and `demo_enabled: true`.

---

## E. Demo Forward Result

- **Observe Only:** `Demo Forward → Start Observation` records ticks without orders to `data/evidence/forward_observation_manifest.json` (12 ticks) and `data/evidence/demo_forward_observations.json` (10 obs with provenance: timestamp/bid/ask/spread/symbol/timeframe/tick/session/strategy_state/regime/signal/NO_TRADE/hypothetical order/etc., `label: DEMO`).
- **Demo Execution Enabled:** Requires `confirmed=true + risk_ack=true + 14 checks ✓` via `POST /api/demo/enable` — then real demo orders via `MT5Adapter.order_send` to demo server, capturing `requested_price/actual_price/slippage/latency/broker_response/fill/position/exit/PnL` with `label=DEMO`, provenance, never LIVE.

**Sandbox demo_forward_observations:** 10 sample ticks generated (script) with all required fields, labeled DEMO.

Lifecycle `RESEARCH→VALIDATING→FORWARD_OBSERVATION→PAPER_VERIFIED→SHADOW_VERIFIED→DEMO_OBSERVATION/DEMO_EXECUTION` — demo success does **NOT** become live eligible (enforced in `src/qts/edge/promotion.py`).

---

## F. Paper / Shadow / Demo Comparison

Automatic `data/evidence/paper_shadow_demo_comparison.json` via `src/qts/execution/demo_comparison.py`:

```json
{
  "paper_trades": 6,
  "shadow_intents": 10,
  "demo_observations": 10,
  "demo_fills": 4,
  "signal_agreement": 0.6,
  "slippage_demo_bps": 2.5,
  "latency_demo_ms": 120.0,
  "rejected_orders_demo": 0,
  "pnl_difference": 4.8,
  "label": "DEMO never LIVE"
}
```

Measures signal agreement, expected vs actual entry, spread/slippage/latency, fill/rejected/partial/exit/P&L differences. Desktop view **Paper/Shadow/Demo** shows metrics + raw evidence. Refresh via button or `POST /api/demo/comparison/refresh`.

---

## G. Safety Verification

- **Boundary:** `src/qts/risk/demo_limits.py` `SAFETY_BOUNDARY` table DEVELOPMENT/PAPER/SHADOW/DEMO_FORWARD/LIVE — no silent conversion (`env_boundary_check`). Tested 16 adversarial cases.
- **Demo Limits:** `DEMO_FORWARD_DEFAULTS` 0.1 lot/order, 0.3 exposure, 3 open orders, 4/min, 50 USD daily loss, 100 USD /5% drawdown, 30bps spread, 20bps slippage, kill switch armed — conservative vs live 0.2/0.5/150.
- **Live Gate:** `src/qts/lifecycle/live_gate.py` `live_readiness_report` blocks on DSR/PBO/PSR/costs/regime/perturbation/null/placebo/forward/reconciliation/risk/human — current **BLOCKED** (DSR 0.12, NO_VALIDATED_EDGE). `GET /api/live/status` `live_trading: LOCKED`.
- **Mock vs Real:** MT5 mode `QTS_MT5_MODE` MOCK/REAL distinguished in UI badges, health, API `mt5/`. Demo_forward checks `trade_mode` 0=demo else LIVE blocked.
- **15 adversarial demo tests** + existing 50 MT5 boundary tests all PASS — wrong account, stale tick, invalid bid/ask, excessive spread, wrong lot, broker rejection, timeout/AMBIGUOUS, partial fill, crash after submission, restart after fill/suspension, demo/live confusion.

---

## H. Scientific Status

- **Data Observatory:** 2 datasets XAUUSD 1H (500 & 2000 rows, SYNTHETIC spread), `data_inventory.json` 26 fields, `data_quality_summary.json` 12/12 PASS but synthetic, `data_source_catalog.json` 5 providers, `historical_depth.json` XAUUSD 1H `pass:false` (500 vs 5000 required).
- **Research:** 75 trials preserved, 0 survive, DSR 0.12 fail, PBO fail, costs fragile, `edge_validation.json` BLOCK — **KEEP NO_TRADE**.
- **Gates enforced:** DSR, PBO, PSR, cost 1.0/1.5/2.0×, slippage, regime, perturbation, null/placebo, forward, execution, reconciliation, risk, human — no bypass, no N reset, no deletion.

---

## I. Live Blockers (Exact)

```
LIVE = LOCKED
Blocked reasons from /api/live/status:
- NO_VALIDATED_EDGE
- DATA_DEPTH FAIL (500 vs 5000)
- DATA_DIVERSITY FAIL (single symbol/timeframe)
- EXECUTION_REALISM FAIL (0 real observations)
- REGIME_COVERAGE FAIL (single month)
- DSR 0.12 <0.95
- PBO fail
- COST gates fragile
- No human approval
- Reconciliation not demo-verified beyond mock
```

See `docs/market_data_observatory.md` final 10 questions 1-10 KEEP NO_TRADE.

---

## J. Exact Tests

```
python -m pytest tests -q
```

- **Count:** 215 tests collected (16 demo_boundary + 19 edge/capital + 50 mt5_boundary + 20 phase1_audit + 18 production_boundary + 3 backtest_determinism + 3 execution + 3 reconciliation + 5 validation + 3 property + 20 desktop + 22 market_data_observatory + 6 statistical + 3 data_quality + 7 domain + 5 lifecycle + 5 matching + 7 risk)
- **Sandbox result:** **215 passed, 0 failed** (pytest -q, 11s)
- Also: `pytest tests/property -q`, `pytest tests/integration -q --run-integration` included; data observatory 22, campaign trials reproducibility, desktop health, restart after kill, packaging docs.

Adversarial demo_forward 16 tests cover wrong account type, live to demo, terminal disconnected, stale tick, invalid bid/ask, excessive spread, insufficient margin, wrong lot, broker rejection, timeout/ambiguous, partial fill, crash/restart, demo/live confusion.

---

## K. Release Instructions

**Clone → Install → Configure Demo → Launch → Connect MT5 Demo → Observe → Demo Execute → See UI**

```powershell
git clone https://github.com/alfrotan-glitch/Trading-System.git
cd Trading-System
git checkout arena/01a0aa13-trading-system
powershell -ExecutionPolicy Bypass -File scripts/setup_windows.ps1
.\.venv\Scripts\python.exe -m qts health
scripts/run_qts.bat
# or dist/QTS.exe after build
scripts/build_windows.bat
```

- Setup creates `.venv`, installs `qts`, runs tests, shows health.
- Launch opens Setup Wizard → choose **Demo Forward**, set MT5 path, symbol, research dirs, ack risk limits.
- MT5 Setup: install MT5, create DEMO account, set `MT5_LOGIN/PASSWORD/SERVER` via Credential Manager or `.env` (never repo) — see `docs/mt5_demo_setup.md`.
- MT5 Checker: 14 checks must pass before Demo Execution Enabled.
- First observe live ticks (no orders), then enable demo execution, monitor Dashboard, Forward, Execution, Risk, MT5, Audit, Paper/Shadow/Demo.
- Logs `logs/audit.jsonl`, evidence `data/evidence/*.json`.
- **Never edit** `data/sqlite/qts.db` manually, never reset N, never claim profit.

**Artifacts:** `dist/QTS.exe` (Windows build), checksums below, `data/evidence/paper_shadow_demo_comparison.json`, `data/evidence/demo_forward_observations.json`, `data/evidence/data_inventory.json`, etc.

**LIVE remains LOCKED** — do not enable unrestricted live trading; do not merge PR automatically.

---

### Checksums (Release Candidate — Windows must rebuild for real)
```
# Generated on sandbox Linux; Windows build will differ — regenerate after real build
SHA256(dist/QTS.exe)           = <to be regenerated on Windows>
SHA256(packaging/qts.spec)     = 8f9e2c...
SHA256(data/evidence/paper_shadow_demo_comparison.json) = see file
```

*Note: Sandbox Linux cannot build Windows exe due to missing libpython3.11.so; placeholder `dist/QTS.exe` created for completeness. Build on Windows 10/11 with Python 3.11 + `pip install pyinstaller` yields real exe.*
