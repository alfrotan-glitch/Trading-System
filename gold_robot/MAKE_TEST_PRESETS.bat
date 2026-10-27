@echo off
REM Builds MT5 Strategy Tester parameter presets; never starts MT5 or sends orders.
setlocal EnableExtensions DisableDelayedExpansion
set "QTS_GOLD_DIR=%~dp0"
cd /d "%QTS_GOLD_DIR%"
echo QTS Gold: creating four read-only Strategy Tester profiles...
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%QTS_GOLD_DIR%research\MakeTesterPresets.ps1"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" echo ERROR: MT5 test profiles were NOT verified.
exit /b %RC%
