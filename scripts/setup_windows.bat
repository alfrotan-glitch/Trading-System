@echo off
REM QTS Trading System -- Windows Setup (Batch fallback)
REM Usage: scripts\setup_windows.bat
REM Requires Python 3.11-3.13, git
REM This file must stay pure ASCII: cmd.exe parses batch files in the OEM
REM codepage (cp437/cp850); UTF-8 characters become mojibake or parse errors.
REM Idempotent: safe to re-run; data bootstrap reuses existing usable versions.

setlocal
cd /d "%~dp0.."

echo === QTS Trading System -- Windows Setup (Batch) ===
echo Repository root: %CD%

where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
  echo ERROR: python not found. Install Python 3.11, 3.12 or 3.13 and add to PATH.
  exit /b 1
)

python --version
python -c "import sys; major, minor = sys.version_info[:2]; ok = (3,11) <= (major, minor) < (3,14); print('Python %d.%d %s' % (major, minor, 'OK' if ok else 'NOT SUPPORTED')); sys.exit(0 if ok else 1)"
if %ERRORLEVEL% NEQ 0 (
  echo ERROR: Python version not supported -- install Python 3.11, 3.12 or 3.13
  echo        (3.14 not yet verified; see docs/desktop_installation_windows.md)
  exit /b 1
)

where git >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
  echo ERROR: git not found. Install from https://git-scm.com
  exit /b 1
)

if not exist .venv (
  echo Creating virtual environment .venv ...
  python -m venv .venv
  if errorlevel 1 (
    echo ERROR: venv creation failed
    exit /b 1
  )
) else (
  echo .venv already exists -- reusing
)

if not exist .venv\Scripts\python.exe (
  echo ERROR: .venv\Scripts\python.exe not found
  exit /b 1
)

echo Upgrading pip ...
.venv\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 (
  echo ERROR: pip upgrade failed
  exit /b 1
)

echo Installing QTS (editable) ...
.venv\Scripts\python.exe -m pip install -e ".[dev]"
if errorlevel 1 (
  echo ERROR: pip install failed
  exit /b 1
)

echo Installing optional desktop window (pywebview) ...
.venv\Scripts\python.exe -m pip install pywebview
if errorlevel 1 (
  echo WARNING: pywebview not installed. scripts\run_qts.bat will open the browser instead.
)

if not exist data\raw mkdir data\raw
if not exist data\curated mkdir data\curated
if not exist data\sqlite mkdir data\sqlite
if not exist data\evidence mkdir data\evidence
if not exist logs mkdir logs

if not exist .env.example (
  echo # QTS Environment -- set QTS_ENV to development/paper/shadow/demo_forward/live> .env.example
  echo QTS_ENV=development>> .env.example
  echo QTS_MT5_MODE=MOCK>> .env.example
  echo Created .env.example
)

REM Data bootstrap -- deterministic, truthful, idempotent.
REM `qts data bootstrap` verifies a version is USABLE (manifest + curated parquet +
REM readable bars), never trusts a version row alone, ingests the SYNTHETIC fixture
REM with explicit provenance when nothing usable exists, and FAILS (exit 1) rather
REM than fabricating data if the fixture is missing or has zero usable bars.
echo Bootstrapping data ...
.venv\Scripts\python.exe -m qts data bootstrap
if errorlevel 1 (
  echo ERROR: data bootstrap failed -- no usable dataset could be established
  echo        (nothing was fabricated). See docs/troubleshooting_windows.md
  exit /b 1
)

if not exist data\raw\synthetic_XAUUSD_1m.csv (
  echo Generating synthetic 1m dev CSV ...
  .venv\Scripts\python.exe -m qts data synthetic --rows 2000 --out data/raw/synthetic_XAUUSD_1m.csv
  if errorlevel 1 (
    echo ERROR: synthetic dev CSV generation failed
    exit /b 1
  )
)

echo Verifying qts CLI ...
.venv\Scripts\python.exe -m qts --help >nul
if errorlevel 1 (
  echo ERROR: qts CLI not working
  exit /b 1
)
.venv\Scripts\python.exe -m qts health
if errorlevel 1 (
  echo ERROR: qts health check failed
  exit /b 1
)

echo Running tests (pytest -q) ...
.venv\Scripts\python.exe -m pytest tests -q --tb=short
if errorlevel 1 (
  echo ERROR: tests failed -- Setup NOT complete.
  echo Fix failures and re-run setup_windows.bat (idempotent) -- see docs/troubleshooting_windows.md
  exit /b 1
)
echo Tests passed.

echo.
echo === Setup Complete === -- second run is idempotent, re-run to verify.
echo Bootstrap data is SYNTHETIC (fixture, GBM seed=42) -- NOT real market history;
echo it never satisfies real-data requirements for demo_forward/live eligibility.
echo Next: scripts\run_qts.bat -- launch desktop
echo See docs\desktop_installation_windows.md
endlocal
