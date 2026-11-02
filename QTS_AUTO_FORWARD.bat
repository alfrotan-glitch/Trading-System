@echo off
REM QTS Auto Forward Shadow: one click only; NO inputs, NO connected orders.
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
set "RUNNER=%~dp0gold_robot\research\StartAutoForwardShadow.ps1"
set "POWERSHELL=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%RUNNER%" exit /b 20
if not exist "%POWERSHELL%" exit /b 21
"%POWERSHELL%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%RUNNER%" %*
exit /b %ERRORLEVEL%
