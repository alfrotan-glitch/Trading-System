@echo off
REM Validate MT5 executable bid/ask quote export and run post-stop replay.
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0QTS_FINISH_STOP_TICKS.ps1"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" echo ERROR: quote export or post-stop replay incomplete. No data was invented.
if /I not "%QTS_NO_PAUSE%"=="1" pause
exit /b %RC%
