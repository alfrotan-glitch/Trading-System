@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo.
echo ========================================================
echo   QTS GOLD MT5 - WMMarkets Setup ^& Broker Readiness
echo ========================================================
echo.
echo STEP 1: Install and compile the CURRENT canonical QTS Gold Robot.
echo No trades will be enabled. The old installed EA is backed up.
echo.
call "%~dp0INSTALL_ROBOT.bat"
if errorlevel 1 (
  echo.
  echo STOP: The robot could not be compiled. Broker audit not started.
  pause
  exit /b 1
)
echo.
echo STEP 2: Install the READ-ONLY broker preflight.
echo.
call "%~dp0CHECK_BROKER.bat"
if errorlevel 1 (
  echo.
  echo The EA may be installed, but the broker audit install FAILED.
  echo Do NOT interpret this as permission to trade.
  pause
  exit /b 2
)
echo.
echo --------------------------------------------------------
echo Installed for observation / Strategy Tester research.
echo Open XAUUSD@ on your exact WMMarkets MT5 terminal.
echo Navigator ^> Expert Advisors ^> Refresh: QTS_Gold_Robot.
echo Navigator ^> Scripts ^> Refresh: QTS_Broker_Preflight.
echo Run ONLY the preflight script for account/symbol diagnostics.
echo Read the guide: docs\WMMarkets_MT5_QUICKSTART_DARI.md
echo LIVE orders remain locked; broker profit NOT validated.
echo --------------------------------------------------------
pause
exit /b 0
