@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0QTS_DUAL_THREEWAY.ps1"
if errorlevel 1 (
 echo Three-way QTS research failed closed. Live trading is locked.
 pause
 exit /b 2
)
pause
