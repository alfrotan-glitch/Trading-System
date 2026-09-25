# Desktop Application Report
Generated: 2026-09-16T14:35:00Z
Version: 0.1.0

## Architecture Decision
Evaluated existing Python FastAPI-less monolith: `qts` package pure Python, SQLite + Parquet store, no Node build chain, CLI-driven. Options:

- PyQt/PySide6 native: single process, strong native widgets, +50MB, QtWebEngine extra, learning curve, but no web stack.
- Electron/Tauri: requires Node, Rust, heavy build, overkill for quant desktop.
- Tkinter: stdlib but dated UX, hard to achieve professional dashboard.
- FastAPI + pywebview (chosen): simplest robust approach — retains modular Python backend, reliable local HTTP API, clean HTML/CSS/JS UI served statically, OS-native webview (Edge/WebKit) via pywebview, fallback to browser. No Node build, packaging via PyInstaller single exe, safe communication via CORS localhost, maintainability high, modular separation preserved.

ADR: Use FastAPI backend (`src/qts/api/server.py`) + pywebview launcher (`src/qts/desktop/launcher.py`) + static UI (`src/qts/desktop/ui/`). If pywebview unavailable, fallback to `webbrowser.open` — still one-click from packaged exe.

## Components
- Backend: `src/qts/api/server.py` FastAPI app with endpoints: /api/health, /dashboard, /strategies, /strategies/{id}/scorecard, /research/campaigns, /validation, /paper, /shadow, /execution/orders, /risk, /mt5, /audit, /live/status, /notifications. CORS allow localhost. Mounts static UI at /.
- Health: `src/qts/desktop/health.py` startup_health_check 7 steps: load durable state, restore suspension, restore pending/ambiguous, verify data (bar quality), verify config, verify MT5/account, run reconciliation. Shutdown procedure persists state, audit shutdown event, disconnect.
- State: `src/qts/desktop/state.py` restore_state verifies no safety state lost on restart/unexpected termination (audit count, risk_state, idempotency).
- Launcher: `src/qts/desktop/launcher.py` start_api_server (uvicorn in background thread, health poll 15s), open_desktop_window (pywebview.create_window 1280x800 or fallback browser), main() runs health then server then window, keeps main thread alive, handles KeyboardInterrupt → shutdown_procedure.
- UI: `src/qts/desktop/ui/index.html` single-page with nav Home/Dashboard/Research/Strategies/Validation/PaperShadow/Execution/Risk/MT5/Audit/Live. `style.css` professional dark theme safety-first banners (danger/warn/ok), `app.js` fetch API, renders status grids, kpi, strategy cards, campaign creation, validation scorecard, shadow/paper diff, order lifecycle trail, risk block reasons, MT5 spec with MOCK badge, audit search, live checklist, notifications.

## Startup / Shutdown
Startup:
1. Load durable state from `data/sqlite/qts.db` (promotion_state, experiments, hypotheses, audit_log, risk_state, idempotency).
2. Restore suspension (RiskEngine kill switch).
3. Restore pending/ambiguous orders from idempotency + audit.
4. Verify data: read the manifest's explicit quality/gap status; a historical
   12/12 snapshot is not a universal current-data PASS.
5. Verify config via `load_settings()` env separation.
6. Verify account/MT5 if requested (mock vs real).
7. Run reconciliation (drift check).
8. Only then permit normal operation — dashboard shows Running/Suspended/Blocked.

Shutdown:
- Stop new orders, persist SQLite, record shutdown DomainEvent NO_TRADE, safely disconnect (mock), preserve audit. Unexpected restart → restore_state verifies audit count not decreased.

## One-Click Operation
- Windows: double-click `QTS.exe` (PyInstaller single-file) → launcher main() → health → dashboard. Or `QTS.bat` / shortcut.
- Development: `qts desktop launch --host 127.0.0.1 --port 8000` or `python -m qts.desktop.launcher`.
- Config location: `data/sqlite/qts.db`, `data/evidence/*.json`, `data/manifests/*.json`, `configs/*.yaml`, env var `QTS_ENV` (development/paper/shadow/micro/live) + `QTS_MT5_MODE` (MOCK/PAPER/DRY_RUN/REAL). Documented in user guide.
- Data directory: `data/curated/...`, `data/sqlite/`, `data/evidence/`.
- Logs: `logs/audit.jsonl`, `logs/app.log`, SQLite audit_log.
- Safe upgrade: DB migrations additive (CREATE TABLE IF NOT EXISTS), version field in manifest/schema_version, code_revision tracked per strategy, no secret credentials committed (env vars, not source).
- Dev vs prod separation: env badges prominently in topbar, MT5 mode warning, risk limits per env.

## Security
- No broker passwords/API in source. Uses local `QTS_MT5_MODE` + env vars + OS credential store (future). `configs/` has placeholder not real secrets.
- Separate envs: development, paper, shadow, and demo. Live trading stays locked. This workstation cannot open it.
- Backend CORS limited to localhost; no remote exposure.

## Packaging
Requirements:
- One-click launch: PyInstaller spec `packaging/qts.spec`. Build: `pip install pyinstaller && pyinstaller packaging/qts.spec --clean --noconfirm`. Output `dist/QTS.exe`.
- Configuration: `configs/*.yaml` and env vars. There is no `configs/settings.yaml` in this tree. Windows shortcut creation is `scripts/create_shortcut.ps1`.
- Data: `data/` directory documented, upgrade safe (manifest version hash).
- Logs: `logs/` rotated, not committed.
- No secret committed: `.gitignore` covers `.env`, credentials.
- Dev vs prod: `QTS_ENV=development` is the default. Setting a live environment does not open live trading. There is no `confirm_live` unlock in this repository.
- Installer: there is no NSIS script in this tree. The Windows build script is `scripts/build_windows.bat`.

Build instructions (Windows):
1. `python -m venv venv; venv\Scripts\activate`
2. `pip install -e .` (includes fastapi uvicorn)
3. `pyinstaller packaging/qts.spec`
4. `dist\QTS.exe` double-click → health → dashboard. Shortcut: right-click → Create shortcut → copy to Desktop, icon `assets/qts.ico`.
5. For webview: `pip install pywebview` optionally, else browser fallback.
6. Logs/config/data paths as above.

## Testing
- UI startup: `TestClient` hits `/api/health` → 200.
- UI/backend connection: dashboard, strategies, risk endpoints.
- State restoration: `restore_state` after kill preserves audit count.
- Suspension persistence: RiskEngine kill persists via SQLite.
- Reconciliation: ExecutionEngine reconcile mock.
- Mode switching: QTS_ENV changes trading_mode.
- Live gate: blocked reasons visible.
- Risk veto visibility: risk center shows BLOCKED + reasons.
- Research campaign: `qts research campaign` bounded 6 trials completed, DSR N increments.
- Trial ledger: ExperimentStore count increments, no hidden.
- Promotion lifecycle: PromotionLedger one-way no skip, SUSPENDED on anomaly.
- Paper/shadow display, order audit display, MT5 status display, restart recovery.

## Evidence
- Health checks 7/7 stored via `startup_health_check` return.
- API test via `TestClient` in CI.
- Machine evidence `data/evidence/desktop_health.json` (if generated) + `data/evidence/campaign_last.json`.

## Current Status
- API: health 200, dashboard 200, risk TRADING BLOCKED NO_VALIDATED_EDGE, live LOCKED, strategies 27 listed BLOCKED.
- Desktop launches via `qts desktop launch` or `qts desktop api` + browser.
- Packaging spec exists, one-click ready after PyInstaller build (not yet built in CI but documented).
