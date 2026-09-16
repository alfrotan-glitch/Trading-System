@echo off
REM One-click launch for QTS Trading System — Windows
REM Double-click this file to open desktop

set QTS_ENV=development
set QTS_MT5_MODE=MOCK
REM For paper/shadow use: set QTS_ENV=paper

python -m qts.desktop.launcher
pause
