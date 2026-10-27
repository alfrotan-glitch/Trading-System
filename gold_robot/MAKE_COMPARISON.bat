@echo off
REM Compare user-saved MT5 Strategy Tester HTML reports; no account access or orders.
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0research\CompareMT5Reports.ps1"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" echo ERROR: Native MT5 comparison report failed. Original reports unchanged.
exit /b %RC%
