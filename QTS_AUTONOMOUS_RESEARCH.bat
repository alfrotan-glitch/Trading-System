@echo off
REM QTS Gold - once-only setup of daily evidence learning, with native MT5 RESEARCH ONLY.
REM Never enables connected orders or changes EA strategy/risk settings.
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
echo ==========================================================
echo  QTS GOLD - AUTONOMOUS LOCAL RESEARCH
echo  No live orders. Research journal + future monthly tests.
echo ==========================================================
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0QTS_AUTONOMOUS_RESEARCH.ps1" -Install
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" echo SETUP FAILED: check PowerShell message; no trade permission granted.
if "%RC%"=="0" echo Installed daily local research while your Windows account is signed in.
echo Results: gold_robot\reports_local\autonomous_learning\QTS_AUTONOMOUS_STATUS.json
if /I not "%QTS_NO_PAUSE%"=="1" pause
exit /b %RC%
