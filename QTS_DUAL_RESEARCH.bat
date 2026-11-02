@echo off
REM QTS multi-strategy research: two isolated native MT5 Strategy Tester runs.
REM No connected broker orders, no live authorization, no unattended polling.
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
set "PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%~dp0QTS_DUAL_RESEARCH.ps1" exit /b 20
"%PS%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0QTS_DUAL_RESEARCH.ps1" %*
exit /b %ERRORLEVEL%
