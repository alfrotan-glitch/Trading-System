# Troubleshooting — Windows
Version 2026-09-16

## Setup Fails: Python not found or unsupported version
- Install **Python 3.11, 3.12, or 3.13** from python.org (check *Add python.exe to PATH*), restart PowerShell, `python --version`.
- **Python 3.14 is not yet verified** — `pyproject.toml` declares `requires-python = ">=3.11,<3.14"` and `scripts/setup_windows.ps1/.bat` fail clearly with `Python 3.14 not supported` if 3.14 is detected. Install a 3.11–3.13 build from python.org. Do not force `3.11+` if 3.14 is present; the version matrix has only been verified on 3.11–3.13 (Linux sandbox 3.11.2, 224 tests pass).

## Setup Reports “Setup Complete” But Tests Failed (Fail-Closed)
- Fixed in current release: `scripts/setup_windows.ps1` and `.bat` now check `pytest` exit code and **fail-closed** — on any test failure they print `ERROR: tests failed (pytest exit …) — Setup NOT complete` and exit 1, never printing `Setup Complete`. If you see `Setup Complete` but tests actually failed on an older checkout, update and re-run — second run is idempotent and will re-validate.

## Tests Fail With PermissionError WinError32 (SQLite Locked)
- Root cause: SQLite files inside `TemporaryDirectory` were left open (store not deterministically closed) — Windows cannot delete a directory containing an open file, unlike Linux. **Fixed**: every store (`SqliteParquetDataStore`, `RiskEngine`, `IdempotencyStore`, `ExperimentStore`, `PromotionLedger`, `LockedTestPartitioner`, `ForwardObservatory`, etc.) now has deterministic `close()` / context-manager (`with store:`) and `PRAGMA wal_checkpoint(TRUNCATE)` before cleanup; tests use `try/finally` or `with` and `tests/conftest.py` provides `SafeTemporaryDirectory` that closes tracked stores before `rmtree`. No retry loops or `ignore_cleanup` — if a store is still open, the test fails closed so the bug is surfaced.
- If you still see `WinError 32` after updating, ensure you are on the latest `arena/01a0aa13-trading-system` and that no antivirus is locking `data/sqlite/qts.db` or `data/curated` — allow the repo folder in antivirus.

## Tests Fail With StarletteDeprecationWarning httpx2 Not Installed
- Fixed: `pyproject.toml` `[project.optional-dependencies] dev` now includes `httpx>=0.27` and `anyio>=4.0` so a fresh `pip install -e ".[dev]"` provides the correct `TestClient` dependency for FastAPI/Starlette. The warning `Using httpx with starlette.testclient is deprecated` is harmless and suppressed; the error `httpx2 is not installed` no longer occurs.

## Setup Fails: Python not found
- Install Python 3.11, 3.12, or 3.13 from python.org, check *Add python.exe to PATH*, restart PowerShell, `python --version`.

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
