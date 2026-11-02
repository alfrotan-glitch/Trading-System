@echo off
REM QTS Gold: immediate offline owner evidence report. NO MT5, no broker orders.
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
set "SCRIPT=%~dp0gold_robot\research\owner_evidence_brief.py"
set "OUTPUT=%CD%\gold_robot\reports_local\owner_decision\QTS_OWNER_VERDICT"
if not exist "%SCRIPT%" exit /b 20
where py.exe >nul 2>&1
if not errorlevel 1 (
  py.exe -3 "%SCRIPT%" --repo "%CD%" --out "%OUTPUT%"
) else (
  where python.exe >nul 2>&1
  if errorlevel 1 (
    echo NO_GO: Python 3 is unavailable. No MT5 or broker action taken.
    exit /b 21
  )
  python.exe "%SCRIPT%" --repo "%CD%" --out "%OUTPUT%"
)
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" exit /b %RC%
if /I not "%QTS_NO_OPEN%"=="1" start "" "%OUTPUT%.html"
exit /b 0
