@echo off
REM QTS Trading System — Windows Setup (Batch fallback)
REM Usage: scripts\setup_windows.bat
REM Requires Python 3.11+, git

echo === QTS Trading System — Windows Setup (Batch) ===

where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
  echo ERROR: python not found. Install Python 3.11+ and add to PATH.
  exit /b 1
)

python --version
python -c "import sys; major, minor = sys.version_info[:2]; assert (3,11) <= (major, minor) < (3,14), f'Python {major}.{minor} not supported — supported 3.11/3.12/3.13 (3.14 not yet verified)'" 2>&1
if %ERRORLEVEL% NEQ 0 (
  echo ERROR: Python version not supported — install Python 3.11, 3.12, or 3.13 (Python 3.14 not yet verified; see docs/desktop_installation_windows.md)
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
  if %ERRORLEVEL% NEQ 0 (
    echo ERROR: venv creation failed
    exit /b 1
  )
) else (
  echo .venv already exists — reusing
)

echo Upgrading pip ...
.\.venv\Scripts\python.exe -m pip install --upgrade pip
if %ERRORLEVEL% NEQ 0 exit /b 1

echo Installing QTS ...
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
if %ERRORLEVEL% NEQ 0 (
  echo ERROR: pip install failed
  exit /b 1
)

if not exist data\raw mkdir data\raw
if not exist data\curated mkdir data\curated
if not exist data\sqlite mkdir data\sqlite
if not exist data\evidence mkdir data\evidence
if not exist logs mkdir logs

echo Checking data versions ...
if not exist data\manifests\manifest_20260916-010-572728d9.json (
  if exist data\fixtures\XAUUSD_1H_500.csv (
    echo Ingesting fixture XAUUSD_1H_500.csv ...
    .\.venv\Scripts\python.exe -m qts data ingest --path data/fixtures/XAUUSD_1H_500.csv --instrument XAUUSD --timeframe 1H
  )
)
if not exist data\raw\synthetic_XAUUSD_1m.csv (
  echo Generating synthetic 1m data ...
  .\.venv\Scripts\python.exe -m qts data synthetic --rows 2000 --out data/raw/synthetic_XAUUSD_1m.csv
)

echo Verifying qts CLI ...
.\.venv\Scripts\python.exe -m qts --help >nul
if %ERRORLEVEL% NEQ 0 (
  echo ERROR: qts CLI not working
  exit /b 1
)

echo Running quick tests ...
.\.venv\Scripts\python.exe -m pytest tests -q --tb=short
if %ERRORLEVEL% NEQ 0 (
  echo ERROR: tests failed (pytest exit %ERRORLEVEL%) -- Setup NOT complete.
  echo Fix failures and re-run setup_windows.bat (idempotent) -- see docs/troubleshooting_windows.md
  exit /b 1
)
echo Tests passed.

echo.
echo === Setup Complete === -- second run is idempotent, re-run to verify.
echo Next: scripts\run_qts.bat  — launch desktop
echo See docs\desktop_installation_windows.md
