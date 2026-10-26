@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo.
echo =====================================================
echo  QTS / WMMarkets MT5 - READ-ONLY BROKER PREFLIGHT
echo =====================================================
echo This tool checks XAUUSD@ contract, minimum lot, spread,
echo model risk on USD 200, and broker stop/margin properties.
echo It does NOT place orders or unlock live trading.
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0mt5_robot\Install_Broker_Preflight.ps1"
set "CODE=%ERRORLEVEL%"
if not "%CODE%"=="0" (
  echo.
  echo PREFLIGHT INSTALLATION FAILED. Nothing was allowed to trade.
) else (
  echo.
  echo Open your XAUUSD@ chart in MT5.
  echo In Navigator choose Scripts ^> Refresh ^> QTS_Broker_Preflight.
  echo Drag it to the XAUUSD@ chart and check the Experts log.
  echo Its CSV appears inside MT5 Data Folder ^> MQL5 ^> Files.
)
echo.
pause
exit /b %CODE%
