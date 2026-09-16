# Troubleshooting — Windows
Version 2026-09-16

## Setup Fails: Python not found
- Install Python 3.11+ from python.org, check *Add python.exe to PATH*, restart PowerShell, `python --version`.

## Setup Fails: git not found
- Install git from git-scm.com, restart.

## Setup Fails: pip install
- `.\.venv\Scripts\python.exe -m pip install --upgrade pip` then retry.
- Antivirus may block — allow.

## Launch Fails: .venv not found
- Run `scripts\setup_windows.bat` first from repo root.

## Launch Fails: API not healthy
- Port 8000 in use → `netstat -ano | findstr 8000` then `taskkill /PID <pid> /F`, or set `QTS_API_PORT=8001`.
- Firewall blocks → allow Python/MT5.

## Desktop Shows Blank / webview not installed
- `.\.venv\Scripts\python.exe -m pip install pywebview` then relaunch. Fallback browser will open `http://127.0.0.1:8000/` if webview missing.

## MT5 Checks Fail
See `docs/mt5_demo_setup.md` 14 checks. Common:
- *MT5 not installed*: install terminal, `pip install MetaTrader5`.
- *Terminal not running*: launch MT5 before QTS.
- *LIVE account to DEMO blocked*: create demo account.
- *Symbol not available*: MT5 Market Watch → Show All, verify XAUUSD vs GOLD.
- *Spread too wide*: wait London/NY session.
- *Stale tick*: check internet, MT5 Tools→Options→Server connected.

## Build Fails: PyInstaller not found
- `.\.venv\Scripts\python.exe -m pip install pyinstaller` or `scripts\build_windows.bat` auto-installs.
- Spec missing: `packaging\qts.spec` must exist, `src\qts\desktop\ui\index.html` must exist.

## QTS.exe Fails / SmartScreen
- Windows SmartScreen warns unsigned exe → *More info* → *Run anyway* (expected for dev build).
- Antivirus flags → allow.
- Run from `dist\QTS.exe` directly, not from zip without extracting.

## Data / Tests Fail
- No data versions → `python -m qts data synthetic --rows 5000 ...` then ingest.
- Tests fail → `.\.venv\Scripts\python.exe -m pytest tests -v`.

## Hard Paths / Secrets
- Never hardcode `C:\Users\...` — use relative `data/`, env vars.
- Never commit `.env` or `configs/live.yaml` — `.gitignore` covers. Use Credential Manager.

## Logs
- `logs/audit.jsonl` (redacted), `data/evidence/*.json`, `http://127.0.0.1:8000/api/health` for startup reason.

## Live Still Locked
Expected: `LIVE = LOCKED` until DSR/PBO/PSR/costs/regime/perturbation/null/placebo/forward/reconciliation/risk/human all pass. See `docs/release_readiness_report.md`.
