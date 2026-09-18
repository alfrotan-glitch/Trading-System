# User Operation Guide
Version: 0.1.0 — QTS Trading System Desktop

## Installation (Windows)
1. Download `QTS.exe` (or build via `pyinstaller build/qts.spec`).
2. Place in `C:\QTS\` or any folder.
3. Double-click `QTS.exe` — no Command Prompt needed.
4. First run creates `data/sqlite/qts.db`, `data/evidence/`, `logs/`.
5. Optional: right-click `QTS.exe` → Create shortcut → drag to Desktop → set icon `assets/qts.ico`.

Developer/Advanced CLI (secondary):
- Install Python 3.11+, `pip install -e .`, then `qts --help`, `qts desktop launch`, `qts edge validate`, `qts research campaign`.

## Configuration Location
- Config: `configs/settings.yaml` (copy from `configs/settings.example.yaml`), env vars override. `QTS_ENV` (development/paper/shadow/micro/live), `QTS_MT5_MODE` (MOCK/PAPER/DRY_RUN/REAL). No secrets in repo — set via env or OS credential store.
- Data: `data/manifests/*.json`, `data/curated/instrument=.../version=.../part-0.parquet`, `data/sqlite/qts.db`.
- Logs: `logs/audit.jsonl`, `logs/app.log`, SQLite `audit_log` table.
- Evidence: `data/evidence/edge_validation.json`, `data/evidence/campaign_last.json`, `data/evidence/paper_trades.json`, `data/evidence/shadow_intents.json`.

## Launch
Double-click → startup health check runs (7 steps):
Load state → Restore suspension → Restore pending orders → Verify data → Verify config → Verify MT5 → Reconciliation → Dashboard.

Home screen shows System Status:
SYSTEM STATUS ● Running / Stopped / Suspended / Blocked
MT5 ● Connected / Disconnected (MOCK badge)
MARKET DATA ● Healthy / Stale / Blocked
RISK ● Healthy / Suspended
RECONCILIATION ● Healthy / Drift Detected
STRATEGY ● current version/lifecycle
TRADING MODE ● Research / Backtest / Paper / Shadow / Dry Run / Micro / Live
LIVE STATUS ● LOCKED / ELIGIBLE / BLOCKED

Safety banners on top — most important first.

## Dashboard
- Equity, balance, unrealized/realized PnL, drawdown, exposure, open positions, market status, spread, account state, current strategy, regime, latest decision/order/fill/risk veto, reconciliation.
- If BLOCKED, banner explains reason (e.g., NO_VALIDATED_EDGE, MISSING_MARKET_PRICE, RECONCILIATION_DRIFT).

## Research Center
- Create campaign: select family (trend/breakout/mean_reversion/momentum/volatility), symbol/timeframe, bounded param space (defaults to bounded), max trials (≤100), start validation → progress view → completed trials → inspect rejected vs surviving → open full evidence (scorecard, WFE, PBO, DSR, etc.).
- Display: trial count, current trial, pass/fail, PBO, DSR, OOS metrics, drawdown, expectancy, cost sensitivity, regime performance.
- Profitable backtest always shows gates — never hide failures.

## Strategy Library
Each card: Strategy, Version, Symbol, Timeframe, Lifecycle (RESEARCH/BLOCKED/CANDIDATE/VALIDATED/FORWARD_TEST/PAPER_VERIFIED/SHADOW_VERIFIED/MICRO_ELIGIBLE/LIVE_ELIGIBLE), OOS Sharpe, DSR, PBO, Expectancy, Drawdown, Cost tolerance, Last validation, Decision.

## Backtest/Validation View
Open validation run: equity curve, drawdown, trades, returns, costs, spread/slippage, WFE, CPCV, PBO, PSR, DSR, perturbation, regime, null/placebo, economic edge. Every metric shows definition/source/context.

## Paper/Shadow Center
PAPER: simulated positions, fills, PnL, drawdown, execution statistics.
SHADOW: intent count, would-be trades, estimated fills, skipped reasons, shadow vs paper discrepancy (avg 144 bps in current evidence indicates paper not live).

## Execution Center
Lifecycle: INTENT → RISK → SUBMISSION → ACCEPTED → PARTIAL → FILLED or REJECTED/CANCELLED/AMBIGUOUS. Click order → full audit trail.

## Risk Center
Hard limits: risk per trade, max exposure, daily loss, max drawdown, spread/slippage/stale limits, order frequency, consecutive-loss protection, kill switch, reconciliation state. Shows exactly why blocked, e.g.:
TRADING BLOCKED Reason: MISSING_MARKET_PRICE or RECONCILIATION_DRIFT or NO_VALIDATED_EDGE.

## MT5 Center
Connection, terminal status, account, broker, symbol, contract size, min/max volume, volume step, digits, tick size, spread, market session, margin/free margin, server time, data freshness. Clearly distinguishes MOCK/PAPER/DRY_RUN/REAL MT5. Warning if MOCK.

## Audit/Evidence Center
Browse decisions, risk vetoes, orders, fills, reconciliations, suspensions, validation results, strategy promotions, data manifests, experiment trials. Search/filter.

## Live Control
Large explicit state: LIVE TRADING LOCKED. Shows every unmet prerequisite:
LIVE NOT AVAILABLE ✗ Validated edge ✗ Forward observation ✓ Risk configuration ✓ MT5 connectivity ✓ Reconciliation ✗ Human approval
Never trick "MT5 connected" = safe. Enabling live requires explicit confirmation and all gates (even if eligible, button disabled unless explicit).

## Notifications / Alerts
Persistent until acknowledged: trading suspended, stale data, reconciliation drift, account unavailable, broker disconnect, ambiguous order, daily loss/drawdown thresholds, strategy invalidated, validation failure, live gate blocked. Shown bottom-right.

## Startup / Shutdown
See desktop report startup 8 steps, shutdown 4 steps, state preserved across unexpected restart (SQLite durable). Do not reset safety state on restart.

## One-Click Operation
Documented above — double-click → health → dashboard. No Python paths/venv needed for normal usage.

## Security
- No passwords in source.
- Separate envs: dev/paper/shadow/micro/live via `QTS_ENV`.
- UI shows active env prominently.

## Troubleshooting
- If health shows Blocked → check data quality, logs, risk kill.
- If MT5 Disconnected and mode MOCK → expected for dev.
- If live shows LOCKED → check checklist, do not force.
- For CLI advanced: `qts health`, `qts audit query`, `qts edge validate --strategy X --data-version Y --strict`, `qts research campaign`.

## Support
Logs in `logs/`, evidence in `data/evidence/`, config in `configs/`, DB in `data/sqlite/qts.db`.
