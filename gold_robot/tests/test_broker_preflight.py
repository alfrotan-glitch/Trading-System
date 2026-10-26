"""Static QTS preflight regression checks; these do NOT compile MQL5."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MQL = (ROOT / "research/QTS_Broker_Preflight.mq5").read_text(encoding="utf-8")
PS = (ROOT / "mt5_robot/Install_Broker_Preflight.ps1").read_text(encoding="utf-8")
BAT = (ROOT / "CHECK_BROKER.bat").read_text(encoding="utf-8")


def test_preflight_is_readonly_and_symbols_are_pinned():
    assert "void OnStart()" in MQL
    assert 'ExpectedSymbol         = "XAUUSD@"' in MQL
    assert "_Symbol!=ExpectedSymbol" in MQL
    assert 'AccountInfoString(ACCOUNT_CURRENCY)!="USD"' in MQL
    assert 'OrdersSubmitted","0"' in MQL
    for forbidden in (
        "OrderSend(", "OrderSendAsync(", "WebRequest(", "trade.Buy(",
        "trade.Sell(", "PositionOpen(", "OrderDelete(", "OrderModify(",
    ):
        assert forbidden not in MQL


def test_preflight_checks_limit_expiry_stops_volume_and_spread():
    for expected in (
        "SYMBOL_VOLUME_MIN", "SYMBOL_VOLUME_STEP",
        "SYMBOL_TRADE_STOPS_LEVEL", "SYMBOL_TRADE_FREEZE_LEVEL",
        "SYMBOL_ORDER_LIMIT", "SYMBOL_ORDER_SL", "SYMBOL_ORDER_TP",
        "SYMBOL_EXPIRATION_SPECIFIED", "MaxSpreadPoints",
        "OrderCalcProfit(", "OrderCalcMargin(", "MaxTickAgeSeconds",
        "BLOCKED_MIN_LOT_EXCEEDS_MODELED_RISK_OR_MARGIN",
        "ActualCommissionVerified", "StrategyProfitableVerified",
    ):
        assert expected in MQL


def test_preflight_default_risk_is_conservative_example_not_trade_authority():
    assert "ModelCapitalUsd         = 200.0;" in MQL
    assert "ModelRiskPercent        = 0.50;" in MQL
    assert "ExampleStopPriceGap     = 4.0;" in MQL
    assert "ModelRiskPercent>1.0" in MQL
    assert "worst>risk_budget" in MQL
    assert "ENGINEERING_PRECHECK_OK_NOT_TRADE_PERMISSION" in MQL


def test_installer_never_invokes_terminal_trade_calls_and_requires_clean_compile():
    assert "Install_Broker_Preflight.ps1" in BAT
    assert "Get-FileHash" in PS
    assert "Start-Process -FilePath $editor" in PS
    assert 'if($summaries.Count -ne 1)' in PS
    assert "Groups[1].Value -ne 0" in PS
    assert "Groups[2].Value -ne 0" in PS
    assert "Remove-Item -LiteralPath $binary -Force" in PS
    assert "$item.Length -lt 1000" in PS
    assert "if(-not $done)" in PS
    assert "Copy-Item -LiteralPath $priorBinary" in PS
    for forbidden in ("OrderSend(", "order_send(", "Set-ExecutionPolicy -Scope", "ACCOUNT_PASSWORD"):
        assert forbidden not in PS
