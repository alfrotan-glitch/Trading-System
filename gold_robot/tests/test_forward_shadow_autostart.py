"""Windows auto-runner safety: static contracts and no operator input prompts.

GitHub Linux jobs cannot attest local MetaEditor, WMMarkets account or EX5.
A fresh native connected DEMO heartbeat is required after launch.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MQL = ROOT / "gold_robot" / "mt5_robot" / "QTS_Gold_Robot.mq5"
PS1 = ROOT / "gold_robot" / "research" / "StartAutoForwardShadow.ps1"
BAT = ROOT / "QTS_AUTO_FORWARD.bat"
MENU = ROOT / "START_HERE.bat"
REFRESH = ROOT / "gold_robot" / "research" / "RefreshAutoForwardShadow.ps1"
REFRESH_BAT = ROOT / "QTS_REFRESH_FORWARD.bat"


def test_one_chart_dual_style_is_disabled_by_default_and_permanently_unarmed():
    source = MQL.read_text("utf-8")
    assert "ForwardShadowObserveBothStyles = false" in source
    assert "bool ForwardShadowDualSafe()" in source
    assert "!EnableDemoOrders && !EnableDemoForwardOrders" in source
    assert 'AccountInfoInteger(ACCOUNT_TRADE_MODE)==ACCOUNT_TRADE_MODE_DEMO' in source
    assert 'StringFind(AccountInfoString(ACCOUNT_SERVER),"WMMarkets")==0' in source
    assert "_Symbol==\"XAUUSD@\" && SignalTimeframe==PERIOD_M15" in source
    assert "if(ForwardShadowObserveBothStyles)" in source
    assert "int s1=CompletedBarSignal(a1);" in source
    assert "int s3=CompletedStructureSignal(a3,level,anchor);" in source
    assert "RecordNativeForwardShadow(s1,a1,QTS_RETEST_LIMIT);" in source
    assert "RecordNativeForwardShadow(s3,a3,QTS_SWEEP_RECLAIM);" in source
    assert "WriteForwardShadowHeartbeat" in source
    # The new dual observer returns before touching the old trade manager.
    tick = source.split("void OnTick()", 1)[1]
    dual = tick.split("if(RealAccountBlocked())", 1)[0]
    assert "ConsiderNewEntry(" not in dual or "No ConsiderNewEntry" in dual
    assert "OrderSend(" not in dual
    assert "trader.Buy" not in dual
    assert "return;" in dual


def test_auto_ps1_refuses_guessing_and_cannot_send_broker_orders():
    source = PS1.read_text("utf-8")
    assert "Read-Host" not in source
    assert "Get-Credential" not in source
    assert "Stop-Process" not in source
    assert "taskkill" not in source.lower()
    assert "AllowLiveTrading=0" in source
    assert "AllowDllImport=0" in source
    assert "EnableDemoOrders=false" in source
    assert "EnableDemoForwardOrders=false" in source
    assert "ForwardShadowObserveBothStyles=true" in source
    assert "EntryStyle=1" in source
    assert "Period=M15" in source
    assert "CANONICAL_COMPILE_NO_GO" in source
    assert "NO_HEALTH_AFTER_STARTUP_NO_GO" in source
    assert "ACTIVE_TERMINAL_WITHOUT_NATIVE_HEALTH_NO_GO" in source or (
        "ACTIVE_TERMINAL_WITHOUT_NATIVE_HEALTH" in source
    )
    assert "NO-GO" not in source or "LOCKED" in source
    for forbidden in ("order_send(", "OrderSend(", "PositionModify(", "OrderDelete("):
        assert forbidden not in source


def test_auto_supervisor_surfaces_child_failures_instead_of_claiming_success():
    source = PS1.read_text("utf-8")
    assert "FORWARD_ANALYSIS_BLOCKED_NO_GO" in source
    assert "FORWARD_WAITING_FOR_NATIVE_SIGNALS" in source
    assert "FORWARD_REPORT_CYCLE_FINISHED_UNVALIDATED" not in source
    assert "observer_exit=$observerCode" in source
    assert "price_path_exit=$pathCode" in source
    assert "observer_reason=$observerReason" in source
    assert "price_path_reason=$pathsReason" in source
    assert "--terminal-path $target.terminal" in source
    assert "--terminal-data-dir (Split-Path -Parent $target.mql)" in source
    assert "INSTALLED_EA_SOURCE_MISMATCH_NO_GO" in source
    assert "Get-FileHash -LiteralPath $installedSource" in source


def test_permanent_no_go_stops_bounded_retries_without_touching_mt5():
    source = PS1.read_text("utf-8")
    assert "$consecutiveNoGo=0" in source
    assert "$consecutiveNoGo+=1" in source
    assert "$consecutiveNoGo -ge 3" in source
    assert "FORWARD_ANALYSIS_STOPPED_NO_GO" in source
    assert "exit 2" in source
    assert "MT5 left untouched" in source
    assert "if($RunOnce -or $consecutiveNoGo -ge 3)" in source
    assert "if(-not $NoAutostart -and -not $autostartRegistered)" in source
    # The auto-registration happens only inside the no-error branch.
    loop = source.split("if($blocked){", 1)[1]
    blocked, healthy = loop.split("}else{", 1)
    assert "QTS_Demo_Shadow" not in blocked
    assert "QTS_Demo_Shadow" in healthy


def test_refresh_helper_only_targets_exact_qts_reporting_script():
    source = REFRESH.read_text("utf-8")
    bat = REFRESH_BAT.read_text("utf-8")
    assert "RefreshAutoForwardShadow.ps1" in bat
    assert "StartAutoForwardShadow.ps1" in source
    assert "[regex]::Escape($supervisor)" in source
    assert 'Stop-Process -Id $processes[0].ProcessId -Force' in source
    assert "$processes.Count -gt 1" in source
    assert "Get-CimInstance Win32_Process" in source
    assert "pull --ff-only origin main" in source
    assert "MAIN_REQUIRED_NO_GO" in source
    assert "STATIC_CHECK_OK_NOT_RUNNING" in source
    assert "REFRESH_REQUESTED_NOT_YET_VERIFIED" in source
    assert "Start-Process -FilePath $launcher" in source
    assert "Stop-Process -Name terminal64" not in source
    assert "taskkill" not in source.lower()
    assert "Read-Host" not in source
    assert "Get-Credential" not in source
    assert "order_send(" not in source
    assert "OrderSend(" not in source


def test_one_click_and_control_panel_do_not_request_manual_chart_or_zip():
    bat = BAT.read_text("utf-8")
    menu = MENU.read_text("utf-8")
    assert "StartAutoForwardShadow.ps1" in bat
    assert "QTS_AUTO_FORWARD.bat" in menu
    assert "start " in menu
    assert "ForwardShadowObserveBothStyles=true" in PS1.read_text("utf-8")
