@echo off
REM QTS Trading System -- Canonical Launcher
REM Double-click this file OR run from PowerShell: .\scripts\run_qts.bat
REM First run: QTS sets itself up automatically (venv, dependencies, data).
REM There is ONE way to launch QTS: this file. (launch_desktop.bat merely
REM forwards here so older shortcuts keep working.)
setlocal
cd /d "%~dp0.."

REM --- Automatic first-run setup (idempotent; safe to re-run) ---
if not exist .venv\Scripts\python.exe (
  echo First run: setting up QTS ^(venv, dependencies, data bootstrap^)...
  echo This happens once. Leave this window open until it finishes.
  call "%~dp0setup_windows.bat"
  if errorlevel 1 (
    echo.
    echo ERROR: QTS setup failed, so the desktop cannot start.
    echo Fix the problem shown above, then run scripts\run_qts.bat again.
    pause
    exit /b 1
  )
)

REM Fail clearly if prerequisites still missing
if not exist .venv\Scripts\python.exe (
  echo ERROR: .venv\Scripts\python.exe not found even after setup.
  echo See docs\troubleshooting_windows.md
  pause
  exit /b 1
)

if not exist src\qts\desktop\launcher.py (
  echo ERROR: src\qts\desktop\launcher.py not found. Run from repository root.
  pause
  exit /b 1
)

REM Default to development MOCK -- no real trading
if "%QTS_ENV%"=="" set QTS_ENV=development
if "%QTS_MT5_MODE%"=="" set QTS_MT5_MODE=MOCK

echo === QTS Trading System -- Desktop ===
echo Environment: %QTS_ENV%   MT5: %QTS_MT5_MODE%
echo Starting FastAPI + webview...
echo UI source: src\qts\desktop\ui

.venv\Scripts\python.exe -m qts.desktop.launcher
if errorlevel 1 (
  echo.
  echo Desktop exited with error %ERRORLEVEL%. See logs\audit.jsonl
  pause
)
endlocal
