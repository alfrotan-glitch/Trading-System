"""Contracts for the separate native local-agent fast screen.

This is only a source-level check; it does not emulate MetaTrader optimization.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PS = (ROOT / "QTS_FAST_OPTIMIZE.ps1").read_text(encoding="utf-8")
BAT = (ROOT / "QTS_FAST_OPTIMIZE.bat").read_text(encoding="utf-8")


def test_fast_screen_is_only_nine_m15_plus_one_m1():
    assert "EntryStyle=0||0||1||8||Y" in PS
    assert "'Optimization=1'" in PS
    assert "RunJob $config9 'M1 scalp'" in PS
    assert "Period=M1" in PS or "'Period=M1'" in PS
    assert "OptimizationCriterion=4" in PS


def test_screen_never_unlocks_money_or_conflates_with_forensic_evidence():
    assert "AllowLiveTrading=0" in PS
    assert "UseRemote=0" in PS and "UseCloud=0" in PS
    assert "TesterIgnoreDailyAndPeakStops=false" in PS
    assert "full_trade_forensics_complete=$false" in PS
    assert "profitable_edge_validated=$false" in PS
    assert "SCREENING_ONLY" in PS
    assert "-PrepareOnly -NoOpen" in PS
    assert "QTS_FAST_OPTIMIZE.ps1" in BAT
