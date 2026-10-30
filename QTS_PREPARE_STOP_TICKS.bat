@echo off
REM Build the no-order MT5 post-SL tick exporter for the latest tested run.
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0QTS_PREPARE_STOP_TICKS.ps1"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" echo ERROR: stop tick exporter was not prepared. Review above error.
if /I not "%QTS_NO_PAUSE%"=="1" pause
exit /b %RC%
