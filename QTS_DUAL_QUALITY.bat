@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0QTS_DUAL_QUALITY.ps1"
if errorlevel 1 (
 echo QTS DUAL QUALITY: FAILED NO-GO. Real money remains locked.
 pause
 exit /b 2
)
echo Research test finished. No real-money trade permission.
pause
