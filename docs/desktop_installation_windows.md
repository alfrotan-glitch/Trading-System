# Desktop Installation — Windows Clean Clone
Version 2026-09-16

## Prerequisites
- Windows 10/11 64-bit
- Python 3.11+ (https://www.python.org/downloads/ — check *Add python.exe to PATH*)
- git (https://git-scm.com/download/win)
- 2 GB free disk, 4 GB RAM, internet for pip

Verify:
```powershell
python --version  # Python 3.11.x
git --version
```

## Clone
```powershell
git clone https://github.com/alfrotan-glitch/Trading-System.git
cd Trading-System
```

## Setup (One Click)
PowerShell (recommended):
```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup_windows.ps1
```
Or batch fallback:
```bat
scripts\setup_windows.bat
```

What it does:
1. Checks Python/git, fails clearly if missing
2. Creates `.venv`
3. `pip install --upgrade pip`
4. `pip install -e ".[dev]"` (installs qts + dev deps)
5. Creates `data/raw, curated, sqlite, evidence, logs` dirs
6. Validates `qts --help` and `qts health`
7. Runs `pytest -q` quick tests

If it fails, see `docs/troubleshooting_windows.md`.

## Launch
```bat
scripts\run_qts.bat
```
- Sets `QTS_ENV=development`, `QTS_MT5_MODE=MOCK` if not already set
- Starts FastAPI at `127.0.0.1:8000` + native webview (pywebview) or browser fallback
- Health check: `http://127.0.0.1:8000/api/health` must return `system_status: Running`

Or manual:
```powershell
.\.venv\Scripts\python.exe -m qts.desktop.launcher
```

Double-click exe: after building `scripts\build_windows.bat`, double-click `dist\QTS.exe` (no repo path needed, no console). First launch shows **Setup Wizard**.

## Test
```bat
scripts\run_tests.bat
# or
.\.venv\Scripts\python.exe -m pytest tests -q
```

## Build Exe
```bat
scripts\build_windows.bat
```
Requires `.venv` + `pip install pyinstaller` (auto-installed). Uses `packaging/qts.spec`:
- Includes `src/qts/desktop/ui`, `configs`
- Hidden imports: api.server, health, state, risk demo limits, lifecycle gates, etc.
- Output `dist/QTS.exe` (one-file) or `dist/QTS/QTS.exe` (onedir). Verify `http://127.0.0.1:8000/api/health`.

## First-Run Wizard
See Setup Wizard in app: Environment, MT5 terminal path, broker/account, symbol, research dirs, risk ack, live LOCKED. Credentials via Windows Credential Manager or `.env` (gitignored), never repo.

## Uninstall
Delete folder + `.venv`. Configs in `configs/` not secrets.
