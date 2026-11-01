@echo off
REM QTS Gold canonical Windows MT5 research launcher.
REM All orders are confined to the native Strategy Tester; LIVE LOCKED.
REM A fresh run directory is pinned and never replaced by an older run.
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"

if /I "%~1"=="v4" goto V4_DIAGNOSE
if /I "%~1"=="champions" goto CHAMPIONS
if not "%~1"=="" goto BAD_OPTION
set "QTS_MODE=ALL_TEN"
set "QTS_STYLE_ARGS="
goto AUTO_RUN

:CHAMPIONS
REM Retest (1) and Sweep/Reclaim (3) are exploratory candidates, not proven winners.
set "QTS_MODE=RETEST_VS_SWEEP"
set "QTS_STYLE_ARGS=-OnlyStyles 1,3"
goto AUTO_RUN

:AUTO_RUN
call :MAKE_RUN_DIR
if errorlevel 1 exit /b 2
set "QTS_NO_OPEN_OPTION="
if /I "%QTS_NO_OPEN%"=="1" set "QTS_NO_OPEN_OPTION=-NoOpen"
echo ==========================================================
echo QTS GOLD - %QTS_MODE% - BROKER REAL-TICK STRATEGY TESTER
echo WMMarkets XAUUSD@ - SIMULATION ONLY - LIVE LOCKED
echo Results are isolated in: %QTS_RUN_DIR%
echo ==========================================================
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0gold_robot\research\RunAutomaticTester.ps1" %QTS_STYLE_ARGS% -OutputDirectory "%QTS_RUN_DIR%" %QTS_NO_OPEN_OPTION%
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto RUN_FINISHED
if exist "%~dp0gold_robot\research\PackTradeEvidence.ps1" (
  "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0gold_robot\research\PackTradeEvidence.ps1" -RunDirectory "%QTS_RUN_DIR%" -NoOpen
  if errorlevel 1 (
    echo Evidence package incomplete for THIS run. Check OPEN_RESULTS.json.
    set "RC=2"
  )
) else (
  echo Evidence packaging tool missing. Research evidence not verified.
  set "RC=2"
)
:RUN_FINISHED
echo.
if not "%RC%"=="0" (
  echo NO-GO: New native research run failed or evidence is incomplete.
  echo Earlier runs were NOT substituted. Read this run's OPEN_RESULTS.json.
) else (
  echo Finished: the new research run and its evidence package are linked.
  echo This result does NOT validate a profitable edge or authorize real money.
)
echo Run directory: %QTS_RUN_DIR%
if /I not "%QTS_NO_PAUSE%"=="1" pause
exit /b %RC%

:V4_DIAGNOSE
call :MAKE_RUN_DIR
if errorlevel 1 exit /b 2
echo ==========================================================
echo QTS GOLD - V4 DECISION DIAGNOSTICS - LAST COMPLETE MONTH
echo Native real-tick Strategy Tester only. LIVE LOCKED.
echo ==========================================================
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$end=(Get-Date -Day 1).Date; $start=$end.AddMonths(-1); & '.\gold_robot\research\RunAutomaticTester.ps1' -OnlyStyles 7 -ResearchVariant ADAPTIVE_V4 -FromDate $start.ToString('yyyy.MM.dd') -ToDate $end.ToString('yyyy.MM.dd') -OutputDirectory $env:QTS_RUN_DIR -NoOpen; exit $LASTEXITCODE"
set "RC=%ERRORLEVEL%"
REM On a failed run, this may still package partial diagnostic evidence from
REM THAT RUN; never silently choose an older run or turn failure into success.
if exist "%QTS_RUN_DIR%\OPEN_RESULTS.json" (
  "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0gold_robot\research\PackTradeEvidence.ps1" -RunDirectory "%QTS_RUN_DIR%" -NoOpen
  if errorlevel 1 if "%RC%"=="0" set "RC=2"
)
echo.
echo V4 diagnostic state: read %QTS_RUN_DIR%\OPEN_RESULTS.html
echo Missing or incomplete native broker evidence means NO-GO.
if /I not "%QTS_NO_PAUSE%"=="1" pause
exit /b %RC%

:MAKE_RUN_DIR
set "QTS_RUN_ID="
for /f %%I in ('powershell.exe -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss_fff"') do set "QTS_RUN_ID=%%I"
if not defined QTS_RUN_ID (
  echo STOP: Cannot create a unique research run identifier.
  exit /b 2
)
set "QTS_RUN_DIR=%~dp0gold_robot\reports_local\auto_runs\%QTS_RUN_ID%"
if exist "%QTS_RUN_DIR%" (
  echo STOP: Refusing to reuse or overwrite a research run.
  exit /b 2
)
exit /b 0

:BAD_OPTION
echo Unsupported mode. Use no argument, "champions", or "v4".
exit /b 2
