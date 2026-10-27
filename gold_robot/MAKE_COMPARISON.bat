@echo off
REM Compare user-saved MT5 Strategy Tester HTML reports; no account access or orders.
setlocal EnableExtensions DisableDelayedExpansion
set "QTS_GOLD_DIR=%~dp0"
cd /d "%QTS_GOLD_DIR%"
set "QTS_NO_OPEN_SWITCH="
if /I "%QTS_NO_OPEN%"=="1" set "QTS_NO_OPEN_SWITCH=-NoOpen"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%QTS_GOLD_DIR%research\CompareMT5Reports.ps1" %QTS_NO_OPEN_SWITCH%
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" echo ERROR: Native MT5 comparison report failed. Original reports unchanged.
exit /b %RC%
