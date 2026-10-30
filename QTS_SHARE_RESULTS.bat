@echo off
REM QTS GOLD: package local, allowlisted research results for trade-by-trade review.
REM NO BROKER ORDERS. NO LOGINS OR NATIVE MT5 HTML IN ZIP.
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
echo ==========================================================
echo QTS GOLD - COLLECT TRADE-BY-TRADE RESULTS
echo LIVE LOCKED - READ ONLY - NO RE-RUN OF MT5
echo ==========================================================
REM Analyze the already saved adaptive deals first; the ZIP then includes the result.
REM Failure to reconcile is explicitly visible and never silently called success.
if exist "%~dp0gold_robot\research\ExplainAdaptiveRouter.ps1" (
  "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0gold_robot\research\ExplainAdaptiveRouter.ps1" -NoOpen
  if errorlevel 1 echo Adaptive position attribution is incomplete. Evidence ZIP will still expose original deal CSV.
)
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0gold_robot\research\PackTradeEvidence.ps1"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" echo Evidence packaging failed. See the specific error above.
if /I not "%QTS_NO_PAUSE%"=="1" pause
exit /b %RC%
