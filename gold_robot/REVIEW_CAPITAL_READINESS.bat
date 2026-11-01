@echo off
setlocal
cd /d "%~dp0"
echo ======================================================
echo QTS GOLD - INDEPENDENT CAPITAL READINESS REPORT
echo No live trading authorization - READ ONLY
echo ======================================================
set "PYTHON=python"
where py >nul 2>&1
if not errorlevel 1 set "PYTHON=py -3"
if "%PYTHON%"=="python" (
  where python >nul 2>&1
  if errorlevel 1 (
    echo ERROR: Python 3 is not installed. No report created.
    pause
    exit /b 1
  )
)
set "REPORT=%~dp0reports_local\capital_readiness\QTS_CAPITAL_READINESS.json"
%PYTHON% "%~dp0research\capital_readiness.py" --auto-discover "%~dp0reports_local\auto_runs" --capital 200 --output "%REPORT%"
if errorlevel 1 (
  echo ERROR: Readiness analysis did not complete. Do NOT deposit funds.
  pause
  exit /b 1
)
echo.
echo Report: "%REPORT%"
echo LIVE: LOCKED. This report is not approval for connected broker orders.
start "" notepad.exe "%REPORT%"
pause
exit /b 0
