@echo off
REM QTS Gold Robot initial development - DEMO-only installer, never places broker orders.
setlocal EnableExtensions
cd /d "%~dp0"
echo.
echo ======================================================
echo             QTS GOLD ROBOT - INITIAL DEVELOPMENT
ECHO ======================================================
echo Installs the DEMO-only MQL5 robot and compiles it.
echo Existing robot files are backed up and restored on failure.
echo Installation does NOT enable orders or change your MT5 account.
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0mt5_robot\Install_QTS_Gold_Robot.ps1"
set "CODE=%ERRORLEVEL%"
if not "%CODE%"=="0" (
    echo.
    echo INSTALLATION FAILED. The previous EA should be restored.
    echo Review the red compiler error above.
) else (
    echo.
    echo Installation finished. Default is observe-only ^(NO orders^).
    echo For authorized DEMO testing, enable entries in EA Inputs.
)
if not defined QTS_NO_PAUSE pause
exit /b %CODE%
